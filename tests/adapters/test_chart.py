import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

import daemon.adapters.chart as chart_module

_VALID_FORECAST = json.dumps({
    "times":      ["2026-06-13T14:00", "2026-06-13T15:00", "2026-06-13T16:00"],
    "temp":       [22.0, 21.0, 19.0],
    "precip_mm":  [0.0, 0.0, 0.8],
    "precip_prob":[5, 10, 55],
    "wmo":        [0, 1, 63],
})

_LAST_WEATHER_WITH_FORECAST = {
    "timestamp": "2026-06-13T14:00:00",
    "rain_last_24h_mm": 0.0,
    "rain_next_24h_mm": 0.8,
    "current_temp": 22.0,
    "weather_code": 0,
    "current_precipitation_mm": 0.0,
    "hourly_forecast_json": _VALID_FORECAST,
}


class TestGenerateWeatherChart(unittest.TestCase):

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=None)
    def test_returns_none_when_no_weather_data(self, _):
        result = chart_module.generate_weather_chart()
        self.assertIsNone(result)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value={
        "hourly_forecast_json": None
    })
    def test_returns_none_when_hourly_json_is_null(self, _):
        result = chart_module.generate_weather_chart()
        self.assertIsNone(result)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value={
        "hourly_forecast_json": ""
    })
    def test_returns_none_when_hourly_json_is_empty(self, _):
        result = chart_module.generate_weather_chart()
        self.assertIsNone(result)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value={
        "hourly_forecast_json": "not-valid-json{"
    })
    def test_returns_none_when_hourly_json_is_invalid(self, _):
        result = chart_module.generate_weather_chart()
        self.assertIsNone(result)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value={
        "hourly_forecast_json": json.dumps({"times": []})
    })
    def test_returns_none_when_times_array_is_empty(self, _):
        result = chart_module.generate_weather_chart()
        self.assertIsNone(result)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_returns_png_bytes_on_success(self, mock_urlopen, _):
        fake_png = b"\x89PNG\r\nfake"
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_png
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = chart_module.generate_weather_chart()

        self.assertEqual(result, fake_png)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen", side_effect=urllib.error.URLError("timeout"))
    def test_returns_none_on_network_error(self, _, __):
        result = chart_module.generate_weather_chart()
        self.assertIsNone(result)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_post_payload_contains_chart_key(self, mock_urlopen, _):
        """QuickChart.io-POST muss einen 'chart'-Schlüssel im Body enthalten."""
        captured = {}

        def capture_request(req, timeout=None):
            captured["data"] = req.data
            fake = MagicMock()
            fake.read.return_value = b"\x89PNG"
            fake.__enter__ = lambda s: s
            fake.__exit__ = MagicMock(return_value=False)
            return fake

        mock_urlopen.side_effect = capture_request
        chart_module.generate_weather_chart()

        body = json.loads(captured["data"].decode("utf-8"))
        self.assertIn("chart", body)
        self.assertIn("datasets", body["chart"]["data"])

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_labels_are_hhmm_format(self, mock_urlopen, _):
        """Zeitachsen-Labels müssen HH:MM sein, nicht die volle ISO-Zeit."""
        captured = {}

        def capture_request(req, timeout=None):
            captured["data"] = req.data
            fake = MagicMock()
            fake.read.return_value = b"\x89PNG"
            fake.__enter__ = lambda s: s
            fake.__exit__ = MagicMock(return_value=False)
            return fake

        mock_urlopen.side_effect = capture_request
        chart_module.generate_weather_chart()

        body = json.loads(captured["data"].decode("utf-8"))
        labels = body["chart"]["data"]["labels"]
        for label in labels:
            self.assertRegex(label, r"^\d{2}:\d{2}$", f"Label '{label}' ist kein HH:MM-Format")


if __name__ == "__main__":
    unittest.main()
