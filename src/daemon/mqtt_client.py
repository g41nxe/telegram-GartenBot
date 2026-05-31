import json
import logging
import time
import threading
from datetime import datetime
from . import config

logger = logging.getLogger("garden_mqtt")

# Globale Variable für den aktuellen Zustand des Ventils
valve_status = {
    "state": "UNKNOWN",
    "battery": 100,
    "flow_rate": 0.0,
    "linkquality": 0,
    "last_update": None
}

# Flussmengen-Integration
active_cycle_volume = 0.0
last_flow_update_time = None

client = None
is_connected = False

# Versuche paho-mqtt zu importieren, andernfalls nutzen wir einen Mock-Modus
try:
    import paho.mqtt.client as mqtt
    HAS_PAHO = True
except ImportError:
    HAS_PAHO = False
    logger.warning("Bibliothek 'paho-mqtt' nicht installiert. Starte im Simulationsmodus (Mock Client).")

def on_connect(mqtt_client, userdata, flags, rc):
    """Callback bei erfolgreicher MQTT-Verbindung."""
    global is_connected
    if rc == 0:
        is_connected = True
        logger.info("Erfolgreich mit dem MQTT-Broker verbunden.")
        
        # Status-Topic abonnieren
        mqtt_client.subscribe(config.MQTT_VALVE_TOPIC)
        logger.info(f"Topic abonniert: {config.MQTT_VALVE_TOPIC}")
        
        # Hardwareseitiges Sicherheits-Timeout (Auto-Close/Inching) an das Ventil senden
        configure_safety_timeout()
    else:
        is_connected = False
        logger.error(f"Verbindungsfehler beim MQTT-Broker. Rückgabecode: {rc}")

def on_message(mqtt_client, userdata, msg):
    """Callback bei eingehender MQTT-Nachricht."""
    global valve_status, active_cycle_volume, last_flow_update_time
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)
        
        state = data.get("state", valve_status["state"])
        flow_rate = float(data.get("flow_rate", valve_status["flow_rate"]))
        now = datetime.now()
        
        # Durchfluss-Integration (Liter aufsummieren über Zeitdifferenz)
        if state == "ON" and valve_status["state"] == "ON" and last_flow_update_time is not None:
            elapsed_seconds = (now - last_flow_update_time).total_seconds()
            # Stabilitätsschutz gegen extreme Time-Gaps (max. 60 Sek annehmen)
            if 0 < elapsed_seconds < 60:
                added_liters = flow_rate * (elapsed_seconds / 60.0)
                active_cycle_volume += added_liters
                logger.info(f"Durchfluss-Messer: +{added_liters:.3f}l (Gesamt: {active_cycle_volume:.2f} Liter)")
        
        if state == "ON" and last_flow_update_time is None:
            active_cycle_volume = 0.0
            
        last_flow_update_time = now
        if state == "OFF":
            last_flow_update_time = None
            
        # Status aktualisieren
        valve_status["state"] = state
        valve_status["battery"] = data.get("battery", valve_status["battery"])
        valve_status["flow_rate"] = flow_rate
        valve_status["linkquality"] = data.get("linkquality", valve_status["linkquality"])
        valve_status["last_update"] = now.isoformat()
        
    except Exception as e:
        logger.error(f"Fehler beim Parsen der MQTT-Nachricht: {e}")

def configure_safety_timeout():
    """Konfiguriert das hardwareseitige Auto-Close-Sicherheitslimit (Inching) auf dem Ventil."""
    global client
    if not is_connected or client is None:
        return
        
    set_topic = f"{config.MQTT_VALVE_TOPIC}/set"
    safety_seconds = config.SAFETY_TIMEOUT_MINUTES * 60
    payload = {
        "inching_control": {
            "inch_mode": "ON",
            "inch_time": safety_seconds
        }
    }
    
    try:
        client.publish(set_topic, json.dumps(payload), retain=True)
        logger.info(f"Hardware-Sicherheits-Timeout ({config.SAFETY_TIMEOUT_MINUTES} Min) an das Ventil gesendet.")
    except Exception as e:
        logger.error(f"Fehler beim Senden des Sicherheits-Timeouts: {e}")

# --- Simulator für Offline-Betrieb (Mock-Modus) ---

def _mock_flow_loop():
    """Hintergrundthread, der im Simulationsmodus den Durchfluss und Literzuwachs simuliert."""
    global active_cycle_volume, valve_status
    logger.info("Simulierter Durchfluss-Loop gestartet.")
    
    while True:
        try:
            if valve_status["state"] == "ON":
                # Simuliere einen konstanten Durchfluss von 5.0 L/min
                valve_status["flow_rate"] = 5.0
                valve_status["linkquality"] = 135
                # Zuwachs um 5.0 Liter / 60 Sekunden = 0.083 Liter pro Sekunde
                active_cycle_volume += 5.0 * (1.0 / 60.0)
                valve_status["last_update"] = datetime.now().isoformat()
            else:
                valve_status["flow_rate"] = 0.0
            
            time.sleep(1)
        except Exception:
            pass

# --- API Methoden für den Daemon ---

def start_client():
    """Initialisiert und startet den MQTT-Client."""
    global client, is_connected
    if not HAS_PAHO:
        # Simulationsmodus initialisieren
        is_connected = True
        valve_status["state"] = "OFF"
        valve_status["last_update"] = datetime.now().isoformat()
        
        # Simulierten Durchfluss starten
        t = threading.Thread(target=_mock_flow_loop, daemon=True)
        t.start()
        logger.info("Simulierter MQTT-Client inklusive Durchfluss-Wächter erfolgreich gestartet.")
        return True
        
    try:
        client = mqtt.Client()
        client.on_connect = on_connect
        client.on_message = on_message
        
        client.connect_async(config.MQTT_BROKER_HOST, config.MQTT_BROKER_PORT, keepalive=60)
        client.loop_start()
        logger.info(f"MQTT-Client gestartet. Verbinde mit {config.MQTT_BROKER_HOST}:{config.MQTT_BROKER_PORT}...")
        return True
    except Exception as e:
        logger.error(f"Fehler beim Senden des MQTT-Befehls: {e}")
        return False

def get_valve_status() -> dict:
    """Gibt den aktuellen Status des Ventils zurück."""
    return valve_status

def reset_active_volume():
    """Setzt den aktiven Wasservolumenzähler zurück."""
    global active_cycle_volume, last_flow_update_time
    active_cycle_volume = 0.0
    last_flow_update_time = datetime.now() if valve_status["state"] == "ON" else None
    logger.info("Aktiv-Wasservolumenzähler zurückgesetzt.")

def get_active_volume() -> float:
    """Gibt die aktuell geflossene Wassermenge in Litern zurück."""
    global active_cycle_volume
    return round(active_cycle_volume, 2)

def open_valve() -> bool:
    """Sendet den Befehl zum Öffnen des Ventils."""
    global client, valve_status
    logger.info("Sende Befehl: Ventil ÖFFNEN")
    
    reset_active_volume()
    
    if not HAS_PAHO:
        valve_status["state"] = "ON"
        valve_status["last_update"] = datetime.now().isoformat()
        return True
        
    if not is_connected or client is None:
        logger.warning("Keine Verbindung zum MQTT-Broker. Befehl konnte nicht gesendet werden.")
        return False
        
    try:
        set_topic = f"{config.MQTT_VALVE_TOPIC}/set"
        client.publish(set_topic, json.dumps({"state": "ON"}))
        return True
    except Exception as e:
        logger.error(f"Fehler beim Senden des Öffnen-Befehls: {e}")
        return False

def close_valve() -> bool:
    """Sendet den Befehl zum Schließen des Ventils."""
    global client, valve_status
    logger.info("Sende Befehl: Ventil SCHLIESSEN")
    
    if not HAS_PAHO:
        valve_status["state"] = "OFF"
        valve_status["last_update"] = datetime.now().isoformat()
        return True
        
    if not is_connected or client is None:
        logger.warning("Keine Verbindung zum MQTT-Broker. Befehl konnte nicht gesendet werden.")
        return False
        
    try:
        set_topic = f"{config.MQTT_VALVE_TOPIC}/set"
        client.publish(set_topic, json.dumps({"state": "OFF"}))
        return True
    except Exception as e:
        logger.error(f"Fehler beim Senden des Schließen-Befehls: {e}")
        return False

def is_broker_connected() -> bool:
    """Gibt zurück, ob der Client mit dem MQTT-Broker verbunden ist."""
    global is_connected
    return is_connected
