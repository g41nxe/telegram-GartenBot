import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from daemon.main import _check_ota_notify

NOTIFY_FILE = Path("/tmp/garden-ota-notify")


def _cleanup():
    NOTIFY_FILE.unlink(missing_ok=True)


class TestCheckOtaNotify(unittest.TestCase):

    def setUp(self):
        _cleanup()

    def tearDown(self):
        _cleanup()

    @patch("daemon.ui.telegram_client.send_message")
    def test_sendet_erfolg_nachricht(self, mock_send):
        NOTIFY_FILE.write_text("12345\nsuccess\nv1.2.3\n")
        _check_ota_notify()

        mock_send.assert_called_once()
        chat_id, text = mock_send.call_args[0]
        self.assertEqual(chat_id, 12345)
        self.assertIn("erfolgreich", text.lower())
        self.assertIn("v1.2.3", text)
        self.assertFalse(NOTIFY_FILE.exists())

    @patch("daemon.ui.telegram_client.send_message")
    def test_sendet_rollback_nachricht(self, mock_send):
        NOTIFY_FILE.write_text("99999\nfailed\nv1.0.0\n")
        _check_ota_notify()

        chat_id, text = mock_send.call_args[0]
        self.assertEqual(chat_id, 99999)
        self.assertIn("fehlgeschlagen", text.lower())
        self.assertIn("v1.0.0", text)
        self.assertFalse(NOTIFY_FILE.exists())

    @patch("daemon.ui.telegram_client.send_message")
    def test_keine_nachricht_ohne_datei(self, mock_send):
        _check_ota_notify()
        mock_send.assert_not_called()

    @patch("daemon.ui.telegram_client.send_message")
    def test_datei_wird_auch_bei_unbekanntem_status_geloescht(self, mock_send):
        NOTIFY_FILE.write_text("12345\nunknown\n?\n")
        _check_ota_notify()
        self.assertFalse(NOTIFY_FILE.exists())


if __name__ == "__main__":
    unittest.main()
