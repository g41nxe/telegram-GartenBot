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
    def __init__(self, schedule_name: str, details: str):
        self.schedule_name = schedule_name
        self.details = details

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
        reasons: list,
    ):
        self.schedule_name = schedule_name
        self.factor = factor
        self.duration_original = duration_original
        self.duration_scaled = duration_scaled
        self.volume_original = volume_original
        self.volume_scaled = volume_scaled
        self.reasons = reasons
