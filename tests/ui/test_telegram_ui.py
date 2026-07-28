import json as _json_module
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
    edit_states,
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

class TestValveFormattingMarkdownSafety(unittest.TestCase):
    """Regression: ein mqtt_name mit Unterstrich (z.B. valve_ffff) darf parse_mode=Markdown
    nicht brechen — sonst lehnt Telegram die ganze /status-Nachricht mit HTTP 400 ab."""

    def test_expanded_valve_id_is_markdown_safe(self):
        from daemon.ui import telegram_ui
        valve = {"wish_name": "Rechts Nebelregen", "mqtt_name": "valve_ffff",
                 "battery": 100, "linkquality": 0, "last_update": None,
                 "valve_abnormal_state": "normal"}
        out = telegram_ui._format_valve_expanded(valve, "red")
        # Technische ID muss in einem Code-Span stehen → Unterstrich wird literal.
        self.assertIn("`valve_ffff`", out)
        # Außerhalb von Code-Spans dürfen keine ungeraden Unterstriche stehen.
        outside = out.replace("`valve_ffff`", "")
        self.assertEqual(outside.count("_") % 2, 0)

    def test_md_escape_escapes_legacy_specials(self):
        from daemon.ui import telegram_ui
        self.assertEqual(telegram_ui._md_escape("a_b*c`d[e"), "a\\_b\\*c\\`d\\[e")

    def test_md_escape_handles_none(self):
        from daemon.ui import telegram_ui
        self.assertEqual(telegram_ui._md_escape(None), "")

    def test_compact_valve_escapes_wish_name(self):
        from daemon.ui import telegram_ui
        valve = {"wish_name": "Beet_1", "battery": 100, "linkquality": 200}
        out = telegram_ui._format_valve_compact(valve)
        self.assertIn("Beet\\_1", out)

    def test_expanded_valve_escapes_wish_name(self):
        from daemon.ui import telegram_ui
        valve = {"wish_name": "A_B", "mqtt_name": "valve_ffff", "battery": 100,
                 "linkquality": 0, "last_update": None, "valve_abnormal_state": "normal"}
        out = telegram_ui._format_valve_expanded(valve, "red")
        self.assertIn("A\\_B", out)

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
        row = kb["inline_keyboard"][0]
        delete_btn = next((b for b in row if b["callback_data"] == "sched_delete_ask_3"), None)
        self.assertIsNotNone(delete_btn, "Kein Lösch-Button mit sched_delete_ask_3 gefunden")

    def test_add_button_is_last_row(self):
        kb = get_schedules_inline_keyboard([self._s(1, "Test", "07:00", 1)])
        self.assertEqual(kb["inline_keyboard"][-1][0]["callback_data"], "wiz_start")

    def test_multiple_schedules_generate_correct_row_count(self):
        schedules = [self._s(1, "A", "07:00", 1), self._s(2, "B", "20:00", 0)]
        kb = get_schedules_inline_keyboard(schedules)
        # Feature 0031: Sofort-Nebel-Zeile entfernt → 2 Zeitplan-Zeilen + Add-Zeile
        self.assertEqual(len(kb["inline_keyboard"]), 3)

    def test_no_sofort_nebel_row(self):
        """Feature 0031: Die Zeitplan-Ansicht enthält keine Sofort-Nebel-Zeile mehr."""
        kb = get_schedules_inline_keyboard([self._s(1, "A", "07:00", 1)])
        all_cb = [b.get("callback_data") for row in kb["inline_keyboard"] for b in row]
        self.assertNotIn("nebel_now", all_cb)

class TestSchedulesMarkdownSafety(unittest.TestCase):
    """Zeitplan-Namen mit Markdown-Sonderzeichen dürfen die Nachricht nicht zerschießen (HTTP 400)."""

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_schedule_name_with_underscore_is_escaped(self, mock_db, mock_client):
        from daemon.ui.telegram_ui import handle_schedules
        mock_db.get_schedules.return_value = [{
            "id": 1, "name": "valve_report_test", "time": "06:00",
            "days": "everyday", "duration_minutes": 12,
            "target_volume_liters": 30, "is_active": 1,
        }]
        handle_schedules(100)
        text = mock_client.send_message.call_args[0][1]
        self.assertIn(r"valve\_report\_test", text)        # escaped → Markdown-sicher
        self.assertNotIn("valve_report_test", text)        # roher Name darf nicht im Markdown-Text stehen

class TestScheduleEditFlow(unittest.TestCase):

    def _cb(self, data, chat_id=100, msg_id=1):
        return {"id": "cb1", "data": data, "message": {"chat": {"id": chat_id}, "message_id": msg_id}}

    def _msg(self, text, chat_id=100):
        return {"chat": {"id": chat_id}, "text": text, "message_id": 1}

    def _schedule(self, id=7, name="Abend", time="20:00", days="Mon", dur=15, vol=0, active=1):
        return {"id": id, "name": name, "time": time, "days": days,
                "duration_minutes": dur, "target_volume_liters": vol, "is_active": active}

    def setUp(self):
        from daemon.ui.telegram_ui import edit_states
        edit_states.clear()

    def tearDown(self):
        from daemon.ui.telegram_ui import edit_states
        edit_states.clear()

    def test_edit_button_in_keyboard(self):
        """Jeder Zeitplan hat einen ✏️-Button mit sched_edit_ID Callback."""
        kb = get_schedules_inline_keyboard([{"id": 7, "name": "Abend", "time": "20:00", "is_active": 1}])
        row = kb["inline_keyboard"][0]
        callbacks = [b["callback_data"] for b in row]
        self.assertIn("sched_edit_7", callbacks)
        edit_btn = next(b for b in row if b["callback_data"] == "sched_edit_7")
        self.assertEqual(edit_btn["text"], "✏️")

    def test_delete_button_still_present(self):
        """🗑️ Button ist nach dem Hinzufügen des Edit-Buttons weiterhin vorhanden."""
        kb = get_schedules_inline_keyboard([{"id": 7, "name": "Abend", "time": "20:00", "is_active": 1}])
        row = kb["inline_keyboard"][0]
        callbacks = [b["callback_data"] for b in row]
        self.assertIn("sched_delete_ask_7", callbacks)

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_sched_edit_zeigt_feld_auswahlmenue(self, mock_client, mock_db):
        """sched_edit_7 zeigt ein Menü mit den bearbeitbaren Feldern."""
        mock_db.get_schedule_by_id.return_value = self._schedule()
        _process_callback_query(self._cb("sched_edit_7"))
        mock_client.edit_message_text.assert_called_once()
        text = mock_client.edit_message_text.call_args[0][2]
        self.assertIn("✏️", text)
        kb = mock_client.edit_message_text.call_args[0][3]
        callbacks = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
        self.assertIn("sched_editfield_duration_7", callbacks)
        self.assertIn("sched_editfield_time_7", callbacks)
        self.assertIn("sched_editfield_days_7", callbacks)

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_sched_edit_unbekannte_id_zeigt_alert(self, mock_client, mock_db):
        """sched_edit_99 zeigt Alert wenn Zeitplan nicht gefunden."""
        mock_db.get_schedule_by_id.return_value = None
        _process_callback_query(self._cb("sched_edit_99"))
        mock_client.edit_message_text.assert_not_called()
        mock_client.answer_callback_query.assert_called()

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_sched_edit_cancel_schliesst_dialog(self, mock_client, mock_db):
        """sched_edit_cancel schließt den Edit-Dialog ohne Änderung."""
        mock_db.get_schedules.return_value = []
        _process_callback_query(self._cb("sched_edit_cancel"))
        mock_client.update_schedule = lambda *a: None
        mock_db.update_schedule.assert_not_called()
        mock_client.answer_callback_query.assert_called()

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
        # Ticket cy1: Löschen läuft jetzt über den DeleteConfirmAssistent (Inline-Dialog).
        mock_db.get_schedules.return_value = [self._schedule()]
        _process_callback_query(self._cb("sched_delete_ask_5"))
        state = _state_get(delete_states, 100)
        self.assertIsNotNone(state)
        self.assertIn("assistent", state)
        self.assertEqual(state["assistent"].data["schedule_id"], 5)
        self.assertEqual(state["assistent"].data["name"], "Morgen")

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_delete_ask_shows_inline_confirm(self, mock_client, mock_db):
        mock_db.get_schedules.return_value = [self._schedule()]
        _process_callback_query(self._cb("sched_delete_ask_5"))
        kb = mock_client.edit_message_text.call_args[0][3]   # Inline-Dialog (ADR 0039)
        cbs = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
        self.assertIn("sched_del_yes", cbs)
        self.assertIn("sched_del_no", cbs)

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_delete_ask_unknown_id_shows_alert(self, mock_client, mock_db):
        mock_db.get_schedules.return_value = []
        _process_callback_query(self._cb("sched_delete_ask_99"))
        mock_client.answer_callback_query.assert_called_once_with("cb1", "Zeitplan nicht gefunden", show_alert=True)
        self.assertIsNone(_state_get(delete_states, 100))

class TestContextSensitiveWateringHint(unittest.TestCase):
    """Feature 0020: Kontextsensible Rückfrage vor manuellem Guss."""

    def setUp(self):
        manual_states.clear()

    def tearDown(self):
        manual_states.clear()

    def _cb(self, data, chat_id=100, msg_id=1):
        return {"id": "cb1", "data": data, "message": {"chat": {"id": chat_id}, "message_id": msg_id}}

    def _decision(self, skip):
        from daemon.core.watering_advice import WateringDecision
        return WateringDecision(
            factor=0.0 if skip else 1.0,
            verdict="🌧 Kein Gießen nötig" if skip else "💧 Gießen empfohlen",
            reasons=["8.0 mm Regen erwartet (Schwelle 5.0 mm)."],
            skip=skip,
        )

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_water_anyway_without_pending_is_noop(self, mock_client, mock_ctrl):
        """Veralteter/doppelter water_anyway-Tap: kein Start, fremder State bleibt unangetastet."""
        _state_set(manual_states, 100, {"step": 1, "mqtt_name": "garden_valve"})  # frischer Wizard

        _process_callback_query(self._cb("water_anyway"))

        mock_ctrl.start_watering.assert_not_called()
        remaining = _state_get(manual_states, 100)   # fremder Wizard NICHT gelöscht
        self.assertIsNotNone(remaining)
        self.assertEqual(remaining["step"], 1)

class TestNebelUI(unittest.TestCase):
    """Sofort-Nebel, Wizard-Nebel-Zweig und Benachrichtigungen (Feature 0032)."""

    def setUp(self):
        wizard_states.clear()
        manual_states.clear()

    def tearDown(self):
        wizard_states.clear()
        manual_states.clear()

    def _cb(self, data, chat_id=100, msg_id=1):
        return {"id": "cb1", "data": data, "message": {"chat": {"id": chat_id}, "message_id": msg_id}}

    def _seed_nebel_flow(self, on_seconds=20, pause_minutes=5):
        """Setzt den Sofort-Nebel-Flow-State (Ventil + Takt) wie nach der Takt-Auswahl (Feature 0031)."""
        _state_set(manual_states, 100, {
            "flow": "nebel_now",
            "valve": {"id": 3, "wish_name": "Terrasse", "mqtt_name": "terrace_mist"},
            "on_seconds": on_seconds,
            "pause_minutes": pause_minutes,
        })

    @patch("daemon.ui.telegram_ui._nebel_ctrl")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_nebel_stop_calls_controller(self, mock_client, mock_nebel):
        mock_nebel.stop.return_value = (True, "gestoppt")
        _process_callback_query(self._cb("nebel_stop"))
        mock_nebel.stop.assert_called_once()

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_on_nebel_started_broadcasts(self, mock_client, mock_db):
        from daemon.ui.telegram_ui import _render_nebel_interval_started
        from daemon.core.nebel_events import NebelIntervalStarted
        mock_db.get_all_valves.return_value = [{"wish_name": "Terrasse", "mqtt_name": "terrace_mist"}]
        msg = _render_nebel_interval_started(NebelIntervalStarted("terrace_mist", "nebel", "2026-06-27T18:00:00"))
        self.assertIn("Nebel-Intervall", msg)
        self.assertIn("Terrasse", msg)

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_on_nebel_ended_broadcasts(self, mock_client, mock_db):
        from daemon.ui.telegram_ui import _render_nebel_interval_ended
        from daemon.core.nebel_events import NebelIntervalEnded
        mock_db.get_all_valves.return_value = [{"wish_name": "Terrasse", "mqtt_name": "terrace_mist"}]
        msg = _render_nebel_interval_ended(NebelIntervalEnded("terrace_mist", "nebel", 45, 9, "fertig"))
        self.assertIn("9", msg)
        self.assertIn("Terrasse", msg)

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_wiz_mode_nebel_sets_state(self, mock_client, mock_db):
        # Ticket cy1: Nebel läuft jetzt über den ScheduleAssistent (mode="nebel").
        mock_db.get_all_valves.return_value = [{"id": 7, "wish_name": "Terrasse"}]
        _process_callback_query(self._cb("wiz_mode_nebel"))
        state = _state_get(wizard_states, 100)
        self.assertIsNotNone(state)
        self.assertIn("assistent", state)
        self.assertEqual(state["assistent"].data["mode"], "nebel")
        self.assertEqual(state["assistent"].step, "name")

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_wiz_mode_nebel_without_valve_aborts(self, mock_client, mock_db):
        mock_db.get_all_valves.return_value = []
        _process_callback_query(self._cb("wiz_mode_nebel"))
        self.assertIsNone(_state_get(wizard_states, 100))
        self.assertIn("kein Ventil", mock_client.edit_message_text.call_args.args[2])

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

    def test_register_telegram_commands_ruft_set_my_commands_auf(self):
        """register_telegram_commands registriert das aufgeräumte Menü (Feature 0031)."""
        from daemon.ui import telegram_client
        with patch.object(telegram_client, "set_my_commands") as mock_cmds:
            from daemon.main import register_telegram_commands
            register_telegram_commands()
            mock_cmds.assert_called_once()
            commands = mock_cmds.call_args[0][0]
            self.assertIsInstance(commands, list)
            cmd_names = [c["command"] for c in commands]
            self.assertEqual(cmd_names, ["status", "tagesbericht", "update", "diagnose"])

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

def _make_valve(wish_name="Terrasse", mqtt_name="garden_valve",
                battery=100, lqi=150,
                last_update="2026-06-18T14:00:00",
                abnormal="normal"):
    return {"wish_name": wish_name, "mqtt_name": mqtt_name,
            "battery": battery, "linkquality": lqi,
            "last_update": last_update, "valve_abnormal_state": abnormal}

def _status_call_args(mock_client, mock_db, mock_ctrl, *,
                      valves=None, services_ok=True, broker=True, bridge=True):
    """Ruft /status ab und gibt den gesendeten Text zurück."""
    from daemon.adapters import mqtt_client as mc
    mock_db.get_all_valves.return_value = valves or []
    mock_db.get_all_cameras.return_value = []
    mock_db.get_last_weather.return_value = None
    mock_db.get_recent_history.return_value = []
    mock_ctrl.get_active_cycle.return_value = None

    with patch.object(mc, "HAS_PAHO", not services_ok or True), \
         patch.object(mc, "request_valve_status"), \
         patch.object(mc, "is_broker_connected", return_value=broker), \
         patch.object(mc, "get_bridge_status", return_value="online" if bridge else "offline"):
        _process_message({"chat": {"id": 100}, "text": "/status"})

    return mock_client.send_message.call_args[0][1]

class TestStatusGartenAmpel(unittest.TestCase):
    """Testet Garten-Ampel-Headline und Progressive Disclosure im /status-Befehl."""

    def setUp(self):
        from daemon.adapters import mqtt_client as mc
        self._mc = mc

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_headline_gruen_wenn_alles_ok(self, mock_client, mock_db, mock_ctrl):
        """Wenn alle Ventile ok und Dienste aktiv: 🟢 in der Headline."""
        text = _status_call_args(mock_client, mock_db, mock_ctrl,
                                 valves=[_make_valve()])
        self.assertIn("🟢", text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_headline_gelb_bei_schwacher_batterie(self, mock_client, mock_db, mock_ctrl):
        """Batterie <= 20 % → 🟡 in der Headline (kein 🔴)."""
        text = _status_call_args(mock_client, mock_db, mock_ctrl,
                                 valves=[_make_valve(battery=20)])
        self.assertIn("🟡", text)
        self.assertNotIn("🔴", text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_headline_rot_bei_bridge_offline(self, mock_client, mock_db, mock_ctrl):
        """Bridge offline → 🔴 in der Headline."""
        text = _status_call_args(mock_client, mock_db, mock_ctrl,
                                 valves=[_make_valve()], bridge=False)
        self.assertIn("🔴", text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_headline_rot_bei_ventil_anomalie(self, mock_client, mock_db, mock_ctrl):
        """Ventil-Anomalie → 🔴 in der Headline."""
        text = _status_call_args(mock_client, mock_db, mock_ctrl,
                                 valves=[_make_valve(abnormal="stuck_open")])
        self.assertIn("🔴", text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_gruen_ventil_kein_mqtt_name_sichtbar(self, mock_client, mock_db, mock_ctrl):
        """Grünes Ventil: mqtt_name (technische ID) nicht in der Nachricht."""
        text = _status_call_args(mock_client, mock_db, mock_ctrl,
                                 valves=[_make_valve(mqtt_name="garden_valve")])
        self.assertNotIn("garden_valve", text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_gruen_ventil_kein_lqi_zahl_sichtbar(self, mock_client, mock_db, mock_ctrl):
        """Grünes Ventil: LQI-Zahl nicht sichtbar (nur qualitativ)."""
        text = _status_call_args(mock_client, mock_db, mock_ctrl,
                                 valves=[_make_valve(lqi=150)])
        self.assertNotIn("150 LQI", text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_nicht_gruen_ventil_zeigt_mqtt_name(self, mock_client, mock_db, mock_ctrl):
        """Nicht-grünes Ventil (schwache Batterie): mqtt_name sichtbar."""
        text = _status_call_args(mock_client, mock_db, mock_ctrl,
                                 valves=[_make_valve(battery=10, mqtt_name="garden_valve")])
        self.assertIn("garden_valve", text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_nicht_gruen_ventil_zeigt_lqi_zahl(self, mock_client, mock_db, mock_ctrl):
        """Nicht-grünes Ventil: LQI-Zahl sichtbar."""
        text = _status_call_args(mock_client, mock_db, mock_ctrl,
                                 valves=[_make_valve(battery=10, lqi=45)])
        self.assertIn("45", text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_kein_doppelasterisk(self, mock_client, mock_db, mock_ctrl):
        """Status-Nachricht enthält kein ** (Markdown-Regression)."""
        text = _status_call_args(mock_client, mock_db, mock_ctrl,
                                 valves=[_make_valve()])
        self.assertNotIn("**", text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_keine_sekunden_in_zeitstempel(self, mock_client, mock_db, mock_ctrl):
        """Zeitstempel im Status enthalten kein ':SS'-Muster (keine Sekunden)."""
        import re
        text = _status_call_args(mock_client, mock_db, mock_ctrl,
                                 valves=[_make_valve()])
        self.assertIsNone(re.search(r"\d{2}:\d{2}:\d{2}", text),
                          f"Sekunden gefunden in: {text}")

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
            _process_message(self._msg("/tagesbericht"))
            
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
            _process_message(self._msg("/tagesbericht"))

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
            _process_message(self._msg("/tagesbericht"))

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
            _process_message(self._msg("/tagesbericht"))

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
        from daemon.ui.telegram_ui import _render_inactivity_alert
        from daemon.core.watchdog_events import InactivityAlertTriggered
        event = InactivityAlertTriggered(device_name="Rasen", valve_id=1, hours_silent=26.5, timeout_hours=24)
        msg = _render_inactivity_alert(event)
        self.assertIn("Rasen", msg)

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_alert_message_contains_hours(self, mock_client):
        from daemon.ui.telegram_ui import _render_inactivity_alert
        from daemon.core.watchdog_events import InactivityAlertTriggered
        event = InactivityAlertTriggered(device_name="Terrasse", valve_id=2, hours_silent=30.0, timeout_hours=24)
        msg = _render_inactivity_alert(event)
        self.assertIn("30.0", msg)

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_resolved_message_contains_device_name(self, mock_client):
        from daemon.ui.telegram_ui import _render_inactivity_resolved
        from daemon.core.watchdog_events import InactivityAlertResolved
        event = InactivityAlertResolved(device_name="Hochbeet", valve_id=3)
        msg = _render_inactivity_resolved(event)
        self.assertIn("Hochbeet", msg)

class TestUnexpectedValveUiHandlers(unittest.TestCase):
    """telegram_ui-Handler für UnexpectedValveOpened / UnexpectedValveResolved (Feature 0029)."""

    @patch("daemon.ui.telegram_ui.config.get_setting", return_value=30)
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_opened_notifies_with_wish_name_and_safety_minutes(self, mock_client, mock_db, mock_get):
        from daemon.ui.telegram_ui import _render_unexpected_valve_opened
        from daemon.core.valve_events import UnexpectedValveOpened
        mock_db.get_valve_by_mqtt_name.return_value = {"wish_name": "Rasen"}
        msg = _render_unexpected_valve_opened(UnexpectedValveOpened("garden_valve"))
        self.assertIn("Rasen", msg)
        self.assertIn("von außen geöffnet", msg)
        self.assertIn("30", msg)

    @patch("daemon.ui.telegram_ui.config.get_setting", return_value=30)
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_opened_falls_back_to_mqtt_name(self, mock_client, mock_db, mock_get):
        from daemon.ui.telegram_ui import _render_unexpected_valve_opened
        from daemon.core.valve_events import UnexpectedValveOpened
        mock_db.get_valve_by_mqtt_name.return_value = None
        msg = _render_unexpected_valve_opened(UnexpectedValveOpened("valve_xyz"))
        self.assertIn(r"valve\_xyz", msg)  # Fallback auf mqtt_name, Markdown-escaped

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_resolved_notifies_with_wish_name(self, mock_client, mock_db):
        from daemon.ui.telegram_ui import _render_unexpected_valve_resolved
        from daemon.core.valve_events import UnexpectedValveResolved
        mock_db.get_valve_by_mqtt_name.return_value = {"wish_name": "Hochbeet"}
        msg = _render_unexpected_valve_resolved(UnexpectedValveResolved("garden_valve"))
        self.assertIn("Hochbeet", msg)
        self.assertIn("wieder", msg)

def _make_camera(wish_name="Garten", last_seen=None, sleep_duration_seconds=900,
                  resolution="UXGA", quality=10):
    return {
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "wish_name": wish_name,
        "last_seen": last_seen,
        "sleep_duration_seconds": sleep_duration_seconds,
        "resolution": resolution,
        "quality": quality,
    }

def _status_call(mock_db, mock_ctrl, cameras):
    """Ruft /status auf und gibt den gesendeten Text zurück."""
    from daemon.adapters import mqtt_client as mc
    mock_db.get_all_cameras.return_value = cameras
    mock_db.get_last_weather.return_value = None
    mock_db.get_all_valves.return_value = []
    mock_db.get_recent_history.return_value = []
    mock_ctrl.get_active_cycle.return_value = None
    with patch.object(mc, "HAS_PAHO", False), \
         patch.object(mc, "request_valve_status"), \
         patch.object(mc, "is_broker_connected", return_value=True), \
         patch.object(mc, "get_bridge_status", return_value="online"):
        from daemon.ui.telegram_ui import _process_message
        _process_message({"chat": {"id": 100}, "text": "/status"})

class TestStatusCameraBlock(unittest.TestCase):
    """Testet den Kamera-Abschnitt in der /status-Anzeige."""

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_shows_camera_name(self, mock_client, mock_db, mock_ctrl):
        """Kameraname erscheint im Status-Text."""
        _status_call(mock_db, mock_ctrl, [_make_camera("Terrasse")])
        sent_text = mock_client.send_message.call_args[0][1]
        self.assertIn("Terrasse", sent_text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_camera_online_when_recently_seen(self, mock_client, mock_db, mock_ctrl):
        """Kamera gilt als online wenn last_seen innerhalb sleep_duration_seconds * 2."""
        from datetime import datetime, timezone
        recent = datetime.now(timezone.utc).isoformat()
        _status_call(mock_db, mock_ctrl, [_make_camera(last_seen=recent, sleep_duration_seconds=3600)])
        sent_text = mock_client.send_message.call_args[0][1]
        self.assertIn("🟢", sent_text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_camera_offline_when_long_ago(self, mock_client, mock_db, mock_ctrl):
        """Kamera gilt als offline wenn last_seen älter als sleep_duration_seconds * 2."""
        old_ts = "2020-01-01T00:00:00"
        _status_call(mock_db, mock_ctrl, [_make_camera(last_seen=old_ts, sleep_duration_seconds=900)])
        sent_text = mock_client.send_message.call_args[0][1]
        self.assertIn("🔴", sent_text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_camera_offline_when_never_seen(self, mock_client, mock_db, mock_ctrl):
        """Kamera ohne last_seen wird als nicht verbunden angezeigt."""
        _status_call(mock_db, mock_ctrl, [_make_camera(last_seen=None)])
        sent_text = mock_client.send_message.call_args[0][1]
        self.assertIn("🔴", sent_text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_no_cameras_shows_no_camera_section(self, mock_client, mock_db, mock_ctrl):
        """Ohne Kameras erscheint kein Kamera-Abschnitt im Status."""
        _status_call(mock_db, mock_ctrl, [])
        sent_text = mock_client.send_message.call_args[0][1]
        self.assertNotIn("📷", sent_text)

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

class TestGartenAmpel(unittest.TestCase):
    """Tests für _garden_ampel_level() — Garten-Ampel Gesundheitsmodell."""

    def setUp(self):
        from daemon.ui.telegram_ui import _garden_ampel_level
        self._fn = _garden_ampel_level

    def _valve(self, battery=100, lqi=80, abnormal="normal", last_update="2026-01-01T10:00:00"):
        return {"battery": battery, "linkquality": lqi,
                "valve_abnormal_state": abnormal, "last_update": last_update}

    def test_gruen_wenn_alles_ok(self):
        """Alles grün: Dienste online, Batterie OK, LQI OK, keine Anomalie."""
        result = self._fn([self._valve()], services_ok=True)
        self.assertEqual(result, "green")

    def test_gruen_ohne_ventile(self):
        """Keine Ventile registriert und Dienste ok → grün."""
        self.assertEqual(self._fn([], services_ok=True), "green")

    def test_rot_wenn_dienst_offline(self):
        """services_ok=False → sofort rot, unabhängig von Ventil-Daten."""
        result = self._fn([self._valve()], services_ok=False)
        self.assertEqual(result, "red")

    def test_rot_bei_ventil_anomalie(self):
        """valve_abnormal_state != 'normal' → rot."""
        result = self._fn([self._valve(abnormal="abnormal")], services_ok=True)
        self.assertEqual(result, "red")

    def test_gelb_bei_niedriger_batterie(self):
        """Batterie <= BATTERY_WARNING_THRESHOLD (Standard 20) → gelb."""
        result = self._fn([self._valve(battery=20)], services_ok=True)
        self.assertEqual(result, "yellow")

    def test_gelb_bei_kritischem_lqi(self):
        """LQI < 60 → gelb."""
        result = self._fn([self._valve(lqi=59)], services_ok=True)
        self.assertEqual(result, "yellow")

    def test_lqi_genau_60_ist_nicht_gelb(self):
        """LQI == 60 ist noch ok (Grenze ist < 60)."""
        result = self._fn([self._valve(lqi=60)], services_ok=True)
        self.assertEqual(result, "green")

    def test_rot_gewinnt_ueber_gelb(self):
        """Wenn ein Ventil rot und ein anderes gelb: Gesamtergebnis rot."""
        valves = [self._valve(abnormal="abnormal"), self._valve(battery=10)]
        self.assertEqual(self._fn(valves, services_ok=True), "red")

    def test_gelb_gewinnt_ueber_gruen(self):
        """Wenn ein Ventil gelb und ein anderes grün: Gesamtergebnis gelb."""
        valves = [self._valve(), self._valve(battery=15)]
        self.assertEqual(self._fn(valves, services_ok=True), "yellow")

    def test_rot_wenn_dienst_offline_trotz_guter_ventile(self):
        """Dienst offline schlägt immer durch, auch wenn Ventile OK wären."""
        valves = [self._valve(), self._valve()]
        self.assertEqual(self._fn(valves, services_ok=False), "red")

    def test_rot_wenn_kein_letztes_signal(self):
        """Ventil mit last_update=None (nie kommuniziert) → rot."""
        v = self._valve()
        v["last_update"] = None
        self.assertEqual(self._fn([v], services_ok=True), "red")

    def test_gruen_ventil_mit_letztem_signal_kein_status_gruen(self):
        """_format_valve_compact für grünes Ventil zeigt kein 🪫/0% wenn battery=None."""
        from daemon.ui.telegram_ui import _format_valve_compact
        valve = {"wish_name": "Terrasse", "battery": None, "linkquality": None,
                 "last_update": "2026-06-18T14:00:00", "valve_abnormal_state": "normal"}
        text = _format_valve_compact(valve)
        self.assertNotIn("0 %", text)
        self.assertNotIn("🪫 Leer", text)

class TestEreignisBenachrichtigungen(unittest.TestCase):
    """Tests für Design-System-konforme Event-Benachrichtigungen (Schritt 5)."""

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_watering_started_zeigt_guss_emoji(self, mock_client):
        """Guss-gestartet-Benachrichtigung enthält 🚿, nicht 🟢."""
        from daemon.ui.telegram_ui import _render_watering_started
        from daemon.core.watering_controller import WateringCycleStarted
        event = WateringCycleStarted(duration=15, target_volume=30, source="manual")
        msg = _render_watering_started(event)
        self.assertIn("🚿", msg)
        self.assertNotIn("🟢", msg)

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_watering_completed_volumen_zeigt_menge(self, mock_client):
        """Volumenlimit-Abschluss enthält 🏁 und die geflossene Menge in Liter."""
        from daemon.ui.telegram_ui import _render_watering_completed
        from daemon.core.watering_controller import WateringCycleCompleted
        event = WateringCycleCompleted(duration_run=12, volume_run=28.5,
                                       source="manual", details="Volumenlimit 30 l erreicht")
        msg = _render_watering_completed(event)
        self.assertIn("🏁", msg)
        self.assertIn("l", msg)
        self.assertIn("28", msg)

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_watering_completed_zeitlimit_mit_fehlmenge(self, mock_client):
        """Zeitlimit erreicht, Zielmenge nicht ganz geschafft → 🏁-Abschluss mit Hinweis,
        KEINE Notfall-/Sicherheits-Wortwahl."""
        from daemon.ui.telegram_ui import _render_watering_completed
        from daemon.core.watering_controller import WateringCycleCompleted
        event = WateringCycleCompleted(
            duration_run=10, volume_run=15.0, source="manual",
            details="Zeitlimit von 10 Min erreicht — Zielmenge 20l nicht ganz geschafft (15.0l geflossen).")
        msg = _render_watering_completed(event)
        self.assertIn("🏁", msg)
        self.assertIn("Zielmenge nicht ganz geschafft", msg)
        self.assertNotIn("Notfall", msg)
        self.assertNotIn("Sicherheits-Timer", msg)

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_watering_stopped_zeigt_stopp_emoji(self, mock_client):
        """Guss-gestoppt-Benachrichtigung enthält 🛑, nicht 🔴."""
        from daemon.ui.telegram_ui import _render_watering_stopped
        from daemon.core.watering_controller import WateringCycleStopped
        event = WateringCycleStopped(duration_run=5, volume_run=10.0,
                                     source="manual", details="")
        msg = _render_watering_stopped(event)
        self.assertIn("🛑", msg)
        self.assertNotIn("🔴", msg)

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_watering_skipped_zeigt_regen_emoji(self, mock_client):
        """Regen-Skip enthält 🌧, nicht 🌤️."""
        from daemon.ui.telegram_ui import _render_watering_skipped
        from daemon.core.scheduler_events import WateringSkipped
        event = WateringSkipped(schedule_name="Rasen", details="4 mm Regen")
        msg = _render_watering_skipped(event)
        self.assertIn("🌧", msg)
        self.assertNotIn("🌤️", msg)

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_broadcast_schedule_name_with_underscore_is_escaped(self, mock_client):
        """Zeitplan-Name mit '_' in Skip-/Fehler-Broadcast wird escaped (sonst HTTP 400)."""
        from daemon.ui.telegram_ui import _render_watering_skipped, _render_schedule_failed
        from daemon.core.scheduler_events import WateringSkipped, ScheduleFailed

        msg = _render_watering_skipped(WateringSkipped(schedule_name="valve_report_test", details="4 mm Regen"))
        self.assertIn(r"valve\_report\_test", msg)
        self.assertNotIn("valve_report_test", msg)

        msg = _render_schedule_failed(ScheduleFailed(schedule_name="valve_report_test", details="MQTT-Fehler"))
        self.assertIn(r"valve\_report\_test", msg)
        self.assertNotIn("valve_report_test", msg)

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_watering_failed_keine_ausrufezeichen_kette(self, mock_client):
        """Echte Guss-Fehler-Meldung ist sachlich, kein '!!' oder '!*'."""
        from daemon.ui.telegram_ui import _render_watering_failed
        from daemon.core.watering_controller import WateringCycleFailed
        event = WateringCycleFailed(duration_run=10, volume_run=3.0,
                                    source="schedule",
                                    details="Zielwassermenge von 5l nicht erreicht")
        msg = _render_watering_failed(event)
        self.assertIn("⚠️", msg)
        self.assertNotIn("!!", msg)

class TestHauptmenueButtons(unittest.TestCase):
    """Tests für die Hauptmenü-Button-Texte (Schritt 4 Design-System-Migration)."""

    def test_hauptmenue_hat_guss_button(self):
        """Hauptmenü enthält '🚿 Bewässern' (Feature 0031, gekürzt)."""
        from daemon.ui.telegram_ui import get_main_keyboard
        kb = get_main_keyboard()
        texts = [b["text"] for row in kb["keyboard"] for b in row]
        self.assertIn("🚿 Bewässern", texts)
        self.assertNotIn("🚿 Bewässern starten", texts)

    def test_hauptmenue_hat_stopp_button(self):
        """Hauptmenü enthält '🛑 Stopp' (Feature 0031, gekürzt)."""
        from daemon.ui.telegram_ui import get_main_keyboard
        kb = get_main_keyboard()
        texts = [b["text"] for row in kb["keyboard"] for b in row]
        self.assertIn("🛑 Stopp", texts)
        self.assertNotIn("🛑 Sofort Stopp", texts)

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_guss_button_loest_wizard_aus(self, mock_client, mock_db):
        """'🚿 Bewässern' zeigt die Art-Auswahl (Guss / Sofort-Nebel)."""
        mock_db.get_all_valves.return_value = [_make_valve()]
        _process_message({"chat": {"id": 100}, "text": "🚿 Bewässern"})
        mock_client.send_message.assert_called_once()
        text = mock_client.send_message.call_args[0][1]
        self.assertIn("Bewässer", text)

    @patch("daemon.ui.telegram_ui._nebel_ctrl")
    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_stopp_button_stoppt_guss(self, mock_client, mock_db, mock_ctrl, mock_nebel):
        """'🛑 Stopp' stoppt bei genau einer aktiven Quelle direkt den Guss."""
        mock_ctrl.get_active_valve_names.return_value = ["garden_valve"]
        mock_nebel.get_active_window.return_value = None
        mock_ctrl.stop_watering.return_value = (True, "gestoppt")
        mock_db.get_valve_by_mqtt_name.return_value = _make_valve()
        _process_message({"chat": {"id": 100}, "text": "🛑 Stopp"})
        mock_ctrl.stop_watering.assert_called_once()

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_guss_wizard_schritt1_zeigt_guss_emoji(self, mock_client, mock_db):
        """Art-Auswahl zeigt 🚿 im Titel, nicht 🟢."""
        mock_db.get_all_valves.return_value = [_make_valve()]
        _process_message({"chat": {"id": 100}, "text": "🚿 Bewässern"})
        text = mock_client.send_message.call_args[0][1]
        self.assertIn("🚿", text)
        self.assertNotIn("🟢", text)

class TestKeinDoppelAsterisk(unittest.TestCase):
    """Regression: Kein ** in Nachrichten-Handlern (Telegram Legacy Markdown Bug)."""

    def _msg(self, text, chat_id=100):
        return {"chat": {"id": chat_id}, "text": text}

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_schedules_leer_kein_doppelasterisk(self, mock_client, mock_db):
        """/schedules ohne Einträge erzeugt kein **."""
        mock_db.get_schedules.return_value = []
        _process_message(self._msg("/schedules"))
        for call in mock_client.send_message.call_args_list:
            text = call[0][1] if len(call[0]) > 1 else ""
            self.assertNotIn("**", text, f"** gefunden in: {text[:120]}")

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_schedules_mit_eintraegen_kein_doppelasterisk(self, mock_client, mock_db):
        """/schedules mit Einträgen erzeugt kein **."""
        mock_db.get_schedules.return_value = [
            {"id": 1, "name": "Rasen", "time": "06:00", "days": "Mon,Wed",
             "duration_minutes": 15, "target_volume_liters": 30, "is_active": 1}
        ]
        _process_message(self._msg("/schedules"))
        for call in mock_client.send_message.call_args_list:
            text = call[0][1] if len(call[0]) > 1 else ""
            self.assertNotIn("**", text, f"** gefunden in: {text[:120]}")

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_start_kein_doppelasterisk(self, mock_client):
        """/start erzeugt kein **."""
        _process_message(self._msg("/start"))
        for call in mock_client.send_message.call_args_list:
            text = call[0][1] if len(call[0]) > 1 else ""
            self.assertNotIn("**", text, f"** gefunden in: {text[:120]}")

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_unbekannter_befehl_kein_doppelasterisk(self, mock_client):
        """Unbekannter Befehl erzeugt kein **."""
        _process_message(self._msg("/gibtsNicht"))
        for call in mock_client.send_message.call_args_list:
            text = call[0][1] if len(call[0]) > 1 else ""
            self.assertNotIn("**", text, f"** gefunden in: {text[:120]}")

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_guss_starten_kein_doppelasterisk(self, mock_client, mock_db):
        """Manuellen Guss starten (Schritt 1/2) erzeugt kein **."""
        mock_db.get_all_valves.return_value = [_make_valve()]
        _process_message(self._msg("🚿 Bewässern"))
        for call in mock_client.send_message.call_args_list:
            text = call[0][1] if len(call[0]) > 1 else ""
            self.assertNotIn("**", text, f"** gefunden in: {text[:120]}")

class TestTypingIndikator(unittest.TestCase):
    """Testet dass handle_status und /report den Typing-Indikator vor der Antwort senden."""

    def _msg(self, text, chat_id=100):
        return {"chat": {"id": chat_id}, "from": {"id": 100}, "text": text, "message_id": 1}

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_handle_status_sendet_typing_vor_antwort(self, mock_client, mock_db, mock_ctrl):
        from daemon.adapters import mqtt_client as mc
        mock_db.get_last_weather.return_value = None
        mock_db.get_all_valves.return_value = []
        mock_db.get_all_cameras.return_value = []
        mock_db.get_recent_history.return_value = []
        mock_ctrl.get_active_cycle.return_value = None
        with patch.object(mc, "HAS_PAHO", False), \
             patch.object(mc, "request_valve_status"):
            _process_message(self._msg("/status"))
        mock_client.send_chat_action.assert_called_once_with(100, "typing")

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_report_sendet_typing_vor_bericht(self, mock_client, mock_db, mock_ctrl):
        from daemon.adapters import mqtt_client as mc
        mock_db.get_last_weather.return_value = None
        mock_db.get_all_valves.return_value = []
        mock_ctrl.get_active_cycle.return_value = None
        with patch.object(mc, "HAS_PAHO", False), \
             patch.object(mc, "request_valve_status"), \
             patch("daemon.ui.telegram_ui._generate_daily_report", return_value="Bericht"), \
             patch("daemon.adapters.chart.generate_weather_chart", return_value=None):
            _process_message(self._msg("/tagesbericht"))
        calls = [c[0] for c in mock_client.send_chat_action.call_args_list]
        self.assertIn((100, "typing"), calls)

class TestEinstellungenHandler(unittest.TestCase):
    """Tests für /einstellungen — In-Chat-Konfiguration der drei Schwellenwerte."""

    def _cb(self, data, chat_id=100, msg_id=1):
        return {"id": "cb1", "from": {"id": chat_id}, "data": data,
                "message": {"chat": {"id": chat_id}, "message_id": msg_id}}

    @patch("daemon.config.get_setting", side_effect=lambda n, d: {
        "RAIN_THRESHOLD_MM": 2.5, "BATTERY_WARNING_THRESHOLD": 20, "SAFETY_TIMEOUT_MINUTES": 30
    }.get(n, d))
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_einstellungen_zeigt_aktuelle_werte(self, mock_client, mock_get):
        """handle_einstellungen sendet Nachricht mit den drei aktuellen Werten."""
        from daemon.ui.telegram_ui import handle_einstellungen
        handle_einstellungen(100)
        mock_client.send_message.assert_called_once()
        text = mock_client.send_message.call_args[0][1]
        self.assertIn("2.5", text)
        self.assertIn("20", text)
        self.assertIn("30", text)

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_einstellungen_slash_entfernt(self, mock_client):
        """/einstellungen wurde entfernt (De-dup) — nur noch über den ⚙️-Button erreichbar."""
        _process_message({"chat": {"id": 100}, "from": {"id": 100}, "text": "/einstellungen"})
        text = mock_client.send_message.call_args[0][1]
        self.assertIn("Unbekannter Befehl", text)

    @patch("daemon.config.set_setting")
    @patch("daemon.config.get_setting", return_value=2.0)
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_set_rain_gueltig_speichert(self, mock_client, mock_get, mock_set):
        """set_rain_VALUE-Callback speichert validen Regenschwellen-Wert."""
        _process_callback_query(self._cb("set_rain_4.0"))
        mock_set.assert_called_once_with("RAIN_THRESHOLD_MM", 4.0)

    @patch("daemon.config.set_setting")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_set_rain_ungueltig_abgelehnt(self, mock_client, mock_set):
        """set_rain mit Wert > Maximalwert wird abgewiesen ohne zu speichern."""
        _process_callback_query(self._cb("set_rain_99.0"))
        mock_set.assert_not_called()

    @patch("daemon.config.set_setting")
    @patch("daemon.config.get_setting", return_value=20)
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_set_battery_gueltig_speichert(self, mock_client, mock_get, mock_set):
        """set_battery_VALUE-Callback speichert validen Batterie-Schwellenwert."""
        _process_callback_query(self._cb("set_battery_15"))
        mock_set.assert_called_once_with("BATTERY_WARNING_THRESHOLD", 15)

    @patch("daemon.config.set_setting")
    @patch("daemon.config.get_setting", return_value=30)
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_set_safety_gueltig_speichert(self, mock_client, mock_get, mock_set):
        """set_safety_VALUE-Callback speichert validen Safety-Timeout-Wert."""
        _process_callback_query(self._cb("set_safety_20"))
        mock_set.assert_called_once_with("SAFETY_TIMEOUT_MINUTES", 20)

    @patch("daemon.config.reset_setting")
    @patch("daemon.config.get_setting", return_value=2.0)
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_reset_einstellung_ruft_reset_setting(self, mock_client, mock_get, mock_reset):
        """reset_setting_KEY-Callback entfernt den DB-Override."""
        _process_callback_query(self._cb("reset_setting_RAIN_THRESHOLD_MM"))
        mock_reset.assert_called_once_with("RAIN_THRESHOLD_MM")

    @patch("daemon.config.get_setting", return_value=2.0)
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_einst_close_sendet_alert(self, mock_client, mock_get):
        """einst_close schließt den Dialog per answerCallbackQuery."""
        _process_callback_query(self._cb("einst_close"))
        mock_client.answer_callback_query.assert_called()

    @patch("daemon.config.get_setting", return_value=2.0)
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_einst_edit_rain_zeigt_optionen(self, mock_client, mock_get):
        """einst_edit_RAIN_THRESHOLD_MM zeigt Auswahlmenü mit gültigen Werten."""
        _process_callback_query(self._cb("einst_edit_RAIN_THRESHOLD_MM"))
        mock_client.edit_message_text.assert_called()
        args = mock_client.edit_message_text.call_args
        text = args[0][2] if len(args[0]) > 2 else args[1].get("text", "")
        self.assertIn("Regen", text)

    @patch("daemon.config.get_setting", return_value=2.0)
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_einstellungen_kein_doppelasterisk(self, mock_client, mock_get):
        """handle_einstellungen erzeugt kein ** in der Nachricht."""
        from daemon.ui.telegram_ui import handle_einstellungen
        handle_einstellungen(100)
        text = mock_client.send_message.call_args[0][1]
        self.assertNotIn("**", text)

class TestKameraAkkustandImStatus(unittest.TestCase):

    def _status_call(self, mock_client, mock_db, mock_ctrl, cameras):
        from daemon.adapters import mqtt_client as mc
        mock_db.get_last_weather.return_value = None
        mock_db.get_all_valves.return_value = []
        mock_db.get_all_cameras.return_value = cameras
        mock_db.get_recent_history.return_value = []
        mock_ctrl.get_active_cycle.return_value = None
        with patch.object(mc, "HAS_PAHO", False), \
             patch.object(mc, "request_valve_status"), \
             patch.object(mc, "is_broker_connected", return_value=True), \
             patch.object(mc, "get_bridge_status", return_value="online"):
            from daemon.ui.telegram_ui import handle_status
            handle_status(100)
        return mock_client.send_message.call_args[0][1]

    def _make_cam(self, battery=None):
        from datetime import datetime, timezone
        return {
            "wish_name": "Hochbeet",
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "sleep_duration_seconds": 900,
            "battery": battery,
        }

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_kamera_akkustand_wird_angezeigt(self, mock_client, mock_db, mock_ctrl):
        """Kamera-Akkustand erscheint im Status wenn vorhanden."""
        text = self._status_call(mock_client, mock_db, mock_ctrl, [self._make_cam(battery=78)])
        self.assertIn("78", text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_kamera_kein_akkustand_kein_crash(self, mock_client, mock_db, mock_ctrl):
        """Kamera ohne Akkustand (None) zeigt kein Batterie-Label, kein Crash."""
        text = self._status_call(mock_client, mock_db, mock_ctrl, [self._make_cam(battery=None)])
        self.assertIn("Hochbeet", text)

    @patch("daemon.config.get_setting", return_value=20)
    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_kamera_niedrig_akkustand_kippt_ampel(self, mock_client, mock_db, mock_ctrl, mock_get):
        """Kamera mit Akku <= Schwellenwert kippt Garten-Ampel auf 🟡."""
        mock_db.get_all_cameras.return_value = [self._make_cam(battery=10)]
        text = self._status_call(mock_client, mock_db, mock_ctrl, [self._make_cam(battery=10)])
        self.assertIn("🟡", text)

class TestGetNextSchedule(unittest.TestCase):

    def _sched(self, name, time_str, days, is_active=1, sched_id=1):
        return {"id": sched_id, "name": name, "time": time_str, "days": days,
                "duration_minutes": 15, "target_volume_liters": 30, "is_active": is_active}

    def test_no_schedules_returns_none(self):
        from daemon.ui.telegram_ui import _get_next_schedule
        now = datetime(2026, 6, 19, 14, 0)
        self.assertIsNone(_get_next_schedule([], now))

    def test_inactive_schedule_ignored(self):
        from daemon.ui.telegram_ui import _get_next_schedule
        now = datetime(2026, 6, 19, 14, 0)
        s = self._sched("Rasen", "20:00", "everyday", is_active=0)
        self.assertIsNone(_get_next_schedule([s], now))

    def test_future_schedule_today_returned(self):
        from daemon.ui.telegram_ui import _get_next_schedule
        now = datetime(2026, 6, 19, 14, 0)  # Donnerstag 14:00
        s = self._sched("Rasen", "20:15", "everyday")
        result = _get_next_schedule([s], now)
        self.assertIsNotNone(result)
        self.assertEqual(result["_next_dt"].hour, 20)
        self.assertEqual(result["_next_dt"].minute, 15)
        self.assertEqual(result["_next_dt"].date(), now.date())

    def test_past_schedule_today_rolls_to_tomorrow(self):
        from daemon.ui.telegram_ui import _get_next_schedule
        now = datetime(2026, 6, 19, 21, 0)  # Donnerstag 21:00
        s = self._sched("Rasen", "06:00", "everyday")
        result = _get_next_schedule([s], now)
        self.assertIsNotNone(result)
        self.assertEqual(result["_next_dt"].day, 20)  # Freitag

    def test_wrong_weekday_skips_to_correct_day(self):
        from daemon.ui.telegram_ui import _get_next_schedule
        now = datetime(2026, 6, 18, 14, 0)  # Donnerstag (18.06.2026)
        s = self._sched("Hochbeet", "06:00", "Mon,Wed,Fri")
        result = _get_next_schedule([s], now)
        self.assertIsNotNone(result)
        self.assertEqual(result["_next_dt"].weekday(), 4)  # 4 = Freitag (19.06.2026)

    def test_earliest_of_two_schedules_returned(self):
        from daemon.ui.telegram_ui import _get_next_schedule
        now = datetime(2026, 6, 19, 14, 0)
        s1 = self._sched("Spät", "22:00", "everyday", sched_id=1)
        s2 = self._sched("Früh", "16:00", "everyday", sched_id=2)
        result = _get_next_schedule([s1, s2], now)
        self.assertEqual(result["name"], "Früh")

class TestGiesscheckHandler(unittest.TestCase):

    def setUp(self):
        wizard_states.clear()
        manual_states.clear()

    def tearDown(self):
        wizard_states.clear()
        manual_states.clear()

    def _msg(self, text: str, chat_id: int = 1) -> dict:
        return {"chat": {"id": chat_id}, "text": text}

    @patch("daemon.ui.telegram_ui._weather_adapter.evaluate_watering_factor")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_button_sends_verdict_message(self, mock_client, mock_factor):
        from daemon.core.watering_advice import WateringDecision
        mock_factor.return_value = WateringDecision(
            factor=1.0, verdict="🚿 Voller Guss", reasons=["Kein nennenswerter Regen."], skip=False
        )
        _process_message(self._msg("💧 Gießcheck"))
        mock_client.send_message.assert_called_once()
        text = mock_client.send_message.call_args[0][1]
        self.assertIn("Gießcheck", text)
        self.assertIn("🚿", text)

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_slash_giesscheck_removed(self, mock_client):
        """/giesscheck Slash-Befehl wurde mit Feature 0031 entfernt (nur Tastatur-Button)."""
        _process_message(self._msg("/giesscheck"))
        text = mock_client.send_message.call_args[0][1]
        self.assertIn("Unbekannter Befehl", text)

    @patch("daemon.ui.telegram_ui._weather_adapter.evaluate_watering_factor", side_effect=Exception("no data"))
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_exception_sends_error_message(self, mock_client, mock_factor):
        _process_message(self._msg("💧 Gießcheck"))
        mock_client.send_message.assert_called_once()
        text = mock_client.send_message.call_args[0][1]
        self.assertIn("Keine Wetterdaten", text)

    @patch("daemon.ui.telegram_ui._weather_adapter.evaluate_watering_factor")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_button_aborts_active_wizard(self, mock_client, mock_factor):
        from daemon.core.watering_advice import WateringDecision
        mock_factor.return_value = WateringDecision(
            factor=1.0, verdict="🚿 Voller Guss", reasons=[], skip=False
        )
        _state_set(wizard_states, 1, {"step": "setup_wish_name"})
        _process_message(self._msg("💧 Gießcheck"))
        self.assertIsNone(_state_get(wizard_states, 1))

    @patch("daemon.ui.telegram_ui._weather_adapter.evaluate_watering_factor")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_reduced_watering_verdict_in_message(self, mock_client, mock_factor):
        from daemon.core.watering_advice import WateringDecision
        mock_factor.return_value = WateringDecision(
            factor=0.5, verdict="💧 Reduzierter Guss (50 %)", reasons=["1.5 mm Regen."], skip=False
        )
        _process_message(self._msg("💧 Gießcheck"))
        text = mock_client.send_message.call_args[0][1]
        self.assertIn("💧", text)
        self.assertIn("50", text)

class TestWateringScaledNotification(unittest.TestCase):

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_on_watering_scaled_sends_broadcast(self, mock_client):
        from daemon.core.scheduler_events import WateringScaled
        from daemon.ui.telegram_ui import _render_watering_scaled
        event = WateringScaled(
            schedule_name="Morgen",
            factor=0.6,
            duration_original=10,
            duration_scaled=6,
            volume_original=20,
            volume_scaled=12,
            reasons=["1.8 mm Regen erwartet."],
        )
        text = _render_watering_scaled(event)
        self.assertIn("60 %", text)
        self.assertIn("Morgen", text)
        self.assertIn("6 min", text)

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_on_watering_scaled_without_volume(self, mock_client):
        from daemon.core.scheduler_events import WateringScaled
        from daemon.ui.telegram_ui import _render_watering_scaled
        event = WateringScaled(
            schedule_name="Abend",
            factor=0.7,
            duration_original=15,
            duration_scaled=11,
            volume_original=0,
            volume_scaled=0,
            reasons=["Leichter Regen."],
        )
        text = _render_watering_scaled(event)
        self.assertIn("70 %", text)
        self.assertNotIn(" L", text)

class TestRainOverride(unittest.TestCase):
    """Feature 0034: Guss-Vorwarnung mit Regen-Übersteuerung."""

    def _cb(self, data, chat_id=100, msg_id=1):
        return {"id": "cb1", "data": data,
                "message": {"chat": {"id": chat_id}, "message_id": msg_id}}

    def _warning(self, sid=7, name="Rasen", run_date="2099-01-01",
                 duration_scaled=5, volume_scaled=10, factor=0.5):
        from daemon.core.scheduler_events import WateringRainWarning
        return WateringRainWarning(
            schedule_id=sid, schedule_name=name, time="20:00", run_date=run_date,
            valve_names=["Rasen-Düse"], duration_original=10, volume_original=20,
            duration_scaled=duration_scaled, volume_scaled=volume_scaled, factor=factor,
            reasons=["Regen 48h-Fenster: 6.0 mm, Schwelle 3.0 mm."])

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_rain_warning_sends_override_button(self, mock_client):
        # Registry-Refactor 3sr: den vollen Emit-Pfad (render + button + broadcast) treiben,
        # um den Button-Slot Ende-zu-Ende zu belegen.
        from daemon.ui.telegram_ui import NOTIFICATIONS
        from daemon.core.scheduler_events import WateringRainWarning
        NOTIFICATIONS[WateringRainWarning].emit(self._warning())
        mock_client.broadcast_notification.assert_called_once()
        text = mock_client.broadcast_notification.call_args[0][0]
        markup = mock_client.broadcast_notification.call_args.kwargs.get("reply_markup")
        # Details im Text
        self.assertIn("Rasen", text)
        self.assertIn("20:00", text)
        self.assertIn("mm", text)
        # Inline-Button mit dem richtigen Callback
        callbacks = [b["callback_data"] for row in markup["inline_keyboard"] for b in row]
        self.assertIn("rainoverride_7_2099-01-01", callbacks)

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_rain_warning_shows_reduced_target(self, mock_client):
        """Die Vorwarnung nennt die reduzierten Zielwerte (Zeit/Menge/Prozent)."""
        from daemon.ui.telegram_ui import _render_watering_rain_warning
        text = _render_watering_rain_warning(self._warning(duration_scaled=5, volume_scaled=10, factor=0.5))
        self.assertIn("5 Min", text)      # reduzierte Dauer
        self.assertIn("10 L", text)       # reduziertes Volumen
        self.assertIn("50 %", text)       # Faktor
        self.assertIn("10 Min", text)     # Originaldauer weiterhin sichtbar

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_rain_warning_skip_shows_uebersprungen(self, mock_client):
        """Bei Faktor 0 meldet die Vorwarnung 'übersprungen' statt reduzierter Werte."""
        from daemon.ui.telegram_ui import _render_watering_rain_warning
        text = _render_watering_rain_warning(self._warning(factor=0.0))
        self.assertIn("übersprungen", text.lower())

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_rainoverride_callback_sets_flag(self, mock_client, mock_db):
        mock_db.rain_override_key.return_value = "rain_override:7:2099-01-01"
        _process_callback_query(self._cb("rainoverride_7_2099-01-01"))
        mock_db.set_flag.assert_called_once_with("rain_override:7:2099-01-01", True)
        mock_client.answer_callback_query.assert_called()

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_rainoverride_callback_too_late_sets_no_flag(self, mock_client, mock_db):
        """Vergangener Lauf (ADR 0035): kein Flag, nur sachlicher Hinweis."""
        _process_callback_query(self._cb("rainoverride_7_2000-01-01"))
        mock_db.set_flag.assert_not_called()
        mock_client.answer_callback_query.assert_called_once()
        self.assertIn("Zu spät", mock_client.answer_callback_query.call_args[0][1])

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_rainoverride_callback_acknowledges_user(self, mock_client, mock_db):
        """Der Nutzer erhält eine sichtbare Quittung (Nachricht aktualisiert oder Antwort)."""
        _process_callback_query(self._cb("rainoverride_3_2099-06-30"))
        self.assertTrue(
            mock_client.edit_message_text.called or mock_client.answer_callback_query.called)

class TestStatusNaechstesPhoto(unittest.TestCase):
    """Feature 0035: 'Nächstes Foto' Zeile in /status."""

    def _make_schedule(self, time="06:00", duration=10, is_active=1, name="Rasen"):
        return {
            "id": 1, "name": name, "time": time, "duration_minutes": duration,
            "is_active": is_active, "days": "everyday", "target_volume_liters": 0,
        }

    def _status_with(self, mock_client, mock_db, mock_ctrl,
                     cameras=None, schedules=None, photo_times=None):
        from daemon.adapters import mqtt_client as mc
        if cameras is None:
            cameras = [_make_camera()]
        if schedules is None:
            schedules = [self._make_schedule()]
        if photo_times is None:
            photo_times = []
        mock_db.get_all_cameras.return_value = cameras
        mock_db.get_schedules.return_value = schedules
        mock_db.get_photo_times.return_value = photo_times
        mock_db.get_all_valves.return_value = []
        mock_db.get_last_weather.return_value = None
        mock_db.get_recent_history.return_value = []
        mock_ctrl.get_active_cycle.return_value = None
        with patch.object(mc, "HAS_PAHO", False), \
             patch.object(mc, "request_valve_status"), \
             patch.object(mc, "is_broker_connected", return_value=True), \
             patch.object(mc, "get_bridge_status", return_value="online"):
            _process_message({"chat": {"id": 100}, "text": "/status"})
        return mock_client.send_message.call_args[0][1]

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_zeigt_naechstes_foto_wenn_kamera_und_schedule(self, mock_client, mock_db, mock_ctrl):
        """Kamera + aktiver Zeitplan → 'Nächstes Foto' Zeile im Status."""
        text = self._status_with(mock_client, mock_db, mock_ctrl)
        self.assertIn("Nächstes Foto", text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_kein_naechstes_foto_ohne_kamera(self, mock_client, mock_db, mock_ctrl):
        """Keine Kamera → keine 'Nächstes Foto' Zeile."""
        text = self._status_with(mock_client, mock_db, mock_ctrl, cameras=[])
        self.assertNotIn("Nächstes Foto", text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_kein_naechstes_foto_ohne_ziele(self, mock_client, mock_db, mock_ctrl):
        """Kamera, aber keine Zeitpläne und keine festen Zeiten → keine 'Nächstes Foto' Zeile."""
        text = self._status_with(mock_client, mock_db, mock_ctrl, schedules=[], photo_times=[])
        self.assertNotIn("Nächstes Foto", text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_offline_kamera_zeigt_foto_linie(self, mock_client, mock_db, mock_ctrl):
        """Offline-Kamera unterdrückt 'Nächstes Foto' nicht — der Zeitplan gilt."""
        offline_cam = _make_camera(last_seen="2020-01-01T00:00:00")
        text = self._status_with(mock_client, mock_db, mock_ctrl, cameras=[offline_cam])
        self.assertIn("Nächstes Foto", text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_status_foto_anlass_im_text(self, mock_client, mock_db, mock_ctrl):
        """'Nächstes Foto' Zeile enthält den Anlass (Zeitplan-Name oder 'feste Fotozeit')."""
        text = self._status_with(mock_client, mock_db, mock_ctrl,
                                 schedules=[self._make_schedule(name="Rasen")])
        self.assertIn("Rasen", text)

class TestHandleAufnahmen(unittest.TestCase):
    """Feature 0035: Zwei-Abschnitt-Ansicht in handle_aufnahmen."""

    def _make_schedule(self, time="06:00", duration=10, is_active=1, name="Rasen", sid=1):
        return {
            "id": sid, "name": name, "time": time, "duration_minutes": duration,
            "is_active": is_active, "days": "everyday",
        }

    def _call(self, mock_client, mock_db, photo_times=None, schedules=None):
        from daemon.ui.telegram_ui import handle_aufnahmen
        mock_db.get_photo_times.return_value = [] if photo_times is None else photo_times
        mock_db.get_schedules.return_value = [] if schedules is None else schedules
        handle_aufnahmen(100)
        return mock_client.send_message.call_args

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_aufnahmen_zeigt_guss_abschnitt_bei_aktivem_zeitplan(self, mock_client, mock_db):
        """Aktiver Zeitplan → 'Nach Güssen' Abschnitt erscheint."""
        call = self._call(mock_client, mock_db, schedules=[self._make_schedule()])
        text = call[0][1]
        self.assertIn("Güssen", text)
        self.assertIn("Rasen", text)

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_aufnahmen_guss_foto_ohne_loeschen_button(self, mock_client, mock_db):
        """Guss-Fotos haben keinen 🗑️ Löschen-Button."""
        call = self._call(mock_client, mock_db, schedules=[self._make_schedule()])
        markup = call[0][2]
        callbacks = [b["callback_data"] for row in markup["inline_keyboard"] for b in row]
        self.assertFalse(any("phtime_del" in cb for cb in callbacks))

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_aufnahmen_feste_zeiten_haben_loeschen_button(self, mock_client, mock_db):
        """Feste Fotozeiten haben 🗑️ Löschen-Button."""
        call = self._call(mock_client, mock_db,
                          photo_times=[{"id": 1, "time": "18:00"}])
        markup = call[0][2]
        callbacks = [b["callback_data"] for row in markup["inline_keyboard"] for b in row]
        self.assertTrue(any("phtime_del" in cb for cb in callbacks))

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_aufnahmen_beide_leer_zeigt_leermeldung(self, mock_client, mock_db):
        """Keine festen Zeiten und keine aktiven Zeitpläne → bisherige Leer-Meldung."""
        call = self._call(mock_client, mock_db)
        text = call[0][1]
        self.assertIn("Keine", text)

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_aufnahmen_hinzufuegen_button_immer_sichtbar(self, mock_client, mock_db):
        """➕ Button ist immer vorhanden — auch ohne Einträge."""
        call = self._call(mock_client, mock_db)
        markup = call[0][2]
        texts = [b["text"] for row in markup["inline_keyboard"] for b in row]
        self.assertTrue(any("➕" in t for t in texts))

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_aufnahmen_inaktiver_zeitplan_kein_guss_abschnitt(self, mock_client, mock_db):
        """Inaktiver Zeitplan → kein 'Nach Güssen' Abschnitt."""
        call = self._call(mock_client, mock_db, schedules=[self._make_schedule(is_active=0)])
        text = call[0][1]
        self.assertNotIn("Güssen", text)

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_aufnahmen_feste_zeiten_abschnitt_header(self, mock_client, mock_db):
        """Feste Fotozeiten → Abschnitt-Überschrift ⏰ Feste Zeiten erscheint."""
        call = self._call(mock_client, mock_db, photo_times=[{"id": 1, "time": "18:00"}])
        text = call[0][1]
        self.assertIn("Feste", text)

class TestDiagnoseCommand(unittest.TestCase):
    """Feature 0041: /diagnose erzeugt das Diagnose-Paket und sendet es an den anfragenden Chat."""

    def _msg(self, text, chat_id=100):
        return {"chat": {"id": chat_id}, "text": text, "message_id": 1}

    @patch("daemon.ui.telegram_ui.threading.Thread")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_diagnose_sendet_quittung_und_startet_daemon_thread(self, mock_client, mock_thread):
        _process_message(self._msg("/diagnose"))
        # Sofortige Quittung an den anfragenden Chat
        mock_client.send_message.assert_called()
        args = mock_client.send_message.call_args[0]
        self.assertEqual(args[0], 100)
        self.assertIn("Diagnose-Paket", args[1])
        # Arbeit läuft im Hintergrund-Thread mit daemon=True (Thread-Hygiene-Regel)
        mock_thread.assert_called_once()
        self.assertTrue(mock_thread.call_args.kwargs.get("daemon"),
                        "Diagnose-Thread muss daemon=True sein")
        mock_thread.return_value.start.assert_called_once()

    @patch("daemon.ui.telegram_ui.diagnose")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_run_diagnose_sendet_dokument_an_anfragenden_chat(self, mock_client, mock_diag):
        mock_diag.collect_diagnose_paket.return_value = (b"PK\x03\x04zip-bytes", [])
        mock_client.send_document.return_value = True
        from daemon.ui.telegram_ui import _run_diagnose
        _run_diagnose(100)
        mock_client.send_chat_action.assert_called_with(100, "upload_document")
        mock_client.send_document.assert_called_once()
        args, kwargs = mock_client.send_document.call_args
        self.assertEqual(args[0], 100)
        self.assertEqual(args[1], b"PK\x03\x04zip-bytes")
        filename = args[2] if len(args) > 2 else kwargs.get("filename", "")
        self.assertTrue(filename.startswith("diagnose_"), f"Dateiname unerwartet: {filename}")
        self.assertTrue(filename.endswith(".zip"), f"Dateiname unerwartet: {filename}")

    @patch("daemon.ui.telegram_ui.diagnose")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_run_diagnose_weist_luecken_aus(self, mock_client, mock_diag):
        mock_diag.collect_diagnose_paket.return_value = (
            b"PK\x03\x04zip-bytes", ["journal_daemon.txt: Berechtigung verweigert"])
        mock_client.send_document.return_value = True
        from daemon.ui.telegram_ui import _run_diagnose
        _run_diagnose(100)
        # Lücken werden dem Nutzer sichtbar gemeldet (Freitext ist Markdown-escapt,
        # daher auf den sonderzeichenfreien Teil prüfen).
        all_texts = " ".join(str(c) for c in mock_client.send_message.call_args_list)
        self.assertIn("Unvollständiges Diagnose-Paket", all_texts)
        self.assertIn("Berechtigung verweigert", all_texts)

    @patch("daemon.ui.telegram_ui.diagnose")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_run_diagnose_totalausfall_meldet_fehler(self, mock_client, mock_diag):
        mock_diag.collect_diagnose_paket.return_value = (None, ["Archiv: kaputt"])
        from daemon.ui.telegram_ui import _run_diagnose
        _run_diagnose(100)
        mock_client.send_document.assert_not_called()
        texts = " ".join(str(c) for c in mock_client.send_message.call_args_list)
        self.assertIn("konnte nicht erstellt werden", texts)

    @patch("daemon.ui.telegram_ui.diagnose")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_run_diagnose_versandfehler_meldet_fehler(self, mock_client, mock_diag):
        mock_diag.collect_diagnose_paket.return_value = (b"PK\x03\x04zip-bytes", [])
        mock_client.send_document.return_value = False
        from daemon.ui.telegram_ui import _run_diagnose
        _run_diagnose(100)
        texts = " ".join(str(c) for c in mock_client.send_message.call_args_list)
        self.assertIn("Versand fehlgeschlagen", texts)

if __name__ == "__main__":
    unittest.main()
