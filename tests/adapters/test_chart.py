import datetime as dt_module
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

import daemon.adapters.chart as chart_module
from daemon.core.watering_advice import WateringDecision

_FULL_DECISION = WateringDecision(factor=1.0, verdict="🚿 Voller Guss", reasons=[], skip=False)
_SKIP_DECISION = WateringDecision(factor=0.0, verdict="🌧 Kein Gießen nötig", reasons=["6 mm Regen."], skip=True)

# Festes "Jetzt" für Jetzt-Markierung-Tests
_NOW_DT = dt_module.datetime(2026, 6, 22, 14, 0, 0)
_NOW_INDEX = 24  # Position von 14:00 im 48h-Fenster (Start: 2026-06-21T14:00)

def _make_48h_times() -> list[str]:
    base = dt_module.datetime(2026, 6, 21, 14, 0, 0)
    return [(base + dt_module.timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(48)]

_TIMES_48H = _make_48h_times()

_FORECAST_48H = json.dumps({
    "times":      _TIMES_48H,
    "temp":       [20.0] * 48,
    "precip_mm":  [0.0] * 48,
    "precip_prob":[10] * 48,
    "wmo":        [0] * 48,
})

_LAST_WEATHER_48H = {
    "timestamp": "2026-06-22T14:00:00",
    "rain_last_24h_mm": 0.0,
    "rain_next_24h_mm": 0.0,
    "current_temp": 20.0,
    "weather_code": 0,
    "current_precipitation_mm": 0.0,
    "hourly_forecast_json": _FORECAST_48H,
}

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
    "precip_mm":  [1.5, 2.0, 1.0],   # Summe 4.5mm ≥ RAIN_THRESHOLD_MM (2.0)
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
    "rain_next_24h_mm": 4.5,
    "hourly_forecast_json": _RAINY_FORECAST,
}

# Viel Regen gestern, trockene Vorhersage — rain_last_24h allein überschreitet Schwellwert
_LAST_WEATHER_RAINED_YESTERDAY = {
    **_LAST_WEATHER_WITH_FORECAST,
    "rain_last_24h_mm": 5.0,   # ≥ RAIN_THRESHOLD_MM (2.0)
    "rain_next_24h_mm": 0.0,
    "hourly_forecast_json": _VALID_FORECAST,  # Vorhersage trocken (0.8mm gesamt)
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
        result = chart_module.generate_weather_chart(_FULL_DECISION)
        self.assertIsNone(result)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value={
        "hourly_forecast_json": None
    })
    def test_returns_none_when_hourly_json_is_null(self, _):
        result = chart_module.generate_weather_chart(_FULL_DECISION)
        self.assertIsNone(result)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value={
        "hourly_forecast_json": ""
    })
    def test_returns_none_when_hourly_json_is_empty(self, _):
        result = chart_module.generate_weather_chart(_FULL_DECISION)
        self.assertIsNone(result)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value={
        "hourly_forecast_json": "not-valid-json{"
    })
    def test_returns_none_when_hourly_json_is_invalid(self, _):
        result = chart_module.generate_weather_chart(_FULL_DECISION)
        self.assertIsNone(result)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value={
        "hourly_forecast_json": json.dumps({"times": []})
    })
    def test_returns_none_when_times_array_is_empty(self, _):
        result = chart_module.generate_weather_chart(_FULL_DECISION)
        self.assertIsNone(result)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_returns_tuple_on_success(self, mock_urlopen, _):
        mock_urlopen.return_value = _make_mock_urlopen()
        result = chart_module.generate_weather_chart(_FULL_DECISION)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_first_element_is_png_bytes(self, mock_urlopen, _):
        fake_png = b"\x89PNG\r\nfake"
        mock_urlopen.return_value = _make_mock_urlopen(fake_png)
        result = chart_module.generate_weather_chart(_FULL_DECISION)
        self.assertEqual(result[0], fake_png)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_second_element_is_string(self, mock_urlopen, _):
        mock_urlopen.return_value = _make_mock_urlopen()
        result = chart_module.generate_weather_chart(_FULL_DECISION)
        self.assertIsInstance(result[1], str)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen", side_effect=urllib.error.URLError("timeout"))
    def test_returns_none_on_network_error(self, _, __):
        result = chart_module.generate_weather_chart(_FULL_DECISION)
        self.assertIsNone(result)

    # --- Caption ---

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_caption_reflects_full_watering_decision(self, mock_urlopen, _):
        """Ticket ccc: Caption = das reale Verdikt der WateringDecision (voller Guss)."""
        mock_urlopen.return_value = _make_mock_urlopen()
        _, caption = chart_module.generate_weather_chart(_FULL_DECISION)
        self.assertIn("Voller Guss", caption)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_RAINY)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_caption_reflects_skip_decision(self, mock_urlopen, _):
        """Ticket ccc: bei skip=True zeigt die Caption das Skip-Verdikt der Entscheidung."""
        mock_urlopen.return_value = _make_mock_urlopen()
        _, caption = chart_module.generate_weather_chart(_SKIP_DECISION)
        self.assertIn("Kein Gießen", caption)

    # --- Chart-Inhalt ---

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_bar_dataset_has_no_datalabels(self, mock_urlopen, _):
        """Balken-Dataset darf kein datalabels-Objekt enthalten — verhindert '0'-Spam."""
        side_effect, captured = _capture_and_return()
        mock_urlopen.side_effect = side_effect
        chart_module.generate_weather_chart(_FULL_DECISION)
        body = json.loads(captured["data"].decode("utf-8"))
        datasets = body["chart"]["data"]["datasets"]
        bar_ds = next(d for d in datasets if d.get("type") == "bar")
        self.assertNotIn("datalabels", bar_ds, "Bar-Dataset enthält datalabels — erzeugt '0'-Spam")

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_zero_line_is_dark_gray(self, mock_urlopen, _):
        """0°-Linie soll dunkelgrau sein, nicht blau."""
        side_effect, captured = _capture_and_return()
        mock_urlopen.side_effect = side_effect
        chart_module.generate_weather_chart(_FULL_DECISION)
        body = json.loads(captured["data"].decode("utf-8"))
        annotations = (
            body["chart"]["options"]
            .get("plugins", {})
            .get("annotation", {})
            .get("annotations", {})
        )
        zero_line = next(
            (a for a in annotations.values()
             if a.get("yMin") == 0 and a.get("yScaleID") == "yTemp"),
            None
        )
        self.assertIsNotNone(zero_line)
        color = zero_line.get("borderColor", "")
        self.assertNotIn("130, 220", color, "0°-Linie ist noch blau — soll grau sein")

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_no_probability_dataset(self, mock_urlopen, _):
        """Wahrscheinlichkeits-Dataset darf nicht mehr im Chart sein."""
        side_effect, captured = _capture_and_return()
        mock_urlopen.side_effect = side_effect
        chart_module.generate_weather_chart(_FULL_DECISION)
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
        chart_module.generate_weather_chart(_FULL_DECISION)
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
        chart_module.generate_weather_chart(_FULL_DECISION)
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
        chart_module.generate_weather_chart(_FULL_DECISION)
        body = json.loads(captured["data"].decode("utf-8"))
        self.assertIn("chart", body)
        self.assertIn("datasets", body["chart"]["data"])

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_labels_every_third_hour(self, mock_urlopen, _):
        """Fixture-Zeiten liegen in der Vergangenheit → now_index == -1, kein Jetzt-Label."""
        side_effect, captured = _capture_and_return()
        mock_urlopen.side_effect = side_effect
        chart_module.generate_weather_chart(_FULL_DECISION)
        body = json.loads(captured["data"].decode("utf-8"))
        labels = body["chart"]["data"]["labels"]
        for i, label in enumerate(labels):
            if i % 3 == 0:
                self.assertRegex(label, r"^\d{2}:\d{2}$|^Jetzt$",
                                 f"Label [{i}] '{label}' ist kein HH:MM-Format und kein 'Jetzt'")
            else:
                self.assertEqual(label, "", f"Label [{i}] sollte leer sein")

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_zero_degree_annotation_present(self, mock_urlopen, _):
        """Horizontale Linie bei 0°C muss als Annotation vorhanden sein."""
        side_effect, captured = _capture_and_return()
        mock_urlopen.side_effect = side_effect
        chart_module.generate_weather_chart(_FULL_DECISION)
        body = json.loads(captured["data"].decode("utf-8"))
        annotations = (
            body["chart"]["options"]
            .get("plugins", {})
            .get("annotation", {})
            .get("annotations", {})
        )
        zero_lines = [
            a for a in annotations.values()
            if a.get("type") == "line"
            and a.get("yMin") == 0
            and a.get("yMax") == 0
            and a.get("yScaleID") == "yTemp"
        ]
        self.assertTrue(zero_lines, "Keine 0°-Linie in annotations gefunden")

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_payload_includes_version_4(self, mock_urlopen, _):
        side_effect, captured = _capture_and_return()
        mock_urlopen.side_effect = side_effect
        chart_module.generate_weather_chart(_FULL_DECISION)
        body = json.loads(captured["data"].decode("utf-8"))
        self.assertEqual(body.get("version"), "4")


class TestJetztMarkierung(unittest.TestCase):

    def _get_annotations(self, captured_data: bytes) -> dict:
        body = json.loads(captured_data.decode("utf-8"))
        return (
            body["chart"]["options"]
            .get("plugins", {})
            .get("annotation", {})
            .get("annotations", {})
        )

    @patch("daemon.adapters.chart.datetime")
    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_48H)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_now_line_present_when_now_in_times(self, mock_urlopen, _, mock_dt):
        mock_dt.now.return_value = _NOW_DT
        side_effect, captured = _capture_and_return()
        mock_urlopen.side_effect = side_effect
        chart_module.generate_weather_chart(_FULL_DECISION)
        annotations = self._get_annotations(captured["data"])
        now_lines = [
            a for a in annotations.values()
            if a.get("type") == "line"
            and a.get("xMin") == _NOW_INDEX
            and a.get("xMax") == _NOW_INDEX
            and "yScaleID" not in a
            and a.get("borderDash")
        ]
        self.assertTrue(now_lines, "Keine Jetzt-Linie in annotations gefunden")

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_no_now_line_when_times_in_past(self, mock_urlopen, _):
        """Fixture-Zeiten 2026-06-13 → now_index == -1 → keine nowLine."""
        side_effect, captured = _capture_and_return()
        mock_urlopen.side_effect = side_effect
        chart_module.generate_weather_chart(_FULL_DECISION)
        annotations = self._get_annotations(captured["data"])
        now_keys = [k for k in annotations if "now" in k.lower()]
        self.assertFalse(now_keys, f"Unerwartete nowLine: {now_keys}")

    @patch("daemon.adapters.chart.datetime")
    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_48H)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_now_label_is_jetzt(self, mock_urlopen, _, mock_dt):
        mock_dt.now.return_value = _NOW_DT
        side_effect, captured = _capture_and_return()
        mock_urlopen.side_effect = side_effect
        chart_module.generate_weather_chart(_FULL_DECISION)
        body = json.loads(captured["data"].decode("utf-8"))
        labels = body["chart"]["data"]["labels"]
        self.assertEqual(labels[_NOW_INDEX], "Jetzt", f"Label[{_NOW_INDEX}] soll 'Jetzt' sein")

    @patch("daemon.adapters.chart.datetime")
    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_48H)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_now_line_same_style_as_zero_line(self, mock_urlopen, _, mock_dt):
        mock_dt.now.return_value = _NOW_DT
        side_effect, captured = _capture_and_return()
        mock_urlopen.side_effect = side_effect
        chart_module.generate_weather_chart(_FULL_DECISION)
        annotations = self._get_annotations(captured["data"])
        zero_line = next(
            (a for a in annotations.values() if a.get("yScaleID") == "yTemp"), None
        )
        now_line = next(
            (a for a in annotations.values()
             if a.get("xMin") == _NOW_INDEX and "yScaleID" not in a and a.get("borderDash")),
            None,
        )
        self.assertIsNotNone(zero_line, "zeroLine nicht gefunden")
        self.assertIsNotNone(now_line, "nowLine nicht gefunden")
        self.assertEqual(now_line["borderColor"], zero_line["borderColor"])
        self.assertEqual(now_line["borderWidth"], zero_line["borderWidth"])
        self.assertEqual(now_line["borderDash"], zero_line["borderDash"])

    @patch("daemon.adapters.chart.datetime")
    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_48H)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_grid_annotations_at_every_third_position(self, mock_urlopen, _, mock_dt):
        mock_dt.now.return_value = _NOW_DT
        side_effect, captured = _capture_and_return()
        mock_urlopen.side_effect = side_effect
        chart_module.generate_weather_chart(_FULL_DECISION)
        annotations = self._get_annotations(captured["data"])
        grid_lines = {
            a["xMin"]
            for a in annotations.values()
            if a.get("type") == "line"
            and "yScaleID" not in a
            and not a.get("borderDash")
        }
        for pos in range(0, 48, 3):
            self.assertIn(pos, grid_lines, f"Grid-Annotation bei Position {pos} fehlt")

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_x_grid_disabled(self, mock_urlopen, _):
        side_effect, captured = _capture_and_return()
        mock_urlopen.side_effect = side_effect
        chart_module.generate_weather_chart(_FULL_DECISION)
        body = json.loads(captured["data"].decode("utf-8"))
        x_scale = body["chart"]["options"]["scales"].get("x", {})
        self.assertFalse(
            x_scale.get("grid", {}).get("display", True),
            "x.grid.display soll False sein"
        )

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_tick_rotation_is_45(self, mock_urlopen, _):
        side_effect, captured = _capture_and_return()
        mock_urlopen.side_effect = side_effect
        chart_module.generate_weather_chart(_FULL_DECISION)
        body = json.loads(captured["data"].decode("utf-8"))
        ticks = body["chart"]["options"]["scales"].get("x", {}).get("ticks", {})
        self.assertEqual(ticks.get("minRotation"), 45)
        self.assertEqual(ticks.get("maxRotation"), 45)

    @patch("daemon.adapters.chart.database.get_last_weather", return_value=_LAST_WEATHER_WITH_FORECAST)
    @patch("daemon.adapters.chart.urllib.request.urlopen")
    def test_chart_title_includes_letzte(self, mock_urlopen, _):
        side_effect, captured = _capture_and_return()
        mock_urlopen.side_effect = side_effect
        chart_module.generate_weather_chart(_FULL_DECISION)
        body = json.loads(captured["data"].decode("utf-8"))
        title = body["chart"]["options"]["plugins"]["title"]["text"]
        self.assertIn("letzte", title)


if __name__ == "__main__":
    unittest.main()
