import time
import logging
import threading
from datetime import datetime
from . import config
from .adapters import database, weather
from .core.event_bus import EventBus
from .adapters.mqtt_client import _global_bus
from .core.watering_controller import (
    WateringCycleStarted,
    WateringCycleCompleted,
    WateringCycleFailed,
    WateringCycleStopped
)

logger = logging.getLogger("garden_scheduler")

# Globale Steuerung des Controllers für abwärtskompatible Aufrufe
controller = None

# Steuerung des Scheduler-Hintergrundthreads
scheduler_running = False
scheduler_thread = None

# Callback-Funktion für Telegram-Benachrichtigungen (Abwärtskompatibilität)
notification_callback = None

def register_notification_callback(callback_fn):
    """Registriert einen Callback, um Telegram-Push-Meldungen zu versenden."""
    global notification_callback
    notification_callback = callback_fn

def send_notification(message: str):
    """Hilfsfunktion zum Senden von Push-Meldungen."""
    if notification_callback:
        try:
            notification_callback(message)
        except Exception as e:
            logger.error(f"Fehler beim Senden der Telegram-Benachrichtigung: {e}")

def get_active_cycle():
    """Gibt Details zum aktuell laufenden Bewässerungszyklus zurück (Fassaden-Methode)."""
    global controller
    if controller:
        return controller.get_active_cycle()
    return None

def start_watering(duration_minutes: int, target_volume_liters: int, source: str) -> tuple[bool, str]:
    """Startet die Bewässerung (Fassaden-Methode)."""
    global controller
    if controller:
        return controller.start_watering(duration_minutes, target_volume_liters, source)
    return False, "Domänen-Controller nicht initialisiert."

def stop_watering() -> tuple[bool, str]:
    """Stoppt die aktive Bewässerung sofort (Fassaden-Methode)."""
    global controller
    if controller:
        return controller.stop_watering()
    return False, "Domänen-Controller nicht initialisiert."

def _time_limit_callback():
    """Löst das Zeitlimit manuell über den Controller aus (Abwärtskompatibilität für Tests)."""
    global controller
    if controller:
        controller._time_limit_callback()

# --- Ereignis-Kanäle abfangen zur Abwärtskompatibilität von Push-Nachrichten ---

def _on_event_started(event: WateringCycleStarted):
    msg = (
        f"🟢 **Bewässerung gestartet!**\n"
        f"⏱️ Zeitlimit: {event.duration} Minuten\n"
        f"💧 Volumenlimit: {f'{event.target_volume} Liter' if event.target_volume > 0 else 'Keines'}\n"
        f"⏳ Quelle: {'Zeitplan' if event.source == 'schedule' else 'Manuell'}"
    )
    send_notification(msg)

def _on_event_completed(event: WateringCycleCompleted):
    if "Volumenlimit" in event.details:
        # Extrahiere das Limit aus den Details oder nutze ein Fallback
        target_volume = event.volume_run
        msg = (
            f"🏁 **Wassermenge erreicht!**\n"
            f"💧 Bewässerung nach {int(target_volume)} Litern automatisch beendet.\n"
            f"⏱️ Benötigte Zeit: ca. {event.duration_run} Minute(n)."
        )
    else:
        msg = (
            f"🏁 **Zeitlimit erreicht!**\n"
            f"⏱️ Bewässerung nach {event.duration_run} Minuten planmäßig beendet.\n"
            f"💧 Wassermenge: {event.volume_run} Liter geflossen."
        )
    send_notification(msg)

def _on_event_failed(event: WateringCycleFailed):
    # Extrahiere das target_volume aus den details
    target_vol = 0
    if "Zielwassermenge von" in event.details:
        try:
            parts = event.details.split("Zielwassermenge von ")
            target_vol = int(parts[1].split("l")[0])
        except Exception:
            pass
            
    msg = (
        f"⚠️ **Notfall-Abschaltung ausgelöst!**\n"
        f"⏱️ Abschaltung nach Ablauf von {event.duration_run} Minuten bei geflossenen {event.volume_run} Litern.\n"
        f"💧 Zielwassermenge von {target_vol} Litern wurde nicht erreicht."
    )
    send_notification(msg)

def _on_event_stopped(event: WateringCycleStopped):
    msg = f"🔴 **Bewässerung vorzeitig gestoppt!**\n⏱️ Laufzeit: ca. {event.duration_run} Min\n💧 Geflossene Menge: {event.volume_run} Liter"
    send_notification(msg)

# Registriere die Event-Listener zur Benachrichtigung
_global_bus.subscribe(WateringCycleStarted, _on_event_started)
_global_bus.subscribe(WateringCycleCompleted, _on_event_completed)
_global_bus.subscribe(WateringCycleFailed, _on_event_failed)
_global_bus.subscribe(WateringCycleStopped, _on_event_stopped)

# --- Scheduler-Schleife (Hintergrund-Thread) ---

def _trigger_scheduled_watering(sched: dict):
    """Führt einen Zeitplan aus, inklusive Wetter-Check."""
    duration = sched.get("duration_minutes", 10)
    volume = sched.get("target_volume_liters", 0)
    name = sched.get("name", "Zeitplan")
    
    try:
        # Wetterdaten abfragen und prüfen
        skip, details = weather.should_skip_watering()
    except Exception as e:
        logger.error(f"Fehler beim Wetter-Check für Zeitplan '{name}': {e}. Führe Bewässerung zur Sicherheit trotzdem durch.")
        skip = False
        details = f"Fehler bei Wetterabfrage: {e}"
        
    if skip:
        database.log_watering(duration, "schedule", "skipped", f"Zeitplan '{name}': {details}")
        send_notification(f"🌤️ **Zeitplan '{name}' übersprungen!**\n{details}")
        return
        
    success, msg = start_watering(duration, volume, "schedule")
    if not success:
        database.log_watering(duration, "schedule", "failed", f"Zeitplan '{name}': {msg}")
        send_notification(f"⚠️ **Fehler bei Zeitplan '{name}'!**\n{msg}")

def _scheduler_loop():
    """Hintergrund-Schleife, die jede Minute prüft, ob Zeitpläne anstehen."""
    global scheduler_running
    logger.info("Scheduler-Hintergrund-Schleife gestartet.")
    
    time.sleep(5)
    
    # Einmalige Sicherheits-Schließung beim Systemstart bei offenem Ventil
    if scheduler_running:
        check_startup_safety()
        
    last_weather_update = 0.0
    
    while scheduler_running:
        try:
            now = datetime.now()
            current_time = now.strftime("%H:%M")
            current_weekday = now.strftime("%a")
            
            # Stündliches Wetter-Pre-Polling (Wärmt den lokalen Cache auf)
            current_timestamp = time.time()
            if current_timestamp - last_weather_update >= 3600:
                last_weather_update = current_timestamp
                logger.info("Hintergrund-Wetterabfrage (Cache-Update) ausgelöst...")
                t_weather = threading.Thread(
                    target=weather.get_weather_data, 
                    args=(config.LATITUDE, config.LONGITUDE), 
                    daemon=True
                )
                t_weather.start()
                
            schedules = database.get_schedules()
            for sched in schedules:
                if sched.get("is_active") == 1:
                    sched_time = sched.get("time")
                    if sched_time == current_time:
                        sched_days = sched.get("days", "")
                        days_list = [d.strip() for d in sched_days.split(",")]
                        
                        if "everyday" in days_list or current_weekday in days_list:
                            logger.info(f"Zeitplan '{sched.get('name')}' ({sched_time}) ausgelöst.")
                            t = threading.Thread(target=_trigger_scheduled_watering, args=(sched,), daemon=True)
                            t.start()
                            
        except Exception as e:
            logger.error(f"Fehler im Scheduler-Thread: {e}")
            
        # Nächsten Prüfpunkt berechnen: Schlafe bis zur nächsten vollen Minute
        now = datetime.now()
        seconds_to_sleep = 60 - now.second
        time.sleep(seconds_to_sleep)

def check_startup_safety() -> bool:
    """Prüft beim Systemstart, ob das Ventil unüberwacht offen steht, und schließt es gegebenenfalls."""
    global controller
    from .adapters import mqtt_client
    status = mqtt_client.get_valve_status()
    if status.get("state") == "ON":
        if controller and controller.get_active_cycle() is None:
            logger.warning("Sicherheits-Schließung: Unerwartet geöffnetes Ventil beim Systemstart erkannt!")
            mqtt_client.close_valve()
            send_notification(
                "⚠️ **Unerwartet geöffnetes Ventil beim Systemstart erkannt!**\n"
                "Sicherheits-Schließung durchgeführt."
            )
            return True
    return False

def start_scheduler():
    """Startet den Hintergrund-Scheduler."""
    global scheduler_running, scheduler_thread
    if scheduler_running:
        return
    scheduler_running = True
    scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
    scheduler_thread.start()
    logger.info("Scheduler erfolgreich gestartet.")

def stop_scheduler():
    """Stoppt den Hintergrund-Scheduler."""
    global scheduler_running
    scheduler_running = False
    logger.info("Scheduler gestoppt.")
