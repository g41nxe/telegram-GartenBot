import json
import logging
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from .. import config
from . import database
from .mqtt_client import _global_bus
from ..core.scheduler_events import WeatherDataFetched

WEATHER_FORECAST_WINDOW_SECONDS = 86400  # Open-Meteo liefert genau 24h voraus

logger = logging.getLogger("garden_weather")

def get_weather_data(lat: float, lon: float) -> tuple[float, float, float, int, float, float, int] | None:
    """
    Ruft stündliche Niederschlagsdaten der letzten 24h, der nächsten 24h,
    die aktuelle Temperatur und den aktuellen Wettercode sowie tägliche Min/Max Temperaturen
    und Regenwahrscheinlichkeit aus der Open-Meteo API ab.
    Gibt ein Tuple (regen_letzte_24h_mm, regen_naechste_24h_mm, temp_c, wetter_code, temp_min, temp_max, rain_prob)
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
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            
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
            return 0.0, 0.0, current_temp, weather_code, temp_min, temp_max, 0
            
        # Finde den Index für die aktuelle Stunde
        current_time_str = datetime.now().strftime("%Y-%m-%dT%H:00")
        
        current_idx = -1
        for idx, t_str in enumerate(times):
            if t_str == current_time_str:
                current_idx = idx
                break
                
        # Fallback, falls die genaue Stunde nicht exakt matched (z.B. Zeitzonen-Offset)
        if current_idx == -1:
            # past_days=1 hat 24 Stunden, also sollte der heutige Tag ab Index 24 starten
            current_idx = 24
            logger.warning(f"Exakte Stunde {current_time_str} nicht gefunden. Nutze Fallback-Index {current_idx}.")
            
        # Summiere die letzten 24 Stunden vor der aktuellen Stunde
        start_past_idx = max(0, current_idx - 24)
        rain_last_24h = sum(precip[start_past_idx:current_idx])
        
        # Summiere die nächsten 24 Stunden ab der aktuellen Stunde
        end_forecast_idx = min(len(precip), current_idx + 24)
        rain_next_24h = sum(precip[current_idx:end_forecast_idx])
        
        # Berechne die maximale Regenwahrscheinlichkeit für die nächsten 24 Stunden
        if precip_probs and current_idx < len(precip_probs):
            end_prob_idx = min(len(precip_probs), current_idx + 24)
            rain_prob = max(precip_probs[current_idx:end_prob_idx])
            try:
                rain_prob = int(rain_prob)
            except (TypeError, ValueError):
                rain_prob = 0
        else:
            rain_prob = 0
            
        # Stündliche Vorhersage für die nächsten 24 Stunden ab aktueller Stunde aufbauen
        forecast_end = min(current_idx + 24, len(times))
        hourly_forecast_json = json.dumps({
            "times": times[current_idx:forecast_end],
            "temp": hourly_temps[current_idx:forecast_end],
            "precip_mm": precip[current_idx:forecast_end],
            "precip_prob": precip_probs[current_idx:forecast_end],
            "wmo": hourly_wmo[current_idx:forecast_end],
        })

        # Werte runden
        rain_last_24h = round(rain_last_24h, 2)
        rain_next_24h = round(rain_next_24h, 2)
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
        ))

        return rain_last_24h, rain_next_24h, current_temp, weather_code, temp_min, temp_max, rain_prob
        
    except urllib.error.URLError as e:
        logger.error(f"Netzwerkfehler beim Abruf der Wetterdaten: {e}")
    except Exception as e:
        logger.error(f"Unerwarteter Fehler beim Verarbeiten der Wetterdaten: {e}")

    return None

def _evaluate_skip(rain_last: float, rain_next: float) -> tuple[bool, str]:
    total_rain = rain_last + rain_next
    if total_rain >= config.RAIN_THRESHOLD_MM:
        details = (
            f"Regenschwelle überschritten: Gesamt {total_rain}mm "
            f"(Gefallen: {rain_last}mm, Erwartet: {rain_next}mm, Grenzwert: {config.RAIN_THRESHOLD_MM}mm)"
        )
        logger.info(f"Bewässerung überspringen: {details}")
        return True, details
    details = (
        f"Regen liegt unter Grenzwert: Gesamt {total_rain}mm "
        f"(Gefallen: {rain_last}mm, Erwartet: {rain_next}mm, Grenzwert: {config.RAIN_THRESHOLD_MM}mm)"
    )
    logger.info(f"Bewässerung freigegeben: {details}")
    return False, details


def should_skip_watering() -> tuple[bool, str]:
    """
    Cache-first: liest Wetterdaten aus dem DB-Cache, ruft die Live-API nur bei
    veraltetem oder fehlendem Cache ab. Fallback-Kette siehe ADR 0020.
    """
    max_age = timedelta(seconds=4 * config.WEATHER_REFRESH_INTERVAL_SECONDS)
    forecast_window = timedelta(seconds=WEATHER_FORECAST_WINDOW_SECONDS)
    now = datetime.now()

    cached = database.get_last_weather()
    cache_age = None
    if cached:
        try:
            cache_time = datetime.fromisoformat(cached["timestamp"])
            cache_age = now - cache_time
        except (KeyError, ValueError):
            cached = None

    # 1. Frischer Cache
    if cached and cache_age is not None and cache_age < max_age:
        logger.info(f"Wetter-Skip-Check nutzt DB-Cache (Alter: {cache_age}).")
        return _evaluate_skip(cached["rain_last_24h_mm"], cached["rain_next_24h_mm"])

    # 2. Cache veraltet oder fehlend — Live-API versuchen
    live_data = None
    try:
        live_data = get_weather_data(config.LATITUDE, config.LONGITUDE)
    except Exception as e:
        logger.error(f"Live-Wetterabfrage fehlgeschlagen: {e}")

    if live_data is not None:
        return _evaluate_skip(live_data[0], live_data[1])

    # 3. Live fehlgeschlagen — stale Cache nutzen falls Vorhersagefenster noch gültig
    if cached and cache_age is not None and cache_age < forecast_window:
        logger.warning(
            f"Live-Wetterabfrage nicht erreichbar. Nutze veralteten Cache (Alter: {cache_age})."
        )
        return _evaluate_skip(cached["rain_last_24h_mm"], cached["rain_next_24h_mm"])

    # 4. Kein verwertbarer Cache und kein Live-Zugriff
    logger.error("Keine Wetterdaten verfügbar (kein Cache, kein Netz). Bewässerung wird durchgeführt.")
    return False, "Keine Wetterdaten verfügbar — Bewässerung zur Sicherheit durchgeführt."
