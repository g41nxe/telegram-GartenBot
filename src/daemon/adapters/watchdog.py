import logging
from datetime import datetime

from . import database
from .. import config
from .. import camera_daylight
from .mqtt_client import _global_bus
from ..core.watchdog_events import InactivityAlertTriggered, InactivityAlertResolved
from ..core.valve_events import ValveStatusReported
from ..core.camera_events import (CameraImageReceived, CameraInactivityAlertTriggered,
                                  CameraInactivityAlertResolved, TimedPhotoCaptured,
                                  CameraDelayAlertTriggered, CameraDelayAlertResolved)
from ..core.sensor_events import RainSensorMeasured, RainSensorInactivityAlertTriggered, RainSensorInactivityAlertResolved
from ..core import camera_schedule
from ..core import edge_alarm
from ..core import watchdog_threshold

logger = logging.getLogger("garden_watchdog")


def _als_zeitpunkt(iso: str | None) -> datetime | None:
    """Liest einen ISO-Zeitstempel aus system_metadata; unlesbare Werte gelten als unbekannt."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def _check_edge(flag_key: str, faulted: bool, on_raise, on_clear):
    """Owns the I/O around one edge-triggered alarm: read the flag, ask the pure
    ``edge_alarm.evaluate`` for the transition, persist a changed flag, publish the event.

    Returns the emitted event (or ``None`` when the state was stable) so the caller can log
    its device-specific line. This is the single place the flag-read/compare/write/publish
    dance lives — every alarm class and both the event- and check-path go through here
    (Ticket 6r2).
    """
    flag = database.get_flag(flag_key)
    new_flag, event = edge_alarm.evaluate(faulted, flag, on_raise, on_clear)
    if new_flag != flag:
        database.set_flag(flag_key, new_flag)
    if event is not None:
        _global_bus.publish(event)
    return event


def _on_valve_status(event: ValveStatusReported):
    """Sofortige Entwarnung sobald ein Ventil wieder ein Signal sendet."""
    valve = database.get_valve_by_mqtt_name(event.mqtt_name)
    if not valve:
        return
    valve_id = valve["id"]
    # Ein Signal heißt „nicht mehr gestört" (faulted=False) — der Ereignis-Pfad kann nur entwarnen.
    _check_edge(
        database.watchdog_valve_alert_key(valve_id),
        faulted=False,
        on_raise=lambda: None,
        on_clear=lambda: InactivityAlertResolved(valve["wish_name"], valve_id),
    )


def _on_camera_image(event: CameraImageReceived):
    """Sofortige Entwarnung sobald ein Kamerabild erfolgreich empfangen wurde."""
    mac = event.mac_address
    _check_edge(
        database.watchdog_camera_alert_key(mac),
        faulted=False,
        on_raise=lambda: None,
        on_clear=lambda: CameraInactivityAlertResolved(mac, event.wish_name),
    )


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
        database.set_int_metadata(streak_key, 0)
        streak = 0
    else:
        streak = database.get_int_metadata(streak_key, 0) + 1
        database.set_int_metadata(streak_key, streak)

    # Entprellung: Gemeldet wird erst beim zweiten Vorfall in Folge — die „zweiter Vorfall"-
    # Bedingung fließt als Störungs-Zustand in die Flanke ein (streak >= 2).
    #
    # Ein entprellter Alarm ist drei-, nicht zweiwertig: melden / entwarnen / *noch abwarten*.
    # Die reine Flanke kennt nur melden/entwarnen — den Abwarte-Zustand (gestört, aber Streak
    # noch < 2) hält der Treiber hier heraus: eine Störung darf NIE entwarnen, egal wie der
    # Streak-Zähler steht (Absicherung gegen Flag/Streak-Desync nach OTA-Migration oder Race).
    if gestoert and streak < 2:
        return

    event = _check_edge(
        flag_key,
        faulted=(gestoert and streak >= 2),
        on_raise=lambda: CameraDelayAlertTriggered(
            mac, wish_name, grund,
            config.AUFNAHME_VERZUG_SCHWELLE_MINUTEN,
            verzug_minuten=verzug_minuten,
            zeitpunkte=zeitpunkte,
        ),
        on_clear=lambda: CameraDelayAlertResolved(mac, wish_name),
    )

    if isinstance(event, CameraDelayAlertResolved):
        logger.info(
            f"Watchdog-Entwarnung: Kamera '{wish_name}' trifft ihre Aufnahme-Zeitpunkte wieder."
        )
    elif isinstance(event, CameraDelayAlertTriggered):
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
    resolved = _check_edge(
        database.KEY_WATCHDOG_RAIN_SENSOR_ALERT,
        faulted=False,
        on_raise=lambda: None,
        on_clear=lambda: RainSensorInactivityAlertResolved(),
    )
    if resolved is not None:
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

    max_seconds = config.WATCHDOG_VALVE_TIMEOUT_HOURS * 3600
    min_seconds = config.WATCHDOG_VALVE_MIN_TIMEOUT_MINUTES * 60
    factor = config.WATCHDOG_VALVE_INTERVAL_FACTOR
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

        # Wie lange darf dieses Ventil schweigen? Nicht 24 Stunden für alle, sondern ein
        # Vielfaches seines eigenen Melde-Takts (Ticket 8zj). Ohne Messdaten bleibt es
        # beim konfigurierten Fixwert.
        interval = database.get_device_report_interval_seconds(valve["mqtt_name"])
        timeout_seconds = watchdog_threshold.valve_timeout_seconds(
            interval, min_seconds, max_seconds, factor
        )
        timeout_hours = timeout_seconds / 3600

        event = _check_edge(
            flag_key,
            faulted=(hours_silent * 3600 > timeout_seconds),
            on_raise=lambda: InactivityAlertTriggered(wish_name, valve_id, hours_silent, timeout_hours),
            on_clear=lambda: InactivityAlertResolved(wish_name, valve_id),
        )
        if isinstance(event, InactivityAlertTriggered):
            logger.warning(
                f"Watchdog-Alert: Ventil '{wish_name}' seit {hours_silent:.1f}h still "
                f"(Schwelle {timeout_hours:.1f}h bei Melde-Takt "
                f"{f'{interval:.0f}s' if interval else 'unbekannt'})."
            )
        elif isinstance(event, InactivityAlertResolved):
            # Ventil wurde zwischen zwei Checks reaktiviert (z.B. nach Daemon-Neustart)
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

        event = _check_edge(
            flag_key,
            faulted=(seconds_silent > timeout_seconds),
            on_raise=lambda: CameraInactivityAlertTriggered(mac, wish_name, int(seconds_silent), timeout_seconds),
            on_clear=lambda: CameraInactivityAlertResolved(mac, wish_name),
        )
        if isinstance(event, CameraInactivityAlertTriggered):
            logger.warning(f"Watchdog-Alert: Kamera '{wish_name}' seit {seconds_silent:.0f}s still.")
        elif isinstance(event, CameraInactivityAlertResolved):
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

        zuletzt = _als_zeitpunkt(database.get_metadata(database.last_delivered_target_key(mac)))
        bereits_bewertet = _als_zeitpunkt(
            database.get_metadata(f"watchdog_delay_last_judged_camera_{mac}")
        )

        verpasst = camera_schedule.verpasste_aufnahme_zeitpunkte(
            now, schedules, photo_times, config.CAMERA_AFTER_GUSS_OFFSET_MINUTES, zuletzt,
            # Ein bei Dunkelheit unterdrueckter Zeitpunkt ist kein Verzug, sondern Absicht.
            photo_allowed=camera_daylight.build_photo_filter(),
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
            event = _check_edge(
                flag_key,
                faulted=(hours_silent > timeout_hours),
                on_raise=lambda: RainSensorInactivityAlertTriggered(hours_silent, timeout_hours),
                on_clear=lambda: RainSensorInactivityAlertResolved(),
            )
            if isinstance(event, RainSensorInactivityAlertTriggered):
                logger.warning(f"Watchdog-Alert: Regensensor seit {hours_silent:.1f}h still.")
            elif isinstance(event, RainSensorInactivityAlertResolved):
                logger.info("Watchdog-Entwarnung (Check): Regensensor wieder aktiv.")
        except Exception:
            pass
