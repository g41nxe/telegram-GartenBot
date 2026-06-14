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

_RAINY_FORECAST = json.dumps({
    "times":      ["2026-06-13T14:00", "2026-06-13T15:00", "2026-06-13T16:00"],
    "temp":       [18.0, 17.0, 16.0],
    "precip_mm":  [1.5, 2.0, 1.0],   # Summe 4.5mm ≥ RAIN_THRESHOLD_MM (3.0)
    "precip_prob":[70, 90, 80],
    "wmo":        [61, 63, 61],
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

_LAST_WEATHER_RAINY = {
    **_LAST_WEATHER_WITH_FORECAST,
    "hourly_forecast_json": _RAINY_FORECAST,
}


def _make_mock_urlopen(png_bytes=b"\x89PNG\r\nfake"):
    fake = MagicMock()
    fake.read.return_value = png_bytes
    fake.__enter__ = lambda s: s
    fake.__exit__ = MagicMock(return_value=False)
    return fake


def _capture_and_return(png_bytes=b"\x89PNG"):
    """Helper: urlopen side_effect that captures the request and returns fake PNG."""
    captured = {}

    def side_effect(req, timeout=None):
        captured["data"] = req.data
        fake = MagicMock()
        fake.read.return_value = png_bytes
        fake.__enter__ = lambda s: s
        fake.__exit__ = MagicMock(return_value=False)
        return fake

    return side_effect, captured


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
    def test_returns_tuple_on_success(self, mock_urlopen, _):
        mock_urlopen.return_value = _make_mock_urlopen()
        result = chart_module.generate_weather_chart()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_first_element_is_png_bytes(self, mock_urlopen, _):
        fake_png = b"\x89PNG\r\nfake"
        mock_urlopen.return_value = _make_mock_urlopen(fake_png)
        result = chart_module.generate_weather_chart()
        self.assertEqual(result[0], fake_png)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_second_element_is_string(self, mock_urlopen, _):
        mock_urlopen.return_value = _make_mock_urlopen()
        result = chart_module.generate_weather_chart()
        self.assertIsInstance(result[1], str)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen", side_effect=urllib.error.URLError("timeout"))
    def test_returns_none_on_network_error(self, _, __):
        result = chart_module.generate_weather_chart()
        self.assertIsNone(result)

    # --- Caption ---

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_caption_recommends_watering_when_dry(self, mock_urlopen, _):
        """Niederschlagsumme < RAIN_THRESHOLD_MM → Gießen empfohlen."""
        mock_urlopen.return_value = _make_mock_urlopen()
        _, caption = chart_module.generate_weather_chart()
        self.assertIn("Gießen empfohlen", caption)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_RAINY)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_caption_skips_watering_when_rain_expected(self, mock_urlopen, _):
        """Niederschlagsumme ≥ RAIN_THRESHOLD_MM → Kein Gießen nötig."""
        mock_urlopen.return_value = _make_mock_urlopen()
        _, caption = chart_module.generate_weather_chart()
        self.assertIn("Kein Gießen", caption)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_RAINY)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_caption_shows_rain_amount(self, mock_urlopen, _):
        """Bei Regen-Caption wird die Gesamtmenge angezeigt."""
        mock_urlopen.return_value = _make_mock_urlopen()
        _, caption = chart_module.generate_weather_chart()
        self.assertIn("mm", caption)

    # --- Chart-Inhalt ---

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_no_probability_dataset(self, mock_urlopen, _):
        """Wahrscheinlichkeits-Dataset darf nicht mehr im Chart sein."""
        side_effect, captured = _capture_and_return()
        mock_urlopen.side_effect = side_effect
        chart_module.generate_weather_chart()
        body = json.loads(captured["data"].decode("utf-8"))
        dataset_labels = [d["label"] for d in body["chart"]["data"]["datasets"]]
        self.assertFalse(
            any("ahrscheinlichkeit" in lbl for lbl in dataset_labels),
            f"Probability dataset gefunden: {dataset_labels}"
        )

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_precipitation_bars_have_array_background_color(self, mock_urlopen, _):
        """Balken-Opazität muss als Array kodiert sein (eine Farbe pro Stunde)."""
        side_effect, captured = _capture_and_return()
        mock_urlopen.side_effect = side_effect
        chart_module.generate_weather_chart()
        body = json.loads(captured["data"].decode("utf-8"))
        datasets = body["chart"]["data"]["datasets"]
        bar_ds = next(d for d in datasets if d.get("type") == "bar")
        self.assertIsInstance(
            bar_ds["backgroundColor"], list,
            "backgroundColor muss eine Liste sein (Opazität pro Stunde)"
        )

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_bar_colors_reflect_probability(self, mock_urlopen, _):
        """Höhere Wahrscheinlichkeit → höhere Opazität im rgba-Farbwert."""
        side_effect, captured = _capture_and_return()
        mock_urlopen.side_effect = side_effect
        chart_module.generate_weather_chart()
        body = json.loads(captured["data"].decode("utf-8"))
        datasets = body["chart"]["data"]["datasets"]
        bar_ds = next(d for d in datasets if d.get("type") == "bar")
        colors = bar_ds["backgroundColor"]
        # precip_prob = [5, 10, 55] → Opazitäten sollen strikt steigen
        # Opazitätswert aus rgba-String extrahieren
        def extract_alpha(rgba_str):
            # "rgba(54, 162, 235, 0.19)" → 0.19
            return float(rgba_str.split(",")[-1].replace(")", "").strip())
        alphas = [extract_alpha(c) for c in colors]
        self.assertLess(alphas[0], alphas[1])
        self.assertLess(alphas[1], alphas[2])

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_post_payload_contains_chart_key(self, mock_urlopen, _):
        side_effect, captured = _capture_and_return()
        mock_urlopen.side_effect = side_effect
        chart_module.generate_weather_chart()
        body = json.loads(captured["data"].decode("utf-8"))
        self.assertIn("chart", body)
        self.assertIn("datasets", body["chart"]["data"])

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_labels_every_third_hour(self, mock_urlopen, _):
        side_effect, captured = _capture_and_return()
        mock_urlopen.side_effect = side_effect
        chart_module.generate_weather_chart()
        body = json.loads(captured["data"].decode("utf-8"))
        labels = body["chart"]["data"]["labels"]
        for i, label in enumerate(labels):
            if i % 3 == 0:
                self.assertRegex(label, r"^\d{2}:\d{2}$", f"Label [{i}] '{label}' ist kein HH:MM-Format")
            else:
                self.assertEqual(label, "", f"Label [{i}] sollte leer sein")

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_payload_includes_version_4(self, mock_urlopen, _):
        side_effect, captured = _capture_and_return()
        mock_urlopen.side_effect = side_effect
        chart_module.generate_weather_chart()
        body = json.loads(captured["data"].decode("utf-8"))
        self.assertEqual(body.get("version"), "4")


if __name__ == "__main__":
    unittest.main()
