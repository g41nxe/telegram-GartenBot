from .event_bus import Event


class NebelIntervalStarted(Event):
    """Ein Nebel-Fenster wurde gestartet (geplant oder Sofort-Nebel)."""
    def __init__(self, mqtt_name: str, source: str, end_time: str):
        self.mqtt_name = mqtt_name
        self.source = source
        self.end_time = end_time


class NebelIntervalEnded(Event):
    """Ein Nebel-Fenster ist beendet (Endzeit erreicht oder manuell gestoppt)."""
    def __init__(self, mqtt_name: str, source: str, duration_run: int, burst_count: int, details: str):
        self.mqtt_name = mqtt_name
        self.source = source
        self.duration_run = duration_run
        self.burst_count = burst_count
        self.details = details
