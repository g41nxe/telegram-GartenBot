import time
import logging
import threading
from datetime import datetime, timedelta
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

def _get_wmo_description(code: int) -> str:
    mapping = {
        0: "☀️ Sonnig / Klar", 1: "🌤️ Leicht bewölkt", 2: "⛅ Teilweise bewölkt", 3: "☁️ Bedeckt / Bewölkt",
        45: "🌫️ Nebelig", 48: "🌫️ Raureifnebel", 51: "🌧️ Leichter Nieselregen", 53: "🌧️ Mäßiger Nieselregen",
        55: "🌧️ Starker Nieselregen", 61: "🌧️ Leichter Regen", 63: "🌧️ Mäßiger Regen", 65: "🌧️ Starker Regen",
        80: "🌧️ Leichte Regenschauer", 81: "🌧️ Mäßige Regenschauer", 82: "🌧️ Starke Regenschauer", 95: "⚡ Gewitter"
    }
    return mapping.get(code, "🌡️ Unbekannt")

def generate_daily_report(today_str: str) -> str:
    """Generiert den Text für den täglichen Statusbericht."""
    from .adapters import mqtt_client
    
    # 1. Guss-Statistiken der letzten 24 Stunden
    success_count, failed_count, total_volume = database.get_watering_stats_last_24h()
    
    # 2. Wetterdaten abrufen
    try:
        rain_last, rain_next, temp, weather_code = weather.get_weather_data(config.LATITUDE, config.LONGITUDE)
        weather_desc = _get_wmo_description(weather_code)
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Wetterdaten für Statusbericht: {e}")
        rain_last, rain_next, temp, weather_code = 0.0, 0.0, 0.0, 0
        weather_desc = "Unbekannt"
        
    # 3. Ventil-Status und Warnungen prüfen
    status = mqtt_client.get_valve_status()
    warnings = []
    
    # Batteriewarnung
    battery = status.get("battery", 100)
    if battery <= config.BATTERY_WARNING_THRESHOLD:
        warnings.append(f"🪫 **Niedriger Batteriestand:** {battery}% (Grenzwert: {config.BATTERY_WARNING_THRESHOLD}%)")
        
    # Offline-Warnung (letztes Update älter als 24h)
    last_update_str = status.get("last_update")
    if not last_update_str:
        warnings.append("⚠️ **Verbindung verloren:** Ventil ist nicht gekoppelt / offline")
    else:
        try:
            last_up = datetime.fromisoformat(last_update_str)
            if datetime.now() - last_up > timedelta(hours=24):
                time_diff_hours = int((datetime.now() - last_up).total_seconds() / 3600)
                warnings.append(f"⚠️ **Verbindung verloren:** Letzte Rückmeldung vor {time_diff_hours} Stunden ({last_up.strftime('%d.%m. %H:%M')})")
        except Exception:
            warnings.append("⚠️ **Verbindung verloren:** Fehler beim Ermitteln des letzten Signals")
            
    # Anomalien
    abnormal_state = status.get("valve_abnormal_state", "normal")
    if abnormal_state != "normal":
        warnings.append(f"🚨 **Ventil-Anomalie erkannt:** {abnormal_state}")
        
    # Nachricht zusammensetzen
    warning_text = ""
    if warnings:
        warning_text = "\n⚠️ **System-Warnungen:**\n" + "\n".join([f"- {w}" for w in warnings]) + "\n"
        
    # Formatiere Datum zur Anzeige
    try:
        date_obj = datetime.strptime(today_str, "%Y-%m-%d")
        display_date = date_obj.strftime("%d.%m.%Y")
    except Exception:
        display_date = today_str
        
    msg = (
        f"📊 **Täglicher Statusbericht vom {display_date}**\n\n"
        f"💧 **Bewässerung (letzte 24h):**\n"
        f"   - Erfolgreiche Zyklen: {success_count}\n"
        f"   - Fehlgeschlagene Zyklen: {failed_count}\n"
        f"   - Gesamtvolumen: {total_volume} Liter\n\n"
        f"🌤️ **Wetter:**\n"
        f"   - Temperatur: {temp} °C | {weather_desc}\n"
        f"   - Regen (letzte 24h): {rain_last} mm\n"
        f"   - Vorhersage (nächste 24h): {rain_next} mm\n"
        f"{warning_text}"
    )
    return msg

def send_daily_report(today_str: str):
    """Generiert den täglichen Bericht und versendet ihn über Telegram, aktualisiert system_metadata."""
    # Setze das Datum direkt in der DB, um mehrfachen Trigger zu verhindern
    database.set_metadata("last_daily_report_date", today_str)
    
    # 1. Vorab aktuelle Werte vom Ventil anfordern (Aufweck-Abfrage)
    try:
        from .adapters import mqtt_client
        mqtt_client.request_valve_status()
    except Exception as e:
        logger.warning(f"Konnte Ventil-Statusaktualisierung nicht anfordern: {e}")
        
    # 2. 5 Sekunden warten, um dem Ventil Zeit für den Empfang/Antwort zu geben (Option A)
    time.sleep(5.0)
    
    try:
        report_text = generate_daily_report(today_str)
        send_notification(report_text)
        logger.info(f"Täglicher Statusbericht für {today_str} erfolgreich versendet.")
    except Exception as e:
        logger.error(f"Fehler beim Generieren/Senden des täglichen Statusberichts: {e}")


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
            today_str = now.strftime("%Y-%m-%d")
            
            # Täglicher Statusbericht um 08:00 Uhr (oder danach falls heute noch ausstehend)
            if current_time >= "08:00":
                last_report = database.get_metadata("last_daily_report_date")
                if last_report != today_str:
                    logger.info(f"Täglicher Statusbericht für heute ({today_str}) steht aus. Starte Versand...")
                    t_report = threading.Thread(target=send_daily_report, args=(today_str,), daemon=True)
                    t_report.start()
            
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
