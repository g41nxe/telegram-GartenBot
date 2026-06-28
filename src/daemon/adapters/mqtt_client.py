import json
import logging
import time
import threading
from datetime import datetime
from typing import Any, Dict, Optional
from .. import config
from ..core.event_bus import EventBus

logger = logging.getLogger("garden_mqtt")

# --- Events (defined in core, re-exported here for backward compatibility) ---

from ..core.valve_events import ValveStatusReported, DeviceJoinedEvent  # noqa: F401
from ..core.sensor_events import RainSensorMeasured  # noqa: F401


def _topic_matches(pattern: str, topic: str) -> bool:
    """Einfaches MQTT-Topic-Matching mit '+' (eine Ebene) und '#' (Rest).

    Nötig, weil der Regensensor auf AQS/<geräte-id>/stat publisht und der Filter
    geräteunabhängig (AQS/+/stat) sein soll.
    """
    p, t = pattern.split("/"), topic.split("/")
    for i, seg in enumerate(p):
        if seg == "#":
            return True
        if i >= len(t):
            return False
        if seg != "+" and seg != t[i]:
            return False
    return len(p) == len(t)


def _rain_battery_pct(consumed_mas) -> int:
    """Rechnet die verbrauchte Kapazität (mAs) des RANWIE01 in Rest-Prozent um.

    Rest-% = 100·(1 − verbraucht / Gesamtkapazität), geklemmt auf 0–100. Ohne
    konfigurierte Kapazität → 100 % (keine sinnvolle Aussage möglich).
    """
    cap_mah = config.RAIN_SENSOR_BATTERY_CAPACITY_MAH
    if not cap_mah:
        return 100
    try:
        consumed = float(consumed_mas or 0)
    except (TypeError, ValueError):
        return 100
    remaining = 100.0 * (1.0 - consumed / (cap_mah * 3600.0))
    return int(max(0, min(100, round(remaining))))

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

# Single lock covering both valve_status and bridge_status to prevent data races
_status_lock = threading.Lock()

# --- Abwärtskompatibles on_message ---

def on_message(client, userdata, msg):
    """Callback bei eingehender MQTT-Nachricht (global und abwärtskompatibel)."""
    global bridge_status
    try:
        payload = msg.payload.decode("utf-8")

        # Bridge-Status-Nachrichten: Kann reiner Text (alt) oder ein JSON-Objekt {"state": "online"} (neu) sein
        if hasattr(msg, "topic") and msg.topic == "zigbee2mqtt/bridge/state":
            raw_payload = payload.strip()
            if raw_payload.startswith("{") and raw_payload.endswith("}"):
                try:
                    state_json = json.loads(raw_payload)
                    new_status = state_json.get("state", "offline").lower()
                except Exception:
                    new_status = "offline"
            else:
                new_status = raw_payload.lower()
            with _status_lock:
                bridge_status = new_status
            logger.info(f"Mittelweg-Dienst Status empfangen: {new_status}")
            return

        data = json.loads(payload)

        state = data.get("state", valve_status["state"])
        flow_rate = float(data.get("flow_rate", valve_status["flow_rate"]))
        now = datetime.now()

        with _status_lock:
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
        with _status_lock:
            return dict(valve_status)

    def get_bridge_status(self) -> str:
        with _status_lock:
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
        if self._client:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception as e:
                logger.error(f"Fehler beim Stoppen des MQTT-Clients: {e}")
            self._connected = False
            with _status_lock:
                global bridge_status
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
            # Wildcard — empfängt Status von allen Zigbee-Geräten (ein Level), nicht nur dem
            # primären MQTT_VALVE_TOPIC. Damit werden auch Zweit-Ventile (z.B. valve_ffff) erfasst.
            self.subscribe("zigbee2mqtt/+")
            self.subscribe("zigbee2mqtt/bridge/event")
            self.subscribe("zigbee2mqtt/bridge/response/device/rename")
            self.subscribe("zigbee2mqtt/bridge/state")
            self.subscribe(config.RAIN_SENSOR_TOPIC)
            self._configure_safety_timeout()
            self.publish(f"{config.MQTT_VALVE_TOPIC}/get", json.dumps({"state": ""}))
            logger.info("Zustandsabfrage an das Ventil gesendet.")
        else:
            self._connected = False
            logger.error(f"PahoMqttAdapter: Verbindungsfehler (rc={rc})")

    def _on_message(self, client, userdata, msg):
        # Rufe abwärtskompatible Methode auf (aktualisiert valve_status unter Lock)
        on_message(client, userdata, msg)

        try:
            payload = msg.payload.decode("utf-8")
            data = json.loads(payload)

            # Valve-Erkennung: jedes zweigliedrige zigbee2mqtt/-Topic mit linkquality gilt als
            # Ventil-Status. Das schließt bridge/*, Rain-Sensor (anderer Namespace) und
            # sonstige Nicht-Geräte-Topics aus.
            topic_parts = msg.topic.split("/")
            is_valve_topic = (
                len(topic_parts) == 2
                and topic_parts[0] == "zigbee2mqtt"
                and not _topic_matches(config.RAIN_SENSOR_TOPIC, msg.topic)
                and "linkquality" in data
            )
            if is_valve_topic:
                with _status_lock:
                    state = data.get("state", valve_status["state"])
                    flow_rate = float(data.get("flow_rate", valve_status["flow_rate"]))
                    battery = int(data.get("battery", valve_status["battery"]))
                    linkquality = int(data.get("linkquality", valve_status["linkquality"]))
                    valve_abnormal_state = data.get("valve_abnormal_state", valve_status.get("valve_abnormal_state", "normal"))

                # Guss-Volumen = live mitlaufende Menge der aktuellen Session, NICHT der
                # kumulative real_time_irrigation_volume (steht während des Gusses still). ADR 0007.
                sched = data.get("irrigation_schedule_status") or {}
                schedule_status = sched.get("schedule_status")
                actual = sched.get("actual_irrigation_amount")
                irrigation_volume = float(actual) if actual is not None else 0.0
                mqtt_name = topic_parts[-1]
                self.event_bus.publish(ValveStatusReported(
                    mqtt_name, state, flow_rate, battery, linkquality, valve_abnormal_state,
                    irrigation_volume=irrigation_volume, schedule_status=schedule_status
                ))

            elif msg.topic == "zigbee2mqtt/bridge/event":
                if data.get("type") == "device_joined":
                    ieee = data.get("data", {}).get("ieee_address")
                    if ieee:
                        logger.info(f"PahoMqttAdapter: Gerät beigetreten – {ieee}")
                        self.event_bus.publish(DeviceJoinedEvent(ieee))

            elif _topic_matches(config.RAIN_SENSOR_TOPIC, msg.topic):
                self._handle_rain_sensor(data)
        except Exception as e:
            logger.error(f"PahoMqttAdapter: Fehler beim Weiterleiten an EventBus auf {msg.topic}: {e}")

    def _handle_rain_sensor(self, data: dict):
        try:
            # RANWIE01: rainlevel/raintotal in 0,5-mm-Ticks, temperature in 1/10 °C,
            # battery = verbrauchte Kapazität in mAs.
            mm_per_tick = config.RAIN_SENSOR_MM_PER_TICK
            rainlevel_mm = round(float(data.get("rainlevel", 0.0)) * mm_per_tick, 2)
            raintotal_mm = round(float(data.get("raintotal", 0.0)) * mm_per_tick, 2)
            temperature_c = round(float(data.get("temperature", 0)) / 10.0, 1)
            battery_pct = _rain_battery_pct(data.get("battery"))
            is_raining = rainlevel_mm >= config.RAIN_SENSOR_THRESHOLD_MM
            self.event_bus.publish(RainSensorMeasured(
                rainlevel_mm, raintotal_mm, temperature_c, battery_pct, is_raining
            ))
            logger.debug(
                f"Regensensor: {rainlevel_mm} mm · Gesamt {raintotal_mm} mm · "
                f"{temperature_c} °C · Batterie {battery_pct}% · Regen={is_raining}"
            )
        except Exception as e:
            logger.error(f"Fehler beim Parsen der Regensensor-Nachricht: {e}")

    def _configure_safety_timeout(self):
        set_topic = f"{config.MQTT_VALVE_TOPIC}/set"
        # The SWV-ZFE converter (hasFlowMeter=true) validates all fields together;
        # omitting irrigation_mode causes it to return early without writing fail_safe.
        _safety_min = config.get_setting("SAFETY_TIMEOUT_MINUTES", 30)
        payload = {
            "manual_default_settings": {
                "irrigation_mode": "duration",
                "irrigation_duration": _safety_min,
                "irrigation_amount_unit": "liter",
                "irrigation_amount": 0,
                "fail_safe": _safety_min,
            }
        }
        self.publish(set_topic, json.dumps(payload), retain=True)
        logger.info(f"Hardware-Sicherheits-Timeout ({_safety_min} Min) via manual_default_settings.fail_safe gesendet.")

# --- Simulated Adapter (Simulation/Mock Mode) ---

class SimulatedMqttAdapter(MqttClient):
    """Simuliert das Ventil und die Bridge-Kopplung im Speicher (für Offline-Tests)."""
    def __init__(self, event_bus: EventBus):
        super().__init__(event_bus)
        self._connected = False
        self._sim_thread: Optional[threading.Thread] = None
        self._sim_running = False

        with _status_lock:
            valve_status["state"] = "OFF"
            valve_status["battery"] = 95
            valve_status["flow_rate"] = 0.0
            valve_status["linkquality"] = 140
            valve_status["valve_abnormal_state"] = "normal"
            valve_status["last_update"] = datetime.now().isoformat()

    def connect(self) -> bool:
        global bridge_status
        self._connected = True
        self._sim_running = True
        with _status_lock:
            bridge_status = "online"
        self._sim_thread = threading.Thread(target=self._simulation_loop, daemon=True)
        self._sim_thread.start()
        logger.info("SimulatedMqttAdapter: Erfolgreich gestartet (Simulationsmodus).")
        return True

    def disconnect(self):
        global bridge_status
        self._sim_running = False
        self._connected = False
        with _status_lock:
            bridge_status = "offline"

    def publish(self, topic: str, payload: str, retain: bool = False) -> bool:
        if not self._connected:
            return False

        try:
            data = json.loads(payload)
            if isinstance(data, dict) and "state" in data:
                new_state = data["state"]
                flow = 5.0 if new_state == "ON" else 0.0
                with _status_lock:
                    valve_status["state"] = new_state
                    valve_status["flow_rate"] = flow
                    valve_status["last_update"] = datetime.now().isoformat()

                mqtt_name = topic.split("/")[1] if topic.count("/") >= 2 else "garden_valve"
                self.event_bus.publish(ValveStatusReported(
                    mqtt_name, new_state, flow, valve_status["battery"], valve_status["linkquality"], valve_status["valve_abnormal_state"]
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
        while self._sim_running:
            try:
                with _status_lock:
                    state = valve_status["state"]
                    battery = valve_status["battery"]
                    lqi = valve_status["linkquality"]
                    abnormal = valve_status["valve_abnormal_state"]
                if state == "ON":
                    # Fire a status event every second; WateringController integrates flow
                    self.event_bus.publish(ValveStatusReported("garden_valve", "ON", 5.0, battery, lqi, abnormal))
                time.sleep(1)
            except Exception:
                pass

# --- Global / Static API Façade (Backward Compatibility) ---

_global_bus = EventBus()
client_instance = None
_registered_valve_names: set = set()  # Zusätzliche Ventil-mqtt_names (befüllt von main.py)

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

def open_valve() -> bool:
    _init_client()
    return client_instance.publish(f"{config.MQTT_VALVE_TOPIC}/set", json.dumps({"state": "ON"}))

def close_valve() -> bool:
    _init_client()
    return client_instance.publish(f"{config.MQTT_VALVE_TOPIC}/set", json.dumps({"state": "OFF"}))

def is_broker_connected() -> bool:
    _init_client()
    return client_instance.is_connected()

def register_valve_topic(mqtt_name: str) -> None:
    """Registriert einen Ventil-mqtt_name für Status-Abfragen. Einmalig von main.py für jedes DB-Ventil."""
    _registered_valve_names.add(mqtt_name)


def request_valve_status() -> bool:
    """Sendet get-Abfragen für alle bekannten Ventile (primäres + registrierte Zweit-Ventile)."""
    _init_client()
    primary_name = config.MQTT_VALVE_TOPIC.split("/")[-1]
    get_payload = json.dumps({"state": "", "battery": ""})
    results = [client_instance.publish(f"{config.MQTT_VALVE_TOPIC}/get", get_payload)]
    for name in _registered_valve_names:
        if name != primary_name:
            results.append(client_instance.publish(f"zigbee2mqtt/{name}/get", get_payload))
    return any(results)

def get_bridge_status() -> str:
    _init_client()
    return client_instance.get_bridge_status()
