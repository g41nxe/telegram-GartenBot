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
# Ticket eor: update.sh legt diesen Marker VOR dem riskanten Teil an und löscht ihn nur bei
# bestätigtem Erfolg. Überlebt er (Skript still gestorben), meldet der Start den Abbruch.
_ATTEMPT_MARKER = Path("/tmp/garden-ota-attempt")


def _read_marker(path: Path):
    try:
        if path.exists():
            return path.read_text().strip() or None
    except Exception as e:
        logger.warning(f"Marker {path} unlesbar: {e}")
    return None


def _clear_marker(path: Path):
    try:
        path.unlink(missing_ok=True)
    except Exception as e:
        logger.warning(f"Marker {path} nicht löschbar: {e}")


def _read_rollback_marker():
    return _read_marker(_ROLLBACK_MARKER)


def _clear_rollback_marker():
    _clear_marker(_ROLLBACK_MARKER)


def _read_attempt_marker():
    return _read_marker(_ATTEMPT_MARKER)


def _clear_attempt_marker():
    _clear_marker(_ATTEMPT_MARKER)


def announce_on_start(event_bus: EventBus) -> None:
    """Meldet einmalig einen Versionswechsel, Rollback oder abgebrochenen Versuch beim Start."""
    current = config.read_version()
    announced = database.get_metadata(_ANNOUNCED_KEY, "")
    rollback_target = _read_rollback_marker()
    attempt_target = _read_attempt_marker()

    event, new_announced = version_announce.decide(
        current, announced, rollback_target, attempt_target)

    # Zustand ZUERST festschreiben (höchstens einmal), dann publizieren.
    if new_announced != announced:
        database.set_metadata(_ANNOUNCED_KEY, new_announced)
    # Beide Marker verbrauchen — ein konsumierter Rollback/Versuch darf nicht erneut melden.
    if rollback_target:
        _clear_rollback_marker()
    if attempt_target:
        _clear_attempt_marker()

    if event is not None:
        event_bus.publish(event)
