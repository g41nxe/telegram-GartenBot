"""Entscheidung, ob sich die Steuerzentrale beim Daemon-Start meldet (ADR 0044).

Rein — kein I/O: aktuelle Version, zuletzt gemeldete Version und ein etwaiges Rollback-Ziel
kommen herein; heraus geht das auszulösende Ereignis (oder None) und der neue „gemeldet"-Wert.
Das I/O (VERSION lesen, system_metadata, Marker-Datei) und die Publikation macht der Adapter.
"""
from __future__ import annotations

from .system_events import (
    SoftwareUpdateActivated, SoftwareUpdateRolledBack, SoftwareUpdateFailed,
)

_UNKNOWN = "unbekannt"


def decide(current: str, announced: str, rollback_target: str | None,
           attempt_target: str | None = None):
    """(auszulösendes Ereignis oder None, neuer announced-Wert).

    ``rollback_target`` (Rollback-Marker) und ``attempt_target`` (Versuchs-Marker) sind die zwei
    Fehlersignale von ``update.sh``: ein Rollback wurde sauber durchgeführt bzw. ein Versuch brach
    ab, bevor ein Rollback lief (Ticket eor).
    """
    # 1. Sauberer Rollback hat Vorrang — unabhängig vom Versions-Diff melden.
    if rollback_target:
        return SoftwareUpdateRolledBack(rollback_target, current), current

    # 2. Ohne gültige Version nichts melden und nichts fortschreiben (Simulation/keine VERSION).
    #    (Verhindert zugleich, dass „unbekannt" fälschlich als abgebrochener Versuch gilt.)
    if current == _UNKNOWN:
        return None, announced

    # 3. Versuchs-Marker, aber die Zielversion läuft NICHT -> der Versuch scheiterte still.
    #    (Läuft die Zielversion, ist es der Health-Check-Race = Erfolg -> unten via Versions-Diff.)
    if attempt_target and current != attempt_target:
        return SoftwareUpdateFailed(attempt_target, current), announced

    # 4. Neue Version (inkl. Erststart mit leerem announced) -> melden; sonst still.
    if current != announced:
        return SoftwareUpdateActivated(current), current
    return None, announced
