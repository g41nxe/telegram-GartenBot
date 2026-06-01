import logging
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple
from .event_bus import Event, EventBus
from ..adapters.mqtt_client import MqttClient, ValveStatusReported
from .. import config
from ..adapters import mqtt_client

logger = logging.getLogger("garden_watering_controller")

# --- Domänen-Ereignisse (Domain Events) ---

class WateringCycleStarted(Event):
    def __init__(self, duration: int, target_volume: int, source: str):
        self.duration = duration
        self.target_volume = target_volume
        self.source = source

class WateringCycleCompleted(Event):
    def __init__(self, duration_run: int, volume_run: float, source: str, details: str):
        self.duration_run = duration_run
        self.volume_run = volume_run
        self.source = source
        self.details = details

class WateringCycleFailed(Event):
    def __init__(self, duration_run: int, volume_run: float, source: str, details: str):
        self.duration_run = duration_run
        self.volume_run = volume_run
        self.source = source
        self.details = details

class WateringCycleStopped(Event):
    def __init__(self, duration_run: int, volume_run: float, source: str, details: str):
        self.duration_run = duration_run
        self.volume_run = volume_run
        self.source = source
        self.details = details

# --- Deep Core Controller ---

class WateringController:
    """Die softwareseitige Kernkomponente des Daemons zur Steuerung des Kombinierten Gusses."""
    def __init__(self, event_bus: EventBus, mqtt_client_instance: MqttClient):
        self.event_bus = event_bus
        self.mqtt_client = mqtt_client_instance
        
        self._lock = threading.RLock()
        self._active_cycle: Optional[Dict[str, Any]] = None
        self._last_flow_update_time: Optional[datetime] = None
        
        # Registriere Event-Listener
        self.event_bus.subscribe(ValveStatusReported, self._on_valve_status_reported)

    def get_active_volume(self) -> float:
        """Gibt die aktuell geflossene Wassermenge in Litern zurück."""
        with self._lock:
            return round(mqtt_client.active_cycle_volume, 2)

    def get_active_cycle(self) -> Optional[Dict[str, Any]]:
        """Gibt Informationen zum aktuell laufenden Guss zurück."""
        with self._lock:
            if self._active_cycle:
                remaining = max(0, int((self._active_cycle["end_time"] - datetime.now()).total_seconds()))
                return {
                    "source": self._active_cycle["source"],
                    "duration": self._active_cycle["duration"],
                    "target_volume": self._active_cycle["target_volume"],
                    "start_time": self._active_cycle["start_time"].isoformat(),
                    "end_time": self._active_cycle["end_time"].isoformat(),
                    "current_volume": round(mqtt_client.active_cycle_volume, 2),
                    "remaining_seconds": remaining
                }
            return None

    def start_watering(self, duration_minutes: int, target_volume_liters: int, source: str) -> Tuple[bool, str]:
        """Startet eine bewachte Guss-Steuerung (Kombinierter Guss) über eine Threading-Verriegelung."""
        if duration_minutes <= 0:
            return False, "Ungültiges Zeitlimit."
        if duration_minutes > config.SAFETY_TIMEOUT_MINUTES:
            return False, f"Zeitlimit überschreitet das Sicherheitslimit ({config.SAFETY_TIMEOUT_MINUTES} Min)."
        if target_volume_liters < 0:
            return False, "Ungültiges Volumenlimit."

        with self._lock:
            if self._active_cycle is not None:
                return False, "Es läuft bereits eine Bewässerung."

            # Öffne das Ventil über den Mqtt-Infrastruktur-Adapter
            set_topic = f"{config.MQTT_VALVE_TOPIC}/set"
            if not self.mqtt_client.publish(set_topic, '{"state": "ON"}'):
                return False, "Fehler beim Ansteuern des Ventils über MQTT."

            # Software-Timer initialisieren
            duration_seconds = duration_minutes * 60
            timer = threading.Timer(duration_seconds, self._time_limit_callback)
            
            start_time = datetime.now()
            end_time = start_time + timedelta(minutes=duration_minutes)
            
            mqtt_client.active_cycle_volume = 0.0
            self._last_flow_update_time = start_time
            
            self._active_cycle = {
                "start_time": start_time,
                "end_time": end_time,
                "duration": duration_minutes,
                "target_volume": target_volume_liters,
                "source": source,
                "timer": timer
            }
            
            # Starten des Zeitlimits
            timer.start()

        # Feuere Domänen-Event
        self.event_bus.publish(WateringCycleStarted(duration_minutes, target_volume_liters, source))
        logger.info(f"Guss-Steuerung: Guss gestartet ({duration_minutes} Min / {target_volume_liters}l, Quelle: {source}).")
        return True, "Bewässerung gestartet."

    def stop_watering(self) -> Tuple[bool, str]:
        """Stoppt die aktive Bewässerung vorzeitig."""
        with self._lock:
            if self._active_cycle is None:
                # Physisches Schließen zur Sicherheit auslösen
                set_topic = f"{config.MQTT_VALVE_TOPIC}/set"
                self.mqtt_client.publish(set_topic, '{"state": "OFF"}')
                return False, "Kein aktiver Bewässerungszyklus gefunden."

            # Wächter-Timer abbrechen
            self._active_cycle["timer"].cancel()
            
            # Physisches Ventil schließen
            set_topic = f"{config.MQTT_VALVE_TOPIC}/set"
            self.mqtt_client.publish(set_topic, '{"state": "OFF"}')
            
            duration_run = max(1, int((datetime.now() - self._active_cycle["start_time"]).total_seconds() / 60))
            vol_run = round(mqtt_client.active_cycle_volume, 2)
            source = self._active_cycle["source"]
            
            self._active_cycle = None
            self._last_flow_update_time = None

        self.event_bus.publish(WateringCycleStopped(
            duration_run, vol_run, source, f"Manuell vorzeitig gestoppt bei {vol_run} Litern."
        ))
        logger.info(f"Guss-Steuerung: Guss vorzeitig gestoppt bei {vol_run}l.")
        return True, "Bewässerung gestoppt."

    def _integrate_flow(self, flow_rate: float, elapsed_seconds: float):
        """Rechnet den Literzuwachs basierend auf der gemeldeten Durchflussrate hoch."""
        with self._lock:
            if self._active_cycle is None:
                return

            # Zeit-Gap-Capping (max. 60 Sek.)
            calculation_seconds = min(elapsed_seconds, 60.0)
            added_liters = flow_rate * (calculation_seconds / 60.0)
            
            mqtt_client.active_cycle_volume += added_liters
            current_volume = round(mqtt_client.active_cycle_volume, 2)
            target_volume = self._active_cycle["target_volume"]
            
            logger.debug(f"Guss-Steuerung: +{added_liters:.3f}l (Gesamt: {current_volume:.2f}l)")

            # Prüfe Volumenlimit
            if target_volume > 0 and current_volume >= target_volume:
                logger.info(f"Guss-Steuerung: Volumenlimit von {target_volume}l erreicht ({current_volume}l). Schließe Ventil...")
                
                # Timer abbrechen
                self._active_cycle["timer"].cancel()
                
                # Schließe Ventil
                set_topic = f"{config.MQTT_VALVE_TOPIC}/set"
                self.mqtt_client.publish(set_topic, '{"state": "OFF"}')
                
                duration_run = max(1, int((datetime.now() - self._active_cycle["start_time"]).total_seconds() / 60))
                source = self._active_cycle["source"]
                self._active_cycle = None
                self._last_flow_update_time = None
                
                # Feuere Event
                self.event_bus.publish(WateringCycleCompleted(
                    duration_run, current_volume, source, f"Volumenlimit von {target_volume}l erreicht in {duration_run} Min."
                ))

    def _on_valve_status_reported(self, event: ValveStatusReported):
        """Callback beim Empfang eines neuen Ventil-Zustands."""
        now = datetime.now()
        
        is_running = False
        with self._lock:
            if self._active_cycle is not None:
                is_running = True

        if is_running and event.state == "ON" and self._last_flow_update_time is not None:
            elapsed = (now - self._last_flow_update_time).total_seconds()
            if elapsed > 0:
                self._integrate_flow(event.flow_rate, elapsed)

        with self._lock:
            if self._active_cycle is not None:
                if event.state == "ON":
                    self._last_flow_update_time = now
                else:
                    self._last_flow_update_time = None
            else:
                self._last_flow_update_time = None

    def _time_limit_callback(self):
        """Callback für den zeitgesteuerten Notfall-Timer."""
        with self._lock:
            if self._active_cycle is None:
                return

            duration = self._active_cycle["duration"]
            target_vol = self._active_cycle["target_volume"]
            vol_run = round(mqtt_client.active_cycle_volume, 2)
            source = self._active_cycle["source"]
            
            # Schließe physisches Ventil
            set_topic = f"{config.MQTT_VALVE_TOPIC}/set"
            self.mqtt_client.publish(set_topic, '{"state": "OFF"}')
            
            self._active_cycle = None
            self._last_flow_update_time = None

        if target_vol > 0 and vol_run < target_vol:
            # Notfall-Abschaltung (Volumenlimit innerhalb der Zeit nicht erreicht)
            details = f"Notfall-Abschaltung nach {duration} Min: Zielwassermenge von {target_vol}l nicht erreicht ({vol_run}l geflossen)."
            self.event_bus.publish(WateringCycleFailed(duration, vol_run, source, details))
            logger.warning(details)
        else:
            # Planmäßige zeitgesteuerte Beendigung
            details = f"Zeitlimit von {duration} Min erreicht ({vol_run}l geflossen)."
            self.event_bus.publish(WateringCycleCompleted(duration, vol_run, source, details))
            logger.info(details)
