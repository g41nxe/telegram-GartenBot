import logging
import time
from datetime import datetime, timedelta
from .. import config
from . import database, weather, mqtt_client
from ..core.weather_codes import get_wmo_description
from ..core.scheduler_events import DailyReportTriggered
from ..adapters.mqtt_client import _global_bus

logger = logging.getLogger("garden_daily_report")


def _lqi_label(avg_lqi: float) -> str:
    if avg_lqi >= 180:
        return "Sehr gut"
    if avg_lqi >= 120:
        return "Gut"
    if avg_lqi >= 60:
        return "Ausreichend"
    return "Kritisch"


def _valve_warnings(valve: dict) -> list[str]:
    """Gibt Warnungen für ein einzelnes Ventil zurück."""
    warnings = []
    wish_name = valve["wish_name"]
    battery = valve.get("battery") or 100
    last_update_str = valve.get("last_update")
    abnormal_state = valve.get("valve_abnormal_state") or "normal"

    if battery <= config.BATTERY_WARNING_THRESHOLD:
        warnings.append(
            f"🪫 **Niedriger Batteriestand ({wish_name}):** {battery}%"
            f" (Grenzwert: {config.BATTERY_WARNING_THRESHOLD}%)"
        )

    if last_update_str:
        try:
            last_up = datetime.fromisoformat(last_update_str)
            if datetime.now() - last_up > timedelta(hours=24):
                hours = int((datetime.now() - last_up).total_seconds() / 3600)
                warnings.append(
                    f"⚠️ **Verbindung verloren ({wish_name}):** Letzte Rückmeldung vor"
                    f" {hours} Stunden ({last_up.strftime('%d.%m. %H:%M')})"
                )
        except Exception:
            warnings.append(f"⚠️ **Verbindung verloren ({wish_name}):** Fehler beim Ermitteln des letzten Signals")

    if abnormal_state != "normal":
        warnings.append(f"🚨 **Ventil-Anomalie erkannt ({wish_name}):** {abnormal_state}")

    return warnings


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

    # 3. System-Warnungen (Broker / Mittelweg-Dienst)
    warnings = []
    if mqtt_client.HAS_PAHO:
        if not mqtt_client.is_broker_connected():
            warnings.append("🚨 **System-Dienst gestört:** MQTT-Broker ist offline")
        elif mqtt_client.get_bridge_status() != "online":
            warnings.append("🚨 **System-Dienst gestört:** Mittelweg-Dienst (Zigbee2MQTT) ist offline")

    # 4. Pro-Ventil-Status aus der Datenbank
    valves = database.get_all_valves()
    valve_sections = []
    for valve in valves:
        warnings.extend(_valve_warnings(valve))

        mqtt_name = valve["mqtt_name"]
        wish_name = valve["wish_name"]
        conn_stats = database.get_device_status_stats_last_24h(mqtt_name)
        lqi_desc = "Keine Verbindung" if conn_stats["count"] == 0 else _lqi_label(conn_stats["avg_lqi"])

        valve_sections.append(
            f"📡 **{wish_name}** (`{mqtt_name}`):\n"
            f"   - Signalmeldungen: {conn_stats['count']}\n"
            f"   - Signalstärke: Ø {conn_stats['avg_lqi']} LQI ({lqi_desc})\n"
            f"   - Längste Funkstille: {conn_stats['max_gap_hours']} Std.\n"
        )

    conn_info = "\n".join(valve_sections) if valve_sections else "Keine Ventile registriert.\n"

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
