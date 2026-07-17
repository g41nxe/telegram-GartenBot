import logging
from datetime import datetime
from .. import config
from . import database, weather, mqtt_client
from ..core.weather_codes import get_wmo_description
from ..core.weather_report import resolve_heute_weather, WEATHER_UNAVAILABLE_MESSAGE
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


def _sensor_issues() -> list:
    """Regensensor-Warnungen im selben Format wie Ventil-Meldungen.

    Leere Liste, wenn kein Regensensor bekannt oder gesund.
    """
    issues = []
    last = database.get_last_rain_measurement()
    if not last:
        return issues
    threshold = config.get_setting("BATTERY_WARNING_THRESHOLD", 20)
    battery = last.get("battery_pct")
    if battery is not None and int(battery) <= threshold:
        issues.append(f"🟡 Regensensor: Batterie schwach ({int(battery)}%)")
    if database.get_metadata("watchdog_alert_active_rain_sensor") == "1":
        issues.append("⚠️ Regensensor: kein Signal (Watchdog aktiv)")
    return issues


def _kamera_issues() -> list:
    """Störungen der Garten-Kameras für den Tagesbericht (ADR 0041).

    Der Aufnahme-Verzug ist der Frühindikator: Er steigt, lange bevor Bilder ganz ausbleiben.
    Die Inaktivität meldet der Watchdog ohnehin sofort per Nachricht — hier steht, was gerade
    noch offen ist.
    """
    issues = []
    for camera in database.get_all_cameras():
        mac = camera["mac_address"]
        name = camera.get("wish_name", "?")
        # Vorrang der Inaktivität (ADR 0041): Eine stumme Kamera trifft ihre Aufnahme-Zeitpunkte
        # selbstverständlich nicht — die mildere Diagnose würde hier nur in die Irre führen.
        if database.get_metadata(f"watchdog_alert_active_camera_{mac}") == "1":
            issues.append(f"⚠️ Kamera „{name}“: kein Bild (Watchdog aktiv)")
        elif database.get_metadata(f"watchdog_delay_alert_active_camera_{mac}") == "1":
            issues.append(f"⚠️ Kamera „{name}“: erfüllt ihre Aufnahme-Zeitpunkte nicht mehr")
    return issues


def _is_report_green(valves: list, services_ok: bool) -> bool:
    """True wenn System, alle Ventile und der Regensensor im Normalzustand — Kurzform wird verwendet."""
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
    if _sensor_issues() or _kamera_issues():
        return False
    return True


def _format_gestern_aktivitaet(
    success_count: int, failed_count: int, total_volume: float,
    skip_count: int, nebel_windows: int, nebel_minutes: float,
) -> str:
    """Aktivitätszeile des Gestern-Blocks: Guss (💧) plus Nebel-Intervall (🌫️), `·`-gebündelt."""
    if skip_count > 0 and success_count == 0 and failed_count == 0:
        line = "💧 Guss übersprungen (Regen)"
    elif success_count == 0 and failed_count == 0:
        line = "💧 nicht bewässert"
    elif success_count == 1:
        line = f"💧 1× bewässert · {total_volume:.0f} l"
    else:
        line = f"💧 {success_count}× bewässert · {total_volume:.0f} l"

    if failed_count == 1:
        line += " · 1 Fehler"
    elif failed_count > 1:
        line += f" · {failed_count} Fehler"

    if nebel_windows > 0:
        line += f" · 🌫️ {nebel_windows} Fenster · {int(round(nebel_minutes))} Min"

    return line


def _format_gestern_wetter(
    rain_mm: float, temp_avg: "float | None", temp_max: "float | None", from_sensor: bool,
) -> str:
    """Wetterzeile des Gestern-Blocks: gefallener Regen (🌧) und Temperatur Ø/max (🌡) kombiniert.

    Quell-Tag nur als Ausnahme: ohne Tag = lokaler Sensor; `(Open-Meteo)` bei Sensor-Ausfall
    (deckt Regen und Temperatur gemeinsam ab).
    """
    line = f"🌧 {rain_mm} mm"
    if temp_avg is not None and temp_max is not None:
        line += f" · 🌡 Ø {temp_avg} °C, max {temp_max} °C"
    if not from_sensor:
        line += " (Open-Meteo)"
    return line


def _format_heute(
    temp_min: float, temp_max: float, weather_code: int, rain_next: float, rain_prob: int,
) -> str:
    """Heute-Zeile (Ausblick): emoji-präfixierte WMO-Beschreibung · Temp-Spanne · Regen/Prob."""
    desc = get_wmo_description(weather_code)
    line = f"{desc} · {temp_min:.0f}–{temp_max:.0f} °C · "
    if rain_next >= 0.5:
        line += f"{rain_next} mm ({rain_prob} % ☂)"
    else:
        line += f"{rain_prob} % ☂"
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
                parts.append(f"{rain_last} mm Regen gefallen {source_label}.")
        elif rain_last > 0:
            parts.append(f"{rain_last} mm Regen gefallen {source_label}.")

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
    nebel_windows, nebel_minutes = database.get_nebel_stats_last_24h()

    # 2. Wetterdaten (Live-Abfrage)
    weather_result = None
    try:
        weather_result = weather.get_weather_data(config.LATITUDE, config.LONGITUDE)
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Wetterdaten für Morgen-Bericht: {e}")
    # Der Gestern-Block braucht nur den gefallenen Regen; die Vorhersagewerte (Temp, Code,
    # erwarteter Regen) holt der Heute-Block in Schritt 7 selbst — inkl. Cache-Rückfall (ADR 0042).
    rain_last = weather_result[0] if weather_result is not None else 0.0

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

    # 6. Gestern-Block (Rückblick): Aktivitätszeile + Wetterzeile
    aktivitaet_line = _format_gestern_aktivitaet(
        success_count, failed_count, total_volume, skip_count, nebel_windows, nebel_minutes
    )
    if rain_sensor_stats:
        gestern_wetter_line = _format_gestern_wetter(
            rain_sensor_stats.get("rain_sum", 0.0),
            rain_sensor_stats.get("temp_avg"),
            rain_sensor_stats.get("temp_max"),
            from_sensor=True,
        )
    else:
        # Sensor-Ausfall: Regen vom Wetter-Dienst, gestrige Temperatur via Open-Meteo
        try:
            temp_stats = weather.get_yesterday_temp_stats(config.LATITUDE, config.LONGITUDE)
        except Exception:
            temp_stats = None
        y_avg, y_max = temp_stats if temp_stats else (None, None)
        gestern_wetter_line = _format_gestern_wetter(rain_last, y_avg, y_max, from_sensor=False)

    # 7. Heute-Block (Ausblick) — bei Live-Ausfall Rückfall auf frischen Cache (ADR 0042)
    heute_cache = database.get_last_weather() if weather_result is None else None
    heute = resolve_heute_weather(
        weather_result, heute_cache, datetime.now(), config.REPORT_WEATHER_MAX_AGE_HOURS
    )
    if heute.available:
        heute_line = _format_heute(
            heute.temp_min, heute.temp_max, heute.weather_code, heute.rain_next, heute.rain_prob
        )
        if heute.stand:
            heute_line += f"  *(Stand: {heute.stand})*"
    else:
        heute_line = WEATHER_UNAVAILABLE_MESSAGE

    # 8. Zustands-Block (Abschluss)
    if _is_report_green(valves, services_ok):
        zustand = "✅ System: alles in Ordnung"
    else:
        issues = _collect_issues(valves, services_ok)
        zustand = "\n".join(issues) if issues else "✅ System: alles in Ordnung"

    return (
        f"🌿 *Guten Morgen, {date_display}!*\n\n"
        f"*Gestern*\n{aktivitaet_line}\n{gestern_wetter_line}\n\n"
        f"*Heute*\n{heute_line}\n\n"
        f"{zustand}"
    )


def _collect_issues(valves: list, services_ok: bool) -> list:
    """Sammelt die Problem-Meldungen für den Zustands-Block: Dienst, Ventile, Regensensor."""
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

    issues.extend(_sensor_issues())
    issues.extend(_kamera_issues())
    return issues


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
