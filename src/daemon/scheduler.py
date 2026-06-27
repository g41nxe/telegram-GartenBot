import time
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from . import config
from .adapters import database, weather, watchdog, mqtt_client
from .adapters.mqtt_client import _global_bus
from .core.scheduler_events import WateringSkipped, ScheduleFailed, WateringScaled
from .core.watering_advice import plan_scheduled_run
from .adapters.daily_report import send_daily_report

logger = logging.getLogger("garden_scheduler")

_controller = None
_nebel_controller = None

# Steuerung des Scheduler-Hintergrundthreads
scheduler_running = False
scheduler_thread = None

# Event-basierte Entkopplung der Benachrichtigungen (siehe scheduler_events)

def set_controller(ctrl) -> None:
    """Verdrahtet die Guss-Steuerung. Einmalig von main.py beim Daemon-Start aufrufen."""
    global _controller
    _controller = ctrl


def set_nebel_controller(ctrl) -> None:
    """Verdrahtet die Nebel-Steuerung (Feature 0032). Von main.py beim Daemon-Start aufrufen."""
    global _nebel_controller
    _nebel_controller = ctrl


def _ensure_nebel_window(sched: dict, now: datetime) -> None:
    """Stellt zustandslos sicher, dass ein Nebel-Intervall läuft, wenn `now` im Fenster liegt.

    Wird je Minute aufgerufen. Liegt die Zeit im Fenster [time, end_time) und läuft für das
    Ventil noch kein Nebel-Intervall, wird die Nebel-Steuerung gestartet. So nimmt ein Fenster
    nach einem Daemon-Neustart von selbst wieder auf. Kein Wetter-Check, keine Skalierung.
    """
    if _nebel_controller is None:
        return
    start = sched.get("time")
    end = sched.get("end_time")
    if not start or not end:
        return
    current = now.strftime("%H:%M")
    if not (start <= current < end):
        return

    on_seconds = sched.get("on_seconds") or config.NEBEL_ON_SECONDS
    pause_minutes = sched.get("pause_minutes") or config.NEBEL_PAUSE_MINUTES
    try:
        end_dt = datetime.combine(now.date(), datetime.strptime(end, "%H:%M").time())
    except ValueError:
        logger.error(f"Nebel-Zeitplan '{sched.get('name')}': ungültige Endzeit '{end}'.")
        return

    sched_id = sched.get("id")
    valve_ids = database.get_schedule_valves(sched_id) if sched_id else []
    for vid in valve_ids:
        valve = database.get_valve_by_id(vid)
        if valve is None:
            continue
        mqtt_name = valve["mqtt_name"]
        if not _nebel_controller.is_active(mqtt_name):
            _nebel_controller.start(mqtt_name, on_seconds, pause_minutes, end_dt, "nebel",
                                    valve_topic=f"zigbee2mqtt/{mqtt_name}")



# --- Scheduler-Schleife (Hintergrund-Thread) ---

def _trigger_scheduled_watering(sched: dict):
    """Führt einen Zeitplan aus, inklusive Wetter-Check und Multi-Ventil-Unterstützung."""
    duration = sched.get("duration_minutes", 10)
    volume = sched.get("target_volume_liters", 0) or 0
    name = sched.get("name", "Zeitplan")
    execution_mode = sched.get("execution_mode", "sequential")

    try:
        decision = weather.evaluate_watering_factor()
    except Exception as e:
        logger.error(f"Fehler beim Wetter-Check für Zeitplan '{name}': {e}. Führe Bewässerung trotzdem durch.")
        decision = None

    plan = plan_scheduled_run(duration, volume, decision)

    if plan.skip:
        database.log_watering(duration, "schedule", "skipped", f"Zeitplan '{name}': {plan.skip_reason}")
        _global_bus.publish(WateringSkipped(name, plan.skip_reason))
        return

    # Skalierter Guss: Zeitplan-Kopie mit reduzierten Werten erstellen
    if plan.scaled:
        _global_bus.publish(WateringScaled(
            schedule_name=name,
            factor=plan.factor,
            duration_original=plan.duration_original,
            duration_scaled=plan.duration,
            volume_original=plan.volume_original,
            volume_scaled=plan.volume,
            reasons=list(plan.reasons),
        ))
        scaled_sched = dict(sched)
        scaled_sched["duration_minutes"] = plan.duration
        scaled_sched["target_volume_liters"] = plan.volume
        sched = scaled_sched  # sched-Referenz ab hier auf skalierten Zeitplan

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
    global _controller
    name = sched.get("name", "Zeitplan")
    duration = sched.get("duration_minutes", 10)
    volume = sched.get("target_volume_liters", 0)
    mqtt_name = valve["mqtt_name"]
    valve_topic = f"zigbee2mqtt/{mqtt_name}"

    if not _controller:
        return False, "Domänen-Controller nicht initialisiert."

    success, msg = _controller.start_watering(duration, volume, "schedule",
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

def _send_daily_report_with_prefetch(today_str: str):
    """Fordert frische Ventil-Status an, wartet und delegiert an send_daily_report().

    Ist der Thread-Target für den täglichen Bericht. Die Wartezeit liegt hier,
    weil der Scheduler die Zeitsteuerung verantwortet — nicht der Report-Adapter.
    """
    try:
        mqtt_client.request_valve_status()
    except Exception as e:
        logger.warning(f"Konnte Ventil-Statusaktualisierung nicht anfordern: {e}")
    time.sleep(5.0)
    send_daily_report(today_str)

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
    last_watchdog_check = 0.0

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
                    t_report = threading.Thread(target=_send_daily_report_with_prefetch, args=(today_str,), daemon=True)
                    t_report.start()

            # Tägliches Cleanup der Kamera-Fotos (>= 03:00 Uhr, analog zum Tagesbericht)
            if current_time >= "03:00":
                last_cleanup = database.get_metadata("last_camera_cleanup_date")
                if last_cleanup != today_str:
                    logger.info("Starte tägliches Kamera-Cleanup...")
                    database.set_metadata("last_camera_cleanup_date", today_str)
                    t_cleanup = threading.Thread(target=_cleanup_camera_photos_safe, daemon=True)
                    t_cleanup.start()
            
            # Stündliche Hintergrundprüfungen
            current_timestamp = time.time()

            if current_timestamp - last_watchdog_check >= 3600:
                last_watchdog_check = current_timestamp
                t_watchdog = threading.Thread(target=watchdog.run_watchdog_check, daemon=True)
                t_watchdog.start()

            # Stündliches Wetter-Pre-Polling (Wärmt den lokalen Cache auf)
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
                if sched.get("is_active") != 1:
                    continue

                sched_days = sched.get("days", "")
                days_list = [d.strip() for d in sched_days.split(",")]
                if not ("everyday" in days_list or current_weekday in days_list):
                    continue

                if sched.get("mode") == "nebel":
                    # Nebel-Intervall: fenster-basiert, zustandslos je Minute prüfen.
                    _ensure_nebel_window(sched, now)
                    continue

                sched_time = sched.get("time")
                if sched_time == current_time:
                    logger.info(f"Zeitplan '{sched.get('name')}' ({sched_time}) ausgelöst.")
                    t = threading.Thread(target=_trigger_scheduled_watering, args=(sched,), daemon=True)
                    t.start()
                            
        except Exception as e:
            logger.error(f"Fehler im Scheduler-Thread: {e}")
            
        # Nächsten Prüfpunkt berechnen: Schlafe bis zur nächsten vollen Minute
        now = datetime.now()
        seconds_to_sleep = 60 - now.second
        time.sleep(seconds_to_sleep)

def _cleanup_camera_photos_safe():
    """Thread-Target: ruft cleanup_camera_photos() auf und fängt alle Ausnahmen ab."""
    try:
        cleanup_camera_photos()
    except Exception as e:
        logger.error(f"Unbehandelter Fehler im Kamera-Cleanup: {e}")


def cleanup_camera_photos():
    """Löscht alte Kamera-Fotos und behält ein Zeitraffer-Bild pro Tag (>= 12:00)."""
    base_dir = Path(config.CAMERA_IMAGE_DIR)
    if not base_dir.exists():
        return
        
    cutoff_date = datetime.now() - timedelta(days=config.CAMERA_CLEANUP_DAYS)
    
    for cam_dir in base_dir.iterdir():
        if not cam_dir.is_dir():
            continue
            
        photos_by_day = {}
        for file_path in cam_dir.glob("photo_*.jpg"):
            name_parts = file_path.stem.split('_')
            if len(name_parts) != 3:
                continue
                
            try:
                date_str = name_parts[1]
                time_str = name_parts[2]
                photo_dt = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
            except ValueError:
                continue
                
            day_str = date_str
            if day_str not in photos_by_day:
                photos_by_day[day_str] = []
            photos_by_day[day_str].append((photo_dt, file_path))
            
        for day_str, photos in photos_by_day.items():
            photos.sort(key=lambda x: x[0])
            
            timelapse_photo = None
            for p_dt, p_path in photos:
                if p_dt.hour >= 12:
                    timelapse_photo = p_path
                    break
                    
            for p_dt, p_path in photos:
                if p_dt < cutoff_date and p_path != timelapse_photo:
                    try:
                        p_path.unlink()
                        logger.debug(f"Cleanup: Gelöscht {p_path.name}")
                    except Exception as e:
                        logger.error(f"Fehler beim Löschen von {p_path}: {e}")

def count_camera_history(wish_name: str) -> int:
    """Zählt die Historienbilder (photo_*.jpg) einer Garten-Kamera, ohne zu löschen.

    Ein fehlendes Kamera-Verzeichnis liefert 0.
    """
    cam_dir = Path(config.CAMERA_IMAGE_DIR) / wish_name
    if not cam_dir.exists():
        return 0
    return sum(1 for _ in cam_dir.glob("photo_*.jpg"))


def clear_camera_history(wish_name: str) -> int:
    """Löscht alle Historienbilder (photo_*.jpg) einer Garten-Kamera und gibt deren Anzahl zurück.

    Geschwister-Funktion zum automatischen Cleanup. Die Momentaufnahme latest.jpg
    bleibt bewusst erhalten, damit die Sofort-Anzeige (/photo) weiter funktioniert.
    Ein fehlendes Kamera-Verzeichnis liefert 0 ohne Fehler.
    """
    cam_dir = Path(config.CAMERA_IMAGE_DIR) / wish_name
    if not cam_dir.exists():
        return 0

    deleted = 0
    for file_path in cam_dir.glob("photo_*.jpg"):
        try:
            file_path.unlink()
            deleted += 1
        except Exception as e:
            logger.error(f"Fehler beim Löschen von {file_path}: {e}")
    return deleted


def check_startup_safety() -> bool:
    """Prüft beim Systemstart, ob das Ventil unüberwacht offen steht, und schließt es gegebenenfalls."""
    global _controller
    from .adapters import mqtt_client
    status = mqtt_client.get_valve_status()
    if status.get("state") == "ON":
        if _controller and _controller.get_active_cycle() is None:
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
