"""Ende-zu-Ende-Regression des Nebel-Zeitplan-Wizards (Ticket cy1).

Treibt den kompletten „Nebel-Intervall anlegen"-Flow durch die echten Dispatcher
(_process_message / _process_callback_query) mit gemocktem telegram_client + database
und prüft Schritte, Prompts und die finale DB-Schreibung. Das ist der Paritäts-Anker
für die Assistent-Migration des Nebel-Zweigs: Dieser Test muss VOR und NACH der
Migration identisch grün bleiben.

Der Nebel-Zweig teilt Name/Stunde/Minute mit dem Wässern-Pfad, zweigt danach aber ab:
Fensterende (Stunde/Minute) → Nebelstoß (s) → Pause (min) → [Ventil] → Wochentage →
Bestätigung. Gespeichert wird über add_schedule(..., mode="nebel", end_time=...,
on_seconds=..., pause_minutes=...).
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.ui.telegram_ui import _process_message, _process_callback_query, wizard_states


class TestNebelWizardFlow(unittest.TestCase):
    CHAT = 200

    def setUp(self):
        wizard_states.clear()
        self.tc = patch("daemon.ui.telegram_ui.telegram_client").start()
        self.db = patch("daemon.ui.telegram_ui.database").start()
        self.addCleanup(patch.stopall)
        self.tc.send_message_id.return_value = 500
        # Nebel braucht mind. ein Ventil; genau eins ⇒ Ventil-Schritt entfällt (auto-Zuweisung).
        self._valve = {"id": 7, "wish_name": "Terrasse", "mqtt_name": "nebel_valve"}
        self.db.get_all_valves.return_value = [self._valve]
        self.db.get_valve_by_id.return_value = self._valve
        self.db.add_schedule.return_value = 3
        self.db.get_schedules.return_value = []

    def tearDown(self):
        wizard_states.clear()

    def _cb(self, data, msg_id=500):
        return {"id": "cb1", "data": data, "message": {"chat": {"id": self.CHAT}, "message_id": msg_id}}

    def _msg(self, text):
        return {"chat": {"id": self.CHAT}, "text": text, "message_id": 1}

    def _sent_texts(self):
        texts = []
        for m in (self.tc.send_message, self.tc.edit_message_text, self.tc.send_message_id):
            for call in m.call_args_list:
                for a in call.args:
                    if isinstance(a, str):
                        texts.append(a)
        return texts

    def _run_full_flow(self):
        _process_callback_query(self._cb("wiz_mode_nebel", msg_id=10))
        _process_message(self._msg("Terrasse"))
        _process_callback_query(self._cb("wiz_hour_8"))
        _process_callback_query(self._cb("wiz_min_0"))
        _process_callback_query(self._cb("nb_ehour_20"))
        _process_callback_query(self._cb("nb_emin_30"))
        _process_callback_query(self._cb("nb_on_10"))
        _process_callback_query(self._cb("nb_pause_5"))
        # genau ein Ventil ⇒ direkt Wochentage
        _process_callback_query(self._cb("wiz_day_Mon"))
        _process_callback_query(self._cb("wiz_save"))
        _process_callback_query(self._cb("wiz_confirm_save"))

    def test_full_flow_creates_nebel_schedule(self):
        self._run_full_flow()

        self.db.add_schedule.assert_called_once()
        call = self.db.add_schedule.call_args
        self.assertEqual(call.args[0], "Terrasse")       # name
        self.assertEqual(call.args[1], "08:00")          # time
        self.assertEqual(call.args[2], "Mon")            # days
        self.assertEqual(call.args[3], 0)                # duration = 0 im Nebel
        self.assertEqual(call.kwargs.get("mode"), "nebel")
        self.assertEqual(call.kwargs.get("end_time"), "20:30")
        self.assertEqual(call.kwargs.get("on_seconds"), 10)
        self.assertEqual(call.kwargs.get("pause_minutes"), 5)
        # Ventil-Zuweisung
        self.db.set_schedule_valves.assert_called_once_with(3, [7])
        # aufgeräumt + Erfolgsmeldung
        self.assertNotIn(self.CHAT, wizard_states)
        self.assertTrue(any("erfolgreich angelegt" in t for t in self._sent_texts()))

    def test_flow_prompts_progress_through_nebel_steps(self):
        self._run_full_flow()
        texts = " || ".join(self._sent_texts())
        self.assertIn("Nebelstoß", texts)     # on-Schritt
        self.assertIn("Pause", texts)         # pause-Schritt
        self.assertIn("Fenster", texts)       # Fensterende
        self.assertIn("Wochentage", texts)    # Tage

    def test_window_end_before_start_is_rejected(self):
        _process_callback_query(self._cb("wiz_mode_nebel", msg_id=10))
        _process_message(self._msg("Terrasse"))
        _process_callback_query(self._cb("wiz_hour_8"))
        _process_callback_query(self._cb("wiz_min_0"))
        _process_callback_query(self._cb("nb_ehour_7"))    # Ende VOR Start
        _process_callback_query(self._cb("nb_emin_0"))
        # kein Sprung zum Nebelstoß: add_schedule nie aufgerufen, Zustand lebt weiter
        self.db.add_schedule.assert_not_called()
        self.assertIn(self.CHAT, wizard_states)

    def test_cancel_clears_state(self):
        _process_callback_query(self._cb("wiz_mode_nebel", msg_id=10))
        _process_message(self._msg("Terrasse"))
        _process_callback_query(self._cb("wiz_cancel"))
        self.assertNotIn(self.CHAT, wizard_states)


if __name__ == "__main__":
    unittest.main()
