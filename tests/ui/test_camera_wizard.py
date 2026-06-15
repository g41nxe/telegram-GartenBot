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


class TestCameraWizardSteps(unittest.TestCase):

    def setUp(self):
        wizard_states.clear()

    def tearDown(self):
        wizard_states.clear()

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.adapters.camera_pairing.start_pairing")
    def test_interval_step_advances_to_resolution(self, mock_start, mock_tc):
        """Nach Intervall-Eingabe wechselt der Wizard zu setup_camera_resolution statt Kopplung zu starten."""
        _state_set(wizard_states, 100, {
            "step": "setup_camera_interval",
            "wish_name": "Garten",
        })
        _process_message(_msg("15"))

        state = _state_get(wizard_states, 100)
        self.assertIsNotNone(state)
        self.assertEqual(state["step"], "setup_camera_resolution")
        self.assertEqual(state["sleep_seconds"], 15 * 60)
        mock_start.assert_not_called()

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_resolution_callback_advances_to_quality(self, mock_tc):
        """Callback camsetup_res_VGA setzt step=setup_camera_quality und resolution='VGA'."""
        _state_set(wizard_states, 100, {
            "step": "setup_camera_resolution",
            "wish_name": "Garten",
            "sleep_seconds": 900,
        })
        _process_callback_query(_cb("camsetup_res_VGA"))

        state = _state_get(wizard_states, 100)
        self.assertIsNotNone(state)
        self.assertEqual(state["step"], "setup_camera_quality")
        self.assertEqual(state["resolution"], "VGA")

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.adapters.camera_pairing.start_pairing")
    def test_quality_callback_starts_pairing_with_all_params(self, mock_start, mock_tc):
        """Callback camsetup_qual_high startet Kopplung mit resolution='VGA' und quality=10."""
        _state_set(wizard_states, 100, {
            "step": "setup_camera_quality",
            "wish_name": "Garten",
            "sleep_seconds": 900,
            "resolution": "VGA",
        })
        _process_callback_query(_cb("camsetup_qual_high"))

        mock_start.assert_called_once()
        call_kwargs = mock_start.call_args
        self.assertEqual(call_kwargs.kwargs.get("resolution"), "VGA")
        self.assertEqual(call_kwargs.kwargs.get("quality"), 10)
        self.assertIsNone(_state_get(wizard_states, 100))

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_invalid_resolution_callback_is_ignored(self, mock_tc):
        """Unbekannter camsetup_res_INVALID-Callback lässt State unverändert."""
        _state_set(wizard_states, 100, {
            "step": "setup_camera_resolution",
            "wish_name": "Garten",
            "sleep_seconds": 900,
        })
        _process_callback_query(_cb("camsetup_res_INVALID"))

        state = _state_get(wizard_states, 100)
        self.assertIsNotNone(state)
        self.assertEqual(state["step"], "setup_camera_resolution")

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.adapters.camera_pairing.start_pairing")
    def test_quality_medium_maps_to_25(self, mock_start, mock_tc):
        """Callback camsetup_qual_medium ruft start_pairing mit quality=25 auf."""
        _state_set(wizard_states, 100, {
            "step": "setup_camera_quality",
            "wish_name": "Garten",
            "sleep_seconds": 900,
            "resolution": "UXGA",
        })
        _process_callback_query(_cb("camsetup_qual_medium"))

        self.assertEqual(mock_start.call_args.kwargs.get("quality"), 25)

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.adapters.camera_pairing.start_pairing")
    def test_quality_low_maps_to_40(self, mock_start, mock_tc):
        """Callback camsetup_qual_low ruft start_pairing mit quality=40 auf."""
        _state_set(wizard_states, 100, {
            "step": "setup_camera_quality",
            "wish_name": "Garten",
            "sleep_seconds": 900,
            "resolution": "UXGA",
        })
        _process_callback_query(_cb("camsetup_qual_low"))

        self.assertEqual(mock_start.call_args.kwargs.get("quality"), 40)


class TestMainMenuReorganisation(unittest.TestCase):

    def test_main_keyboard_has_setup_button(self):
        """Das Hauptmenü enthält den ⚙️ Setup-Button."""
        kb = get_main_keyboard()
        all_texts = [btn["text"] for row in kb["keyboard"] for btn in row]
        self.assertIn("⚙️ Setup", all_texts)

    def test_main_keyboard_has_photo_button(self):
        """Das Hauptmenü enthält 📸 Foto anzeigen."""
        kb = get_main_keyboard()
        all_texts = [btn["text"] for row in kb["keyboard"] for btn in row]
        self.assertIn("📸 Foto anzeigen", all_texts)

    def test_main_keyboard_no_direct_pairing_buttons(self):
        """Kopplungsbuttons sind nicht mehr direkt im Hauptmenü sichtbar."""
        kb = get_main_keyboard()
        all_texts = [btn["text"] for row in kb["keyboard"] for btn in row]
        self.assertNotIn("🔧 Ventil koppeln", all_texts)
        self.assertNotIn("📷 Kamera koppeln", all_texts)

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_setup_button_opens_submenu_with_pairing_options(self, mock_tc):
        """Nachricht '⚙️ Setup' sendet ein Inline-Keyboard mit Kopplungsoptionen."""
        _process_message(_msg("⚙️ Setup"))

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
