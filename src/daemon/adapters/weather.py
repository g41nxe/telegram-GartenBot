import json
import logging
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from .. import config
from .mqtt_client import _global_bus
from ..core.scheduler_events import WeatherDataFetched

logger = logging.getLogger("garden_weather")

def get_weather_data(lat: float, lon: float) -> tuple[float, float, float, int, float, float, int]:
    """
    Ruft stündliche Niederschlagsdaten der letzten 24h, der nächsten 24h,
    die aktuelle Temperatur und den aktuellen Wettercode sowie tägliche Min/Max Temperaturen
    und Regenwahrscheinlichkeit aus der Open-Meteo API ab.
    Gibt ein Tuple (regen_letzte_24h_mm, regen_naechste_24h_mm, temp_c, wetter_code, temp_min, temp_max, rain_prob) zurück.
    """
    # Open-Meteo-Abfrage: past_days=1 (letzte 24h), forecast_days=2 (kommende 24h) sowie aktuelle & tägliche/stündliche Vorhersage
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}&current=temperature_2m,weather_code"
        f"&hourly=precipitation,precipitation_probability&timezone=auto&past_days=1&forecast_days=2"
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
            
        # Werte runden
        rain_last_24h = round(rain_last_24h, 2)
        rain_next_24h = round(rain_next_24h, 2)
        temp_min = round(temp_min, 1)
        temp_max = round(temp_max, 1)
        
        logger.info(
            f"Wetterdaten geladen - Temp: {current_temp}°C (Min: {temp_min}°C/Max: {temp_max}°C), "
            f"Code: {weather_code}, Regenwahrscheinlichkeit: {rain_prob}%, "
            f"Regen 24h: {rain_last_24h}mm, Vorhersage: {rain_next_24h}mm"
        )
        
        # Event publizieren (Datenbank-Adapter und andere Abonnenten kümmern sich um Speicherung)
        _global_bus.publish(WeatherDataFetched(rain_last_24h, rain_next_24h, current_temp, weather_code, temp_min, temp_max, rain_prob))
        
        return rain_last_24h, rain_next_24h, current_temp, weather_code, temp_min, temp_max, rain_prob
        
    except urllib.error.URLError as e:
        logger.error(f"Netzwerkfehler beim Abruf der Wetterdaten: {e}")
    except Exception as e:
        logger.error(f"Unerwarteter Fehler beim Verarbeiten der Wetterdaten: {e}")
        
    # Im Fehlerfall geben wir Fallback-Werte zurück, da die DB-Kopplung aufgehoben wurde.
    return 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0

def should_skip_watering() -> tuple[bool, str]:
    """
    Prüft, ob die Summe aus gefallendem Regen (letzte 24h) und
    erwartetem Regen (nächste 24h) den konfigurierten Schwellenwert überschreitet.
    Gibt ein Tuple (should_skip, details_text) zurück.
    """
    rain_last, rain_next, _, _, _, _, _ = get_weather_data(config.LATITUDE, config.LONGITUDE)
    total_rain = rain_last + rain_next
    
    if total_rain >= config.RAIN_THRESHOLD_MM:
        details = (
            f"Regenschwelle überschritten: Gesamt {total_rain}mm "
            f"(Gefallen: {rain_last}mm, Erwartet: {rain_next}mm, Grenzwert: {config.RAIN_THRESHOLD_MM}mm)"
        )
        logger.info(f"Bewässerung überspringen: {details}")
        return True, details
    else:
        details = (
            f"Regen liegt unter Grenzwert: Gesamt {total_rain}mm "
            f"(Gefallen: {rain_last}mm, Erwartet: {rain_next}mm, Grenzwert: {config.RAIN_THRESHOLD_MM}mm)"
        )
        logger.info(f"Bewässerung freigegeben: {details}")
        return False, details
