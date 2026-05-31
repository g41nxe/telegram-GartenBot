import json
import logging
import threading
import time
from . import config

logger = logging.getLogger("garden_pairing")

VALVE_NAME = "garden_valve"
PAIRING_TIMEOUT = 90   # Sekunden bis Abbruch
REMINDER_AT    = 45    # Sekunden bis Erinnerungsnachricht

_pairing_active = False
_pairing_lock   = threading.Lock()


def is_pairing_active() -> bool:
    """Gibt zurück, ob gerade eine Ventil-Kopplung läuft."""
    return _pairing_active


def start_pairing(chat_id: int, notify_fn) -> bool:
    """
    Startet die Ventil-Kopplung in einem Hintergrund-Thread.

    :param chat_id:   Telegram-Chat-ID des Nutzers, der Fortschritt-Updates erhält.
    :param notify_fn: Callable(chat_id, text) zum Senden von Telegram-Nachrichten.
    :returns:         True wenn der Thread gestartet wurde, False wenn bereits aktiv.
    """
    global _pairing_active
    with _pairing_lock:
        if _pairing_active:
            return False
        _pairing_active = True

    t = threading.Thread(
        target=_pairing_worker,
        args=(chat_id, notify_fn),
        daemon=True
    )
    t.start()
    return True


def _pairing_worker(chat_id: int, notify_fn):
    """Hintergrund-Thread: führt die vollständige Ventil-Kopplung durch."""
    global _pairing_active

    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        notify_fn(chat_id,
            "❌ MQTT-Bibliothek (paho-mqtt) nicht installiert.\n"
            "Ventil-Kopplung nicht möglich."
        )
        _pairing_active = False
        return

    found_event   = threading.Event()
    ieee_address  = [None]

    # ── MQTT-Callbacks ────────────────────────────────────────────────────────

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            client.subscribe("zigbee2mqtt/bridge/event")
            client.subscribe("zigbee2mqtt/bridge/response/device/rename")
            # Koppelmodus im Mittelweg-Dienst aktivieren
            client.publish(
                "zigbee2mqtt/bridge/request/permit_join",
                json.dumps({"value": True})
            )
            logger.info("Ventil-Kopplung: Koppelmodus aktiviert.")
        else:
            logger.error(f"Ventil-Kopplung: MQTT-Verbindungsfehler (rc={rc})")

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            if msg.topic == "zigbee2mqtt/bridge/event":
                if payload.get("type") == "device_joined":
                    ieee = payload.get("data", {}).get("ieee_address")
                    if ieee:
                        ieee_address[0] = ieee
                        found_event.set()
                        logger.info(f"Ventil-Kopplung: Gerät beigetreten – {ieee}")
        except Exception as e:
            logger.error(f"Ventil-Kopplung: Fehler beim Verarbeiten der MQTT-Nachricht: {e}")

    # ── Kurzlebige MQTT-Verbindung nur für die Kopplung ──────────────────────

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(config.MQTT_BROKER_HOST, config.MQTT_BROKER_PORT, keepalive=60)
        client.loop_start()

        # Auf Beitrittssignal warten (max. PAIRING_TIMEOUT Sekunden)
        reminded = False
        start    = time.time()

        while True:
            elapsed = time.time() - start

            if found_event.is_set():
                break

            if elapsed >= PAIRING_TIMEOUT:
                break

            if not reminded and elapsed >= REMINDER_AT:
                reminded = True
                notify_fn(
                    chat_id,
                    "⏳ Noch kein Ventil erkannt.\n\n"
                    "Bitte Reset-Knopf am Sonoff Hydro ONE **5 Sekunden** "
                    "gedrückt halten, bis die LED schnell blinkt.\n\n"
                    f"_Noch {PAIRING_TIMEOUT - REMINDER_AT} Sekunden verbleibend..._"
                )

            time.sleep(1)

        # ── Timeout ───────────────────────────────────────────────────────────

        if not found_event.is_set():
            client.publish(
                "zigbee2mqtt/bridge/request/permit_join",
                json.dumps({"value": False})
            )
            logger.warning("Ventil-Kopplung: Timeout – kein Gerät erkannt.")
            notify_fn(
                chat_id,
                "❌ *Ventil-Kopplung fehlgeschlagen.*\n\n"
                "Kein Ventil erkannt nach 90 Sekunden. "
                "Koppelmodus wurde automatisch deaktiviert.\n\n"
                "Erneut versuchen: `/setup`"
            )
            return

        # ── Gerät umbenennen auf garden_valve ─────────────────────────────────

        ieee = ieee_address[0]
        logger.info(f"Ventil-Kopplung: Benenne {ieee} → {VALVE_NAME}")
        client.publish(
            "zigbee2mqtt/bridge/request/device/rename",
            json.dumps({"from": ieee, "to": VALVE_NAME})
        )
        time.sleep(2)

        # Koppelmodus deaktivieren
        client.publish(
            "zigbee2mqtt/bridge/request/permit_join",
            json.dumps({"value": False})
        )
        time.sleep(1)

        logger.info("Ventil-Kopplung: Erfolgreich abgeschlossen.")
        notify_fn(
            chat_id,
            f"✅ *Ventil-Kopplung erfolgreich!*\n\n"
            f"Das Ventil wurde erkannt und als `{VALVE_NAME}` registriert.\n"
            f"Der Koppelmodus wurde automatisch deaktiviert.\n\n"
            f"Sende /status um den Verbindungsstatus zu prüfen."
        )

    except Exception as e:
        logger.error(f"Ventil-Kopplung: Unerwarteter Fehler: {e}")
        notify_fn(chat_id, f"❌ Fehler bei der Ventil-Kopplung: {e}")
    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass
        _pairing_active = False
