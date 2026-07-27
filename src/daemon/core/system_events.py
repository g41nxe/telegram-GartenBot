"""System-/Betriebs-Ereignisse (nicht Sensor, nicht Scheduler) — z. B. Software-Updates."""
from .event_bus import Event


class SoftwareUpdateActivated(Event):
    """Eine neue Version läuft seit diesem Daemon-Start (ADR 0044)."""
    def __init__(self, version: str):
        self.version = version


class SoftwareUpdateRolledBack(Event):
    """Ein Update ließ sich nicht installieren; es wurde zurückgerollt (ADR 0044).

    target_version: die Version, die installiert werden sollte.
    current_version: die Version, auf der die Steuerzentrale weiterläuft.
    """
    def __init__(self, target_version: str, current_version: str):
        self.target_version = target_version
        self.current_version = current_version


class SoftwareUpdateFailed(Event):
    """Ein Update-Versuch brach ab, BEVOR ein sauberer Rollback lief (Ticket eor, ADR 0044).

    ``update.sh`` legt vor dem riskanten Teil einen Versuchs-Marker an; überlebt der (weil das
    Skript still starb, z. B. Netz-/Kopierfehler unter ``set -e``) und läuft die Zielversion
    NICHT, meldet der Daemon-Start diesen Abbruch — im Unterschied zum sauberen Rollback ist der
    Zustand hier ungewiss.

    target_version: die Version, die installiert werden sollte.
    current_version: die Version, auf der die Steuerzentrale (noch) läuft.
    """
    def __init__(self, target_version: str, current_version: str):
        self.target_version = target_version
        self.current_version = current_version
