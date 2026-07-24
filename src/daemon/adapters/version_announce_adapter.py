"""Start-Adapter der Update-Benachrichtigung (ADR 0044).

Liest beim Daemon-Start den Versions-/Rollback-Zustand, entscheidet über den puren Kern,
schreibt den Zustand **zuerst** fort und publiziert dann das Ereignis auf den Ereignis-Kanal.
Die Telegram-UI abonniert die Ereignisse und formuliert den Text (Regel 2: kein direkter
UI-Aufruf hier).
"""
import logging
from pathlib import Path

from .. import config
from ..core import version_announce
from ..core.event_bus import EventBus
from . import database

logger = logging.getLogger("garden_version_announce")

_ANNOUNCED_KEY = "announced_version"
_ROLLBACK_MARKER = Path("/tmp/garden-ota-rollback")


def _read_rollback_marker():
    try:
        if _ROLLBACK_MARKER.exists():
            return _ROLLBACK_MARKER.read_text().strip() or None
    except Exception as e:
        logger.warning(f"Rollback-Marker unlesbar: {e}")
    return None


def _clear_rollback_marker():
    try:
        _ROLLBACK_MARKER.unlink(missing_ok=True)
    except Exception as e:
        logger.warning(f"Rollback-Marker nicht löschbar: {e}")


def announce_on_start(event_bus: EventBus) -> None:
    """Meldet einmalig einen Versionswechsel bzw. Rollback beim Daemon-Start."""
    current = config.read_version()
    announced = database.get_metadata(_ANNOUNCED_KEY, "")
    rollback_target = _read_rollback_marker()

    event, new_announced = version_announce.decide(current, announced, rollback_target)

    # Zustand ZUERST festschreiben (höchstens einmal), dann publizieren.
    if new_announced != announced:
        database.set_metadata(_ANNOUNCED_KEY, new_announced)
    if rollback_target:
        _clear_rollback_marker()

    if event is not None:
        event_bus.publish(event)
