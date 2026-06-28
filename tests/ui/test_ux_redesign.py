"""Tests für Feature 0031 — Bot UX Redesign (Befehle, Menüs, Flows).

Dispatcher-Ebene via _process_message() / _process_callback_query(), analog
zu tests/ui/test_photo_times.py.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.ui.telegram_ui import _process_message, _process_callback_query


def _msg(text, chat_id=100):
    return {"chat": {"id": chat_id}, "text": text}


def _cb(data, chat_id=100, msg_id=1):
    return {"id": "cb1", "data": data, "message": {"chat": {"id": chat_id}, "message_id": msg_id}}


def _markup(call_args):
    return call_args.args[2] if len(call_args.args) > 2 else call_args.kwargs.get("reply_markup")


def _edit_markup(call_args):
    # edit_message_text(chat_id, message_id, text, markup)
    return call_args.args[3] if len(call_args.args) > 3 else call_args.kwargs.get("reply_markup")


def _cb_data(markup):
    if markup is None:
        return []
    return [b.get("callback_data") for row in markup["inline_keyboard"] for b in row]


# ===========================================================================
# Gruppe A — Tastatur, Befehls-Umbenennung, Untermenüs, Clean Cut
# ===========================================================================

class TestKeyboardRouting(unittest.TestCase):
    """Neue Tastatur-Button-Texte lösen die korrekten Handler aus."""

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.handle_status")
    def test_status_button(self, mock_h, _tc):
        _process_message(_msg("📊 Status"))
        mock_h.assert_called_once()

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.handle_giesscheck")
    def test_giesscheck_button(self, mock_h, _tc):
        _process_message(_msg("💧 Gießcheck"))
        mock_h.assert_called_once()

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.handle_schedules")
    def test_zeitplaene_button(self, mock_h, _tc):
        _process_message(_msg("📅 Zeitpläne"))
        mock_h.assert_called_once()

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.handle_kamera_menu")
    def test_kamera_button(self, mock_h, _tc):
        _process_message(_msg("📷 Kamera"))
        mock_h.assert_called_once()

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.handle_einstellungen_menu")
    def test_einstellungen_button(self, mock_h, _tc):
        _process_message(_msg("⚙️ Einstellungen"))
        mock_h.assert_called_once()

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.handle_bewaessern_start")
    def test_bewaessern_button_shows_art_selection(self, mock_h, _tc):
        _process_message(_msg("🚿 Bewässern"))
        mock_h.assert_called_once()


class TestCommandRouting(unittest.TestCase):
    """Registrierte und Dispatcher-only Befehle."""

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.handle_update")
    def test_update_command_routes_to_handler(self, mock_h, _tc):
        """/update (registriert) ruft handle_update — Ziel der CI-Build-Benachrichtigung."""
        _process_message(_msg("/update"))
        mock_h.assert_called_once()

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui._generate_daily_report", return_value="Bericht")
    @patch("daemon.ui.telegram_ui.datetime")
    def test_tagesbericht_command_generates_report(self, mock_dt, mock_report, mock_tc):
        mock_dt.now.return_value.strftime.return_value = "2026-06-28"
        with patch("daemon.adapters.mqtt_client.HAS_PAHO", False), \
             patch("daemon.adapters.mqtt_client.request_valve_status"), \
             patch("daemon.adapters.chart.generate_weather_chart", return_value=None):
            _process_message(_msg("/tagesbericht"))
        mock_report.assert_called_once()


class TestRemovedCommands(unittest.TestCase):
    """Clean Cut: entfernte Befehle und alte Tastatur-Texte → Unbekannter Befehl."""

    REMOVED = [
        "/add", "/delete", "/toggle", "/photo", "/report", "/stop", "/setup",
        "/zeitplan", "/camera_setup", "/photo_clear", "/aufnahmen", "/statusbericht",
        "/foto", "/zeitplaene", "/einstellungen", "/stopp",
        "📊 Status anzeigen", "🚿 Bewässern starten", "📸 Foto anzeigen", "⚙️ Setup",
        "🛑 Sofort Stopp",
    ]

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_removed_commands_unknown(self, mock_tc):
        for cmd in self.REMOVED:
            with self.subTest(cmd=cmd):
                mock_tc.reset_mock()
                _process_message(_msg(cmd))
                # letzte send_message muss "Unbekannter Befehl" sein
                texts = " ".join(
                    str(c.args[1]) for c in mock_tc.send_message.call_args_list if len(c.args) > 1
                )
                self.assertIn("Unbekannter Befehl", texts, f"{cmd!r} wurde nicht abgewiesen")


class TestKameraSubmenu(unittest.TestCase):

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_kamera_menu_keyboard(self, mock_tc):
        from daemon.ui.telegram_ui import handle_kamera_menu
        handle_kamera_menu(100)
        cb_data = _cb_data(_markup(mock_tc.send_message.call_args))
        for expected in ("kamera_foto", "kamera_verlauf", "kamera_fotozeiten"):
            self.assertIn(expected, cb_data)

    @patch("daemon.ui.telegram_ui.handle_photo")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_kamera_foto_callback(self, _tc, mock_h):
        _process_callback_query(_cb("kamera_foto"))
        mock_h.assert_called_once()

    @patch("daemon.ui.telegram_ui.handle_photo_clear")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_kamera_verlauf_callback(self, _tc, mock_h):
        _process_callback_query(_cb("kamera_verlauf"))
        mock_h.assert_called_once()

    @patch("daemon.ui.telegram_ui.handle_aufnahmen")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_kamera_fotozeiten_callback(self, _tc, mock_h):
        _process_callback_query(_cb("kamera_fotozeiten"))
        mock_h.assert_called_once()


class TestEinstellungenSubmenu(unittest.TestCase):

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_einstellungen_menu_has_five_options(self, mock_tc):
        from daemon.ui.telegram_ui import handle_einstellungen_menu
        handle_einstellungen_menu(100)
        cb_data = _cb_data(_markup(mock_tc.send_message.call_args))
        for expected in ("setup_confirm", "camsetup_start", "camsetup_settings",
                         "einst_open", "update_start"):
            self.assertIn(expected, cb_data)

    @patch("daemon.ui.telegram_ui.handle_update")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_update_start_callback(self, _tc, mock_h):
        _process_callback_query(_cb("update_start"))
        mock_h.assert_called_once()

    @patch("daemon.ui.telegram_ui.handle_einstellungen")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_einst_open_callback_opens_thresholds(self, _tc, mock_h):
        _process_callback_query(_cb("einst_open"))
        mock_h.assert_called_once()


def _clear_states():
    from daemon.ui import telegram_ui
    telegram_ui.manual_states.clear()


def _valve(vid, wish, mqtt):
    return {"id": vid, "wish_name": wish, "mqtt_name": mqtt}


# ===========================================================================
# Gruppe C — Bewässern / Guss-Zweig (Art → Ventil → Zeitlimit)
# ===========================================================================

class TestGussFlow(unittest.TestCase):
    def setUp(self):
        _clear_states()

    def tearDown(self):
        _clear_states()

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_guss_one_valve_skips_to_duration(self, mock_db, mock_tc):
        mock_db.get_all_valves.return_value = [_valve(1, "Rasen", "garden_valve")]
        _process_callback_query(_cb("water_mode_guss"))
        cb_data = _cb_data(_edit_markup(mock_tc.edit_message_text.call_args))
        self.assertTrue(any("man_dur_" in (d or "") for d in cb_data), f"Kein Zeitlimit-Keyboard: {cb_data}")

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_guss_multiple_valves_shows_selection(self, mock_db, mock_tc):
        mock_db.get_all_valves.return_value = [_valve(1, "Rasen", "garden_valve"),
                                               _valve(2, "Beet", "beet_valve")]
        _process_callback_query(_cb("water_mode_guss"))
        cb_data = _cb_data(_edit_markup(mock_tc.edit_message_text.call_args))
        self.assertIn("water_valve_1", cb_data)
        self.assertIn("water_valve_2", cb_data)

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_guss_no_valve_shows_hint(self, mock_db, mock_tc):
        mock_db.get_all_valves.return_value = []
        _process_callback_query(_cb("water_mode_guss"))
        text = mock_tc.edit_message_text.call_args.args[2]
        self.assertIn("kein Ventil", text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_guss_selected_valve_threads_mqtt_name(self, mock_db, mock_tc, mock_water):
        mock_db.get_valve_by_id.return_value = _valve(2, "Beet", "beet_valve")
        mock_water.start_watering.return_value = (True, "ok")

        _process_callback_query(_cb("water_valve_2"))
        _process_callback_query(_cb("man_dur_10"))
        _process_callback_query(_cb("man_vol_25"))

        mock_water.start_watering.assert_called_once()
        _, kwargs = mock_water.start_watering.call_args
        self.assertEqual(kwargs.get("mqtt_name"), "beet_valve")


# ===========================================================================
# Gruppe B — Sofort-Nebel Takt (Ventil → Stoß-Dauer → Pause → Laufzeit)
# ===========================================================================

class TestNebelTaktFlow(unittest.TestCase):
    def setUp(self):
        _clear_states()

    def tearDown(self):
        _clear_states()

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_nebel_one_valve_shows_stoss_dauer(self, mock_db, mock_tc):
        mock_db.get_all_valves.return_value = [_valve(1, "Terrasse", "terrace_mist")]
        _process_callback_query(_cb("nebel_now"))
        cb_data = _cb_data(_markup(mock_tc.send_message.call_args))
        self.assertTrue(any("nebel_now_on_" in (d or "") for d in cb_data), f"Keine Stoß-Dauer: {cb_data}")

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_nebel_full_takt_chain_passes_chosen_values(self, mock_db, mock_tc):
        from daemon.ui import telegram_ui
        mock_db.get_all_valves.return_value = [_valve(1, "Terrasse", "terrace_mist")]

        nebel = MagicMock()
        nebel.start.return_value = (True, "ok")
        with patch.object(telegram_ui, "_nebel_ctrl", nebel):
            _process_callback_query(_cb("nebel_now"))          # → Stoß-Dauer
            _process_callback_query(_cb("nebel_now_on_30"))    # → Pause
            cb_pause = _cb_data(_edit_markup(mock_tc.edit_message_text.call_args))
            self.assertTrue(any("nebel_now_pause_" in (d or "") for d in cb_pause))
            _process_callback_query(_cb("nebel_now_pause_5"))  # → Laufzeit
            cb_dur = _cb_data(_edit_markup(mock_tc.edit_message_text.call_args))
            self.assertTrue(any("nebel_dur_" in (d or "") for d in cb_dur))
            _process_callback_query(_cb("nebel_dur_30"))       # → Start

        nebel.start.assert_called_once()
        args = nebel.start.call_args.args
        # start(mqtt_name, on_seconds, pause_minutes, end, source)
        self.assertEqual(args[0], "terrace_mist")
        self.assertEqual(args[1], 30)   # gewählte Stoß-Dauer, nicht Config-Default
        self.assertEqual(args[2], 5)    # gewählte Pause


# ===========================================================================
# Gruppe D — Stopp: querschnittliche Auswahl
# ===========================================================================

class TestStoppSelection(unittest.TestCase):
    @patch("daemon.ui.telegram_ui._nebel_ctrl")
    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_two_guss_shows_selection(self, mock_db, mock_tc, mock_water, mock_nebel):
        from daemon.ui.telegram_ui import handle_stopp
        mock_water.get_active_valve_names.return_value = ["garden_valve", "beet_valve"]
        mock_nebel.get_active_window.return_value = None
        mock_db.get_valve_by_mqtt_name.side_effect = lambda n: _valve(0, n, n)
        handle_stopp(100)
        cb_data = _cb_data(_markup(mock_tc.send_message.call_args))
        self.assertIn("stop_valve_garden_valve", cb_data)
        self.assertIn("stop_valve_beet_valve", cb_data)
        self.assertIn("stop_valve_all", cb_data)

    @patch("daemon.ui.telegram_ui._nebel_ctrl")
    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_guss_and_nebel_shows_both(self, mock_db, mock_tc, mock_water, mock_nebel):
        from daemon.ui.telegram_ui import handle_stopp
        mock_water.get_active_valve_names.return_value = ["garden_valve"]
        mock_nebel.get_active_window.return_value = "terrace_mist"
        mock_db.get_valve_by_mqtt_name.side_effect = lambda n: _valve(0, n, n)
        handle_stopp(100)
        cb_data = _cb_data(_markup(mock_tc.send_message.call_args))
        self.assertIn("stop_valve_garden_valve", cb_data)
        self.assertIn("stop_nebel_terrace_mist", cb_data)
        self.assertIn("stop_valve_all", cb_data)

    @patch("daemon.ui.telegram_ui._nebel_ctrl")
    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_stop_all_callback_stops_both(self, mock_db, mock_tc, mock_water, mock_nebel):
        _process_callback_query(_cb("stop_valve_all"))
        mock_water.stop_watering.assert_called_once_with()
        mock_nebel.stop.assert_called_once_with()

    @patch("daemon.ui.telegram_ui._nebel_ctrl")
    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_stop_nebel_callback(self, mock_db, mock_tc, mock_water, mock_nebel):
        mock_db.get_valve_by_mqtt_name.return_value = _valve(0, "Terrasse", "terrace_mist")
        _process_callback_query(_cb("stop_nebel_terrace_mist"))
        mock_nebel.stop.assert_called_once_with("terrace_mist")

    @patch("daemon.ui.telegram_ui._nebel_ctrl")
    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_stop_valve_callback(self, mock_db, mock_tc, mock_water, mock_nebel):
        mock_db.get_valve_by_mqtt_name.return_value = _valve(0, "Rasen", "garden_valve")
        _process_callback_query(_cb("stop_valve_garden_valve"))
        mock_water.stop_watering.assert_called_once_with("garden_valve")

    # --- Extern/manuell geöffnete Ventile (Bug-Fix) ---

    @patch("daemon.ui.telegram_ui._nebel_ctrl")
    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_extern_open_valve_alone_is_force_closed(self, mock_db, mock_tc, mock_water, mock_nebel):
        from daemon.ui.telegram_ui import handle_stopp
        mock_water.get_active_valve_names.return_value = []
        mock_water.get_unexpected_open_valves.return_value = ["beet_valve"]
        mock_nebel.get_active_window.return_value = None
        mock_db.get_valve_by_mqtt_name.side_effect = lambda n: _valve(0, n, n)
        handle_stopp(100)
        mock_water.force_close.assert_called_once_with("beet_valve")

    @patch("daemon.ui.telegram_ui._nebel_ctrl")
    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_selection_includes_extern_valve(self, mock_db, mock_tc, mock_water, mock_nebel):
        from daemon.ui.telegram_ui import handle_stopp
        mock_water.get_active_valve_names.return_value = ["garden_valve"]
        mock_water.get_unexpected_open_valves.return_value = ["beet_valve"]
        mock_nebel.get_active_window.return_value = None
        mock_db.get_valve_by_mqtt_name.side_effect = lambda n: _valve(0, n, n)
        handle_stopp(100)
        cb_data = _cb_data(_markup(mock_tc.send_message.call_args))
        self.assertIn("stop_valve_garden_valve", cb_data)
        self.assertIn("stop_extern_beet_valve", cb_data)
        self.assertIn("stop_valve_all", cb_data)

    @patch("daemon.ui.telegram_ui._nebel_ctrl")
    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_stop_extern_callback_force_closes(self, mock_db, mock_tc, mock_water, mock_nebel):
        mock_db.get_valve_by_mqtt_name.return_value = _valve(0, "Beet", "beet_valve")
        _process_callback_query(_cb("stop_extern_beet_valve"))
        mock_water.force_close.assert_called_once_with("beet_valve")

    @patch("daemon.ui.telegram_ui._nebel_ctrl")
    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_stop_all_also_closes_extern(self, mock_db, mock_tc, mock_water, mock_nebel):
        mock_water.get_unexpected_open_valves.return_value = ["beet_valve"]
        _process_callback_query(_cb("stop_valve_all"))
        mock_water.stop_watering.assert_called_once_with()
        mock_nebel.stop.assert_called_once_with()
        mock_water.force_close.assert_called_once_with("beet_valve")


if __name__ == "__main__":
    unittest.main()
