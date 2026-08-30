"""Verdichtet die Upload-Telemetrie einer Kamera zu einer Aussage (Ticket top).

Die Frage lautet: Wertet die Kamera Uploads als gescheitert, die die Steuerzentrale als
erfolgreich protokolliert hat? Sie ist nur zu beantworten, wenn man beide Seiten
nebeneinanderlegt — was die Kamera meldet (`fail_count`, `wifi_connect_ms`) und was die
Steuerzentrale selbst gemessen hat (`request_ms`, die Dauer des offenen /upload-Requests).

Kein I/O: Die Zeilen holt der Adapter, die Aussage entsteht hier.
"""
from __future__ import annotations


def _mittel(werte: list) -> int | None:
    return round(sum(werte) / len(werte)) if werte else None


def summarize(rows: list) -> dict | None:
    """Verdichtet die Telemetrie-Zeilen einer Kamera; None, wenn es keine gibt.

    Erwartet die Zeilen neueste zuerst (so liefert sie `database.get_camera_telemetry`),
    damit `fail_count_last` den aktuellen Stand nennt.

    `has_camera_metrics` unterscheidet zwei Fälle, die sonst gleich aussähen: eine Kamera,
    die 0 Fehlschläge meldet, und eine Firmware, die überhaupt nichts meldet. Der zweite
    Fall beantwortet die Vorfrage, ob die Telemetrie-Header ankommen.
    """
    if not rows:
        return None

    fails = [r["fail_count"] for r in rows if r.get("fail_count") is not None]
    wifi = [r["wifi_connect_ms"] for r in rows if r.get("wifi_connect_ms") is not None]
    request = [r["request_ms"] for r in rows if r.get("request_ms") is not None]

    return {
        "uploads": len(rows),
        "has_camera_metrics": bool(fails or wifi),
        "fail_count_last": fails[0] if fails else None,
        "fail_count_max": max(fails) if fails else None,
        # Der Kern der Verdachtsfrage: Uploads, die hier ankamen, während die Kamera von
        # vorangegangenen Fehlschlägen berichtet.
        "uploads_with_failures": sum(1 for f in fails if f > 0),
        "wifi_connect_ms_avg": _mittel(wifi),
        "request_ms_avg": _mittel(request),
        # Für die Frage wichtiger als der Mittelwert: Ein einzelner langer Request reicht,
        # damit die Kamera in ihr Timeout läuft.
        "request_ms_max": max(request) if request else None,
    }


def format_line(wish_name: str, summary: dict | None) -> str:
    """Eine Zeile für den Diagnose-Bericht."""
    if summary is None:
        return f"Kamera {wish_name}: keine Uploads protokolliert"

    anzahl = summary["uploads"]
    teile = [f"{anzahl} Upload" if anzahl == 1 else f"{anzahl} Uploads"]
    if summary["has_camera_metrics"]:
        teile.append(
            f"Fehlschläge zuletzt {summary['fail_count_last']}, max {summary['fail_count_max']}"
        )
        teile.append(f"betroffene Uploads {summary['uploads_with_failures']}")
        if summary["wifi_connect_ms_avg"] is not None:
            teile.append(f"WLAN-Aufbau {summary['wifi_connect_ms_avg']} ms im Mittel")
    else:
        teile.append("keine Kamera-Kennzahlen gemeldet")

    if summary["request_ms_avg"] is not None:
        teile.append(
            f"Bearbeitung {summary['request_ms_avg']} ms im Mittel, "
            f"max {summary['request_ms_max']} ms"
        )

    return f"Kamera {wish_name}: " + " · ".join(teile)
