import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

import daemon.adapters.database as db
import daemon.adapters.daily_report as dr


class TestVerbalWateringSection(unittest.TestCase):

    def test_zero_cycles(self):
        result = dr._format_watering_section(0, 0, 0.0)
        self.assertIn("nicht bewässert", result)

    def test_one_cycle(self):
        result = dr._format_watering_section(1, 0, 6.0)
        self.assertIn("1×", result)
        self.assertIn("6", result)
        self.assertNotIn("fehlgeschlagen", result)

    def test_multiple_cycles_with_failure(self):
        result = dr._format_watering_section(2, 1, 12.0)
        self.assertIn("2×", result)
        self.assertIn("1 Zyklus fehlgeschlagen", result)

    def test_multiple_failures(self):
        result = dr._format_watering_section(0, 3, 0.0)
        self.assertIn("3 Zyklen fehlgeschlagen", result)


class TestVerbalWeatherSection(unittest.TestCase):

    def test_no_rain_no_forecast(self):
        result = dr._format_weather_section(
            temp=22.0, temp_min=15.0, temp_max=26.0,
            weather_desc="Leicht bewölkt",
            rain_last=0.0, rain_next=0.5, rain_prob=10,
            yesterday_rain_next=None,
            rain_last_source="measured",
        )
        self.assertIn("Leicht bewölkt", result)
        self.assertIn("15", result)
        self.assertIn("26", result)
        self.assertNotIn("erwartet:", result.split("wenig erwartet")[0] if "wenig erwartet" in result else result)

    def test_significant_less_rain_than_forecast(self):
        result = dr._format_weather_section(
            temp=18.0, temp_min=12.0, temp_max=22.0,
            weather_desc="Bewölkt",
            rain_last=0.3, rain_next=1.0, rain_prob=20,
            yesterday_rain_next=6.0,
            rain_last_source="measured",
        )
        self.assertIn("Weniger Regen", result)
        self.assertIn("0.3", result)
        self.assertIn("6.0", result)

    def test_significant_more_rain_than_forecast(self):
        result = dr._format_weather_section(
            temp=14.0, temp_min=10.0, temp_max=18.0,
            weather_desc="Regnerisch",
            rain_last=9.0, rain_next=2.0, rain_prob=40,
            yesterday_rain_next=1.0,
            rain_last_source="measured",
        )
        self.assertIn("Mehr Regen", result)
        self.assertIn("9.0", result)
        self.assertIn("1.0", result)

    def test_insignificant_deviation_not_shown(self):
        result = dr._format_weather_section(
            temp=20.0, temp_min=14.0, temp_max=24.0,
            weather_desc="Sonnig",
            rain_last=1.5, rain_next=0.0, rain_prob=5,
            yesterday_rain_next=2.0,  # Abweichung 0.5mm — unter Schwellenwert
            rain_last_source="measured",
        )
        self.assertNotIn("erwartet:", result)

    def test_heavy_rain_forecast(self):
        result = dr._format_weather_section(
            temp=15.0, temp_min=10.0, temp_max=18.0,
            weather_desc="Gewitter",
            rain_last=0.0, rain_next=15.0, rain_prob=80,
            yesterday_rain_next=None,
            rain_last_source="measured",
        )
        self.assertIn("starker Regen", result)

    def test_moderate_rain_forecast(self):
        result = dr._format_weather_section(
            temp=17.0, temp_min=12.0, temp_max=21.0,
            weather_desc="Bewölkt",
            rain_last=0.0, rain_next=5.0, rain_prob=55,
            yesterday_rain_next=None,
            rain_last_source="measured",
        )
        self.assertIn("mäßiger Regen", result)

    def test_not_measured_source_skips_deviation_and_adds_disclaimer(self):
        result = dr._format_weather_section(
            temp=18.0, temp_min=12.0, temp_max=22.0,
            weather_desc="Bewölkt",
            rain_last=5.0, rain_next=1.0, rain_prob=20,
            yesterday_rain_next=0.0,
            rain_last_source="forecast",
        )
        self.assertNotIn("Mehr Regen als erwartet", result)
        self.assertNotIn("gefallen", result)
        self.assertIn("Gemessene Regendaten zurzeit nicht verfügbar", result)

    def test_api_failure_with_snapshot_suppresses_deviation(self):
        """Wenn get_weather_data() None zurückgibt (rain_last_source='forecast' im Fallback),
        darf kein Abweichungssatz erscheinen, auch wenn ein gestern-Snapshot existiert."""
        result = dr._format_weather_section(
            temp=0.0, temp_min=0.0, temp_max=0.0,
            weather_desc="Unbekannt",
            rain_last=0.0, rain_next=0.0, rain_prob=0,
            yesterday_rain_next=4.2,
            rain_last_source="forecast",  # Fallback bei vollständigem API-Fehler
        )
        self.assertNotIn("0.0 mm gefallen", result)
        self.assertNotIn("Weniger Regen als erwartet", result)
        self.assertNotIn("Mehr Regen als erwartet", result)
        self.assertIn("Gemessene Regendaten zurzeit nicht verfügbar", result)


class TestVerbalValveSection(unittest.TestCase):

    def test_good_signal(self):
        result = dr._format_valve_line(
            wish_name="Vorgarten", mqtt_name="garden_valve",
            count=48, avg_lqi=145.0, max_gap_hours=1.5,
            has_watchdog_alert=False, battery=100, abnormal_state="normal",
        )
        self.assertIn("Vorgarten", result)
        self.assertIn("gutes Signal", result)

    def test_very_good_signal(self):
        result = dr._format_valve_line(
            wish_name="Vorgarten", mqtt_name="garden_valve",
            count=48, avg_lqi=185.0, max_gap_hours=0.5,
            has_watchdog_alert=False, battery=100, abnormal_state="normal",
        )
        self.assertIn("sehr gutes Signal", result)

    def test_no_connection(self):
        result = dr._format_valve_line(
            wish_name="Vorgarten", mqtt_name="garden_valve",
            count=0, avg_lqi=0.0, max_gap_hours=0.0,
            has_watchdog_alert=False, battery=100, abnormal_state="normal",
        )
        self.assertIn("Keine Verbindung", result)
        self.assertIn("⚠️", result)

    def test_watchdog_alert(self):
        result = dr._format_valve_line(
            wish_name="Vorgarten", mqtt_name="garden_valve",
            count=5, avg_lqi=80.0, max_gap_hours=15.0,
            has_watchdog_alert=True, battery=100, abnormal_state="normal",
        )
        self.assertIn("⚠️", result)

    def test_low_battery(self):
        result = dr._format_valve_line(
            wish_name="Vorgarten", mqtt_name="garden_valve",
            count=20, avg_lqi=130.0, max_gap_hours=2.0,
            has_watchdog_alert=False, battery=15, abnormal_state="normal",
        )
        self.assertIn("🪫", result)

    def test_abnormal_state(self):
        result = dr._format_valve_line(
            wish_name="Vorgarten", mqtt_name="garden_valve",
            count=20, avg_lqi=130.0, max_gap_hours=2.0,
            has_watchdog_alert=False, battery=100, abnormal_state="stuck_open",
        )
        self.assertIn("🚨", result)


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
        return mocks

    def _setup_db_mock(self, mocks, success=1, failed=0, volume=5.0, skip_count=0, valves=None):
        mocks["db"].get_watering_stats_last_24h.return_value = (success, failed, volume)
        mocks["db"].get_watering_skip_count_last_24h.return_value = skip_count
        mocks["db"].get_nebel_stats_last_24h.return_value = (0, 0.0)
        mocks["db"].get_all_valves.return_value = valves or []
        mocks["db"].get_metadata.return_value = None

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


class TestDailyReportDesignSystem(unittest.TestCase):
    """Design-System-Konformität des Tagesberichts (Schritt 7 Migration)."""

    def _generate(self):
        from daemon.adapters.daily_report import generate_daily_report
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.weather") as mock_weather, \
             patch("daemon.adapters.daily_report.mqtt_client") as mock_mqtt:
            mock_db.get_watering_stats_last_24h.return_value = (1, 0, 5.0)
            mock_db.get_watering_skip_count_last_24h.return_value = 0
            mock_db.get_nebel_stats_last_24h.return_value = (0, 0.0)
            mock_db.get_all_valves.return_value = []
            mock_db.get_metadata.return_value = None
            mock_weather.get_weather_data.return_value = (0.0, 0.0, 20.0, 0, 15.0, 25.0, 5, "measured")
            mock_mqtt.HAS_PAHO = False
            return generate_daily_report("2026-06-18")

    def test_tagesbericht_kein_doppelasterisk(self):
        """Tagesbericht enthält kein ** (Markdown-Regression)."""
        text = self._generate()
        self.assertNotIn("**", text, f"** gefunden in: {text[:200]}")

    def test_ventil_zeile_kein_doppelasterisk(self):
        """_format_valve_line() erzeugt kein **."""
        result = dr._format_valve_line(
            wish_name="Terrasse", mqtt_name="garden_valve",
            count=48, avg_lqi=145.0, max_gap_hours=1.5,
            has_watchdog_alert=False, battery=100, abnormal_state="normal",
        )
        self.assertNotIn("**", result)

    def test_ventil_zeile_mit_anomalie_kein_doppelasterisk(self):
        """_format_valve_line() mit Anomalie erzeugt kein **."""
        result = dr._format_valve_line(
            wish_name="Terrasse", mqtt_name="garden_valve",
            count=20, avg_lqi=130.0, max_gap_hours=2.0,
            has_watchdog_alert=False, battery=100, abnormal_state="stuck_open",
        )
        self.assertNotIn("**", result)


class TestKameraWarnungen(unittest.TestCase):

    def test_niedrige_kamera_batterie_erzeugt_warnung(self):
        """Kamera mit Akku <= Schwellenwert erscheint in den Warnungen."""
        with patch("daemon.config.get_setting", return_value=20):
            result = dr._camera_warnings({"wish_name": "Hochbeet", "battery": 10})
        self.assertEqual(len(result), 1)
        self.assertIn("Hochbeet", result[0])
        self.assertIn("10%", result[0])

    def test_volle_kamera_batterie_keine_warnung(self):
        """Kamera mit vollem Akku erzeugt keine Warnung."""
        with patch("daemon.config.get_setting", return_value=20):
            result = dr._camera_warnings({"wish_name": "Hochbeet", "battery": 80})
        self.assertEqual(result, [])

    def test_kamera_ohne_akkustand_keine_warnung(self):
        """Kamera ohne bekannten Akkustand (None) erzeugt keine Warnung."""
        with patch("daemon.config.get_setting", return_value=20):
            result = dr._camera_warnings({"wish_name": "Hochbeet", "battery": None})
        self.assertEqual(result, [])


class TestMorningReportAssembly(unittest.TestCase):

    def test_short_form_starts_with_guten_morgen(self):
        result = dr._format_morning_report_short(
            date_display="Do 19.06.",
            watering_line="💧 Gestern 1× bewässert · 45 L",
            weather_line="☀️ Heute 14–24 °C · Sonnig (5 % ☂)",
            rain_extra_line=None,
        )
        self.assertIn("Guten Morgen", result)
        self.assertIn("✅ System: alles in Ordnung", result)
        self.assertNotIn("LQI", result)

    def test_short_form_includes_rain_extra_when_present(self):
        result = dr._format_morning_report_short(
            date_display="Do 19.06.",
            watering_line="💧 Gestern 1× bewässert · 45 L",
            weather_line="🌦 Heute 12–18 °C · Bewölkt (40 % ☂)",
            rain_extra_line="🌧 0.8 mm erwartet",
        )
        self.assertIn("0.8 mm", result)

    def test_problem_form_shows_issue_first(self):
        result = dr._format_morning_report_problem(
            date_display="Do 19.06.",
            issues=["🟡 Terrasse: Batterie schwach (15%)"],
            watering_line="💧 Gestern 1× bewässert · 45 L",
            weather_line="☀️ Heute 14–24 °C · Sonnig (5 % ☂)",
            rain_extra_line=None,
        )
        self.assertIn("Guten Morgen", result)
        self.assertIn("Batterie schwach", result)
        self.assertLess(result.index("Batterie"), result.index("bewässert"))

    def test_problem_form_no_double_asterisk(self):
        result = dr._format_morning_report_problem(
            date_display="Do 19.06.",
            issues=["🔴 MQTT-Broker nicht erreichbar"],
            watering_line="💧 Gestern nicht bewässert",
            weather_line="☀️ Heute 14–24 °C · Sonnig (5 % ☂)",
            rain_extra_line=None,
        )
        self.assertNotIn("**", result)


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
        return mocks

    def _generate(self, success=1, failed=0, volume=45.0, skip_count=0, valves=None):
        from daemon.adapters.daily_report import generate_daily_report
        mocks = self._make_patches()
        mocks["db"].get_watering_stats_last_24h.return_value = (success, failed, volume)
        mocks["db"].get_watering_skip_count_last_24h.return_value = skip_count
        mocks["db"].get_nebel_stats_last_24h.return_value = (0, 0.0)
        mocks["db"].get_all_valves.return_value = valves or []
        mocks["db"].get_metadata.return_value = None
        mocks["weather"].get_weather_data.return_value = (0.5, 0.0, 20.0, 0, 14.0, 24.0, 5, "measured")
        mocks["mqtt"].HAS_PAHO = False
        return generate_daily_report("2026-06-19")

    def test_nebel_line_appears_when_misted(self):
        """Wurde genebelt, erscheint eine Nebel-Zusammenfassungszeile (Feature 0032)."""
        from daemon.adapters.daily_report import generate_daily_report
        mocks = self._make_patches()
        mocks["db"].get_watering_stats_last_24h.return_value = (0, 0, 0.0)
        mocks["db"].get_watering_skip_count_last_24h.return_value = 0
        mocks["db"].get_nebel_stats_last_24h.return_value = (2, 360.0)
        mocks["db"].get_all_valves.return_value = []
        mocks["db"].get_metadata.return_value = None
        mocks["weather"].get_weather_data.return_value = (0.0, 0.0, 28.0, 0, 18.0, 30.0, 5, "measured")
        mocks["mqtt"].HAS_PAHO = False
        result = generate_daily_report("2026-06-27")
        self.assertIn("Nebel-Intervall", result)
        self.assertIn("2 Fenster", result)

    def test_no_nebel_line_when_not_misted(self):
        result = self._generate()
        self.assertNotIn("Nebel-Intervall", result)

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
        mocks["db"].get_nebel_stats_last_24h.return_value = (0, 0.0)
        mocks["db"].get_all_valves.return_value = [valve]
        mocks["db"].get_metadata.return_value = None
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
        mocks["db"].get_nebel_stats_last_24h.return_value = (0, 0.0)
        mocks["db"].get_all_valves.return_value = [valve]
        mocks["db"].get_metadata.return_value = None
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


class TestFormatWeatherMorning(unittest.TestCase):

    def test_dry_day_returns_sunny_emoji(self):
        main, extra = dr._format_weather_morning(14.0, 24.0, "Sonnig", rain_next=0.0, rain_prob=5)
        self.assertIn("☀️", main)
        self.assertIn("14", main)
        self.assertIn("24", main)
        self.assertIsNone(extra)

    def test_light_rain_returns_partly_cloudy_emoji_and_extra_line(self):
        main, extra = dr._format_weather_morning(12.0, 18.0, "Bewölkt", rain_next=0.8, rain_prob=40)
        self.assertIn("🌦", main)
        self.assertIsNotNone(extra)
        self.assertIn("0.8", extra)

    def test_heavy_rain_returns_rain_emoji(self):
        main, extra = dr._format_weather_morning(10.0, 15.0, "Regen", rain_next=8.0, rain_prob=85)
        self.assertIn("🌧", main)
        self.assertIsNotNone(extra)
        self.assertIn("8.0", extra)

    def test_below_threshold_no_extra_line(self):
        main, extra = dr._format_weather_morning(14.0, 22.0, "Leicht bewölkt", rain_next=0.3, rain_prob=10)
        self.assertIsNone(extra)

    def test_no_double_asterisk(self):
        main, _ = dr._format_weather_morning(14.0, 24.0, "Sonnig", rain_next=0.0, rain_prob=5)
        self.assertNotIn("**", main)


class TestFormatWateringMorning(unittest.TestCase):

    def test_no_activity_returns_nicht_bewaessert(self):
        result = dr._format_watering_morning(0, 0, 0.0, skip_count=0)
        self.assertIn("nicht bewässert", result)
        self.assertTrue(result.startswith("💧"))

    def test_one_cycle_shows_volume(self):
        result = dr._format_watering_morning(1, 0, 45.0, skip_count=0)
        self.assertIn("1×", result)
        self.assertIn("45", result)
        self.assertTrue(result.startswith("💧"))

    def test_multiple_cycles_shows_gesamt(self):
        result = dr._format_watering_morning(3, 0, 90.0, skip_count=0)
        self.assertIn("3×", result)
        self.assertIn("gesamt", result)

    def test_skip_with_no_success_shows_uebersprungen(self):
        result = dr._format_watering_morning(0, 0, 0.0, skip_count=1, rain_last=2.5)
        self.assertIn("übersprungen", result)
        self.assertIn("2.5", result)
        self.assertTrue(result.startswith("🌧"))

    def test_failed_cycle_noted(self):
        result = dr._format_watering_morning(0, 2, 0.0, skip_count=0)
        self.assertIn("Fehler", result)
        self.assertNotIn("LQI", result)

    def test_no_double_asterisk(self):
        result = dr._format_watering_morning(1, 0, 30.0, skip_count=0)
        self.assertNotIn("**", result)


class TestIsReportGreen(unittest.TestCase):

    def _valve(self, battery=100, abnormal_state="normal", valve_id=1):
        return {"id": valve_id, "battery": battery, "valve_abnormal_state": abnormal_state, "wish_name": "Terrasse"}

    def test_all_healthy_services_ok_returns_true(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config") as mock_cfg:
            mock_db.get_metadata.return_value = None
            mock_cfg.get_setting.return_value = 20
            result = dr._is_report_green([self._valve()], services_ok=True)
        self.assertTrue(result)

    def test_services_not_ok_returns_false(self):
        result = dr._is_report_green([self._valve()], services_ok=False)
        self.assertFalse(result)

    def test_low_battery_returns_false(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config") as mock_cfg:
            mock_db.get_metadata.return_value = None
            mock_cfg.get_setting.return_value = 20
            result = dr._is_report_green([self._valve(battery=15)], services_ok=True)
        self.assertFalse(result)

    def test_battery_exactly_at_threshold_returns_false(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config") as mock_cfg:
            mock_db.get_metadata.return_value = None
            mock_cfg.get_setting.return_value = 20
            result = dr._is_report_green([self._valve(battery=20)], services_ok=True)
        self.assertFalse(result)

    def test_abnormal_state_returns_false(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config") as mock_cfg:
            mock_db.get_metadata.return_value = None
            mock_cfg.get_setting.return_value = 20
            result = dr._is_report_green([self._valve(abnormal_state="stuck_open")], services_ok=True)
        self.assertFalse(result)

    def test_watchdog_alert_active_returns_false(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config") as mock_cfg:
            mock_db.get_metadata.return_value = "1"
            mock_cfg.get_setting.return_value = 20
            result = dr._is_report_green([self._valve()], services_ok=True)
        self.assertFalse(result)

    def test_no_valves_services_ok_returns_true(self):
        result = dr._is_report_green([], services_ok=True)
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
