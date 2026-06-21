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
    WateringCycleStopped,
    WateringCycleInterrupted,
)
from ..core.scheduler_events import (
    DailyReportTriggered,
    WateringSkipped,
    ScheduleFailed,
    WateringScaled,
)
from ..core import watering_advice
from ..adapters import weather as _weather_adapter
from ..core.watchdog_events import InactivityAlertTriggered, InactivityAlertResolved
from ..core.camera_events import CameraInactivityAlertTriggered, CameraInactivityAlertResolved
from ..core.sensor_events import RainSensorMeasured, RainSensorInactivityAlertTriggered, RainSensorInactivityAlertResolved

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
edit_states = {}    # { chat_id: { "sched_id": int, "field": str|None, "edit_days": list, "last_active": datetime } }

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

    confirm_kb = {
        "inline_keyboard": [[
            {"text": "✓ Jetzt installieren", "callback_data": "update_confirm"},
            {"text": "✗ Abbrechen",          "callback_data": "update_cancel"},
        ]]
    }

    if len(notes_raw) > 800:
        notes_raw = notes_raw[:800] + "…"
    # Markdown-Sonderzeichen in den Notes escapen, damit Telegrams Parser nicht abbricht
    notes_escaped = notes_raw.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")
    notes_section = f"\n\n📋 *Was ist neu:*\n{notes_escaped}" if notes_escaped else ""

    sent = telegram_client.send_message(
        chat_id,
        f"🔄 *Software-Update verfügbar*\n\n"
        f"Installiert: `{local}`\n"
        f"Verfügbar:   `{remote_name}`"
        f"{notes_section}\n\n"
        f"Soll das Update jetzt installiert werden?\n"
        f"_(Dauer: ca. 1–5 Minuten. Der Daemon startet neu.)_",
        confirm_kb,
    )
    if not sent:
        # Fallback ohne Notes und ohne Markdown-Formatierung
        telegram_client.send_message(
            chat_id,
            f"Update verfügbar: {local} → {remote_tag}\nJetzt installieren?",
            confirm_kb,
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
        [{"text": "📊 Status anzeigen"}, {"text": "💧 Gießcheck"}],
        [{"text": "🚿 Bewässern starten"}, {"text": "🛑 Sofort Stopp"}],
        [{"text": "📅 Zeitpläne"}, {"text": "⚙️ Setup"}],
        [{"text": "📸 Foto anzeigen"}],
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
    """Erstellt ein Inline-Keyboard mit Toggle-, Bearbeiten- und Lösch-Button pro Zeitplan."""
    rows = []
    for s in schedules:
        icon = "🟢" if s['is_active'] == 1 else "🔴"
        rows.append([
            {"text": f"{icon} {s['name']} ({s['time']})", "callback_data": f"sched_toggle_{s['id']}"},
            {"text": "✏️", "callback_data": f"sched_edit_{s['id']}"},
            {"text": "🗑️", "callback_data": f"sched_delete_ask_{s['id']}"}
        ])
    rows.append([{"text": "➕ Neuer Zeitplan", "callback_data": "wiz_start"}])
    return {"inline_keyboard": rows}


def _get_edit_days_keyboard(sched_id: int, selected: list) -> dict:
    """Inline-Keyboard für Tage-Auswahl im Edit-Modus."""
    _DAY_MAP = [("Mon", "Mo"), ("Tue", "Di"), ("Wed", "Mi"), ("Thu", "Do"),
                ("Fri", "Fr"), ("Sat", "Sa"), ("Sun", "So")]
    row1 = [{"text": ("✅ " if d[0] in selected else "") + d[1],
             "callback_data": f"sched_editday_{sched_id}_{d[0]}"} for d in _DAY_MAP[:4]]
    row2 = [{"text": ("✅ " if d[0] in selected else "") + d[1],
             "callback_data": f"sched_editday_{sched_id}_{d[0]}"} for d in _DAY_MAP[4:]]
    everyday_sel = "everyday" in selected
    row2.append({"text": ("✅ " if everyday_sel else "") + "Täglich",
                 "callback_data": f"sched_editday_{sched_id}_everyday"})
    return {"inline_keyboard": [row1, row2, [
        {"text": "💾 Speichern", "callback_data": f"sched_editday_save_{sched_id}"},
        {"text": "❌ Abbrechen",  "callback_data": "sched_edit_cancel"},
    ]]}

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

def _garden_ampel_level(valves: list, services_ok: bool, cameras: list | None = None) -> str:
    """Gibt 'green', 'yellow' oder 'red' zurück — schlimmste aktive Stufe gewinnt."""
    if not services_ok:
        return "red"
    threshold = config.get_setting("BATTERY_WARNING_THRESHOLD", 20)
    worst = "green"
    for v in valves:
        if not v.get("last_update"):
            return "red"
        abnormal = v.get("valve_abnormal_state") or "normal"
        if abnormal != "normal":
            return "red"
        battery = v.get("battery")
        lqi = v.get("linkquality")
        battery_val = int(battery) if battery is not None else 100
        lqi_val = int(lqi) if lqi is not None else 100
        if battery_val <= threshold or lqi_val < 60:
            worst = "yellow"
    for cam in (cameras if cameras is not None else database.get_all_cameras()):
        cam_battery = cam.get("battery")
        if cam_battery is not None and int(cam_battery) <= threshold:
            worst = "yellow"
    return worst


def _valve_level(valve: dict, services_ok: bool, cameras: list | None = None) -> str:
    """Gibt 'green', 'yellow' oder 'red' für ein einzelnes Ventil zurück."""
    return _garden_ampel_level([valve], services_ok, cameras)


def _status_headline(level: str) -> str:
    if level == "green":
        return "🟢 Alles im grünen Bereich"
    elif level == "yellow":
        return "🟡 Aufmerksamkeit nötig"
    return "🔴 Es gibt ein Problem"


def _get_lqi_label(lqi_val) -> str:
    """Qualitatives LQI-Label ohne Zahl (für kompakte Darstellung)."""
    try:
        lqi = int(lqi_val)
    except (TypeError, ValueError):
        lqi = 0
    if lqi >= 120:
        return "gut"
    elif lqi >= 60:
        return "ausreichend"
    elif lqi > 0:
        return "schwach"
    return "keine Verbindung"


def _format_valve_compact(valve: dict) -> str:
    """Einzeilige Ventil-Darstellung für grüne Geräte (keine technischen IDs)."""
    battery = valve.get("battery")
    lqi = valve.get("linkquality")
    battery_label = _get_battery_description(battery if battery is not None else 100)
    lqi_label = _get_lqi_label(lqi if lqi is not None else 100)
    return f"{valve['wish_name']} · 🟢 aktiv · {battery_label} · 📶 {lqi_label}"


def _format_valve_expanded(valve: dict, level: str) -> str:
    """Mehrzeilige Ventil-Darstellung für nicht-grüne Geräte (mit Details)."""
    icon = "🟡" if level == "yellow" else "🔴"
    battery = valve.get("battery")
    lqi = valve.get("linkquality")
    battery_val = int(battery) if battery is not None else 0
    lqi_val = int(lqi) if lqi is not None else 0
    lqi_desc = _get_lqi_description(lqi_val)
    last_update_str = valve.get("last_update")
    last_signal_line = ""
    if last_update_str:
        try:
            last_up = datetime.fromisoformat(last_update_str)
            last_signal_line = f"\n   Letztes Signal: {last_up.strftime('%d.%m. um %H:%M')} Uhr"
        except Exception:
            pass
    return (
        f"{icon} {valve['wish_name']}\n"
        f"   🔋 {battery_val} % · 📶 {lqi_desc}"
        f"{last_signal_line}\n"
        f"   ID: {valve['mqtt_name']}"
    )


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
        telegram_client.send_message(chat_id, "❌ *Ungültiges Format.* Nutzen Sie: `/camera_interval <minuten>` (z.B. `/camera_interval 15`)")

_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _get_next_schedule(schedules: list, now: datetime) -> dict | None:
    """Gibt den nächsten aktiven Zeitplan zurück, der nach `now` feuert (inkl. _next_dt key)."""
    best = None
    best_delta = None

    for s in schedules:
        if not s.get("is_active"):
            continue
        try:
            h, m = map(int, s["time"].split(":"))
        except (ValueError, KeyError):
            continue
        days_raw = s.get("days", "")
        days = [d.strip() for d in days_raw.split(",")] if days_raw else []

        for offset in range(7):
            candidate = (now + timedelta(days=offset)).replace(
                hour=h, minute=m, second=0, microsecond=0
            )
            if candidate <= now:
                continue
            day_name = _WEEKDAY_NAMES[candidate.weekday()]
            if "everyday" in days or day_name in days:
                delta = (candidate - now).total_seconds()
                if best_delta is None or delta < best_delta:
                    best_delta = delta
                    best = dict(s)
                    best["_next_dt"] = candidate
                break

    return best


def _format_rain_sensor_status() -> str | None:
    """Gibt die Regensensor-Statuszeile für /status zurück, oder None wenn kein Sensor bekannt."""
    last = database.get_last_rain_measurement()
    if not last:
        return None
    try:
        age_hours = (datetime.now() - datetime.fromisoformat(last["timestamp"])).total_seconds() / 3600
    except Exception:
        return None
    offline_hours = config.RAIN_SENSOR_OFFLINE_HOURS
    if age_hours >= offline_hours:
        last_weather = database.get_last_weather()
        source_label = "Sensor offline · Regen-24h via ERA5"
        if last_weather and last_weather.get("rain_last_source") == "sensor":
            source_label = "Sensor offline"
        return f"🌧 *Regen*  ⚠️ {source_label} (seit {age_hours:.1f} h)"
    battery_label = _get_battery_description(last.get("battery_pct", 100))
    return (
        f"🌧 *Regen*  {last['rainlevel_mm']} mm · "
        f"Gesamt {last['raintotal_mm']} mm · "
        f"🌡 {last['temperature_c']} °C · {battery_label}"
    )


def handle_status(chat_id: int):
    from ..adapters import mqtt_client
    from ..core.valve_events import ValveStatusReported

    telegram_client.send_chat_action(chat_id, "typing")

    if mqtt_client.HAS_PAHO:
        _valve_event = threading.Event()
        def _on_valve_status(ev):
            _valve_event.set()
        _global_bus.subscribe(ValveStatusReported, _on_valve_status)
        try:
            mqtt_client.request_valve_status()
            _valve_event.wait(timeout=3.0)
        finally:
            _global_bus.unsubscribe(ValveStatusReported, _on_valve_status)
    else:
        mqtt_client.request_valve_status()

    broker_connected = mqtt_client.is_broker_connected()
    bridge_online = mqtt_client.get_bridge_status() == "online"

    if not mqtt_client.HAS_PAHO:
        services_status = "⚡ Simulationsmodus"
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

    now = datetime.now()
    _days_de = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    day_str = f"{_days_de[now.weekday()]}, {now.strftime('%d.%m.')} · {now.strftime('%H:%M')} Uhr"

    active = _watering_ctrl.get_active_cycle() if _watering_ctrl else None
    active_text = ""
    if active:
        active_text = (
            f"\n⚡ *Laufender Zyklus:*\n"
            f"   Gestartet: {active['source'].upper()}\n"
            f"   Restzeit: {int(active['remaining_seconds']/60)} Min ({active['remaining_seconds'] % 60} Sek)\n"
        )

    valves = database.get_all_valves()
    cameras = database.get_all_cameras()
    level = _garden_ampel_level(valves, services_ok, cameras)
    headline = _status_headline(level)

    valve_lines = []
    for valve in valves:
        vlvl = _valve_level(valve, services_ok, cameras)
        if vlvl == "green":
            valve_lines.append(_format_valve_compact(valve))
        else:
            valve_lines.append(_format_valve_expanded(valve, vlvl))
    valves_text = "\n".join(valve_lines) if valve_lines else "Keine Ventile registriert."

    # Kamera-Abschnitt (Logik unverändert, Format angepasst)
    camera_sections = []
    for cam in cameras:
        wish_name = cam["wish_name"]
        last_seen_str = cam.get("last_seen")
        sleep_sec = cam.get("sleep_duration_seconds") or 900

        if not last_seen_str:
            cam_status = "🔴 Noch kein Bild empfangen"
        else:
            try:
                from datetime import timezone
                last_dt = datetime.fromisoformat(last_seen_str)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                now_utc = datetime.now(timezone.utc)
                age_sec = (now_utc - last_dt).total_seconds()
                time_str = last_dt.strftime("%H:%M")
                if age_sec <= sleep_sec * 2:
                    cam_status = f"🟢 {time_str} Uhr"
                else:
                    cam_status = f"🔴 kein Bild seit {last_dt.strftime('%d.%m. um %H:%M')} Uhr"
            except Exception:
                cam_status = "🔴 Unbekannt"

        battery = cam.get("battery")
        battery_label = f" · {_get_battery_description(battery)}" if battery is not None else ""
        camera_sections.append(f"{wish_name} · {cam_status}{battery_label}")

    cameras_text = "\n".join(camera_sections) if camera_sections else ""

    rain_sensor_line = _format_rain_sensor_status()
    rain_sensor_block = f"\n{rain_sensor_line}\n" if rain_sensor_line else ""

    last_weather = database.get_last_weather()
    weather_text = "   Keine Daten vorhanden"
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
                        f"\n   *{nxt_time}*  {nxt_desc} · {nxt_temp} °C · {nxt_precip} mm · {nxt_prob} %"
                    )
            except Exception:
                pass

        weather_text = (
            f"   *Jetzt*  {desc} · {temp} °C · 💧 {current_precip} mm"
            f"{next_hour_line}\n"
            f"   *(Stand: {time_str})*"
        )

    _SOURCE_LABELS = {"schedule": "Zeitplan", "manual": "Manuell"}
    history = database.get_recent_history(3)
    history_lines = []
    for h in history:
        time_obj = datetime.fromisoformat(h['timestamp'])
        time_str = time_obj.strftime("%d.%m. %H:%M")
        status_char = "✅" if h['status'] == "completed" else "🌧" if h['status'] == "skipped" else "❌"
        volume = h.get("watered_volume") or 0.0
        source_label = _SOURCE_LABELS.get(h.get("source", ""), h.get("source", ""))
        vol_str = f" · {volume:.0f} L" if volume > 0 else ""
        history_lines.append(f"{status_char} {time_str} · {h['duration_minutes']} Min{vol_str} · {source_label}")
    history_text = "\n".join(history_lines) if history_lines else "Keine Einträge vorhanden"

    all_schedules = database.get_schedules()
    active_schedules = [s for s in all_schedules if s.get("is_active")]
    nxt = _get_next_schedule(active_schedules, now)
    next_sched_text = ""
    if nxt:
        nxt_dt = nxt["_next_dt"]
        day_label = "heute" if nxt_dt.date() == now.date() else "morgen"
        next_sched_text = (
            f"\n⏰ *Nächster Guss:* {day_label} {nxt_dt.strftime('%H:%M')} Uhr"
            f" · {nxt['name']} · {nxt['duration_minutes']} Min\n"
        )

    services_block = f"🔌 Dienste: {services_status}\n" if level != "green" else ""
    cameras_block = f"\n📷 *Kameras*\n{cameras_text}\n" if cameras_text else ""

    msg = (
        f"🌱 *Dein Garten auf einen Blick*\n"
        f"{day_str}\n\n"
        f"{headline}\n\n"
        f"{services_block}"
        f"{active_text}"
        f"\n📡 *Ventile*\n{valves_text}\n"
        f"{next_sched_text}"
        f"{cameras_block}"
        f"{rain_sensor_block}"
        f"\n🌡 *Wetter*\n{weather_text}\n\n"
        f"📜 *Zuletzt*\n{history_text}"
    )

    telegram_client.send_message(chat_id, msg, get_main_keyboard())

def handle_giesscheck(chat_id: int):
    """Gieß-Empfehlung: graduierter Faktor aus Regen-Fenster, Temperatur und Hitzestrecke."""
    try:
        decision = _weather_adapter.evaluate_watering_factor()
    except Exception as e:
        logger.error(f"Fehler beim Laden der Gieß-Empfehlung: {e}")
        telegram_client.send_message(
            chat_id,
            "❌ Keine Wetterdaten verfügbar. Bitte später erneut versuchen.",
            get_main_keyboard(),
        )
        return
    reason_text = "\n".join(f"• {r}" for r in decision.reasons)
    telegram_client.send_message(
        chat_id,
        f"*💧 Gießcheck*\n\n{decision.verdict}\n\n{reason_text}",
        get_main_keyboard(),
    )

def handle_schedules(chat_id: int):
    schedules = database.get_schedules()
    if not schedules:
        msg = (
            "📅 *Zeitsteuerung*\n\n"
            "Es sind aktuell keine aktiven Zeitpläne eingerichtet.\n\n"
            "💡 *Neuen Zeitplan anlegen:*\n"
            "Klicke auf den Button unten, um den geführten Assistenten zu starten, oder nutze den klassischen `/add` Befehl.\n\n"
            "*Klassischer Befehl:*\n"
            "`/add <Name>, <Uhrzeit>, <Tage>, <Dauer>, [Menge_Liter]`\n\n"
            "*Beispiel:*\n"
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
            f"🆔 *ID {s['id']}: {s['name']}*\n"
            f"   - ⏰ Startzeit: {s['time']} Uhr\n"
            f"   - 📅 Tage: {days_formatted}\n"
            f"   - ⏳ Dauer: {s['duration_minutes']} Min\n"
            f"   - 💧 Menge: {vol_str}\n"
            f"   - Status: {status}\n"
        )

    msg = "📅 *Aktuelle Zeitsteuerung (Zeitpläne):*\n\n" + "\n".join(lines)
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
            telegram_client.send_message(chat_id, f"📅 Zeitplan *'{name}'* erfolgreich mit ID {db_id} angelegt!")
            handle_schedules(chat_id)
        else:
            telegram_client.send_message(chat_id, "❌ Fehler beim Speichern des Zeitplans in der Datenbank.")
    except Exception:
        telegram_client.send_message(
            chat_id,
            "❌ *Ungültiges Format.*\n\n"
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
        telegram_client.send_message(chat_id, "❌ *Ungültiges Format.* Nutzen Sie: `/delete <ID>` (z.B. `/delete 2`)")

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
            telegram_client.send_message(chat_id, f"📅 Zeitplan *'{target['name']}'* wurde {status_text}.")
            handle_schedules(chat_id)
        else:
            telegram_client.send_message(chat_id, f"❌ Zeitplan ID {sched_id} nicht gefunden.")
    except Exception:
        telegram_client.send_message(chat_id, "❌ *Ungültiges Format.* Nutzen Sie: `/toggle <ID>` (z.B. `/toggle 1`)")

# --- Interface-Schicht-Update Callback ---

_SETTINGS_META = {
    "RAIN_THRESHOLD_MM": {
        "label": "Regenschwelle",
        "unit": "mm",
        "options": [1.0, 2.0, 3.0, 5.0, 8.0, 10.0],
        "min": 0.5, "max": 30.0,
        "cb_prefix": "set_rain",
        "typ": float,
    },
    "BATTERY_WARNING_THRESHOLD": {
        "label": "Batterie-Warnschwelle",
        "unit": "%",
        "options": [10, 15, 20, 25, 30],
        "min": 1, "max": 99,
        "cb_prefix": "set_battery",
        "typ": int,
    },
    "SAFETY_TIMEOUT_MINUTES": {
        "label": "Hardware-Sicherheits-Timeout",
        "unit": "Min",
        "options": [10, 20, 30, 45, 60],
        "min": 1, "max": 120,
        "cb_prefix": "set_safety",
        "typ": int,
    },
}


def handle_einstellungen(chat_id: int, message_id: int | None = None):
    """Zeigt die aktuellen konfigurierbaren Werte und Bearbeitungs-Buttons."""
    lines = ["*⚙️ Einstellungen*\n"]
    for key, meta in _SETTINGS_META.items():
        val = config.get_setting(key, meta["options"][0])
        lines.append(f"• *{meta['label']}:* {val} {meta['unit']}")
    lines.append("\nWas möchtest du ändern?")
    rows = [
        [{"text": f"✏️ {meta['label']}", "callback_data": f"einst_edit_{key}"}]
        for key, meta in _SETTINGS_META.items()
    ]
    rows.append([{"text": "✅ Schließen", "callback_data": "einst_close"}])
    markup = {"inline_keyboard": rows}
    text = "\n".join(lines)
    if message_id:
        telegram_client.edit_message_text(chat_id, message_id, text, markup)
    else:
        telegram_client.send_message(chat_id, text, markup)


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
                telegram_client.send_message(chat_id, f"🗑️ Zeitplan *'{name}'* wurde gelöscht.", get_main_keyboard())
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

    ed_state = _state_get(edit_states, chat_id)
    if ed_state is not None and ed_state.get("field") == "name":
        new_name = text.strip()
        if not new_name or len(new_name) > 50 or text.startswith("/"):
            telegram_client.send_message(chat_id, "❌ Name muss 1–50 Zeichen lang sein.")
            return
        sched_id = ed_state["sched_id"]
        schedule = database.get_schedule_by_id(sched_id)
        if schedule:
            database.update_schedule(
                sched_id, new_name, schedule["time"], schedule["days"],
                schedule["duration_minutes"], schedule.get("target_volume_liters") or 0, schedule["is_active"]
            )
            _state_del(edit_states, chat_id)
            telegram_client.send_message(chat_id, f"✅ Name auf *\"{new_name}\"* geändert.")
            handle_schedules(chat_id)
        return

    state = _state_get(wizard_states, chat_id)
    if state is not None:
        step = state.get("step")

        if text.startswith("/") or text in ["📊 Status anzeigen", "💧 Gießcheck", "📅 Zeitsteuerung", "📅 Zeitpläne", "🚿 Bewässern starten", "🛑 Sofort Stopp", "🟢 Bewässern starten", "🔴 Sofort Stopp"]:
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
                    f"🆕 *Neuen Zeitplan '{text}' (Schritt 2/6)*\n\nZu welcher *Stunde* soll die Bewässerung starten?",
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
                        f"🆕 *Neuen Zeitplan '{state['name']}' (Schritt 5/6)*\n\nWie viel Wasser soll *maximal* fließen? (Volumenlimit)",
                        get_volume_wizard_keyboard("wiz")
                    )
                except ValueError:
                    telegram_client.send_message(chat_id, "❌ *Ungültige Eingabe.* Bitte gib eine Zahl zwischen 1 und 25 Minuten ein:")
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
                        f"🆕 *Neuen Zeitplan '{state['name']}' (Schritt 6/6)*\n\nWähle die *Wochentage* aus, an denen bewässert werden soll:\n\n*Ausgewählt: Keine*",
                        get_days_wizard_keyboard([])
                    )
                except ValueError:
                    telegram_client.send_message(chat_id, "❌ *Ungültige Eingabe.* Bitte gib eine Zahl größer als 0 Liter ein:")
                return

    man_state = _state_get(manual_states, chat_id)
    if man_state is not None:
        step = man_state.get("step")

        if text.startswith("/") or text in ["📊 Status anzeigen", "💧 Gießcheck", "📅 Zeitsteuerung", "📅 Zeitpläne", "🚿 Bewässern starten", "🛑 Sofort Stopp", "🟢 Bewässern starten", "🔴 Sofort Stopp"]:
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
                        "🚿 *Bewässern starten — Schritt 2/2*\n\nWie viel Wasser soll *maximal* fließen? (Volumenlimit)",
                        get_volume_wizard_keyboard("man")
                    )
                except ValueError:
                    telegram_client.send_message(chat_id, "❌ *Ungültige Eingabe.* Bitte gib eine Zahl zwischen 1 und 25 Minuten ein:")
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
                    telegram_client.send_message(chat_id, "❌ *Ungültige Eingabe.* Bitte gib eine Zahl größer als 0 Liter ein:")
                return

    if text.startswith("/start"):
        telegram_client.send_message(
            chat_id,
            "👋 *Willkommen bei der Gartenbewässerung-Steuerung!*\n\n"
            "Ich bin Ihr lokaler Assistent. Nutzen Sie die Buttons unten oder "
            "die Chat-Befehle `/status` und `/zeitplan`, um Ihr System zu steuern.",
            get_main_keyboard()
        )
    elif text == "💧 Gießcheck" or text.startswith("/giesscheck"):
        handle_giesscheck(chat_id)
    elif text == "📊 Status anzeigen" or text.startswith("/status"):
        handle_status(chat_id)
    elif text.startswith("/report") or text.startswith("/statusbericht"):
        from ..adapters import mqtt_client as _mc, chart as _chart
        from ..core.valve_events import ValveStatusReported

        telegram_client.send_chat_action(chat_id, "typing")

        if _mc.HAS_PAHO:
            _rpt_event = threading.Event()
            def _on_rpt_valve(ev):
                _rpt_event.set()
            _global_bus.subscribe(ValveStatusReported, _on_rpt_valve)
            try:
                _mc.request_valve_status()
                _rpt_event.wait(timeout=5.0)
            finally:
                _global_bus.unsubscribe(ValveStatusReported, _on_rpt_valve)
        else:
            _mc.request_valve_status()

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
    elif text in ("🚿 Bewässern starten", "🟢 Bewässern starten"):
        _state_set(manual_states, chat_id, {"step": 1})
        telegram_client.send_message(
            chat_id,
            "🚿 *Bewässern starten — Schritt 1/2*\n\nWie lange soll *maximal* bewässert werden? (Zeitlimit)\n\n*Aus Sicherheitsgründen max. 25 Min.*",
            get_duration_wizard_keyboard("man")
        )
    elif text in ("🛑 Sofort Stopp", "🔴 Sofort Stopp") or text.startswith("/stop"):
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
    elif text.startswith("/einstellungen"):
        handle_einstellungen(chat_id)
    else:
        telegram_client.send_message(
            chat_id,
            "❓ *Unbekannter Befehl.*\n\n"
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
            "🆕 *Neuen Zeitplan anlegen (Schritt 1/6)*\n\nBitte gib einen *Namen* für den Zeitplan ein (z. B. *Rasen morgens* oder *Hochbeet*):",
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
                f"🆕 *Neuen Zeitplan '{state['name']}' um {hour:02d}:?? (Schritt 3/6)*\n\nZu welcher *Minute* soll die Bewässerung starten?",
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
                f"🆕 *Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{minute:02d} (Schritt 4/6)*\n\nWie lange soll *maximal* bewässert werden? (Zeitlimit)\n\n*Aus Sicherheitsgründen max. 25 Min.*",
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
                    f"🆕 *Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{state['minute']:02d} (Schritt 4/6)*\n\nBitte gib die gewünschte Dauer in Minuten über die Tastatur ein (Zahl von 1 bis 25):",
                    {"inline_keyboard": [[{"text": "❌ Abbrechen", "callback_data": "wiz_cancel"}]]}
                )
            else:
                dur = int(dur_str)
                state["duration"] = dur
                state["step"] = 5
                _state_touch(wizard_states, chat_id)
                telegram_client.edit_message_text(
                    chat_id, message_id,
                    f"🆕 *Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{state['minute']:02d} (Schritt 5/6)*\n\nWie viel Wasser soll *maximal* fließen? (Volumenlimit)\n\n*Ausgewählte Dauer: {dur} Min.*",
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
                    f"🆕 *Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{state['minute']:02d} (Schritt 5/6)*\n\nBitte gib die gewünschte Wassermenge in Litern über die Tastatur ein (Zahl > 0):",
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
                    f"🆕 *Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{state['minute']:02d} (Schritt 6/6)*\n\nWähle die *Wochentage* aus, an denen bewässert werden soll:\n\n*Ausgewählt: Keine*",
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
                f"🆕 *Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{state['minute']:02d} (Schritt 6/6)*\n\nWähle die *Wochentage* aus, an denen bewässert werden soll:\n\n*Ausgewählt: {days_str}*",
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
                f"📝 *Zusammenfassung & Bestätigung*\n\n"
                f"Bitte überprüfe die Angaben für den neuen Zeitplan:\n\n"
                f"• *Name:* {state['name']}\n"
                f"• *Startzeit:* {state['hour']:02d}:{state['minute']:02d} Uhr\n"
                f"• *Dauer:* {state['duration']} Min\n"
                f"• *Wassermenge:* {state['volume']} Liter\n"
                f"• *Tage:* {days_str}\n\n"
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
                telegram_client.send_message(chat_id, f"📅 Zeitplan *'{name}'* erfolgreich angelegt!", get_main_keyboard())
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
                "🚿 *Bewässern starten — Schritt 1/2*\n\nBitte gib die gewünschte Dauer in Minuten über die Tastatur ein (Zahl von 1 bis 25):",
                {"inline_keyboard": [[{"text": "❌ Abbrechen", "callback_data": "man_cancel"}]]}
            )
        else:
            dur = int(dur_str)
            _state_set(manual_states, chat_id, {"step": 2, "duration": dur})
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"🚿 *Bewässern starten — Schritt 2/2*\n\nWie viel Wasser soll *maximal* fließen? (Volumenlimit)\n\n*Ausgewählte Dauer: {dur} Min.*",
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
                    "🚿 *Bewässern starten — Schritt 2/2*\n\nBitte gib die gewünschte Wassermenge in Litern über die Tastatur ein (Zahl > 0):",
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
                    telegram_client.edit_message_text(chat_id, message_id, f"🟢 *Befehl gesendet:* Bewässerung gestartet ({dur} Min / {vol}l).")

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
                f"🗑️ *Zeitplan löschen*\n\nMöchtest du den Zeitplan *'{target['name']}'* wirklich löschen?\n\nDiese Aktion kann nicht rückgängig gemacht werden.",
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

    elif data.startswith("sched_edit_") and not data.startswith("sched_editfield_") and not data.startswith("sched_editday_"):
        if data == "sched_edit_cancel":
            _state_del(edit_states, chat_id)
            telegram_client.answer_callback_query(cb_id, "Bearbeitung abgebrochen.")
            handle_schedules(chat_id)
        else:
            sched_id = int(data.split("_")[2])
            schedule = database.get_schedule_by_id(sched_id)
            if not schedule:
                telegram_client.answer_callback_query(cb_id, "Zeitplan nicht gefunden.", show_alert=True)
                return
            _state_set(edit_states, chat_id, {"sched_id": sched_id})
            telegram_client.answer_callback_query(cb_id)
            days_str = format_days_german(schedule["days"].split(",") if schedule["days"] else [])
            vol = schedule.get("target_volume_liters") or 0
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"*✏️ Zeitplan bearbeiten — \"{schedule['name']}\"*\n\n"
                f"• Zeit: {schedule['time']} Uhr\n"
                f"• Tage: {days_str}\n"
                f"• Dauer: {schedule['duration_minutes']} Min\n"
                f"• Menge: {'∞' if vol == 0 else str(vol) + ' L'}\n\n"
                "Was möchtest du ändern?",
                {"inline_keyboard": [
                    [{"text": "⏰ Zeit",   "callback_data": f"sched_editfield_time_{sched_id}"},
                     {"text": "📅 Tage",  "callback_data": f"sched_editfield_days_{sched_id}"}],
                    [{"text": "⏳ Dauer",  "callback_data": f"sched_editfield_duration_{sched_id}"},
                     {"text": "💧 Menge", "callback_data": f"sched_editfield_volume_{sched_id}"}],
                    [{"text": "✏️ Name",  "callback_data": f"sched_editfield_name_{sched_id}"}],
                    [{"text": "❌ Abbrechen", "callback_data": "sched_edit_cancel"}],
                ]},
            )

    elif data.startswith("sched_editfield_"):
        parts = data.split("_")
        field = parts[2]
        sched_id = int(parts[3])
        schedule = database.get_schedule_by_id(sched_id)
        if not schedule:
            telegram_client.answer_callback_query(cb_id, "Zeitplan nicht mehr vorhanden.", show_alert=True)
            return
        _state_set(edit_states, chat_id, {"sched_id": sched_id, "field": field})
        telegram_client.answer_callback_query(cb_id)

        if field == "duration":
            durations = [5, 10, 15, 20, 25]
            rows = [
                [{"text": f"{d} Min", "callback_data": f"sched_setdur_{sched_id}_{d}"} for d in durations],
                [{"text": "❌ Abbrechen", "callback_data": "sched_edit_cancel"}],
            ]
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"*✏️ Dauer — \"{schedule['name']}\"*\n\nAktuell: *{schedule['duration_minutes']} Min*\n\nNeue Dauer wählen:",
                {"inline_keyboard": rows}
            )

        elif field == "volume":
            volumes = [0, 5, 10, 15, 20, 25, 30, 40]
            rows = [
                [{"text": ("∞" if v == 0 else f"{v} L"), "callback_data": f"sched_setvol_{sched_id}_{v}"} for v in volumes[:4]],
                [{"text": ("∞" if v == 0 else f"{v} L"), "callback_data": f"sched_setvol_{sched_id}_{v}"} for v in volumes[4:]],
                [{"text": "❌ Abbrechen", "callback_data": "sched_edit_cancel"}],
            ]
            cur_vol = schedule.get("target_volume_liters") or 0
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"*✏️ Menge — \"{schedule['name']}\"*\n\nAktuell: *{'∞ (kein Limit)' if cur_vol == 0 else str(cur_vol) + ' L'}*\n\nNeue Menge wählen:",
                {"inline_keyboard": rows}
            )

        elif field == "time":
            rows = []
            for i in range(0, 24, 6):
                rows.append([{"text": f"{h:02d}", "callback_data": f"sched_edithour_{sched_id}_{h}"} for h in range(i, i + 6)])
            rows.append([{"text": "❌ Abbrechen", "callback_data": "sched_edit_cancel"}])
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"*✏️ Zeit — \"{schedule['name']}\"*\n\nAktuell: *{schedule['time']} Uhr*\n\nNeue Stunde wählen:",
                {"inline_keyboard": rows}
            )

        elif field == "name":
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"*✏️ Name — \"{schedule['name']}\"*\n\nAktuell: *{schedule['name']}*\n\nNeuen Namen eingeben:",
                {"inline_keyboard": [[{"text": "❌ Abbrechen", "callback_data": "sched_edit_cancel"}]]}
            )

        elif field == "days":
            current_days = schedule["days"].split(",") if schedule["days"] else []
            _state_set(edit_states, chat_id, {"sched_id": sched_id, "field": "days", "edit_days": list(current_days)})
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"*✏️ Tage — \"{schedule['name']}\"*\n\nWochentage wählen:",
                _get_edit_days_keyboard(sched_id, current_days)
            )

    elif data.startswith("sched_edithour_"):
        parts = data.split("_")
        sched_id, hour = int(parts[2]), int(parts[3])
        state = _state_get(edit_states, chat_id)
        if state:
            state["hour"] = hour
            _state_touch(edit_states, chat_id)
        telegram_client.answer_callback_query(cb_id)
        rows = []
        for i in range(0, 60, 15):
            rows.append([{"text": f":{m:02d}", "callback_data": f"sched_editmin_{sched_id}_{hour}_{m}"}
                         for m in range(i, min(i + 15, 60), 5)])
        rows.append([{"text": "❌ Abbrechen", "callback_data": "sched_edit_cancel"}])
        telegram_client.edit_message_text(
            chat_id, message_id,
            f"*✏️ Zeit*\n\nStunde: *{hour:02d}*\nMinuten wählen:",
            {"inline_keyboard": rows}
        )

    elif data.startswith("sched_editmin_"):
        parts = data.split("_")
        sched_id, hour, minute = int(parts[2]), int(parts[3]), int(parts[4])
        schedule = database.get_schedule_by_id(sched_id)
        if schedule:
            new_time = f"{hour:02d}:{minute:02d}"
            database.update_schedule(
                sched_id, schedule["name"], new_time, schedule["days"],
                schedule["duration_minutes"], schedule.get("target_volume_liters") or 0, schedule["is_active"]
            )
            telegram_client.answer_callback_query(cb_id, f"Zeit auf {new_time} Uhr gesetzt.")
            _state_del(edit_states, chat_id)
            handle_schedules(chat_id)

    elif data.startswith("sched_setdur_"):
        parts = data.split("_")
        sched_id, dur = int(parts[2]), int(parts[3])
        schedule = database.get_schedule_by_id(sched_id)
        if schedule:
            database.update_schedule(
                sched_id, schedule["name"], schedule["time"], schedule["days"],
                dur, schedule.get("target_volume_liters") or 0, schedule["is_active"]
            )
            telegram_client.answer_callback_query(cb_id, f"Dauer auf {dur} Min gesetzt.")
            _state_del(edit_states, chat_id)
            handle_schedules(chat_id)

    elif data.startswith("sched_setvol_"):
        parts = data.split("_")
        sched_id, vol = int(parts[2]), int(parts[3])
        schedule = database.get_schedule_by_id(sched_id)
        if schedule:
            database.update_schedule(
                sched_id, schedule["name"], schedule["time"], schedule["days"],
                schedule["duration_minutes"], vol, schedule["is_active"]
            )
            label = "∞ (kein Limit)" if vol == 0 else f"{vol} L"
            telegram_client.answer_callback_query(cb_id, f"Menge auf {label} gesetzt.")
            _state_del(edit_states, chat_id)
            handle_schedules(chat_id)

    elif data.startswith("sched_editday_save_"):
        sched_id = int(data.split("_")[3])
        state = _state_get(edit_states, chat_id)
        if state:
            days = state.get("edit_days", [])
            if not days:
                telegram_client.answer_callback_query(cb_id, "⚠️ Mind. einen Tag auswählen!", show_alert=True)
                return
            schedule = database.get_schedule_by_id(sched_id)
            if schedule:
                days_str = ",".join(days)
                database.update_schedule(
                    sched_id, schedule["name"], schedule["time"], days_str,
                    schedule["duration_minutes"], schedule.get("target_volume_liters") or 0, schedule["is_active"]
                )
                telegram_client.answer_callback_query(cb_id, "Tage gespeichert.")
                _state_del(edit_states, chat_id)
                handle_schedules(chat_id)

    elif data.startswith("sched_editday_"):
        parts = data.split("_")
        sched_id, day = int(parts[2]), parts[3]
        state = _state_get(edit_states, chat_id)
        if state:
            days = list(state.get("edit_days", []))
            if day == "everyday":
                days = [] if "everyday" in days else ["everyday"]
            else:
                if "everyday" in days:
                    days.remove("everyday")
                if day in days:
                    days.remove(day)
                else:
                    days.append(day)
            state["edit_days"] = days
            _state_touch(edit_states, chat_id)
            telegram_client.answer_callback_query(cb_id)
            schedule = database.get_schedule_by_id(sched_id)
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"*✏️ Tage — \"{schedule['name'] if schedule else ''}\"*\n\nWochentage wählen:",
                _get_edit_days_keyboard(sched_id, days)
            )

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

    elif data.startswith("einst_edit_"):
        key = data[len("einst_edit_"):]
        meta = _SETTINGS_META.get(key)
        if not meta:
            telegram_client.answer_callback_query(cb_id, "Unbekannte Einstellung", show_alert=True)
            return
        telegram_client.answer_callback_query(cb_id)
        cur = config.get_setting(key, meta["options"][0])
        rows = [
            [{"text": f"{v} {meta['unit']}{' ✓' if v == cur else ''}", "callback_data": f"{meta['cb_prefix']}_{v}"}
             for v in meta["options"][:3]],
            [{"text": f"{v} {meta['unit']}{' ✓' if v == cur else ''}", "callback_data": f"{meta['cb_prefix']}_{v}"}
             for v in meta["options"][3:]],
        ]
        rows.append([{"text": "↩️ Zurücksetzen", "callback_data": f"reset_setting_{key}"},
                     {"text": "❌ Schließen",  "callback_data": "einst_close"}])
        telegram_client.edit_message_text(
            chat_id, message_id,
            f"*⚙️ {meta['label']} ändern*\n\nAktuell: *{cur} {meta['unit']}*\n\nWähle einen neuen Wert:",
            {"inline_keyboard": rows}
        )

    elif data.startswith("set_rain_"):
        val_str = data[len("set_rain_"):]
        try:
            val = float(val_str)
            meta = _SETTINGS_META["RAIN_THRESHOLD_MM"]
            if not (meta["min"] <= val <= meta["max"]):
                raise ValueError
        except (ValueError, KeyError):
            telegram_client.answer_callback_query(cb_id, "Ungültiger Wert", show_alert=True)
            return
        config.set_setting("RAIN_THRESHOLD_MM", val)
        telegram_client.answer_callback_query(cb_id, f"Regenschwelle auf {val} mm gesetzt.")
        handle_einstellungen(chat_id, message_id)

    elif data.startswith("set_battery_"):
        val_str = data[len("set_battery_"):]
        try:
            val = int(val_str)
            meta = _SETTINGS_META["BATTERY_WARNING_THRESHOLD"]
            if not (meta["min"] <= val <= meta["max"]):
                raise ValueError
        except (ValueError, KeyError):
            telegram_client.answer_callback_query(cb_id, "Ungültiger Wert", show_alert=True)
            return
        config.set_setting("BATTERY_WARNING_THRESHOLD", val)
        telegram_client.answer_callback_query(cb_id, f"Batterie-Warnschwelle auf {val}% gesetzt.")
        handle_einstellungen(chat_id, message_id)

    elif data.startswith("set_safety_"):
        val_str = data[len("set_safety_"):]
        try:
            val = int(val_str)
            meta = _SETTINGS_META["SAFETY_TIMEOUT_MINUTES"]
            if not (meta["min"] <= val <= meta["max"]):
                raise ValueError
        except (ValueError, KeyError):
            telegram_client.answer_callback_query(cb_id, "Ungültiger Wert", show_alert=True)
            return
        config.set_setting("SAFETY_TIMEOUT_MINUTES", val)
        telegram_client.answer_callback_query(cb_id, f"Sicherheits-Timeout auf {val} Min gesetzt.")
        handle_einstellungen(chat_id, message_id)

    elif data.startswith("reset_setting_"):
        key = data[len("reset_setting_"):]
        meta = _SETTINGS_META.get(key)
        if not meta:
            telegram_client.answer_callback_query(cb_id, "Unbekannte Einstellung", show_alert=True)
            return
        config.reset_setting(key)
        telegram_client.answer_callback_query(cb_id, f"{meta['label']} zurückgesetzt.")
        handle_einstellungen(chat_id, message_id)

    elif data == "einst_close":
        telegram_client.answer_callback_query(cb_id)
        telegram_client.edit_message_text(chat_id, message_id, "_Einstellungen geschlossen._", {"inline_keyboard": []})

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
    vol_str = f"{event.target_volume} l" if event.target_volume > 0 else "kein Limit"
    source_str = "Zeitplan" if event.source == "schedule" else "Manuell"
    msg = (
        f"🚿 *Wasser marsch!*\n"
        f"⏱️ Zeitlimit: {event.duration} Min · 💧 Volumen: {vol_str}\n"
        f"Quelle: {source_str}"
    )
    telegram_client.broadcast_notification(msg)

def _on_watering_completed(event: WateringCycleCompleted):
    if "Volumenlimit" in event.details:
        msg = (
            f"🏁 *Fertig — {event.volume_run:.1f} l sind durch!*\n"
            f"⏱️ Laufzeit: ca. {event.duration_run} Min"
        )
    else:
        msg = (
            f"🏁 *Zeitlimit erreicht*\n"
            f"⏱️ {event.duration_run} Min · 💧 {event.volume_run:.1f} l"
        )
    telegram_client.broadcast_notification(msg)

def _on_watering_failed(event: WateringCycleFailed):
    msg = (
        f"⚠️ *Notfall-Abschaltung*\n"
        f"Sicherheits-Timer nach {event.duration_run} Min ausgelöst.\n"
        f"💧 {event.volume_run:.1f} l geflossen."
    )
    telegram_client.broadcast_notification(msg)

def _on_watering_stopped(event: WateringCycleStopped):
    msg = (
        f"🛑 *Guss gestoppt*\n"
        f"⏱️ Laufzeit: ca. {event.duration_run} Min · 💧 {event.volume_run:.1f} l"
    )
    telegram_client.broadcast_notification(msg)

def _on_daily_report(event: DailyReportTriggered):
    from ..adapters import chart
    chart_result = chart.generate_weather_chart()
    if chart_result:
        image_bytes, caption = chart_result
        telegram_client.broadcast_photo(image_bytes, caption=caption)
    telegram_client.broadcast_notification(event.report_text)

def _on_watering_skipped(event: WateringSkipped):
    telegram_client.broadcast_notification(
        f"🌧 *Heute übernimmt der Regen*\n"
        f"Zeitplan '{event.schedule_name}' übersprungen -- {event.details}"
    )

def _on_schedule_failed(event: ScheduleFailed):
    telegram_client.broadcast_notification(f"⚠️ *Fehler bei Zeitplan '{event.schedule_name}'!*\n{event.details}")

def _on_watering_scaled(event: WateringScaled):
    pct = int(round(event.factor * 100))
    msg = (
        f"💧 *Guss reduziert ({pct} %)*\n"
        f"Zeitplan '{event.schedule_name}': {event.duration_scaled} min"
    )
    if event.volume_original > 0:
        msg += f" / {event.volume_scaled} L"
    msg += f" (statt {event.duration_original} min"
    if event.volume_original > 0:
        msg += f" / {event.volume_original} L"
    msg += ")."
    if event.reasons:
        msg += f"\n{event.reasons[0]}"
    telegram_client.broadcast_notification(msg)

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

_RAIN_FLAG_KEY = "rain_sensor_raining_flag"

def _on_rain_sensor_measured(event: RainSensorMeasured):
    prev_flag = database.get_metadata(_RAIN_FLAG_KEY, "0")
    if event.is_raining and prev_flag != "1":
        database.set_metadata(_RAIN_FLAG_KEY, "1")
        telegram_client.broadcast_notification(
            f"🌧 *Regen erkannt* — {event.rainlevel_mm} mm"
        )
    elif not event.is_raining and prev_flag == "1":
        database.set_metadata(_RAIN_FLAG_KEY, "0")
        telegram_client.broadcast_notification("🌤 *Regen vorbei*")

def _on_watering_interrupted(event: WateringCycleInterrupted):
    valve = database.get_valve_by_mqtt_name(event.mqtt_name) if event.mqtt_name else None
    valve_name = valve["wish_name"] if valve else "Ventil"
    rain_mm = event.rain_mm
    rain_str = f" · {rain_mm} mm erkannt" if rain_mm > 0 else ""
    msg = (
        f"🌧 *Regen übernimmt — Guss gestoppt*\n"
        f"{valve_name} · {event.duration_run} Min · {event.volume_run:.1f} l geflossen{rain_str}"
    )
    telegram_client.broadcast_notification(msg)

def _on_rain_sensor_inactivity_alert(event: RainSensorInactivityAlertTriggered):
    msg = (
        f"⚠️ *Regensensor nicht erreichbar* — seit {event.hours_silent:.1f} h "
        f"keine Messung (Limit: {event.timeout_hours:.0f} h)."
    )
    telegram_client.broadcast_notification(msg)

def _on_rain_sensor_inactivity_resolved(event: RainSensorInactivityAlertResolved):
    telegram_client.broadcast_notification("🟢 *Regensensor wieder aktiv* — Messung empfangen.")

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
    _global_bus.subscribe(WateringScaled, _on_watering_scaled)
    _global_bus.subscribe(ScheduleFailed, _on_schedule_failed)
    _global_bus.subscribe(InactivityAlertTriggered, _on_inactivity_alert)
    _global_bus.subscribe(InactivityAlertResolved, _on_inactivity_resolved)
    _global_bus.subscribe(CameraInactivityAlertTriggered, _on_camera_inactivity_alert)
    _global_bus.subscribe(CameraInactivityAlertResolved, _on_camera_inactivity_resolved)
    _global_bus.subscribe(RainSensorMeasured, _on_rain_sensor_measured)
    _global_bus.subscribe(WateringCycleInterrupted, _on_watering_interrupted)
    _global_bus.subscribe(RainSensorInactivityAlertTriggered, _on_rain_sensor_inactivity_alert)
    _global_bus.subscribe(RainSensorInactivityAlertResolved, _on_rain_sensor_inactivity_resolved)
