import json
import logging
import urllib.request
import urllib.error
from . import database

logger = logging.getLogger("garden_chart")

QUICKCHART_URL = "https://quickchart.io/chart"
# QuickChart.io defaults to Chart.js v2 — "version": "4" is required for v3+ syntax
# (scales as objects with ID-keys, per-dataset type overrides). Omitting it causes HTTP 400.


def generate_weather_chart() -> bytes | None:
    """
    Liest hourly_forecast_json aus dem letzten weather_history-Eintrag,
    baut eine Chart.js-Konfiguration und sendet diese per POST an QuickChart.io.
    Gibt PNG-Bytes zurück oder None bei Fehler / fehlenden Daten (→ Textfallback).
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
    except (json.JSONDecodeError, TypeError) as e:
        logger.error(f"Chart-Generierung fehlgeschlagen: ungültiges JSON. Nutze Textfallback.")
        return None

    times = forecast.get("times", [])
    temps = forecast.get("temp", [])
    precip_mm = forecast.get("precip_mm", [])
    precip_prob = forecast.get("precip_prob", [])

    if not times:
        logger.warning("Keine Stundendaten für Chart verfügbar.")
        return None

    # Zeitachse: nur HH:MM anzeigen
    labels = [t[11:16] if len(t) >= 16 else t for t in times]

    chart_config = {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "type": "line",
                    "label": "Temperatur (°C)",
                    "data": temps,
                    "borderColor": "rgb(255, 99, 132)",
                    "backgroundColor": "rgba(255, 99, 132, 0.1)",
                    "yAxisID": "yTemp",
                    "tension": 0.3,
                    "pointRadius": 2,
                },
                {
                    "type": "bar",
                    "label": "Niederschlag (mm)",
                    "data": precip_mm,
                    "backgroundColor": "rgba(54, 162, 235, 0.7)",
                    "yAxisID": "yPrecip",
                },
                {
                    "type": "line",
                    "label": "Regenwahrscheinlichkeit (%)",
                    "data": precip_prob,
                    "borderColor": "rgb(75, 192, 192)",
                    "backgroundColor": "rgba(75, 192, 192, 0.1)",
                    "yAxisID": "yProb",
                    "tension": 0.3,
                    "pointRadius": 2,
                },
            ],
        },
        "options": {
            "plugins": {
                "title": {
                    "display": True,
                    "text": "Wetterverlauf — nächste 24h",
                }
            },
            "scales": {
                "yTemp": {
                    "type": "linear",
                    "position": "left",
                    "title": {"display": True, "text": "°C"},
                },
                "yPrecip": {
                    "type": "linear",
                    "position": "right",
                    "title": {"display": True, "text": "mm"},
                    "grid": {"drawOnChartArea": False},
                },
                "yProb": {
                    "type": "linear",
                    "position": "right",
                    "title": {"display": True, "text": "%"},
                    "min": 0,
                    "max": 100,
                    "grid": {"drawOnChartArea": False},
                    "display": False,
                },
            },
        },
    }

    payload = json.dumps({"chart": chart_config, "width": 600, "height": 300, "version": "4"}).encode("utf-8")

    try:
        req = urllib.request.Request(
            QUICKCHART_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            image_bytes = response.read()
        return image_bytes
    except Exception as e:
        logger.error(f"Chart-Generierung fehlgeschlagen: {e}. Nutze Textfallback.")
        return None
