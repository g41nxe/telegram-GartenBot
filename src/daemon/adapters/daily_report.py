import logging
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


def _camera_warnings(camera: dict) -> list[str]:
    """Gibt Warnungen für eine einzelne Kamera zurück (aktuell: Akkustand)."""
    warnings = []
    battery = camera.get("battery")
    if battery is None:
        return warnings
    wish_name = camera["wish_name"]
    _bat_threshold = config.get_setting("BATTERY_WARNING_THRESHOLD", 20)
    if int(battery) <= _bat_threshold:
        warnings.append(
            f"🪫 *Niedriger Akkustand ({wish_name}):* {battery}%"
            f" (Grenzwert: {_bat_threshold}%)"
        )
    return warnings


def _valve_warnings(valve: dict) -> list[str]:
    """Gibt Warnungen für ein einzelnes Ventil zurück."""
    warnings = []
    wish_name = valve["wish_name"]
    battery_raw = valve.get("battery")
    battery = battery_raw if battery_raw is not None else 100
    abnormal_state = valve.get("valve_abnormal_state") or "normal"

    _bat_threshold = config.get_setting("BATTERY_WARNING_THRESHOLD", 20)
    if battery <= _bat_threshold:
        warnings.append(
            f"🪫 *Niedriger Batteriestand ({wish_name}):* {battery}%"
            f" (Grenzwert: {_bat_threshold}%)"
        )

    if abnormal_state != "normal":
        warnings.append(f"🚨 *Ventil-Anomalie erkannt ({wish_name}):* {abnormal_state}")

    return warnings


def _format_morning_report_short(
    date_display: str,
    watering_line: str,
    weather_line: str,
    rain_extra_line: "str | None",
) -> str:
    """Kurzform des Morgen-Berichts (3–4 Zeilen, alles grün)."""
    parts = [f"🌿 *Guten Morgen, {date_display}!*", ""]
    parts.append(weather_line)
    if rain_extra_line:
        parts.append(rain_extra_line)
    parts.append(watering_line)
    parts.append("✅ System: alles in Ordnung")
    return "\n".join(parts)


def _format_morning_report_problem(
    date_display: str,
    issues: list,
    watering_line: str,
    weather_line: str,
    rain_extra_line: "str | None",
) -> str:
    """Erweiterter Morgen-Bericht mit Problem-Block (sortiert nach Schwere)."""
    parts = [f"🌿 *Guten Morgen, {date_display}!*", ""]
    parts.extend(issues)
    parts.append("")
    parts.append(weather_line)
    if rain_extra_line:
        parts.append(rain_extra_line)
    parts.append(watering_line)
    return "\n".join(parts)


def _is_report_green(valves: list, services_ok: bool) -> bool:
    """True wenn System und alle Ventile im Normalzustand — Kurzform des Morgen-Berichts wird verwendet."""
    if not services_ok:
        return False
    threshold = config.get_setting("BATTERY_WARNING_THRESHOLD", 20)
    for valve in valves:
        battery = valve.get("battery")
        if battery is not None and int(battery) <= threshold:
            return False
        if (valve.get("valve_abnormal_state") or "normal") != "normal":
            return False
        flag_key = f"watchdog_alert_active_valve_{valve['id']}"
        if database.get_metadata(flag_key) == "1":
            return False
    return True


def _format_weather_morning(
    temp_min: float,
    temp_max: float,
    weather_desc: str,
    rain_next: float,
    rain_prob: int,
) -> tuple[str, "str | None"]:
    """Wetter-Zusammenfassung für den Morgen-Bericht. Gibt (Hauptzeile, optionale Regenzeile) zurück."""
    if rain_next >= 2.0:
        emoji = "🌧"
    elif rain_next >= 0.5:
        emoji = "🌦"
    else:
        emoji = "☀️"

    main = f"{emoji} Heute {temp_min:.0f}–{temp_max:.0f} °C · {weather_desc} ({rain_prob} % ☂)"
    extra = f"🌧 {rain_next} mm erwartet" if rain_next >= 0.5 else None
    return main, extra


def _format_watering_morning(
    success_count: int,
    failed_count: int,
    total_volume: float,
    skip_count: int = 0,
    rain_last: float = 0.0,
) -> str:
    """Bewässerungs-Zusammenfassung für den Morgen-Bericht (eine Zeile)."""
    if skip_count > 0 and success_count == 0 and failed_count == 0:
        return f"🌧 Guss übersprungen · {rain_last} mm gefallen"
    if success_count == 0 and failed_count == 0:
        return "💧 Gestern nicht bewässert"
    if success_count == 1:
        line = f"💧 Gestern 1× bewässert · {total_volume:.0f} L"
    else:
        line = f"💧 Gestern {success_count}× bewässert · {total_volume:.0f} L gesamt"
    if failed_count == 1:
        line += " · 1 Fehler"
    elif failed_count > 1:
        line += f" · {failed_count} Fehler"
    return line


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
    rain_last_source: str = "measured",
) -> str:
    parts = [f"{weather_desc}, heute {temp_min}–{temp_max} °C."]

    if rain_last_source == "sensor":
        source_label = "(lokal gemessen)"
    elif rain_last_source == "measured":
        source_label = "(ERA5-Reanalyse)"
    else:
        source_label = ""

    if rain_last_source not in ("measured", "sensor"):
        parts.append("Gemessene Regendaten zurzeit nicht verfügbar.")
    else:
        if yesterday_rain_next is not None:
            deviation = rain_last - yesterday_rain_next
            if deviation > _RAIN_DEVIATION_THRESHOLD_MM:
                parts.append(
                    f"Mehr Regen als erwartet: {rain_last} mm gefallen {source_label} (Vorhersage gestern: {yesterday_rain_next} mm)."
                )
            elif deviation < -_RAIN_DEVIATION_THRESHOLD_MM:
                parts.append(
                    f"Weniger Regen als erwartet: {rain_last} mm gefallen {source_label} (Vorhersage gestern: {yesterday_rain_next} mm)."
                )
            elif rain_last > 0:
                parts.append(f"{rain_last} mm Regen gefallen {source_label}.".strip())
        elif rain_last > 0:
            parts.append(f"{rain_last} mm Regen gefallen {source_label}.".strip())

    if rain_next > 10.0:
        parts.append(f"Heute starker Regen erwartet ({rain_next} mm, {rain_prob}%).")
    elif rain_next >= 2.0:
        parts.append(f"Heute mäßiger Regen erwartet ({rain_next} mm, {rain_prob}%).")
    elif rain_next > 0:
        parts.append(f"Heute wenig Regen erwartet ({rain_next} mm, {rain_prob}%).")
    else:
        parts.append(f"Heute trocken ({rain_prob}% Regenwahrscheinlichkeit).")

    return " ".join(parts)


def _format_rain_sensor_line(rain_stats: dict, last_measurement: dict | None) -> str | None:
    """Regensensor-Zeile für den Tagesbericht. Gibt None zurück wenn kein Sensor bekannt."""
    if not last_measurement:
        return None
    if not rain_stats:
        offline_h = 0.0
        try:
            from datetime import datetime
            offline_h = (datetime.now() - datetime.fromisoformat(last_measurement["timestamp"])).total_seconds() / 3600
        except Exception:
            pass
        return f"🌧 Regen — ⚠️ Sensor offline (seit {offline_h:.0f} h), Fallback auf ERA5"
    rain_sum = rain_stats.get("rain_sum", 0.0)
    temp_avg = rain_stats.get("temp_avg", 0.0)
    temp_max = rain_stats.get("temp_max", 0.0)
    battery = last_measurement.get("battery_pct", 100)
    bat_label = _get_battery_description_simple(battery)
    return (
        f"🌧 Regen — {rain_sum} mm gefallen · "
        f"Ø {temp_avg} °C, max {temp_max} °C · 🔋 {bat_label}"
    )


def _get_battery_description_simple(battery_pct) -> str:
    try:
        b = int(battery_pct)
    except (TypeError, ValueError):
        return "unbekannt"
    if b > 60:
        return "voll"
    if b > 20:
        return "mittel"
    return "schwach"


def _format_valve_line(
    wish_name: str, mqtt_name: str,
    count: int, avg_lqi: float, max_gap_hours: float,
    has_watchdog_alert: bool, battery: int, abnormal_state: str,
) -> str:
    warnings = []
    if battery <= config.get_setting("BATTERY_WARNING_THRESHOLD", 20):
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

    line = f"📡 *{wish_name}* — {signal_text}"
    if warnings:
        line += " | " + ", ".join(warnings)
    return line


def generate_daily_report(today_str: str) -> str:
    """Generiert den Morgen-Bericht (Kurzform wenn grün, Problemfall sonst)."""
    # 1. Guss-Statistiken
    success_count, failed_count, total_volume = database.get_watering_stats_last_24h()
    skip_count = database.get_watering_skip_count_last_24h()

    # 2. Wetterdaten (Live-Abfrage)
    weather_result = None
    try:
        weather_result = weather.get_weather_data(config.LATITUDE, config.LONGITUDE)
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Wetterdaten für Morgen-Bericht: {e}")
    if weather_result is not None:
        rain_last, rain_next, temp, weather_code, temp_min, temp_max, rain_prob, rain_last_source = weather_result
        weather_desc = get_wmo_description(weather_code)
    else:
        rain_last, rain_next, temp, weather_code, temp_min, temp_max, rain_prob, rain_last_source = 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0, "forecast"
        weather_desc = "Unbekannt"

    # 3. Systemzustand
    if mqtt_client.HAS_PAHO:
        broker_ok = mqtt_client.is_broker_connected()
        bridge_ok = mqtt_client.get_bridge_status() == "online"
        services_ok = broker_ok and bridge_ok
    else:
        services_ok = True

    # 4. Ventile
    valves = database.get_all_valves()

    # 4b. Regensensor
    rain_sensor_last = database.get_last_rain_measurement()
    rain_sensor_stats = database.get_rain_stats_last_24h() if rain_sensor_last else {}

    # 5. Datum (Wochentag-Kurzform)
    _days_de = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    try:
        date_obj = datetime.strptime(today_str, "%Y-%m-%d")
        date_display = f"{_days_de[date_obj.weekday()]} {date_obj.strftime('%d.%m.')}"
    except Exception:
        date_display = today_str

    # 6. Gemeinsame Bausteine
    watering_line = _format_watering_morning(success_count, failed_count, total_volume, skip_count, rain_last)
    weather_line, rain_extra = _format_weather_morning(temp_min, temp_max, weather_desc, rain_next, rain_prob)

    # 6b. Regensensor-Zeile
    rain_sensor_line = _format_rain_sensor_line(rain_sensor_stats, rain_sensor_last)

    # 7. Grün-Prüfung → Pfad wählen
    if _is_report_green(valves, services_ok):
        report = _format_morning_report_short(date_display, watering_line, weather_line, rain_extra)
        if rain_sensor_line:
            report += f"\n{rain_sensor_line}"
        return report

    # Problem-Pfad: Issues nach Schwere aufsammeln
    threshold = config.get_setting("BATTERY_WARNING_THRESHOLD", 20)
    issues = []

    if not services_ok:
        if mqtt_client.HAS_PAHO and not mqtt_client.is_broker_connected():
            issues.append("🔴 MQTT-Broker nicht erreichbar")
        else:
            issues.append("🔴 Mittelweg-Dienst (Zigbee2MQTT) offline")

    for valve in valves:
        wish_name = valve["wish_name"]
        abnormal = (valve.get("valve_abnormal_state") or "normal")
        battery = valve.get("battery")
        flag_key = f"watchdog_alert_active_valve_{valve['id']}"
        has_watchdog = database.get_metadata(flag_key) == "1"

        if abnormal != "normal":
            issues.append(f"🚨 {wish_name}: Anomalie erkannt ({abnormal})")
        elif battery is not None and int(battery) <= threshold:
            issues.append(f"🟡 {wish_name}: Batterie schwach ({battery}%)")
        if has_watchdog:
            issues.append(f"⚠️ {wish_name}: kein Signal (Watchdog aktiv)")

    report = _format_morning_report_problem(date_display, issues, watering_line, weather_line, rain_extra)
    if rain_sensor_line:
        report += f"\n{rain_sensor_line}"
    return report


def send_daily_report(today_str: str):
    """Generiert den täglichen Bericht und publiziert ihn als Event; markiert ihn als versendet.

    Voraussetzung: Der Aufrufer hat vorab mqtt_client.request_valve_status() aufgerufen
    und ausreichend Zeit für die Antwort der Ventile abgewartet.
    """
    database.set_metadata("last_daily_report_date", today_str)
    try:
        report_text = generate_daily_report(today_str)
        # Snapshot für morgen schreiben (nach generate_daily_report, nutzt frische Zeile)
        last_weather = database.get_last_weather()
        if last_weather:
            database.set_daily_forecast_snapshot(
                date_str=today_str,
                rain_next_mm=last_weather.get("rain_next_24h_mm", 0.0) or 0.0,
                window_start=datetime.now().strftime("%H:00")
            )
            
        _global_bus.publish(DailyReportTriggered(today_str, report_text))
        logger.info(f"Täglicher Statusbericht für {today_str} erfolgreich generiert und Event veröffentlicht.")
    except Exception as e:
        logger.error(f"Fehler beim Generieren/Senden des täglichen Statusberichts: {e}")
