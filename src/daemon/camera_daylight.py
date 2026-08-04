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


def photo_allowed():
    """Der Aufnahme-Filter ``(target_dt, label) -> bool`` — oder None, wenn nicht gefiltert wird.

    None kommt in drei Fällen: keine Koordinaten in der `.env` (Standard 0.0/0.0 wäre der
    Golf von Guinea — lieber gar nicht filtern als am falschen Ort), leere Typmenge, oder
    beides. In allen dreien bleibt das bisherige Verhalten unverändert.
    """
    lat, lon = config.LATITUDE, config.LONGITUDE
    if not lat and not lon:
        logger.debug("Keine Koordinaten konfiguriert — Tageslicht-Filter bleibt aus.")
        return None

    is_daylight = sun.daylight_predicate(
        lat, lon, config.CAMERA_DAYLIGHT_MARGIN_MINUTES, tz=local_tz()
    )
    return camera_schedule.daylight_filter(is_daylight, config.CAMERA_DAYLIGHT_FILTER_TYPES)
