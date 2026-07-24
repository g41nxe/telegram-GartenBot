import json
import logging
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from .. import config
from . import database
from .mqtt_client import _global_bus
from ..core.scheduler_events import WeatherDataFetched
from ..core.watering_advice import evaluate_watering, WateringDecision
from ..core.weather_report import is_cache_fresh, resolve_watering_source

WEATHER_FORECAST_WINDOW_SECONDS = 86400  # Open-Meteo liefert genau 24h voraus
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

logger = logging.getLogger("garden_weather")

# Poll-Resilienz gegen vereinzelte Open-Meteo-5xx (Ticket lca): kleiner Retry mit kurzem Backoff,
# damit ein isolierter 503/502-Blip nicht eine ganze 30-Min-Poll-Runde überspringt.
HTTP_RETRIES = 2          # zusätzliche Versuche nach dem ersten
HTTP_BACKOFF_SECONDS = 2.0  # Basis-Wartezeit; wächst linear pro Versuch


def _http_get_bytes(req, timeout: int = 10):
    """urlopen mit Retry bei transienten HTTP-5xx. 4xx und andere Fehler werden sofort
    weitergereicht (kein Retry). Gibt den Antwort-Body als Bytes zurück."""
    for attempt in range(HTTP_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            transient = 500 <= e.code < 600
            if transient and attempt < HTTP_RETRIES:
                wait = HTTP_BACKOFF_SECONDS * (attempt + 1)
                logger.warning(
                    f"Wetter-Abruf HTTP {e.code} (Versuch {attempt + 1}/{HTTP_RETRIES + 1}) — "
                    f"erneuter Versuch in {wait:.0f}s."
                )
                time.sleep(wait)
                continue
            raise


def _find_current_index(times: list[str]) -> int:
    """Index des letzten Stunden-Zeitstempels <= jetzt (ISO sortiert lexikografisch).

    Ersetzt die frühere Exakt-Match-Logik mit hartem Fallback auf Index 24.
    Gibt -1 zurück, wenn alle Zeitstempel in der Zukunft liegen.
    """
    now_str = datetime.now().strftime("%Y-%m-%dT%H:00")
    idx = -1
    for i, t in enumerate(times):
        if t <= now_str:
            idx = i
        else:
            break
    return idx

def _fetch_measured_rain_last(lat: float, lon: float) -> float | None:
    """Gemessener Niederschlag der letzten 24h aus dem ERA5-Archiv.

    Gibt die Summe in mm zurück oder None bei Netzwerk-/Datenfehler.
    """
    start = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    end = datetime.now().strftime("%Y-%m-%d")
    url = (
        f"{ARCHIVE_URL}?latitude={lat}&longitude={lon}"
        f"&start_date={start}&end_date={end}&hourly=precipitation&timezone=auto"
    )
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'GardenIrrigationDaemon/1.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        times = data.get("hourly", {}).get("time", [])
        precip = data.get("hourly", {}).get("precipitation", [])
        idx = _find_current_index(times)
        if idx < 1 or not precip:
            return None
        start_idx = max(0, idx - 24)
        return round(sum(p for p in precip[start_idx:idx] if p is not None), 2)
    except urllib.error.URLError as e:
        logger.warning(f"Archiv-Wetterabfrage nicht erreichbar: {e}")
    except Exception as e:
        logger.warning(f"Archiv-Wetterdaten nicht verwertbar: {e}")
    return None

# --- Reine Helfer über bereits geparste Open-Meteo-Arrays (Ticket 6xy) --------------------
# Bleiben im Adapter, weil ans Open-Meteo-Array-Layout gekoppelt (ADR 0045), aber rein und
# unit-testbar. null-Sicherheit lebt hier an einem Ort statt an den Aufrufstellen kopiert.

def aggregate_rain_window(precip: list, start: int, end: int) -> float:
    """Null-sichere Regensumme im halb-offenen Fenster [start, end), auf 2 Stellen gerundet."""
    return round(sum(p for p in precip[start:end] if p is not None), 2)


def max_rain_prob(precip_probs: list, current_idx: int, hours: int = 24) -> int:
    """Höchste Regenwahrscheinlichkeit der nächsten `hours` Stunden ab current_idx.
    Open-Meteo liefert modellabhängig teils null — herausfiltern, sonst wirft max() TypeError (Ticket 11b)."""
    if not precip_probs or current_idx >= len(precip_probs):
        return 0
    end = min(len(precip_probs), current_idx + hours)
    window = [p for p in precip_probs[current_idx:end] if p is not None]
    return int(max(window)) if window else 0


def select_rain_last(sensor_fresh: bool, sensor_sum: float, measured: "float | None",
                     forecast_fallback: float) -> "tuple[float, str]":
    """Regen-der-letzten-24h — Quelle der Wahrheit: frischer Sensor > gemessenes Archiv >
    Forecast-Fallback (Ticket 6xy/0028). Liefert (Wert, Quell-Kennung)."""
    if sensor_fresh:
        return sensor_sum, "sensor"
    if measured is not None:
        return measured, "measured"
    return forecast_fallback, "forecast"


def build_hourly_forecast(times: list, temps: list, precip: list, precip_probs: list,
                          wmo: list, current_idx: int) -> str:
    """±24h-Fenster (bis zu 48 Einträge) als JSON-String fürs Wetterchart. Vergangenheitsstunden:
    gemessener Regen → prob 100, trocken → prob 0; Zukunft → Forecast-Wahrscheinlichkeit."""
    chart_start = max(0, current_idx - 24)
    forecast_end = min(chart_start + 48, len(times))
    # precip_probs kann kürzer sein (z. B. leer bei nicht-best_match-Modell) — auf Länge auffüllen
    safe_probs = list(precip_probs) + [0] * max(0, forecast_end - len(precip_probs))
    chart_probs = []
    for i in range(chart_start, forecast_end):
        if i < current_idx:
            chart_probs.append(100 if (i < len(precip) and precip[i] is not None and precip[i] > 0) else 0)
        else:
            chart_probs.append(safe_probs[i] if i < len(safe_probs) else 0)
    return json.dumps({
        "times": times[chart_start:forecast_end],
        "temp": temps[chart_start:forecast_end],
        "precip_mm": precip[chart_start:forecast_end],
        "precip_prob": chart_probs,
        "wmo": wmo[chart_start:forecast_end],
    })


def get_weather_data(lat: float, lon: float) -> tuple[float, float, float, int, float, float, int, str] | None:
    """
    Ruft stündliche Niederschlagsdaten der letzten 24h, der nächsten 24h,
    die aktuelle Temperatur und den aktuellen Wettercode sowie tägliche Min/Max Temperaturen
    und Regenwahrscheinlichkeit aus der Open-Meteo API ab.
    Gibt ein Tuple (regen_letzte_24h_mm, regen_naechste_24h_mm, temp_c, wetter_code, temp_min, temp_max, rain_prob, rain_last_source)
    oder None bei Netzwerk-/Verarbeitungsfehlern zurück.
    """
    # Open-Meteo-Abfrage: past_days=1 (letzte 24h), forecast_days=2 (kommende 24h) sowie aktuelle & tägliche/stündliche Vorhersage
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}&current=temperature_2m,precipitation,weather_code"
        f"&hourly=temperature_2m,precipitation,precipitation_probability,weather_code"
        f"&timezone=auto&past_days=1&forecast_days=2"
        f"&daily=temperature_2m_max,temperature_2m_min"
    )
    
    try:
        logger.info(f"Rufe Wetterdaten ab: {url}")
        req = urllib.request.Request(url, headers={'User-Agent': 'GardenIrrigationDaemon/1.0'})
        data = json.loads(_http_get_bytes(req, timeout=10).decode("utf-8"))

        current = data.get("current", {})
        current_temp = float(current.get("temperature_2m", 0.0))
        weather_code = int(current.get("weather_code", 0))
        current_precipitation = float(current.get("precipitation", 0.0))
        
        # Tägliche Vorhersage für heute extrahieren
        daily = data.get("daily", {})
        daily_times = daily.get("time", [])
        temp_maxs = daily.get("temperature_2m_max", [])
        temp_mins = daily.get("temperature_2m_min", [])
        
        today_date_str = datetime.now().strftime("%Y-%m-%d")
        daily_idx = -1
        for idx, t_str in enumerate(daily_times):
            if t_str == today_date_str:
                daily_idx = idx
                break
                
        if daily_idx != -1 and daily_idx < len(temp_maxs) and daily_idx < len(temp_mins):
            temp_max = float(temp_maxs[daily_idx])
            temp_min = float(temp_mins[daily_idx])
        else:
            temp_max = current_temp + 5.0
            temp_min = current_temp - 5.0
            
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        precip = hourly.get("precipitation", [])
        precip_probs = hourly.get("precipitation_probability", [])
        hourly_temps = hourly.get("temperature_2m", [])
        hourly_wmo = hourly.get("weather_code", [])
        
        if not times or not precip:
            logger.warning("Keine stündlichen Niederschlagsdaten in der API-Antwort gefunden.")
            return 0.0, 0.0, current_temp, weather_code, temp_min, temp_max, 0, "forecast"
            
        # Finde den Index für die aktuelle Stunde
        current_idx = _find_current_index(times)
        if current_idx == -1:
            current_idx = 24
            logger.warning(f"Alle Forecast-Zeiten in Zukunft. Nutze Fallback-Index {current_idx}.")
            
        # rain_last aus Forecast (Fallback) — null-sichere Summe der Vergangenheitsstunden
        start_past_idx = max(0, current_idx - 24)
        forecast_rain_last = aggregate_rain_window(precip, start_past_idx, current_idx)

        # Regen-der-letzten-24h: Quelle über I/O sammeln, reine Politik wählt (Ticket 6xy).
        sensor_last = database.get_last_rain_measurement()
        sensor_is_fresh = False
        if sensor_last:
            try:
                sensor_age_h = (datetime.now() - datetime.fromisoformat(sensor_last["timestamp"])).total_seconds() / 3600
                sensor_is_fresh = sensor_age_h < config.RAIN_SENSOR_OFFLINE_HOURS
            except Exception:
                pass

        if sensor_is_fresh:
            sensor_sum = database.get_rain_sum_last_24h()
            measured = None
        else:
            sensor_sum = 0.0
            measured = _fetch_measured_rain_last(lat, lon)
        rain_last_24h, rain_last_source = select_rain_last(
            sensor_is_fresh, sensor_sum, measured, forecast_rain_last
        )
        if rain_last_source == "sensor":
            logger.info(f"Regenmenge aus lokalem Sensor: {rain_last_24h} mm (letzte 24h).")
        elif rain_last_source == "forecast":
            logger.warning("Gemessener Regen nicht verfügbar — nutze Forecast-Wert (degradiert).")

        # Summe nächste 24h + höchste Regenwahrscheinlichkeit (beide null-sicher, Ticket 11b/6xy)
        end_forecast_idx = min(len(precip), current_idx + 24)
        rain_next_24h = aggregate_rain_window(precip, current_idx, end_forecast_idx)
        rain_prob = max_rain_prob(precip_probs, current_idx, 24)

        # Stündliche Vorhersage ±24h (bis 48 Einträge) fürs Wetterchart
        hourly_forecast_json = build_hourly_forecast(
            times, hourly_temps, precip, precip_probs, hourly_wmo, current_idx
        )

        temp_min = round(temp_min, 1)
        temp_max = round(temp_max, 1)

        logger.info(
            f"Wetterdaten geladen - Temp: {current_temp}°C (Min: {temp_min}°C/Max: {temp_max}°C), "
            f"Code: {weather_code}, Regenwahrscheinlichkeit: {rain_prob}%, "
            f"Regen 24h: {rain_last_24h}mm, Vorhersage: {rain_next_24h}mm, "
            f"Aktuelle Niederschlag: {current_precipitation}mm"
        )

        # Event publizieren (Datenbank-Adapter und andere Abonnenten kümmern sich um Speicherung)
        _global_bus.publish(WeatherDataFetched(
            rain_last_24h, rain_next_24h, current_temp, weather_code,
            temp_min, temp_max, rain_prob,
            current_precipitation=current_precipitation,
            hourly_forecast_json=hourly_forecast_json,
            rain_last_source=rain_last_source,
        ))

        return rain_last_24h, rain_next_24h, current_temp, weather_code, temp_min, temp_max, rain_prob, rain_last_source
        
    except urllib.error.URLError as e:
        logger.error(f"Netzwerkfehler beim Abruf der Wetterdaten: {e}")
    except Exception as e:
        logger.error(f"Unerwarteter Fehler beim Verarbeiten der Wetterdaten: {e}")

    return None


def get_yesterday_temp_stats(lat: float, lon: float) -> "tuple[float, float] | None":
    """Gibt (Ø, max) der gestrigen Temperatur von Open-Meteo zurück, oder None.

    Fallback für den Gestern-Block des Tagesberichts, wenn der lokale Regensensor ausfällt.
    Nutzt die täglichen Open-Meteo-Werte (Mittel + Max) für den Vortag (`past_days=1`).
    """
    from datetime import timedelta
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&daily=temperature_2m_max,temperature_2m_mean"
        f"&timezone=auto&past_days=1&forecast_days=1"
    )
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'GardenIrrigationDaemon/1.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        daily = data.get("daily", {})
        days = daily.get("time", [])
        maxs = daily.get("temperature_2m_max", [])
        means = daily.get("temperature_2m_mean", [])
        yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
        for idx, d in enumerate(days):
            if d == yesterday:
                if (idx < len(maxs) and idx < len(means)
                        and maxs[idx] is not None and means[idx] is not None):
                    return round(float(means[idx]), 1), round(float(maxs[idx]), 1)
                break
        return None
    except Exception as e:
        logger.warning(f"Gestrige Temperatur von Open-Meteo nicht verfügbar: {e}")
        return None


def _compute_rain_next_eff(hourly_forecast_json: str) -> float:
    """Erwarteter Niederschlag der nächsten 24h: stundenweise mit Wahrscheinlichkeit gewichtet.

    Σ precip[h] * prob[h] / 100 für alle zukünftigen Stunden bis +24h.
    Bei fehlenden Daten → 0 (fail-safe Richtung Gießen).
    """
    if not hourly_forecast_json:
        return 0.0
    try:
        data = json.loads(hourly_forecast_json)
        times = data.get("times", [])
        precip = data.get("precip_mm", [])
        probs = data.get("precip_prob", [])
        if not times or not precip:
            return 0.0
        now_str = datetime.now().strftime("%Y-%m-%dT%H:00")
        total = 0.0
        future_count = 0
        for i, t in enumerate(times):
            if t >= now_str:
                if i < len(precip) and i < len(probs):
                    p = precip[i] if precip[i] is not None else 0.0
                    prob = probs[i] if probs[i] is not None else 0.0
                    total += p * prob / 100.0
                    future_count += 1
                if future_count >= 24:
                    break
        return round(total, 2)
    except Exception:
        return 0.0


def _watering_decision_from_cache(cached: dict) -> WateringDecision:
    """Berechnet eine WateringDecision aus einem gecachten Wettereintrag."""
    rain_last = cached.get("rain_last_24h_mm", 0.0)
    rain_last_source = cached.get("rain_last_source", "measured")
    hourly_json = cached.get("hourly_forecast_json") or ""
    rain_next_eff = _compute_rain_next_eff(hourly_json)
    temp_max_today = cached.get("temp_max", 0.0) or 0.0
    past_daily_temps = database.get_daily_max_temps(config.GIESSCHECK_HOT_DAYS_COUNT + 1)
    threshold = config.get_setting("RAIN_THRESHOLD_MM", config.RAIN_THRESHOLD_MM)
    return evaluate_watering(
        rain_last_mm=rain_last,
        rain_next_eff_mm=rain_next_eff,
        temp_max_today=temp_max_today,
        past_daily_temps=past_daily_temps,
        rain_last_source=rain_last_source,
        threshold_mm=float(threshold),
        hot_temp_c=config.GIESSCHECK_HOT_TEMP_C,
        heat_sensitivity=config.GIESSCHECK_HEAT_SENSITIVITY,
        hot_days_cap=config.GIESSCHECK_HOT_DAYS_COUNT,
    )


def evaluate_watering_factor() -> WateringDecision:
    """Cache-first graduierte Gieß-Entscheidung. Fallback-Kette wie ADR 0020.

    Gibt einen WateringDecision mit Faktor 0–1.0 zurück. Kein Daten → factor=1.0 (sicher gießen).
    """
    max_age = timedelta(seconds=4 * config.WEATHER_REFRESH_INTERVAL_SECONDS)
    forecast_window = timedelta(seconds=WEATHER_FORECAST_WINDOW_SECONDS)
    now = datetime.now()

    cached = database.get_last_weather()

    # 1. Frischer Cache — Live gar nicht erst holen (reine Politik: is_cache_fresh, Ticket 2jq).
    if is_cache_fresh(cached, now, max_age):
        logger.info("Gieß-Faktor aus frischem DB-Cache.")
        return _watering_decision_from_cache(cached)

    # 2. Cache veraltet/fehlend — Live-API versuchen (I/O).
    try:
        live_ok = get_weather_data(config.LATITUDE, config.LONGITUDE) is not None
    except Exception as e:
        logger.error(f"Live-Wetterabfrage fehlgeschlagen: {e}")
        live_ok = False

    # 3. Reine Quellen-Wahl: live > stale-im-Fenster > fail-safe.
    source = resolve_watering_source(cached, now, forecast_window, live_ok)
    if source == "live":
        refreshed = database.get_last_weather()
        if refreshed:
            return _watering_decision_from_cache(refreshed)
        # Live meldete Erfolg, aber kein Eintrag lesbar → wie ohne Live neu entscheiden.
        source = resolve_watering_source(cached, now, forecast_window, live_ok=False)
    if source == "stale":
        logger.warning("Live nicht erreichbar. Nutze veralteten Cache im Vorhersagefenster.")
        return _watering_decision_from_cache(cached)

    # 4. Kein verwertbarer Cache — fail-safe: voller Guss.
    logger.error("Keine Wetterdaten — Bewässerung zur Sicherheit durchgeführt.")
    return WateringDecision(
        factor=1.0,
        verdict="🚿 Voller Guss",
        reasons=["Keine Wetterdaten verfügbar — Bewässerung zur Sicherheit."],
        skip=False,
    )


def should_skip_watering() -> tuple[bool, str]:
    """Binärer Wrapper um evaluate_watering_factor() für Abwärtskompatibilität (Feature 0020).

    Gibt (skip, details) zurück. Logik identisch mit dem graduierten Faktor; skip = (factor == 0).
    """
    decision = evaluate_watering_factor()
    details = " | ".join(decision.reasons)
    if decision.skip:
        logger.info(f"Bewässerung überspringen: {details}")
        return True, details
    logger.info(f"Bewässerung freigegeben ({decision.verdict}): {details}")
    return False, details
