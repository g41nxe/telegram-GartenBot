import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.core.event_bus import EventBus
from daemon.core.valve_events import DeviceJoinedEvent
from daemon.adapters.mqtt_client import SimulatedMqttAdapter
import daemon.adapters.valve_pairing as pairing_module
import daemon.adapters.database as db


def _make_bus_and_client():
    bus = EventBus()
    client = SimulatedMqttAdapter(bus)
    client.connect()
    return bus, client


def _wait_for_pairing_done(timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pairing_module._pairing_active:
            return True
        time.sleep(0.05)
    return False


class TestPairing(unittest.TestCase):

    def setUp(self):
        pairing_module._pairing_active = False
        self.bus, self.client = _make_bus_and_client()
        pairing_module._global_bus = self.bus
        pairing_module.mqtt_client.client_instance = self.client

        self.db_path = Path(tempfile.mktemp(suffix=".db"))
        self._db_patcher = patch.object(db, "DB_PATH", self.db_path)
        self._db_patcher.start()
        db.init_db()

    def tearDown(self):
        self.client.disconnect()
        pairing_module._pairing_active = False
        self._db_patcher.stop()
        import gc; gc.collect()
        try:
            self.db_path.unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_successful_pairing_completes_and_resets_state(self):
        """start_pairing() returns True and _pairing_active resets to False after DeviceJoinedEvent."""
        notifications = []

        result = pairing_module.start_pairing(
            chat_id=1,
            notify_fn=lambda cid, txt: notifications.append(txt),
            wish_name="Rasen"
        )
        self.assertTrue(result, "start_pairing() should return True on first call")

        self.assertTrue(_wait_for_pairing_done(), "Pairing should complete within timeout")
        self.assertFalse(pairing_module._pairing_active)
        success_msg = any("erfolgreich" in n.lower() or "✅" in n for n in notifications)
        self.assertTrue(success_msg, f"Expected success notification, got: {notifications}")

    def test_pairing_registers_valve_in_database(self):
        """Nach erfolgreichem Koppeln wird das Ventil mit wish_name und mqtt_name in der DB gespeichert."""
        pairing_module.start_pairing(
            chat_id=1,
            notify_fn=lambda cid, txt: None,
            wish_name="Hochbeet"
        )
        self.assertTrue(_wait_for_pairing_done())

        valves = db.get_all_valves()
        # Default-Ventil (id=1) + neues Ventil
        new_valve = next((v for v in valves if v["wish_name"] == "Hochbeet"), None)
        self.assertIsNotNone(new_valve, "Neues Ventil muss nach Kopplung in DB eingetragen sein")
        # mqtt_name ist valve_<letzte 4 IEEE-Stellen> von "0x00124b0025aa1122"
        self.assertEqual(new_valve["mqtt_name"], "valve_1122")

    def test_reentry_guard_prevents_concurrent_pairing(self):
        """Calling start_pairing() while already active returns False immediately."""
        pairing_module._pairing_active = True
        result = pairing_module.start_pairing(
            chat_id=1,
            notify_fn=lambda cid, txt: None,
            wish_name="Test"
        )
        self.assertFalse(result, "Second concurrent start_pairing() should return False")

    def test_listener_unsubscribed_after_pairing(self):
        """DeviceJoinedEvent listener is removed from bus after pairing finishes."""
        initial_count = len(self.bus._listeners.get(DeviceJoinedEvent, []))

        pairing_module.start_pairing(
            chat_id=1,
            notify_fn=lambda cid, txt: None,
            wish_name="Gewächshaus"
        )
        self.assertTrue(_wait_for_pairing_done())

        final_count = len(self.bus._listeners.get(DeviceJoinedEvent, []))
        self.assertEqual(
            final_count, initial_count,
            "Listener count should return to baseline after pairing"
        )


if __name__ == "__main__":
    unittest.main()
