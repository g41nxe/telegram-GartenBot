import json
import logging
import threading
import time
from .. import config
from . import mqtt_client
from .mqtt_client import _global_bus, DeviceJoinedEvent

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
    """Hintergrund-Thread: führt die vollständige Ventil-Kopplung über das einheitliche MqttClient-Seam durch."""
    global _pairing_active

    found_event   = threading.Event()
    ieee_address  = [None]

    # Event-Listener für Beigetretene Geräte
    def on_device_joined(event: DeviceJoinedEvent):
        ieee_address[0] = event.ieee_address
        found_event.set()
        logger.info(f"Ventil-Kopplung: Gerät beigetreten – {event.ieee_address}")

    # Registriere den Listener auf dem Ereignis-Kanal
    _global_bus.subscribe(DeviceJoinedEvent, on_device_joined)

    try:
        # Koppelmodus im Mittelweg-Dienst aktivieren über den Haupt-Client
        permit_join_payload = json.dumps({"time": PAIRING_TIMEOUT})
        mqtt_client.client_instance.publish(
            "zigbee2mqtt/bridge/request/permit_join",
            permit_join_payload
        )
        logger.info("Ventil-Kopplung: Koppelmodus aktiviert.")

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
            mqtt_client.client_instance.publish(
                "zigbee2mqtt/bridge/request/permit_join",
                json.dumps({"time": 0})
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
        mqtt_client.client_instance.publish(
            "zigbee2mqtt/bridge/request/device/rename",
            json.dumps({"from": ieee, "to": VALVE_NAME})
        )
        time.sleep(2)

        # Koppelmodus deaktivieren
        mqtt_client.client_instance.publish(
            "zigbee2mqtt/bridge/request/permit_join",
            json.dumps({"time": 0})
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
        _pairing_active = False
