import logging
from datetime import datetime

from . import database
from .. import config
from .mqtt_client import _global_bus
from ..core.watchdog_events import InactivityAlertTriggered, InactivityAlertResolved
from ..core.valve_events import ValveStatusReported
from ..core.camera_events import (CameraImageReceived, CameraInactivityAlertTriggered,
                                  CameraInactivityAlertResolved, TimedPhotoCaptured,
                                  CameraDelayAlertTriggered, CameraDelayAlertResolved)
from ..core.sensor_events import RainSensorMeasured, RainSensorInactivityAlertTriggered, RainSensorInactivityAlertResolved
from ..core import camera_schedule

logger = logging.getLogger("garden_watchdog")


def _als_zeitpunkt(iso: str | None) -> datetime | None:
    """Liest einen ISO-Zeitstempel aus system_metadata; unlesbare Werte gelten als unbekannt."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def _on_valve_status(event: ValveStatusReported):
    """Sofortige Entwarnung sobald ein Ventil wieder ein Signal sendet."""
    valve = database.get_valve_by_mqtt_name(event.mqtt_name)
    if not valve:
        return
    valve_id = valve["id"]
    flag_key = database.watchdog_valve_alert_key(valve_id)
    if database.get_flag(flag_key):
        database.set_flag(flag_key, False)
        _global_bus.publish(InactivityAlertResolved(valve["wish_name"], valve_id))


def _on_camera_image(event: CameraImageReceived):
    """Sofortige Entwarnung sobald ein Kamerabild erfolgreich empfangen wurde."""
    mac = event.mac_address
    flag_key = database.watchdog_camera_alert_key(mac)
    if database.get_flag(flag_key):
        database.set_flag(flag_key, False)
        _global_bus.publish(CameraInactivityAlertResolved(mac, event.wish_name))


def _on_timed_photo_captured(event: TimedPhotoCaptured):
    """Bewertet den Aufnahme-Verzug eines erfüllten Aufnahme-Zeitpunkts (ADR 0041).

    Die Tatsache (wie spät war das Bild?) liefert der camera_receiver im Ereignis; die
    Bewertung (ab wann ist das eine Störung?) gehört hierher — Alarm-Logik hat in einem
    Transport-Adapter nichts zu suchen (ADR 0018).

    Gemeldet wird erst beim **zweiten** Verzug in Folge: Ein einzelner WLAN-Wackler soll
    nicht nachts melden, ein echtes Problem meldet sich am nächsten Aufnahme-Zeitpunkt
    ohnehin wieder.
    """
    if not config.WATCHDOG_ENABLED:
        return
    if event.mac_address is None or event.target_dt is None or event.captured_at is None:
        return

    # Ist die Kamera bereits als inaktiv gemeldet, schweigt die Verzugs-Warnung —
    # die Inaktivität ist die umfassendere Aussage.
    if database.get_flag(database.watchdog_camera_alert_key(event.mac_address)):
        return

    schwelle = config.AUFNAHME_VERZUG_SCHWELLE_MINUTEN
    verzug_minuten = (event.captured_at - event.target_dt).total_seconds() / 60

    _bewerte_stoerung(
        event.mac_address, event.wish_name,
        gestoert=verzug_minuten > schwelle,
        grund="verzug",
        verzug_minuten=verzug_minuten,
    )


def _bewerte_stoerung(mac: str, wish_name: str, gestoert: bool, grund: str,
                      verzug_minuten: float | None = None,
                      zeitpunkte: list | None = None):
    """Führt den Störungs-Zähler fort und schlägt bzw. entwarnt (Ereignis- wie Prüflauf-Pfad).

    Die Bewertung nimmt die **Tatsache** entgegen (`gestoert`), nicht eine Zahl, aus der sie
    erst geschlossen werden müsste. Ein **verpasster** Aufnahme-Zeitpunkt hat gar keine
    Aufnahmezeit — jede Minutenangabe für ihn wäre erfunden und könnte unter die Schwelle
    rutschen, womit ein Zeitpunkt ganz ohne Bild als „pünktlich" gälte (ADR 0041).

    Gemeldet wird beim **zweiten** Vorfall in Folge; ein Wechsel der Störungsart zählt mit.
    """
    streak_key = f"watchdog_delay_streak_camera_{mac}"
    flag_key = database.watchdog_camera_delay_alert_key(mac)

    if not gestoert:
        database.set_metadata(streak_key, "0")
        if database.get_flag(flag_key):
            database.set_flag(flag_key, False)
            _global_bus.publish(CameraDelayAlertResolved(mac, wish_name))
            logger.info(
                f"Watchdog-Entwarnung: Kamera '{wish_name}' trifft ihre Aufnahme-Zeitpunkte wieder."
            )
        return

    try:
        streak = int(database.get_metadata(streak_key) or 0)
    except ValueError:
        streak = 0
    streak += 1
    database.set_metadata(streak_key, str(streak))

    if streak >= 2 and not database.get_flag(flag_key):
        database.set_flag(flag_key, True)
        _global_bus.publish(
            CameraDelayAlertTriggered(
                mac, wish_name, grund,
                config.AUFNAHME_VERZUG_SCHWELLE_MINUTEN,
                verzug_minuten=verzug_minuten,
                zeitpunkte=zeitpunkte,
            )
        )
        if grund == "verpasst":
            logger.warning(
                f"Watchdog-Alert: Kamera '{wish_name}' lieferte zu zwei Aufnahme-Zeitpunkten "
                f"in Folge kein Bild."
            )
        else:
            logger.warning(
                f"Watchdog-Alert: Kamera '{wish_name}' kommt zu spät "
                f"({verzug_minuten:.0f} min nach dem Aufnahme-Zeitpunkt)."
            )


def _on_rain_sensor_measurement(event: RainSensorMeasured):
    """Sofortige Entwarnung sobald der Regensensor wieder eine Messung sendet."""
    flag_key = database.KEY_WATCHDOG_RAIN_SENSOR_ALERT
    if database.get_flag(flag_key):
        database.set_flag(flag_key, False)
        _global_bus.publish(RainSensorInactivityAlertResolved())
        logger.info("Watchdog-Entwarnung: Regensensor wieder aktiv.")


def initialize():
    """Registriert dauerhafte EventBus-Listener. Einmalig beim Daemon-Start aufrufen."""
    if not config.WATCHDOG_ENABLED:
        logger.info("Inaktivitäts-Watchdog deaktiviert (WATCHDOG_ENABLED=false).")
        return
    _global_bus.subscribe(ValveStatusReported, _on_valve_status)
    _global_bus.subscribe(CameraImageReceived, _on_camera_image)
    _global_bus.subscribe(RainSensorMeasured, _on_rain_sensor_measurement)
    _global_bus.subscribe(TimedPhotoCaptured, _on_timed_photo_captured)
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
        flag_key = database.watchdog_valve_alert_key(valve_id)

        try:
            last_up = datetime.fromisoformat(last_update_str)
        except Exception:
            continue

        hours_silent = (now - last_up).total_seconds() / 3600
        flag = database.get_flag(flag_key)

        if hours_silent > timeout_hours:
            if not flag:
                database.set_flag(flag_key, True)
                _global_bus.publish(
                    InactivityAlertTriggered(wish_name, valve_id, hours_silent, int(timeout_hours))
                )
                logger.warning(f"Watchdog-Alert: Ventil '{wish_name}' seit {hours_silent:.1f}h still.")
        else:
            if flag:
                # Ventil wurde zwischen zwei Checks reaktiviert (z.B. nach Daemon-Neustart)
                database.set_flag(flag_key, False)
                _global_bus.publish(InactivityAlertResolved(wish_name, valve_id))
                logger.info(f"Watchdog-Entwarnung (Check): Ventil '{wish_name}' wieder aktiv.")

    # --- Kameras ---
    for camera in database.get_all_cameras():
        last_seen_str = camera.get("last_seen")
        if not last_seen_str:
            continue
            
        mac = camera["mac_address"]
        wish_name = camera["wish_name"]
        flag_key = database.watchdog_camera_alert_key(mac)
        sleep_sec = camera.get("sleep_duration_seconds", 900)
        
        # Dynamisches Limit: 3 * sleep_duration_seconds, mind. 3600 Sekunden (1h)
        timeout_seconds = max(3 * sleep_sec, 3600)
        
        try:
            last_seen = datetime.fromisoformat(last_seen_str)
        except Exception:
            continue
            
        seconds_silent = (now - last_seen).total_seconds()
        flag = database.get_flag(flag_key)
        
        if seconds_silent > timeout_seconds:
            if not flag:
                database.set_flag(flag_key, True)
                _global_bus.publish(
                    CameraInactivityAlertTriggered(mac, wish_name, int(seconds_silent), timeout_seconds)
                )
                logger.warning(f"Watchdog-Alert: Kamera '{wish_name}' seit {seconds_silent:.0f}s still.")
        else:
            if flag:
                database.set_flag(flag_key, False)
                _global_bus.publish(CameraInactivityAlertResolved(mac, wish_name))
                logger.info(f"Watchdog-Entwarnung (Check): Kamera '{wish_name}' wieder aktiv.")

    # --- Aufnahme-Verzug der Kameras (ADR 0041) ---
    # Ein Aufnahme-Zeitpunkt, der abgelöst wurde, ohne je ein Bild erhalten zu haben, gilt als
    # maximal verzögert. Der Ereignis-Pfad (_on_timed_photo_captured) sieht nur erfüllte
    # Zeitpunkte — ausgebliebene bemerkt niemand, wenn nicht hier nachgesehen wird.
    # Zeitpläne und Fotozeiten sind kameraunabhängig — einmal lesen, nicht je Kamera.
    schedules = database.get_schedules()
    photo_times = database.get_photo_times()

    for camera in database.get_all_cameras():
        mac = camera["mac_address"]
        wish_name = camera["wish_name"]

        # Ist die Kamera bereits als inaktiv gemeldet, schweigt die Verzugs-Warnung.
        if database.get_flag(database.watchdog_camera_alert_key(mac)):
            continue

        zuletzt = _als_zeitpunkt(database.get_metadata(f"last_delivered_target:{mac}"))
        bereits_bewertet = _als_zeitpunkt(
            database.get_metadata(f"watchdog_delay_last_judged_camera_{mac}")
        )

        verpasst = camera_schedule.verpasste_aufnahme_zeitpunkte(
            now, schedules, photo_times, config.CAMERA_AFTER_GUSS_OFFSET_MINUTES, zuletzt,
        )

        for target_dt in verpasst:
            if bereits_bewertet is not None and target_dt <= bereits_bewertet:
                continue  # in einem früheren Prüflauf schon gezählt
            database.set_metadata(
                f"watchdog_delay_last_judged_camera_{mac}", target_dt.isoformat()
            )
            bereits_bewertet = target_dt
            logger.warning(
                f"Aufnahme-Zeitpunkt {target_dt:%d.%m. %H:%M} der Kamera '{wish_name}' "
                f"blieb ohne Bild."
            )
            # Ein verpasster Zeitpunkt ist IMMER eine Störung: Es gibt kein Bild und damit
            # keinen Verzug, den man gegen eine Schwelle halten könnte.
            _bewerte_stoerung(
                mac, wish_name, gestoert=True, grund="verpasst",
                zeitpunkte=[f"{target_dt:%H:%M}"],
            )

    # --- Regensensor ---
    last_rain = database.get_last_rain_measurement()
    if last_rain:
        flag_key = database.KEY_WATCHDOG_RAIN_SENSOR_ALERT
        timeout_hours = config.RAIN_SENSOR_OFFLINE_HOURS
        try:
            last_rain_time = datetime.fromisoformat(last_rain["timestamp"])
            hours_silent = (now - last_rain_time).total_seconds() / 3600
            flag = database.get_flag(flag_key)
            if hours_silent > timeout_hours:
                if not flag:
                    database.set_flag(flag_key, True)
                    _global_bus.publish(RainSensorInactivityAlertTriggered(hours_silent, timeout_hours))
                    logger.warning(f"Watchdog-Alert: Regensensor seit {hours_silent:.1f}h still.")
            else:
                if flag:
                    database.set_flag(flag_key, False)
                    _global_bus.publish(RainSensorInactivityAlertResolved())
                    logger.info("Watchdog-Entwarnung (Check): Regensensor wieder aktiv.")
        except Exception:
            pass
