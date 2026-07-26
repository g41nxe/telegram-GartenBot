"""Ende-zu-Ende-Regression des Zeitplan-Editors (Ticket cy1).

Bearbeiten ist jetzt ein Nabe-Speiche-Editor (EditAssistent): „✏️" (sched_edit_<id>) öffnet
das Feld-Menü, jede Speiche ändert nur den Entwurf, „✅ Fertig" (sched_edit_done) schreibt
ALLES in einem update_schedule (transaktional). „❌ Abbrechen" lässt den Zeitplan unberührt.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.ui.telegram_ui import _process_message, _process_callback_query, edit_states


class TestEditFlow(unittest.TestCase):
    CHAT = 800

    def setUp(self):
        edit_states.clear()
        self.tc = patch("daemon.ui.telegram_ui.telegram_client").start()
        self.db = patch("daemon.ui.telegram_ui.database").start()
        self.addCleanup(patch.stopall)
        self.tc.send_message_id.return_value = 500
        self._sched = {"id": 5, "name": "Morgen", "time": "08:30", "days": "Mon,Wed",
                       "duration_minutes": 10, "target_volume_liters": 20, "is_active": 1}
        self.db.get_schedule_by_id.return_value = self._sched
        self.db.get_schedules.return_value = [self._sched]
        self.db.get_schedule_valves.return_value = [3]
        self.db.get_all_valves.return_value = [{"id": 3, "wish_name": "Beet"}]
        self.db.get_valve_by_id.return_value = {"id": 3, "wish_name": "Beet"}

    def tearDown(self):
        edit_states.clear()

    def _cb(self, data, msg_id=42):
        return {"id": "cb1", "data": data, "message": {"chat": {"id": self.CHAT}, "message_id": msg_id}}

    def _msg(self, text):
        return {"chat": {"id": self.CHAT}, "text": text, "message_id": 1}

    def _open(self):
        _process_callback_query(self._cb("sched_edit_5"))

    def test_open_creates_editor(self):
        self._open()
        st = edit_states.get(self.CHAT)
        self.assertIsNotNone(st)
        self.assertIn("assistent", st)
        self.assertEqual(st["assistent"].data["name"], "Morgen")

    def test_edit_time_then_done_batches_one_update(self):
        self._open()
        _process_callback_query(self._cb("sched_editfield_time_5"))
        _process_callback_query(self._cb("sched_edithour_5_14"))
        _process_callback_query(self._cb("sched_editmin_5_14_45"))
        # Zwischenstand: NOCH nicht gespeichert (Batch)
        self.db.update_schedule.assert_not_called()
        _process_callback_query(self._cb("sched_edit_done"))
        self.db.update_schedule.assert_called_once()
        args = self.db.update_schedule.call_args.args
        self.assertEqual(args[0], 5)              # sched_id
        self.assertEqual(args[1], "Morgen")       # name unverändert
        self.assertEqual(args[2], "14:45")        # neue Zeit
        self.assertEqual(args[3], "Mon,Wed")      # Tage unverändert
        self.assertNotIn(self.CHAT, edit_states)

    def test_edit_name_typed_then_done(self):
        self._open()
        _process_callback_query(self._cb("sched_editfield_name_5"))
        _process_message(self._msg("Abendrunde"))
        self.db.update_schedule.assert_not_called()   # noch nicht
        _process_callback_query(self._cb("sched_edit_done"))
        self.assertEqual(self.db.update_schedule.call_args.args[1], "Abendrunde")

    def test_edit_duration_and_volume_batched(self):
        self._open()
        _process_callback_query(self._cb("sched_editfield_duration_5"))
        _process_callback_query(self._cb("sched_setdur_5_20"))
        _process_callback_query(self._cb("sched_editfield_volume_5"))
        _process_callback_query(self._cb("sched_setvol_5_0"))
        _process_callback_query(self._cb("sched_edit_done"))
        args = self.db.update_schedule.call_args.args
        self.assertEqual(args[4], 20)             # duration
        self.assertEqual(args[5], 0)              # volume

    def test_edit_valve_sets_valves_on_done(self):
        self.db.get_all_valves.return_value = [{"id": 3, "wish_name": "Beet"}, {"id": 4, "wish_name": "Rasen"}]
        self._open()
        _process_callback_query(self._cb("sched_editfield_valve_5"))
        _process_callback_query(self._cb("sched_setvalve_5_4"))
        _process_callback_query(self._cb("sched_edit_done"))
        self.db.set_schedule_valves.assert_called_once_with(5, [4])

    def test_cancel_leaves_schedule_untouched(self):
        self._open()
        _process_callback_query(self._cb("sched_editfield_duration_5"))
        _process_callback_query(self._cb("sched_setdur_5_25"))
        _process_callback_query(self._cb("sched_edit_cancel"))
        self.db.update_schedule.assert_not_called()
        self.assertNotIn(self.CHAT, edit_states)

    def test_editing_nebel_schedule_preserves_nebel_fields(self):
        # Review-Befund: Bearbeiten darf ein Nebel-Intervall nicht auf „watering" zurücksetzen.
        self.db.get_schedule_by_id.return_value = {
            "id": 9, "name": "Terrasse", "time": "18:00", "days": "Mon", "duration_minutes": 0,
            "target_volume_liters": 0, "is_active": 1, "mode": "nebel", "end_time": "20:00",
            "on_seconds": 10, "pause_minutes": 5}
        _process_callback_query(self._cb("sched_edit_9"))
        _process_callback_query(self._cb("sched_editfield_days_9"))
        _process_callback_query(self._cb("sched_editday_9_Fri"))
        _process_callback_query(self._cb("sched_editday_save_9"))
        _process_callback_query(self._cb("sched_edit_done"))
        kwargs = self.db.update_schedule.call_args.kwargs
        self.assertEqual(kwargs.get("mode"), "nebel")
        self.assertEqual(kwargs.get("end_time"), "20:00")
        self.assertEqual(kwargs.get("on_seconds"), 10)
        self.assertEqual(kwargs.get("pause_minutes"), 5)


if __name__ == "__main__":
    unittest.main()
