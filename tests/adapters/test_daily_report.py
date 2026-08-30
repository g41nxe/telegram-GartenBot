import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

import daemon.adapters.database as db
import daemon.adapters.daily_report as dr


class TestSendDailyReport(unittest.TestCase):

    def _make_patches(self):
        patches = {
            "db": patch("daemon.adapters.daily_report.database"),
            "weather": patch("daemon.adapters.daily_report.weather"),
            "mqtt": patch("daemon.adapters.daily_report.mqtt_client"),
            "bus": patch("daemon.adapters.daily_report._global_bus"),
        }
        mocks = {k: p.start() for k, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)
        # Standard: gesunder Regensensor mit Daten (from_sensor-Pfad, kein Fallback/Issue)
        mocks["db"].get_last_rain_measurement.return_value = {"battery_pct": 100}
        mocks["db"].get_rain_stats_last_24h.return_value = {
            "rain_sum": 0.0, "rain_max": 0.0, "temp_avg": 18.0, "temp_max": 24.0,
        }
        return mocks

    def _setup_db_mock(self, mocks, success=1, failed=0, volume=5.0, skip_count=0, valves=None):
        mocks["db"].get_watering_stats_last_24h.return_value = (success, failed, volume)
        mocks["db"].get_watering_skip_count_last_24h.return_value = skip_count
        mocks["db"].get_mist_stats_last_24h.return_value = (0, 0.0)
        mocks["db"].get_all_valves.return_value = valves or []
        mocks["db"].get_metadata.return_value = None
        mocks["db"].get_flag.side_effect = lambda k, _m=mocks["db"]: _m.get_metadata(k) == "1"

    def test_send_daily_report_does_not_sleep(self):
        """send_daily_report() must not block — scheduler thread owns the wait."""
        from daemon.adapters.daily_report import send_daily_report

        mocks = self._make_patches()
        self._setup_db_mock(mocks)
        mocks["weather"].get_weather_data.return_value = (0.0, 0.0, 20.0, 0, 15.0, 25.0, 5, "measured")
        mocks["mqtt"].HAS_PAHO = False

        send_daily_report("2026-06-14")
        # Function completes immediately without blocking

    def test_send_daily_report_does_not_request_valve_status(self):
        """send_daily_report() must not trigger MQTT side-effects — caller's responsibility."""
        from daemon.adapters.daily_report import send_daily_report

        mocks = self._make_patches()
        self._setup_db_mock(mocks, success=0, failed=0, volume=0.0)
        mocks["weather"].get_weather_data.return_value = (0.0, 0.0, 20.0, 0, 15.0, 25.0, 5, "measured")
        mocks["mqtt"].HAS_PAHO = False

        send_daily_report("2026-06-14")

        mocks["mqtt"].request_valve_status.assert_not_called()

    def test_send_daily_report_publishes_event(self):
        """send_daily_report() must publish DailyReportTriggered on the EventBus."""
        from daemon.adapters.daily_report import send_daily_report
        from daemon.core.scheduler_events import DailyReportTriggered

        mocks = self._make_patches()
        self._setup_db_mock(mocks, success=2, failed=1, volume=8.5)
        mocks["weather"].get_weather_data.return_value = (3.0, 1.0, 18.0, 61, 14.0, 22.0, 80, "measured")
        mocks["mqtt"].HAS_PAHO = False

        send_daily_report("2026-06-14")

        mocks["bus"].publish.assert_called_once()
        published_event = mocks["bus"].publish.call_args[0][0]
        self.assertIsInstance(published_event, DailyReportTriggered)
        self.assertEqual(published_event.today_str, "2026-06-14")

    def test_send_daily_report_sets_metadata(self):
        """send_daily_report() must mark the report date as sent."""
        from daemon.adapters.daily_report import send_daily_report

        mocks = self._make_patches()
        self._setup_db_mock(mocks, success=0, failed=0, volume=0.0)
        mocks["weather"].get_weather_data.return_value = (0.0, 0.0, 20.0, 0, 15.0, 25.0, 5, "measured")
        mocks["mqtt"].HAS_PAHO = False

        send_daily_report("2026-06-14")

        mocks["db"].set_metadata.assert_called_once_with("last_daily_report_date", "2026-06-14")

    def test_heute_block_faellt_bei_live_ausfall_auf_frischen_cache(self):
        """Live-Abruf None + frischer Cache → Heute-Block zeigt Cache-Werte mit Stand, keine 0-0-Lüge (ADR 0042)."""
        from datetime import datetime
        from daemon.adapters.daily_report import generate_daily_report

        mocks = self._make_patches()
        self._setup_db_mock(mocks)
        mocks["weather"].get_weather_data.return_value = None
        mocks["mqtt"].HAS_PAHO = False
        fresh_ts = datetime.now().replace(microsecond=0).isoformat()
        mocks["db"].get_last_weather.return_value = {
            "timestamp": fresh_ts,
            "rain_last_24h_mm": 1.9, "rain_next_24h_mm": 0.0,
            "current_temp": 20.3, "weather_code": 2,
            "temp_min": 18.0, "temp_max": 30.0, "rain_probability": 8,
            "hourly_forecast_json": "", "rain_last_source": "measured",
        }

        result = generate_daily_report("2026-07-17")

        self.assertIn("18–30 °C", result)
        self.assertIn("(Stand:", result)
        self.assertNotIn("0–0 °C", result)

    def test_heute_block_nicht_verfuegbar_ohne_cache(self):
        """Live-Abruf None + kein Cache → ehrliche 'nicht verfügbar'-Zeile statt 0-0 (ADR 0042)."""
        from daemon.adapters.daily_report import generate_daily_report

        mocks = self._make_patches()
        self._setup_db_mock(mocks)
        mocks["weather"].get_weather_data.return_value = None
        mocks["mqtt"].HAS_PAHO = False
        mocks["db"].get_last_weather.return_value = None

        result = generate_daily_report("2026-07-17")

        self.assertIn("Keine Wetterdaten verfügbar", result)
        self.assertNotIn("0–0 °C", result)

    def test_heute_block_nicht_verfuegbar_bei_zu_altem_cache(self):
        """Live-Abruf None + Cache älter als REPORT_WEATHER_MAX_AGE_HOURS → 'nicht verfügbar' (ADR 0042).

        Verdrahtet die 3h-Altersschwelle über generate_daily_report, nicht nur die Core-Funktion.
        """
        from datetime import datetime, timedelta
        from daemon.adapters.daily_report import generate_daily_report

        mocks = self._make_patches()
        self._setup_db_mock(mocks)
        mocks["weather"].get_weather_data.return_value = None
        mocks["mqtt"].HAS_PAHO = False
        stale_ts = (datetime.now() - timedelta(hours=4)).replace(microsecond=0).isoformat()
        mocks["db"].get_last_weather.return_value = {
            "timestamp": stale_ts,
            "rain_last_24h_mm": 1.9, "rain_next_24h_mm": 0.0,
            "current_temp": 20.3, "weather_code": 2,
            "temp_min": 18.0, "temp_max": 30.0, "rain_probability": 8,
            "hourly_forecast_json": "", "rain_last_source": "measured",
        }

        result = generate_daily_report("2026-07-17")

        self.assertIn("Keine Wetterdaten verfügbar", result)
        self.assertNotIn("18–30 °C", result)   # veralteter Cache wird NICHT gezeigt
        self.assertNotIn("(Stand:", result)


class TestDailyReportDesignSystem(unittest.TestCase):
    """Design-System-Konformität des Tagesberichts (Schritt 7 Migration)."""

    def _generate(self):
        from daemon.adapters.daily_report import generate_daily_report
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.weather") as mock_weather, \
             patch("daemon.adapters.daily_report.mqtt_client") as mock_mqtt:
            mock_db.get_watering_stats_last_24h.return_value = (1, 0, 5.0)
            mock_db.get_watering_skip_count_last_24h.return_value = 0
            mock_db.get_mist_stats_last_24h.return_value = (0, 0.0)
            mock_db.get_all_valves.return_value = []
            mock_db.get_metadata.return_value = None
            mock_db.get_flag.side_effect = lambda k, _m=mock_db: _m.get_metadata(k) == "1"
            mock_weather.get_weather_data.return_value = (0.0, 0.0, 20.0, 0, 15.0, 25.0, 5, "measured")
            mock_mqtt.HAS_PAHO = False
            return generate_daily_report("2026-06-18")

    def test_tagesbericht_kein_doppelasterisk(self):
        """Tagesbericht enthält kein ** (Markdown-Regression)."""
        text = self._generate()
        self.assertNotIn("**", text, f"** gefunden in: {text[:200]}")



class TestGenerateDailyReportIntegration(unittest.TestCase):

    def _make_patches(self):
        patches = {
            "db": patch("daemon.adapters.daily_report.database"),
            "weather": patch("daemon.adapters.daily_report.weather"),
            "mqtt": patch("daemon.adapters.daily_report.mqtt_client"),
        }
        mocks = {k: p.start() for k, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)
        # Standard: gesunder Regensensor mit Daten (from_sensor-Pfad, kein Fallback/Issue)
        mocks["db"].get_last_rain_measurement.return_value = {"battery_pct": 100}
        mocks["db"].get_rain_stats_last_24h.return_value = {
            "rain_sum": 0.0, "rain_max": 0.0, "temp_avg": 18.0, "temp_max": 24.0,
        }
        return mocks

    def _generate(self, success=1, failed=0, volume=45.0, skip_count=0, valves=None):
        from daemon.adapters.daily_report import generate_daily_report
        mocks = self._make_patches()
        mocks["db"].get_watering_stats_last_24h.return_value = (success, failed, volume)
        mocks["db"].get_watering_skip_count_last_24h.return_value = skip_count
        mocks["db"].get_mist_stats_last_24h.return_value = (0, 0.0)
        mocks["db"].get_all_valves.return_value = valves or []
        mocks["db"].get_metadata.return_value = None
        mocks["db"].get_flag.side_effect = lambda k, _m=mocks["db"]: _m.get_metadata(k) == "1"
        mocks["weather"].get_weather_data.return_value = (0.5, 0.0, 20.0, 0, 14.0, 24.0, 5, "measured")
        mocks["mqtt"].HAS_PAHO = False
        return generate_daily_report("2026-06-19")

    def test_nebel_line_appears_when_misted(self):
        """Wurde genebelt, erscheint eine Nebel-Zusammenfassungszeile (Feature 0032)."""
        from daemon.adapters.daily_report import generate_daily_report
        mocks = self._make_patches()
        mocks["db"].get_watering_stats_last_24h.return_value = (0, 0, 0.0)
        mocks["db"].get_watering_skip_count_last_24h.return_value = 0
        mocks["db"].get_mist_stats_last_24h.return_value = (2, 360.0)
        mocks["db"].get_all_valves.return_value = []
        mocks["db"].get_metadata.return_value = None
        mocks["db"].get_flag.side_effect = lambda k, _m=mocks["db"]: _m.get_metadata(k) == "1"
        mocks["weather"].get_weather_data.return_value = (0.0, 0.0, 28.0, 0, 18.0, 30.0, 5, "measured")
        mocks["mqtt"].HAS_PAHO = False
        result = generate_daily_report("2026-06-27")
        self.assertIn("🌫️", result)
        self.assertIn("2 Fenster", result)

    def test_no_nebel_line_when_not_misted(self):
        result = self._generate()
        self.assertNotIn("🌫️", result)

    def test_sensor_offline_falls_back_to_open_meteo(self):
        """Ohne lokale Sensor-Daten kommen Regen + Temperatur von Open-Meteo (mit Tag)."""
        from daemon.adapters.daily_report import generate_daily_report
        mocks = self._make_patches()
        mocks["db"].get_last_rain_measurement.return_value = None  # kein Sensor → Fallback
        mocks["db"].get_rain_stats_last_24h.return_value = {}
        mocks["db"].get_watering_stats_last_24h.return_value = (0, 0, 0.0)
        mocks["db"].get_watering_skip_count_last_24h.return_value = 0
        mocks["db"].get_mist_stats_last_24h.return_value = (0, 0.0)
        mocks["db"].get_all_valves.return_value = []
        mocks["db"].get_metadata.return_value = None
        mocks["db"].get_flag.side_effect = lambda k, _m=mocks["db"]: _m.get_metadata(k) == "1"
        mocks["weather"].get_weather_data.return_value = (1.2, 0.0, 18.0, 3, 20.0, 31.0, 20, "measured")
        mocks["weather"].get_yesterday_temp_stats.return_value = (17.4, 22.1)
        mocks["mqtt"].HAS_PAHO = False
        with patch("daemon.adapters.daily_report.config") as mock_cfg:
            mock_cfg.get_setting.return_value = 20
            mock_cfg.LATITUDE = 48.0
            mock_cfg.LONGITUDE = 11.0
            result = generate_daily_report("2026-06-30")
        self.assertIn("🌧 1.2 mm", result)
        self.assertIn("Ø 17.4 °C, max 22.1 °C", result)
        self.assertIn("(Open-Meteo)", result)

    def test_green_case_starts_with_guten_morgen(self):
        result = self._generate()
        self.assertIn("Guten Morgen", result)

    def test_green_case_has_system_ok_line(self):
        result = self._generate()
        self.assertIn("alles in Ordnung", result)

    def test_green_case_no_lqi_number(self):
        result = self._generate()
        self.assertNotIn("LQI", result)
        self.assertNotIn("Meldungen", result)

    def test_green_case_no_old_header(self):
        result = self._generate()
        self.assertNotIn("Täglicher Statusbericht", result)

    def test_problem_case_battery_shows_warning(self):
        from daemon.adapters.daily_report import generate_daily_report
        valve = {"id": 1, "wish_name": "Terrasse", "mqtt_name": "garden_valve",
                 "battery": 15, "valve_abnormal_state": "normal", "last_update": None}
        mocks = self._make_patches()
        mocks["db"].get_watering_stats_last_24h.return_value = (1, 0, 30.0)
        mocks["db"].get_watering_skip_count_last_24h.return_value = 0
        mocks["db"].get_mist_stats_last_24h.return_value = (0, 0.0)
        mocks["db"].get_all_valves.return_value = [valve]
        mocks["db"].get_metadata.return_value = None
        mocks["db"].get_flag.side_effect = lambda k, _m=mocks["db"]: _m.get_metadata(k) == "1"
        mocks["weather"].get_weather_data.return_value = (0.0, 0.0, 20.0, 0, 14.0, 24.0, 5, "measured")
        mocks["mqtt"].HAS_PAHO = False
        with patch("daemon.adapters.daily_report.config") as mock_cfg:
            mock_cfg.get_setting.return_value = 20
            mock_cfg.LATITUDE = 48.0
            mock_cfg.LONGITUDE = 11.0
            result = generate_daily_report("2026-06-19")
        self.assertIn("Batterie", result)
        self.assertIn("15", result)
        self.assertNotIn("alles in Ordnung", result)

    def test_problem_case_no_lqi_number(self):
        from daemon.adapters.daily_report import generate_daily_report
        valve = {"id": 1, "wish_name": "Terrasse", "mqtt_name": "garden_valve",
                 "battery": 15, "valve_abnormal_state": "normal", "last_update": None}
        mocks = self._make_patches()
        mocks["db"].get_watering_stats_last_24h.return_value = (0, 0, 0.0)
        mocks["db"].get_watering_skip_count_last_24h.return_value = 0
        mocks["db"].get_mist_stats_last_24h.return_value = (0, 0.0)
        mocks["db"].get_all_valves.return_value = [valve]
        mocks["db"].get_metadata.return_value = None
        mocks["db"].get_flag.side_effect = lambda k, _m=mocks["db"]: _m.get_metadata(k) == "1"
        mocks["weather"].get_weather_data.return_value = (0.0, 0.0, 20.0, 0, 14.0, 24.0, 5, "measured")
        mocks["mqtt"].HAS_PAHO = False
        with patch("daemon.adapters.daily_report.config") as mock_cfg:
            mock_cfg.get_setting.return_value = 20
            mock_cfg.LATITUDE = 48.0
            mock_cfg.LONGITUDE = 11.0
            result = generate_daily_report("2026-06-19")
        self.assertNotIn("LQI", result)
        self.assertNotIn("Meldungen", result)

    def test_no_double_asterisk_in_any_case(self):
        result = self._generate()
        self.assertNotIn("**", result)


class TestIsReportGreen(unittest.TestCase):

    def _valve(self, battery=100, abnormal_state="normal", valve_id=1):
        return {"id": valve_id, "battery": battery, "valve_abnormal_state": abnormal_state, "wish_name": "Terrasse"}

    def _patched(self, mock_db, *, watchdog=None, sensor=None):
        """Standard-Mock: Watchdog-Flag aus, kein Regensensor."""
        mock_db.get_metadata.return_value = watchdog
        mock_db.get_flag.side_effect = lambda k, _m=mock_db: _m.get_metadata(k) == "1"
        mock_db.get_last_rain_measurement.return_value = sensor

    def test_all_healthy_services_ok_returns_true(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config") as mock_cfg:
            self._patched(mock_db)
            mock_cfg.get_setting.return_value = 20
            result = dr._is_report_green([self._valve()], services_ok=True)
        self.assertTrue(result)

    def test_services_not_ok_returns_false(self):
        result = dr._is_report_green([self._valve()], services_ok=False)
        self.assertFalse(result)

    def test_low_battery_returns_false(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config") as mock_cfg:
            self._patched(mock_db)
            mock_cfg.get_setting.return_value = 20
            result = dr._is_report_green([self._valve(battery=15)], services_ok=True)
        self.assertFalse(result)

    def test_battery_exactly_at_threshold_returns_false(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config") as mock_cfg:
            self._patched(mock_db)
            mock_cfg.get_setting.return_value = 20
            result = dr._is_report_green([self._valve(battery=20)], services_ok=True)
        self.assertFalse(result)

    def test_abnormal_state_returns_false(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config") as mock_cfg:
            self._patched(mock_db)
            mock_cfg.get_setting.return_value = 20
            result = dr._is_report_green([self._valve(abnormal_state="stuck_open")], services_ok=True)
        self.assertFalse(result)

    def test_watchdog_alert_active_returns_false(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config") as mock_cfg:
            self._patched(mock_db, watchdog="1")
            mock_cfg.get_setting.return_value = 20
            result = dr._is_report_green([self._valve()], services_ok=True)
        self.assertFalse(result)

    def test_no_valves_services_ok_returns_true(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config") as mock_cfg:
            self._patched(mock_db)
            mock_cfg.get_setting.return_value = 20
            result = dr._is_report_green([], services_ok=True)
        self.assertTrue(result)

    def test_sensor_battery_low_returns_false(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config") as mock_cfg:
            self._patched(mock_db, sensor={"battery_pct": 18})
            mock_cfg.get_setting.return_value = 20
            result = dr._is_report_green([], services_ok=True)
        self.assertFalse(result)

    def test_sensor_watchdog_returns_false(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config") as mock_cfg:
            mock_db.get_metadata.return_value = "1"  # Sensor-Watchdog-Flag aktiv
            mock_db.get_flag.side_effect = lambda k, _m=mock_db: _m.get_metadata(k) == "1"
            mock_db.get_last_rain_measurement.return_value = {"battery_pct": 100}
            mock_cfg.get_setting.return_value = 20
            result = dr._is_report_green([], services_ok=True)
        self.assertFalse(result)


class TestSensorIssues(unittest.TestCase):
    """Regensensor-Warnungen im Ventil-Format."""

    def test_kein_sensor_keine_issues(self):
        with patch("daemon.adapters.daily_report.database") as mock_db:
            mock_db.get_last_rain_measurement.return_value = None
            self.assertEqual(dr._sensor_issues(), [])

    def test_schwacher_akku(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config") as mock_cfg:
            mock_db.get_last_rain_measurement.return_value = {"battery_pct": 18}
            mock_db.get_metadata.return_value = None
            mock_db.get_flag.side_effect = lambda k, _m=mock_db: _m.get_metadata(k) == "1"
            mock_cfg.get_setting.return_value = 20
            issues = dr._sensor_issues()
        self.assertEqual(issues, ["🟡 Regensensor: Batterie schwach (18%)"])

    def test_watchdog_signal(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config") as mock_cfg:
            mock_db.get_last_rain_measurement.return_value = {"battery_pct": 100}
            mock_db.get_metadata.return_value = "1"
            mock_db.get_flag.side_effect = lambda k, _m=mock_db: _m.get_metadata(k) == "1"
            mock_cfg.get_setting.return_value = 20
            issues = dr._sensor_issues()
        self.assertIn("⚠️ Regensensor: kein Signal (Watchdog aktiv)", issues)


if __name__ == "__main__":
    unittest.main()


class TestFormatGesternAktivitaet(unittest.TestCase):
    """Aktivitätszeile des Gestern-Blocks: Guss (+ Nebel), Klein-l."""

    def test_ein_guss_ohne_nebel(self):
        result = dr._format_gestern_aktivitaet(1, 0, 245.0, skip_count=0, mist_windows=0, mist_minutes=0.0)
        self.assertEqual(result, "💧 1× bewässert · 245 l")

    def test_klein_liter(self):
        result = dr._format_gestern_aktivitaet(1, 0, 245.0, skip_count=0, mist_windows=0, mist_minutes=0.0)
        self.assertIn(" l", result)
        self.assertNotIn(" L", result)

    def test_mehrere_guesse_mit_nebel(self):
        result = dr._format_gestern_aktivitaet(2, 0, 410.0, skip_count=0, mist_windows=5, mist_minutes=75.0)
        self.assertIn("2× bewässert", result)
        self.assertIn("410 l", result)
        self.assertIn("🌫️", result)
        self.assertIn("5 Fenster", result)
        self.assertIn("75 Min", result)

    def test_nicht_bewaessert_mit_nebel(self):
        result = dr._format_gestern_aktivitaet(0, 0, 0.0, skip_count=0, mist_windows=4, mist_minutes=60.0)
        self.assertIn("nicht bewässert", result)
        self.assertIn("🌫️ 4 Fenster · 60 Min", result)

    def test_uebersprungen_ohne_doppelte_mm(self):
        result = dr._format_gestern_aktivitaet(0, 0, 0.0, skip_count=1, mist_windows=1, mist_minutes=12.0)
        self.assertIn("💧 Guss übersprungen (Regen)", result)
        self.assertNotIn("mm", result)  # mm-Zahl steht auf der Wetterzeile, nicht hier

    def test_mit_fehler(self):
        result = dr._format_gestern_aktivitaet(2, 1, 410.0, skip_count=0, mist_windows=0, mist_minutes=0.0)
        self.assertIn("1 Fehler", result)

    def test_ohne_nebel_kein_nebel_emoji(self):
        result = dr._format_gestern_aktivitaet(1, 0, 100.0, skip_count=0, mist_windows=0, mist_minutes=0.0)
        self.assertNotIn("🌫️", result)


class TestFormatGesternWetter(unittest.TestCase):
    """Wetterzeile des Gestern-Blocks: Regen + Temp kombiniert; Quell-Tag nur im Fallback."""

    def test_sensor_ohne_tag(self):
        result = dr._format_gestern_wetter(3.0, 19.2, 32.0, from_sensor=True)
        self.assertIn("🌧 3.0 mm", result)
        self.assertIn("🌡", result)
        self.assertIn("Ø 19.2 °C", result)
        self.assertIn("max 32.0 °C", result)
        self.assertNotIn("Open-Meteo", result)

    def test_fallback_mit_open_meteo_tag(self):
        result = dr._format_gestern_wetter(1.2, 17.4, 22.1, from_sensor=False)
        self.assertIn("🌧 1.2 mm", result)
        self.assertIn("🌡", result)
        self.assertTrue(result.rstrip().endswith("(Open-Meteo)"))

    def test_kein_doppelasterisk(self):
        result = dr._format_gestern_wetter(0.0, 24.1, 33.5, from_sensor=True)
        self.assertNotIn("**", result)


class TestFormatHeute(unittest.TestCase):
    """Heute-Zeile: Emoji aus get_wmo_description, gefaltete Regenmenge."""

    def test_bedeckt_kein_sonnen_emoji(self):
        # Code 3 = Bedeckt / Bewölkt → ☁️, NICHT ☀️
        result = dr._format_heute(18, 29, weather_code=3, rain_next=0.0, rain_prob=30)
        self.assertIn("☁️", result)
        self.assertNotIn("☀️", result)
        self.assertIn("18–29 °C", result)
        self.assertIn("30 % ☂", result)

    def test_regen_menge_gefaltet(self):
        # Code 61 = Leichter Regen
        result = dr._format_heute(21, 28, weather_code=61, rain_next=6.2, rain_prob=80)
        self.assertIn("6.2 mm", result)
        self.assertIn("(80 % ☂)", result)

    def test_trocken_keine_mm(self):
        result = dr._format_heute(19, 34, weather_code=0, rain_next=0.0, rain_prob=0)
        self.assertNotIn("mm", result)
        self.assertIn("0 % ☂", result)


if __name__ == "__main__":
    unittest.main()


class TestKameraVerzugImTagesbericht(unittest.TestCase):
    """Ein aktiver Aufnahme-Verzug erscheint als Stoerungszeile im Tagesbericht (ADR 0041)."""

    def test_aktiver_verzug_erscheint_als_stoerung(self):
        from daemon.adapters import daily_report, database
        from unittest.mock import patch

        cameras = [{"mac_address": "AA:BB", "wish_name": "Garten01"}]

        def fake_metadata(key, default=None):
            if key == "watchdog_delay_alert_active_camera_AA:BB":
                return "1"
            return default

        with patch.object(database, "get_all_cameras", return_value=cameras), \
             patch.object(database, "get_metadata", side_effect=fake_metadata):
            issues = daily_report._kamera_issues()

        assert any("Garten01" in i for i in issues), f"Erwartete Stoerungszeile fehlt: {issues}"
        assert any("Aufnahme-Zeitpunkt" in i for i in issues), \
            f"Die Zeile muss den Aufnahme-Verzug benennen: {issues}"
