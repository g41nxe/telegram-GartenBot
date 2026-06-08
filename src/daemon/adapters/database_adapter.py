import logging
from ..core.event_bus import EventBus
from . import database
from ..core.watering_controller import (
    WateringCycleStarted,
    WateringCycleCompleted,
    WateringCycleFailed,
    WateringCycleStopped
)
from .mqtt_client import ValveStatusReported

logger = logging.getLogger("garden_database_adapter")

class DatabaseLoggerAdapter:
    """Abonniert Domänen-Ereignisse der Guss-Steuerung und archiviert diese in der SQLite-Datenbank."""
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        
        # Am Ereignis-Kanal registrieren
        self.event_bus.subscribe(WateringCycleStarted, self._on_cycle_started)
        self.event_bus.subscribe(WateringCycleCompleted, self._on_cycle_completed)
        self.event_bus.subscribe(WateringCycleFailed, self._on_cycle_failed)
        self.event_bus.subscribe(WateringCycleStopped, self._on_cycle_stopped)
        self.event_bus.subscribe(ValveStatusReported, self._on_valve_status_reported)

    def _on_cycle_started(self, event: WateringCycleStarted):
        limit_info = f"Zeitlimit: {event.duration} Min"
        if event.target_volume > 0:
            limit_info += f" | Volumenlimit: {event.target_volume} Liter"
        
        details = f"Bewässerung gestartet ({limit_info})."
        database.log_watering(event.duration, event.source, "completed", details)

    def _on_cycle_completed(self, event: WateringCycleCompleted):
        database.log_watering(event.duration_run, event.source, "completed", event.details, watered_volume=event.volume_run)

    def _on_cycle_failed(self, event: WateringCycleFailed):
        database.log_watering(event.duration_run, event.source, "failed", event.details, watered_volume=event.volume_run)

    def _on_cycle_stopped(self, event: WateringCycleStopped):
        database.log_watering(event.duration_run, event.source, "stopped", event.details, watered_volume=event.volume_run)

    def _on_valve_status_reported(self, event: ValveStatusReported):
        database.log_device_status(event.battery, event.linkquality)


