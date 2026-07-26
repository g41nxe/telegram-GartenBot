"""Ende-zu-Ende-Regression des Sofort-Guss-Wizards (Ticket cy1).

Treibt den manuellen „Bewässern starten"-Flow (Ventil-Wahl → Dauer → Volumen → Start)
durch die echten Dispatcher mit gemocktem telegram_client / database / Wetter / Guss-
Steuerung. Paritäts-Anker für die GussAssistent-Migration: grün VOR und NACH der Migration.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.ui.telegram_ui import _process_message, _process_callback_query, manual_states
from daemon.core.watering_advice import WateringDecision

_FULL_GUSS = WateringDecision(factor=1.0, verdict="🚿 Voller Guss", reasons=[], skip=False)


class TestGussFlow(unittest.TestCase):
    CHAT = 300

    def setUp(self):
        manual_states.clear()
        self.tc = patch("daemon.ui.telegram_ui.telegram_client").start()
        self.db = patch("daemon.ui.telegram_ui.database").start()
        self.weather = patch("daemon.ui.telegram_ui._weather_adapter").start()
        self.ctrl = patch("daemon.ui.telegram_ui._watering_ctrl").start()
        self.addCleanup(patch.stopall)
        self.tc.send_message_id.return_value = 500
        self.weather.evaluate_watering_factor.return_value = _FULL_GUSS   # kein skip ⇒ Sofortstart
        self.ctrl.start_watering.return_value = (True, "OK")
        self._valve = {"id": 1, "wish_name": "Beet", "mqtt_name": "beet_valve"}
        self.db.get_all_valves.return_value = [self._valve]
        self.db.get_valve_by_id.return_value = self._valve

    def tearDown(self):
        manual_states.clear()

    def _cb(self, data, msg_id=500):
        return {"id": "cb1", "data": data, "message": {"chat": {"id": self.CHAT}, "message_id": msg_id}}

    def _msg(self, text):
        return {"chat": {"id": self.CHAT}, "text": text, "message_id": 1}

    def test_preset_path_starts_watering(self):
        _process_callback_query(self._cb("water_mode_guss", msg_id=10))   # 1 Ventil ⇒ direkt Dauer
        _process_callback_query(self._cb("man_dur_10"))
        _process_callback_query(self._cb("man_vol_25"))
        self.ctrl.start_watering.assert_called_once()
        args = self.ctrl.start_watering.call_args
        self.assertEqual(args.args[0], 10)                       # duration
        self.assertEqual(args.args[1], 25)                       # volume
        self.assertEqual(args.kwargs.get("mqtt_name"), "beet_valve")
        self.assertNotIn(self.CHAT, manual_states)

    def test_custom_duration_then_start(self):
        _process_callback_query(self._cb("water_mode_guss", msg_id=10))
        _process_callback_query(self._cb("man_dur_custom"))
        _process_message(self._msg("7"))                         # getippte Dauer
        _process_callback_query(self._cb("man_vol_25"))
        self.ctrl.start_watering.assert_called_once()
        self.assertEqual(self.ctrl.start_watering.call_args.args[0], 7)

    def test_custom_volume_typed_no_stale_keyboard(self):
        """ADR 0039: der getippte-Menge-Pfad darf kein zweites lebendes Inline-Keyboard per
        send_message hinterlassen."""
        _process_callback_query(self._cb("water_mode_guss", msg_id=10))
        _process_callback_query(self._cb("man_dur_10"))
        _process_callback_query(self._cb("man_vol_custom"))
        _process_message(self._msg("30"))                        # getippte Menge ⇒ Start
        self.ctrl.start_watering.assert_called_once()
        self.assertEqual(self.ctrl.start_watering.call_args.args[1], 30)
        for call in self.tc.send_message.call_args_list:
            markup = call.args[2] if len(call.args) > 2 else call.kwargs.get("reply_markup")
            self.assertFalse(
                isinstance(markup, dict) and "inline_keyboard" in markup,
                "Custom-Menge-Schritt erzeugte eine zweite lebende Inline-Tastatur",
            )

    def test_context_skip_asks_instead_of_starting(self):
        """Feature 0020: spricht der Kontext dagegen (skip), wird NICHT sofort gestartet,
        sondern rückgefragt (water_anyway)."""
        self.weather.evaluate_watering_factor.return_value = WateringDecision(
            factor=0.0, verdict="🌧 Kein Gießen", reasons=["Regen erwartet"], skip=True)
        _process_callback_query(self._cb("water_mode_guss", msg_id=10))
        _process_callback_query(self._cb("man_dur_10"))
        _process_callback_query(self._cb("man_vol_25"))
        self.ctrl.start_watering.assert_not_called()
        # gemerkte Werte für „Trotzdem gießen"
        state = manual_states.get(self.CHAT)
        self.assertIsNotNone(state)
        self.assertIn("pending_water", state)

    def test_cancel_clears_state(self):
        _process_callback_query(self._cb("water_mode_guss", msg_id=10))
        _process_callback_query(self._cb("man_cancel"))
        self.assertNotIn(self.CHAT, manual_states)

    _SKIP = WateringDecision(factor=0.0, verdict="🌧 Kein Gießen", reasons=["8.0 mm Regen"], skip=True)

    def test_context_skip_then_water_anyway_starts(self):
        # Feature 0020: bei skip Rückfrage, „Trotzdem gießen" startet mit gemerkten Werten.
        self.weather.evaluate_watering_factor.return_value = self._SKIP
        _process_callback_query(self._cb("water_mode_guss", msg_id=10))
        _process_callback_query(self._cb("man_dur_15"))
        _process_callback_query(self._cb("man_vol_30"))
        self.ctrl.start_watering.assert_not_called()
        _process_callback_query(self._cb("water_anyway"))
        self.ctrl.start_watering.assert_called_once()
        self.assertEqual(self.ctrl.start_watering.call_args.args[0], 15)
        self.assertEqual(self.ctrl.start_watering.call_args.args[1], 30)
        self.assertNotIn(self.CHAT, manual_states)

    def test_eval_failure_does_not_block(self):
        # Fällt die Kontextprüfung aus, wird der Guss NICHT blockiert.
        self.weather.evaluate_watering_factor.side_effect = RuntimeError("Wetter weg")
        _process_callback_query(self._cb("water_mode_guss", msg_id=10))
        _process_callback_query(self._cb("man_dur_10"))
        _process_callback_query(self._cb("man_vol_25"))
        self.ctrl.start_watering.assert_called_once()

    def test_custom_volume_skip_asks(self):
        # Auch der getippte Mengen-Pfad muss bei skip nachfragen (statt zu starten).
        self.weather.evaluate_watering_factor.return_value = self._SKIP
        _process_callback_query(self._cb("water_mode_guss", msg_id=10))
        _process_callback_query(self._cb("man_dur_10"))
        _process_callback_query(self._cb("man_vol_custom"))
        _process_message(self._msg("40"))
        self.ctrl.start_watering.assert_not_called()
        self.assertIn("pending_water", manual_states.get(self.CHAT))

    def test_start_failure_sends_error(self):
        self.ctrl.start_watering.return_value = (False, "Ventil klemmt")
        _process_callback_query(self._cb("water_mode_guss", msg_id=10))
        _process_callback_query(self._cb("man_dur_10"))
        _process_callback_query(self._cb("man_vol_25"))
        texts = " || ".join(
            a for call in self.tc.send_message.call_args_list for a in call.args if isinstance(a, str))
        self.assertIn("Fehler beim Starten", texts)


if __name__ == "__main__":
    unittest.main()
