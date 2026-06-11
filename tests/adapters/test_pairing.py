import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.core.event_bus import EventBus
from daemon.core.valve_events import DeviceJoinedEvent
from daemon.adapters.mqtt_client import SimulatedMqttAdapter
import daemon.adapters.pairing as pairing_module


def _make_bus_and_client():
    bus = EventBus()
    client = SimulatedMqttAdapter(bus)
    client.connect()
    return bus, client


class TestPairing(unittest.TestCase):

    def setUp(self):
        # Reset module-level pairing state between tests
        pairing_module._pairing_active = False
        # Wire pairing module to a fresh bus/client
        self.bus, self.client = _make_bus_and_client()
        pairing_module._global_bus = self.bus
        pairing_module.mqtt_client.client_instance = self.client

    def tearDown(self):
        self.client.disconnect()
        pairing_module._pairing_active = False

    def test_successful_pairing_completes_and_resets_state(self):
        """start_pairing() returns True and _pairing_active resets to False after DeviceJoinedEvent."""
        notifications = []

        result = pairing_module.start_pairing(
            chat_id=1,
            notify_fn=lambda cid, txt: notifications.append(txt)
        )
        self.assertTrue(result, "start_pairing() should return True on first call")

        # SimulatedMqttAdapter fires DeviceJoinedEvent after ~100ms when permit_join is sent
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if not pairing_module._pairing_active:
                break
            time.sleep(0.05)

        self.assertFalse(pairing_module._pairing_active, "Pairing should be inactive after completion")
        success_msg = any("erfolgreich" in n.lower() or "✅" in n for n in notifications)
        self.assertTrue(success_msg, f"Expected success notification, got: {notifications}")

    def test_reentry_guard_prevents_concurrent_pairing(self):
        """Calling start_pairing() while already active returns False immediately."""
        pairing_module._pairing_active = True
        result = pairing_module.start_pairing(
            chat_id=1,
            notify_fn=lambda cid, txt: None
        )
        self.assertFalse(result, "Second concurrent start_pairing() should return False")

    def test_listener_unsubscribed_after_pairing(self):
        """DeviceJoinedEvent listener is removed from bus after pairing finishes."""
        initial_count = len(self.bus._listeners.get(DeviceJoinedEvent, []))

        pairing_module.start_pairing(
            chat_id=1,
            notify_fn=lambda cid, txt: None
        )

        deadline = time.time() + 5.0
        while time.time() < deadline:
            if not pairing_module._pairing_active:
                break
            time.sleep(0.05)

        final_count = len(self.bus._listeners.get(DeviceJoinedEvent, []))
        self.assertEqual(
            final_count, initial_count,
            "Listener count should return to baseline after pairing — unsubscribe not called"
        )


if __name__ == "__main__":
    unittest.main()
