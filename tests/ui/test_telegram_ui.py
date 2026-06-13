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


class TestTelegramBotStartup(unittest.TestCase):
    """Smoke-tests that start_bot() wires up without AttributeError.

    Regression guard: a missing function on an imported module (e.g. scheduler.
    register_notification_callback) would previously crash the daemon at runtime
    but was invisible to the test suite.
    """

    def test_start_bot_does_not_raise(self):
        from unittest.mock import patch
        from daemon.ui import telegram_bot
        with patch("daemon.ui.telegram_client.register_update_callback"), \
             patch("daemon.ui.telegram_client.start_polling"):
            telegram_bot.start_bot()

    def test_broadcast_notification_delegates_to_client(self):
        from unittest.mock import patch, call
        from daemon.ui import telegram_bot
        with patch("daemon.ui.telegram_client.broadcast_notification") as mock_bc:
            telegram_bot.broadcast_notification("test message")
            mock_bc.assert_called_once_with("test message")


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

    @patch("daemon.ui.telegram_ui.scheduler")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_shows_jetzt_line(self, mock_client, mock_db, mock_scheduler):
        from daemon.adapters import mqtt_client as mc
        mock_db.get_last_weather.return_value = _make_weather_row()
        mock_db.get_all_valves.return_value = []
        mock_db.get_recent_history.return_value = []
        mock_scheduler.get_active_cycle.return_value = None
        with patch.object(mc, "HAS_PAHO", False), \
             patch.object(mc, "request_valve_status"), \
             patch.object(mc, "is_broker_connected", return_value=True), \
             patch.object(mc, "get_bridge_status", return_value="online"):
            _process_message(self._msg("/status"))

        sent_text = mock_client.send_message.call_args[0][1]
        self.assertIn("Jetzt", sent_text)

    @patch("daemon.ui.telegram_ui.scheduler")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_shows_next_hour_line(self, mock_client, mock_db, mock_scheduler):
        from daemon.adapters import mqtt_client as mc
        mock_db.get_last_weather.return_value = _make_weather_row(with_forecast=True)
        mock_db.get_all_valves.return_value = []
        mock_db.get_recent_history.return_value = []
        mock_scheduler.get_active_cycle.return_value = None
        with patch.object(mc, "HAS_PAHO", False), \
             patch.object(mc, "request_valve_status"), \
             patch.object(mc, "is_broker_connected", return_value=True), \
             patch.object(mc, "get_bridge_status", return_value="online"):
            _process_message(self._msg("/status"))

        sent_text = mock_client.send_message.call_args[0][1]
        self.assertIn("15:00", sent_text)  # nächste Stunde aus Forecast-Index 1

    @patch("daemon.ui.telegram_ui.scheduler")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_without_forecast_shows_no_next_hour(self, mock_client, mock_db, mock_scheduler):
        from daemon.adapters import mqtt_client as mc
        mock_db.get_last_weather.return_value = _make_weather_row(with_forecast=False)
        mock_db.get_all_valves.return_value = []
        mock_db.get_recent_history.return_value = []
        mock_scheduler.get_active_cycle.return_value = None
        with patch.object(mc, "HAS_PAHO", False), \
             patch.object(mc, "request_valve_status"), \
             patch.object(mc, "is_broker_connected", return_value=True), \
             patch.object(mc, "get_bridge_status", return_value="online"):
            _process_message(self._msg("/status"))

        sent_text = mock_client.send_message.call_args[0][1]
        # "Jetzt" must still appear; "🔜" must not (no forecast)
        self.assertIn("Jetzt", sent_text)
        self.assertNotIn("🔜", sent_text)

    @patch("daemon.ui.telegram_ui.scheduler")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_no_weather_shows_fallback(self, mock_client, mock_db, mock_scheduler):
        from daemon.adapters import mqtt_client as mc
        mock_db.get_last_weather.return_value = None
        mock_db.get_all_valves.return_value = []
        mock_db.get_recent_history.return_value = []
        mock_scheduler.get_active_cycle.return_value = None
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

    @patch("daemon.ui.telegram_ui.scheduler")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.adapters.chart.generate_weather_chart", return_value=b"\x89PNG")
    def test_report_sends_photo_when_chart_available(self, mock_chart, mock_client, mock_db, mock_sched):
        from daemon.adapters import mqtt_client as mc
        mock_db.get_last_weather.return_value = _make_weather_row()
        mock_db.get_all_valves.return_value = []
        mock_db.get_recent_history.return_value = []
        mock_sched.get_active_cycle.return_value = None
        mock_sched.generate_daily_report.return_value = "Tagesbericht"
        with patch.object(mc, "HAS_PAHO", False), \
             patch.object(mc, "request_valve_status"), \
             patch.object(mc, "is_broker_connected", return_value=True), \
             patch.object(mc, "get_bridge_status", return_value="online"):
            _process_message(self._msg("/report"))

        mock_client.send_photo.assert_called_once()
        args = mock_client.send_photo.call_args[0]
        self.assertEqual(args[1], b"\x89PNG")

    @patch("daemon.ui.telegram_ui.scheduler")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.adapters.chart.generate_weather_chart", return_value=None)
    def test_report_sends_text_fallback_when_chart_fails(self, mock_chart, mock_client, mock_db, mock_sched):
        from daemon.adapters import mqtt_client as mc
        mock_db.get_last_weather.return_value = _make_weather_row(with_forecast=True)
        mock_db.get_all_valves.return_value = []
        mock_db.get_recent_history.return_value = []
        mock_sched.get_active_cycle.return_value = None
        mock_sched.generate_daily_report.return_value = "Tagesbericht"
        with patch.object(mc, "HAS_PAHO", False), \
             patch.object(mc, "request_valve_status"), \
             patch.object(mc, "is_broker_connected", return_value=True), \
             patch.object(mc, "get_bridge_status", return_value="online"):
            _process_message(self._msg("/report"))

        mock_client.send_photo.assert_not_called()
        # Textfallback must contain hourly data
        all_texts = " ".join(str(c) for c in mock_client.send_message.call_args_list)
        self.assertIn("Wetterverlauf", all_texts)

    @patch("daemon.ui.telegram_ui.scheduler")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.adapters.chart.generate_weather_chart", return_value=None)
    def test_report_sends_daily_report_regardless_of_chart(self, mock_chart, mock_client, mock_db, mock_sched):
        from daemon.adapters import mqtt_client as mc
        mock_db.get_last_weather.return_value = None
        mock_db.get_all_valves.return_value = []
        mock_db.get_recent_history.return_value = []
        mock_sched.get_active_cycle.return_value = None
        mock_sched.generate_daily_report.return_value = "Tagesbericht"
        with patch.object(mc, "HAS_PAHO", False), \
             patch.object(mc, "request_valve_status"), \
             patch.object(mc, "is_broker_connected", return_value=True), \
             patch.object(mc, "get_bridge_status", return_value="online"):
            _process_message(self._msg("/report"))

        all_texts = " ".join(str(c) for c in mock_client.send_message.call_args_list)
        self.assertIn("Tagesbericht", all_texts)


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


if __name__ == "__main__":
    unittest.main()
