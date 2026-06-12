import logging
import time
from datetime import datetime, timedelta
from .. import config
from . import database, weather, mqtt_client
from ..core.weather_codes import get_wmo_description
from ..core.scheduler_events import DailyReportTriggered
from ..adapters.mqtt_client import _global_bus

logger = logging.getLogger("garden_daily_report")


def generate_daily_report(today_str: str) -> str:
    """Generiert den Text für den täglichen Statusbericht."""
    # 1. Guss-Statistiken der letzten 24 Stunden
    success_count, failed_count, total_volume = database.get_watering_stats_last_24h()

    # 2. Wetterdaten abrufen
    try:
        rain_last, rain_next, temp, weather_code, temp_min, temp_max, rain_prob = weather.get_weather_data(config.LATITUDE, config.LONGITUDE)
        weather_desc = get_wmo_description(weather_code)
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Wetterdaten für Statusbericht: {e}")
        rain_last, rain_next, temp, weather_code, temp_min, temp_max, rain_prob = 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0
        weather_desc = "Unbekannt"

    # 3. Ventil-Status und Warnungen prüfen
    status = mqtt_client.get_valve_status()
    warnings = []

    if mqtt_client.HAS_PAHO:
        if not mqtt_client.is_broker_connected():
            warnings.append("🚨 **System-Dienst gestört:** MQTT-Broker ist offline")
        elif mqtt_client.get_bridge_status() != "online":
            warnings.append("🚨 **System-Dienst gestört:** Mittelweg-Dienst (Zigbee2MQTT) ist offline")

    battery = status.get("battery", 100)
    if battery <= config.BATTERY_WARNING_THRESHOLD:
        warnings.append(f"🪫 **Niedriger Batteriestand:** {battery}% (Grenzwert: {config.BATTERY_WARNING_THRESHOLD}%)")

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

    abnormal_state = status.get("valve_abnormal_state", "normal")
    if abnormal_state != "normal":
        warnings.append(f"🚨 **Ventil-Anomalie erkannt:** {abnormal_state}")

    # 4. Verbindungsstatistik der letzten 24 Stunden
    conn_stats = database.get_device_status_stats_last_24h("garden_valve")

    if conn_stats["count"] == 0:
        lqi_desc = "Keine Verbindung"
    elif conn_stats["avg_lqi"] >= 180:
        lqi_desc = "Sehr gut"
    elif conn_stats["avg_lqi"] >= 120:
        lqi_desc = "Gut"
    elif conn_stats["avg_lqi"] >= 60:
        lqi_desc = "Ausreichend"
    else:
        lqi_desc = "Kritisch"

    conn_info = (
        f"📡 **Verbindung (letzte 24h):**\n"
        f"   - Signalmeldungen: {conn_stats['count']}\n"
        f"   - Signalstärke: Ø {conn_stats['avg_lqi']} LQI ({lqi_desc})\n"
        f"   - Längste Funkstille: {conn_stats['max_gap_hours']} Std.\n"
    )

    warning_text = ""
    if warnings:
        warning_text = "\n⚠️ **System-Warnungen:**\n" + "\n".join([f"- {w}" for w in warnings]) + "\n"

    try:
        date_obj = datetime.strptime(today_str, "%Y-%m-%d")
        display_date = date_obj.strftime("%d.%m.%Y")
    except Exception:
        display_date = today_str

    return (
        f"📊 **Täglicher Statusbericht vom {display_date}**\n\n"
        f"💧 **Bewässerung (letzte 24h):**\n"
        f"   - Erfolgreiche Zyklen: {success_count}\n"
        f"   - Fehlgeschlagene Zyklen: {failed_count}\n"
        f"   - Gesamtvolumen: {total_volume} Liter\n\n"
        f"🌤️ **Wetter:**\n"
        f"   - Temperatur: {temp} °C (Min: {temp_min} °C / Max: {temp_max} °C) | {weather_desc}\n"
        f"   - Regenwahrscheinlichkeit: {rain_prob}%\n"
        f"   - Regen (letzte 24h): {rain_last} mm\n"
        f"   - Vorhersage (nächste 24h): {rain_next} mm\n\n"
        f"{conn_info}"
        f"{warning_text}"
    )


def send_daily_report(today_str: str):
    """Generiert den täglichen Bericht und publiziert ihn als Event; markiert ihn als versendet."""
    database.set_metadata("last_daily_report_date", today_str)

    try:
        mqtt_client.request_valve_status()
    except Exception as e:
        logger.warning(f"Konnte Ventil-Statusaktualisierung nicht anfordern: {e}")

    # Warte kurz, damit das Ventil Zeit hat zu antworten
    time.sleep(5.0)

    try:
        report_text = generate_daily_report(today_str)
        _global_bus.publish(DailyReportTriggered(today_str, report_text))
        logger.info(f"Täglicher Statusbericht für {today_str} erfolgreich generiert und Event veröffentlicht.")
    except Exception as e:
        logger.error(f"Fehler beim Generieren/Senden des täglichen Statusberichts: {e}")
