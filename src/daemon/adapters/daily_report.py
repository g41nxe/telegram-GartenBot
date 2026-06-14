import logging
import time
from datetime import datetime
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
    abnormal_state = valve.get("valve_abnormal_state") or "normal"

    if battery <= config.BATTERY_WARNING_THRESHOLD:
        warnings.append(
            f"🪫 **Niedriger Batteriestand ({wish_name}):** {battery}%"
            f" (Grenzwert: {config.BATTERY_WARNING_THRESHOLD}%)"
        )

    if abnormal_state != "normal":
        warnings.append(f"🚨 **Ventil-Anomalie erkannt ({wish_name}):** {abnormal_state}")

    return warnings


_RAIN_DEVIATION_THRESHOLD_MM = 2.0  # DWD-Schwellenwert für signifikante Abweichung


def _format_watering_section(success_count: int, failed_count: int, total_volume: float) -> str:
    if success_count == 0 and failed_count == 0:
        return "💧 In den letzten 24h wurde nicht bewässert."
    if success_count == 1:
        base = f"💧 In den letzten 24h wurde 1× bewässert — {total_volume} Liter gesamt."
    else:
        base = f"💧 In den letzten 24h wurde {success_count}× bewässert — {total_volume} Liter gesamt."
    if failed_count == 1:
        base += " 1 Zyklus fehlgeschlagen."
    elif failed_count > 1:
        base += f" {failed_count} Zyklen fehlgeschlagen."
    return base


def _format_weather_section(
    temp: float, temp_min: float, temp_max: float,
    weather_desc: str,
    rain_last: float, rain_next: float, rain_prob: int,
    yesterday_rain_next: float | None,
) -> str:
    parts = [f"{weather_desc}, heute {temp_min}–{temp_max} °C."]

    if yesterday_rain_next is not None:
        deviation = rain_last - yesterday_rain_next
        if deviation > _RAIN_DEVIATION_THRESHOLD_MM:
            parts.append(
                f"Mehr Regen als erwartet: {rain_last} mm gefallen (Vorhersage gestern: {yesterday_rain_next} mm)."
            )
        elif deviation < -_RAIN_DEVIATION_THRESHOLD_MM:
            parts.append(
                f"Weniger Regen als erwartet: {rain_last} mm gefallen (Vorhersage gestern: {yesterday_rain_next} mm)."
            )
        elif rain_last > 0:
            parts.append(f"{rain_last} mm Regen gefallen.")
    elif rain_last > 0:
        parts.append(f"{rain_last} mm Regen gefallen.")

    if rain_next > 10.0:
        parts.append(f"Heute starker Regen erwartet ({rain_next} mm, {rain_prob}%).")
    elif rain_next >= 2.0:
        parts.append(f"Heute mäßiger Regen erwartet ({rain_next} mm, {rain_prob}%).")
    elif rain_next > 0:
        parts.append(f"Heute wenig Regen erwartet ({rain_next} mm, {rain_prob}%).")
    else:
        parts.append(f"Heute trocken ({rain_prob}% Regenwahrscheinlichkeit).")

    return " ".join(parts)


def _format_valve_line(
    wish_name: str, mqtt_name: str,
    count: int, avg_lqi: float, max_gap_hours: float,
    has_watchdog_alert: bool, battery: int, abnormal_state: str,
) -> str:
    warnings = []
    if battery <= config.BATTERY_WARNING_THRESHOLD:
        warnings.append(f"🪫 Batterie {battery}%")
    if abnormal_state != "normal":
        warnings.append(f"🚨 Anomalie: {abnormal_state}")

    if count == 0:
        signal_text = "Keine Verbindung ⚠️"
    else:
        if avg_lqi >= 180:
            quality = "sehr gutes Signal"
        elif avg_lqi >= 120:
            quality = "gutes Signal"
        elif avg_lqi >= 60:
            quality = "ausreichendes Signal"
        else:
            quality = "schwaches Signal"
        gap_text = f", max. {max_gap_hours:.0f}h Funkstille" if max_gap_hours >= 1 else ""
        watchdog_text = " ⚠️" if has_watchdog_alert else ""
        signal_text = f"{quality} (Ø {avg_lqi:.0f} LQI, {count} Meldungen{gap_text}){watchdog_text}"

    line = f"📡 **{wish_name}** — {signal_text}"
    if warnings:
        line += " | " + ", ".join(warnings)
    return line


def generate_daily_report(today_str: str) -> str:
    """Generiert den Text für den täglichen Statusbericht."""
    # 1. Guss-Statistiken der letzten 24h
    success_count, failed_count, total_volume = database.get_watering_stats_last_24h()

    # 2. Wetterdaten (Live-Abfrage)
    weather_result = None
    try:
        weather_result = weather.get_weather_data(config.LATITUDE, config.LONGITUDE)
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Wetterdaten für Statusbericht: {e}")
    if weather_result is not None:
        rain_last, rain_next, temp, weather_code, temp_min, temp_max, rain_prob = weather_result
        weather_desc = get_wmo_description(weather_code)
    else:
        rain_last, rain_next, temp, weather_code, temp_min, temp_max, rain_prob = 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0
        weather_desc = "Unbekannt"

    # 3. Gestrige Regenvorhersage für Abweichungsvergleich
    yesterday_weather = database.get_weather_around_hours_ago(24)
    yesterday_rain_next = yesterday_weather["rain_next_24h_mm"] if yesterday_weather else None

    # 4. System-Warnungen
    warnings = []
    if mqtt_client.HAS_PAHO:
        if not mqtt_client.is_broker_connected():
            warnings.append("🚨 **System-Dienst gestört:** MQTT-Broker ist offline")
        elif mqtt_client.get_bridge_status() != "online":
            warnings.append("🚨 **System-Dienst gestört:** Mittelweg-Dienst (Zigbee2MQTT) ist offline")

    # 5. Pro-Ventil-Status
    valves = database.get_all_valves()
    valve_lines = []
    for valve in valves:
        mqtt_name = valve["mqtt_name"]
        wish_name = valve["wish_name"]
        conn_stats = database.get_device_status_stats_last_24h(mqtt_name)
        flag_key = f"watchdog_alert_active_valve_{valve['id']}"
        has_watchdog_alert = database.get_metadata(flag_key) == "1"
        battery = valve.get("battery") or 100
        abnormal_state = valve.get("valve_abnormal_state") or "normal"

        valve_lines.append(_format_valve_line(
            wish_name=wish_name,
            mqtt_name=mqtt_name,
            count=conn_stats["count"],
            avg_lqi=conn_stats["avg_lqi"],
            max_gap_hours=conn_stats["max_gap_hours"],
            has_watchdog_alert=has_watchdog_alert,
            battery=battery,
            abnormal_state=abnormal_state,
        ))

    try:
        date_obj = datetime.strptime(today_str, "%Y-%m-%d")
        display_date = date_obj.strftime("%d.%m.%Y")
    except Exception:
        display_date = today_str

    watering_text = _format_watering_section(success_count, failed_count, total_volume)
    weather_text = _format_weather_section(
        temp=temp, temp_min=temp_min, temp_max=temp_max,
        weather_desc=weather_desc,
        rain_last=rain_last, rain_next=rain_next, rain_prob=rain_prob,
        yesterday_rain_next=yesterday_rain_next,
    )
    valve_text = "\n".join(valve_lines) if valve_lines else "Keine Ventile registriert."

    warning_text = ""
    if warnings:
        warning_text = "\n\n⚠️ **System-Warnungen:**\n" + "\n".join([f"- {w}" for w in warnings])

    return (
        f"📊 **Täglicher Statusbericht vom {display_date}**\n\n"
        f"{watering_text}\n\n"
        f"{weather_text}\n\n"
        f"{valve_text}"
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
