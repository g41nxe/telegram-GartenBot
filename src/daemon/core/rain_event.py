"""Regenereignis-Zustandslogik (ADR 0043).

Trennt die einzelne **Regen-Messung** vom zusammenhängenden **Regenereignis**: Ein Kipp
der Regenwippe startet das Ereignis, beendet wird es erst, wenn die **Karenzzeit** ohne
weiteren Kipp verstrichen ist. Rein — kein I/O, keine Datenbank: Zustand und Zeit kommen
herein, neuer Zustand und ausgelöste Ereignisse gehen heraus. Persistenz und Publikation
übernimmt der Adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .sensor_events import RainEventEnded, RainEventStarted

DEFAULT_THRESHOLD_MM = 0.1   # ab hier gilt eine Messung als Kipp (RAIN_SENSOR_THRESHOLD_MM)


@dataclass
class RainEventState:
    """Der überlebende Zustand eines Regenereignisses."""
    active: bool = False
    start: datetime | None = None
    last_tick: datetime | None = None
    total_mm: float = 0.0


def advance(
    state: RainEventState,
    rainlevel_mm: float,
    now: datetime,
    grace_minutes: float,
    threshold_mm: float = DEFAULT_THRESHOLD_MM,
) -> tuple[RainEventState, list]:
    """Verarbeitet eine Regen-Messung und liefert (neuer Zustand, ausgelöste Ereignisse)."""
    is_tick = rainlevel_mm >= threshold_mm

    if is_tick:
        if not state.active:
            return RainEventState(True, now, now, round(rainlevel_mm, 2)), [RainEventStarted()]
        return (
            RainEventState(True, state.start, now, round(state.total_mm + rainlevel_mm, 2)),
            [],
        )

    if not state.active:
        return state, []

    # Kein Kipp: Ereignis endet erst, wenn die Karenzzeit seit dem letzten Kipp verstrichen ist.
    if now - state.last_tick < timedelta(minutes=grace_minutes):
        return state, []

    duration = int(round((state.last_tick - state.start).total_seconds() / 60))
    return RainEventState(), [RainEventEnded(round(state.total_mm, 2), duration)]
