"""Ende-zu-Ende-Regression des Sofort-Nebel-Wizards (Ticket cy1).

Treibt „🌫️ Sofort-Nebel" (Ventil → Stoß-Dauer → Pause → Laufzeit → Start) durch die
echten Dispatcher mit gemocktem telegram_client / database / Nebel-Steuerung. Paritäts-
Anker für die SofortNebelAssistent-Migration: grün VOR und NACH der Migration.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.ui.telegram_ui import _process_callback_query, manual_states


class TestSofortNebelFlow(unittest.TestCase):
    CHAT = 400

    def setUp(self):
        manual_states.clear()
        self.tc = patch("daemon.ui.telegram_ui.telegram_client").start()
        self.db = patch("daemon.ui.telegram_ui.database").start()
        self.nebel = patch("daemon.ui.telegram_ui._nebel_ctrl").start()
        self.addCleanup(patch.stopall)
        self.nebel.start.return_value = (True, "OK")
        self._valve = {"id": 3, "wish_name": "Terrasse", "mqtt_name": "terrace_mist"}
        self.db.get_all_valves.return_value = [self._valve]
        self.db.get_valve_by_id.return_value = self._valve

    def tearDown(self):
        manual_states.clear()

    def _cb(self, data, msg_id=500):
        return {"id": "cb1", "data": data, "message": {"chat": {"id": self.CHAT}, "message_id": msg_id}}

    def test_full_flow_starts_nebel(self):
        _process_callback_query(self._cb("nebel_now", msg_id=10))     # 1 Ventil ⇒ direkt Stoß-Dauer
        _process_callback_query(self._cb("nebel_now_on_30"))
        _process_callback_query(self._cb("nebel_now_pause_5"))
        _process_callback_query(self._cb("nebel_dur_60"))
        self.nebel.start.assert_called_once()
        args = self.nebel.start.call_args[0]
        self.assertEqual(args[0], "terrace_mist")     # mqtt_name
        self.assertEqual(args[1], 30)                 # on_seconds
        self.assertEqual(args[2], 5)                  # pause_minutes
        self.assertEqual(args[4], "nebel_manual")     # source
        self.assertNotIn(self.CHAT, manual_states)

    def test_multi_valve_selects_then_starts(self):
        v2 = {"id": 4, "wish_name": "Beet", "mqtt_name": "beet_mist"}
        self.db.get_all_valves.return_value = [self._valve, v2]
        self.db.get_valve_by_id.return_value = v2
        _process_callback_query(self._cb("nebel_now", msg_id=10))     # >1 ⇒ Ventil-Auswahl
        _process_callback_query(self._cb("nebel_now_valve_4"))
        _process_callback_query(self._cb("nebel_now_on_20"))
        _process_callback_query(self._cb("nebel_now_pause_3"))
        _process_callback_query(self._cb("nebel_dur_45"))
        self.nebel.start.assert_called_once()
        self.assertEqual(self.nebel.start.call_args[0][0], "beet_mist")

    def test_cancel_clears_state(self):
        _process_callback_query(self._cb("nebel_now", msg_id=10))
        _process_callback_query(self._cb("nebel_cancel"))
        self.assertNotIn(self.CHAT, manual_states)

    def test_runtime_is_capped(self):
        # Laufzeit wird hart auf NEBEL_MANUAL_MAX_MINUTES gedeckelt.
        from datetime import datetime
        from daemon.ui import telegram_ui
        _process_callback_query(self._cb("nebel_now", msg_id=10))
        _process_callback_query(self._cb("nebel_now_on_30"))
        _process_callback_query(self._cb("nebel_now_pause_5"))
        with patch.object(telegram_ui.config, "NEBEL_MANUAL_MAX_MINUTES", 90):
            _process_callback_query(self._cb("nebel_dur_120"))   # über dem Cap
        end_dt = self.nebel.start.call_args[0][3]
        delta_min = (end_dt - datetime.now()).total_seconds() / 60
        self.assertLessEqual(delta_min, 91)
        self.assertGreater(delta_min, 85)


if __name__ == "__main__":
    unittest.main()
