"""Adapter: verbindet die pure Regenereignis-Logik mit Persistenz und Ereignis-Kanal (ADR 0043).

Der Zustand liegt in `system_metadata` und überlebt damit den Neustart des
Bewässerungs-Daemons — sonst gäbe es mitten im Regen ein zweites „Regen erkannt"
und eine unvollständige Gesamtmenge.
"""
import logging
from datetime import datetime

from .. import config
from ..core import rain_event
from ..core.event_bus import EventBus
from ..core.rain_event import RainEventState
from ..core.sensor_events import RainSensorMeasured
from . import database

logger = logging.getLogger("garden_rain_event")

_ACTIVE = "rain_event_active"
_START = "rain_event_start"
_LAST_TICK = "rain_event_last_tick"
_TOTAL = "rain_event_total_mm"


class RainEventAdapter:
    """Hält den Regenereignis-Zustand und publiziert dessen Übergänge."""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.event_bus.subscribe(RainSensorMeasured, self._on_rain_sensor_measured)

    def _load(self) -> RainEventState:
        if database.get_metadata(_ACTIVE, "0") != "1":
            return RainEventState()
        try:
            return RainEventState(
                True,
                datetime.fromisoformat(database.get_metadata(_START)),
                datetime.fromisoformat(database.get_metadata(_LAST_TICK)),
                float(database.get_metadata(_TOTAL, "0")),
            )
        except (TypeError, ValueError) as e:
            logger.warning(f"Regenereignis-Zustand unlesbar ({e}) — beginne neu.")
            return RainEventState()

    def _save(self, state: RainEventState) -> None:
        database.set_metadata(_ACTIVE, "1" if state.active else "0")
        if state.active:
            database.set_metadata(_START, state.start.isoformat())
            database.set_metadata(_LAST_TICK, state.last_tick.isoformat())
            database.set_metadata(_TOTAL, str(state.total_mm))

    def _on_rain_sensor_measured(self, event: RainSensorMeasured):
        state = self._load()
        new_state, events = rain_event.advance(
            state,
            event.rainlevel_mm,
            datetime.now(),
            config.RAIN_EVENT_GRACE_MINUTES,
            config.RAIN_SENSOR_THRESHOLD_MM,   # dieselbe Schwelle wie beim Parsen
        )
        if new_state != state:
            self._save(new_state)
        for e in events:
            self.event_bus.publish(e)
