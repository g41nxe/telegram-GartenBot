import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.ui.telegram_ui import _process_message, _process_callback_query


def _msg(text, chat_id=100):
    return {"chat": {"id": chat_id}, "text": text}


def _cb(data, chat_id=100, msg_id=1):
    return {"id": "cb1", "data": data, "message": {"chat": {"id": chat_id}, "message_id": msg_id}}


def _markup(call_args):
    return call_args.args[2] if len(call_args.args) > 2 else call_args.kwargs.get("reply_markup")


def _cb_data(markup):
    return [b["callback_data"] for row in markup["inline_keyboard"] for b in row]


class TestPhotoClearCommand(unittest.TestCase):

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_no_camera_sends_hint(self, mock_db, mock_tc):
        """Keine gekoppelte Kamera → Hinweis, keine Rückfrage."""
        mock_db.get_all_cameras.return_value = []
        _process_message(_msg("/photo_clear"))
        mock_tc.send_message.assert_called_once()
        self.assertIn("keine kamera", mock_tc.send_message.call_args.args[1].lower())

    @patch("daemon.scheduler.count_camera_history", return_value=3)
    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_single_camera_asks_confirmation_with_count(self, mock_db, mock_tc, mock_count):
        """Eine Kamera mit Bildern → Ja/Nein-Rückfrage mit Anzahl und Bestätigungs-Callback."""
        mock_db.get_all_cameras.return_value = [{"wish_name": "Garten", "mac_address": "AA"}]
        _process_message(_msg("/photo_clear"))

        call = mock_tc.send_message.call_args
        self.assertIn("3", call.args[1])
        self.assertIn("photoclear_confirm_Garten", _cb_data(_markup(call)))

    @patch("daemon.scheduler.count_camera_history", return_value=0)
    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_single_camera_no_photos_hint(self, mock_db, mock_tc, mock_count):
        """Eine Kamera ohne Bilder → Hinweis statt Rückfrage (kein Bestätigungs-Keyboard)."""
        mock_db.get_all_cameras.return_value = [{"wish_name": "Garten", "mac_address": "AA"}]
        _process_message(_msg("/photo_clear"))

        call = mock_tc.send_message.call_args
        self.assertIsNone(_markup(call))
        self.assertIn("keine bilder", call.args[1].lower())

    @patch("daemon.scheduler.count_camera_history", return_value=3)
    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_multi_camera_shows_selection(self, mock_db, mock_tc, mock_count):
        """Mehrere Kameras → Auswahl-Keyboard mit photoclear_-Callbacks pro Kamera."""
        mock_db.get_all_cameras.return_value = [
            {"wish_name": "Garten", "mac_address": "AA"},
            {"wish_name": "Terrasse", "mac_address": "BB"},
        ]
        _process_message(_msg("/photo_clear"))

        data = _cb_data(_markup(mock_tc.send_message.call_args))
        self.assertIn("photoclear_Garten", data)
        self.assertIn("photoclear_Terrasse", data)

    @patch("daemon.ui.telegram_ui.handle_photo")
    @patch("daemon.ui.telegram_ui.handle_photo_clear")
    def test_photo_clear_not_routed_to_photo(self, mock_clear, mock_photo):
        """/photo_clear muss handle_photo_clear auslösen, nicht die Foto-Anzeige."""
        _process_message(_msg("/photo_clear"))
        mock_clear.assert_called_once()
        mock_photo.assert_not_called()


class TestPhotoClearCallbacks(unittest.TestCase):

    @patch("daemon.scheduler.count_camera_history", return_value=2)
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_selection_callback_asks_confirmation(self, mock_tc, mock_count):
        """Auswahl-Callback photoclear_<name> führt zur Ja/Nein-Rückfrage."""
        _process_callback_query(_cb("photoclear_Garten"))
        call = mock_tc.send_message.call_args
        self.assertIn("photoclear_confirm_Garten", _cb_data(_markup(call)))

    @patch("daemon.scheduler.clear_camera_history", return_value=4)
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_confirm_callback_clears_and_reports(self, mock_tc, mock_clear):
        """Bestätigung löscht die Historie und meldet die Anzahl."""
        _process_callback_query(_cb("photoclear_confirm_Garten"))
        mock_clear.assert_called_once_with("Garten")
        self.assertIn("4", mock_tc.send_message.call_args.args[1])

    @patch("daemon.scheduler.clear_camera_history", return_value=1)
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_confirm_callback_handles_underscore_name(self, mock_tc, mock_clear):
        """Wunschnamen mit Unterstrich werden im Bestätigungs-Callback korrekt aufgelöst."""
        _process_callback_query(_cb("photoclear_confirm_Garten_Nord"))
        mock_clear.assert_called_once_with("Garten_Nord")


if __name__ == "__main__":
    unittest.main()
