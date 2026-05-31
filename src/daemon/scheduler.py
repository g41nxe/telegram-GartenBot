import time
import logging
import threading
from datetime import datetime, timedelta
from . import database, weather, mqtt_client, config

logger = logging.getLogger("garden_scheduler")

# Globale Variablen zur Überwachung des aktiven Bewässerungszyklus
active_cycle_lock = threading.Lock()
active_cycle = None  
# Struktur: {
#   "start_time": datetime, 
#   "end_time": datetime, 
#   "duration": int, 
#   "target_volume": int,
#   "source": str, 
#   "timer": threading.Timer,
#   "volume_check_running": bool
# }

# Steuerung des Scheduler-Hintergrundthreads
scheduler_running = False
scheduler_thread = None

# Callback-Funktion für Telegram-Benachrichtigungen
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
    """Gibt Details zum aktuell laufenden Bewässerungszyklus zurück."""
    with active_cycle_lock:
        if active_cycle:
            return {
                "source": active_cycle["source"],
                "duration": active_cycle["duration"],
                "target_volume": active_cycle["target_volume"],
                "start_time": active_cycle["start_time"].isoformat(),
                "end_time": active_cycle["end_time"].isoformat(),
                "current_volume": mqtt_client.get_active_volume(),
                "remaining_seconds": max(0, int((active_cycle["end_time"] - datetime.now()).total_seconds()))
            }
        return None

def start_watering(duration_minutes: int, target_volume_liters: int, source: str) -> tuple[bool, str]:
    """
    Startet die Bewässerung mit kombiniertem Zeit- und Volumen-Limit.
    Sichert über Locks ab, dass nicht zwei Zyklen gleichzeitig laufen können.
    """
    global active_cycle
    
    # Sicherheitsprüfung der Dauer
    if duration_minutes <= 0:
        return False, "Ungültiges Zeitlimit."
    if duration_minutes > config.SAFETY_TIMEOUT_MINUTES:
        return False, f"Zeitlimit überschreitet das Sicherheitslimit ({config.SAFETY_TIMEOUT_MINUTES} Min)."
    if target_volume_liters < 0:
        return False, "Ungültiges Volumenlimit."

    with active_cycle_lock:
        if active_cycle is not None:
            return False, "Es läuft bereits eine Bewässerung."
            
        # MQTT-Befehl zum Öffnen des Ventils
        if not mqtt_client.open_valve():
            return False, "Fehler beim Ansteuern des Ventils über MQTT."
            
        # 1. Zeit-Wächter (threading.Timer) initialisieren
        duration_seconds = duration_minutes * 60
        timer = threading.Timer(duration_seconds, _time_limit_callback)
        
        start_time = datetime.now()
        end_time = start_time + timedelta(minutes=duration_minutes)
        
        active_cycle = {
            "start_time": start_time,
            "end_time": end_time,
            "duration": duration_minutes,
            "target_volume": target_volume_liters,
            "source": source,
            "timer": timer,
            "volume_check_running": False
        }
        
        # 2. Volumen-Wächter starten (falls Volumenlimit > 0)
        if target_volume_liters > 0:
            active_cycle["volume_check_running"] = True
            volume_thread = threading.Thread(
                target=_volume_check_loop, 
                args=(target_volume_liters,), 
                daemon=True
            )
            volume_thread.start()
            
        # Starten des Zeit-Timers
        timer.start()
        
    # In DB protokollieren
    limit_info = f"Zeitlimit: {duration_minutes} Min"
    if target_volume_liters > 0:
        limit_info += f" | Volumenlimit: {target_volume_liters} Liter"
        
    database.log_watering(duration_minutes, source, "completed", f"Bewässerung gestartet ({limit_info}).")
    
    msg = (
        f"🟢 **Bewässerung gestartet!**\n"
        f"⏱️ Zeitlimit: {duration_minutes} Minuten\n"
        f"💧 Volumenlimit: {f'{target_volume_liters} Liter' if target_volume_liters > 0 else 'Keines'}\n"
        f"⏳ Quelle: {'Zeitplan' if source == 'schedule' else 'Manuell'}"
    )
    send_notification(msg)
    
    logger.info(f"Kombinierter Guss gestartet ({duration_minutes} Min / {target_volume_liters}l, Quelle: {source}).")
    return True, "Bewässerung gestartet."

def stop_watering() -> tuple[bool, str]:
    """Stoppt die aktive Bewässerung sofort manuell."""
    global active_cycle
    
    with active_cycle_lock:
        if active_cycle is None:
            mqtt_client.close_valve()
            return False, "Kein aktiver Bewässerungszyklus gefunden."
            
        # Limits und Wächter abbrechen
        active_cycle["timer"].cancel()
        active_cycle["volume_check_running"] = False
        
        # Ventil schließen
        mqtt_client.close_valve()
        
        duration_run = max(1, int((datetime.now() - active_cycle["start_time"]).total_seconds() / 60))
        vol_run = mqtt_client.get_active_volume()
        source = active_cycle["source"]
        
        active_cycle = None
        
    database.log_watering(duration_run, source, "stopped", f"Manuell vorzeitig gestoppt bei {vol_run} Litern.")
    
    msg = f"🔴 **Bewässerung vorzeitig gestoppt!**\n⏱️ Laufzeit: ca. {duration_run} Min\n💧 Geflossene Menge: {vol_run} Liter"
    send_notification(msg)
    
    logger.info("Bewässerungszyklus manuell abgebrochen.")
    return True, "Bewässerung gestoppt."

# --- Wächter Callbacks ---

def _time_limit_callback():
    """Callback für den Zeit-Wächter: Ausgelöst, wenn das Zeitlimit abläuft."""
    global active_cycle
    logger.info("Zeitlimit erreicht. Schließe Ventil...")
    
    with active_cycle_lock:
        if active_cycle is None:
            return
            
        # Volumen-Wächter stoppen
        active_cycle["volume_check_running"] = False
        
        # Ventil schließen
        mqtt_client.close_valve()
        duration = active_cycle["duration"]
        vol_run = mqtt_client.get_active_volume()
        source = active_cycle["source"]
        
        active_cycle = None
        
    database.log_watering(duration, source, "completed", f"Zeitlimit von {duration} Min erreicht ({vol_run}l geflossen).")
    
    msg = (
        f"🏁 **Zeitlimit erreicht!**\n"
        f"⏱️ Bewässerung nach {duration} Minuten planmäßig beendet.\n"
        f"💧 Wassermenge: {vol_run} Liter geflossen."
    )
    send_notification(msg)
    logger.info("Bewässerungslauf über Zeitlimit beendet.")

def _volume_check_loop(target_volume: int):
    """Hintergrund-Wächter für die Wassermenge (Volumenlimit)."""
    global active_cycle
    logger.info(f"Volumen-Wächter für {target_volume} Liter gestartet.")
    
    while True:
        # Prüfen, ob der Loop abgebrochen werden soll
        with active_cycle_lock:
            if active_cycle is None or not active_cycle.get("volume_check_running", False):
                break
                
        current_volume = mqtt_client.get_active_volume()
        if current_volume >= target_volume:
            logger.info(f"Volumenlimit von {target_volume}l erreicht ({current_volume}l). Schließe Ventil...")
            
            with active_cycle_lock:
                if active_cycle is None:
                    break
                
                # Zeit-Wächter-Timer abbrechen
                active_cycle["timer"].cancel()
                active_cycle["volume_check_running"] = False
                
                # Ventil schließen
                mqtt_client.close_valve()
                
                start_time = active_cycle["start_time"]
                duration_run = max(1, int((datetime.now() - start_time).total_seconds() / 60))
                source = active_cycle["source"]
                
                active_cycle = None
                
            database.log_watering(duration_run, source, "completed", f"Volumenlimit von {target_volume}l erreicht in {duration_run} Min.")
            
            msg = (
                f"🏁 **Wassermenge erreicht!**\n"
                f"💧 Bewässerung nach {target_volume} Litern automatisch beendet.\n"
                f"⏱️ Benötigte Zeit: ca. {duration_run} Minute(n)."
            )
            send_notification(msg)
            logger.info("Bewässerungslauf über Volumenlimit beendet.")
            break
            
        time.sleep(2)  # Alle 2 Sekunden prüfen

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
