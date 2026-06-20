from .event_bus import Event


class RainSensorMeasured(Event):
    """Fired when a rain sensor measurement arrives via MQTT."""
    def __init__(
        self,
        rainlevel_mm: float,
        raintotal_mm: float,
        temperature_c: float,
        battery_pct: int,
        is_raining: bool,
    ):
        self.rainlevel_mm = rainlevel_mm
        self.raintotal_mm = raintotal_mm
        self.temperature_c = temperature_c
        self.battery_pct = battery_pct
        self.is_raining = is_raining


class RainSensorInactivityAlertTriggered(Event):
    def __init__(self, hours_silent: float, timeout_hours: float):
        self.hours_silent = hours_silent
        self.timeout_hours = timeout_hours


class RainSensorInactivityAlertResolved(Event):
    pass
