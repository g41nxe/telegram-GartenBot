import sys
import unittest
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.core.event_bus import EventBus
from daemon.adapters.mqtt_client import SimulatedMqttAdapter, ValveStatusReported, DeviceJoinedEvent

class TestMqttClient(unittest.TestCase):
    def test_simulated_client_state_changes(self):
        """Verifies that the SimulatedMqttAdapter updates state and publishes status events."""
        bus = EventBus()
        client = SimulatedMqttAdapter(bus)
        
        status_events = []
        bus.subscribe(ValveStatusReported, lambda e: status_events.append(e))
        
        # Connect client
        self.assertTrue(client.connect())
        self.assertTrue(client.is_connected())
        
        # Initially OFF
        self.assertEqual(client.get_valve_status()["state"], "OFF")
        
        # Open valve
        client.publish("zigbee2mqtt/garden_valve/set", '{"state": "ON"}')
        
        # The state should update to ON
        self.assertEqual(client.get_valve_status()["state"], "ON")
        
        # There should be status events dispatched
        self.assertGreater(len(status_events), 0)
        self.assertEqual(status_events[-1].state, "ON")
        self.assertEqual(status_events[-1].mqtt_name, "garden_valve")
        
        # Close valve
        client.publish("zigbee2mqtt/garden_valve/set", '{"state": "OFF"}')
        self.assertEqual(client.get_valve_status()["state"], "OFF")
        self.assertEqual(status_events[-1].state, "OFF")

    def test_simulated_client_pairing_flow(self):
        """Verifies that publishing a permit_join request triggers a DeviceJoinedEvent."""
        bus = EventBus()
        client = SimulatedMqttAdapter(bus)
        
        joined_events = []
        bus.subscribe(DeviceJoinedEvent, lambda e: joined_events.append(e))
        
        client.connect()
        
        # Trigger pairing
        client.publish("zigbee2mqtt/bridge/request/permit_join", '{"time": 90}')
        
        # Wait a moment for simulated asynchronous device joined trigger
        time.sleep(0.2)
        
        self.assertEqual(len(joined_events), 1)
        self.assertEqual(joined_events[0].ieee_address, "0x00124b0025aa1122")
        client.disconnect()

    def test_simulated_client_pairing_flow_formats(self):
        """Verifies that SimulatedMqttAdapter handles various permit_join payload formats."""
        import json
        for payload in ['{"time": 90}', '{"value": true}', '"90"', '90']:
            bus = EventBus()
            client = SimulatedMqttAdapter(bus)
            
            joined_events = []
            bus.subscribe(DeviceJoinedEvent, lambda e: joined_events.append(e))
            
            client.connect()
            client.publish("zigbee2mqtt/bridge/request/permit_join", payload)
            
            time.sleep(0.2)
            self.assertEqual(len(joined_events), 1, f"Failed for format: {payload}")
            client.disconnect()

    def test_simulated_client_configuration_and_get_ignored(self):
        """Verifies that SimulatedMqttAdapter handles safety timeout and get requests without raising exceptions."""
        bus = EventBus()
        client = SimulatedMqttAdapter(bus)
        client.connect()
        
        # Should return True and not crash
        self.assertTrue(client.publish("zigbee2mqtt/garden_valve/set", '{"manual_default_settings": {"fail_safe": 30}}'))
        self.assertTrue(client.publish("zigbee2mqtt/garden_valve/get", '{"state": ""}'))
        
        client.disconnect()

from unittest.mock import patch
import unittest

from daemon.adapters.mqtt_client import HAS_PAHO

@unittest.skipIf(not HAS_PAHO, "paho-mqtt nicht installiert")
class TestPahoMqttClient(unittest.TestCase):
    def setUp(self):
        from daemon.core.event_bus import EventBus
        from daemon.adapters.mqtt_client import PahoMqttAdapter
        self.bus = EventBus()
        self.adapter = PahoMqttAdapter(self.bus)
        
    @patch("daemon.adapters.mqtt_client.mqtt.Client")
    def test_connect_subscribe_publish(self, mock_mqtt):
        from unittest.mock import MagicMock
        mock_instance = MagicMock()
        mock_mqtt.return_value = mock_instance
        
        self.adapter.connect()
        mock_instance.connect_async.assert_called_once()
        mock_instance.loop_start.assert_called_once()
        
        self.adapter._on_connect(mock_instance, None, None, 0)
        self.assertTrue(self.adapter.is_connected())
        
        # Wildcard-Subscription statt spezifischem MQTT_VALVE_TOPIC (seit Multi-Ventil-Fix)
        from daemon import config
        mock_instance.subscribe.assert_any_call("zigbee2mqtt/+")
        mock_instance.publish.assert_any_call(f"{config.MQTT_VALVE_TOPIC}/get", '{"state": ""}', retain=False)
        
        self.adapter.publish("test/topic", "test")
        mock_instance.publish.assert_any_call("test/topic", "test", retain=False)
        
    def test_on_message_routing(self):
        from unittest.mock import MagicMock
        import json
        from daemon import config
        mock_handler = MagicMock()
        self.bus.subscribe(ValveStatusReported, mock_handler)
        
        class MockMsg:
            def __init__(self, topic, payload):
                self.topic = topic
                self.payload = payload
                
        msg = MockMsg(config.MQTT_VALVE_TOPIC, json.dumps({
            "state": "ON", "flow_rate": 5.5, "battery": 80, "linkquality": 100, "valve_abnormal_state": "normal"
        }).encode())
        
        self.adapter._on_message(None, None, msg)
        
        mock_handler.assert_called_once()
        event = mock_handler.call_args[0][0]
        self.assertEqual(event.mqtt_name, "garden_valve")
        self.assertEqual(event.state, "ON")
        self.assertEqual(event.flow_rate, 5.5)
        self.assertEqual(event.battery, 80)
        
    def test_on_message_reads_actual_irrigation_amount(self):
        """_on_message liest actual_irrigation_amount + schedule_status, NICHT real_time_irrigation_volume (ADR 0007)."""
        from unittest.mock import MagicMock
        import json
        from daemon import config
        mock_handler = MagicMock()
        self.bus.subscribe(ValveStatusReported, mock_handler)

        class MockMsg:
            def __init__(self, topic, payload):
                self.topic = topic
                self.payload = payload

        msg = MockMsg(config.MQTT_VALVE_TOPIC, json.dumps({
            "state": "ON", "battery": 95, "linkquality": 120,
            "real_time_irrigation_volume": 140,  # kumulativ — darf NICHT als Guss-Volumen genutzt werden
            "irrigation_schedule_status": {"schedule_status": "running", "actual_irrigation_amount": 4.7}
        }).encode())

        self.adapter._on_message(None, None, msg)

        event = mock_handler.call_args[0][0]
        self.assertAlmostEqual(event.irrigation_volume, 4.7, places=2)
        self.assertEqual(event.schedule_status, "running")

    def test_on_message_missing_actual_amount_is_zero(self):
        """Ohne irrigation_schedule_status ist irrigation_volume 0 und schedule_status None."""
        from unittest.mock import MagicMock
        import json
        from daemon import config
        mock_handler = MagicMock()
        self.bus.subscribe(ValveStatusReported, mock_handler)

        class MockMsg:
            def __init__(self, topic, payload):
                self.topic = topic
                self.payload = payload

        msg = MockMsg(config.MQTT_VALVE_TOPIC, json.dumps({
            "state": "OFF", "battery": 95, "linkquality": 120,
            "real_time_irrigation_volume": 140
        }).encode())

        self.adapter._on_message(None, None, msg)

        event = mock_handler.call_args[0][0]
        self.assertEqual(event.irrigation_volume, 0.0)
        self.assertIsNone(event.schedule_status)

    def test_on_message_device_joined(self):
        from unittest.mock import MagicMock
        import json
        mock_handler = MagicMock()
        self.bus.subscribe(DeviceJoinedEvent, mock_handler)
        
        class MockMsg:
            def __init__(self, topic, payload):
                self.topic = topic
                self.payload = payload
                
        msg = MockMsg("zigbee2mqtt/bridge/event", json.dumps({
            "type": "device_joined", "data": {"ieee_address": "0x123"}
        }).encode())
        
        self.adapter._on_message(None, None, msg)
        
        mock_handler.assert_called_once()
        event = mock_handler.call_args[0][0]
        self.assertEqual(event.ieee_address, "0x123")

class TestPahoOnMessageRouting(unittest.TestCase):
    """Testet PahoMqttAdapter._on_message direkt — kein echter Broker oder paho-Verbindung nötig."""

    def setUp(self):
        from daemon.core.event_bus import EventBus
        from daemon.adapters.mqtt_client import PahoMqttAdapter
        self.bus = EventBus()
        self.adapter = PahoMqttAdapter(self.bus)

    def _mock_msg(self, topic: str, payload: dict):
        import json

        class _Msg:
            pass

        m = _Msg()
        m.topic = topic
        m.payload = json.dumps(payload).encode()
        return m

    def test_secondary_valve_fires_valve_status_reported(self):
        """ValveStatusReported muss für jedes zigbee2mqtt-Gerät feuern, nicht nur MQTT_VALVE_TOPIC.

        Reproduziert: valve_ffff zeigt 🔴 obwohl LQI 212, weil _on_message den Topic-Check
        `== config.MQTT_VALVE_TOPIC` verwendet → Nachrichten von Zweit-Ventilen verworfen →
        DB-Eintrag bleibt last_update=NULL → Ampel Rot.
        """
        from unittest.mock import MagicMock
        handler = MagicMock()
        self.bus.subscribe(ValveStatusReported, handler)

        msg = self._mock_msg("zigbee2mqtt/valve_ffff", {
            "state": "OFF", "battery": 100, "linkquality": 212,
            "valve_abnormal_state": "normal", "flow_rate": 0.0,
        })
        self.adapter._on_message(None, None, msg)

        handler.assert_called_once()
        event = handler.call_args[0][0]
        self.assertEqual(event.mqtt_name, "valve_ffff")
        self.assertEqual(event.linkquality, 212)
        self.assertEqual(event.battery, 100)

    def test_primary_valve_still_fires(self):
        """Primär-Ventil (MQTT_VALVE_TOPIC) darf nach der Änderung weiter ValveStatusReported liefern."""
        from unittest.mock import MagicMock
        from daemon import config
        handler = MagicMock()
        self.bus.subscribe(ValveStatusReported, handler)

        msg = self._mock_msg(config.MQTT_VALVE_TOPIC, {
            "state": "ON", "battery": 90, "linkquality": 180,
            "valve_abnormal_state": "normal", "flow_rate": 5.0,
        })
        self.adapter._on_message(None, None, msg)

        handler.assert_called_once()
        event = handler.call_args[0][0]
        self.assertEqual(event.mqtt_name, config.MQTT_VALVE_TOPIC.split("/")[-1])

    def test_bridge_health_does_not_fire_valve_status(self):
        """zigbee2mqtt/bridge/... Nachrichten dürfen kein ValveStatusReported auslösen."""
        from unittest.mock import MagicMock
        handler = MagicMock()
        self.bus.subscribe(ValveStatusReported, handler)

        msg = self._mock_msg("zigbee2mqtt/bridge/health", {
            "response_time": 1234, "devices": {}
        })
        self.adapter._on_message(None, None, msg)

        handler.assert_not_called()


if __name__ == "__main__":
    unittest.main()
