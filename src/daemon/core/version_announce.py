"""Entscheidung, ob sich die Steuerzentrale beim Daemon-Start meldet (ADR 0044).

Rein — kein I/O: aktuelle Version, zuletzt gemeldete Version und ein etwaiges Rollback-Ziel
kommen herein; heraus geht das auszulösende Ereignis (oder None) und der neue „gemeldet"-Wert.
Das I/O (VERSION lesen, system_metadata, Marker-Datei) und die Publikation macht der Adapter.
"""
from __future__ import annotations

from .system_events import SoftwareUpdateActivated, SoftwareUpdateRolledBack

_UNKNOWN = "unbekannt"


def decide(current: str, announced: str, rollback_target: str | None):
    """(auszulösendes Ereignis oder None, neuer announced-Wert)."""
    # Rollback: update.sh hat einen Marker hinterlassen — unabhängig vom Versions-Diff melden.
    if rollback_target:
        return SoftwareUpdateRolledBack(rollback_target, current), current

    # Ohne gültige Version nichts melden und nichts fortschreiben.
    if current == _UNKNOWN:
        return None, announced

    # Neue Version (inkl. Erststart mit leerem announced) -> melden; sonst still.
    if current != announced:
        return SoftwareUpdateActivated(current), current
    return None, announced
