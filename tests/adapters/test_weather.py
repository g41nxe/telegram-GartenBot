import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.adapters import weather
from daemon.adapters.mqtt_client import _global_bus
from daemon.core.scheduler_events import WeatherDataFetched


def _make_api_response(current_precipitation=0.7, n_hours=48, include_precipitation=True):
    """Baut eine vollständige Mock-Antwort der Open-Meteo API inkl. aller Feature-0007-Felder."""
    now = datetime.now()
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    start_hour = current_hour - timedelta(hours=24)

    times = [(start_hour + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(n_hours)]
    precip = [0.0] * n_hours
    precip_prob = [10] * n_hours
    temps = [20.0 + i * 0.1 for i in range(n_hours)]
    wmo = [0] * n_hours

    current = {"temperature_2m": 22.5, "weather_code": 3}
    if include_precipitation:
        current["precipitation"] = current_precipitation

    return json.dumps({
        "current": current,
        "hourly": {
            "time": times,
            "precipitation": precip,
            "precipitation_probability": precip_prob,
            "temperature_2m": temps,
            "weather_code": wmo,
        },
        "daily": {
            "time": [
                (now - timedelta(days=1)).strftime("%Y-%m-%d"),
                now.strftime("%Y-%m-%d"),
                (now + timedelta(days=1)).strftime("%Y-%m-%d"),
            ],
            "temperature_2m_max": [20.0, 26.5, 25.0],
            "temperature_2m_min": [10.0, 15.5, 14.0],
        },
    }).encode("utf-8")


def _mock_urlopen(response_bytes):
    mock_resp = MagicMock()
    mock_resp.read.return_value = response_bytes
    mock = MagicMock()
    mock.return_value.__enter__.return_value = mock_resp
    return mock


class TestCurrentPrecipitationExtraction(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_current_precipitation_extracted(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value = MagicMock(
            read=lambda: _make_api_response(current_precipitation=0.7)
        )
        captured = []
        _global_bus.subscribe(WeatherDataFetched, captured.append)
        try:
            weather.get_weather_data(52.5, 13.5)
        finally:
            _global_bus.unsubscribe(WeatherDataFetched, captured.append)

        self.assertEqual(len(captured), 1)
        self.assertAlmostEqual(captured[0].current_precipitation, 0.7)

    @patch("urllib.request.urlopen")
    def test_current_precipitation_defaults_to_zero_when_missing(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value = MagicMock(
            read=lambda: _make_api_response(include_precipitation=False)
        )
        captured = []
        _global_bus.subscribe(WeatherDataFetched, captured.append)
        try:
            weather.get_weather_data(52.5, 13.5)
        finally:
            _global_bus.unsubscribe(WeatherDataFetched, captured.append)

        self.assertEqual(len(captured), 1)
        self.assertAlmostEqual(captured[0].current_precipitation, 0.0)


class TestHourlyForecastJson(unittest.TestCase):

    def _call_and_capture_event(self, response_bytes, mock_urlopen_obj):
        mock_urlopen_obj.return_value.__enter__.return_value = MagicMock(
            read=lambda: response_bytes
        )
        captured = []
        _global_bus.subscribe(WeatherDataFetched, captured.append)
        try:
            weather.get_weather_data(52.5, 13.5)
        finally:
            _global_bus.unsubscribe(WeatherDataFetched, captured.append)
        return captured[0] if captured else None

    @patch("urllib.request.urlopen")
    def test_hourly_forecast_json_has_all_keys(self, mock_urlopen):
        event = self._call_and_capture_event(_make_api_response(), mock_urlopen)
        self.assertIsNotNone(event)
        fc = json.loads(event.hourly_forecast_json)
        for key in ("times", "temp", "precip_mm", "precip_prob", "wmo"):
            self.assertIn(key, fc, f"Schlüssel '{key}' fehlt in hourly_forecast_json")

    @patch("urllib.request.urlopen")
    def test_hourly_forecast_json_starts_2h_before_current_hour(self, mock_urlopen):
        """Forecast-Fenster startet 2 Stunden vor der aktuellen Stunde."""
        event = self._call_and_capture_event(_make_api_response(), mock_urlopen)
        fc = json.loads(event.hourly_forecast_json)
        expected_start = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%dT%H:00")
        self.assertEqual(fc["times"][0], expected_start,
                         "Erster Forecast-Eintrag muss 2 Stunden vor der aktuellen Stunde liegen")

    @patch("urllib.request.urlopen")
    def test_hourly_forecast_json_max_24_entries(self, mock_urlopen):
        event = self._call_and_capture_event(_make_api_response(n_hours=72), mock_urlopen)
        fc = json.loads(event.hourly_forecast_json)
        self.assertLessEqual(len(fc["times"]), 24)
        self.assertEqual(len(fc["temp"]), len(fc["times"]))
        self.assertEqual(len(fc["precip_mm"]), len(fc["times"]))

    @patch("urllib.request.urlopen")
    def test_hourly_forecast_json_fewer_when_near_end_of_data(self, mock_urlopen):
        # Nur 26 Stunden total → current_idx=24, nur 2 Einträge verbleiben
        event = self._call_and_capture_event(_make_api_response(n_hours=26), mock_urlopen)
        fc = json.loads(event.hourly_forecast_json)
        self.assertLess(len(fc["times"]), 24,
                        "Bei weniger als 24 verbleibenden Einträgen darf kein IndexError entstehen")

    @patch("urllib.request.urlopen")
    def test_hourly_forecast_json_all_arrays_same_length(self, mock_urlopen):
        event = self._call_and_capture_event(_make_api_response(), mock_urlopen)
        fc = json.loads(event.hourly_forecast_json)
        lengths = {k: len(v) for k, v in fc.items()}
        self.assertEqual(len(set(lengths.values())), 1,
                         f"Alle Arrays müssen gleich lang sein, aber: {lengths}")


class TestWeatherEventCarriesNewFields(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_weather_event_carries_current_precipitation_and_hourly_json(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value = MagicMock(
            read=lambda: _make_api_response(current_precipitation=1.2)
        )
        captured = []
        _global_bus.subscribe(WeatherDataFetched, captured.append)
        try:
            weather.get_weather_data(52.5, 13.5)
        finally:
            _global_bus.unsubscribe(WeatherDataFetched, captured.append)

        self.assertEqual(len(captured), 1)
        event = captured[0]
        self.assertAlmostEqual(event.current_precipitation, 1.2)
        self.assertTrue(event.hourly_forecast_json, "hourly_forecast_json darf nicht leer sein")
        fc = json.loads(event.hourly_forecast_json)
        self.assertIn("times", fc)
        self.assertGreater(len(fc["times"]), 0)


if __name__ == "__main__":
    unittest.main()
