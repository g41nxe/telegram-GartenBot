import logging
from datetime import datetime
from ..core.event_bus import EventBus
from . import database
from ..core.watering_events import (
    WateringCycleStarted,
    WateringCycleCompleted,
    WateringCycleFailed,
    WateringCycleStopped,
    WateringCycleInterrupted,
)
from .mqtt_client import ValveStatusReported
from ..core.scheduler_events import WeatherDataFetched, WateringSkipped
from ..core.sensor_events import RainSensorMeasured
from ..core.mist_events import MistIntervalStarted, MistIntervalEnded
from ..core.camera_events import TimedPhotoDeliveryFailed

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
        self.event_bus.subscribe(WateringCycleInterrupted, self._on_cycle_interrupted)
        self.event_bus.subscribe(ValveStatusReported, self._on_valve_status_reported)
        self.event_bus.subscribe(WeatherDataFetched, self._on_weather_data_fetched)
        self.event_bus.subscribe(WateringSkipped, self._on_watering_skipped)
        self.event_bus.subscribe(RainSensorMeasured, self._on_rain_sensor_measured)
        self.event_bus.subscribe(MistIntervalStarted, self._on_mist_started)
        self.event_bus.subscribe(MistIntervalEnded, self._on_mist_ended)
        self.event_bus.subscribe(TimedPhotoDeliveryFailed, self._on_timed_photo_delivery_failed)

    def _on_watering_skipped(self, event: WateringSkipped):
        """Ticket 6l3: journalt den bewusst uebersprungenen Guss (Rule 2, statt Direktaufruf im Scheduler)."""
        database.log_watering(event.duration, "schedule", "skipped", f"Zeitplan '{event.schedule_name}': {event.details}")

    def _on_timed_photo_delivery_failed(self, event: TimedPhotoDeliveryFailed):
        """Öffnet den Aufnahme-Zeitpunkt wieder, ohne den Anker zu zerstören.

        Der Schlüssel beantwortet zwei Fragen: „Was ist bedient?" (Empfänger) und „Ab wo suche
        ich nach verpassten Zeitpunkten?" (Kamera-Überwachung). Ihn zu leeren beantwortete die
        erste richtig und machte die zweite blind — ohne Anker meldet der Prüflauf bewusst
        nichts (Schutz vor der Alarm-Flut nach Neustart). Wir setzen ihn deshalb auf eine
        Sekunde VOR den Zeitpunkt: Der Zeitpunkt liegt danach, ist also wieder offen; alles
        Ältere liegt davor, gilt also weiterhin als erledigt.
        """
        from datetime import timedelta
        anker = event.target_dt - timedelta(seconds=1)
        database.set_metadata(database.last_delivered_target_key(event.mac_address), anker.isoformat())
        logger.warning(
            f"Aufnahme-Zeitpunkt {event.target_dt} wieder geöffnet — Versand des Fotos gescheitert."
        )

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

    def _on_cycle_interrupted(self, event: WateringCycleInterrupted):
        database.log_watering(event.duration_run, event.source, "interrupted", event.details, watered_volume=event.volume_run)

    def _on_mist_started(self, event: MistIntervalStarted):
        database.log_watering(0, event.source, "started", "Nebel-Intervall gestartet.")

    def _on_mist_ended(self, event: MistIntervalEnded):
        # Pro Fenster genau ein Abschluss-Eintrag; einzelne Nebelstöße werden nicht protokolliert.
        database.log_watering(event.duration_run, event.source, "completed", event.details)

    def _on_valve_status_reported(self, event: ValveStatusReported):
        now = datetime.now().isoformat()
        database.log_device_status(event.mqtt_name, event.battery, event.linkquality)
        database.update_valve_status(event.mqtt_name, event.battery, event.linkquality, now, event.valve_abnormal_state)

    def _on_rain_sensor_measured(self, event: RainSensorMeasured):
        database.log_rain_measurement(
            event.rainlevel_mm,
            event.raintotal_mm,
            event.temperature_c,
            event.battery_pct,
        )

    def _on_weather_data_fetched(self, event: WeatherDataFetched):
        database.log_weather(
            event.rain_last_24h,
            event.rain_next_24h,
            event.current_temp,
            event.weather_code,
            event.temp_min,
            event.temp_max,
            event.rain_prob,
            current_precipitation_mm=event.current_precipitation,
            hourly_forecast_json=event.hourly_forecast_json,
            rain_last_source=event.rain_last_source,
        )


