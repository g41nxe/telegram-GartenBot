"""Tageslicht-Regel für Aufnahme-Zeitpunkte — die Verdrahtung aus der Konfiguration.

`core/sun.py` weiß, wann die Sonne steht; `core/camera_schedule.py` weiß, was ein
Aufnahme-Zeitpunkt ist. Beide sind bewusst rein und kennen die Konfiguration nicht. Dieses
Modul ist die Naht dazwischen: Es liest Koordinaten, Zeitzone, Puffer und Typmenge und baut
daraus den einen Filter, den alle vier Verbraucher (Schlafdauer, Zustellung, Watchdog,
Bot-Anzeige) übergeben. Ohne diese Naht müsste jeder von ihnen dieselben fünf Config-Werte
zusammensetzen — und die vier Kopien liefen auseinander.

Ort nach ADR 0045: Der Code ist an die Konfiguration gekoppelt, nicht an ein Adapter-Format,
und wird von `adapters/` wie von `ui/` gebraucht. Als Adapter läge er falsch (Regel 1:
Adapter importieren einander nicht), als Kern-Modul auch (er liest Konfiguration).
"""
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import config
from .core import sun
from .core import camera_schedule

logger = logging.getLogger("garden_camera_daylight")


def local_tz():
    """Konfigurierte Zeitzone. Unbekannter Name → None, damit naiv gerechnet wird
    statt abzustürzen (Ticket fok)."""
    try:
        return ZoneInfo(config.TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError) as e:
        logger.warning(f"Unbekannte TIMEZONE '{config.TIMEZONE}': {e} — rechne naiv.")
        return None


def build_photo_filter():
    """Baut den Aufnahme-Filter ``(moment, label) -> bool`` — oder None, wenn nicht gefiltert wird.

    None heißt „Verhalten wie vorher" und ist der sichere Rückfall. Er greift, sobald eine
    Voraussetzung fehlt, statt mit einem falschen Tageslicht-Fenster zu arbeiten — ein um
    Stunden verschobenes Fenster unterdrückt Fotos am hellen Tag und lässt nächtliche durch,
    also genau das Gegenteil des Gewollten.
    """
    types = config.CAMERA_DAYLIGHT_FILTER_TYPES
    if not types:
        return None

    unbekannt = set(types) - camera_schedule.TARGET_TYPES
    if unbekannt:
        logger.warning(
            f"CAMERA_DAYLIGHT_FILTER_TYPES enthält unbekannte Werte {sorted(unbekannt)} — "
            f"gültig sind {sorted(camera_schedule.TARGET_TYPES)}. Sie bleiben wirkungslos."
        )

    lat, lon = config.LATITUDE, config.LONGITUDE
    if not lat and not lon:
        # Vorgabe 0.0/0.0 heißt „nicht konfiguriert" — das wäre der Golf von Guinea.
        logger.debug("Keine Koordinaten konfiguriert — Tageslicht-Filter bleibt aus.")
        return None
    if not lat or not lon:
        # Nur eine der beiden gesetzt: fast sicher eine halb ausgefüllte .env. Der Ort läge
        # auf dem Nullmeridian oder dem Äquator und das Fenster wäre um Stunden verschoben.
        logger.warning(
            f"Unvollständige Koordinaten (LATITUDE={lat}, LONGITUDE={lon}) — "
            f"Tageslicht-Filter bleibt aus."
        )
        return None

    tz = local_tz()
    if tz is None:
        # Ohne Zeitzone rechnete `sun` in UTC, die Aufnahme-Zeitpunkte sind aber lokale
        # Wanduhrzeit — in Berlin läge das Fenster im Sommer zwei Stunden zu früh.
        logger.warning(
            f"Zeitzone '{config.TIMEZONE}' unbrauchbar — Tageslicht-Filter bleibt aus."
        )
        return None

    is_daylight = sun.daylight_predicate(
        lat, lon, config.CAMERA_DAYLIGHT_MARGIN_MINUTES, tz=tz
    )
    return camera_schedule.daylight_filter(is_daylight, types)
