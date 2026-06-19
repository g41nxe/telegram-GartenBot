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

    def test_send_daily_report_does_not_sleep(self):
        """send_daily_report() must not block — scheduler thread owns the wait."""
        from daemon.adapters.daily_report import send_daily_report

        mocks = self._make_patches()
        mocks["db"].get_watering_stats_last_24h.return_value = (1, 0, 5.0)
        mocks["db"].get_all_valves.return_value = []
        mocks["db"].get_metadata.return_value = None
        mocks["db"].get_daily_forecast_snapshot.return_value = None
        mocks["weather"].get_weather_data.return_value = (0.0, 0.0, 20.0, 0, 15.0, 25.0, 5, "measured")
        mocks["mqtt"].HAS_PAHO = False

        send_daily_report("2026-06-14")
        # Function completes immediately without blocking

    def test_send_daily_report_does_not_request_valve_status(self):
        """send_daily_report() must not trigger MQTT side-effects — caller's responsibility."""
        from daemon.adapters.daily_report import send_daily_report

        mocks = self._make_patches()
        mocks["db"].get_watering_stats_last_24h.return_value = (0, 0, 0.0)
        mocks["db"].get_all_valves.return_value = []
        mocks["db"].get_metadata.return_value = None
        mocks["db"].get_daily_forecast_snapshot.return_value = None
        mocks["weather"].get_weather_data.return_value = (0.0, 0.0, 20.0, 0, 15.0, 25.0, 5, "measured")
        mocks["mqtt"].HAS_PAHO = False

        send_daily_report("2026-06-14")

        mocks["mqtt"].request_valve_status.assert_not_called()

    def test_send_daily_report_publishes_event(self):
        """send_daily_report() must publish DailyReportTriggered on the EventBus."""
        from daemon.adapters.daily_report import send_daily_report
        from daemon.core.scheduler_events import DailyReportTriggered

        mocks = self._make_patches()
        mocks["db"].get_watering_stats_last_24h.return_value = (2, 1, 8.5)
        mocks["db"].get_all_valves.return_value = []
        mocks["db"].get_metadata.return_value = None
        mocks["db"].get_daily_forecast_snapshot.return_value = None
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
        mocks["db"].get_watering_stats_last_24h.return_value = (0, 0, 0.0)
        mocks["db"].get_all_valves.return_value = []
        mocks["db"].get_metadata.return_value = None
        mocks["db"].get_daily_forecast_snapshot.return_value = None
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
            mock_db.get_all_valves.return_value = []
            mock_db.get_metadata.return_value = None
            mock_db.get_daily_forecast_snapshot.return_value = None
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


if __name__ == "__main__":
    unittest.main()
