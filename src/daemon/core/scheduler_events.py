from typing import Dict, Any, List
from .event_bus import Event

class DailyReportTriggered(Event):
    def __init__(self, today_str: str, report_text: str):
        self.today_str = today_str
        self.report_text = report_text

class WeatherDataFetched(Event):
    def __init__(self, rain_last_24h: float, rain_next_24h: float, current_temp: float, weather_code: int, temp_min: float, temp_max: float, rain_prob: int):
        self.rain_last_24h = rain_last_24h
        self.rain_next_24h = rain_next_24h
        self.current_temp = current_temp
        self.weather_code = weather_code
        self.temp_min = temp_min
        self.temp_max = temp_max
        self.rain_prob = rain_prob

class WateringSkipped(Event):
    def __init__(self, schedule_name: str, details: str):
        self.schedule_name = schedule_name
        self.details = details

class ScheduleFailed(Event):
    def __init__(self, schedule_name: str, details: str):
        self.schedule_name = schedule_name
        self.details = details
