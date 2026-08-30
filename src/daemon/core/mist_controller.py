import logging
import threading
from datetime import datetime
from typing import Any, Callable, Dict, Tuple

from .event_bus import EventBus
from .mist_events import MistIntervalStarted, MistIntervalEnded

logger = logging.getLogger("garden_nebel_controller")

__all__ = ["MistController", "MistIntervalStarted", "MistIntervalEnded"]


class MistController:
    """Die Nebel-Steuerung: fährt den ON/Pause-Burst-Zyklus eines Nebel-Intervalls.

    Pendant zur Guss-Steuerung, aber fürs Kühlen statt fürs Bewässern. Eigener
    threading.Timer-Loop für sekundengenaues Timing; Ventil-Ansteuerung ausschließlich
    über die injizierte publish_fn (ADR 0017). Keine Volumen-, Flow- oder Regenlogik.

    Solange ein Ventil bedient wird, „beansprucht" die Nebel-Steuerung es über claim_fn,
    damit die Guss-Steuerung die regulären Nebelstöße nicht als Unerwartete Ventilöffnung
    (ADR 0032) fehldeutet. release_fn gibt das Ventil am Fensterende wieder frei.
    """

    def __init__(self, event_bus: EventBus, publish_fn: Callable[[str, str], bool],
                 claim_fn: Callable[[str], None] = None, release_fn: Callable[[str], None] = None):
        self.event_bus = event_bus
        self.publish_fn = publish_fn
        self._claim_fn = claim_fn
        self._release_fn = release_fn

        self._lock = threading.RLock()
        # Indiziert nach mqtt_name; ein aktives Nebel-Fenster pro Ventil.
        self._cycles: Dict[str, Dict[str, Any]] = {}
        # Restart-Unterdrückung (C1, in-memory): manuell gestoppte Fenster bleiben bis
        # zu ihrer Endzeit gegen den Scheduler-Neustart gesperrt. Läuft lazy ab.
        self._suppressed_until: Dict[str, datetime] = {}

    # --- Öffentliche API ---

    def start(self, mqtt_name: str, on_seconds: int, pause_minutes: int,
              end_time: datetime, source: str, valve_topic: str = None) -> Tuple[bool, str]:
        """Startet ein Nebel-Fenster für ein Ventil. Idempotent: läuft bereits eines → no-op.

        Das idempotente Verhalten erlaubt dem Scheduler, ein Fenster zustandslos je Minute
        anzustoßen, ohne einen zweiten Lauf zu erzeugen.
        """
        if valve_topic is None:
            valve_topic = f"zigbee2mqtt/{mqtt_name}"

        with self._lock:
            if mqtt_name in self._cycles:
                return False, "Es läuft bereits ein Nebel-Intervall."

            # Expliziter Neustart hebt eine bestehende Sperre auf (Neustart gewinnt).
            self._suppressed_until.pop(mqtt_name, None)

            self._cycles[mqtt_name] = {
                "on_seconds": on_seconds,
                "pause_minutes": pause_minutes,
                "end_time": end_time,
                "source": source,
                "valve_topic": valve_topic,
                "start_time": datetime.now(),
                "burst_count": 0,
                "timer": None,
            }
            if self._claim_fn:
                self._claim_fn(mqtt_name)

        self.event_bus.publish(MistIntervalStarted(mqtt_name, source, end_time.isoformat()))
        logger.info(f"Nebel-Steuerung: Nebel-Intervall gestartet für '{mqtt_name}' "
                    f"({on_seconds}s an / {pause_minutes}min Pause, bis {end_time.strftime('%H:%M')}, Quelle: {source}).")
        self._begin_burst(mqtt_name)
        return True, "Nebel-Intervall gestartet."

    def stop(self, mqtt_name: str = None) -> Tuple[bool, str]:
        """Beendet ein oder alle aktiven Nebel-Fenster. Ohne mqtt_name: alle."""
        with self._lock:
            targets = [mqtt_name] if (mqtt_name and mqtt_name in self._cycles) else list(self._cycles.keys())
            if not targets:
                return False, "Kein aktives Nebel-Intervall."
            # Endzeit jedes Fensters merken, bevor _finish es entfernt — so bleibt ein
            # geplantes Fenster bis zu seinem regulären Ende gegen Neustart gesperrt.
            for name in targets:
                self._suppressed_until[name] = self._cycles[name]["end_time"]

        for name in targets:
            self._finish(name, "Manuell gestoppt")
        return True, f"Nebel-Intervall gestoppt ({', '.join(targets)})."

    def is_active(self, mqtt_name: str = None) -> bool:
        with self._lock:
            if mqtt_name:
                return mqtt_name in self._cycles
            return bool(self._cycles)

    def get_active_window(self, mqtt_name: str = None) -> str:
        """Gibt das mqtt_name eines laufenden Nebel-Fensters zurück (fürs Stopp-Menü), sonst None."""
        with self._lock:
            if mqtt_name:
                return mqtt_name if mqtt_name in self._cycles else None
            return next(iter(self._cycles.keys()), None)

    def is_suppressed(self, mqtt_name: str) -> bool:
        """Wahr, solange ein manuell gestopptes Fenster gegen Neustart gesperrt ist (läuft lazy ab)."""
        with self._lock:
            until = self._suppressed_until.get(mqtt_name)
            if until is None:
                return False
            if datetime.now() >= until:
                self._suppressed_until.pop(mqtt_name, None)
                return False
            return True

    # --- Burst-Loop (Transitions) ---

    def _begin_burst(self, mqtt_name: str):
        """Öffnet das Ventil für einen Nebelstoß und armt den Stoß-Ende-Timer."""
        with self._lock:
            cycle = self._cycles.get(mqtt_name)
            if cycle is None:
                return
            if datetime.now() >= cycle["end_time"]:
                finish = True
            else:
                finish = False
                if not self.publish_fn(f"{cycle['valve_topic']}/set", '{"state": "ON"}'):
                    logger.warning(f"Nebel-Steuerung [{mqtt_name}]: Ventil-Ansteuerung (ON) "
                                   f"fehlgeschlagen — nächster Nebelstoß versucht es erneut.")
                cycle["burst_count"] += 1
                timer = threading.Timer(cycle["on_seconds"], self._end_burst, args=(mqtt_name,))
                timer.daemon = True
                cycle["timer"] = timer
                timer.start()
        if finish:
            self._finish(mqtt_name, "Fensterende erreicht")

    def _end_burst(self, mqtt_name: str):
        """Schließt das Ventil nach einem Nebelstoß und armt den Pausen-Timer (oder beendet)."""
        with self._lock:
            cycle = self._cycles.get(mqtt_name)
            if cycle is None:
                return
            self.publish_fn(f"{cycle['valve_topic']}/set", '{"state": "OFF"}')
            if datetime.now() >= cycle["end_time"]:
                finish = True
            else:
                finish = False
                timer = threading.Timer(cycle["pause_minutes"] * 60, self._begin_burst, args=(mqtt_name,))
                timer.daemon = True
                cycle["timer"] = timer
                timer.start()
        if finish:
            self._finish(mqtt_name, "Fensterende erreicht")

    def _finish(self, mqtt_name: str, reason: str):
        """Beendet das Nebel-Fenster sicher: Timer aus, Ventil zu, Ventil freigeben, Ereignis."""
        with self._lock:
            cycle = self._cycles.pop(mqtt_name, None)
            if cycle is None:
                return
            if cycle.get("timer"):
                cycle["timer"].cancel()
            self.publish_fn(f"{cycle['valve_topic']}/set", '{"state": "OFF"}')
            duration_run = max(1, int((datetime.now() - cycle["start_time"]).total_seconds() / 60))
            burst_count = cycle["burst_count"]
            source = cycle["source"]
            if self._release_fn:
                self._release_fn(mqtt_name)

        details = f"{reason}: {burst_count} Nebelstöße in {duration_run} Min."
        self.event_bus.publish(MistIntervalEnded(mqtt_name, source, duration_run, burst_count, details))
        logger.info(f"Nebel-Steuerung: '{mqtt_name}' beendet ({reason}, {burst_count} Stöße).")
