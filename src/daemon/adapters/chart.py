import json
import logging
import math
import urllib.request
import urllib.error
from . import database
from .. import config
from ..core.watering_advice import evaluate_rain_window

logger = logging.getLogger("garden_chart")

QUICKCHART_URL = "https://quickchart.io/chart"
# QuickChart.io defaults to Chart.js v2 — "version": "4" is required for v3+ syntax
# (scales as objects with ID-keys, per-dataset type overrides). Omitting it causes HTTP 400.


def _bar_color(prob: int) -> str:
    """Berechnet rgba-Farbe für einen Niederschlagsbalken basierend auf der Wahrscheinlichkeit.

    alpha = 0.15 (Minimum) + 0.75 * (prob / 100), sodass auch unsichere Stunden
    sichtbar bleiben, aber klarer Regen (100%) deutlich dunkler erscheint.
    """
    alpha = round(0.15 + 0.75 * (max(0, min(100, prob)) / 100), 3)
    return f"rgba(54, 162, 235, {alpha})"


def _build_caption(rain_last_24h_mm: float, rain_next_24h_mm: float) -> str:
    result = evaluate_rain_window(rain_last_24h_mm, rain_next_24h_mm, config.RAIN_THRESHOLD_MM)
    if result.skip:
        return f"🌤 Wetterverlauf — nächste 24h\n☔ Kein Gießen nötig — Regen erwartet ({result.total_mm:.1f}mm)"
    return "🌤 Wetterverlauf — nächste 24h\n🌱 Gießen empfohlen — trocken bis morgen"


def generate_weather_chart() -> tuple[bytes, str] | None:
    """
    Liest hourly_forecast_json aus dem letzten weather_history-Eintrag,
    baut eine Chart.js-Konfiguration und sendet diese per POST an QuickChart.io.
    Gibt (PNG-Bytes, Caption-String) zurück oder None bei Fehler / fehlenden Daten.
    """
    last_weather = database.get_last_weather()
    if not last_weather:
        logger.warning("Keine Stundendaten für Chart verfügbar.")
        return None

    raw_json = last_weather.get("hourly_forecast_json")
    if not raw_json:
        logger.warning("Keine Stundendaten für Chart verfügbar.")
        return None

    try:
        forecast = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        logger.error("Chart-Generierung fehlgeschlagen: ungültiges JSON. Nutze Textfallback.")
        return None

    times = forecast.get("times", [])
    temps = forecast.get("temp", [])
    precip_mm = forecast.get("precip_mm", [])
    precip_prob = forecast.get("precip_prob", [])

    if not times:
        logger.warning("Keine Stundendaten für Chart verfügbar.")
        return None

    # Nur jede 3. Stunde beschriften, Rest leer lassen
    labels = []
    for i, t in enumerate(times):
        hour_str = t[11:16] if len(t) >= 16 else t
        labels.append(hour_str if i % 3 == 0 else "")

    bar_colors = [
        _bar_color(precip_prob[i] if i < len(precip_prob) else 0)
        for i in range(len(times))
    ]

    precip_max = max(precip_mm) if precip_mm else 0

    chart_config = {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "type": "line",
                    "label": "Temperatur (°C)",
                    "data": temps,
                    "borderColor": "rgb(255, 159, 64)",
                    "backgroundColor": "rgba(0,0,0,0)",
                    "fill": False,
                    "yAxisID": "yTemp",
                    "tension": 0.3,
                    "pointRadius": 0,
                    "borderWidth": 2,
                },
                {
                    "type": "bar",
                    "label": "Niederschlag (mm)",
                    "data": precip_mm,
                    "backgroundColor": bar_colors,
                    "yAxisID": "yPrecip",
                },
            ],
        },
        "options": {
            "plugins": {
                "title": {
                    "display": True,
                    "text": "Wetterverlauf — nächste 24h",
                    "font": {"size": 14, "weight": "bold"},
                },
                "legend": {"display": False},
                "datalabels": {"display": False},
                "annotation": {
                    "annotations": {
                        "zeroLine": {
                            "type": "line",
                            "yMin": 0,
                            "yMax": 0,
                            "yScaleID": "yTemp",
                            "borderColor": "rgba(60, 60, 60, 0.35)",
                            "borderWidth": 1,
                            "borderDash": [6, 3],
                        }
                    }
                },
            },
            "scales": {
                "yTemp": {
                    "type": "linear",
                    "position": "left",
                    "title": {
                        "display": True,
                        "text": "Temperatur (°C)",
                        "font": {"size": 12},
                    },
                    "min": -10,
                    "max": 40,
                    "grid": {"color": "rgba(0,0,0,0.07)"},
                },
                "yPrecip": {
                    "type": "linear",
                    "position": "right",
                    "title": {
                        "display": True,
                        "text": "Niederschlag (mm)",
                        "font": {"size": 12},
                    },
                    "min": 0,
                    "max": max(5, math.ceil(precip_max * 1.2)),
                    "grid": {"drawOnChartArea": False},
                },
            },
        },
    }

    payload = json.dumps({
        "chart": chart_config,
        "width": 700,
        "height": 350,
        "version": "4",
        "backgroundColor": "white",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            QUICKCHART_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            image_bytes = response.read()
        rain_last = last_weather.get("rain_last_24h_mm", 0.0) or 0.0
        rain_next = last_weather.get("rain_next_24h_mm", 0.0) or 0.0
        caption = _build_caption(rain_last, rain_next)
        return image_bytes, caption
    except Exception as e:
        logger.error(f"Chart-Generierung fehlgeschlagen: {e}. Nutze Textfallback.")
        return None
