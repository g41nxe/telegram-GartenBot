from typing import Dict, Any, List
from .event_bus import Event

class DailyReportTriggered(Event):
    def __init__(self, today_str: str, report_text: str):
        self.today_str = today_str
        self.report_text = report_text

class WeatherDataFetched(Event):
    def __init__(self, rain_last_24h: float, rain_next_24h: float, current_temp: float, weather_code: int, temp_min: float, temp_max: float, rain_prob: int, current_precipitation: float = 0.0, hourly_forecast_json: str = "", rain_last_source: str = "measured"):
        self.rain_last_24h = rain_last_24h
        self.rain_next_24h = rain_next_24h
        self.current_temp = current_temp
        self.weather_code = weather_code
        self.temp_min = temp_min
        self.temp_max = temp_max
        self.rain_prob = rain_prob
        self.current_precipitation = current_precipitation
        self.hourly_forecast_json = hourly_forecast_json
        self.rain_last_source = rain_last_source

class WateringSkipped(Event):
    def __init__(self, schedule_name: str, details: str, schedule_id: int = None):
        self.schedule_name = schedule_name
        self.details = details
        self.schedule_id = schedule_id


class WateringRainWarning(Event):
    """Guss-Vorwarnung (Feature 0034): ~5 Min vor einem geplanten Guss, der regenbedingt
    übersprungen oder reduziert würde. Trägt Original- *und* reduzierte Zielwerte (samt
    Faktor) sowie das Datum des geplanten Laufs, damit der Nutzer sieht, worauf angepasst
    würde, und die Reduzierung/das Überspringen für genau diesen Lauf übersteuern kann
    (Regen-Übersteuerung)."""

    def __init__(self, schedule_id: int, schedule_name: str, time: str, run_date: str,
                 valve_names: list, duration_original: int, volume_original: int, reasons: list,
                 duration_scaled: int = 0, volume_scaled: int = 0, factor: float = 0.0):
        self.schedule_id = schedule_id
        self.schedule_name = schedule_name
        self.time = time
        self.run_date = run_date
        self.valve_names = valve_names
        self.duration_original = duration_original
        self.volume_original = volume_original
        # Reduzierte Zielwerte + Faktor, damit die Vorwarnung anzeigen kann, worauf
        # angepasst würde (factor == 0 ⇒ kompletter Skip).
        self.duration_scaled = duration_scaled
        self.volume_scaled = volume_scaled
        self.factor = factor
        self.reasons = reasons

class ScheduleFailed(Event):
    def __init__(self, schedule_name: str, details: str):
        self.schedule_name = schedule_name
        self.details = details

class WateringScaled(Event):
    def __init__(
        self,
        schedule_name: str,
        factor: float,
        duration_original: int,
        duration_scaled: int,
        volume_original: int,
        volume_scaled: int,
        reasons: list[str],
        schedule_id: int = None,
    ):
        self.schedule_name = schedule_name
        self.factor = factor
        self.duration_original = duration_original
        self.duration_scaled = duration_scaled
        self.volume_original = volume_original
        self.volume_scaled = volume_scaled
        self.reasons = reasons
        self.schedule_id = schedule_id
