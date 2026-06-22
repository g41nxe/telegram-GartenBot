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
    def test_hourly_forecast_json_starts_24h_before_current_hour(self, mock_urlopen):
        """Forecast-Fenster startet 24 Stunden vor der aktuellen Stunde."""
        event = self._call_and_capture_event(_make_api_response(), mock_urlopen)
        fc = json.loads(event.hourly_forecast_json)
        expected_start = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:00")
        self.assertEqual(fc["times"][0], expected_start,
                         "Erster Forecast-Eintrag muss 24 Stunden vor der aktuellen Stunde liegen")

    @patch("urllib.request.urlopen")
    def test_hourly_forecast_json_has_48_entries_for_full_api_window(self, mock_urlopen):
        """Bei 48h API-Daten werden alle 48 Einträge geliefert."""
        event = self._call_and_capture_event(_make_api_response(n_hours=48), mock_urlopen)
        fc = json.loads(event.hourly_forecast_json)
        self.assertEqual(len(fc["times"]), 48)
        self.assertEqual(len(fc["temp"]), 48)
        self.assertEqual(len(fc["precip_mm"]), 48)
        self.assertEqual(len(fc["precip_prob"]), 48)

    @patch("urllib.request.urlopen")
    def test_hourly_forecast_json_fewer_when_near_end_of_data(self, mock_urlopen):
        # Nur 26 Stunden total → current_idx=24, chart_start=0, forecast_end=min(48,26)=26
        event = self._call_and_capture_event(_make_api_response(n_hours=26), mock_urlopen)
        fc = json.loads(event.hourly_forecast_json)
        self.assertLessEqual(len(fc["times"]), 26,
                             "Bei weniger Daten als 48h darf kein IndexError entstehen")

    @patch("urllib.request.urlopen")
    def test_past_hours_with_rain_have_prob_100(self, mock_urlopen):
        """Vergangene Stunden mit gemessenem Regen: precip_prob = 100."""
        now = datetime.now()
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        start_hour = current_hour - timedelta(hours=24)
        times = [(start_hour + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(48)]
        precip = [0.0] * 48
        precip[12] = 1.5   # Regen in Vergangenheit (12h vor jetzt)
        precip[13] = 0.3   # Regen in Vergangenheit

        response = json.dumps({
            "current": {"temperature_2m": 20.0, "weather_code": 0, "precipitation": 0.0},
            "hourly": {
                "time": times,
                "precipitation": precip,
                "precipitation_probability": [50] * 48,
                "temperature_2m": [20.0] * 48,
                "weather_code": [0] * 48,
            },
            "daily": {
                "time": [now.strftime("%Y-%m-%d")],
                "temperature_2m_max": [25.0],
                "temperature_2m_min": [15.0],
            },
        }).encode("utf-8")

        event = self._call_and_capture_event(response, mock_urlopen)
        fc = json.loads(event.hourly_forecast_json)
        # chart_start = max(0, 24-24) = 0; precip[12] und [13] sind in Vergangenheit
        self.assertEqual(fc["precip_prob"][12], 100, "Stunde mit Regen soll prob=100 haben")
        self.assertEqual(fc["precip_prob"][13], 100, "Stunde mit Regen soll prob=100 haben")

    @patch("urllib.request.urlopen")
    def test_past_dry_hours_have_prob_0(self, mock_urlopen):
        """Vergangene trockene Stunden: precip_prob = 0 (nicht Vorhersagewert)."""
        now = datetime.now()
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        start_hour = current_hour - timedelta(hours=24)
        times = [(start_hour + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(48)]

        response = json.dumps({
            "current": {"temperature_2m": 20.0, "weather_code": 0, "precipitation": 0.0},
            "hourly": {
                "time": times,
                "precipitation": [0.0] * 48,
                "precipitation_probability": [75] * 48,   # API liefert 75% für alle
                "temperature_2m": [20.0] * 48,
                "weather_code": [0] * 48,
            },
            "daily": {
                "time": [now.strftime("%Y-%m-%d")],
                "temperature_2m_max": [25.0],
                "temperature_2m_min": [15.0],
            },
        }).encode("utf-8")

        event = self._call_and_capture_event(response, mock_urlopen)
        fc = json.loads(event.hourly_forecast_json)
        # Stunden 0–23 sind Vergangenheit; precip=0 → prob soll 0 sein
        for i in range(24):
            self.assertEqual(fc["precip_prob"][i], 0,
                             f"Vergangenheitsstunde {i}: kein Regen → prob soll 0 sein (war {fc['precip_prob'][i]})")

    @patch("urllib.request.urlopen")
    def test_future_hours_keep_forecast_probability(self, mock_urlopen):
        """Zukünftige Stunden behalten die API-Vorhersagewahrscheinlichkeit."""
        now = datetime.now()
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        start_hour = current_hour - timedelta(hours=24)
        times = [(start_hour + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(48)]

        response = json.dumps({
            "current": {"temperature_2m": 20.0, "weather_code": 0, "precipitation": 0.0},
            "hourly": {
                "time": times,
                "precipitation": [0.0] * 48,
                "precipitation_probability": [60] * 48,
                "temperature_2m": [20.0] * 48,
                "weather_code": [0] * 48,
            },
            "daily": {
                "time": [now.strftime("%Y-%m-%d")],
                "temperature_2m_max": [25.0],
                "temperature_2m_min": [15.0],
            },
        }).encode("utf-8")

        event = self._call_and_capture_event(response, mock_urlopen)
        fc = json.loads(event.hourly_forecast_json)
        # Stunden 24–47 sind Zukunft; API-Wert 60% soll erhalten bleiben
        for i in range(24, 48):
            self.assertEqual(fc["precip_prob"][i], 60,
                             f"Zukunftsstunde {i}: prob soll API-Wert 60 behalten (war {fc['precip_prob'][i]})")

    @patch("urllib.request.urlopen")
    def test_hourly_forecast_json_all_arrays_same_length(self, mock_urlopen):
        event = self._call_and_capture_event(_make_api_response(), mock_urlopen)
        fc = json.loads(event.hourly_forecast_json)
        lengths = {k: len(v) for k, v in fc.items()}
        self.assertEqual(len(set(lengths.values())), 1,
                         f"Alle Arrays müssen gleich lang sein, aber: {lengths}")

    @patch("urllib.request.urlopen")
    def test_hourly_forecast_json_arrays_same_length_when_precip_prob_empty(self, mock_urlopen):
        """Wenn precipitation_probability fehlt (leere Liste), müssen alle Arrays gleich lang sein."""
        response = json.loads(_make_api_response().decode("utf-8"))
        response["hourly"]["precipitation_probability"] = []
        payload = json.dumps(response).encode("utf-8")
        event = self._call_and_capture_event(payload, mock_urlopen)
        self.assertIsNotNone(event)
        fc = json.loads(event.hourly_forecast_json)
        lengths = {k: len(v) for k, v in fc.items()}
        self.assertEqual(len(set(lengths.values())), 1,
                         f"Alle Arrays müssen gleich lang sein auch ohne precip_prob, aber: {lengths}")
        self.assertEqual(fc["precip_prob"], [0] * len(fc["times"]),
                         "Fehlende precip_prob-Einträge sollen mit 0 aufgefüllt werden")


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


class TestArchiveIntegration(unittest.TestCase):

    def _make_archive_response(self, hours_back=48, mm_value=6.1):
        now = datetime.now()
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        start_hour = current_hour - timedelta(hours=hours_back)
        times = [(start_hour + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(hours_back)]
        precip = [0.0] * hours_back
        if len(precip) >= 24:
            precip[-24] = mm_value  # inject 6.1 mm 24h ago to test sum

        return json.dumps({
            "hourly": {
                "time": times,
                "precipitation": precip
            }
        }).encode("utf-8")

    def _branching_side_effect(self, forecast_bytes, archive_bytes, fail_archive=False, fail_forecast=False):
        import urllib.error
        def _side_effect(req, *args, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "archive-api" in url:
                if fail_archive:
                    raise urllib.error.URLError("Archive unreachable")
                payload = archive_bytes
            else:
                if fail_forecast:
                    raise urllib.error.URLError("Forecast unreachable")
                payload = forecast_bytes
            cm = MagicMock()
            cm.__enter__.return_value = MagicMock(read=lambda: payload)
            return cm
        return _side_effect

    @patch("urllib.request.urlopen")
    def test_2_call_success_measured_source(self, mock_urlopen):
        forecast_payload = _make_api_response()
        archive_payload = self._make_archive_response(mm_value=6.1)
        mock_urlopen.side_effect = self._branching_side_effect(forecast_payload, archive_payload)
        
        captured = []
        _global_bus.subscribe(WeatherDataFetched, captured.append)
        try:
            res = weather.get_weather_data(52.5, 13.5)
        finally:
            _global_bus.unsubscribe(WeatherDataFetched, captured.append)
            
        self.assertIsNotNone(res)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].rain_last_source, "measured")
        self.assertAlmostEqual(captured[0].rain_last_24h, 6.1)

    @patch("urllib.request.urlopen")
    def test_archive_fails_forecast_ok(self, mock_urlopen):
        forecast_payload = _make_api_response()
        archive_payload = self._make_archive_response()
        mock_urlopen.side_effect = self._branching_side_effect(forecast_payload, archive_payload, fail_archive=True)
        
        captured = []
        _global_bus.subscribe(WeatherDataFetched, captured.append)
        try:
            res = weather.get_weather_data(52.5, 13.5)
        finally:
            _global_bus.unsubscribe(WeatherDataFetched, captured.append)
            
        self.assertIsNotNone(res)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].rain_last_source, "forecast")
        # should fallback to forecast payload rain
        self.assertAlmostEqual(captured[0].rain_last_24h, 0.0)

    @patch("urllib.request.urlopen")
    def test_forecast_fails(self, mock_urlopen):
        forecast_payload = _make_api_response()
        archive_payload = self._make_archive_response()
        mock_urlopen.side_effect = self._branching_side_effect(forecast_payload, archive_payload, fail_forecast=True)
        
        captured = []
        _global_bus.subscribe(WeatherDataFetched, captured.append)
        try:
            res = weather.get_weather_data(52.5, 13.5)
        finally:
            _global_bus.unsubscribe(WeatherDataFetched, captured.append)
            
        self.assertIsNone(res)
        self.assertEqual(len(captured), 0)

    @patch("urllib.request.urlopen")
    def test_robust_index_assignment(self, mock_urlopen):
        # Create response where current exact hour is missing, but past hour exists
        now = datetime.now()
        past_hour = now - timedelta(minutes=45) # missing exact hour
        # using standard api response but shift times
        res_json = json.loads(_make_api_response().decode("utf-8"))
        # shift all times by 45 minutes backwards
        shifted_times = []
        for t_str in res_json["hourly"]["time"]:
            t = datetime.fromisoformat(t_str) - timedelta(minutes=45)
            shifted_times.append(t.strftime("%Y-%m-%dT%H:%M"))
        res_json["hourly"]["time"] = shifted_times
        
        forecast_payload = json.dumps(res_json).encode("utf-8")
        archive_payload = self._make_archive_response()
        mock_urlopen.side_effect = self._branching_side_effect(forecast_payload, archive_payload)
        
        captured = []
        _global_bus.subscribe(WeatherDataFetched, captured.append)
        try:
            res = weather.get_weather_data(52.5, 13.5)
        finally:
            _global_bus.unsubscribe(WeatherDataFetched, captured.append)
            
        self.assertIsNotNone(res)
        self.assertEqual(len(captured), 1)

if __name__ == "__main__":
    unittest.main()
