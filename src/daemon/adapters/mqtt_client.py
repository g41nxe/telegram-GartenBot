import json
import logging
import time
import threading
from datetime import datetime
from typing import Any, Dict, Optional
from .. import config
from ..core.event_bus import Event, EventBus

logger = logging.getLogger("garden_mqtt")

# --- Events ---

class ValveStatusReported(Event):
    """Event, das gefeuert wird, wenn ein neuer Ventil-Zustand empfangen wird."""
    def __init__(self, state: str, flow_rate: float, battery: int, linkquality: int, valve_abnormal_state: str = "normal"):
        self.state = state
        self.flow_rate = flow_rate
        self.battery = battery
        self.linkquality = linkquality
        self.valve_abnormal_state = valve_abnormal_state

class DeviceJoinedEvent(Event):
    """Event, das gefeuert wird, wenn ein neues Zigbee-Gerät beigetreten ist."""
    def __init__(self, ieee_address: str):
        self.ieee_address = ieee_address

# --- Globale abwärtskompatible Zustände ---

valve_status = {
    "state": "UNKNOWN",
    "battery": 100,
    "flow_rate": 0.0,
    "linkquality": 0,
    "valve_abnormal_state": "normal",
    "last_update": None
}

bridge_status = "offline"

# --- Abwärtskompatibles on_message ---

def on_message(client, userdata, msg):
    """Callback bei eingehender MQTT-Nachricht (global und abwärtskompatibel)."""
    global valve_status, bridge_status
    try:
        payload = msg.payload.decode("utf-8")
        
        # Bridge-Status-Nachrichten: Kann reiner Text (alt) oder ein JSON-Objekt {"state": "online"} (neu) sein
        if hasattr(msg, "topic") and msg.topic == "zigbee2mqtt/bridge/state":
            raw_payload = payload.strip()
            if raw_payload.startswith("{") and raw_payload.endswith("}"):
                try:
                    state_json = json.loads(raw_payload)
                    bridge_status = state_json.get("state", "offline").lower()
                except Exception:
                    bridge_status = "offline"
            else:
                bridge_status = raw_payload.lower()
            logger.info(f"Mittelweg-Dienst Status empfangen: {bridge_status}")
            return
            
        data = json.loads(payload)
        
        state = data.get("state", valve_status["state"])
        flow_rate = float(data.get("flow_rate", valve_status["flow_rate"]))
        now = datetime.now()
        
        # Status aktualisieren
        valve_status["state"] = state
        valve_status["battery"] = data.get("battery", valve_status["battery"])
        valve_status["flow_rate"] = flow_rate
        valve_status["linkquality"] = data.get("linkquality", valve_status["linkquality"])
        valve_status["valve_abnormal_state"] = data.get("valve_abnormal_state", valve_status.get("valve_abnormal_state", "normal"))
        valve_status["last_update"] = now.isoformat()
        
    except Exception as e:
        logger.error(f"Fehler beim Parsen der MQTT-Nachricht: {e}")

# --- Base Interface ---

class MqttClient:
    """Basis-Interface (Seam) für den MQTT-Transport."""
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus

    def connect(self) -> bool:
        raise NotImplementedError

    def disconnect(self):
        raise NotImplementedError

    def publish(self, topic: str, payload: str, retain: bool = False) -> bool:
        raise NotImplementedError

    def subscribe(self, topic: str) -> bool:
        raise NotImplementedError

    def is_connected(self) -> bool:
        raise NotImplementedError

    def get_valve_status(self) -> Dict[str, Any]:
        return valve_status

    def get_bridge_status(self) -> str:
        return bridge_status

# --- Production Adapter (Paho-MQTT) ---

try:
    import paho.mqtt.client as mqtt
    HAS_PAHO = True
except ImportError:
    HAS_PAHO = False
    logger.warning("Bibliothek 'paho-mqtt' nicht installiert. Starte im Simulationsmodus (Mock Client).")

class PahoMqttAdapter(MqttClient):
    """Echte MQTT-Kommunikation unter Verwendung von paho-mqtt."""
    def __init__(self, event_bus: EventBus):
        super().__init__(event_bus)
        self._connected = False
        self._client: Optional[mqtt.Client] = None

    def connect(self) -> bool:
        if not HAS_PAHO:
            logger.error("paho-mqtt ist nicht verfügbar. PahoMqttAdapter kann nicht gestartet werden.")
            return False
        try:
            self._client = mqtt.Client()
            self._client.on_connect = self._on_connect
            self._client.on_message = self._on_message
            self._client.connect_async(config.MQTT_BROKER_HOST, config.MQTT_BROKER_PORT, keepalive=60)
            self._client.loop_start()
            logger.info(f"PahoMqttAdapter gestartet. Verbinde mit {config.MQTT_BROKER_HOST}:{config.MQTT_BROKER_PORT}...")
            return True
        except Exception as e:
            logger.error(f"Fehler beim Starten des PahoMqttAdapters: {e}")
            return False

    def disconnect(self):
        global bridge_status
        if self._client:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception as e:
                logger.error(f"Fehler beim Stoppen des MQTT-Clients: {e}")
            self._connected = False
            bridge_status = "offline"

    def publish(self, topic: str, payload: str, retain: bool = False) -> bool:
        if not self._client or not self._connected:
            logger.warning("MQTT-Client nicht verbunden. Publish übersprungen.")
            return False
        try:
            self._client.publish(topic, payload, retain=retain)
            return True
        except Exception as e:
            logger.error(f"Fehler beim Veröffentlichen auf Topic {topic}: {e}")
            return False

    def subscribe(self, topic: str) -> bool:
        if not self._client or not self._connected:
            logger.warning("MQTT-Client nicht verbunden. Subscribe übersprungen.")
            return False
        try:
            self._client.subscribe(topic)
            return True
        except Exception as e:
            logger.error(f"Fehler beim Abonnieren von Topic {topic}: {e}")
            return False

    def is_connected(self) -> bool:
        return self._connected

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            logger.info("PahoMqttAdapter: Erfolgreich mit Broker verbunden.")
            # Status-Topic abonnieren
            self.subscribe(config.MQTT_VALVE_TOPIC)
            
            # Bridge-Events für Kopplung abonnieren
            self.subscribe("zigbee2mqtt/bridge/event")
            self.subscribe("zigbee2mqtt/bridge/response/device/rename")
            self.subscribe("zigbee2mqtt/bridge/state")
            
            # Hardware-Timeout senden
            self._configure_safety_timeout()
            
            # Aktuellen Zustand des Ventils abfragen, um Pairing-Status zu laden
            self.publish(f"{config.MQTT_VALVE_TOPIC}/get", json.dumps({"state": ""}))
            logger.info("Zustandsabfrage an das Ventil gesendet.")
        else:
            self._connected = False
            logger.error(f"PahoMqttAdapter: Verbindungsfehler (rc={rc})")

    def _on_message(self, client, userdata, msg):
        # Rufe abwärtskompatible Methode auf
        on_message(client, userdata, msg)
        
        try:
            payload = msg.payload.decode("utf-8")
            data = json.loads(payload)
            
            if msg.topic == config.MQTT_VALVE_TOPIC:
                state = data.get("state", valve_status["state"])
                flow_rate = float(data.get("flow_rate", valve_status["flow_rate"]))
                battery = int(data.get("battery", valve_status["battery"]))
                linkquality = int(data.get("linkquality", valve_status["linkquality"]))
                valve_abnormal_state = data.get("valve_abnormal_state", valve_status.get("valve_abnormal_state", "normal"))
                
                # Ereignis publizieren
                self.event_bus.publish(ValveStatusReported(state, flow_rate, battery, linkquality, valve_abnormal_state))
                
            elif msg.topic == "zigbee2mqtt/bridge/event":
                if data.get("type") == "device_joined":
                    ieee = data.get("data", {}).get("ieee_address")
                    if ieee:
                        logger.info(f"PahoMqttAdapter: Gerät beigetreten – {ieee}")
                        self.event_bus.publish(DeviceJoinedEvent(ieee))
        except Exception as e:
            logger.error(f"PahoMqttAdapter: Fehler beim Weiterleiten an EventBus auf {msg.topic}: {e}")

    def _configure_safety_timeout(self):
        set_topic = f"{config.MQTT_VALVE_TOPIC}/set"
        payload = {
            "manual_default_settings": {
                "fail_safe": config.SAFETY_TIMEOUT_MINUTES
            }
        }
        self.publish(set_topic, json.dumps(payload), retain=True)
        logger.info(f"Hardware-Sicherheits-Timeout ({config.SAFETY_TIMEOUT_MINUTES} Min) via manual_default_settings.fail_safe gesendet.")

# --- Simulated Adapter (Simulation/Mock Mode) ---

class SimulatedMqttAdapter(MqttClient):
    """Simuliert das Ventil und die Bridge-Kopplung im Speicher (für Offline-Tests)."""
    def __init__(self, event_bus: EventBus):
        super().__init__(event_bus)
        self._connected = False
        self._sim_thread: Optional[threading.Thread] = None
        self._sim_running = False
        
        # Initialer simulationsfähiger Zustand
        valve_status["state"] = "OFF"
        valve_status["battery"] = 95
        valve_status["flow_rate"] = 0.0
        valve_status["linkquality"] = 140
        valve_status["valve_abnormal_state"] = "normal"
        valve_update_time = datetime.now()
        valve_status["last_update"] = valve_update_time.isoformat()

    def connect(self) -> bool:
        global bridge_status
        self._connected = True
        self._sim_running = True
        bridge_status = "online"
        self._sim_thread = threading.Thread(target=self._simulation_loop, daemon=True)
        self._sim_thread.start()
        logger.info("SimulatedMqttAdapter: Erfolgreich gestartet (Simulationsmodus).")
        return True

    def disconnect(self):
        global bridge_status
        self._sim_running = False
        self._connected = False
        bridge_status = "offline"

    def publish(self, topic: str, payload: str, retain: bool = False) -> bool:
        global active_cycle_volume, last_flow_update_time
        if not self._connected:
            return False
        
        try:
            data = json.loads(payload)
            if isinstance(data, dict) and "state" in data:
                new_state = data["state"]
                valve_status["state"] = new_state
                valve_status["last_update"] = datetime.now().isoformat()
                
                # Zukünftiger Status-Event
                flow = 5.0 if new_state == "ON" else 0.0
                valve_status["flow_rate"] = flow
                
                if new_state == "ON":
                    active_cycle_volume = 0.0
                    last_flow_update_time = datetime.now()
                else:
                    last_flow_update_time = None
                    
                self.event_bus.publish(ValveStatusReported(
                    new_state, flow, valve_status["battery"], valve_status["linkquality"], valve_status["valve_abnormal_state"]
                ))
                logger.info(f"SimulatedMqttAdapter: Ventil-State geändert -> {new_state}")
                
            if topic == "zigbee2mqtt/bridge/request/permit_join":
                is_permit = False
                if isinstance(data, dict):
                    if data.get("value") is True or data.get("time", 0) > 0:
                        is_permit = True
                elif isinstance(data, (int, float)):
                    if data > 0:
                        is_permit = True
                elif isinstance(data, str):
                    try:
                        if int(data) > 0:
                            is_permit = True
                    except ValueError:
                        pass
                
                if is_permit:
                    logger.info("SimulatedMqttAdapter: Koppelmodus aktiviert. Simuliere Gerät nach 100ms...")
                    # Simuliere Koppelungsbeitritt nach einer minimalen Verzögerung asynchronous
                    threading.Thread(target=self._simulate_device_joined, daemon=True).start()
            return True
        except Exception as e:
            logger.error(f"SimulatedMqttAdapter: Fehler beim Verarbeiten von publish auf {topic}: {e}")
            return False

    def subscribe(self, topic: str) -> bool:
        return True

    def is_connected(self) -> bool:
        return self._connected

    def _simulate_device_joined(self):
        time.sleep(0.1)
        self.event_bus.publish(DeviceJoinedEvent("0x00124b0025aa1122"))

    def _simulation_loop(self):
        global active_cycle_volume, last_flow_update_time
        while self._sim_running:
            try:
                # Simuliere stetiges Feuern des Status-Events bei offenem Ventil
                if valve_status["state"] == "ON":
                    now = datetime.now()
                    if last_flow_update_time is not None:
                        elapsed = (now - last_flow_update_time).total_seconds()
                        if elapsed > 0:
                            active_cycle_volume += 5.0 * (min(elapsed, 60.0) / 60.0)
                    last_flow_update_time = now
                    self.event_bus.publish(ValveStatusReported(
                        "ON", 5.0, valve_status["battery"], valve_status["linkquality"], valve_status["valve_abnormal_state"]
                    ))
                time.sleep(1)
            except Exception:
                pass

# --- Global / Static API Façade (Backward Compatibility) ---

_global_bus = EventBus()
client_instance = None

def _init_client():
    global client_instance
    if client_instance is None:
        if HAS_PAHO:
            client_instance = PahoMqttAdapter(_global_bus)
        else:
            client_instance = SimulatedMqttAdapter(_global_bus)

def start_client() -> bool:
    global client_instance
    # Falls die Test-Suite HAS_PAHO dynamisch auf False überschrieben hat, erzwinge den SimulatedMqttAdapter
    if not HAS_PAHO:
        client_instance = SimulatedMqttAdapter(_global_bus)
    else:
        _init_client()
    return client_instance.connect()

def get_valve_status() -> Dict[str, Any]:
    _init_client()
    return client_instance.get_valve_status()

def reset_active_volume():
    global active_cycle_volume, last_flow_update_time
    active_cycle_volume = 0.0
    last_flow_update_time = datetime.now() if valve_status["state"] == "ON" else None

def get_active_volume() -> float:
    global active_cycle_volume
    return round(active_cycle_volume, 2)

def open_valve() -> bool:
    _init_client()
    return client_instance.publish(f"{config.MQTT_VALVE_TOPIC}/set", json.dumps({"state": "ON"}))

def close_valve() -> bool:
    _init_client()
    return client_instance.publish(f"{config.MQTT_VALVE_TOPIC}/set", json.dumps({"state": "OFF"}))

def is_broker_connected() -> bool:
    _init_client()
    return client_instance.is_connected()

def request_valve_status() -> bool:
    """Sendet eine get-Abfrage über MQTT, um aktuelle Werte (Zustand, Batterie) vom Ventil anzufordern."""
    _init_client()
    return client_instance.publish(f"{config.MQTT_VALVE_TOPIC}/get", json.dumps({"state": "", "battery": ""}))

def get_bridge_status() -> str:
    _init_client()
    return client_instance.get_bridge_status()

