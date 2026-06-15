import time
import logging
import threading
from . import database
from ..core.event_bus import EventBus
from ..core.camera_events import CameraRegistered

logger = logging.getLogger("garden_camera_pairing")

PAIRING_TIMEOUT = 90
_pairing_active = False
_pairing_lock = threading.Lock()

_global_bus = None

def init_pairing(event_bus: EventBus):
    """Initialisiert das Pairing-Modul mit dem EventBus.

    Bereinigt veraltete Koppel-Metadaten aus einem früheren Daemon-Lauf,
    damit kein unbeaufsichtigtes Koppel-Fenster offen bleibt.
    """
    global _global_bus
    _global_bus = event_bus
    database.set_metadata("camera_pairing_active", "0")
    database.set_metadata("camera_pairing_wish_name", "")
    database.set_metadata("camera_pairing_expires_at", "0")

def is_pairing_active() -> bool:
    """Gibt zurück, ob gerade eine Kamera-Kopplung läuft."""
    return _pairing_active

def start_pairing(chat_id: int, notify_fn, wish_name: str, sleep_seconds: int = 900) -> bool:
    """
    Startet die Kamera-Kopplung in einem Hintergrund-Thread.
    """
    global _pairing_active
    with _pairing_lock:
        if _pairing_active:
            return False
        _pairing_active = True

    t = threading.Thread(
        target=_pairing_worker,
        args=(chat_id, notify_fn, wish_name, sleep_seconds),
        daemon=True
    )
    t.start()
    return True

def _pairing_worker(chat_id: int, notify_fn, wish_name: str, sleep_seconds: int):
    """Hintergrund-Thread: führt die Kamera-Kopplung durch."""
    global _pairing_active
    
    registered_event = threading.Event()
    mac_ref = [None]
    
    def on_camera_registered(event: CameraRegistered):
        mac_ref[0] = event.mac_address
        registered_event.set()
        
    try:
        # DB-Metadaten zuerst schreiben, damit camera_receiver das Fenster sofort sieht
        expires_at = time.time() + PAIRING_TIMEOUT
        database.set_metadata("camera_pairing_active", "1")
        database.set_metadata("camera_pairing_wish_name", wish_name)
        database.set_metadata("camera_pairing_expires_at", str(expires_at))

        # Erst nach dem DB-Write subscriben, um Race zu vermeiden
        if _global_bus:
            _global_bus.subscribe(CameraRegistered, on_camera_registered)
        
        logger.info(f"Kamera-Kopplung: Koppelmodus aktiviert für '{wish_name}'.")
        
        if registered_event.wait(PAIRING_TIMEOUT):
            # Erfolgreich registriert — Intervall speichern
            mac = mac_ref[0]
            cam = database.get_camera(mac)
            if cam:
                database.update_camera_settings(
                    mac,
                    sleep_seconds=sleep_seconds,
                    resolution=cam["resolution"],
                    quality=cam["quality"],
                )
            logger.info("Kamera-Kopplung: Erfolgreich abgeschlossen.")
            minutes = sleep_seconds // 60
            notify_fn(
                chat_id,
                f"✅ *Kamera-Kopplung erfolgreich!*\n\n"
                f"Die Kamera **'{wish_name}'** (MAC: `{mac}`) wurde registriert.\n"
                f"Sendeintervall: {minutes} Minuten\n"
                f"Der Koppelmodus wurde automatisch deaktiviert."
            )
        else:
            # Timeout
            logger.warning("Kamera-Kopplung: Timeout – keine Kamera hat sich gemeldet.")
            notify_fn(
                chat_id,
                "❌ *Kamera-Kopplung fehlgeschlagen.*\n\n"
                "Keine Kamera hat sich innerhalb von 90 Sekunden gemeldet. "
                "Koppelmodus wurde automatisch deaktiviert.\n\n"
                "Erneut versuchen: `/camera_setup`"
            )
            
    except Exception as e:
        logger.error(f"Kamera-Kopplung: Unerwarteter Fehler: {e}")
        notify_fn(chat_id, f"❌ Fehler bei der Kamera-Kopplung: {e}")
    finally:
        database.set_metadata("camera_pairing_active", "0")
        database.set_metadata("camera_pairing_wish_name", "")
        database.set_metadata("camera_pairing_expires_at", "0")
        if _global_bus:
            _global_bus.unsubscribe(CameraRegistered, on_camera_registered)
        _pairing_active = False
