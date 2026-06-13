import time
import logging
import threading
from datetime import datetime
from . import config
from .adapters import database, weather
from .adapters.mqtt_client import _global_bus
from .core.scheduler_events import WateringSkipped, ScheduleFailed
from .adapters.daily_report import generate_daily_report, send_daily_report  # noqa: F401 (generate_daily_report re-exported for telegram_ui)

logger = logging.getLogger("garden_scheduler")

# Globale Steuerung des Controllers für abwärtskompatible Aufrufe
controller = None

# Steuerung des Scheduler-Hintergrundthreads
scheduler_running = False
scheduler_thread = None

# Event-basierte Entkopplung der Benachrichtigungen (siehe scheduler_events)

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



# --- Scheduler-Schleife (Hintergrund-Thread) ---

def _trigger_scheduled_watering(sched: dict):
    """Führt einen Zeitplan aus, inklusive Wetter-Check und Multi-Ventil-Unterstützung."""
    duration = sched.get("duration_minutes", 10)
    name = sched.get("name", "Zeitplan")
    execution_mode = sched.get("execution_mode", "sequential")

    try:
        skip, details = weather.should_skip_watering()
    except Exception as e:
        logger.error(f"Fehler beim Wetter-Check für Zeitplan '{name}': {e}. Führe Bewässerung zur Sicherheit trotzdem durch.")
        skip = False
        details = f"Fehler bei Wetterabfrage: {e}"

    if skip:
        database.log_watering(duration, "schedule", "skipped", f"Zeitplan '{name}': {details}")
        _global_bus.publish(WateringSkipped(name, details))
        return

    sched_id = sched.get("id")
    valves = []
    if sched_id:
        for vid in database.get_schedule_valves(sched_id):
            v = database.get_valve_by_id(vid)
            if v is not None:
                valves.append(v)

    if not valves:
        valves = [{"mqtt_name": "garden_valve", "wish_name": "Ventil"}]

    if execution_mode == "parallel":
        for valve in valves:
            _start_single_valve(valve, sched)
    else:
        _start_sequential(list(valves), sched)


def _start_single_valve(valve: dict, sched: dict) -> tuple[bool, str]:
    """Startet einen Guss-Zyklus für ein einzelnes Ventil."""
    global controller
    name = sched.get("name", "Zeitplan")
    duration = sched.get("duration_minutes", 10)
    volume = sched.get("target_volume_liters", 0)
    mqtt_name = valve["mqtt_name"]
    valve_topic = f"zigbee2mqtt/{mqtt_name}"

    if not controller:
        return False, "Domänen-Controller nicht initialisiert."

    success, msg = controller.start_watering(duration, volume, "schedule",
                                             mqtt_name=mqtt_name, valve_topic=valve_topic)
    if not success:
        database.log_watering(duration, "schedule", "failed", f"Zeitplan '{name}' [{mqtt_name}]: {msg}")
        _global_bus.publish(ScheduleFailed(name, msg))
    return success, msg


def _start_sequential(queue: list, sched: dict):
    """Startet Ventile in der Queue nacheinander; trägt sich nach jedem Abschluss erneut ein."""
    if not queue:
        return
    valve = queue.pop(0)
    success, _ = _start_single_valve(valve, sched)
    if success and queue:
        from .core.watering_controller import WateringCycleCompleted, WateringCycleFailed

        def on_cycle_done(event):
            _global_bus.unsubscribe(WateringCycleCompleted, on_cycle_done)
            _global_bus.unsubscribe(WateringCycleFailed, on_cycle_done)
            _start_sequential(queue, sched)

        _global_bus.subscribe(WateringCycleCompleted, on_cycle_done)
        _global_bus.subscribe(WateringCycleFailed, on_cycle_done)

def _scheduler_loop():
    """Hintergrund-Schleife, die jede Minute prüft, ob Zeitpläne anstehen."""
    global scheduler_running
    logger.info("Scheduler-Hintergrund-Schleife gestartet.")
    
    time.sleep(5)
    
    # Einmalige Sicherheits-Schließung beim Systemstart bei offenem Ventil
    if scheduler_running:
        check_startup_safety()
        
    # Delay the first background weather fetch by 60 s so the Pi Zero W's
    # WiFi stack has time to resolve DNS before we hit the network.
    last_weather_update = time.time() - config.WEATHER_REFRESH_INTERVAL_SECONDS + 60
    
    while scheduler_running:
        try:
            now = datetime.now()
            current_time = now.strftime("%H:%M")
            current_weekday = now.strftime("%a")
            today_str = now.strftime("%Y-%m-%d")
            
            # Täglicher Statusbericht um 08:00 Uhr (oder danach falls heute noch ausstehend)
            if current_time >= config.DAILY_REPORT_TIME:
                last_report = database.get_metadata("last_daily_report_date")
                if last_report != today_str:
                    logger.info(f"Täglicher Statusbericht für heute ({today_str}) steht aus. Starte Versand...")
                    t_report = threading.Thread(target=send_daily_report, args=(today_str,), daemon=True)
                    t_report.start()
            
            # Stündliches Wetter-Pre-Polling (Wärmt den lokalen Cache auf)
            current_timestamp = time.time()
            if current_timestamp - last_weather_update >= config.WEATHER_REFRESH_INTERVAL_SECONDS:
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
            _global_bus.publish(ScheduleFailed("Systemstart", "Unerwartet geöffnetes Ventil erkannt. Sicherheits-Schließung durchgeführt."))
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
