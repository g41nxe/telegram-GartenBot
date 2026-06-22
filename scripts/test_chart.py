"""Standalone-Testscript für die Wetterchart-Generierung.

Baut denselben Chart-Config wie chart.py mit eingebetteten Beispieldaten,
schickt ihn an QuickChart.io und speichert das Ergebnis als PNG.

Ausführen (aus dem Repo-Root):
    python scripts/test_chart.py
    python scripts/test_chart.py --open   # öffnet das PNG danach

Kein laufender Daemon, keine Datenbank, kein MQTT erforderlich.
"""
import argparse
import json
import math
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta

QUICKCHART_URL = "https://quickchart.io/chart"
OUTPUT_FILE = "test_chart_output.png"

# 48 Datenpunkte: gestern 14:00 bis morgen 13:00, "Jetzt" = Index 24 (heute 14:00).
# Fenster passend zum Bewässerungshinweis (±24 h).
# Vergangenheit (idx 0–23): Wahrscheinlichkeit 100 % wo Regen gemessen, 0 % sonst.
# Zukunft (idx 24–47): Vorhersagewahrscheinlichkeit.
SAMPLE_DATA = {
    "times": [
        # gestern 14–23h
        "2026-06-21T14:00", "2026-06-21T15:00", "2026-06-21T16:00",
        "2026-06-21T17:00", "2026-06-21T18:00", "2026-06-21T19:00",
        "2026-06-21T20:00", "2026-06-21T21:00", "2026-06-21T22:00", "2026-06-21T23:00",
        # heute 00–13h
        "2026-06-22T00:00", "2026-06-22T01:00", "2026-06-22T02:00",
        "2026-06-22T03:00", "2026-06-22T04:00", "2026-06-22T05:00",
        "2026-06-22T06:00", "2026-06-22T07:00", "2026-06-22T08:00",
        "2026-06-22T09:00", "2026-06-22T10:00", "2026-06-22T11:00",
        "2026-06-22T12:00", "2026-06-22T13:00",
        # Jetzt: heute 14h (Index 24)
        "2026-06-22T14:00",
        # heute 15–23h
        "2026-06-22T15:00", "2026-06-22T16:00", "2026-06-22T17:00",
        "2026-06-22T18:00", "2026-06-22T19:00", "2026-06-22T20:00",
        "2026-06-22T21:00", "2026-06-22T22:00", "2026-06-22T23:00",
        # morgen 00–13h
        "2026-06-23T00:00", "2026-06-23T01:00", "2026-06-23T02:00",
        "2026-06-23T03:00", "2026-06-23T04:00", "2026-06-23T05:00",
        "2026-06-23T06:00", "2026-06-23T07:00", "2026-06-23T08:00",
        "2026-06-23T09:00", "2026-06-23T10:00", "2026-06-23T11:00",
        "2026-06-23T12:00", "2026-06-23T13:00",
    ],
    "temp": [
        23, 22, 22, 21, 19, 17, 16, 15, 14, 13,  # gestern 14–23h
        13, 13, 12, 12, 12, 12, 13, 15, 17, 19, 21, 23, 24, 24,  # heute 00–13h
        25,  # Jetzt
        26, 25, 24, 22, 20, 18, 16, 15, 14,  # heute 15–23h
        13, 13, 12, 12, 12, 12, 13, 15, 17, 19, 21, 22, 23, 24,  # morgen 00–13h
    ],
    "precip_mm": [
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  # gestern 14–23h
        0, 0, 0, 0.1, 0.1, 0, 0, 0, 0, 0, 0, 0, 0, 0,  # heute 00–13h
        0,  # Jetzt
        0.1, 0.2, 0.8, 1.2, 0.5, 0.1, 0, 0, 0,  # heute 15–23h
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  # morgen 00–13h
    ],
    "precip_prob": [
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  # gestern 14–23h
        0, 0, 0, 100, 100, 0, 0, 0, 0, 0, 0, 0, 0, 0,  # heute 00–13h (gemessen)
        10,  # Jetzt
        15, 30, 70, 85, 60, 25, 10, 5, 5,  # heute 15–23h (Vorhersage)
        5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,  # morgen 00–13h
    ],
}


def _bar_color(prob: int) -> str:
    alpha = round(0.15 + 0.75 * (max(0, min(100, prob)) / 100), 3)
    return f"rgba(54, 162, 235, {alpha})"


def _find_now_index(times: list[str]) -> int:
    now_str = datetime.now().strftime("%Y-%m-%dT%H:00")
    for i, t in enumerate(times):
        if t[:16] == now_str[:16]:
            return i
    return -1


def build_chart_config(data: dict) -> dict:
    times = data["times"]
    temps = data["temp"]
    precip_mm = data["precip_mm"]
    precip_prob = data["precip_prob"]

    now_index = _find_now_index(times)

    bar_colors = [
        _bar_color(precip_prob[i] if i < len(precip_prob) else 0)
        for i in range(len(times))
    ]
    precip_max = max(precip_mm) if precip_mm else 0

    dash_line = {
        "borderColor": "rgba(60, 60, 60, 0.35)",
        "borderWidth": 1,
        "borderDash": [6, 3],
    }

    annotations = {
        "zeroLine": {
            "type": "line",
            "yMin": 0,
            "yMax": 0,
            "yScaleID": "yTemp",
            **dash_line,
        },
    }
    # Gitternetz als Annotationen: liegen auf Balkenmitte = exakt unter Labels
    for i in range(len(times)):
        if i % 3 == 0:
            annotations[f"g{i}"] = {
                "type": "line",
                "xMin": i,
                "xMax": i,
                "borderColor": "rgba(0,0,0,0.07)",
                "borderWidth": 1,
            }
    if now_index >= 0:
        annotations["nowLine"] = {
            "type": "line",
            "xMin": now_index,
            "xMax": now_index,
            **dash_line,
        }

    labels = [
        ("Jetzt" if i == now_index else (t[11:16] if i % 3 == 0 else ""))
        for i, t in enumerate(times)
    ]

    return {
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
                    "text": "Wetterverlauf — letzte & nächste 24h",
                    "font": {"size": 14, "weight": "bold"},
                },
                "legend": {"display": False},
                "datalabels": {"display": False},
                "annotation": {"annotations": annotations},
            },
            "scales": {
                "x": {
                    "grid": {"display": False},
                    "ticks": {
                        "minRotation": 45,
                        "maxRotation": 45,
                        "font": {"size": 12},
                    },
                },
                "yTemp": {
                    "type": "linear",
                    "position": "left",
                    "title": {"display": True, "text": "Temperatur (°C)", "font": {"size": 12}},
                    "min": -10,
                    "max": 40,
                    "grid": {"color": "rgba(0,0,0,0.07)"},
                },
                "yPrecip": {
                    "type": "linear",
                    "position": "right",
                    "title": {"display": True, "text": "Niederschlag (mm)", "font": {"size": 12}},
                    "min": 0,
                    "max": max(5, math.ceil(precip_max * 1.2)),
                    "grid": {"drawOnChartArea": False},
                },
            },
        },
    }


def generate(data: dict, output: str) -> None:
    chart_config = build_chart_config(data)
    payload = json.dumps({
        "chart": chart_config,
        "width": 700,
        "height": 390,
        "version": "4",
        "backgroundColor": "white",
    }).encode("utf-8")

    print(f"Sende Chart-Request an {QUICKCHART_URL} ...")
    req = urllib.request.Request(
        QUICKCHART_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        image_bytes = resp.read()

    with open(output, "wb") as f:
        f.write(image_bytes)
    print(f"Chart gespeichert: {output} ({len(image_bytes)} Bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Wetterchart-Testgenerator")
    parser.add_argument("--open", action="store_true", help="PNG nach Erzeugung öffnen")
    parser.add_argument("--output", default=OUTPUT_FILE, help="Ausgabedatei (Standard: test_chart_output.png)")
    args = parser.parse_args()

    try:
        generate(SAMPLE_DATA, args.output)
    except urllib.error.URLError as e:
        print(f"Netzwerkfehler: {e}", file=sys.stderr)
        sys.exit(1)

    if args.open:
        import os
        os.startfile(args.output) if sys.platform == "win32" else subprocess.run(
            ["open" if sys.platform == "darwin" else "xdg-open", args.output]
        )


if __name__ == "__main__":
    main()
