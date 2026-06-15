import logging
from datetime import datetime

from . import database
from .. import config
from .mqtt_client import _global_bus
from ..core.watchdog_events import InactivityAlertTriggered, InactivityAlertResolved
from ..core.valve_events import ValveStatusReported
from ..core.camera_events import CameraImageReceived, CameraInactivityAlertTriggered, CameraInactivityAlertResolved

logger = logging.getLogger("garden_watchdog")


def _on_valve_status(event: ValveStatusReported):
    """Sofortige Entwarnung sobald ein Ventil wieder ein Signal sendet."""
    valve = database.get_valve_by_mqtt_name(event.mqtt_name)
    if not valve:
        return
    valve_id = valve["id"]
    flag_key = f"watchdog_alert_active_valve_{valve_id}"
    if database.get_metadata(flag_key) == "1":
        database.set_metadata(flag_key, "0")
        _global_bus.publish(InactivityAlertResolved(valve["wish_name"], valve_id))


def _on_camera_image(event: CameraImageReceived):
    """Sofortige Entwarnung sobald ein Kamerabild erfolgreich empfangen wurde."""
    mac = event.mac_address
    flag_key = f"watchdog_alert_active_camera_{mac}"
    if database.get_metadata(flag_key) == "1":
        database.set_metadata(flag_key, "0")
        _global_bus.publish(CameraInactivityAlertResolved(mac, event.wish_name))


def initialize():
    """Registriert dauerhafte EventBus-Listener. Einmalig beim Daemon-Start aufrufen."""
    if not config.WATCHDOG_ENABLED:
        logger.info("Inaktivitäts-Watchdog deaktiviert (WATCHDOG_ENABLED=false).")
        return
    _global_bus.subscribe(ValveStatusReported, _on_valve_status)
    _global_bus.subscribe(CameraImageReceived, _on_camera_image)
    logger.info("Inaktivitäts-Watchdog initialisiert.")


def run_watchdog_check():
    """Prüft alle Ventile auf Inaktivität. Stündlich in einem Daemon-Thread aufrufen."""
    if not config.WATCHDOG_ENABLED:
        return

    timeout_hours = config.WATCHDOG_VALVE_TIMEOUT_HOURS
    now = datetime.now()

    for valve in database.get_all_valves():
        last_update_str = valve.get("last_update")
        if not last_update_str:
            continue

        valve_id = valve["id"]
        wish_name = valve["wish_name"]
        flag_key = f"watchdog_alert_active_valve_{valve_id}"

        try:
            last_up = datetime.fromisoformat(last_update_str)
        except Exception:
            continue

        hours_silent = (now - last_up).total_seconds() / 3600
        flag = database.get_metadata(flag_key)

        if hours_silent > timeout_hours:
            if flag != "1":
                database.set_metadata(flag_key, "1")
                _global_bus.publish(
                    InactivityAlertTriggered(wish_name, valve_id, hours_silent, int(timeout_hours))
                )
                logger.warning(f"Watchdog-Alert: Ventil '{wish_name}' seit {hours_silent:.1f}h still.")
        else:
            if flag == "1":
                # Ventil wurde zwischen zwei Checks reaktiviert (z.B. nach Daemon-Neustart)
                database.set_metadata(flag_key, "0")
                _global_bus.publish(InactivityAlertResolved(wish_name, valve_id))
                logger.info(f"Watchdog-Entwarnung (Check): Ventil '{wish_name}' wieder aktiv.")

    # --- Kameras ---
    for camera in database.get_all_cameras():
        last_seen_str = camera.get("last_seen")
        if not last_seen_str:
            continue
            
        mac = camera["mac_address"]
        wish_name = camera["wish_name"]
        flag_key = f"watchdog_alert_active_camera_{mac}"
        sleep_sec = camera.get("sleep_duration_seconds", 900)
        
        # Dynamisches Limit: 3 * sleep_duration_seconds, mind. 3600 Sekunden (1h)
        timeout_seconds = max(3 * sleep_sec, 3600)
        
        try:
            last_seen = datetime.fromisoformat(last_seen_str)
        except Exception:
            continue
            
        seconds_silent = (now - last_seen).total_seconds()
        flag = database.get_metadata(flag_key)
        
        if seconds_silent > timeout_seconds:
            if flag != "1":
                database.set_metadata(flag_key, "1")
                _global_bus.publish(
                    CameraInactivityAlertTriggered(mac, wish_name, int(seconds_silent), timeout_seconds)
                )
                logger.warning(f"Watchdog-Alert: Kamera '{wish_name}' seit {seconds_silent:.0f}s still.")
        else:
            if flag == "1":
                database.set_metadata(flag_key, "0")
                _global_bus.publish(CameraInactivityAlertResolved(mac, wish_name))
                logger.info(f"Watchdog-Entwarnung (Check): Kamera '{wish_name}' wieder aktiv.")
