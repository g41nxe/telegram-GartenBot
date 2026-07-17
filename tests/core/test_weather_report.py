import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.core.weather_report import resolve_heute_weather, HeuteWeather


# Live-Tupel-Layout (wie weather.get_weather_data):
# (rain_last, rain_next, current_temp, weather_code, temp_min, temp_max, rain_prob, rain_last_source)
def _live(rain_next=0.2, weather_code=3, temp_min=19.4, temp_max=28.8, rain_prob=38):
    return (1.9, rain_next, 24.8, weather_code, temp_min, temp_max, rain_prob, "measured")


# Cache-Zeile-Layout (wie database.get_last_weather)
def _cache(timestamp="2026-07-17T07:30:00"):
    return {
        "timestamp": timestamp,
        "rain_last_24h_mm": 1.9,
        "rain_next_24h_mm": 0.7,
        "current_temp": 20.3,
        "weather_code": 2,
        "temp_min": 18.0,
        "temp_max": 30.0,
        "rain_probability": 8,
        "hourly_forecast_json": "",
        "rain_last_source": "measured",
    }


class TestResolveHeuteWeather(unittest.TestCase):

    def test_live_ok_uses_live_values_without_stand(self):
        now = datetime(2026, 7, 17, 8, 0, 0)
        result = resolve_heute_weather(_live(), cached=None, now=now, max_age_hours=3)

        self.assertTrue(result.available)
        self.assertEqual(result.temp_min, 19.4)
        self.assertEqual(result.temp_max, 28.8)
        self.assertEqual(result.weather_code, 3)
        self.assertEqual(result.rain_next, 0.2)
        self.assertEqual(result.rain_prob, 38)
        self.assertIsNone(result.stand)

    def test_live_none_fresh_cache_uses_cache_values_with_stand(self):
        now = datetime(2026, 7, 17, 8, 0, 0)
        cached = _cache(timestamp="2026-07-17T07:30:00")
        result = resolve_heute_weather(None, cached=cached, now=now, max_age_hours=3)

        self.assertTrue(result.available)
        self.assertEqual(result.temp_min, 18.0)
        self.assertEqual(result.temp_max, 30.0)
        self.assertEqual(result.weather_code, 2)
        self.assertEqual(result.rain_next, 0.7)
        self.assertEqual(result.rain_prob, 8)
        self.assertEqual(result.stand, "07:30 Uhr")

    def test_live_none_stale_cache_is_unavailable(self):
        now = datetime(2026, 7, 17, 8, 0, 0)
        cached = _cache(timestamp="2026-07-17T04:00:00")  # 4 h alt > 3 h
        result = resolve_heute_weather(None, cached=cached, now=now, max_age_hours=3)

        self.assertFalse(result.available)
        self.assertIsNone(result.stand)

    def test_live_none_no_cache_is_unavailable(self):
        now = datetime(2026, 7, 17, 8, 0, 0)
        result = resolve_heute_weather(None, cached=None, now=now, max_age_hours=3)

        self.assertFalse(result.available)
        self.assertIsNone(result.stand)


if __name__ == "__main__":
    unittest.main()
