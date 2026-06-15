import json
import logging
import re
import subprocess
import threading
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from .. import config
from ..adapters import database
from . import telegram_client

_VERSION_FILE = Path(__file__).resolve().parent.parent.parent.parent / "VERSION"
from ..adapters.daily_report import generate_daily_report as _generate_daily_report
from ..adapters.mqtt_client import _global_bus
from ..core.weather_codes import get_wmo_description as _get_wmo_description
from ..core.watering_controller import (
    WateringCycleStarted,
    WateringCycleCompleted,
    WateringCycleFailed,
    WateringCycleStopped
)
from ..core.scheduler_events import (
    DailyReportTriggered,
    WateringSkipped,
    ScheduleFailed
)
from ..core.watchdog_events import InactivityAlertTriggered, InactivityAlertResolved
from ..core.camera_events import CameraInactivityAlertTriggered, CameraInactivityAlertResolved
logger = logging.getLogger("garden_telegram_ui")

# Module-level controller reference — set once at daemon startup by main.py
_watering_ctrl = None

def set_watering_controller(ctrl) -> None:
    """Verdrahtet die Guss-Steuerung für manuelle Bewässerungsbefehle. Einmalig von main.py aufrufen."""
    global _watering_ctrl
    _watering_ctrl = ctrl

# Zustandsbasierter Zeitplan-Assistent (Wizard) und manuelle Bewässerung
wizard_states = {}  # { chat_id: { "step": int/str, "name": str, ..., "last_active": datetime } }
manual_states = {}  # { chat_id: { "step": int/str, "duration": int, "volume": int, "last_active": datetime } }
delete_states = {}  # { chat_id: { "schedule_id": int, "name": str, "last_active": datetime } }

_state_lock = threading.Lock()
WIZARD_TTL_SECONDS = 600  # 10 minutes of inactivity expires a wizard session


def _read_local_version() -> str:
    if _VERSION_FILE.exists():
        return _VERSION_FILE.read_text().strip()
    return "unbekannt"


def _fetch_latest_release_info() -> dict:
    """Gibt {"tag": str, "name": str, "notes": str} zurück. Felder sind "?" / "" bei Fehler."""
    if not config.GITHUB_PAT or not config.GITHUB_REPO:
        return {"tag": "?", "name": "?", "notes": ""}
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/releases/latest"
    try:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {config.GITHUB_PAT}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "GardenIrrigationDaemon/1.0",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return {
                "tag":   data.get("tag_name", "?"),
                "name":  data.get("name", "?"),
                "notes": data.get("body", ""),
            }
    except Exception:
        return {"tag": "?", "name": "?", "notes": ""}


def handle_update(chat_id: int):
    local = _read_local_version()
    info = _fetch_latest_release_info()
    remote_tag = info["tag"]
    remote_name = info["name"]
    notes_raw = info["notes"] or ""

    if local == remote_tag:
        telegram_client.send_message(
            chat_id,
            f"✅ Bereits aktuell ({local}). Kein Update verfügbar."
        )
        return

    if len(notes_raw) > 800:
        notes_raw = notes_raw[:800] + "…"
    notes_section = f"\n\n📋 **Was ist neu:**\n{notes_raw}" if notes_raw else ""

    telegram_client.send_message(
        chat_id,
        f"🔄 **Software-Update verfügbar**\n\n"
        f"Installiert: `{local}`\n"
        f"Verfügbar:   `{remote_name}`"
        f"{notes_section}\n\n"
        f"Soll das Update jetzt installiert werden?\n"
        f"_(Dauer: ca. 1–5 Minuten. Der Daemon startet neu.)_",
        {
            "inline_keyboard": [[
                {"text": "✓ Jetzt installieren", "callback_data": "update_confirm"},
                {"text": "✗ Abbrechen",          "callback_data": "update_cancel"},
            ]]
        }
    )


def _cleanup_expired_states():
    """Remove wizard/manual/delete sessions that have been inactive for longer than WIZARD_TTL_SECONDS."""
    cutoff = datetime.now() - timedelta(seconds=WIZARD_TTL_SECONDS)
    with _state_lock:
        expired_wizard = [cid for cid, s in wizard_states.items() if s.get("last_active", datetime.min) < cutoff]
        expired_manual = [cid for cid, s in manual_states.items() if s.get("last_active", datetime.min) < cutoff]
        expired_delete = [cid for cid, s in delete_states.items() if s.get("last_active", datetime.min) < cutoff]
        for cid in expired_wizard:
            del wizard_states[cid]
        for cid in expired_manual:
            del manual_states[cid]
        for cid in expired_delete:
            del delete_states[cid]


def _state_get(d: dict, chat_id: int) -> dict | None:
    """Thread-safely retrieve a state entry; returns None if absent."""
    with _state_lock:
        return d.get(chat_id)


def _state_set(d: dict, chat_id: int, value: dict):
    """Thread-safely set a state entry, stamping last_active."""
    with _state_lock:
        d[chat_id] = {**value, "last_active": datetime.now()}


def _state_touch(d: dict, chat_id: int):
    """Thread-safely update the last_active timestamp on an existing entry."""
    with _state_lock:
        if chat_id in d:
            d[chat_id]["last_active"] = datetime.now()


def _state_del(d: dict, chat_id: int):
    """Thread-safely remove a state entry; no-op if absent."""
    with _state_lock:
        d.pop(chat_id, None)


# --- Hauptmenüs (Tastaturen) ---

def get_main_keyboard() -> dict:
    """Erstellt die permanente Haupttastatur unten im Chat."""
    rows = [
        [{"text": "📊 Status anzeigen"}, {"text": "📅 Zeitpläne"}],
        [{"text": "🟢 Bewässern starten"}, {"text": "🔴 Sofort Stopp"}],
        [{"text": "📸 Foto anzeigen"}, {"text": "⚙️ Setup"}],
    ]
    return {
        "keyboard": rows,
        "resize_keyboard": True
    }

def get_camera_resolution_keyboard() -> dict:
    """Inline-Keyboard für die Auflösungsauswahl im Kamera-Kopplungs-Assistenten."""
    return {
        "inline_keyboard": [
            [
                {"text": "🏔 Hoch (1600×1200)", "callback_data": "camsetup_res_UXGA"},
                {"text": "⚡ Mittel (1024×768)", "callback_data": "camsetup_res_XGA"},
            ],
            [{"text": "💨 Niedrig (640×480)", "callback_data": "camsetup_res_VGA"}],
            [{"text": "❌ Abbrechen", "callback_data": "camsetup_cancel"}],
        ]
    }

def get_camera_quality_keyboard() -> dict:
    """Inline-Keyboard für die Bildqualitäts-Auswahl im Kamera-Kopplungs-Assistenten."""
    return {
        "inline_keyboard": [
            [
                {"text": "🌟 Hoch", "callback_data": "camsetup_qual_high"},
                {"text": "⚡ Mittel", "callback_data": "camsetup_qual_medium"},
            ],
            [{"text": "💨 Niedrig", "callback_data": "camsetup_qual_low"}],
            [{"text": "❌ Abbrechen", "callback_data": "camsetup_cancel"}],
        ]
    }

def get_schedules_keyboard() -> dict:
    """Erstellt ein Inline-Keyboard zum Starten des geführten Zeitplan-Assistenten."""
    return {
        "inline_keyboard": [
            [{"text": "➕ Neuer Zeitplan", "callback_data": "wiz_start"}]
        ]
    }

def get_schedules_inline_keyboard(schedules: list) -> dict:
    """Erstellt ein Inline-Keyboard mit Toggle- und Lösch-Button pro Zeitplan."""
    rows = []
    for s in schedules:
        icon = "🟢" if s['is_active'] == 1 else "🔴"
        rows.append([
            {"text": f"{icon} {s['name']} ({s['time']})", "callback_data": f"sched_toggle_{s['id']}"},
            {"text": "🗑️", "callback_data": f"sched_delete_ask_{s['id']}"}
        ])
    rows.append([{"text": "➕ Neuer Zeitplan", "callback_data": "wiz_start"}])
    return {"inline_keyboard": rows}

def get_hour_keyboard() -> dict:
    """Erstellt ein kompaktes 6x4 Grid für alle 24 Stunden."""
    rows = []
    for r in range(4):
        row = []
        for c in range(6):
            h = r * 6 + c
            row.append({"text": f"{h:02d}", "callback_data": f"wiz_hour_{h}"})
        rows.append(row)
    rows.append([{"text": "❌ Abbrechen", "callback_data": "wiz_cancel"}])
    return {"inline_keyboard": rows}

def get_minute_keyboard() -> dict:
    """Erstellt ein Keyboard für Minuten in 5-Minuten-Schritten."""
    rows = []
    for r in range(3):
        row = []
        for c in range(4):
            m = (r * 4 + c) * 5
            row.append({"text": f"{m:02d}", "callback_data": f"wiz_min_{m}"})
        rows.append(row)
    rows.append([{"text": "❌ Abbrechen", "callback_data": "wiz_cancel"}])
    return {"inline_keyboard": rows}

def get_duration_wizard_keyboard(prefix: str) -> dict:
    """Erstellt ein Inline-Keyboard für die Schnellauswahl der Dauer."""
    return {
        "inline_keyboard": [
            [
                {"text": "⏱️ 5 Min", "callback_data": f"{prefix}_dur_5"},
                {"text": "⏱️ 10 Min", "callback_data": f"{prefix}_dur_10"}
            ],
            [
                {"text": "⏱️ 15 Min", "callback_data": f"{prefix}_dur_15"},
                {"text": "⏱️ 20 Min", "callback_data": f"{prefix}_dur_20"}
            ],
            [
                {"text": "⏱️ 25 Min", "callback_data": f"{prefix}_dur_25"},
                {"text": "✏️ Eigene Dauer", "callback_data": f"{prefix}_dur_custom"}
            ],
            [
                {"text": "❌ Abbrechen", "callback_data": f"{prefix}_cancel"}
            ]
        ]
    }

def get_volume_wizard_keyboard(prefix: str) -> dict:
    """Erstellt ein Inline-Keyboard mit gärtnerisch sinnvollen Vorschlägen für Kleingärten."""
    return {
        "inline_keyboard": [
            [
                {"text": "🌱 10 Liter", "callback_data": f"{prefix}_vol_10"},
                {"text": "🥬 25 Liter", "callback_data": f"{prefix}_vol_25"}
            ],
            [
                {"text": "🍅 50 Liter", "callback_data": f"{prefix}_vol_50"},
                {"text": "🥦 80 Liter", "callback_data": f"{prefix}_vol_80"}
            ],
            [
                {"text": "✏️ Eigene Menge", "callback_data": f"{prefix}_vol_custom"}
            ],
            [
                {"text": "❌ Abbrechen", "callback_data": f"{prefix}_cancel"}
            ]
        ]
    }

def get_days_wizard_keyboard(selected_days: list) -> dict:
    """Erstellt ein Inline-Keyboard für die Wochentag-Auswahl mit Checkmarks."""
    day_map = [
        ("Mon", "Mo"),
        ("Tue", "Di"),
        ("Wed", "Mi"),
        ("Thu", "Do"),
        ("Fri", "Fr"),
        ("Sat", "Sa"),
        ("Sun", "So")
    ]

    row1 = []
    for eng, ger in day_map[:4]:
        has_sel = eng in selected_days and "everyday" not in selected_days
        label = f"✅ {ger}" if has_sel else ger
        row1.append({"text": label, "callback_data": f"wiz_day_{eng}"})

    row2 = []
    for eng, ger in day_map[4:]:
        has_sel = eng in selected_days and "everyday" not in selected_days
        label = f"✅ {ger}" if has_sel else ger
        row2.append({"text": label, "callback_data": f"wiz_day_{eng}"})

    is_everyday = "everyday" in selected_days
    everyday_label = "✅ Täglich" if is_everyday else "Täglich"
    row2.append({"text": everyday_label, "callback_data": "wiz_day_everyday"})

    return {
        "inline_keyboard": [
            row1,
            row2,
            [
                {"text": "❌ Abbrechen", "callback_data": "wiz_cancel"},
                {"text": "✅ Weiter", "callback_data": "wiz_save"}
            ]
        ]
    }

def format_days_german(days_list: list) -> str:
    """Formatiert die Wochentagsliste in lesbares Deutsch."""
    if "everyday" in days_list:
        return "Täglich"
    day_mapping = {
        "Mon": "Mo", "Tue": "Di", "Wed": "Mi", "Thu": "Do", "Fri": "Fr", "Sat": "Sa", "Sun": "So"
    }
    ordered_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    present_days = [day_mapping[d] for d in ordered_days if d in days_list]
    return ", ".join(present_days) if present_days else "Keine Tage ausgewählt"

def get_duration_keyboard() -> dict:
    """Erstellt ein Inline-Keyboard für die Schnellauswahl der manuellen Bewässerungsdauer."""
    return {
        "inline_keyboard": [
            [
                {"text": "⏱️ 5 Min", "callback_data": "water_5"},
                {"text": "⏱️ 10 Min", "callback_data": "water_10"}
            ],
            [
                {"text": "⏱️ 15 Min", "callback_data": "water_15"},
                {"text": "⏱️ 20 Min", "callback_data": "water_20"}
            ],
            [
                {"text": "❌ Abbrechen", "callback_data": "cancel"}
            ]
        ]
    }

def _get_battery_description(battery_val) -> str:
    try:
        b = int(battery_val)
    except (TypeError, ValueError):
        b = 0
    suffix = "" if b == 100 else f" ({b}%)"
    if b > 60:
        return f"🔋 Voll{suffix}"
    if b > 20:
        return f"🔋 Mittel{suffix}"
    if b > 0:
        return f"🪫 Schwach{suffix}"
    return "🪫 Unbekannt"

def _get_lqi_description(lqi_val) -> str:
    """Übersetzt den LQI-Wert (0-255) in eine menschenlesbare Beschreibung."""
    try:
        lqi = int(lqi_val)
    except (TypeError, ValueError):
        lqi = 0

    if lqi >= 180:
        return f"🟢 Sehr gut ({lqi} LQI)"
    elif lqi >= 120:
        return f"🟢 Gut ({lqi} LQI)"
    elif lqi >= 60:
        return f"🟡 Ausreichend ({lqi} LQI)"
    elif lqi > 0:
        return f"🔴 Kritisch ({lqi} LQI)"
    else:
        return "🔴 Keine Verbindung (0 LQI)"

# --- Befehlsverarbeitung ---

def _start_pairing(chat_id: int, wish_name: str):
    from ..adapters import valve_pairing as pairing
    telegram_client.send_message(
        chat_id,
        f'🔧 *Ventil-Kopplung gestartet* - "{wish_name}"\n\n'
        "Bitte drücke jetzt den *Reset-Knopf* am Sonoff Hydro ONE für "
        "*5 Sekunden*, bis die LED schnell blinkt.\n\n"
        "⏱️ Das System wartet bis zu 90 Sekunden auf das Ventil."
    )
    pairing.start_pairing(chat_id, telegram_client.send_message, wish_name)

def handle_setup_menu(chat_id: int):
    """Zeigt das Setup-Untermenü mit Kopplungs- und Einstellungsoptionen."""
    telegram_client.send_message(
        chat_id,
        "⚙️ *Setup*\n\nWas möchtest du einrichten?",
        {
            "inline_keyboard": [
                [
                    {"text": "🔧 Ventil koppeln", "callback_data": "setup_confirm"},
                    {"text": "📷 Kamera koppeln", "callback_data": "camsetup_start"},
                ],
                [{"text": "⏱ Kamera-Einstellungen", "callback_data": "camsetup_settings"}],
            ]
        }
    )

def handle_setup(chat_id: int):
    from ..adapters import valve_pairing as pairing

    if pairing.is_pairing_active():
        telegram_client.send_message(
            chat_id,
            "⏳ Eine Ventil-Kopplung läuft bereits im Hintergrund. Bitte warten."
        )
        return

    _state_set(wizard_states, chat_id, {"step": "setup_wish_name"})
    telegram_client.send_message(
        chat_id,
        "🔧 *Neues Ventil koppeln*\n\n"
        "Wie soll dieses Ventil heißen?\n"
        "_(z.B. \"Terrasse\", \"Rasen\", \"Hochbeet\")_\n\n"
        "Bitte tippe den Namen ein:"
    )

def handle_camera_setup(chat_id: int):
    from ..adapters import camera_pairing
    if camera_pairing.is_pairing_active():
        telegram_client.send_message(chat_id, "⏳ Eine Kamera-Kopplung läuft bereits im Hintergrund. Bitte warten.")
        return

    _state_set(wizard_states, chat_id, {"step": "setup_camera_wish_name"})
    telegram_client.send_message(
        chat_id,
        "📷 *Neue Kamera koppeln*\n\n"
        "Wie soll diese Kamera heißen?\n"
        "_(Erlaubte Zeichen: a-z, A-Z, 0-9, Bindestrich, Unterstrich. Max 32 Zeichen)_\n\n"
        "Bitte tippe den Namen ein:"
    )

def handle_photo(chat_id: int):
    cameras = database.get_all_cameras()
    if not cameras:
        telegram_client.send_message(chat_id, "❌ Es sind keine Kameras gekoppelt.")
        return
        
    if len(cameras) == 1:
        _send_latest_photo(chat_id, cameras[0]["wish_name"])
    else:
        rows = []
        for cam in cameras:
            rows.append([{"text": cam["wish_name"], "callback_data": f"camphoto_{cam['wish_name']}"}])
        telegram_client.send_message(
            chat_id,
            "Von welcher Kamera möchtest du das aktuellste Foto sehen?",
            {"inline_keyboard": rows}
        )

def _send_latest_photo(chat_id: int, wish_name: str):
    latest_path = Path(config.CAMERA_IMAGE_DIR) / wish_name / "latest.jpg"
    if latest_path.exists():
        with open(latest_path, "rb") as f:
            photo_bytes = f.read()
        ts = datetime.fromtimestamp(latest_path.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
        telegram_client.send_photo(chat_id, photo_bytes, caption=f"📸 '{wish_name}' — {ts} Uhr")
    else:
        telegram_client.send_message(chat_id, f"❌ Kein Foto für Kamera '{wish_name}' gefunden.")

def handle_camera_interval(chat_id: int, text: str):
    try:
        parts = text.split(" ")
        if len(parts) < 2:
            raise ValueError
        minutes = int(parts[1])
        if not (1 <= minutes <= 60):
            telegram_client.send_message(chat_id, "❌ Das Intervall muss zwischen 1 und 60 Minuten liegen.")
            return
            
        cameras = database.get_all_cameras()
        if not cameras:
            telegram_client.send_message(chat_id, "❌ Es sind keine Kameras gekoppelt.")
            return
            
        if len(cameras) == 1:
            mac = cameras[0]["mac_address"]
            database.update_camera_settings(mac, sleep_seconds=minutes*60, resolution=cameras[0]["resolution"], quality=cameras[0]["quality"])
            telegram_client.send_message(chat_id, f"✅ Sendeintervall für Kamera '{cameras[0]['wish_name']}' auf {minutes} Minuten gesetzt.")
        else:
            rows = []
            for cam in cameras:
                rows.append([{"text": cam["wish_name"], "callback_data": f"camint_{cam['mac_address']}_{minutes}"}])
            telegram_client.send_message(
                chat_id,
                f"Wähle die Kamera, deren Intervall auf {minutes} Minuten gesetzt werden soll:",
                {"inline_keyboard": rows}
            )
            
    except ValueError:
        telegram_client.send_message(chat_id, "❌ **Ungültiges Format.** Nutzen Sie: `/camera_interval <minuten>` (z.B. `/camera_interval 15`)")

def handle_status(chat_id: int):
    from ..adapters import mqtt_client
    import time

    mqtt_client.request_valve_status()
    time.sleep(1.5)

    broker_connected = mqtt_client.is_broker_connected()
    bridge_online = mqtt_client.get_bridge_status() == "online"

    if not mqtt_client.HAS_PAHO:
        services_status = "⚡ Simulationsmodus (Lokaler Test)"
        services_ok = True
    elif not broker_connected:
        services_status = "🔴 Inaktiv (MQTT-Broker nicht erreichbar)"
        services_ok = False
    elif not bridge_online:
        services_status = "🔴 Inaktiv (Mittelweg-Dienst offline)"
        services_ok = False
    else:
        services_status = "🟢 Aktiv"
        services_ok = True

    active = _watering_ctrl.get_active_cycle() if _watering_ctrl else None
    active_text = ""
    if active:
        active_text = (
            f"\n⚡ **Laufender Zyklus:**\n"
            f"   - Gestartet: {active['source'].upper()}\n"
            f"   - Restzeit: {int(active['remaining_seconds']/60)} Min ({active['remaining_seconds'] % 60} Sek)\n"
        )

    # Pro-Ventil-Abschnitt aus der Datenbank
    valves = database.get_all_valves()
    valve_sections = []
    for valve in valves:
        wish_name = valve["wish_name"]
        mqtt_name = valve["mqtt_name"]
        battery = valve.get("battery") or 0
        lqi = valve.get("linkquality") or 0
        last_update_str = valve.get("last_update")
        battery_label = _get_battery_description(battery)

        if not services_ok:
            conn_text = "🔴 Offline (Dienste gestört)"
        elif not last_update_str:
            conn_text = "🔴 Nicht gekoppelt / Offline"
        else:
            try:
                last_up = datetime.fromisoformat(last_update_str)
                time_str = last_up.strftime("%d.%m. %H:%M:%S Uhr")
                conn_text = f"🟢 Aktiv (Letztes Signal: {time_str})"
            except Exception:
                conn_text = "🟢 Gekoppelt / Aktiv"

        valve_sections.append(
            f"📡 **{wish_name}** (`{mqtt_name}`):\n"
            f"   - Verbindung: {conn_text}\n"
            f"   - Batterie: {battery_label}\n"
            f"   - Signalqualität: {_get_lqi_description(lqi)}\n"
        )

    valves_text = "\n".join(valve_sections) if valve_sections else "Keine Ventile registriert.\n"

    # Kamera-Abschnitt
    cameras = database.get_all_cameras()
    camera_sections = []
    for cam in cameras:
        wish_name = cam["wish_name"]
        last_seen_str = cam.get("last_seen")
        sleep_sec = cam.get("sleep_duration_seconds") or 900
        resolution = cam.get("resolution") or "UXGA"
        quality_val = cam.get("quality") or 10
        quality_label = {10: "🌟 Hoch", 25: "⚡ Mittel", 40: "💨 Niedrig"}.get(quality_val, str(quality_val))

        if not last_seen_str:
            conn_text = "🔴 Noch kein Bild empfangen"
        else:
            try:
                from datetime import timezone
                last_dt = datetime.fromisoformat(last_seen_str)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                now_utc = datetime.now(timezone.utc)
                age_sec = (now_utc - last_dt).total_seconds()
                time_str = last_dt.strftime("%d.%m. %H:%M")
                if age_sec <= sleep_sec * 2:
                    conn_text = f"🟢 Aktiv (Letztes Bild: {time_str})"
                else:
                    conn_text = f"🔴 Offline (Letztes Bild: {time_str})"
            except Exception:
                conn_text = "🔴 Unbekannt"

        camera_sections.append(
            f"📷 **{wish_name}:**\n"
            f"   - Verbindung: {conn_text}\n"
            f"   - Auflösung: {resolution} · Qualität: {quality_label}\n"
            f"   - Intervall: {sleep_sec // 60} Min\n"
        )

    cameras_text = "\n".join(camera_sections) if camera_sections else ""

    last_weather = database.get_last_weather()
    weather_text = "   - Keine Daten vorhanden"
    if last_weather:
        import json as _json
        try:
            timestamp_dt = datetime.fromisoformat(last_weather["timestamp"])
            time_str = timestamp_dt.strftime("%H:%M Uhr")
        except Exception:
            time_str = "Unbekannt"

        temp = last_weather.get("current_temp", 0.0)
        code = last_weather.get("weather_code", 0)
        desc = _get_wmo_description(code)
        current_precip = last_weather.get("current_precipitation_mm") or 0.0

        # Nächste-Stunde-Vorhersage aus hourly_forecast_json (Index 1)
        next_hour_line = ""
        raw_json = last_weather.get("hourly_forecast_json")
        if raw_json:
            try:
                fc = _json.loads(raw_json)
                fc_times = fc.get("times", [])
                fc_temp = fc.get("temp", [])
                fc_precip = fc.get("precip_mm", [])
                fc_prob = fc.get("precip_prob", [])
                fc_wmo = fc.get("wmo", [])
                if len(fc_times) > 1:
                    nxt_time = fc_times[1][11:16] if len(fc_times[1]) >= 16 else fc_times[1]
                    nxt_temp = fc_temp[1] if len(fc_temp) > 1 else "?"
                    nxt_precip = fc_precip[1] if len(fc_precip) > 1 else 0.0
                    nxt_prob = fc_prob[1] if len(fc_prob) > 1 else 0
                    nxt_desc = _get_wmo_description(fc_wmo[1] if len(fc_wmo) > 1 else 0)
                    next_hour_line = (
                        f"\n   🔜 *{nxt_time}*  {nxt_desc} · {nxt_temp}°C · {nxt_precip}mm · {nxt_prob}%"
                    )
            except Exception:
                pass

        weather_text = (
            f"   🌡 *Jetzt*  {desc} · {temp}°C · 💧 {current_precip}mm"
            f"{next_hour_line}\n"
            f"   *(Stand: {time_str})*"
        )

    history = database.get_recent_history(3)
    history_lines = []
    for h in history:
        time_obj = datetime.fromisoformat(h['timestamp'])
        time_str = time_obj.strftime("%d.%m. %H:%M")
        status_char = "✅" if h['status'] == "completed" else "🌤️" if h['status'] == "skipped" else "❌"
        history_lines.append(f"{status_char} {time_str} ({h['duration_minutes']} Min, {h['source']})")
    history_text = "\n".join(history_lines) if history_lines else "Keine Einträge vorhanden"

    version_line = f"\n\n🔧 **Version:** `{_read_local_version()}`"

    cameras_block = f"\n{cameras_text}\n" if cameras_text else ""

    msg = (
        f"📊 **System-Status Gartenbewässerung**\n\n"
        f"🔌 **System-Dienste:** {services_status}\n"
        f"{active_text}"
        f"\n{valves_text}\n"
        f"{cameras_block}"
        f"🌤️ **Wetter:**\n"
        f"{weather_text}\n\n"
        f"📜 **Letzte Zyklen:**\n{history_text}"
        f"{version_line}"
    )

    telegram_client.send_message(chat_id, msg, get_main_keyboard())

def handle_schedules(chat_id: int):
    schedules = database.get_schedules()
    if not schedules:
        msg = (
            "📅 **Zeitsteuerung**\n\n"
            "Es sind aktuell keine aktiven Zeitpläne eingerichtet.\n\n"
            "💡 **Neuen Zeitplan anlegen:**\n"
            "Klicke auf den Button unten, um den geführten Assistenten zu starten, oder nutze den klassischen `/add` Befehl.\n\n"
            "**Klassischer Befehl:**\n"
            "`/add <Name>, <Uhrzeit>, <Tage>, <Dauer>, [Menge_Liter]`\n\n"
            "**Beispiel:**\n"
            "`/add Abend-Guss, 20:15, Mon,Wed,Fri, 15, 50`"
        )
        telegram_client.send_message(chat_id, msg, get_schedules_keyboard())
        return

    lines = []
    for s in schedules:
        status = "✅ Aktiv" if s['is_active'] == 1 else "❌ Inaktiv"
        days_formatted = format_days_german(s['days'].split(',')) if s['days'] else 'Keine'
        vol_str = f"{s['target_volume_liters']} Liter" if s.get('target_volume_liters', 0) > 0 else "Keines"
        lines.append(
            f"🆔 **ID {s['id']}: {s['name']}**\n"
            f"   - ⏰ Startzeit: {s['time']} Uhr\n"
            f"   - 📅 Tage: {days_formatted}\n"
            f"   - ⏳ Dauer: {s['duration_minutes']} Min\n"
            f"   - 💧 Menge: {vol_str}\n"
            f"   - Status: {status}\n"
        )

    msg = "📅 **Aktuelle Zeitsteuerung (Zeitpläne):**\n\n" + "\n".join(lines)
    telegram_client.send_message(chat_id, msg, get_schedules_inline_keyboard(schedules))

def handle_add_schedule(chat_id: int, text: str):
    try:
        args = text.split(" ", 1)[1]
        parts = [p.strip() for p in args.split(",")]

        if len(parts) < 4:
            raise ValueError

        name, time_str, days, duration_raw = parts[:4]
        duration = int(duration_raw)
        volume = int(parts[4]) if len(parts) > 4 else 0

        datetime.strptime(time_str, "%H:%M")

        db_id = database.add_schedule(name, time_str, days, duration, volume)
        if db_id > 0:
            telegram_client.send_message(chat_id, f"📅 Zeitplan **'{name}'** erfolgreich mit ID {db_id} angelegt!")
            handle_schedules(chat_id)
        else:
            telegram_client.send_message(chat_id, "❌ Fehler beim Speichern des Zeitplans in der Datenbank.")
    except Exception:
        telegram_client.send_message(
            chat_id,
            "❌ **Ungültiges Format.**\n\n"
            "Nutzen Sie folgendes Format:\n"
            "`/add Name, HH:MM, Tage, Dauer, [Menge_Liter]` (z.B. `/add Abend, 20:00, Mon,Wed,Fri, 12, 30`)\n\n"
            "Tage: `everyday` oder kommagetrennt: `Mon,Tue,Wed,Thu,Fri,Sat,Sun`."
        )

def handle_delete_schedule(chat_id: int, text: str):
    try:
        sched_id = int(text.split(" ")[1])
        if database.delete_schedule(sched_id):
            telegram_client.send_message(chat_id, f"🗑️ Zeitplan ID {sched_id} erfolgreich gelöscht.")
            handle_schedules(chat_id)
        else:
            telegram_client.send_message(chat_id, f"❌ Zeitplan ID {sched_id} nicht gefunden.")
    except Exception:
        telegram_client.send_message(chat_id, "❌ **Ungültiges Format.** Nutzen Sie: `/delete <ID>` (z.B. `/delete 2`)")

def handle_toggle_schedule(chat_id: int, text: str):
    try:
        sched_id = int(text.split(" ")[1])
        schedules = database.get_schedules()
        target = next((s for s in schedules if s["id"] == sched_id), None)

        if target:
            new_active = 0 if target["is_active"] == 1 else 1
            database.update_schedule(
                sched_id, target["name"], target["time"],
                target["days"], target["duration_minutes"], target.get("target_volume_liters", 0), new_active
            )
            status_text = "AKTIVIERT" if new_active == 1 else "DEAKTIVIERT"
            telegram_client.send_message(chat_id, f"📅 Zeitplan **'{target['name']}'** wurde {status_text}.")
            handle_schedules(chat_id)
        else:
            telegram_client.send_message(chat_id, f"❌ Zeitplan ID {sched_id} nicht gefunden.")
    except Exception:
        telegram_client.send_message(chat_id, "❌ **Ungültiges Format.** Nutzen Sie: `/toggle <ID>` (z.B. `/toggle 1`)")

# --- Interface-Schicht-Update Callback ---

def _process_message(msg_obj: dict):
    _cleanup_expired_states()
    chat_id = msg_obj["chat"]["id"]
    text = msg_obj.get("text", "").strip()

    del_state = _state_get(delete_states, chat_id)
    if del_state is not None:
        if text == "✅ Ja, löschen":
            sched_id = del_state["schedule_id"]
            name = del_state["name"]
            _state_del(delete_states, chat_id)
            if database.delete_schedule(sched_id):
                telegram_client.send_message(chat_id, f"🗑️ Zeitplan **'{name}'** wurde gelöscht.", get_main_keyboard())
                handle_schedules(chat_id)
            else:
                telegram_client.send_message(chat_id, f"❌ Zeitplan ID {sched_id} nicht gefunden.", get_main_keyboard())
            return
        elif text == "❌ Nein, abbrechen":
            _state_del(delete_states, chat_id)
            telegram_client.send_message(chat_id, "❌ Löschvorgang abgebrochen.", get_main_keyboard())
            return
        else:
            _state_del(delete_states, chat_id)

    state = _state_get(wizard_states, chat_id)
    if state is not None:
        step = state.get("step")

        if text.startswith("/") or text in ["📊 Status anzeigen", "📅 Zeitsteuerung", "📅 Zeitpläne", "🟢 Bewässern starten", "🔴 Sofort Stopp"]:
            _state_del(wizard_states, chat_id)
        else:
            if step == "setup_wish_name":
                if not text:
                    telegram_client.send_message(chat_id, "❌ Der Name darf nicht leer sein. Bitte gib einen Namen ein:")
                    return
                wish_name = text
                _state_del(wizard_states, chat_id)
                _start_pairing(chat_id, wish_name)
                return
            elif step == "camsetup_settings_interval":
                try:
                    minutes = int(text.strip())
                    if minutes < 1 or minutes > 1440:
                        raise ValueError
                except ValueError:
                    telegram_client.send_message(chat_id, "❌ Ungültige Eingabe. Bitte eine Zahl zwischen 1 und 1440 eingeben:")
                    return
                mac = state["mac"]
                wish_name = state["wish_name"]
                _state_del(wizard_states, chat_id)
                camera = database.get_camera(mac)
                if camera:
                    database.update_camera_settings(
                        mac,
                        sleep_seconds=minutes * 60,
                        resolution=camera["resolution"],
                        quality=camera["quality"],
                    )
                    telegram_client.send_message(
                        chat_id,
                        f"✅ Sendeintervall für Kamera *'{wish_name}'* auf {minutes} Minuten gesetzt.",
                        get_main_keyboard()
                    )
                else:
                    telegram_client.send_message(chat_id, "❌ Kamera nicht mehr in der Datenbank gefunden.", get_main_keyboard())
                return
            elif step == "setup_camera_wish_name":
                if not text or not re.match(r"^[a-zA-Z0-9_-]{1,32}$", text):
                    telegram_client.send_message(chat_id, "❌ Ungültiger Name. Erlaubt: a-z, A-Z, 0-9, -, _ (Max 32 Zeichen). Bitte erneut eingeben:")
                    return
                state["wish_name"] = text
                state["step"] = "setup_camera_interval"
                _state_touch(wizard_states, chat_id)
                telegram_client.send_message(
                    chat_id,
                    "⏱ *Wie oft soll die Kamera ein Bild senden?*\n\n"
                    "Bitte gib das Intervall in Minuten ein _(z.B. `15` für alle 15 Minuten)_:"
                )
                return
            elif step == "setup_camera_interval":
                try:
                    minutes = int(text.strip())
                    if minutes < 1 or minutes > 1440:
                        raise ValueError
                except ValueError:
                    telegram_client.send_message(chat_id, "❌ Ungültige Eingabe. Bitte eine Zahl zwischen 1 und 1440 eingeben:")
                    return
                state["sleep_seconds"] = minutes * 60
                state["step"] = "setup_camera_resolution"
                _state_touch(wizard_states, chat_id)
                telegram_client.send_message(
                    chat_id,
                    "🖼 *Welche Auflösung soll die Kamera verwenden?*\n\n"
                    "Höhere Auflösung = schärfere Bilder, größere Dateien.",
                    get_camera_resolution_keyboard()
                )
                return
            elif step == 1:
                if not text:
                    telegram_client.send_message(chat_id, "❌ Der Name darf nicht leer sein. Bitte gib einen Namen ein:")
                    return
                state["name"] = text
                state["step"] = 2
                _state_touch(wizard_states, chat_id)
                telegram_client.send_message(
                    chat_id,
                    f"🆕 **Neuen Zeitplan '{text}' (Schritt 2/6)**\n\nZu welcher **Stunde** soll die Bewässerung starten?",
                    get_hour_keyboard()
                )
                return
            elif step == "custom_duration":
                try:
                    dur = int(text)
                    if not (1 <= dur <= 25):
                        raise ValueError
                    state["duration"] = dur
                    state["step"] = 5
                    _state_touch(wizard_states, chat_id)
                    telegram_client.send_message(
                        chat_id,
                        f"🆕 **Neuen Zeitplan '{state['name']}' (Schritt 5/6)**\n\nWie viel Wasser soll **maximal** fließen? (Volumenlimit)",
                        get_volume_wizard_keyboard("wiz")
                    )
                except ValueError:
                    telegram_client.send_message(chat_id, "❌ **Ungültige Eingabe.** Bitte gib eine Zahl zwischen 1 und 25 Minuten ein:")
                return
            elif step == "custom_volume":
                try:
                    vol = int(text)
                    if vol <= 0:
                        raise ValueError
                    state["volume"] = vol
                    state["step"] = 6
                    state["days"] = []
                    _state_touch(wizard_states, chat_id)
                    telegram_client.send_message(
                        chat_id,
                        f"🆕 **Neuen Zeitplan '{state['name']}' (Schritt 6/6)**\n\nWähle die **Wochentage** aus, an denen bewässert werden soll:\n\n*Ausgewählt: Keine*",
                        get_days_wizard_keyboard([])
                    )
                except ValueError:
                    telegram_client.send_message(chat_id, "❌ **Ungültige Eingabe.** Bitte gib eine Zahl größer als 0 Liter ein:")
                return

    man_state = _state_get(manual_states, chat_id)
    if man_state is not None:
        step = man_state.get("step")

        if text.startswith("/") or text in ["📊 Status anzeigen", "📅 Zeitsteuerung", "📅 Zeitpläne", "🟢 Bewässern starten", "🔴 Sofort Stopp"]:
            _state_del(manual_states, chat_id)
        else:
            if step == "man_custom_duration":
                try:
                    dur = int(text)
                    if not (1 <= dur <= 25):
                        raise ValueError
                    man_state["duration"] = dur
                    man_state["step"] = 2
                    _state_touch(manual_states, chat_id)
                    telegram_client.send_message(
                        chat_id,
                        "🟢 **Manuelle Bewässerung starten (Schritt 2/2)**\n\nWie viel Wasser soll **maximal** fließen? (Volumenlimit)",
                        get_volume_wizard_keyboard("man")
                    )
                except ValueError:
                    telegram_client.send_message(chat_id, "❌ **Ungültige Eingabe.** Bitte gib eine Zahl zwischen 1 und 25 Minuten ein:")
                return
            elif step == "man_custom_volume":
                try:
                    vol = int(text)
                    if vol <= 0:
                        raise ValueError
                    man_state["volume"] = vol
                    dur = man_state["duration"]
                    _state_del(manual_states, chat_id)

                    if _watering_ctrl:
                        success, response = _watering_ctrl.start_watering(dur, vol, "manual")
                    else:
                        success, response = False, "Guss-Steuerung nicht initialisiert."
                    if not success:
                        telegram_client.send_message(chat_id, f"❌ Fehler beim Starten: {response}", get_main_keyboard())
                except ValueError:
                    telegram_client.send_message(chat_id, "❌ **Ungültige Eingabe.** Bitte gib eine Zahl größer als 0 Liter ein:")
                return

    if text.startswith("/start"):
        telegram_client.send_message(
            chat_id,
            "👋 **Willkommen bei der Gartenbewässerung-Steuerung!**\n\n"
            "Ich bin Ihr lokaler Assistent. Nutzen Sie die Buttons unten oder "
            "die Chat-Befehle `/status` und `/zeitplan`, um Ihr System zu steuern.",
            get_main_keyboard()
        )
    elif text == "📊 Status anzeigen" or text.startswith("/status"):
        handle_status(chat_id)
    elif text.startswith("/report") or text.startswith("/statusbericht"):
        from ..adapters import mqtt_client as _mc, chart as _chart
        import time as _time

        _mc.request_valve_status()
        _time.sleep(5.0)

        today_str = datetime.now().strftime("%Y-%m-%d")
        report_text = _generate_daily_report(today_str)

        chart_result = _chart.generate_weather_chart()
        if chart_result:
            image_bytes, caption = chart_result
            telegram_client.send_photo(chat_id, image_bytes, caption=caption)

        telegram_client.send_message(chat_id, report_text, get_main_keyboard())
    elif text == "📅 Zeitsteuerung" or text == "📅 Zeitpläne" or text.startswith("/zeitplan"):
        handle_schedules(chat_id)
    elif text == "⚙️ Setup":
        handle_setup_menu(chat_id)
    elif text == "🔧 Ventil koppeln" or text.startswith("/setup"):
        handle_setup(chat_id)
    elif text == "📸 Foto anzeigen" or text == "📷 Foto anzeigen" or text.startswith("/photo") or (text.startswith("/camera") and not text.startswith("/camera_")):
        handle_photo(chat_id)
    elif text == "📷 Kamera koppeln" or text.startswith("/camera_setup"):
        handle_camera_setup(chat_id)
    elif text.startswith("/camera_interval"):
        handle_camera_interval(chat_id, text)
    elif text == "🟢 Bewässern starten":
        _state_set(manual_states, chat_id, {"step": 1})
        telegram_client.send_message(
            chat_id,
            "🟢 **Manuelle Bewässerung starten (Schritt 1/2)**\n\nWie lange soll **maximal** bewässert werden? (Zeitlimit)\n\n*Aus Sicherheitsgründen max. 25 Min.*",
            get_duration_wizard_keyboard("man")
        )
    elif text == "🔴 Sofort Stopp" or text.startswith("/stop"):
        if _watering_ctrl:
            success, response = _watering_ctrl.stop_watering()
        else:
            success, response = False, "Guss-Steuerung nicht initialisiert."
        if not success:
            telegram_client.send_message(chat_id, f"ℹ️ {response}")
    elif text.startswith("/add"):
        handle_add_schedule(chat_id, text)
    elif text.startswith("/delete"):
        handle_delete_schedule(chat_id, text)
    elif text.startswith("/toggle"):
        handle_toggle_schedule(chat_id, text)
    elif text.startswith("/update"):
        handle_update(chat_id)
    else:
        telegram_client.send_message(
            chat_id,
            "❓ **Unbekannter Befehl.**\n\n"
            "Verwenden Sie die Buttons oder `/status` für eine Übersicht."
        )

def _process_callback_query(cb_obj: dict):
    _cleanup_expired_states()
    cb_id = cb_obj["id"]
    chat_id = cb_obj["message"]["chat"]["id"]
    message_id = cb_obj["message"]["message_id"]
    data = cb_obj["data"]

    if data == "cancel":
        telegram_client.answer_callback_query(cb_id, "Abgebrochen")
        telegram_client.send_message(chat_id, "❌ Vorgang abgebrochen.", get_main_keyboard())
    elif data.startswith("water_"):
        duration = int(data.split("_")[1])
        telegram_client.answer_callback_query(cb_id, "Starte Bewässerung...")
        if _watering_ctrl:
            success, response = _watering_ctrl.start_watering(duration, 0, "manual")
        else:
            success, response = False, "Guss-Steuerung nicht initialisiert."
        if not success:
            telegram_client.send_message(chat_id, f"❌ Fehler: {response}", get_main_keyboard())

    elif data == "wiz_start":
        telegram_client.answer_callback_query(cb_id, "Zeitplan-Assistent gestartet")
        _state_set(wizard_states, chat_id, {"step": 1})
        telegram_client.send_message(
            chat_id,
            "🆕 **Neuen Zeitplan anlegen (Schritt 1/6)**\n\nBitte gib einen **Namen** für den Zeitplan ein (z. B. *Rasen morgens* oder *Hochbeet*):",
            {"inline_keyboard": [[{"text": "❌ Abbrechen", "callback_data": "wiz_cancel"}]]}
        )

    elif data.startswith("wiz_hour_"):
        hour = int(data.split("_")[2])
        state = _state_get(wizard_states, chat_id)
        if state is not None:
            state["hour"] = hour
            state["step"] = 3
            _state_touch(wizard_states, chat_id)
            telegram_client.answer_callback_query(cb_id, f"Stunde: {hour:02d}")
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"🆕 **Neuen Zeitplan '{state['name']}' um {hour:02d}:?? (Schritt 3/6)**\n\nZu welcher **Minute** soll die Bewässerung starten?",
                get_minute_keyboard()
            )

    elif data.startswith("wiz_min_"):
        minute = int(data.split("_")[2])
        state = _state_get(wizard_states, chat_id)
        if state is not None:
            state["minute"] = minute
            state["step"] = 4
            _state_touch(wizard_states, chat_id)
            telegram_client.answer_callback_query(cb_id, f"Minute: {minute:02d}")
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"🆕 **Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{minute:02d} (Schritt 4/6)**\n\nWie lange soll **maximal** bewässert werden? (Zeitlimit)\n\n*Aus Sicherheitsgründen max. 25 Min.*",
                get_duration_wizard_keyboard("wiz")
            )

    elif data.startswith("wiz_dur_"):
        dur_str = data.split("_")[2]
        state = _state_get(wizard_states, chat_id)
        if state is not None:
            telegram_client.answer_callback_query(cb_id)
            if dur_str == "custom":
                state["step"] = "custom_duration"
                _state_touch(wizard_states, chat_id)
                telegram_client.edit_message_text(
                    chat_id, message_id,
                    f"🆕 **Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{state['minute']:02d} (Schritt 4/6)**\n\nBitte gib die gewünschte Dauer in Minuten über die Tastatur ein (Zahl von 1 bis 25):",
                    {"inline_keyboard": [[{"text": "❌ Abbrechen", "callback_data": "wiz_cancel"}]]}
                )
            else:
                dur = int(dur_str)
                state["duration"] = dur
                state["step"] = 5
                _state_touch(wizard_states, chat_id)
                telegram_client.edit_message_text(
                    chat_id, message_id,
                    f"🆕 **Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{state['minute']:02d} (Schritt 5/6)**\n\nWie viel Wasser soll **maximal** fließen? (Volumenlimit)\n\n*Ausgewählte Dauer: {dur} Min.*",
                    get_volume_wizard_keyboard("wiz")
                )

    elif data.startswith("wiz_vol_"):
        vol_str = data.split("_")[2]
        state = _state_get(wizard_states, chat_id)
        if state is not None:
            telegram_client.answer_callback_query(cb_id)
            if vol_str == "custom":
                state["step"] = "custom_volume"
                _state_touch(wizard_states, chat_id)
                telegram_client.edit_message_text(
                    chat_id, message_id,
                    f"🆕 **Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{state['minute']:02d} (Schritt 5/6)**\n\nBitte gib die gewünschte Wassermenge in Litern über die Tastatur ein (Zahl > 0):",
                    {"inline_keyboard": [[{"text": "❌ Abbrechen", "callback_data": "wiz_cancel"}]]}
                )
            else:
                vol = int(vol_str)
                state["volume"] = vol
                state["step"] = 6
                state["days"] = []
                _state_touch(wizard_states, chat_id)
                telegram_client.edit_message_text(
                    chat_id, message_id,
                    f"🆕 **Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{state['minute']:02d} (Schritt 6/6)**\n\nWähle die **Wochentage** aus, an denen bewässert werden soll:\n\n*Ausgewählt: Keine*",
                    get_days_wizard_keyboard([])
                )

    elif data.startswith("wiz_day_"):
        day = data.split("_")[2]
        state = _state_get(wizard_states, chat_id)
        if state is not None:
            telegram_client.answer_callback_query(cb_id)
            days = state.get("days", [])

            if day == "everyday":
                if "everyday" in days:
                    days.clear()
                else:
                    days.clear()
                    days.append("everyday")
            else:
                if "everyday" in days:
                    days.remove("everyday")
                if day in days:
                    days.remove(day)
                else:
                    days.append(day)

            state["days"] = days
            _state_touch(wizard_states, chat_id)
            days_str = format_days_german(days)
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"🆕 **Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{state['minute']:02d} (Schritt 6/6)**\n\nWähle die **Wochentage** aus, an denen bewässert werden soll:\n\n*Ausgewählt: {days_str}*",
                get_days_wizard_keyboard(days)
            )

    elif data == "wiz_save":
        state = _state_get(wizard_states, chat_id)
        if state is not None:
            days = state.get("days", [])
            if not days:
                telegram_client.answer_callback_query(cb_id, "⚠️ Wähle mind. einen Tag!", show_alert=True)
                return

            state["step"] = 7
            _state_touch(wizard_states, chat_id)
            telegram_client.answer_callback_query(cb_id)
            days_str = format_days_german(days)
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"📝 **Zusammenfassung & Bestätigung**\n\n"
                f"Bitte überprüfe die Angaben für den neuen Zeitplan:\n\n"
                f"• **Name:** {state['name']}\n"
                f"• **Startzeit:** {state['hour']:02d}:{state['minute']:02d} Uhr\n"
                f"• **Dauer:** {state['duration']} Min\n"
                f"• **Wassermenge:** {state['volume']} Liter\n"
                f"• **Tage:** {days_str}\n\n"
                f"Soll dieser Zeitplan gespeichert werden?",
                {
                    "inline_keyboard": [
                        [
                            {"text": "❌ Abbrechen", "callback_data": "wiz_cancel"},
                            {"text": "✅ Speichern", "callback_data": "wiz_confirm_save"}
                        ]
                    ]
                }
            )

    elif data == "wiz_confirm_save":
        state = _state_get(wizard_states, chat_id)
        if state is not None:
            telegram_client.answer_callback_query(cb_id, "Zeitplan erfolgreich gespeichert!")

            name = state["name"]
            time_str = f"{state['hour']:02d}:{state['minute']:02d}"
            days_str = ",".join(state["days"])
            duration = state["duration"]
            volume = state["volume"]

            db_id = database.add_schedule(name, time_str, days_str, duration, volume)
            _state_del(wizard_states, chat_id)

            if db_id > 0:
                telegram_client.send_message(chat_id, f"📅 Zeitplan **'{name}'** erfolgreich angelegt!", get_main_keyboard())
                handle_schedules(chat_id)
            else:
                telegram_client.send_message(chat_id, "❌ Fehler beim Speichern des Zeitplans in der Datenbank.", get_main_keyboard())

    elif data == "wiz_cancel":
        _state_del(wizard_states, chat_id)
        telegram_client.answer_callback_query(cb_id, "Abgebrochen")
        telegram_client.send_message(chat_id, "❌ Vorgang abgebrochen.", get_main_keyboard())

    elif data.startswith("man_dur_"):
        dur_str = data.split("_")[2]
        telegram_client.answer_callback_query(cb_id)
        if dur_str == "custom":
            _state_set(manual_states, chat_id, {"step": "man_custom_duration"})
            telegram_client.edit_message_text(
                chat_id, message_id,
                "🟢 **Manuelle Bewässerung starten (Schritt 1/2)**\n\nBitte gib die gewünschte Dauer in Minuten über die Tastatur ein (Zahl von 1 bis 25):",
                {"inline_keyboard": [[{"text": "❌ Abbrechen", "callback_data": "man_cancel"}]]}
            )
        else:
            dur = int(dur_str)
            _state_set(manual_states, chat_id, {"step": 2, "duration": dur})
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"🟢 **Manuelle Bewässerung starten (Schritt 2/2)**\n\nWie viel Wasser soll **maximal** fließen? (Volumenlimit)\n\n*Ausgewählte Dauer: {dur} Min.*",
                get_volume_wizard_keyboard("man")
            )

    elif data.startswith("man_vol_"):
        vol_str = data.split("_")[2]
        state = _state_get(manual_states, chat_id)
        if state is not None:
            telegram_client.answer_callback_query(cb_id)
            if vol_str == "custom":
                state["step"] = "man_custom_volume"
                _state_touch(manual_states, chat_id)
                telegram_client.edit_message_text(
                    chat_id, message_id,
                    "🟢 **Manuelle Bewässerung starten (Schritt 2/2)**\n\nBitte gib die gewünschte Wassermenge in Litern über die Tastatur ein (Zahl > 0):",
                    {"inline_keyboard": [[{"text": "❌ Abbrechen", "callback_data": "man_cancel"}]]}
                )
            else:
                vol = int(vol_str)
                dur = state["duration"]
                _state_del(manual_states, chat_id)

                if _watering_ctrl:
                    success, response = _watering_ctrl.start_watering(dur, vol, "manual")
                else:
                    success, response = False, "Guss-Steuerung nicht initialisiert."
                if not success:
                    telegram_client.send_message(chat_id, f"❌ Fehler beim Starten: {response}", get_main_keyboard())
                else:
                    telegram_client.edit_message_text(chat_id, message_id, f"🟢 **Befehl gesendet:** Bewässerung gestartet ({dur} Min / {vol}l).")

    elif data == "man_cancel":
        _state_del(manual_states, chat_id)
        telegram_client.answer_callback_query(cb_id, "Abgebrochen")
        telegram_client.send_message(chat_id, "❌ Vorgang abgebrochen.", get_main_keyboard())

    elif data == "setup_confirm":
        telegram_client.answer_callback_query(cb_id, "Bitte Namen eingeben...")
        _state_set(wizard_states, chat_id, {"step": "setup_wish_name"})
        telegram_client.send_message(
            chat_id,
            "🔧 *Neues Ventil koppeln*\n\nWie soll dieses Ventil heißen?\nBitte tippe den Namen ein:"
        )

    elif data == "setup_cancel":
        telegram_client.answer_callback_query(cb_id, "Abgebrochen")
        telegram_client.send_message(chat_id, "❌ Ventil-Kopplung abgebrochen.", get_main_keyboard())

    elif data.startswith("sched_toggle_"):
        sched_id = int(data.split("_")[2])
        schedules = database.get_schedules()
        target = next((s for s in schedules if s["id"] == sched_id), None)
        if target:
            new_active = 0 if target["is_active"] == 1 else 1
            database.update_schedule(
                sched_id, target["name"], target["time"],
                target["days"], target["duration_minutes"], target.get("target_volume_liters", 0), new_active
            )
            status_text = "aktiviert" if new_active == 1 else "deaktiviert"
            telegram_client.answer_callback_query(cb_id, f"'{target['name']}' {status_text}")
            handle_schedules(chat_id)
        else:
            telegram_client.answer_callback_query(cb_id, "Zeitplan nicht gefunden", show_alert=True)

    elif data.startswith("sched_delete_ask_"):
        sched_id = int(data.split("_")[3])
        schedules = database.get_schedules()
        target = next((s for s in schedules if s["id"] == sched_id), None)
        if target:
            _state_set(delete_states, chat_id, {"schedule_id": sched_id, "name": target["name"]})
            telegram_client.answer_callback_query(cb_id)
            telegram_client.send_message(
                chat_id,
                f"🗑️ **Zeitplan löschen**\n\nMöchtest du den Zeitplan **'{target['name']}'** wirklich löschen?\n\nDiese Aktion kann nicht rückgängig gemacht werden.",
                {
                    "keyboard": [[{"text": "✅ Ja, löschen"}, {"text": "❌ Nein, abbrechen"}]],
                    "resize_keyboard": True,
                    "one_time_keyboard": True
                }
            )
        else:
            telegram_client.answer_callback_query(cb_id, "Zeitplan nicht gefunden", show_alert=True)

    elif data == "update_confirm":
        telegram_client.answer_callback_query(cb_id, "Update wird gestartet...")
        Path("/tmp/garden-ota-notify").write_text(str(chat_id))
        scripts_dir = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
        subprocess.Popen(["bash", str(scripts_dir / "update.sh")])
        telegram_client.send_message(
            chat_id,
            "⏳ Update gestartet. Bitte 1–5 Minuten warten, dann `/status` prüfen."
        )

    elif data == "update_cancel":
        telegram_client.answer_callback_query(cb_id, "Abgebrochen")
        telegram_client.send_message(chat_id, "❌ Update abgebrochen.", get_main_keyboard())

    elif data == "camsetup_start":
        telegram_client.answer_callback_query(cb_id)
        handle_camera_setup(chat_id)

    elif data == "camsetup_cancel":
        _state_del(wizard_states, chat_id)
        telegram_client.answer_callback_query(cb_id, "Abgebrochen")
        telegram_client.send_message(chat_id, "❌ Kamera-Kopplung abgebrochen.", get_main_keyboard())

    elif data == "camsetup_settings":
        telegram_client.answer_callback_query(cb_id)
        from ..adapters import camera_pairing as _cp
        cameras = database.get_all_cameras()
        if not cameras:
            telegram_client.send_message(chat_id, "❌ Es sind keine Kameras gekoppelt.")
            return
        if len(cameras) == 1:
            cam = cameras[0]
            _state_set(wizard_states, chat_id, {
                "step": "camsetup_settings_interval",
                "mac": cam["mac_address"],
                "wish_name": cam["wish_name"],
            })
            telegram_client.send_message(
                chat_id,
                f"⏱ *Sendeintervall für '{cam['wish_name']}' ändern*\n\n"
                "Bitte gib das neue Intervall in Minuten ein _(z.B. `30`)_:"
            )
        else:
            rows = [[{"text": c["wish_name"], "callback_data": f"camsetup_settings_sel_{c['mac_address']}"}]
                    for c in cameras]
            telegram_client.send_message(
                chat_id,
                "Welche Kamera möchtest du anpassen?",
                {"inline_keyboard": rows}
            )

    elif data.startswith("camsetup_settings_sel_"):
        mac = data[len("camsetup_settings_sel_"):]
        camera = database.get_camera(mac)
        if not camera:
            telegram_client.answer_callback_query(cb_id, "Kamera nicht gefunden", show_alert=True)
            return
        telegram_client.answer_callback_query(cb_id)
        _state_set(wizard_states, chat_id, {
            "step": "camsetup_settings_interval",
            "mac": mac,
            "wish_name": camera["wish_name"],
        })
        telegram_client.edit_message_text(
            chat_id, message_id,
            f"⏱ *Sendeintervall für '{camera['wish_name']}' ändern*\n\n"
            "Bitte gib das neue Intervall in Minuten ein _(z.B. `30`)_:"
        )

    elif data.startswith("camsetup_res_"):
        val = data[len("camsetup_res_"):]
        if val not in {"VGA", "XGA", "UXGA"}:
            telegram_client.answer_callback_query(cb_id, "Ungültige Auflösung", show_alert=True)
            return
        state = _state_get(wizard_states, chat_id)
        if state is None:
            telegram_client.answer_callback_query(cb_id)
            return
        state["resolution"] = val
        state["step"] = "setup_camera_quality"
        _state_touch(wizard_states, chat_id)
        labels = {"VGA": "💨 Niedrig (640×480)", "XGA": "⚡ Mittel (1024×768)", "UXGA": "🏔 Hoch (1600×1200)"}
        telegram_client.answer_callback_query(cb_id, f"Auflösung: {labels[val]}")
        telegram_client.edit_message_text(
            chat_id, message_id,
            f"🎨 *Welche Bildqualität soll die Kamera verwenden?*\n\n"
            f"Gewählte Auflösung: {labels[val]}\n\n"
            "Höhere Qualität = schärfere Bilder, größere Dateien.",
            get_camera_quality_keyboard()
        )

    elif data.startswith("camsetup_qual_"):
        val = data[len("camsetup_qual_"):]
        quality_map = {"high": 10, "medium": 25, "low": 40}
        if val not in quality_map:
            telegram_client.answer_callback_query(cb_id, "Ungültige Qualität", show_alert=True)
            return
        state = _state_get(wizard_states, chat_id)
        if state is None:
            telegram_client.answer_callback_query(cb_id)
            return
        quality = quality_map[val]
        wish_name = state["wish_name"]
        sleep_seconds = state["sleep_seconds"]
        resolution = state["resolution"]
        _state_del(wizard_states, chat_id)
        from ..adapters import camera_pairing
        telegram_client.answer_callback_query(cb_id, "Starte Kopplung...")
        telegram_client.edit_message_text(
            chat_id, message_id,
            f"🔧 *Kamera-Kopplung gestartet* — \"{wish_name}\"\n"
            f"Intervall: {sleep_seconds // 60} Min · Auflösung: {resolution} · Qualität: {val}\n\n"
            "Bitte schalte die Kamera jetzt ein oder drücke Reset.\n"
            "⏱️ Das System wartet bis zu 90 Sekunden."
        )
        camera_pairing.start_pairing(
            chat_id, telegram_client.send_message, wish_name,
            sleep_seconds=sleep_seconds, resolution=resolution, quality=quality
        )

    elif data.startswith("camphoto_"):
        wish_name = data.split("_", 1)[1]
        telegram_client.answer_callback_query(cb_id, f"Lade Foto von {wish_name}...")
        _send_latest_photo(chat_id, wish_name)

    elif data.startswith("camint_"):
        try:
            parts = data.split("_")
            mac = parts[1]
            minutes = int(parts[2])
        except (IndexError, ValueError):
            telegram_client.answer_callback_query(cb_id, "Ungültiger Callback", show_alert=True)
            return
        camera = database.get_camera(mac)
        if camera:
            database.update_camera_settings(mac, sleep_seconds=minutes*60, resolution=camera["resolution"], quality=camera["quality"])
            telegram_client.answer_callback_query(cb_id, "Intervall aktualisiert")
            telegram_client.edit_message_text(chat_id, message_id, f"✅ Intervall für '{camera['wish_name']}' wurde auf {minutes} Minuten gesetzt.")
        else:
            telegram_client.answer_callback_query(cb_id, "Kamera nicht gefunden", show_alert=True)

    else:
        telegram_client.answer_callback_query(cb_id)

def on_telegram_update(msg_obj: dict, cb_obj: dict):
    """Routing-Callback, das vom TelegramClient aufgerufen wird."""
    if msg_obj:
        _process_message(msg_obj)
    elif cb_obj:
        _process_callback_query(cb_obj)

# --- Domain Event Listeners ---

def _on_watering_started(event: WateringCycleStarted):
    msg = (
        f"🟢 **Bewässerung gestartet!**\n"
        f"⏱️ Zeitlimit: {event.duration} Minuten\n"
        f"💧 Volumenlimit: {f'{event.target_volume} Liter' if event.target_volume > 0 else 'Keines'}\n"
        f"⏳ Quelle: {'Zeitplan' if event.source == 'schedule' else 'Manuell'}"
    )
    telegram_client.broadcast_notification(msg)

def _on_watering_completed(event: WateringCycleCompleted):
    if "Volumenlimit" in event.details:
        target_volume = event.volume_run
        msg = (
            f"🏁 **Wassermenge erreicht!**\n"
            f"💧 Bewässerung nach {int(target_volume)} Litern automatisch beendet.\n"
            f"⏱️ Benötigte Zeit: ca. {event.duration_run} Minute(n)."
        )
    else:
        msg = (
            f"🏁 **Zeitlimit erreicht!**\n"
            f"⏱️ Bewässerung nach {event.duration_run} Minuten planmäßig beendet.\n"
            f"💧 Wassermenge: {event.volume_run} Liter geflossen."
        )
    telegram_client.broadcast_notification(msg)

def _on_watering_failed(event: WateringCycleFailed):
    target_vol = 0
    if "Zielwassermenge von" in event.details:
        try:
            parts = event.details.split("Zielwassermenge von ")
            target_vol = int(parts[1].split("l")[0])
        except Exception:
            pass

    msg = (
        f"⚠️ **Notfall-Abschaltung ausgelöst!**\n"
        f"⏱️ Abschaltung nach Ablauf von {event.duration_run} Minuten bei geflossenen {event.volume_run} Litern.\n"
        f"💧 Zielwassermenge von {target_vol} Litern wurde nicht erreicht."
    )
    telegram_client.broadcast_notification(msg)

def _on_watering_stopped(event: WateringCycleStopped):
    msg = f"🔴 **Bewässerung vorzeitig gestoppt!**\n⏱️ Laufzeit: ca. {event.duration_run} Min\n💧 Geflossene Menge: {event.volume_run} Liter"
    telegram_client.broadcast_notification(msg)

def _on_daily_report(event: DailyReportTriggered):
    from ..adapters import chart
    chart_result = chart.generate_weather_chart()
    if chart_result:
        image_bytes, caption = chart_result
        telegram_client.broadcast_photo(image_bytes, caption=caption)
    telegram_client.broadcast_notification(event.report_text)

def _on_watering_skipped(event: WateringSkipped):
    telegram_client.broadcast_notification(f"🌤️ **Zeitplan '{event.schedule_name}' übersprungen!**\n{event.details}")

def _on_schedule_failed(event: ScheduleFailed):
    telegram_client.broadcast_notification(f"⚠️ **Fehler bei Zeitplan '{event.schedule_name}'!**\n{event.details}")

def _on_inactivity_alert(event: InactivityAlertTriggered):
    msg = (
        f"⚠️ *Verbindung verloren:* Ventil \"{event.device_name}\" "
        f"hat seit {event.hours_silent:.1f} Stunden kein Signal gesendet."
    )
    telegram_client.broadcast_notification(msg)

def _on_inactivity_resolved(event: InactivityAlertResolved):
    msg = f"🟢 *Verbindung wiederhergestellt:* Ventil \"{event.device_name}\" sendet wieder Signale."
    telegram_client.broadcast_notification(msg)

def _on_camera_inactivity_alert(event: CameraInactivityAlertTriggered):
    msg = (
        f"⚠️ *Kamera-Verbindung verloren:* Kamera \"{event.wish_name}\" "
        f"hat seit {event.seconds_silent / 3600:.1f} Stunden kein Bild gesendet."
    )
    telegram_client.broadcast_notification(msg)

def _on_camera_inactivity_resolved(event: CameraInactivityAlertResolved):
    msg = f"🟢 *Kamera-Verbindung wiederhergestellt:* Kamera \"{event.wish_name}\" sendet wieder Bilder."
    telegram_client.broadcast_notification(msg)

def subscribe_event_handlers():
    """Verdrahtet alle telegram_ui-Benachrichtigungs-Handler mit dem globalen Ereignis-Kanal.

    Muss explizit von main.py aufgerufen werden — nicht automatisch beim Import.
    Dadurch können Tests das Modul importieren, ohne echte Telegram-Nachrichten auszulösen.
    Entspricht dem gleichen Muster wie watchdog.initialize().
    """
    _global_bus.subscribe(WateringCycleStarted, _on_watering_started)
    _global_bus.subscribe(WateringCycleCompleted, _on_watering_completed)
    _global_bus.subscribe(WateringCycleFailed, _on_watering_failed)
    _global_bus.subscribe(WateringCycleStopped, _on_watering_stopped)
    _global_bus.subscribe(DailyReportTriggered, _on_daily_report)
    _global_bus.subscribe(WateringSkipped, _on_watering_skipped)
    _global_bus.subscribe(ScheduleFailed, _on_schedule_failed)
    _global_bus.subscribe(InactivityAlertTriggered, _on_inactivity_alert)
    _global_bus.subscribe(InactivityAlertResolved, _on_inactivity_resolved)
    _global_bus.subscribe(CameraInactivityAlertTriggered, _on_camera_inactivity_alert)
    _global_bus.subscribe(CameraInactivityAlertResolved, _on_camera_inactivity_resolved)
