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
    """Wird gefeuert, wenn ein Upload einen Aufnahme-Zeitpunkt erfüllt hat (ADR 0040).

    `target_dt` und `captured_at` tragen den Aufnahme-Verzug mit: Die Bildunterschrift nennt
    ihn, und die Kamera-Überwachung bewertet ihn (ADR 0041).
    """
    def __init__(self, wish_name: str, file_path: str, caption: str,
                 target_dt=None, captured_at=None, mac_address: str = None):
        self.wish_name = wish_name
        self.file_path = file_path
        self.caption = caption
        self.target_dt = target_dt
        self.captured_at = captured_at
        self.mac_address = mac_address


class CameraDelayAlertTriggered(Event):
    """Die Garten-Kamera erfüllt ihre Aufnahme-Zeitpunkte nicht mehr (ADR 0041).

    Zweite Alarmklasse der Kamera-Überwachung neben der Inaktivität. Sie hat **zwei Gründe**,
    die verschiedene Krankheiten benennen — der Text der Warnung muss ihnen folgen:

    - `grund="verzug"`: Die Kamera **war da**, aber zu spät (`verzug_minuten` gesetzt). Deutet
      auf scheiternde Zyklen hin — schwaches WLAN, schwacher Akku.
    - `grund="verpasst"`: Der Aufnahme-Zeitpunkt bekam **gar kein Bild** (`zeitpunkte` nennt sie).
      Das heißt zwingend, dass die Kamera über das ganze Fenster **stumm** war — es gibt keinen
      Verzug, den man messen könnte.

    Der Inaktivitäts-Watchdog sieht beides nicht: Beim Verzug bleibt `last_seen` frisch, und ein
    verpasster Zeitpunkt fällt lange vor seinem Timeout auf (bei 4 h Schlafintervall: 12 h).
    """
    def __init__(self, mac_address: str, wish_name: str, grund: str, schwelle_minuten: int,
                 verzug_minuten: float = None, zeitpunkte: list = None):
        self.mac_address = mac_address
        self.wish_name = wish_name
        self.grund = grund
        self.schwelle_minuten = schwelle_minuten
        self.verzug_minuten = verzug_minuten
        self.zeitpunkte = zeitpunkte or []


class CameraDelayAlertResolved(Event):
    """Die Garten-Kamera trifft ihre Aufnahme-Zeitpunkte wieder (Entwarnung)."""
    def __init__(self, mac_address: str, wish_name: str):
        self.mac_address = mac_address
        self.wish_name = wish_name


class TimedPhotoDeliveryFailed(Event):
    """Der Versand eines erfüllenden Fotos ist gescheitert (Telegram nicht erreichbar).

    Der Aufnahme-Zeitpunkt wird beim Empfang sofort als zugestellt vermerkt — sonst würde
    jeder weitere Upload dasselbe Foto erneut senden. Scheitert der Versand, muss dieser
    Vermerk zurückgenommen werden, damit der nächste Upload den Zeitpunkt erneut erfüllt.
    Ohne diesen Rückweg wäre das Bild endgültig verloren — genau der stille Verlust, den
    ADR 0040 beseitigt.
    """
    def __init__(self, mac_address: str, target_dt):
        self.mac_address = mac_address
        self.target_dt = target_dt
