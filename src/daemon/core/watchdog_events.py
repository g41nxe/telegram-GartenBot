from .event_bus import Event


class InactivityAlertTriggered(Event):
    def __init__(self, device_name: str, valve_id: int, hours_silent: float, timeout_hours: float):
        self.device_name = device_name
        self.valve_id = valve_id
        self.hours_silent = hours_silent
        self.timeout_hours = timeout_hours


class InactivityAlertResolved(Event):
    def __init__(self, device_name: str, valve_id: int):
        self.device_name = device_name
        self.valve_id = valve_id
