import os
import logging
from pathlib import Path

# Logger initialisieren
logger = logging.getLogger("garden_config")

def _load_env_file():
    """Lädt Variablen aus einer .env-Datei im Projekt-Root, falls diese existiert."""
    root_dir = Path(__file__).resolve().parent.parent.parent
    env_path = root_dir / ".env"
    
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        # Setze nur, wenn noch nicht in os.environ vorhanden
                        os.environ.setdefault(key.strip(), val.strip())
            logger.info("Konfiguration erfolgreich aus .env geladen.")
        except Exception as e:
            logger.error(f"Fehler beim Lesen der .env-Datei: {e}")

# .env-Datei parsen
_load_env_file()

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

try:
    SAFETY_TIMEOUT_MINUTES = int(os.getenv("SAFETY_TIMEOUT_MINUTES", "30"))
except ValueError:
    SAFETY_TIMEOUT_MINUTES = 30

try:
    BATTERY_WARNING_THRESHOLD = int(os.getenv("BATTERY_WARNING_THRESHOLD", "20"))
except ValueError:
    BATTERY_WARNING_THRESHOLD = 20

try:
    FLOW_TIME_GAP_CAP_SECONDS = int(os.getenv("FLOW_TIME_GAP_CAP_SECONDS", "60"))
except ValueError:
    FLOW_TIME_GAP_CAP_SECONDS = 60

try:
    WEATHER_REFRESH_INTERVAL_SECONDS = int(os.getenv("WEATHER_REFRESH_INTERVAL_SECONDS", "3600"))
except ValueError:
    WEATHER_REFRESH_INTERVAL_SECONDS = 3600

DAILY_REPORT_TIME = os.getenv("DAILY_REPORT_TIME", "08:00")
