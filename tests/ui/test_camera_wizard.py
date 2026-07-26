import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.ui.telegram_ui import (
    wizard_states,
    _state_set,
    _state_get,
    _process_message,
    _process_callback_query,
    get_main_keyboard,
)

def _msg(text, chat_id=100):
    return {"chat": {"id": chat_id}, "text": text}

def _cb(data, chat_id=100, msg_id=1):
    return {"id": "cb1", "data": data, "message": {"chat": {"id": chat_id}, "message_id": msg_id}}

class TestMainMenuReorganisation(unittest.TestCase):

    def test_main_keyboard_has_setup_button(self):
        """Das Hauptmenü enthält den ⚙️ Einstellungen-Button (Feature 0031)."""
        kb = get_main_keyboard()
        all_texts = [btn["text"] for row in kb["keyboard"] for btn in row]
        self.assertIn("⚙️ Einstellungen", all_texts)
        self.assertNotIn("⚙️ Setup", all_texts)

    def test_main_keyboard_has_kamera_button(self):
        """Das Hauptmenü enthält 📷 Kamera (Foto-Anzeige zog ins Kamera-Untermenü, Feature 0031)."""
        kb = get_main_keyboard()
        all_texts = [btn["text"] for row in kb["keyboard"] for btn in row]
        self.assertIn("📷 Kamera", all_texts)
        self.assertNotIn("📸 Foto anzeigen", all_texts)

    def test_main_keyboard_no_direct_pairing_buttons(self):
        """Kopplungsbuttons sind nicht mehr direkt im Hauptmenü sichtbar."""
        kb = get_main_keyboard()
        all_texts = [btn["text"] for row in kb["keyboard"] for btn in row]
        self.assertNotIn("🔧 Ventil koppeln", all_texts)
        self.assertNotIn("📷 Kamera koppeln", all_texts)

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_setup_button_opens_submenu_with_pairing_options(self, mock_tc):
        """Nachricht '⚙️ Einstellungen' sendet ein Inline-Keyboard mit Kopplungsoptionen."""
        _process_message(_msg("⚙️ Einstellungen"))

        mock_tc.send_message.assert_called_once()
        call_args = mock_tc.send_message.call_args
        markup = call_args.args[2] if len(call_args.args) > 2 else call_args.kwargs.get("reply_markup")
        self.assertIsNotNone(markup)
        all_cb_data = [
            btn["callback_data"]
            for row in markup["inline_keyboard"]
            for btn in row
        ]
        self.assertIn("setup_confirm", all_cb_data)
        self.assertIn("camsetup_start", all_cb_data)

if __name__ == "__main__":
    unittest.main()
