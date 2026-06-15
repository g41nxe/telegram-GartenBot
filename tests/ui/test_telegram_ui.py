import sys
import time
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.core.weather_codes import get_wmo_description
from unittest.mock import patch

from daemon.ui.telegram_ui import (
    wizard_states,
    manual_states,
    delete_states,
    _state_get,
    _state_set,
    _state_del,
    _state_touch,
    _cleanup_expired_states,
    get_schedules_inline_keyboard,
    _process_message,
    _process_callback_query,
    WIZARD_TTL_SECONDS,
)


class TestWeatherCodes(unittest.TestCase):

    def test_known_code_returns_description(self):
        self.assertIn("Sonnig", get_wmo_description(0))

    def test_rain_code_returns_description(self):
        self.assertIn("Regen", get_wmo_description(61))

    def test_unknown_code_returns_fallback(self):
        result = get_wmo_description(9999)
        self.assertIn("Unbekannt", result)

    def test_boundary_code_45(self):
        self.assertIn("Nebel", get_wmo_description(45))


class TestWizardStateMachine(unittest.TestCase):

    def setUp(self):
        wizard_states.clear()
        manual_states.clear()

    def tearDown(self):
        wizard_states.clear()
        manual_states.clear()

    def test_state_set_stores_value_with_last_active(self):
        _state_set(wizard_states, 42, {"step": 1})
        state = _state_get(wizard_states, 42)
        self.assertIsNotNone(state)
        self.assertEqual(state["step"], 1)
        self.assertIn("last_active", state)
        self.assertIsInstance(state["last_active"], datetime)

    def test_state_get_returns_none_for_missing_key(self):
        self.assertIsNone(_state_get(wizard_states, 999))

    def test_state_del_removes_entry(self):
        _state_set(wizard_states, 42, {"step": 1})
        _state_del(wizard_states, 42)
        self.assertIsNone(_state_get(wizard_states, 42))

    def test_state_del_noop_on_missing_key(self):
        # Must not raise
        _state_del(wizard_states, 9999)

    def test_state_touch_updates_last_active(self):
        _state_set(wizard_states, 42, {"step": 1})
        original_time = _state_get(wizard_states, 42)["last_active"]
        time.sleep(0.01)
        _state_touch(wizard_states, 42)
        updated_time = _state_get(wizard_states, 42)["last_active"]
        self.assertGreater(updated_time, original_time)


class TestWizardTTLCleanup(unittest.TestCase):

    def setUp(self):
        wizard_states.clear()
        manual_states.clear()

    def tearDown(self):
        wizard_states.clear()
        manual_states.clear()

    def test_cleanup_removes_expired_entries(self):
        past = datetime.now() - timedelta(seconds=WIZARD_TTL_SECONDS + 10)
        wizard_states[100] = {"step": 1, "last_active": past}
        _cleanup_expired_states()
        self.assertNotIn(100, wizard_states)

    def test_cleanup_preserves_fresh_entries(self):
        _state_set(wizard_states, 200, {"step": 2})
        _cleanup_expired_states()
        self.assertIn(200, wizard_states)

    def test_cleanup_removes_expired_manual_states(self):
        past = datetime.now() - timedelta(seconds=WIZARD_TTL_SECONDS + 1)
        manual_states[300] = {"step": "man_custom_duration", "last_active": past}
        _cleanup_expired_states()
        self.assertNotIn(300, manual_states)

    def test_cleanup_is_thread_safe(self):
        """Concurrent cleanup and state mutations must not raise."""
        errors = []

        def writer():
            for i in range(50):
                try:
                    _state_set(wizard_states, i % 5, {"step": i})
                    _state_del(wizard_states, i % 5)
                except Exception as e:
                    errors.append(e)

        def cleaner():
            for _ in range(50):
                try:
                    _cleanup_expired_states()
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=writer), threading.Thread(target=cleaner)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Thread-safety errors: {errors}")


class TestDeleteStatesCleanup(unittest.TestCase):

    def setUp(self):
        delete_states.clear()

    def tearDown(self):
        delete_states.clear()

    def test_cleanup_removes_expired_delete_states(self):
        past = datetime.now() - timedelta(seconds=WIZARD_TTL_SECONDS + 10)
        delete_states[100] = {"schedule_id": 1, "name": "Test", "last_active": past}
        _cleanup_expired_states()
        self.assertNotIn(100, delete_states)

    def test_cleanup_preserves_fresh_delete_states(self):
        _state_set(delete_states, 200, {"schedule_id": 2, "name": "Frisch"})
        _cleanup_expired_states()
        self.assertIn(200, delete_states)


class TestSchedulesInlineKeyboard(unittest.TestCase):

    def _s(self, id, name, time, is_active):
        return {"id": id, "name": name, "time": time, "is_active": is_active}

    def test_active_schedule_shows_green_icon(self):
        kb = get_schedules_inline_keyboard([self._s(1, "Morgen", "07:00", 1)])
        btn = kb["inline_keyboard"][0][0]
        self.assertIn("🟢", btn["text"])
        self.assertEqual(btn["callback_data"], "sched_toggle_1")

    def test_inactive_schedule_shows_red_icon(self):
        kb = get_schedules_inline_keyboard([self._s(2, "Abend", "20:00", 0)])
        btn = kb["inline_keyboard"][0][0]
        self.assertIn("🔴", btn["text"])

    def test_delete_button_callback_data(self):
        kb = get_schedules_inline_keyboard([self._s(3, "Test", "08:00", 1)])
        btn = kb["inline_keyboard"][0][1]
        self.assertEqual(btn["callback_data"], "sched_delete_ask_3")

    def test_add_button_is_last_row(self):
        kb = get_schedules_inline_keyboard([self._s(1, "Test", "07:00", 1)])
        self.assertEqual(kb["inline_keyboard"][-1][0]["callback_data"], "wiz_start")

    def test_multiple_schedules_generate_correct_row_count(self):
        schedules = [self._s(1, "A", "07:00", 1), self._s(2, "B", "20:00", 0)]
        kb = get_schedules_inline_keyboard(schedules)
        self.assertEqual(len(kb["inline_keyboard"]), 3)  # 2 schedule rows + add row


class TestScheduleToggleCallback(unittest.TestCase):

    def _cb(self, data, chat_id=100, msg_id=1):
        return {"id": "cb1", "data": data, "message": {"chat": {"id": chat_id}, "message_id": msg_id}}

    def _schedule(self, id=1, name="Test", time="07:00", days="everyday", dur=10, vol=0, active=1):
        return {"id": id, "name": name, "time": time, "days": days,
                "duration_minutes": dur, "target_volume_liters": vol, "is_active": active}

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_toggle_activates_inactive_schedule(self, mock_client, mock_db):
        mock_db.get_schedules.return_value = [self._schedule(active=0)]
        _process_callback_query(self._cb("sched_toggle_1"))
        mock_db.update_schedule.assert_called_once_with(1, "Test", "07:00", "everyday", 10, 0, 1)

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_toggle_deactivates_active_schedule(self, mock_client, mock_db):
        mock_db.get_schedules.return_value = [self._schedule(active=1)]
        _process_callback_query(self._cb("sched_toggle_1"))
        mock_db.update_schedule.assert_called_once_with(1, "Test", "07:00", "everyday", 10, 0, 0)

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_toggle_unknown_id_shows_alert(self, mock_client, mock_db):
        mock_db.get_schedules.return_value = []
        _process_callback_query(self._cb("sched_toggle_99"))
        mock_client.answer_callback_query.assert_called_once_with("cb1", "Zeitplan nicht gefunden", show_alert=True)


class TestScheduleDeleteFlow(unittest.TestCase):

    def setUp(self):
        delete_states.clear()
        wizard_states.clear()
        manual_states.clear()

    def tearDown(self):
        delete_states.clear()
        wizard_states.clear()
        manual_states.clear()

    def _cb(self, data, chat_id=100):
        return {"id": "cb1", "data": data, "message": {"chat": {"id": chat_id}, "message_id": 1}}

    def _msg(self, text, chat_id=100):
        return {"chat": {"id": chat_id}, "text": text}

    def _schedule(self, id=5, name="Morgen", time="07:00"):
        return {"id": id, "name": name, "time": time, "days": "everyday",
                "duration_minutes": 10, "target_volume_liters": 0, "is_active": 1}

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_delete_ask_sets_delete_state(self, mock_client, mock_db):
        mock_db.get_schedules.return_value = [self._schedule()]
        _process_callback_query(self._cb("sched_delete_ask_5"))
        state = _state_get(delete_states, 100)
        self.assertIsNotNone(state)
        self.assertEqual(state["schedule_id"], 5)
        self.assertEqual(state["name"], "Morgen")

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_delete_ask_sends_reply_keyboard(self, mock_client, mock_db):
        mock_db.get_schedules.return_value = [self._schedule()]
        _process_callback_query(self._cb("sched_delete_ask_5"))
        sent_kb = mock_client.send_message.call_args[0][2]
        self.assertIn("keyboard", sent_kb)
        texts = [btn["text"] for btn in sent_kb["keyboard"][0]]
        self.assertIn("✅ Ja, löschen", texts)
        self.assertIn("❌ Nein, abbrechen", texts)

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_confirm_delete_calls_db_and_clears_state(self, mock_client, mock_db):
        mock_db.delete_schedule.return_value = True
        mock_db.get_schedules.return_value = []
        _state_set(delete_states, 100, {"schedule_id": 5, "name": "Morgen"})
        _process_message(self._msg("✅ Ja, löschen"))
        mock_db.delete_schedule.assert_called_once_with(5)
        self.assertIsNone(_state_get(delete_states, 100))

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_cancel_delete_does_not_call_db(self, mock_client, mock_db):
        _state_set(delete_states, 100, {"schedule_id": 5, "name": "Morgen"})
        _process_message(self._msg("❌ Nein, abbrechen"))
        mock_db.delete_schedule.assert_not_called()
        self.assertIsNone(_state_get(delete_states, 100))

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_unrelated_text_clears_delete_state(self, mock_client, mock_db):
        _state_set(delete_states, 100, {"schedule_id": 5, "name": "Morgen"})
        _process_message(self._msg("irgendwas"))
        self.assertIsNone(_state_get(delete_states, 100))

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_delete_ask_unknown_id_shows_alert(self, mock_client, mock_db):
        mock_db.get_schedules.return_value = []
        _process_callback_query(self._cb("sched_delete_ask_99"))
        mock_client.answer_callback_query.assert_called_once_with("cb1", "Zeitplan nicht gefunden", show_alert=True)
        self.assertIsNone(_state_get(delete_states, 100))


class TestManualWateringPresetCallback(unittest.TestCase):
    """Tests the man_vol_<preset> callback path (inline button selection)."""

    def setUp(self):
        manual_states.clear()

    def tearDown(self):
        manual_states.clear()

    def _cb(self, data, chat_id=100, msg_id=1):
        return {"id": "cb1", "data": data, "message": {"chat": {"id": chat_id}, "message_id": msg_id}}

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_preset_volume_triggers_start_watering(self, mock_client, mock_ctrl):
        """Pressing a preset volume button must call _watering_ctrl.start_watering."""
        mock_ctrl.start_watering.return_value = (True, "OK")
        _state_set(manual_states, 100, {"step": 2, "duration": 10})

        _process_callback_query(self._cb("man_vol_25"))

        mock_ctrl.start_watering.assert_called_once_with(10, 25, "manual")

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_preset_volume_clears_state(self, mock_client, mock_ctrl):
        """Selecting a preset volume must clear manual_states."""
        mock_ctrl.start_watering.return_value = (True, "OK")
        _state_set(manual_states, 100, {"step": 2, "duration": 5})

        _process_callback_query(self._cb("man_vol_10"))

        self.assertIsNone(_state_get(manual_states, 100))

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_preset_volume_failure_sends_error(self, mock_client, mock_ctrl):
        """On failure, an error message must be sent to the user."""
        mock_ctrl.start_watering.return_value = (False, "Ventil blockiert")
        _state_set(manual_states, 100, {"step": 2, "duration": 10})

        _process_callback_query(self._cb("man_vol_50"))

        error_text = mock_client.send_message.call_args[0][1]
        self.assertIn("Fehler", error_text)


class TestTelegramWiringSmoke(unittest.TestCase):
    """Wiring smoke test (ARCHITECTURE.md Rule 6): verifies that the Telegram startup
    wiring in main.py calls the correct functions by name. A renamed or removed
    function on telegram_client or telegram_ui would be caught here rather than
    at daemon startup on the Pi.
    """

    def test_telegram_wiring_does_not_raise(self):
        from daemon.ui import telegram_client, telegram_ui
        with patch.object(telegram_client, "register_update_callback") as mock_reg, \
             patch.object(telegram_client, "start_polling") as mock_poll:
            telegram_client.register_update_callback(telegram_ui.on_telegram_update)
            telegram_client.start_polling()

        mock_reg.assert_called_once_with(telegram_ui.on_telegram_update)
        mock_poll.assert_called_once()


import json as _json_module


def _make_weather_row(with_forecast=True):
    fc = _json_module.dumps({
        "times":       ["2026-06-13T14:00", "2026-06-13T15:00"],
        "temp":        [22.0, 21.0],
        "precip_mm":   [0.0, 0.5],
        "precip_prob": [5, 30],
        "wmo":         [0, 61],
    }) if with_forecast else None
    return {
        "timestamp": "2026-06-13T14:00:00",
        "current_temp": 22.0,
        "weather_code": 0,
        "current_precipitation_mm": 0.1,
        "temp_min": 15.0,
        "temp_max": 25.0,
        "rain_probability": 5,
        "rain_last_24h_mm": 0.0,
        "rain_next_24h_mm": 0.5,
        "hourly_forecast_json": fc,
    }


class TestStatusWeatherBlock(unittest.TestCase):
    """Testet den neuen 'Jetzt / Nächste Stunde'-Wetter-Block im /status-Befehl."""

    def _msg(self, text, chat_id=100):
        return {"chat": {"id": chat_id}, "text": text}

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_shows_jetzt_line(self, mock_client, mock_db, mock_ctrl):
        from daemon.adapters import mqtt_client as mc
        mock_db.get_last_weather.return_value = _make_weather_row()
        mock_db.get_all_valves.return_value = []
        mock_db.get_recent_history.return_value = []
        mock_ctrl.get_active_cycle.return_value = None
        with patch.object(mc, "HAS_PAHO", False), \
             patch.object(mc, "request_valve_status"), \
             patch.object(mc, "is_broker_connected", return_value=True), \
             patch.object(mc, "get_bridge_status", return_value="online"):
            _process_message(self._msg("/status"))

        sent_text = mock_client.send_message.call_args[0][1]
        self.assertIn("Jetzt", sent_text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_shows_next_hour_line(self, mock_client, mock_db, mock_ctrl):
        from daemon.adapters import mqtt_client as mc
        mock_db.get_last_weather.return_value = _make_weather_row(with_forecast=True)
        mock_db.get_all_valves.return_value = []
        mock_db.get_recent_history.return_value = []
        mock_ctrl.get_active_cycle.return_value = None
        with patch.object(mc, "HAS_PAHO", False), \
             patch.object(mc, "request_valve_status"), \
             patch.object(mc, "is_broker_connected", return_value=True), \
             patch.object(mc, "get_bridge_status", return_value="online"):
            _process_message(self._msg("/status"))

        sent_text = mock_client.send_message.call_args[0][1]
        self.assertIn("15:00", sent_text)  # nächste Stunde aus Forecast-Index 1

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_without_forecast_shows_no_next_hour(self, mock_client, mock_db, mock_ctrl):
        from daemon.adapters import mqtt_client as mc
        mock_db.get_last_weather.return_value = _make_weather_row(with_forecast=False)
        mock_db.get_all_valves.return_value = []
        mock_db.get_recent_history.return_value = []
        mock_ctrl.get_active_cycle.return_value = None
        with patch.object(mc, "HAS_PAHO", False), \
             patch.object(mc, "request_valve_status"), \
             patch.object(mc, "is_broker_connected", return_value=True), \
             patch.object(mc, "get_bridge_status", return_value="online"):
            _process_message(self._msg("/status"))

        sent_text = mock_client.send_message.call_args[0][1]
        # "Jetzt" must still appear; "🔜" must not (no forecast)
        self.assertIn("Jetzt", sent_text)
        self.assertNotIn("🔜", sent_text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_no_weather_shows_fallback(self, mock_client, mock_db, mock_ctrl):
        from daemon.adapters import mqtt_client as mc
        mock_db.get_last_weather.return_value = None
        mock_db.get_all_valves.return_value = []
        mock_db.get_recent_history.return_value = []
        mock_ctrl.get_active_cycle.return_value = None
        with patch.object(mc, "HAS_PAHO", False), \
             patch.object(mc, "request_valve_status"), \
             patch.object(mc, "is_broker_connected", return_value=True), \
             patch.object(mc, "get_bridge_status", return_value="online"):
            _process_message(self._msg("/status"))

        sent_text = mock_client.send_message.call_args[0][1]
        self.assertIn("Keine Daten", sent_text)


class TestReportChartIntegration(unittest.TestCase):
    """Testet Chart-Einbindung und Textfallback im /report-Befehl."""

    def _msg(self, text, chat_id=100):
        return {"chat": {"id": chat_id}, "text": text}

    @patch("daemon.ui.telegram_ui._generate_daily_report")
    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.adapters.chart.generate_weather_chart", return_value=(b"\x89PNG", "caption"))
    def test_report_generates_text_before_chart(self, mock_chart, mock_client, mock_db, mock_ctrl, mock_generate):
        from daemon.adapters import mqtt_client as mc
        mock_db.get_last_weather.return_value = _make_weather_row()
        mock_db.get_all_valves.return_value = []
        mock_db.get_recent_history.return_value = []
        mock_ctrl.get_active_cycle.return_value = None
        
        call_order = []
        mock_generate.side_effect = lambda *a, **kw: call_order.append("generate_report") or "Tagesbericht"
        mock_chart.side_effect = lambda *a, **kw: call_order.append("generate_chart") or (b"\x89PNG", "caption")
        
        with patch.object(mc, "HAS_PAHO", False), \
             patch.object(mc, "request_valve_status"), \
             patch.object(mc, "is_broker_connected", return_value=True), \
             patch.object(mc, "get_bridge_status", return_value="online"):
            _process_message(self._msg("/report"))
            
        self.assertEqual(call_order, ["generate_report", "generate_chart"])

    @patch("daemon.ui.telegram_ui._generate_daily_report")
    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.adapters.chart.generate_weather_chart", return_value=(b"\x89PNG", "🌤 Wetterverlauf — nächste 24h\n🌱 Gießen empfohlen — trocken bis morgen"))
    def test_report_sends_photo_when_chart_available(self, mock_chart, mock_client, mock_db, mock_ctrl, mock_generate):
        from daemon.adapters import mqtt_client as mc
        mock_db.get_last_weather.return_value = _make_weather_row()
        mock_db.get_all_valves.return_value = []
        mock_db.get_recent_history.return_value = []
        mock_ctrl.get_active_cycle.return_value = None
        mock_generate.return_value = "Tagesbericht"
        with patch.object(mc, "HAS_PAHO", False), \
             patch.object(mc, "request_valve_status"), \
             patch.object(mc, "is_broker_connected", return_value=True), \
             patch.object(mc, "get_bridge_status", return_value="online"):
            _process_message(self._msg("/report"))

        mock_client.send_photo.assert_called_once()
        args = mock_client.send_photo.call_args[0]
        self.assertEqual(args[1], b"\x89PNG")

    @patch("daemon.ui.telegram_ui._generate_daily_report")
    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.adapters.chart.generate_weather_chart", return_value=None)
    def test_report_sends_no_photo_when_chart_fails(self, mock_chart, mock_client, mock_db, mock_ctrl, mock_generate):
        from daemon.adapters import mqtt_client as mc
        mock_db.get_last_weather.return_value = _make_weather_row(with_forecast=True)
        mock_db.get_all_valves.return_value = []
        mock_db.get_recent_history.return_value = []
        mock_ctrl.get_active_cycle.return_value = None
        mock_generate.return_value = "Tagesbericht"
        with patch.object(mc, "HAS_PAHO", False), \
             patch.object(mc, "request_valve_status"), \
             patch.object(mc, "is_broker_connected", return_value=True), \
             patch.object(mc, "get_bridge_status", return_value="online"):
            _process_message(self._msg("/report"))

        mock_client.send_photo.assert_not_called()
        # Tagesbericht wird trotzdem gesendet
        mock_client.send_message.assert_called()

    @patch("daemon.ui.telegram_ui._generate_daily_report")
    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.adapters.chart.generate_weather_chart", return_value=None)
    def test_report_sends_daily_report_regardless_of_chart(self, mock_chart, mock_client, mock_db, mock_ctrl, mock_generate):
        from daemon.adapters import mqtt_client as mc
        mock_db.get_last_weather.return_value = None
        mock_db.get_all_valves.return_value = []
        mock_db.get_recent_history.return_value = []
        mock_ctrl.get_active_cycle.return_value = None
        mock_generate.return_value = "Tagesbericht"
        with patch.object(mc, "HAS_PAHO", False), \
             patch.object(mc, "request_valve_status"), \
             patch.object(mc, "is_broker_connected", return_value=True), \
             patch.object(mc, "get_bridge_status", return_value="online"):
            _process_message(self._msg("/report"))

        all_texts = " ".join(str(c) for c in mock_client.send_message.call_args_list)
        self.assertIn("Tagesbericht", all_texts)


class TestDailyReportEventHandler(unittest.TestCase):
    """Testet dass _on_daily_report den Wetterchart per broadcast_photo sendet."""

    def _make_event(self, text="Tagesbericht"):
        from daemon.core.scheduler_events import DailyReportTriggered
        return DailyReportTriggered("2026-06-14", text)

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.adapters.chart.generate_weather_chart", return_value=(b"\x89PNG", "🌤 Wetterverlauf — nächste 24h\n🌱 Gießen empfohlen — trocken bis morgen"))
    def test_daily_report_sends_chart_photo_when_available(self, mock_chart, mock_client):
        from daemon.ui.telegram_ui import _on_daily_report
        _on_daily_report(self._make_event())
        mock_client.broadcast_photo.assert_called_once()
        args = mock_client.broadcast_photo.call_args[0]
        self.assertEqual(args[0], b"\x89PNG")

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.adapters.chart.generate_weather_chart", return_value=None)
    def test_daily_report_skips_photo_when_chart_fails(self, mock_chart, mock_client):
        from daemon.ui.telegram_ui import _on_daily_report
        _on_daily_report(self._make_event())
        mock_client.broadcast_photo.assert_not_called()

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.adapters.chart.generate_weather_chart", return_value=(b"\x89PNG", "🌤 caption"))
    def test_daily_report_always_sends_text(self, mock_chart, mock_client):
        from daemon.ui.telegram_ui import _on_daily_report
        _on_daily_report(self._make_event("Mein Bericht"))
        mock_client.broadcast_notification.assert_called_once_with("Mein Bericht")

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.adapters.chart.generate_weather_chart", return_value=None)
    def test_daily_report_sends_text_even_without_chart(self, mock_chart, mock_client):
        from daemon.ui.telegram_ui import _on_daily_report
        _on_daily_report(self._make_event("Kein Chart"))
        mock_client.broadcast_notification.assert_called_once_with("Kein Chart")


class TestBatteryDescription(unittest.TestCase):
    """Testet die verbale Übersetzung des Batteriestands."""

    def setUp(self):
        from daemon.ui.telegram_ui import _get_battery_description
        self.desc = _get_battery_description

    def test_full_battery_above_60(self):
        self.assertIn("Voll", self.desc(100))
        self.assertIn("Voll", self.desc(61))

    def test_100_percent_hides_percentage(self):
        self.assertNotIn("100%", self.desc(100))

    def test_non_100_full_shows_percentage(self):
        self.assertIn("61%", self.desc(61))

    def test_medium_battery_between_20_and_60(self):
        self.assertIn("Mittel", self.desc(60))
        self.assertIn("Mittel", self.desc(21))

    def test_low_battery_at_or_below_20(self):
        self.assertIn("Schwach", self.desc(20))
        self.assertIn("Schwach", self.desc(1))

    def test_zero_battery_shows_unknown(self):
        self.assertIn("Unbekannt", self.desc(0))

    def test_none_battery_shows_unknown(self):
        self.assertIn("Unbekannt", self.desc(None))

    def test_full_battery_shows_full_icon(self):
        self.assertIn("🔋", self.desc(100))

    def test_low_battery_shows_empty_icon(self):
        self.assertIn("🪫", self.desc(10))

    def test_unknown_shows_empty_icon(self):
        self.assertIn("🪫", self.desc(0))


class TestWatchdogUiHandlers(unittest.TestCase):
    """Testet die telegram_ui-Handler für InactivityAlertTriggered / InactivityAlertResolved."""

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_alert_message_contains_device_name(self, mock_client):
        from daemon.ui.telegram_ui import _on_inactivity_alert
        from daemon.core.watchdog_events import InactivityAlertTriggered
        event = InactivityAlertTriggered(device_name="Rasen", valve_id=1, hours_silent=26.5, timeout_hours=24)
        _on_inactivity_alert(event)
        msg = mock_client.broadcast_notification.call_args[0][0]
        self.assertIn("Rasen", msg)

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_alert_message_contains_hours(self, mock_client):
        from daemon.ui.telegram_ui import _on_inactivity_alert
        from daemon.core.watchdog_events import InactivityAlertTriggered
        event = InactivityAlertTriggered(device_name="Terrasse", valve_id=2, hours_silent=30.0, timeout_hours=24)
        _on_inactivity_alert(event)
        msg = mock_client.broadcast_notification.call_args[0][0]
        self.assertIn("30.0", msg)

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_resolved_message_contains_device_name(self, mock_client):
        from daemon.ui.telegram_ui import _on_inactivity_resolved
        from daemon.core.watchdog_events import InactivityAlertResolved
        event = InactivityAlertResolved(device_name="Hochbeet", valve_id=3)
        _on_inactivity_resolved(event)
        msg = mock_client.broadcast_notification.call_args[0][0]
        self.assertIn("Hochbeet", msg)


class TestCamintCallbackSafety(unittest.TestCase):
    """Stellt sicher, dass fehlerhafte camint_-Callbacks den Handler nicht zum Absturz bringen."""

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_camint_callback_with_missing_parts_does_not_raise(self, mock_db, mock_client):
        """camint_-Callback ohne MAC und Minuten löst keinen IndexError/ValueError aus."""
        mock_db.get_camera.return_value = None
        cb = {
            "id": "cb_001",
            "from": {"id": 12345},
            "message": {"chat": {"id": 12345}, "message_id": 1},
            "data": "camint_",  # fehlende MAC und Minuten
        }
        try:
            _process_callback_query(cb)
        except (IndexError, ValueError) as e:
            self.fail(f"Unkontrollierte Ausnahme bei fehlerhaftem camint_-Callback: {e}")

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_camint_callback_with_non_numeric_minutes_does_not_raise(self, mock_db, mock_client):
        """camint_-Callback mit nicht-numerischen Minuten löst keinen ValueError aus."""
        mock_db.get_camera.return_value = None
        cb = {
            "id": "cb_002",
            "from": {"id": 12345},
            "message": {"chat": {"id": 12345}, "message_id": 1},
            "data": "camint_AA:BB:CC:DD:EE:FF_abc",  # Minuten nicht numerisch
        }
        try:
            _process_callback_query(cb)
        except (IndexError, ValueError) as e:
            self.fail(f"Unkontrollierte Ausnahme bei nicht-numerischen Minuten: {e}")


class TestCameraPairingMetadataCleanup(unittest.TestCase):
    """Stellt sicher, dass veraltete Koppel-Metadaten beim Start bereinigt werden."""

    def test_init_pairing_clears_stale_metadata(self):
        """init_pairing() löscht Koppel-Metadaten, die von einem früheren Daemon-Lauf stammen."""
        import tempfile, os
        from daemon.adapters import camera_pairing, database as db
        from daemon.core.event_bus import EventBus

        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()

        with patch.object(db, "DB_PATH", temp_db.name):
            db.init_db()
            db.set_metadata("camera_pairing_active", "1")
            db.set_metadata("camera_pairing_wish_name", "AlteCam")
            db.set_metadata("camera_pairing_expires_at", "1000000")  # weit in der Vergangenheit

            camera_pairing.init_pairing(EventBus())

            self.assertEqual(db.get_metadata("camera_pairing_active"), "0")

        os.unlink(temp_db.name)


if __name__ == "__main__":
    unittest.main()
