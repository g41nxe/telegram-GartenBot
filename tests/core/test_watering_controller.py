import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.core.event_bus import EventBus
from daemon.adapters.mqtt_client import SimulatedMqttAdapter
from daemon.core.watering_controller import (
    WateringController,
    WateringCycleStarted,
    WateringCycleCompleted,
    WateringCycleFailed,
    WateringCycleStopped
)

class TestWateringController(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.client = SimulatedMqttAdapter(self.bus)
        self.controller = WateringController(self.bus, self.client.publish)
        self.assertTrue(self.client.connect())

    def tearDown(self):
        self.client.disconnect()

    def test_start_and_volume_limit_reached(self):
        """Verifies that the controller starts watering and auto-closes when volume limit is reached."""
        events = []
        self.bus.subscribe(WateringCycleStarted, lambda e: events.append(e))
        self.bus.subscribe(WateringCycleCompleted, lambda e: events.append(e))
        
        # Initially OFF
        self.assertEqual(self.client.get_valve_status()["state"], "OFF")
        
        # Start watering: 10 mins, 5 liters, manual source
        success, msg = self.controller.start_watering(duration_minutes=10, target_volume_liters=5, source="manual")
        self.assertTrue(success, f"Failed to start: {msg}")
        self.assertEqual(self.client.get_valve_status()["state"], "ON")
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], WateringCycleStarted)
        
        # Send status update of 5.0 L/min flow rate
        # Let's simulate a status update after 12 seconds: 5.0 L/min * (12/60) = 1.0 Liters
        self.controller._integrate_flow(flow_rate=5.0, elapsed_seconds=12.0)
        self.assertEqual(self.controller.get_active_volume(), 1.0)
        
        # Integrate another 4.0 Liters: 5.0 L/min * (48/60) = 4.0 Liters
        self.controller._integrate_flow(flow_rate=5.0, elapsed_seconds=48.0)
        
        # Now volume limit of 5.0 is reached (1.0 + 4.0 = 5.0)
        # The valve should be closed
        self.assertEqual(self.client.get_valve_status()["state"], "OFF")
        self.assertEqual(len(events), 2)
        self.assertIsInstance(events[1], WateringCycleCompleted)
        self.assertEqual(events[1].volume_run, 5.0)
        self.assertIn("Volumenlimit", events[1].details)

    def test_emergency_shutdown_on_time_limit(self):
        """Verifies that if the time limit expires before the volume is reached, it triggers emergency shutdown."""
        events = []
        self.bus.subscribe(WateringCycleFailed, lambda e: events.append(e))
        
        success, msg = self.controller.start_watering(duration_minutes=10, target_volume_liters=5, source="manual")
        self.assertTrue(success, f"Failed to start: {msg}")
        
        # Simulate some flow (3.0 Liters out of 5.0)
        self.controller._integrate_flow(flow_rate=5.0, elapsed_seconds=36.0)
        self.assertEqual(self.controller.get_active_volume(), 3.0)
        
        # Force expiration of the time-limit callback
        self.controller._time_limit_callback()
        
        # Should close valve and trigger Failure event
        self.assertEqual(self.client.get_valve_status()["state"], "OFF")
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], WateringCycleFailed)
        self.assertEqual(events[0].volume_run, 3.0)
        self.assertIn("Notfall-Abschaltung", events[0].details)

    def test_time_gap_capping(self):
        """Verifies that time gaps between status reports are capped at 60 seconds."""
        success, msg = self.controller.start_watering(duration_minutes=10, target_volume_liters=20, source="manual")
        self.assertTrue(success, f"Failed to start: {msg}")
        
        # Simulate an update with 75 seconds gap
        self.controller._integrate_flow(flow_rate=6.0, elapsed_seconds=75.0)
        
        # Due to capping at 60 seconds: 6.0 L/min * (60/60) = 6.0 Liters
        self.assertEqual(self.controller.get_active_volume(), 6.0)

    def test_double_start_prevention(self):
        """Verifies that starting a cycle when another is active fails."""
        success1, msg1 = self.controller.start_watering(duration_minutes=5, target_volume_liters=0, source="manual")
        self.assertTrue(success1, f"Failed to start 1: {msg1}")

        success2, msg2 = self.controller.start_watering(duration_minutes=5, target_volume_liters=0, source="manual")
        self.assertFalse(success2)
        self.assertIn("bereits", msg2)

    # --- Multi-Ventil-Tests (Schritt 6 / Feature 0006) ---

    def test_start_watering_with_mqtt_name(self):
        """start_watering() akzeptiert mqtt_name und valve_topic; Flow-Integration filtert nach mqtt_name."""
        from daemon.core.valve_events import ValveStatusReported
        events = []
        self.bus.subscribe(WateringCycleCompleted, lambda e: events.append(e))

        success, _ = self.controller.start_watering(
            duration_minutes=10, target_volume_liters=5, source="manual",
            mqtt_name="garden_valve", valve_topic="zigbee2mqtt/garden_valve"
        )
        self.assertTrue(success)

        # Event vom richtigen Ventil → wird integriert
        self.bus.publish(ValveStatusReported("garden_valve", "ON", 5.0, 95, 120))
        self.bus.publish(ValveStatusReported("garden_valve", "ON", 5.0, 95, 120))
        # ... nach ausreichend Zeit sollte das Volumenlimit nicht sofort erreicht sein
        # Wir prüfen nur, dass der Zyklus noch aktiv ist
        self.assertIsNotNone(self.controller.get_active_cycle("garden_valve"))

    def test_flow_integration_ignores_other_valves(self):
        """ValveStatusReported-Events von anderen Ventilen werden für die Flow-Integration ignoriert."""
        from daemon.core.valve_events import ValveStatusReported

        success, _ = self.controller.start_watering(
            duration_minutes=10, target_volume_liters=20, source="manual",
            mqtt_name="garden_valve", valve_topic="zigbee2mqtt/garden_valve"
        )
        self.assertTrue(success)
        initial_volume = self.controller.get_active_volume("garden_valve")

        # Event von anderem Ventil → darf NICHT integriert werden
        self.controller._last_flow_update_time["garden_valve"] = \
            self.controller._last_flow_update_time["garden_valve"] - __import__("datetime").timedelta(seconds=10)
        self.bus.publish(ValveStatusReported("valve_other", "ON", 999.0, 95, 120))

        self.assertAlmostEqual(self.controller.get_active_volume("garden_valve"), initial_volume, places=2,
                               msg="Event vom falschen Ventil darf den Flow nicht verändern")

    def test_parallel_cycles_independent(self):
        """Zwei Ventile können parallel laufen mit unabhängigen Zyklen."""
        from daemon.core.valve_events import ValveStatusReported

        ok1, _ = self.controller.start_watering(
            duration_minutes=10, target_volume_liters=10, source="manual",
            mqtt_name="garden_valve", valve_topic="zigbee2mqtt/garden_valve"
        )
        ok2, _ = self.controller.start_watering(
            duration_minutes=10, target_volume_liters=10, source="manual",
            mqtt_name="valve_1122", valve_topic="zigbee2mqtt/valve_1122"
        )
        self.assertTrue(ok1)
        self.assertTrue(ok2)
        self.assertIsNotNone(self.controller.get_active_cycle("garden_valve"))
        self.assertIsNotNone(self.controller.get_active_cycle("valve_1122"))

        # Jetzt Valve 1 stoppen
        self.controller.stop_watering("garden_valve")
        self.assertIsNone(self.controller.get_active_cycle("garden_valve"))
        self.assertIsNotNone(self.controller.get_active_cycle("valve_1122"),
                             "Valve 2 muss noch laufen nach Stopp von Valve 1")

    def test_stop_all_valves(self):
        """stop_watering() ohne Argument stoppt alle aktiven Zyklen."""
        self.controller.start_watering(
            duration_minutes=10, target_volume_liters=10, source="manual",
            mqtt_name="garden_valve", valve_topic="zigbee2mqtt/garden_valve"
        )
        self.controller.start_watering(
            duration_minutes=10, target_volume_liters=10, source="manual",
            mqtt_name="valve_1122", valve_topic="zigbee2mqtt/valve_1122"
        )
        self.controller.stop_watering()
        self.assertIsNone(self.controller.get_active_cycle("garden_valve"))
        self.assertIsNone(self.controller.get_active_cycle("valve_1122"))

    def test_get_active_cycle_returns_none_without_mqtt_name(self):
        """get_active_cycle() ohne Argument gibt None zurück wenn kein Zyklus läuft."""
        self.assertIsNone(self.controller.get_active_cycle())


if __name__ == "__main__":
    unittest.main()
