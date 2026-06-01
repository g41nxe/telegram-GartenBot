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
        client.publish("zigbee2mqtt/bridge/request/permit_join", '{"value": true}')
        
        # Wait a moment for simulated asynchronous device joined trigger
        time.sleep(0.2)
        
        self.assertEqual(len(joined_events), 1)
        self.assertEqual(joined_events[0].ieee_address, "0x00124b0025aa1122")

if __name__ == "__main__":
    unittest.main()
