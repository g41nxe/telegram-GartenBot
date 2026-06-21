from .event_bus import Event


class WateringCycleStarted(Event):
    def __init__(self, duration: int, target_volume: int, source: str):
        self.duration = duration
        self.target_volume = target_volume
        self.source = source


class WateringCycleCompleted(Event):
    def __init__(self, duration_run: int, volume_run: float, source: str, details: str):
        self.duration_run = duration_run
        self.volume_run = volume_run
        self.source = source
        self.details = details


class WateringCycleFailed(Event):
    def __init__(self, duration_run: int, volume_run: float, source: str, details: str):
        self.duration_run = duration_run
        self.volume_run = volume_run
        self.source = source
        self.details = details


class WateringCycleTerminated(Event):
    """Gemeinsames Eltern-Ereignis für alle nicht-regulären Guss-Beendigungen."""
    def __init__(self, duration_run: int, volume_run: float, source: str, details: str):
        self.duration_run = duration_run
        self.volume_run = volume_run
        self.source = source
        self.details = details


class WateringCycleStopped(WateringCycleTerminated):
    """Manueller Stopp durch den Benutzer."""
    pass


class WateringCycleInterrupted(WateringCycleTerminated):
    """Guss-Unterbrechung durch das System (z.B. Regen)."""
    def __init__(
        self,
        duration_run: int,
        volume_run: float,
        source: str,
        details: str,
        mqtt_name: str = "",
        rain_mm: float = 0.0,
    ):
        super().__init__(duration_run, volume_run, source, details)
        self.mqtt_name = mqtt_name
        self.rain_mm = rain_mm
