"""Ende-zu-Ende-Regression des Zeitplan-Wizards (Ticket cy1).

Treibt den kompletten „Zeitplan anlegen"-Flow durch die echten Dispatcher
(_process_message / _process_callback_query) mit gemocktem telegram_client + database
und prüft Schritte, Prompts und die finale DB-Schreibung. Das ersetzt das manuelle
Durchklicken am Bot und ist der Paritäts-Anker für die Assistent-Migration: Dieser Test
muss VOR und NACH der Migration identisch grün bleiben.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.ui.telegram_ui import _process_message, _process_callback_query, wizard_states


class TestZeitplanWizardFlow(unittest.TestCase):
    CHAT = 100

    def setUp(self):
        wizard_states.clear()
        self.tc = patch("daemon.ui.telegram_ui.telegram_client").start()
        self.db = patch("daemon.ui.telegram_ui.database").start()
        self.addCleanup(patch.stopall)
        # show_step nutzt send_message_id → muss eine Nachrichten-ID liefern
        self.tc.send_message_id.return_value = 500
        # Verzweigung: kein Ventil gekoppelt → Ventil-Schritt wird übersprungen
        self.db.get_all_valves.return_value = []
        self.db.add_schedule.return_value = 1
        self.db.get_schedules.return_value = []

    def tearDown(self):
        wizard_states.clear()

    def _cb(self, data, msg_id=500):
        return {"id": "cb1", "data": data, "message": {"chat": {"id": self.CHAT}, "message_id": msg_id}}

    def _msg(self, text):
        return {"chat": {"id": self.CHAT}, "text": text, "message_id": 1}

    def _sent_texts(self):
        """Alle über send_message / edit_message_text / send_message_id ausgegebenen Texte."""
        texts = []
        for m in (self.tc.send_message, self.tc.edit_message_text, self.tc.send_message_id):
            for call in m.call_args_list:
                for a in call.args:
                    if isinstance(a, str):
                        texts.append(a)
        return texts

    def test_full_flow_creates_schedule(self):
        # Modus wählen → Name-Prompt
        _process_callback_query(self._cb("wiz_mode_watering", msg_id=10))
        # Name tippen
        _process_message(self._msg("Rasen"))
        # Stunde / Minute
        _process_callback_query(self._cb("wiz_hour_14"))
        _process_callback_query(self._cb("wiz_min_30"))
        # Dauer: Custom-Pfad (dort sitzt der ADR-0039-Bypass im Alt-Code)
        _process_callback_query(self._cb("wiz_dur_custom"))
        _process_message(self._msg("12"))
        # Menge (Preset) → Ventil übersprungen → Tage
        _process_callback_query(self._cb("wiz_vol_25"))
        _process_callback_query(self._cb("wiz_day_Mon"))
        _process_callback_query(self._cb("wiz_save"))
        _process_callback_query(self._cb("wiz_confirm_save"))

        # DB-Schreibung: name, time, days, duration, volume
        self.db.add_schedule.assert_called_once()
        args = self.db.add_schedule.call_args.args
        self.assertEqual(args[0], "Rasen")
        self.assertEqual(args[1], "14:30")
        self.assertEqual(args[2], "Mon")
        self.assertEqual(args[3], 12)
        self.assertEqual(args[4], 25)
        # Wizard-Zustand aufgeräumt
        self.assertNotIn(self.CHAT, wizard_states)
        # Erfolgsmeldung
        self.assertTrue(any("angelegt" in t for t in self._sent_texts()))

    def test_flow_prompts_progress_through_steps(self):
        _process_callback_query(self._cb("wiz_mode_watering", msg_id=10))
        _process_message(self._msg("Rasen"))
        _process_callback_query(self._cb("wiz_hour_14"))
        _process_callback_query(self._cb("wiz_min_30"))
        texts = " || ".join(self._sent_texts())
        self.assertIn("Stunde", texts)     # Schritt 2
        self.assertIn("Minute", texts)     # Schritt 3
        self.assertIn("14:30", texts)      # Startzeit übernommen

    def test_empty_name_stays_on_name_step(self):
        _process_callback_query(self._cb("wiz_mode_watering", msg_id=10))
        _process_message(self._msg("   "))
        # kein Schritt-Wechsel: der Assistent bleibt im Namen-Schritt (ADR 0039)
        self.assertEqual(wizard_states[self.CHAT]["assistent"].step, "name")

    def test_cancel_clears_state(self):
        _process_callback_query(self._cb("wiz_mode_watering", msg_id=10))
        _process_message(self._msg("Rasen"))
        _process_callback_query(self._cb("wiz_cancel"))
        self.assertNotIn(self.CHAT, wizard_states)

    def test_custom_step_no_stale_inline_keyboard(self):
        """ADR 0039: Nach der getippten Custom-Dauer darf kein NEUES Inline-Keyboard per
        send_message entstehen (das lässt das alte Prompt-Keyboard stehen → zwei lebende
        Tastaturen). Seit der Assistent-Migration (durchgängig show_step) erfüllt — echter
        grüner Regel-Wächter (vorher @expectedFailure, Bug im Alt-Code reproduziert)."""
        _process_callback_query(self._cb("wiz_mode_watering", msg_id=10))
        _process_message(self._msg("Rasen"))
        _process_callback_query(self._cb("wiz_hour_14"))
        _process_callback_query(self._cb("wiz_min_30"))
        _process_callback_query(self._cb("wiz_dur_custom"))
        _process_message(self._msg("12"))   # genau hier sendet der Alt-Code das stale Keyboard

        for call in self.tc.send_message.call_args_list:
            markup = call.args[2] if len(call.args) > 2 else call.kwargs.get("reply_markup")
            self.assertFalse(
                isinstance(markup, dict) and "inline_keyboard" in markup,
                "Custom-Schritt erzeugte eine zweite lebende Inline-Tastatur per send_message",
            )


if __name__ == "__main__":
    unittest.main()
