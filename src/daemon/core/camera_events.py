from src.daemon.core.event_bus import Event

class CameraImageReceived(Event):
    """Wird gefeuert, wenn ein neues Bild von einer Kamera erfolgreich empfangen und gespeichert wurde."""
    def __init__(self, mac_address: str, wish_name: str, file_path: str):
        self.mac_address = mac_address
        self.wish_name = wish_name
        self.file_path = file_path

class CameraInactivityAlertTriggered(Event):
    """Wird gefeuert, wenn eine Kamera ihr maximales Sendeintervall überschritten hat (Watchdog)."""
    def __init__(self, mac_address: str, wish_name: str, seconds_silent: int, timeout_seconds: int):
        self.mac_address = mac_address
        self.wish_name = wish_name
        self.seconds_silent = seconds_silent
        self.timeout_seconds = timeout_seconds

class CameraInactivityAlertResolved(Event):
    """Wird gefeuert, wenn sich eine als inaktiv gemeldete Kamera wieder meldet (Entwarnung)."""
    def __init__(self, mac_address: str, wish_name: str):
        self.mac_address = mac_address
        self.wish_name = wish_name

class CameraRegistered(Event):
    """Wird gefeuert, wenn eine Kamera erfolgreich gekoppelt (registriert) wurde."""
    def __init__(self, mac_address: str, wish_name: str):
        self.mac_address = mac_address
        self.wish_name = wish_name

class TimedPhotoCaptured(Event):
    """Wird gefeuert, wenn ein Upload einem Aufnahme-Zeitpunkt zugeordnet werden konnte."""
    def __init__(self, wish_name: str, file_path: str, caption: str):
        self.wish_name = wish_name
        self.file_path = file_path
        self.caption = caption
