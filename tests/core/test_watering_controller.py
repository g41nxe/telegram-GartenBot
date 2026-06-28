import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from unittest.mock import patch

from daemon.core.event_bus import EventBus
from daemon.adapters.mqtt_client import SimulatedMqttAdapter
from daemon.core.valve_events import (
    ValveStatusReported,
    UnexpectedValveOpened,
    UnexpectedValveResolved,
)
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

    def test_get_active_valve_names_reflects_running_cycles(self):
        """get_active_valve_names liefert die mqtt_names aller laufenden Güsse (fürs Stopp-Menü)."""
        self.assertEqual(self.controller.get_active_valve_names(), [])

        self.controller.start_watering(10, 5, "manual", mqtt_name="garden_valve")
        self.controller.start_watering(10, 5, "manual", mqtt_name="beet_valve")
        self.assertCountEqual(
            self.controller.get_active_valve_names(), ["garden_valve", "beet_valve"]
        )

        self.controller.stop_watering("garden_valve")
        self.assertEqual(self.controller.get_active_valve_names(), ["beet_valve"])

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

    # --- Guss-Volumen aus actual_irrigation_amount der laufenden Session (ADR 0007) ---

    def _running(self, vol, mqtt_name="garden_valve"):
        """Geraete-Report einer laufenden Session (schedule_status='running')."""
        from daemon.core.valve_events import ValveStatusReported
        self.bus.publish(ValveStatusReported(
            mqtt_name, "ON", 0.0, 95, 120, irrigation_volume=vol, schedule_status="running"))

    def test_session_volume_counts_up_from_actual_amount(self):
        """Guss-Volumen folgt actual_irrigation_amount der laufenden Session (kein Baseline-Abzug)."""
        self.controller.start_watering(
            duration_minutes=10, target_volume_liters=20, source="manual",
            mqtt_name="garden_valve", valve_topic="zigbee2mqtt/garden_valve"
        )
        self._running(0.0)
        self.assertAlmostEqual(self.controller.get_active_volume("garden_valve"), 0.0, places=2)
        self._running(2.0)
        self.assertAlmostEqual(self.controller.get_active_volume("garden_valve"), 2.0, places=2)
        self._running(8.0)
        self.assertAlmostEqual(self.controller.get_active_volume("garden_valve"), 8.0, places=2)

    def test_volume_limit_triggers_on_session_amount(self):
        """Volumenlimit loest aus, sobald actual_irrigation_amount das Ziel erreicht."""
        events = []
        self.bus.subscribe(WateringCycleCompleted, lambda e: events.append(e))

        self.controller.start_watering(
            duration_minutes=10, target_volume_liters=10, source="manual",
            mqtt_name="garden_valve", valve_topic="zigbee2mqtt/garden_valve"
        )
        self._running(8.0)
        self.assertIsNotNone(self.controller.get_active_cycle("garden_valve"))

        self._running(10.0)  # erreicht das Ziel
        self.assertIsNone(self.controller.get_active_cycle("garden_valve"))
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0].volume_run, 10.0, places=2)
        self.assertIn("Volumenlimit", events[0].details)

    def test_non_running_reports_are_ignored(self):
        """Reports mit schedule_status != 'running' (lagged end/start) werden nicht gezaehlt."""
        from daemon.core.valve_events import ValveStatusReported

        self.controller.start_watering(
            duration_minutes=10, target_volume_liters=10, source="manual",
            mqtt_name="garden_valve", valve_topic="zigbee2mqtt/garden_valve"
        )
        # Verspaeteter 'end'-Report der Vorsession mit hoher Menge -> ignorieren
        self.bus.publish(ValveStatusReported("garden_valve", "ON", 0.0, 95, 120,
                                             irrigation_volume=40.0, schedule_status="end"))
        self.assertAlmostEqual(self.controller.get_active_volume("garden_valve"), 0.0, places=2)
        self.assertIsNotNone(self.controller.get_active_cycle("garden_valve"))

        # 'start'-Report ebenfalls ignorieren
        self.bus.publish(ValveStatusReported("garden_valve", "ON", 0.0, 95, 120,
                                             irrigation_volume=0.0, schedule_status="start"))
        self.assertAlmostEqual(self.controller.get_active_volume("garden_valve"), 0.0, places=2)

    def test_lagged_cumulative_does_not_poison_followup_guss(self):
        """Reproduziert den 2.-Guss-Bug: ein verspaeteter Vorsession-Wert darf den neuen Guss nicht sofort beenden."""
        from daemon.core.valve_events import ValveStatusReported

        self.controller.start_watering(
            duration_minutes=1, target_volume_liters=10, source="schedule",
            mqtt_name="garden_valve", valve_topic="zigbee2mqtt/garden_valve"
        )
        # Direkt nach Start trifft noch ein verspaeteter 'end'-Report der VORigen Session (40 L) ein
        self.bus.publish(ValveStatusReported("garden_valve", "ON", 0.0, 95, 120,
                                             irrigation_volume=40.0, schedule_status="end"))
        self.assertIsNotNone(self.controller.get_active_cycle("garden_valve"),
                             "Verspaeteter Vorsession-Wert darf den Folge-Guss nicht sofort beenden")
        self.assertAlmostEqual(self.controller.get_active_volume("garden_valve"), 0.0, places=2)

        # Neue Session laeuft sauber bei 0 los
        self._running(0.0)
        self._running(3.0)
        self.assertAlmostEqual(self.controller.get_active_volume("garden_valve"), 3.0, places=2)
        self.assertIsNotNone(self.controller.get_active_cycle("garden_valve"))

    def test_monotonic_against_transient_low_report(self):
        """max() schuetzt gegen einen einzelnen zu niedrigen running-Report (Funk-Ausreisser)."""
        self.controller.start_watering(
            duration_minutes=10, target_volume_liters=100, source="manual",
            mqtt_name="garden_valve", valve_topic="zigbee2mqtt/garden_valve"
        )
        self._running(10.0)
        self.assertAlmostEqual(self.controller.get_active_volume("garden_valve"), 10.0, places=2)

        self._running(3.0)  # Ausreisser nach unten -> ignoriert
        self.assertAlmostEqual(self.controller.get_active_volume("garden_valve"), 10.0, places=2)

        self._running(12.0)
        self.assertAlmostEqual(self.controller.get_active_volume("garden_valve"), 12.0, places=2)


class TestUnexpectedValveOpen(unittest.TestCase):
    """Erkennung der Unerwarteten Ventilöffnung (Feature 0029, ADR 0032)."""

    def setUp(self):
        self.bus = EventBus()
        # No-op-publish: präzise Kontrolle über die Event-Sequenz (kein synchroner OFF-Echo).
        self.controller = WateringController(self.bus, lambda t, p: True)
        self.opened = []
        self.resolved = []
        self.bus.subscribe(UnexpectedValveOpened, lambda e: self.opened.append(e))
        self.bus.subscribe(UnexpectedValveResolved, lambda e: self.resolved.append(e))

    def tearDown(self):
        self.controller.stop_watering()  # offene Zyklen + Timer aufräumen

    def _report(self, state, name="garden_valve"):
        self.bus.publish(ValveStatusReported(name, state, 0.0, 95, 120))

    def test_external_open_emits_event_once(self):
        """Echte Flanke OFF→ON ohne aktiven Zyklus → genau ein Ereignis, auch bei Folge-Reports."""
        self._report("OFF")   # bekannter Vorzustand (kein Cold-Start)
        self._report("ON")    # externe Öffnung
        self._report("ON")    # Folge-Report
        self.assertEqual(len(self.opened), 1)
        self.assertEqual(self.opened[0].mqtt_name, "garden_valve")

    def test_get_unexpected_open_valves(self):
        """Liste der aktuell extern offenen Ventile (fürs Stopp-Menü, Bug-Fix)."""
        self.assertEqual(self.controller.get_unexpected_open_valves(), [])
        self._report("OFF", "beet_valve")
        self._report("ON", "beet_valve")          # externe Öffnung
        self.assertIn("beet_valve", self.controller.get_unexpected_open_valves())
        self._report("OFF", "beet_valve")         # wieder zu
        self.assertNotIn("beet_valve", self.controller.get_unexpected_open_valves())

    def test_force_close_publishes_off_to_named_valve(self):
        """force_close schickt OFF gezielt an das genannte Ventil (auch ohne aktiven Zyklus)."""
        from unittest.mock import Mock
        pub = Mock(return_value=True)
        ctrl = WateringController(self.bus, pub)
        ok = ctrl.force_close("beet_valve")
        self.assertTrue(ok)
        pub.assert_called_once_with("zigbee2mqtt/beet_valve/set", '{"state": "OFF"}')

    def test_cold_start_on_does_not_emit(self):
        """Allererster Report ist ON (unbekannter Vorzustand) → kein Ereignis (Doppelfeuer-Schutz)."""
        self._report("ON")
        self.assertEqual(self.opened, [])

    def test_open_with_active_cycle_no_event(self):
        """ON mit aktivem Zyklus (regulärer Guss) → kein Ereignis."""
        self.controller.start_watering(5, 0, "manual", mqtt_name="garden_valve",
                                       valve_topic="zigbee2mqtt/garden_valve")
        self._report("ON")
        self.assertEqual(self.opened, [])

    def test_resolved_on_close(self):
        """Nach einer Episode meldet OFF die Entwarnung."""
        self._report("OFF")
        self._report("ON")
        self.assertEqual(len(self.opened), 1)
        self._report("OFF")
        self.assertEqual(len(self.resolved), 1)
        self.assertEqual(self.resolved[0].mqtt_name, "garden_valve")

    def test_daemon_close_lingering_on_no_false_alarm(self):
        """Daemon schließt (Zyklus weg), Ventil meldet noch kurz ON → kein Fehlalarm, keine Entwarnung."""
        self.controller.start_watering(5, 0, "manual", mqtt_name="garden_valve",
                                       valve_topic="zigbee2mqtt/garden_valve")
        self._report("ON")                          # während des Zyklus (last_state=ON)
        self.controller.stop_watering("garden_valve")  # Zyklus entfernt (No-op-publish, kein Echo)
        self._report("ON")                          # lagged ON nach dem Schließen
        self.assertEqual(self.opened, [])
        self._report("OFF")
        self.assertEqual(self.resolved, [])         # Episode war nie aktiv

    def test_disabled_emits_nothing(self):
        """Bei UNEXPECTED_VALVE_ALERT_ENABLED=False wird nichts veröffentlicht."""
        with patch("daemon.core.watering_controller.config.UNEXPECTED_VALVE_ALERT_ENABLED", False):
            self._report("OFF")
            self._report("ON")
        self.assertEqual(self.opened, [])

    def test_detection_is_per_valve(self):
        """Erkennung läuft unabhängig pro mqtt_name."""
        self._report("OFF", "valve_a")
        self._report("OFF", "valve_b")
        self._report("ON", "valve_a")
        self.assertEqual([e.mqtt_name for e in self.opened], ["valve_a"])

    def test_claimed_valve_suppresses_unexpected_open(self):
        """Ein von der Nebel-Steuerung beanspruchtes Ventil löst keine Fremdöffnung aus (Feature 0032)."""
        self.controller.claim_valve("terrace_mist")
        self._report("OFF", "terrace_mist")
        self._report("ON", "terrace_mist")   # Nebelstoß-Flanke
        self.assertEqual(self.opened, [])

        # Nach Freigabe greift die Erkennung wieder
        self.controller.release_valve("terrace_mist")
        self._report("OFF", "terrace_mist")
        self._report("ON", "terrace_mist")
        self.assertEqual([e.mqtt_name for e in self.opened], ["terrace_mist"])

    def test_guss_takeover_clears_pending_episode(self):
        """Übernimmt der Daemon ein fremd geöffnetes Ventil per Guss, gibt es beim Guss-Ende keine stale Entwarnung."""
        # Fremdöffnung → Episode aktiv
        self._report("OFF")
        self._report("ON")
        self.assertEqual(len(self.opened), 1)

        # Daemon übernimmt das bereits offene Ventil
        self.controller.start_watering(5, 0, "manual", mqtt_name="garden_valve",
                                       valve_topic="zigbee2mqtt/garden_valve")
        # Regulärer Guss endet → Ventil meldet OFF
        self.controller.stop_watering("garden_valve")
        self._report("OFF")
        self.assertEqual(self.resolved, [],
                         "Reguläres Guss-Ende darf keine Fremdöffnungs-Entwarnung auslösen")


if __name__ == "__main__":
    unittest.main()
