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
from ..core.sensor_events import RainSensorMeasured
from . import database

logger = logging.getLogger("garden_rain_event")


class RainEventAdapter:
    """Hält den Regenereignis-Zustand und publiziert dessen Übergänge.

    (De-)Serialisierung des überlebenden Zustands liegt zentral in database (Ticket cs9,
    ADR 0045) — der Adapter besitzt nur noch die Übergangs-Logik, nicht die Schlüssel.
    """

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.event_bus.subscribe(RainSensorMeasured, self._on_rain_sensor_measured)

    def _on_rain_sensor_measured(self, event: RainSensorMeasured):
        state = database.get_rain_event_state()
        new_state, events = rain_event.advance(
            state,
            event.rainlevel_mm,
            datetime.now(),
            config.RAIN_EVENT_GRACE_MINUTES,
            config.RAIN_SENSOR_THRESHOLD_MM,   # dieselbe Schwelle wie beim Parsen
        )
        if new_state != state:
            database.set_rain_event_state(new_state)
        for e in events:
            self.event_bus.publish(e)
