import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.core.event_bus import EventBus
from daemon.core.camera_events import CameraRegistered
import daemon.adapters.camera_pairing as camera_pairing_module
import daemon.adapters.database as db


def _wait_for(condition, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return False


class TestCameraPairing(unittest.TestCase):

    def setUp(self):
        camera_pairing_module._pairing_active = False

        # DB-Patcher zuerst, damit init_pairing in die korrekte temp-DB schreibt
        self.db_path = Path(tempfile.mktemp(suffix=".db"))
        self._db_patcher = patch.object(db, "DB_PATH", self.db_path)
        self._db_patcher.start()
        db.init_db()

        self.bus = EventBus()
        camera_pairing_module.init_pairing(self.bus)

    def tearDown(self):
        camera_pairing_module._pairing_active = False
        self._db_patcher.stop()
        try:
            self.db_path.unlink(missing_ok=True)
        except PermissionError:
            pass

    def _trigger_registered(self, mac="AA:BB:CC:DD:EE:FF", wish_name="Garten"):
        """Simuliert das Ankommen der Kamera: erst in DB eintragen, dann Event feuern.
        Aufrufer muss sicherstellen dass der Worker-Thread bereits subscribed hat."""
        db.add_camera(mac, wish_name)
        self.bus.publish(CameraRegistered(mac_address=mac, wish_name=wish_name))

    def _start_and_trigger(self, sleep_seconds=None, mac="AA:BB:CC:DD:EE:FF", wish_name="Garten"):
        kwargs = dict(chat_id=1, notify_fn=lambda cid, txt: None, wish_name=wish_name)
        if sleep_seconds is not None:
            kwargs["sleep_seconds"] = sleep_seconds
        camera_pairing_module.start_pairing(**kwargs)
        # Windows: Thread-Start + 3× set_metadata braucht bis zu 200ms
        time.sleep(0.4)
        self._trigger_registered(mac=mac, wish_name=wish_name)

    def test_sleep_seconds_saved_after_successful_pairing(self):
        """start_pairing mit sleep_seconds=30 speichert den Wert in der DB nach erfolgreicher Kopplung."""
        self._start_and_trigger(sleep_seconds=30)

        self.assertTrue(_wait_for(lambda: not camera_pairing_module._pairing_active))

        cam = db.get_camera("AA:BB:CC:DD:EE:FF")
        self.assertIsNotNone(cam)
        self.assertEqual(cam["sleep_duration_seconds"], 30)

    def test_default_sleep_seconds_when_not_specified(self):
        """start_pairing ohne sleep_seconds behält den DB-Default (900s)."""
        self._start_and_trigger()

        self.assertTrue(_wait_for(lambda: not camera_pairing_module._pairing_active))

        cam = db.get_camera("AA:BB:CC:DD:EE:FF")
        self.assertEqual(cam["sleep_duration_seconds"], 900)

    def test_reentry_guard_prevents_concurrent_pairing(self):
        """Zweiter Aufruf während laufender Kopplung gibt False zurück."""
        camera_pairing_module._pairing_active = True
        result = camera_pairing_module.start_pairing(
            chat_id=1,
            notify_fn=lambda cid, txt: None,
            wish_name="Garten",
            sleep_seconds=60,
        )
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
