import json
import logging
import threading
import time
from . import mqtt_client, database
from .mqtt_client import _global_bus, DeviceJoinedEvent

logger = logging.getLogger("garden_pairing")

PAIRING_TIMEOUT = 90   # Sekunden bis Abbruch
REMINDER_AT    = 45    # Sekunden bis Erinnerungsnachricht

_pairing_active = False
_pairing_lock   = threading.Lock()

def is_pairing_active() -> bool:
    """Gibt zurück, ob gerade eine Ventil-Kopplung läuft."""
    return _pairing_active

def start_pairing(chat_id: int, notify_fn, wish_name: str) -> bool:
    """
    Startet die Ventil-Kopplung in einem Hintergrund-Thread.

    :param chat_id:   Telegram-Chat-ID des Nutzers, der Fortschritt-Updates erhält.
    :param notify_fn: Callable(chat_id, text) zum Senden von Telegram-Nachrichten.
    :param wish_name: Benutzerdefinierter Anzeigename des neuen Ventils (z. B. "Rasen").
    :returns:         True wenn der Thread gestartet wurde, False wenn bereits aktiv.
    """
    global _pairing_active
    with _pairing_lock:
        if _pairing_active:
            return False
        _pairing_active = True

    t = threading.Thread(
        target=_pairing_worker,
        args=(chat_id, notify_fn, wish_name),
        daemon=True
    )
    t.start()
    return True

def _pairing_worker(chat_id: int, notify_fn, wish_name: str):
    """Hintergrund-Thread: führt die vollständige Ventil-Kopplung durch."""
    global _pairing_active

    found_event   = threading.Event()
    ieee_address  = [None]

    def on_device_joined(event: DeviceJoinedEvent):
        ieee_address[0] = event.ieee_address
        found_event.set()
        logger.info(f"Ventil-Kopplung: Gerät beigetreten – {event.ieee_address}")

    _global_bus.subscribe(DeviceJoinedEvent, on_device_joined)

    try:
        permit_join_payload = json.dumps({"time": PAIRING_TIMEOUT})
        mqtt_client.client_instance.publish(
            "zigbee2mqtt/bridge/request/permit_join",
            permit_join_payload
        )
        logger.info("Ventil-Kopplung: Koppelmodus aktiviert.")

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
                "Erneut versuchen über ⚙️ Einstellungen ▸ 🔧 Ventil koppeln."
            )
            return

        ieee = ieee_address[0]
        # mqtt_name aus den letzten 4 Stellen der IEEE-Adresse ableiten
        mqtt_name = f"valve_{ieee[-4:]}"
        logger.info(f"Ventil-Kopplung: Benenne {ieee} → {mqtt_name}")

        mqtt_client.client_instance.publish(
            "zigbee2mqtt/bridge/request/device/rename",
            json.dumps({"from": ieee, "to": mqtt_name})
        )
        time.sleep(2)

        # Koppelmodus deaktivieren
        mqtt_client.client_instance.publish(
            "zigbee2mqtt/bridge/request/permit_join",
            json.dumps({"time": 0})
        )
        time.sleep(1)

        # Ventil in der Datenbank registrieren
        valve_id = database.add_valve(wish_name, mqtt_name)
        if valve_id > 0:
            logger.info(f"Ventil-Kopplung: '{wish_name}' ({mqtt_name}) in DB gespeichert (id={valve_id}).")
        else:
            logger.warning(f"Ventil-Kopplung: Konnte '{mqtt_name}' nicht in DB speichern (evtl. bereits vorhanden).")

        # Topic beim Client abonnieren
        mqtt_client.client_instance.subscribe(f"zigbee2mqtt/{mqtt_name}")

        logger.info("Ventil-Kopplung: Erfolgreich abgeschlossen.")
        notify_fn(
            chat_id,
            f"✅ *Ventil-Kopplung erfolgreich!*\n\n"
            f"Das Ventil **'{wish_name}'** wurde erkannt und als `{mqtt_name}` registriert.\n"
            f"Der Koppelmodus wurde automatisch deaktiviert.\n\n"
            f"Sende /status um den Verbindungsstatus zu prüfen."
        )

    except Exception as e:
        logger.error(f"Ventil-Kopplung: Unerwarteter Fehler: {e}")
        notify_fn(chat_id, f"❌ Fehler bei der Ventil-Kopplung: {e}")
    finally:
        _global_bus.unsubscribe(DeviceJoinedEvent, on_device_joined)
        _pairing_active = False
