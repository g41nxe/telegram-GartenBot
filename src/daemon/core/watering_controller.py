import logging
import threading
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional, Tuple
from .event_bus import Event, EventBus
from .valve_events import ValveStatusReported
from .. import config

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

    def __init__(self, event_bus: EventBus, publish_fn: Callable[[str, str], bool]):
        self.event_bus = event_bus
        self.publish_fn = publish_fn

        self._lock = threading.RLock()
        # Indiziert nach mqtt_name; unterstützt mehrere parallele Zyklen
        self._active_cycles: Dict[str, Dict[str, Any]] = {}
        self._last_flow_update_time: Dict[str, Optional[datetime]] = {}

        self.event_bus.subscribe(ValveStatusReported, self._on_valve_status_reported)

    def get_active_volume(self, mqtt_name: str = None) -> float:
        """Gibt die aktuell geflossene Wassermenge zurück. Ohne mqtt_name: erstes aktives Ventil."""
        with self._lock:
            cycle = self._active_cycles.get(mqtt_name) if mqtt_name else next(iter(self._active_cycles.values()), None)
            return round(cycle.get("current_volume", 0.0), 2) if cycle else 0.0

    def get_active_cycle(self, mqtt_name: str = None) -> Optional[Dict[str, Any]]:
        """Gibt Informationen zum laufenden Zyklus zurück. Ohne mqtt_name: erstes aktives Ventil."""
        with self._lock:
            cycle = self._active_cycles.get(mqtt_name) if mqtt_name else next(iter(self._active_cycles.values()), None)
            if cycle:
                remaining = max(0, int((cycle["end_time"] - datetime.now()).total_seconds()))
                return {
                    "source": cycle["source"],
                    "duration": cycle["duration"],
                    "target_volume": cycle["target_volume"],
                    "start_time": cycle["start_time"].isoformat(),
                    "end_time": cycle["end_time"].isoformat(),
                    "current_volume": round(cycle.get("current_volume", 0.0), 2),
                    "remaining_seconds": remaining
                }
            return None

    def start_watering(self, duration_minutes: int, target_volume_liters: int, source: str,
                       mqtt_name: str = "garden_valve", valve_topic: str = None) -> Tuple[bool, str]:
        """Startet einen bewachten Guss für ein bestimmtes Ventil."""
        if valve_topic is None:
            valve_topic = f"zigbee2mqtt/{mqtt_name}"

        if duration_minutes <= 0:
            return False, "Ungültiges Zeitlimit."
        if duration_minutes > config.SAFETY_TIMEOUT_MINUTES:
            return False, f"Zeitlimit überschreitet das Sicherheitslimit ({config.SAFETY_TIMEOUT_MINUTES} Min)."
        if target_volume_liters < 0:
            return False, "Ungültiges Volumenlimit."

        with self._lock:
            if mqtt_name in self._active_cycles:
                return False, "Es läuft bereits eine Bewässerung."

            if not self.publish_fn(f"{valve_topic}/set", '{"state": "ON"}'):
                return False, "Fehler beim Ansteuern des Ventils über MQTT."

            duration_seconds = duration_minutes * 60
            timer = threading.Timer(duration_seconds, self._time_limit_callback, args=(mqtt_name, valve_topic))
            timer.daemon = True

            start_time = datetime.now()
            self._last_flow_update_time[mqtt_name] = start_time
            self._active_cycles[mqtt_name] = {
                "start_time": start_time,
                "end_time": start_time + timedelta(minutes=duration_minutes),
                "duration": duration_minutes,
                "target_volume": target_volume_liters,
                "current_volume": 0.0,
                "source": source,
                "timer": timer,
                "valve_topic": valve_topic,
            }
            timer.start()

        self.event_bus.publish(WateringCycleStarted(duration_minutes, target_volume_liters, source))
        logger.info(f"Guss-Steuerung: Guss gestartet für '{mqtt_name}' ({duration_minutes} Min / {target_volume_liters}l, Quelle: {source}).")
        return True, "Bewässerung gestartet."

    def stop_watering(self, mqtt_name: str = None) -> Tuple[bool, str]:
        """Stoppt einen oder alle aktiven Zyklen. Ohne mqtt_name: alle stoppen."""
        with self._lock:
            targets = [mqtt_name] if (mqtt_name and mqtt_name in self._active_cycles) else list(self._active_cycles.keys())

            if not targets:
                # Fallback: Standard-Ventil physisch schließen
                self.publish_fn(f"{config.MQTT_VALVE_TOPIC}/set", '{"state": "OFF"}')
                return False, "Kein aktiver Bewässerungszyklus gefunden."

            stopped = []
            for name in targets:
                cycle = self._active_cycles.pop(name)
                cycle["timer"].cancel()
                valve_topic = cycle.get("valve_topic", f"zigbee2mqtt/{name}")
                self.publish_fn(f"{valve_topic}/set", '{"state": "OFF"}')
                duration_run = max(1, int((datetime.now() - cycle["start_time"]).total_seconds() / 60))
                vol_run = round(cycle.get("current_volume", 0.0), 2)
                source = cycle["source"]
                self._last_flow_update_time.pop(name, None)
                self.event_bus.publish(WateringCycleStopped(
                    duration_run, vol_run, source, f"Manuell vorzeitig gestoppt bei {vol_run} Litern."
                ))
                logger.info(f"Guss-Steuerung: '{name}' gestoppt bei {vol_run}l.")
                stopped.append(name)

        return True, f"Bewässerung gestoppt ({', '.join(stopped)})."

    def _integrate_flow(self, flow_rate: float, elapsed_seconds: float, mqtt_name: str = "garden_valve"):
        """Integriert den Durchfluss für ein bestimmtes Ventil."""
        with self._lock:
            if mqtt_name not in self._active_cycles:
                return

            cycle = self._active_cycles[mqtt_name]
            calculation_seconds = min(elapsed_seconds, float(config.FLOW_TIME_GAP_CAP_SECONDS))
            added_liters = flow_rate * (calculation_seconds / 60.0)
            cycle["current_volume"] = cycle.get("current_volume", 0.0) + added_liters
            current_volume = round(cycle["current_volume"], 2)
            target_volume = cycle["target_volume"]

            logger.debug(f"Guss-Steuerung [{mqtt_name}]: +{added_liters:.3f}l (Gesamt: {current_volume:.2f}l)")

            if target_volume > 0 and current_volume >= target_volume:
                logger.info(f"Guss-Steuerung [{mqtt_name}]: Volumenlimit von {target_volume}l erreicht. Schließe Ventil...")
                cycle["timer"].cancel()
                valve_topic = cycle.get("valve_topic", f"zigbee2mqtt/{mqtt_name}")
                self.publish_fn(f"{valve_topic}/set", '{"state": "OFF"}')
                duration_run = max(1, int((datetime.now() - cycle["start_time"]).total_seconds() / 60))
                source = cycle["source"]
                del self._active_cycles[mqtt_name]
                self._last_flow_update_time.pop(mqtt_name, None)
                self.event_bus.publish(WateringCycleCompleted(
                    duration_run, current_volume, source,
                    f"Volumenlimit von {target_volume}l erreicht in {duration_run} Min."
                ))

    def _on_valve_status_reported(self, event: ValveStatusReported):
        """Callback beim Empfang eines neuen Ventil-Zustands — filtert nach mqtt_name."""
        mqtt_name = event.mqtt_name
        now = datetime.now()

        with self._lock:
            if mqtt_name not in self._active_cycles:
                return
            last_update = self._last_flow_update_time.get(mqtt_name)

        if event.state == "ON" and last_update is not None:
            elapsed = (now - last_update).total_seconds()
            if elapsed > 0:
                self._integrate_flow(event.flow_rate, elapsed, mqtt_name)

        with self._lock:
            if mqtt_name in self._active_cycles:
                self._last_flow_update_time[mqtt_name] = now if event.state == "ON" else None
            else:
                self._last_flow_update_time.pop(mqtt_name, None)

    def _time_limit_callback(self, mqtt_name: str = "garden_valve", valve_topic: str = None):
        """Callback für den zeitgesteuerten Notfall-Timer."""
        with self._lock:
            if mqtt_name not in self._active_cycles:
                return

            cycle = self._active_cycles[mqtt_name]
            duration = cycle["duration"]
            target_vol = cycle["target_volume"]
            vol_run = round(cycle.get("current_volume", 0.0), 2)
            source = cycle["source"]
            actual_topic = valve_topic or cycle.get("valve_topic", f"zigbee2mqtt/{mqtt_name}")

            self.publish_fn(f"{actual_topic}/set", '{"state": "OFF"}')
            del self._active_cycles[mqtt_name]
            self._last_flow_update_time.pop(mqtt_name, None)

        if target_vol > 0 and vol_run < target_vol:
            details = f"Notfall-Abschaltung nach {duration} Min: Zielwassermenge von {target_vol}l nicht erreicht ({vol_run}l geflossen)."
            self.event_bus.publish(WateringCycleFailed(duration, vol_run, source, details))
            logger.warning(details)
        else:
            details = f"Zeitlimit von {duration} Min erreicht ({vol_run}l geflossen)."
            self.event_bus.publish(WateringCycleCompleted(duration, vol_run, source, details))
            logger.info(details)
