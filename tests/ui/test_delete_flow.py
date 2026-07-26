"""Ende-zu-Ende-Regression der Zeitplan-Löschung (Ticket cy1).

Löschen ist jetzt ein Inline-Dialog über den DeleteConfirmAssistent: „🗑️" (sched_delete_ask_)
→ Inline-Bestätigung → „✅ Ja" (sched_del_yes) löscht, „❌ Nein" (sched_del_no) bricht ab.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.ui.telegram_ui import _process_callback_query, delete_states


class TestDeleteFlow(unittest.TestCase):
    CHAT = 700

    def setUp(self):
        delete_states.clear()
        self.tc = patch("daemon.ui.telegram_ui.telegram_client").start()
        self.db = patch("daemon.ui.telegram_ui.database").start()
        self.addCleanup(patch.stopall)
        self.tc.send_message_id.return_value = 500
        self.db.get_schedules.return_value = [
            {"id": 5, "name": "Morgen", "is_active": 1, "days": "Mon", "time": "08:00",
             "duration_minutes": 10, "target_volume_liters": 0}]
        self.db.delete_schedule.return_value = True

    def tearDown(self):
        delete_states.clear()

    def _cb(self, data, msg_id=42):
        return {"id": "cb1", "data": data, "message": {"chat": {"id": self.CHAT}, "message_id": msg_id}}

    def test_confirm_deletes(self):
        _process_callback_query(self._cb("sched_delete_ask_5"))
        _process_callback_query(self._cb("sched_del_yes"))
        self.db.delete_schedule.assert_called_once_with(5)
        self.assertNotIn(self.CHAT, delete_states)

    def test_cancel_keeps_schedule(self):
        _process_callback_query(self._cb("sched_delete_ask_5"))
        _process_callback_query(self._cb("sched_del_no"))
        self.db.delete_schedule.assert_not_called()
        self.assertNotIn(self.CHAT, delete_states)

    def test_unknown_id_shows_alert(self):
        self.db.get_schedules.return_value = []
        _process_callback_query(self._cb("sched_delete_ask_99"))
        self.tc.answer_callback_query.assert_called_once_with("cb1", "Zeitplan nicht gefunden", show_alert=True)
        self.assertNotIn(self.CHAT, delete_states)


if __name__ == "__main__":
    unittest.main()
