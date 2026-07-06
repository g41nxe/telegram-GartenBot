import os
import logging
from pathlib import Path

logger = logging.getLogger("garden_config")

_ROOT = Path(__file__).resolve().parent.parent.parent
_GARDEN_CONF_PATH = _ROOT / "config" / "garden.conf"
_ENV_PATH = _ROOT / ".env"

# Schlüssel, die beim Programmstart in der Shell-Umgebung vorhanden waren.
# Diese werden durch keine Konfigurationsdatei überschrieben (Shell > .env > garden.conf).
_SHELL_ENV_KEYS = frozenset(os.environ.keys())


def _load_file(path: Path, override: bool) -> None:
    """
    Lädt KEY=VALUE-Paare aus einer Konfigurationsdatei in os.environ.
    override=False → setdefault (vorhandene Einträge bleiben unberührt)
    override=True  → direktes Assignment, respektiert aber Shell-Env-Schlüssel
    """
    if not path.exists():
        logger.warning(f"Konfigurationsdatei nicht gefunden: {path}. Nutze Fallback-Werte.")
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key, val = key.strip(), val.strip()
                    if override:
                        if key not in _SHELL_ENV_KEYS:
                            os.environ[key] = val
                    else:
                        os.environ.setdefault(key, val)
        logger.info(f"Konfiguration geladen aus: {path}")
    except Exception as e:
        logger.error(f"Fehler beim Lesen von {path}: {e}")


# Lade-Reihenfolge: garden.conf (Defaults) → .env (überschreibt, außer Shell-Env)
# Priorität: Shell-Env > .env > garden.conf
_load_file(_GARDEN_CONF_PATH, override=False)
_load_file(_ENV_PATH, override=True)

# Konfigurationswerte auslesen und Standardwerte festlegen
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Erlaubte User-IDs als Liste von Integern konvertieren
allowed_ids_raw = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
TELEGRAM_ALLOWED_USER_IDS = []
if allowed_ids_raw:
    try:
        TELEGRAM_ALLOWED_USER_IDS = [int(uid.strip()) for uid in allowed_ids_raw.split(",") if uid.strip()]
    except ValueError:
        logger.error("TELEGRAM_ALLOWED_USER_IDS enthält ungültige Zeichen. IDs müssen Nummern sein.")

MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "127.0.0.1")
try:
    MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))
except ValueError:
    MQTT_BROKER_PORT = 1883

MQTT_VALVE_TOPIC = os.getenv("MQTT_VALVE_TOPIC", "zigbee2mqtt/garden_valve")

try:
    LATITUDE = float(os.getenv("LATITUDE", "0.0"))
    LONGITUDE = float(os.getenv("LONGITUDE", "0.0"))
except ValueError:
    LATITUDE = 0.0
    LONGITUDE = 0.0

try:
    RAIN_THRESHOLD_MM = float(os.getenv("RAIN_THRESHOLD_MM", "3.0"))
except ValueError:
    RAIN_THRESHOLD_MM = 3.0

# --- Gießcheck-Empfehlung (graduierte Gieß-Steuerung, ADR 0031) ---
try:
    GIESSCHECK_HOT_TEMP_C = float(os.getenv("GIESSCHECK_HOT_TEMP_C", "25.0"))
except ValueError:
    GIESSCHECK_HOT_TEMP_C = 25.0

try:
    GIESSCHECK_HEAT_SENSITIVITY = float(os.getenv("GIESSCHECK_HEAT_SENSITIVITY", "0.5"))
except ValueError:
    GIESSCHECK_HEAT_SENSITIVITY = 0.5

try:
    GIESSCHECK_HOT_DAYS_COUNT = int(os.getenv("GIESSCHECK_HOT_DAYS_COUNT", "3"))
except ValueError:
    GIESSCHECK_HOT_DAYS_COUNT = 3

try:
    SAFETY_TIMEOUT_MINUTES = int(os.getenv("SAFETY_TIMEOUT_MINUTES", "30"))
except ValueError:
    SAFETY_TIMEOUT_MINUTES = 30

try:
    BATTERY_WARNING_THRESHOLD = int(os.getenv("BATTERY_WARNING_THRESHOLD", "20"))
except ValueError:
    BATTERY_WARNING_THRESHOLD = 20

# Vorlaufzeit der Guss-Vorwarnung vor einem geplanten Guss (Feature 0034, ADR 0035).
try:
    RAIN_WARNING_LEAD_MINUTES = int(os.getenv("RAIN_WARNING_LEAD_MINUTES", "5"))
except ValueError:
    RAIN_WARNING_LEAD_MINUTES = 5

try:
    FLOW_TIME_GAP_CAP_SECONDS = int(os.getenv("FLOW_TIME_GAP_CAP_SECONDS", "60"))
except ValueError:
    FLOW_TIME_GAP_CAP_SECONDS = 60

try:
    WEATHER_REFRESH_INTERVAL_SECONDS = int(os.getenv("WEATHER_REFRESH_INTERVAL_SECONDS", "1800"))
except ValueError:
    WEATHER_REFRESH_INTERVAL_SECONDS = 1800

DAILY_REPORT_TIME = os.getenv("DAILY_REPORT_TIME", "08:00")

# --- Nebel-Intervall (Terrassen-Kühlung, Feature 0032) ---
try:
    NEBEL_ON_SECONDS = int(os.getenv("NEBEL_ON_SECONDS", "20"))
except ValueError:
    NEBEL_ON_SECONDS = 20
try:
    NEBEL_PAUSE_MINUTES = int(os.getenv("NEBEL_PAUSE_MINUTES", "5"))
except ValueError:
    NEBEL_PAUSE_MINUTES = 5
try:
    NEBEL_MANUAL_MAX_MINUTES = int(os.getenv("NEBEL_MANUAL_MAX_MINUTES", "120"))
except ValueError:
    NEBEL_MANUAL_MAX_MINUTES = 120
try:
    NEBEL_VALVE_FAIL_SAFE_SECONDS = int(os.getenv("NEBEL_VALVE_FAIL_SAFE_SECONDS", "90"))
except ValueError:
    NEBEL_VALVE_FAIL_SAFE_SECONDS = 90

# --- Unerwartete Ventilöffnung ---
UNEXPECTED_VALVE_ALERT_ENABLED = os.getenv("UNEXPECTED_VALVE_ALERT_ENABLED", "true").lower() == "true"

# --- Inaktivitäts-Watchdog ---
WATCHDOG_ENABLED = os.getenv("WATCHDOG_ENABLED", "true").lower() == "true"
try:
    WATCHDOG_VALVE_TIMEOUT_HOURS = float(os.getenv("WATCHDOG_VALVE_TIMEOUT_HOURS", "24"))
except ValueError:
    WATCHDOG_VALVE_TIMEOUT_HOURS = 24.0

GITHUB_PAT = os.getenv("GITHUB_PAT", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")

# --- Regensensor-Einstellungen (Aqua Scope RANWIE01) ---
# Topic-Filter mit Wildcard, da der Sensor auf AQS/<geräte-id>/stat publisht.
RAIN_SENSOR_TOPIC = os.getenv("RAIN_SENSOR_TOPIC", "AQS/+/stat")
try:
    RAIN_SENSOR_THRESHOLD_MM = float(os.getenv("RAIN_SENSOR_THRESHOLD_MM", "0.1"))
except ValueError:
    RAIN_SENSOR_THRESHOLD_MM = 0.1
try:
    RAIN_SENSOR_OFFLINE_HOURS = float(os.getenv("RAIN_SENSOR_OFFLINE_HOURS", "18"))
except ValueError:
    RAIN_SENSOR_OFFLINE_HOURS = 18.0
# Auflösung der Kippwaage: ein rainlevel/raintotal-Tick = 0,5 mm Wassersäule.
try:
    RAIN_SENSOR_MM_PER_TICK = float(os.getenv("RAIN_SENSOR_MM_PER_TICK", "0.5"))
except ValueError:
    RAIN_SENSOR_MM_PER_TICK = 0.5
# `battery` ist verbrauchte Kapazität in mAs. Rest-% = 100·(1 − verbraucht/Kapazität).
# Standard: 2× AAA LiFeS2 (Energizer L92), nutzbare Kapazität bis zur Geräte-Abschaltung
# (2,9 V Pack = 1,45 V/Zelle) ≈ 1200 mAh laut Hersteller-Batteriereport (~2,3 Jahre Laufzeit).
try:
    RAIN_SENSOR_BATTERY_CAPACITY_MAH = float(os.getenv("RAIN_SENSOR_BATTERY_CAPACITY_MAH", "1200"))
except ValueError:
    RAIN_SENSOR_BATTERY_CAPACITY_MAH = 1200.0

# --- Kamera-Einstellungen ---
try:
    CAMERA_RECEIVER_PORT = int(os.getenv("CAMERA_RECEIVER_PORT", "8080"))
except ValueError:
    CAMERA_RECEIVER_PORT = 8080

CAMERA_IMAGE_DIR = os.getenv("CAMERA_IMAGE_DIR", "data/camera")

try:
    CAMERA_CLEANUP_DAYS = int(os.getenv("CAMERA_CLEANUP_DAYS", "30"))
except ValueError:
    CAMERA_CLEANUP_DAYS = 30

try:
    CAMERA_MAX_UPLOAD_BYTES = int(os.getenv("CAMERA_MAX_UPLOAD_BYTES", "512000"))
except ValueError:
    CAMERA_MAX_UPLOAD_BYTES = 512000

try:
    TIMED_PHOTO_TOLERANCE_MINUTES = int(os.getenv("TIMED_PHOTO_TOLERANCE_MINUTES", "5"))
except ValueError:
    TIMED_PHOTO_TOLERANCE_MINUTES = 5

try:
    CAMERA_AFTER_GUSS_OFFSET_MINUTES = int(os.getenv("CAMERA_AFTER_GUSS_OFFSET_MINUTES", "2"))
except ValueError:
    CAMERA_AFTER_GUSS_OFFSET_MINUTES = 2


VERSION_FILE = _ROOT / "VERSION"


def read_version() -> str:
    """Liest die installierte Versionskennung aus der VERSION-Datei (oder 'unbekannt').

    Einzige Quelle für die Version — von /update-Anzeige und Diagnose-Steckbrief genutzt.
    """
    try:
        if VERSION_FILE.exists():
            return VERSION_FILE.read_text().strip()
    except Exception:
        pass
    return "unbekannt"


def get_setting(name: str, default=None):
    """Liest einen Konfigurationswert — DB-Override hat Vorrang vor Modulkonstante."""
    try:
        from .adapters import database
        db_val = database.get_metadata(f"setting_{name}")
        if db_val is not None:
            if isinstance(default, float):
                return float(db_val)
            if isinstance(default, int):
                return int(db_val)
            return db_val
    except Exception as e:
        logger.warning(f"get_setting({name!r}): DB-Zugriff fehlgeschlagen, verwende Modulkonstante: {e}")
    import sys
    mod = sys.modules[__name__]
    if hasattr(mod, name):
        return getattr(mod, name)
    return default


def set_setting(name: str, value) -> None:
    """Speichert einen Laufzeit-Override für einen Konfigurationswert in der DB."""
    from .adapters import database
    database.set_metadata(f"setting_{name}", str(value))


def reset_setting(name: str) -> None:
    """Entfernt den DB-Override — der Wert aus garden.conf/.env greift wieder."""
    from .adapters import database
    database.delete_metadata(f"setting_{name}")
