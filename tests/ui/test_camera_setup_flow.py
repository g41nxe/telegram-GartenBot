"""Ende-zu-Ende-Regression der Kamera-Wizards (Ticket cy1).

Treibt Kamera-Kopplung (Name → Intervall → Auflösung → Qualität → start_pairing) und
Kamera-Einstellungen (Intervall → update_camera_settings) durch die echten Dispatcher.
Paritäts-Anker für die CameraPair-/CameraSettingsAssistent-Migration: grün VOR und NACH.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.ui.telegram_ui import _process_message, _process_callback_query, wizard_states
import daemon.adapters.camera_pairing  # noqa: F401  (sicherstellen, dass das Submodul importiert ist)


class TestCameraPairFlow(unittest.TestCase):
    CHAT = 500

    def setUp(self):
        wizard_states.clear()
        self.tc = patch("daemon.ui.telegram_ui.telegram_client").start()
        self.db = patch("daemon.ui.telegram_ui.database").start()
        patch("daemon.adapters.camera_pairing.is_pairing_active", return_value=False).start()
        self.start_pairing = patch("daemon.adapters.camera_pairing.start_pairing").start()
        self.addCleanup(patch.stopall)
        self.tc.send_message_id.return_value = 500
        self.cp = self  # Alias für Assertions unten (self.cp.start_pairing)

    def tearDown(self):
        wizard_states.clear()

    def _cb(self, data, msg_id=500):
        return {"id": "cb1", "data": data, "message": {"chat": {"id": self.CHAT}, "message_id": msg_id}}

    def _msg(self, text):
        return {"chat": {"id": self.CHAT}, "text": text, "message_id": 1}

    def test_full_pairing_flow(self):
        _process_callback_query(self._cb("camsetup_start", msg_id=10))
        _process_message(self._msg("Terrasse-Cam"))       # Name
        _process_message(self._msg("15"))                 # Intervall (min)
        _process_callback_query(self._cb("camsetup_res_XGA"))
        _process_callback_query(self._cb("camsetup_qual_high"))
        self.cp.start_pairing.assert_called_once()
        kwargs = self.cp.start_pairing.call_args.kwargs
        self.assertEqual(kwargs.get("sleep_seconds"), 900)
        self.assertEqual(kwargs.get("resolution"), "XGA")
        self.assertEqual(kwargs.get("quality"), 10)        # high → 10
        # wish_name als Positionsargument
        self.assertIn("Terrasse-Cam", self.cp.start_pairing.call_args.args)
        self.assertNotIn(self.CHAT, wizard_states)

    def test_invalid_name_stays(self):
        _process_callback_query(self._cb("camsetup_start", msg_id=10))
        _process_message(self._msg("hat leerzeichen"))    # ungültig
        self.assertIn(self.CHAT, wizard_states)
        self.cp.start_pairing.assert_not_called()

    def test_invalid_interval_stays(self):
        _process_callback_query(self._cb("camsetup_start", msg_id=10))
        _process_message(self._msg("Cam"))
        _process_message(self._msg("9999"))               # > 1440
        self.assertIn(self.CHAT, wizard_states)
        self.cp.start_pairing.assert_not_called()

    def test_quality_medium_and_low_mapping(self):
        for qual, expected in (("medium", 25), ("low", 40)):
            self.start_pairing.reset_mock()
            wizard_states.clear()
            _process_callback_query(self._cb("camsetup_start", msg_id=10))
            _process_message(self._msg("Cam"))
            _process_message(self._msg("15"))
            _process_callback_query(self._cb("camsetup_res_UXGA"))
            _process_callback_query(self._cb(f"camsetup_qual_{qual}"))
            self.assertEqual(self.start_pairing.call_args.kwargs.get("quality"), expected,
                             f"Qualität {qual}")


class TestCameraSettingsFlow(unittest.TestCase):
    CHAT = 501

    def setUp(self):
        wizard_states.clear()
        self.tc = patch("daemon.ui.telegram_ui.telegram_client").start()
        self.db = patch("daemon.ui.telegram_ui.database").start()
        self.addCleanup(patch.stopall)
        self.tc.send_message_id.return_value = 500
        self._cam = {"mac_address": "AA:BB:CC", "wish_name": "Terrasse", "resolution": "XGA", "quality": 25}
        self.db.get_all_cameras.return_value = [self._cam]
        self.db.get_camera.return_value = self._cam

    def tearDown(self):
        wizard_states.clear()

    def _cb(self, data, msg_id=500):
        return {"id": "cb1", "data": data, "message": {"chat": {"id": self.CHAT}, "message_id": msg_id}}

    def _msg(self, text):
        return {"chat": {"id": self.CHAT}, "text": text, "message_id": 1}

    def test_single_camera_interval_update(self):
        _process_callback_query(self._cb("camsetup_settings", msg_id=10))
        _process_message(self._msg("30"))
        self.db.update_camera_settings.assert_called_once()
        kwargs = self.db.update_camera_settings.call_args.kwargs
        self.assertEqual(kwargs.get("sleep_seconds"), 1800)
        self.assertNotIn(self.CHAT, wizard_states)

    def test_invalid_interval_stays(self):
        _process_callback_query(self._cb("camsetup_settings", msg_id=10))
        _process_message(self._msg("abc"))
        self.assertIn(self.CHAT, wizard_states)
        self.db.update_camera_settings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
