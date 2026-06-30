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
from ..core.camera_schedule import next_photo_target as _next_photo_target
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
    WateringRainWarning,
)
from ..adapters import weather as _weather_adapter
from ..core.watchdog_events import InactivityAlertTriggered, InactivityAlertResolved
from ..core.camera_events import CameraInactivityAlertTriggered, CameraInactivityAlertResolved, TimedPhotoCaptured
from ..core.sensor_events import RainSensorMeasured, RainSensorInactivityAlertTriggered, RainSensorInactivityAlertResolved
from ..core.valve_events import UnexpectedValveOpened, UnexpectedValveResolved
from ..core.nebel_events import NebelIntervalStarted, NebelIntervalEnded

logger = logging.getLogger("garden_telegram_ui")

# Module-level controller reference — set once at daemon startup by main.py
_watering_ctrl = None
_nebel_ctrl = None

def set_watering_controller(ctrl) -> None:
    """Verdrahtet die Guss-Steuerung für manuelle Bewässerungsbefehle. Einmalig von main.py aufrufen."""
    global _watering_ctrl
    _watering_ctrl = ctrl

def set_nebel_controller(ctrl) -> None:
    """Verdrahtet die Nebel-Steuerung für Sofort-Nebel (Feature 0032). Einmalig von main.py aufrufen."""
    global _nebel_ctrl
    _nebel_ctrl = ctrl

def _resolve_valve_wish_name(mqtt_name: str) -> str:
    """Löst den Wunschnamen eines Ventils auf; Fallback ist der mqtt_name."""
    try:
        for v in database.get_all_valves():
            if v.get("mqtt_name") == mqtt_name:
                return v.get("wish_name") or mqtt_name
    except Exception:
        pass
    return mqtt_name

def _start_sofort_nebel(valve: dict, minutes: int, on_seconds: int = None, pause_minutes: int = None):
    """Startet einen Sofort-Nebel auf einem Ventil; Laufzeit hart gedeckelt. (Feature 0032/0031)

    Stoß-Dauer und Pause werden pro Lauf übergeben (Feature 0031); fehlen sie, gelten die
    Config-Defaults als Fallback. Es wird nichts persistiert.
    """
    if _nebel_ctrl is None:
        return False, "Nebel-Steuerung nicht initialisiert."
    on_seconds = on_seconds if on_seconds is not None else config.NEBEL_ON_SECONDS
    pause_minutes = pause_minutes if pause_minutes is not None else config.NEBEL_PAUSE_MINUTES
    capped = min(minutes, config.NEBEL_MANUAL_MAX_MINUTES)
    end = datetime.now() + timedelta(minutes=capped)
    return _nebel_ctrl.start(
        valve["mqtt_name"], on_seconds, pause_minutes, end, "nebel_manual",
    )

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
        [{"text": "📊 Status"}, {"text": "💧 Gießcheck"}],
        [{"text": "🚿 Bewässern"}, {"text": "🛑 Stopp"}],
        [{"text": "📅 Zeitpläne"}, {"text": "📷 Kamera"}],
        [{"text": "⚙️ Einstellungen"}],
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

def get_mode_wizard_keyboard() -> dict:
    """Auswahl der Zeitplan-Art: Bewässerung oder Nebel-Intervall (Feature 0032)."""
    return {
        "inline_keyboard": [
            [
                {"text": "🚿 Bewässerung", "callback_data": "wiz_mode_watering"},
                {"text": "🌫️ Nebel", "callback_data": "wiz_mode_nebel"},
            ],
            [{"text": "❌ Abbrechen", "callback_data": "wiz_cancel"}],
        ]
    }

def get_nebel_end_hour_keyboard() -> dict:
    """Endstunde des Nebel-Fensters (6x4-Grid, eigene Callbacks)."""
    rows = []
    for r in range(4):
        row = [{"text": f"{r * 6 + c:02d}", "callback_data": f"nb_ehour_{r * 6 + c}"} for c in range(6)]
        rows.append(row)
    rows.append([{"text": "❌ Abbrechen", "callback_data": "wiz_cancel"}])
    return {"inline_keyboard": rows}

def get_nebel_end_minute_keyboard() -> dict:
    """Endminute des Nebel-Fensters (5-Minuten-Schritte, eigene Callbacks)."""
    rows = []
    for r in range(3):
        row = [{"text": f"{(r * 4 + c) * 5:02d}", "callback_data": f"nb_emin_{(r * 4 + c) * 5}"} for c in range(4)]
        rows.append(row)
    rows.append([{"text": "❌ Abbrechen", "callback_data": "wiz_cancel"}])
    return {"inline_keyboard": rows}

def get_nebel_on_keyboard(prefix: str = "nb_on", cancel_cb: str = "wiz_cancel") -> dict:
    """Dauer eines Nebelstoßes in Sekunden. Eigener Callback-Präfix trennt Zeitplan- und Sofort-Flow."""
    presets = [10, 15, 20, 30, 45, 60]
    row = [{"text": f"{s}s", "callback_data": f"{prefix}_{s}"} for s in presets]
    return {"inline_keyboard": [row, [{"text": "❌ Abbrechen", "callback_data": cancel_cb}]]}

def get_nebel_pause_keyboard(prefix: str = "nb_pause", cancel_cb: str = "wiz_cancel") -> dict:
    """Pause zwischen Nebelstößen in Minuten. Eigener Callback-Präfix trennt Zeitplan- und Sofort-Flow."""
    presets = [1, 2, 3, 5, 10, 15]
    row = [{"text": f"{m}min", "callback_data": f"{prefix}_{m}"} for m in presets]
    return {"inline_keyboard": [row, [{"text": "❌ Abbrechen", "callback_data": cancel_cb}]]}

def get_nebel_now_keyboard() -> dict:
    """Laufzeit-Auswahl für den Sofort-Nebel (gedeckelt durch NEBEL_MANUAL_MAX_MINUTES)."""
    presets = [30, 60, 120]
    row = [{"text": f"{m} Min", "callback_data": f"nebel_dur_{m}"} for m in presets]
    return {"inline_keyboard": [
        row,
        [{"text": "🛑 Nebel stoppen", "callback_data": "nebel_stop"}],
        [{"text": "❌ Abbrechen", "callback_data": "nebel_cancel"}],
    ]}

def _schedule_valve_name(sched_id) -> str:
    """Wunschname des dem Zeitplan zugewiesenen Ventils; Fallback wenn keines zugewiesen."""
    try:
        vids = database.get_schedule_valves(sched_id)
        if vids:
            v = database.get_valve_by_id(vids[0])
            if v:
                return v["wish_name"]
    except Exception:
        pass
    return "Standard"


def _wizard_valve_or_days(state: dict) -> tuple:
    """Nächster Bewässerungs-Wizard-Schritt nach der Mengen-Auswahl.

    Wie beim Nebel-Wizard: bei mehreren Ventilen eine Ventil-Auswahl (genau eines),
    bei höchstens einem Ventil automatisch zuweisen und direkt zu den Wochentagen.
    Mutiert `state` und liefert (text, keyboard) für den Aufrufer (edit/send).
    """
    valves = database.get_all_valves()
    if len(valves) > 1:
        state["step"] = "wiz_valve"
        rows = [[{"text": f"🚰 {_md_escape(v['wish_name'])}", "callback_data": f"wv_valve_{v['id']}"}]
                for v in valves]
        rows.append([{"text": "❌ Abbrechen", "callback_data": "wiz_cancel"}])
        return (f"🆕 *Zeitplan '{state['name']}'*\n\nWelches *Ventil* soll dieser Zeitplan steuern?",
                {"inline_keyboard": rows})
    if valves:
        state["valve_id"] = valves[0]["id"]
    state["step"] = 6
    state["days"] = []
    return (f"🆕 *Neuen Zeitplan '{state['name']}' (Schritt 6/6)*\n\n"
            f"Wähle die *Wochentage* aus, an denen bewässert werden soll:\n\n*Ausgewählt: Keine*",
            get_days_wizard_keyboard([]))


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


def _md_escape(text) -> str:
    """Neutralisiert die Sonderzeichen der Telegram-Legacy-Markdown (_ * ` [) in Freitext.

    Ohne Escaping bricht z.B. ein Ventilname „Beet_1" die Markdown-Analyse und Telegram
    verwirft die ganze Nachricht mit HTTP 400. Backslash-Escaping entspricht dem üblichen
    escape_markdown(v1) und wird von der Legacy-Markdown korrekt als literal gerendert.
    """
    if not text:
        return ""
    return re.sub(r"([_*`\[])", r"\\\1", str(text))


def _format_valve_compact(valve: dict) -> str:
    """Einzeilige Ventil-Darstellung für grüne Geräte (keine technischen IDs)."""
    battery = valve.get("battery")
    lqi = valve.get("linkquality")
    battery_label = _get_battery_description(battery if battery is not None else 100)
    lqi_label = _get_lqi_label(lqi if lqi is not None else 100)
    return f"{_md_escape(valve['wish_name'])} · 🟢 aktiv · {battery_label} · 📶 {lqi_label}"


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
        f"{icon} {_md_escape(valve['wish_name'])}\n"
        f"   🔋 {battery_val} % · 📶 {lqi_desc}"
        f"{last_signal_line}\n"
        # Code-Span: der mqtt_name (z.B. valve_ffff) enthält Unterstriche; ohne Backticks
        # bricht das die Telegram-Markdown-Analyse und die ganze Nachricht wird 400-verworfen.
        f"   ID: `{valve['mqtt_name']}`"
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

def handle_einstellungen_menu(chat_id: int):
    """Zeigt das Einstellungen-Untermenü: Kopplung, Kamera-Einstellungen, Schwellenwerte, Update."""
    telegram_client.send_message(
        chat_id,
        "⚙️ *Einstellungen*\n\nWas möchtest du einrichten?",
        {
            "inline_keyboard": [
                [
                    {"text": "🔧 Ventil koppeln", "callback_data": "setup_confirm"},
                    {"text": "📷 Kamera koppeln", "callback_data": "camsetup_start"},
                ],
                [
                    {"text": "⏱ Kamera-Einstellungen", "callback_data": "camsetup_settings"},
                    {"text": "📊 Schwellenwerte", "callback_data": "einst_open"},
                ],
                [{"text": "🔄 Software-Update", "callback_data": "update_start"}],
            ]
        }
    )


def handle_kamera_menu(chat_id: int):
    """Zeigt das Kamera-Untermenü (Inline): Foto anzeigen, Fotos löschen, Fotozeiten."""
    telegram_client.send_message(
        chat_id,
        "📷 *Kamera*\n\nWas möchtest du tun?",
        {
            "inline_keyboard": [
                [
                    {"text": "📸 Foto anzeigen", "callback_data": "kamera_foto"},
                    {"text": "🗑️ Fotos löschen", "callback_data": "kamera_verlauf"},
                ],
                [{"text": "⏰ Fotozeiten", "callback_data": "kamera_fotozeiten"}],
            ]
        }
    )

def handle_bewaessern_start(chat_id: int):
    """Einstieg „Bewässern": gemeinsame Art-Auswahl Guss / Sofort-Nebel (Feature 0031).

    Muster Art → Ventil → Details. Guss-Zweig: water_mode_guss; Nebel-Zweig: nebel_now.
    """
    telegram_client.send_message(
        chat_id,
        "🚿 *Bewässern*\n\nWas möchtest du?",
        {
            "inline_keyboard": [
                [
                    {"text": "🚿 Guss", "callback_data": "water_mode_guss"},
                    {"text": "🌫️ Sofort-Nebel", "callback_data": "nebel_now"},
                ],
                [{"text": "❌ Abbrechen", "callback_data": "man_cancel"}],
            ]
        }
    )


def _active_stop_sources() -> list:
    """Sammelt alle aktiven Aktuierungen als (kind, mqtt_name).

    Güsse + extern geöffnete Ventile (ADR 0032) + laufendes Nebel-Fenster. Auch ein
    manuell/extern geöffnetes Ventil ist über Stopp schließbar (nutzer-initiiert).
    """
    sources = []
    if _watering_ctrl:
        for name in _watering_ctrl.get_active_valve_names():
            sources.append(("guss", name))
        for name in _watering_ctrl.get_unexpected_open_valves():
            sources.append(("extern", name))
    if _nebel_ctrl:
        nebel_name = _nebel_ctrl.get_active_window()
        if nebel_name:
            sources.append(("nebel", nebel_name))
    return sources


def _stop_source(kind: str, mqtt_name: str):
    """Stoppt eine einzelne Quelle (Guss, extern offen oder Nebel) und liefert das Label."""
    valve = database.get_valve_by_mqtt_name(mqtt_name)
    label = valve["wish_name"] if valve else mqtt_name
    if kind == "guss":
        _watering_ctrl.stop_watering(mqtt_name)
    elif kind == "extern":
        _watering_ctrl.force_close(mqtt_name)
        label = f"{label} (extern geöffnet)"
    else:
        _nebel_ctrl.stop(mqtt_name)
        label = f"{label} (Nebel)"
    return label


def handle_stopp(chat_id: int):
    """Querschnittlicher Notfall-Aus über Güsse UND laufendes Nebel-Fenster (Feature 0031).

    0/1 aktive Quelle → sofort stoppen (kein Extra-Klick im Notfall). >1 → Auswahl
    inkl. „Alle stoppen".
    """
    sources = _active_stop_sources()
    if not sources:
        telegram_client.send_message(chat_id, "ℹ️ Es läuft gerade nichts.")
        return
    if len(sources) == 1:
        kind, name = sources[0]
        label = _stop_source(kind, name)
        telegram_client.send_message(chat_id, f"🛑 *Gestoppt:* {label}", get_main_keyboard())
        return

    rows = []
    for kind, name in sources:
        valve = database.get_valve_by_mqtt_name(name)
        wish = valve["wish_name"] if valve else name
        if kind == "guss":
            rows.append([{"text": f"🛑 {wish}", "callback_data": f"stop_valve_{name}"}])
        elif kind == "extern":
            rows.append([{"text": f"🛑 {wish} (extern)", "callback_data": f"stop_extern_{name}"}])
        else:
            rows.append([{"text": f"🛑 {wish} (Nebel)", "callback_data": f"stop_nebel_{name}"}])
    rows.append([{"text": "🛑 Alle stoppen", "callback_data": "stop_valve_all"}])
    telegram_client.send_message(
        chat_id,
        "🛑 *Stopp*\n\nMehrere Quellen aktiv — was soll gestoppt werden?",
        {"inline_keyboard": rows}
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

def handle_photo_clear(chat_id: int):
    """Startet das Löschen der Bild-Historie: Kamera-Auswahl bei mehreren, sonst direkt zur Rückfrage."""
    cameras = database.get_all_cameras()
    if not cameras:
        telegram_client.send_message(chat_id, "❌ Es sind keine Kameras gekoppelt.")
        return

    if len(cameras) == 1:
        _ask_photo_clear_confirmation(chat_id, cameras[0]["wish_name"])
    else:
        rows = [[{"text": cam["wish_name"], "callback_data": f"photoclear_{cam['wish_name']}"}]
                for cam in cameras]
        telegram_client.send_message(
            chat_id,
            "Von welcher Kamera möchtest du die Bild-Historie löschen?",
            {"inline_keyboard": rows}
        )

def _ask_photo_clear_confirmation(chat_id: int, wish_name: str):
    """Zeigt die Ja/Nein-Rückfrage mit der Anzahl betroffener Bilder; bei 0 Bildern nur ein Hinweis."""
    from .. import scheduler
    count = scheduler.count_camera_history(wish_name)
    if count == 0:
        telegram_client.send_message(chat_id, f"ℹ️ Für die Kamera '{wish_name}' sind keine Bilder vorhanden.")
        return

    telegram_client.send_message(
        chat_id,
        f"🗑️ *Bild-Historie löschen*\n\n"
        f"Möchtest du wirklich alle *{count}* Bilder der Kamera *'{wish_name}'* löschen?\n\n"
        "_Diese Aktion kann nicht rückgängig gemacht werden._ Das aktuellste Foto bleibt erhalten.",
        {"inline_keyboard": [[
            {"text": "✅ Ja, löschen", "callback_data": f"photoclear_confirm_{wish_name}"},
            {"text": "❌ Abbrechen", "callback_data": "cancel"}
        ]]}
    )

# --- Getimte Kamera-Aufnahmen (Feature 0030) ---

_phtadd_states: dict[int, dict] = {}


def _get_photo_time_hour_keyboard() -> dict:
    rows = []
    for r in range(4):
        row = []
        for c in range(6):
            h = r * 6 + c
            row.append({"text": f"{h:02d}", "callback_data": f"phtadd_h_{h}"})
        rows.append(row)
    rows.append([{"text": "❌ Abbrechen", "callback_data": "cancel"}])
    return {"inline_keyboard": rows}


def _get_photo_time_minute_keyboard() -> dict:
    rows = []
    for r in range(3):
        row = []
        for c in range(4):
            m = (r * 4 + c) * 5
            row.append({"text": f"{m:02d}", "callback_data": f"phtadd_m_{m}"})
        rows.append(row)
    rows.append([{"text": "❌ Abbrechen", "callback_data": "cancel"}])
    return {"inline_keyboard": rows}


def handle_aufnahmen(chat_id: int):
    """Zeigt Foto-Uhrzeiten in zwei Abschnitten: feste Zeiten + Guss-Fotos."""
    fixed_times = database.get_photo_times()
    active_schedules = [s for s in database.get_schedules() if s.get("is_active")]
    add_button = [{"text": "➕ Uhrzeit hinzufügen", "callback_data": "phtadd_start"}]

    if not fixed_times and not active_schedules:
        telegram_client.send_message(
            chat_id,
            "📷 *Foto-Uhrzeiten*\n\nKeine Aufnahme-Uhrzeiten konfiguriert.",
            {"inline_keyboard": [add_button]}
        )
        return

    lines = ["📷 *Foto-Uhrzeiten*"]
    rows = []

    if fixed_times:
        lines.append("\n⏰ *Feste Zeiten*")
        for t in fixed_times:
            lines.append(f"• {t['time']} Uhr")
        for t in fixed_times:
            rows.append([{"text": f"🗑️ {t['time']}", "callback_data": f"phtime_del_ask_{t['id']}"}])

    if active_schedules:
        lines.append("\n🌿 *Nach Güssen*")
        offset = config.CAMERA_AFTER_GUSS_OFFSET_MINUTES
        for s in active_schedules:
            try:
                h, m = map(int, s["time"].split(":"))
                capture_min = h * 60 + m + s["duration_minutes"] + offset
                cap_h, cap_m = divmod(capture_min % (24 * 60), 60)
                lines.append(
                    f"• {cap_h:02d}:{cap_m:02d} Uhr · {_md_escape(s['name'])}"
                )
            except (ValueError, KeyError):
                lines.append(f"• {_md_escape(s.get('name', '?'))}")

    rows.append(add_button)
    telegram_client.send_message(chat_id, "\n".join(lines), {"inline_keyboard": rows})


def _on_timed_photo_captured(event: TimedPhotoCaptured):
    """Sendet ein getimtes Foto mit Beschriftung an alle Benutzer."""
    path = Path(event.file_path)
    if not path.exists():
        return
    telegram_client.broadcast_photo(path.read_bytes(), caption=event.caption)


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
        source_label = "Sensor offline · Regen-24h via Open-Meteo"
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
        camera_sections.append(f"{_md_escape(wish_name)} · {cam_status}{battery_label}")

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
            f" · {_md_escape(nxt['name'])} · {nxt['duration_minutes']} Min\n"
        )

    next_photo_text = ""
    if cameras:
        photo_times = database.get_photo_times()
        photo_target = _next_photo_target(
            now, all_schedules, photo_times, config.CAMERA_AFTER_GUSS_OFFSET_MINUTES
        )
        if photo_target:
            pt_dt, pt_label = photo_target
            pt_day = "heute" if pt_dt.date() == now.date() else "morgen"
            if pt_label["type"] == "guss":
                pt_anlass = f"nach Guss „{_md_escape(pt_label['name'])}“"
            else:
                pt_anlass = "feste Fotozeit"
            next_photo_text = (
                f"📷 *Nächstes Foto:* {pt_day} {pt_dt.strftime('%H:%M')} Uhr · {pt_anlass}\n"
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
        f"{next_photo_text}"
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
            "💡 Tippe unten auf „➕ Neuer Zeitplan“, um den geführten Assistenten zu starten."
        )
        telegram_client.send_message(chat_id, msg, get_schedules_keyboard())
        return

    lines = []
    for s in schedules:
        status = "✅ Aktiv" if s['is_active'] == 1 else "❌ Inaktiv"
        days_formatted = format_days_german(s['days'].split(',')) if s['days'] else 'Keine'
        vol_str = f"{s['target_volume_liters']} Liter" if s.get('target_volume_liters', 0) > 0 else "Keines"
        lines.append(
            f"🆔 *ID {s['id']}: {_md_escape(s['name'])}*\n"
            f"   - ⏰ Startzeit: {s['time']} Uhr\n"
            f"   - 📅 Tage: {days_formatted}\n"
            f"   - ⏳ Dauer: {s['duration_minutes']} Min\n"
            f"   - 💧 Menge: {vol_str}\n"
            f"   - Status: {status}\n"
        )

    msg = "📅 *Aktuelle Zeitsteuerung (Zeitpläne):*\n\n" + "\n".join(lines)
    telegram_client.send_message(chat_id, msg, get_schedules_inline_keyboard(schedules))

# Legacy-Textbefehle /add, /delete, /toggle wurden mit Feature 0031 entfernt
# (durch den Zeitplan-Wizard ersetzt, Feature 0021).

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
    lines = ["*📊 Schwellenwerte*\n"]
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
                telegram_client.send_message(chat_id, f"🗑️ Zeitplan *'{_md_escape(name)}'* wurde gelöscht.", get_main_keyboard())
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
                if state.get("mode") == "nebel":
                    telegram_client.send_message(
                        chat_id,
                        f"🌫️ *Nebel-Intervall '{text}'*\n\nZu welcher *Stunde* soll das Nebel-Fenster starten?",
                        get_hour_keyboard()
                    )
                else:
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
                    _state_touch(wizard_states, chat_id)
                    text, kb = _wizard_valve_or_days(state)
                    telegram_client.send_message(chat_id, text, kb)
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
                    mqtt_name = man_state.get("mqtt_name", "garden_valve")
                    _state_del(manual_states, chat_id)

                    if _watering_ctrl:
                        success, response = _watering_ctrl.start_watering(dur, vol, "manual", mqtt_name=mqtt_name)
                    else:
                        success, response = False, "Guss-Steuerung nicht initialisiert."
                    if not success:
                        telegram_client.send_message(chat_id, f"❌ Fehler beim Starten: {response}", get_main_keyboard())
                except ValueError:
                    telegram_client.send_message(chat_id, "❌ *Ungültige Eingabe.* Bitte gib eine Zahl größer als 0 Liter ein:")
                return

    # Slash-Befehle exakt auflösen (Token vor Leerzeichen/@), damit z. B. /status nicht
    # fälschlich /statusbericht fängt. Tastatur-Buttons werden per Volltreffer gematcht.
    cmd = text.split()[0].split("@")[0] if text.startswith("/") else ""

    if cmd == "/start":
        telegram_client.send_message(
            chat_id,
            "👋 *Willkommen bei der Gartenbewässerung-Steuerung!*\n\n"
            "Ich bin Ihr lokaler Assistent. Nutze die Buttons unten oder "
            "den Chat-Befehl `/status`, um dein System zu steuern.",
            get_main_keyboard()
        )
    elif text == "💧 Gießcheck":
        handle_giesscheck(chat_id)
    elif text == "📊 Status" or cmd == "/status":
        handle_status(chat_id)
    elif cmd == "/tagesbericht":
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
    elif text == "📅 Zeitpläne":
        handle_schedules(chat_id)
    elif text == "⚙️ Einstellungen":
        handle_einstellungen_menu(chat_id)
    elif text == "📷 Kamera":
        handle_kamera_menu(chat_id)
    elif cmd == "/update":
        # /update ist registriert; Ziel der CI-Build-Benachrichtigung.
        handle_update(chat_id)
    elif text == "🚿 Bewässern":
        handle_bewaessern_start(chat_id)
    elif text == "🛑 Stopp":
        handle_stopp(chat_id)
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
    elif data.startswith("rainoverride_"):
        # Regen-Übersteuerung (Feature 0034): Flag für genau diesen Lauf setzen.
        rest = data[len("rainoverride_"):]
        sid_str, _, datum = rest.partition("_")
        try:
            run_date = datetime.strptime(datum, "%Y-%m-%d").date()
        except ValueError:
            run_date = None
        if run_date is not None and run_date < datetime.now().date():
            # Lauf liegt in der Vergangenheit — wirkungslos (ADR 0035).
            telegram_client.answer_callback_query(
                cb_id, "Zu spät — der Guss ist bereits durch.", show_alert=True)
        else:
            database.set_metadata(f"rain_override:{sid_str}:{datum}", "1")
            telegram_client.answer_callback_query(cb_id, "🚿 Regen wird ignoriert")
            telegram_client.edit_message_text(
                chat_id, message_id,
                "🚿 *Regen-Übersteuerung aktiv*\n"
                "Der Guss läuft zu seiner geplanten Zeit mit den vollen Werten.")
    elif data == "wiz_start":
        telegram_client.answer_callback_query(cb_id, "Zeitplan-Assistent gestartet")
        telegram_client.send_message(
            chat_id,
            "🆕 *Neuen Zeitplan anlegen*\n\nWelche Art von Zeitplan möchtest du anlegen?\n\n"
            "🚿 *Bewässerung* — einmaliger Guss mit Zeit-/Volumenlimit\n"
            "🌫️ *Nebel* — wiederkehrende Kühlung der Terrasse",
            get_mode_wizard_keyboard()
        )

    elif data in ("wiz_mode_watering", "wiz_mode_nebel"):
        mode = "nebel" if data == "wiz_mode_nebel" else "watering"
        _state_set(wizard_states, chat_id, {"step": 1, "mode": mode})
        telegram_client.answer_callback_query(cb_id)
        art = "Nebel-Intervall" if mode == "nebel" else "Zeitplan"
        telegram_client.edit_message_text(
            chat_id, message_id,
            f"🆕 *Neues {art} anlegen — Name*\n\nBitte gib einen *Namen* ein "
            f"(z. B. *{'Terrassen-Nebel' if mode == 'nebel' else 'Rasen morgens'}*):",
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
            _state_touch(wizard_states, chat_id)
            telegram_client.answer_callback_query(cb_id, f"Minute: {minute:02d}")
            if state.get("mode") == "nebel":
                state["step"] = "nebel_endhour"
                telegram_client.edit_message_text(
                    chat_id, message_id,
                    f"🌫️ *Nebel '{state['name']}' ab {state['hour']:02d}:{minute:02d}*\n\n"
                    f"Bis zu welcher *Stunde* soll genebelt werden? (Fensterende)",
                    get_nebel_end_hour_keyboard()
                )
            else:
                state["step"] = 4
                telegram_client.edit_message_text(
                    chat_id, message_id,
                    f"🆕 *Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{minute:02d} (Schritt 4/6)*\n\nWie lange soll *maximal* bewässert werden? (Zeitlimit)\n\n*Aus Sicherheitsgründen max. 25 Min.*",
                    get_duration_wizard_keyboard("wiz")
                )

    elif data.startswith("nb_ehour_"):
        state = _state_get(wizard_states, chat_id)
        if state is not None:
            state["end_hour"] = int(data.split("_")[2])
            state["step"] = "nebel_endmin"
            _state_touch(wizard_states, chat_id)
            telegram_client.answer_callback_query(cb_id, f"Bis {state['end_hour']:02d}:??")
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"🌫️ *Nebel '{state['name']}'*\n\nZu welcher *Minute* soll das Fenster enden?",
                get_nebel_end_minute_keyboard()
            )

    elif data.startswith("nb_emin_"):
        state = _state_get(wizard_states, chat_id)
        if state is not None:
            end_minute = int(data.split("_")[2])
            # Endzeit muss nach der Startzeit liegen (kein Mitternachts-Fenster) — sonst
            # würde das Fenster nie matchen (Scheduler prüft start <= jetzt < end).
            if (state["end_hour"], end_minute) <= (state["hour"], state["minute"]):
                state["step"] = "nebel_endhour"
                _state_touch(wizard_states, chat_id)
                telegram_client.answer_callback_query(
                    cb_id, "⚠️ Ende muss nach dem Start liegen!", show_alert=True)
                telegram_client.edit_message_text(
                    chat_id, message_id,
                    f"🌫️ *Nebel '{state['name']}' ab {state['hour']:02d}:{state['minute']:02d}*\n\n"
                    f"Das Fensterende muss *nach* dem Start liegen. Bis zu welcher *Stunde* soll genebelt werden?",
                    get_nebel_end_hour_keyboard()
                )
            else:
                state["end_minute"] = end_minute
                state["step"] = "nebel_on"
                _state_touch(wizard_states, chat_id)
                telegram_client.answer_callback_query(cb_id)
                telegram_client.edit_message_text(
                    chat_id, message_id,
                    f"🌫️ *Nebel '{state['name']}' bis {state['end_hour']:02d}:{end_minute:02d}*\n\n"
                    f"Wie lange soll ein einzelner *Nebelstoß* dauern?",
                    get_nebel_on_keyboard()
                )

    elif data.startswith("nb_on_"):
        state = _state_get(wizard_states, chat_id)
        if state is not None:
            state["on_seconds"] = int(data.split("_")[2])
            state["step"] = "nebel_pause"
            _state_touch(wizard_states, chat_id)
            telegram_client.answer_callback_query(cb_id, f"{state['on_seconds']}s")
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"🌫️ *Nebel '{state['name']}' — {state['on_seconds']}s pro Stoß*\n\n"
                f"Wie lange soll die *Pause* zwischen zwei Nebelstößen sein?",
                get_nebel_pause_keyboard()
            )

    elif data.startswith("nb_pause_"):
        state = _state_get(wizard_states, chat_id)
        if state is not None:
            state["pause_minutes"] = int(data.split("_")[2])
            _state_touch(wizard_states, chat_id)
            telegram_client.answer_callback_query(cb_id, f"{state['pause_minutes']}min")
            valves = database.get_all_valves()
            if not valves:
                _state_del(wizard_states, chat_id)
                telegram_client.edit_message_text(
                    chat_id, message_id,
                    "❌ Es ist noch kein Ventil gekoppelt. Koppel zuerst ein Ventil über ⚙️ Einstellungen ▸ 🔧 Ventil koppeln."
                )
            elif len(valves) == 1:
                state["valve_id"] = valves[0]["id"]
                state["step"] = 6
                state["days"] = []
                _state_touch(wizard_states, chat_id)
                telegram_client.edit_message_text(
                    chat_id, message_id,
                    f"🌫️ *Nebel '{state['name']}'*\n\nWähle die *Wochentage* aus, an denen genebelt werden soll:\n\n*Ausgewählt: Keine*",
                    get_days_wizard_keyboard([])
                )
            else:
                state["step"] = "nebel_valve"
                _state_touch(wizard_states, chat_id)
                rows = [[{"text": f"🚰 {v['wish_name']}", "callback_data": f"nb_valve_{v['id']}"}] for v in valves]
                rows.append([{"text": "❌ Abbrechen", "callback_data": "wiz_cancel"}])
                telegram_client.edit_message_text(
                    chat_id, message_id,
                    f"🌫️ *Nebel '{state['name']}'*\n\nWelches *Ventil* steuert die Nebeldüse?",
                    {"inline_keyboard": rows}
                )

    elif data.startswith("nb_valve_"):
        state = _state_get(wizard_states, chat_id)
        if state is not None:
            state["valve_id"] = int(data.split("_")[2])
            state["step"] = 6
            state["days"] = []
            _state_touch(wizard_states, chat_id)
            telegram_client.answer_callback_query(cb_id)
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"🌫️ *Nebel '{state['name']}'*\n\nWähle die *Wochentage* aus, an denen genebelt werden soll:\n\n*Ausgewählt: Keine*",
                get_days_wizard_keyboard([])
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
                _state_touch(wizard_states, chat_id)
                text, kb = _wizard_valve_or_days(state)
                telegram_client.edit_message_text(chat_id, message_id, text, kb)

    elif data.startswith("wv_valve_"):
        state = _state_get(wizard_states, chat_id)
        if state is not None:
            state["valve_id"] = int(data.split("_")[2])
            state["step"] = 6
            state["days"] = []
            _state_touch(wizard_states, chat_id)
            telegram_client.answer_callback_query(cb_id)
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"🆕 *Neuen Zeitplan '{state['name']}' (Schritt 6/6)*\n\n"
                f"Wähle die *Wochentage* aus, an denen bewässert werden soll:\n\n*Ausgewählt: Keine*",
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
            confirm_kb = {
                "inline_keyboard": [
                    [
                        {"text": "❌ Abbrechen", "callback_data": "wiz_cancel"},
                        {"text": "✅ Speichern", "callback_data": "wiz_confirm_save"}
                    ]
                ]
            }
            if state.get("mode") == "nebel":
                valve = database.get_valve_by_id(state.get("valve_id"))
                valve_name = _md_escape(valve["wish_name"]) if valve else "—"
                telegram_client.edit_message_text(
                    chat_id, message_id,
                    f"📝 *Zusammenfassung & Bestätigung*\n\n"
                    f"Bitte überprüfe das neue Nebel-Intervall:\n\n"
                    f"• *Name:* {state['name']}\n"
                    f"• *Fenster:* {state['hour']:02d}:{state['minute']:02d} – {state['end_hour']:02d}:{state['end_minute']:02d} Uhr\n"
                    f"• *Nebelstoß:* {state['on_seconds']} s · *Pause:* {state['pause_minutes']} min\n"
                    f"• *Ventil:* {valve_name}\n"
                    f"• *Tage:* {days_str}\n\n"
                    f"Soll dieses Nebel-Intervall gespeichert werden?",
                    confirm_kb
                )
            else:
                valve_line = ""
                if state.get("valve_id"):
                    v = database.get_valve_by_id(state["valve_id"])
                    if v:
                        valve_line = f"• *Ventil:* {_md_escape(v['wish_name'])}\n"
                telegram_client.edit_message_text(
                    chat_id, message_id,
                    f"📝 *Zusammenfassung & Bestätigung*\n\n"
                    f"Bitte überprüfe die Angaben für den neuen Zeitplan:\n\n"
                    f"• *Name:* {state['name']}\n"
                    f"• *Startzeit:* {state['hour']:02d}:{state['minute']:02d} Uhr\n"
                    f"• *Dauer:* {state['duration']} Min\n"
                    f"• *Wassermenge:* {state['volume']} Liter\n"
                    f"{valve_line}"
                    f"• *Tage:* {days_str}\n\n"
                    f"Soll dieser Zeitplan gespeichert werden?",
                    confirm_kb
                )

    elif data == "wiz_confirm_save":
        state = _state_get(wizard_states, chat_id)
        if state is not None:
            name = state["name"]
            time_str = f"{state['hour']:02d}:{state['minute']:02d}"
            days_str = ",".join(state["days"])

            if state.get("mode") == "nebel":
                telegram_client.answer_callback_query(cb_id, "Nebel-Intervall gespeichert!")
                end_str = f"{state['end_hour']:02d}:{state['end_minute']:02d}"
                db_id = database.add_schedule(
                    name, time_str, days_str, 0, mode="nebel", end_time=end_str,
                    on_seconds=state["on_seconds"], pause_minutes=state["pause_minutes"],
                )
                if db_id > 0 and state.get("valve_id"):
                    database.set_schedule_valves(db_id, [state["valve_id"]])
                _state_del(wizard_states, chat_id)
                if db_id > 0:
                    telegram_client.send_message(chat_id, f"🌫️ Nebel-Intervall *'{_md_escape(name)}'* erfolgreich angelegt!", get_main_keyboard())
                    handle_schedules(chat_id)
                else:
                    telegram_client.send_message(chat_id, "❌ Fehler beim Speichern des Nebel-Intervalls in der Datenbank.", get_main_keyboard())
            else:
                telegram_client.answer_callback_query(cb_id, "Zeitplan erfolgreich gespeichert!")
                duration = state["duration"]
                volume = state["volume"]
                db_id = database.add_schedule(name, time_str, days_str, duration, volume)
                if db_id > 0 and state.get("valve_id"):
                    database.set_schedule_valves(db_id, [state["valve_id"]])
                _state_del(wizard_states, chat_id)
                if db_id > 0:
                    telegram_client.send_message(chat_id, f"📅 Zeitplan *'{_md_escape(name)}'* erfolgreich angelegt!", get_main_keyboard())
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
        # bestehenden Flow-State (u. a. gewähltes mqtt_name aus der Ventil-Auswahl) erhalten
        state = _state_get(manual_states, chat_id) or {}
        if dur_str == "custom":
            state["step"] = "man_custom_duration"
            _state_set(manual_states, chat_id, state)
            telegram_client.edit_message_text(
                chat_id, message_id,
                "🚿 *Bewässern starten — Schritt 1/2*\n\nBitte gib die gewünschte Dauer in Minuten über die Tastatur ein (Zahl von 1 bis 25):",
                {"inline_keyboard": [[{"text": "❌ Abbrechen", "callback_data": "man_cancel"}]]}
            )
        else:
            dur = int(dur_str)
            state.update({"step": 2, "duration": dur})
            _state_set(manual_states, chat_id, state)
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
                mqtt_name = state.get("mqtt_name", "garden_valve")
                _state_del(manual_states, chat_id)

                if _watering_ctrl:
                    success, response = _watering_ctrl.start_watering(dur, vol, "manual", mqtt_name=mqtt_name)
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

    # --- Kamera-Untermenü (Feature 0031) ---
    elif data == "kamera_foto":
        telegram_client.answer_callback_query(cb_id)
        handle_photo(chat_id)

    elif data == "kamera_verlauf":
        telegram_client.answer_callback_query(cb_id)
        handle_photo_clear(chat_id)

    elif data == "kamera_fotozeiten":
        telegram_client.answer_callback_query(cb_id)
        handle_aufnahmen(chat_id)

    # --- Einstellungen-Untermenü (Feature 0031) ---
    elif data == "einst_open":
        telegram_client.answer_callback_query(cb_id)
        handle_einstellungen(chat_id)

    elif data == "update_start":
        telegram_client.answer_callback_query(cb_id)
        handle_update(chat_id)

    # --- Bewässern / Guss-Zweig: Art → Ventil → Zeitlimit (Feature 0031) ---
    elif data == "water_mode_guss":
        telegram_client.answer_callback_query(cb_id)
        valves = database.get_all_valves()
        if not valves:
            telegram_client.edit_message_text(
                chat_id, message_id,
                "❌ Es ist noch kein Ventil gekoppelt. Koppel zuerst ein Ventil über Einstellungen."
            )
        elif len(valves) == 1:
            _state_set(manual_states, chat_id, {"step": 1, "mqtt_name": valves[0]["mqtt_name"]})
            telegram_client.edit_message_text(
                chat_id, message_id,
                "🚿 *Bewässern starten — Schritt 1/2*\n\nWie lange soll *maximal* bewässert werden? (Zeitlimit)\n\n*Aus Sicherheitsgründen max. 25 Min.*",
                get_duration_wizard_keyboard("man")
            )
        else:
            rows = [[{"text": f"🚰 {v['wish_name']}", "callback_data": f"water_valve_{v['id']}"}] for v in valves]
            rows.append([{"text": "❌ Abbrechen", "callback_data": "man_cancel"}])
            telegram_client.edit_message_text(
                chat_id, message_id,
                "🚿 *Bewässern*\n\nWelches *Ventil* soll bewässern?",
                {"inline_keyboard": rows}
            )

    elif data.startswith("water_valve_"):
        vid = int(data[len("water_valve_"):])
        telegram_client.answer_callback_query(cb_id)
        valve = database.get_valve_by_id(vid)
        if valve is None:
            telegram_client.edit_message_text(chat_id, message_id, "❌ Ventil nicht gefunden.")
        else:
            _state_set(manual_states, chat_id, {"step": 1, "mqtt_name": valve["mqtt_name"]})
            telegram_client.edit_message_text(
                chat_id, message_id,
                "🚿 *Bewässern starten — Schritt 1/2*\n\nWie lange soll *maximal* bewässert werden? (Zeitlimit)\n\n*Aus Sicherheitsgründen max. 25 Min.*",
                get_duration_wizard_keyboard("man")
            )

    # --- Sofort-Nebel: Ventil → Stoß-Dauer → Pause → Laufzeit (Feature 0031) ---
    elif data == "nebel_now":
        telegram_client.answer_callback_query(cb_id, "Sofort-Nebel")
        valves = database.get_all_valves()
        if not valves:
            telegram_client.send_message(
                chat_id,
                "❌ Es ist noch kein Ventil gekoppelt. Koppel zuerst ein Ventil über Einstellungen."
            )
        elif len(valves) == 1:
            _state_set(manual_states, chat_id, {"flow": "nebel_now", "valve": valves[0]})
            telegram_client.send_message(
                chat_id,
                "🌫️ *Sofort-Nebel — Stoß-Dauer*\n\nWie lange soll ein Nebelstoß dauern?",
                get_nebel_on_keyboard("nebel_now_on", "nebel_cancel")
            )
        else:
            rows = [[{"text": f"🚰 {v['wish_name']}", "callback_data": f"nebel_now_valve_{v['id']}"}] for v in valves]
            rows.append([{"text": "❌ Abbrechen", "callback_data": "nebel_cancel"}])
            telegram_client.send_message(
                chat_id,
                "🌫️ *Sofort-Nebel*\n\nWelches *Ventil* steuert die Nebeldüse?",
                {"inline_keyboard": rows}
            )

    elif data.startswith("nebel_now_valve_"):
        vid = int(data[len("nebel_now_valve_"):])
        telegram_client.answer_callback_query(cb_id)
        valve = database.get_valve_by_id(vid)
        if valve is None:
            telegram_client.edit_message_text(chat_id, message_id, "❌ Ventil nicht gefunden.")
        else:
            _state_set(manual_states, chat_id, {"flow": "nebel_now", "valve": valve})
            telegram_client.edit_message_text(
                chat_id, message_id,
                "🌫️ *Sofort-Nebel — Stoß-Dauer*\n\nWie lange soll ein Nebelstoß dauern?",
                get_nebel_on_keyboard("nebel_now_on", "nebel_cancel")
            )

    elif data.startswith("nebel_now_on_"):
        on_seconds = int(data[len("nebel_now_on_"):])
        telegram_client.answer_callback_query(cb_id)
        state = _state_get(manual_states, chat_id)
        if state is None or state.get("flow") != "nebel_now":
            telegram_client.edit_message_text(chat_id, message_id, "⌛ Vorgang abgelaufen. Bitte erneut über „Bewässern“ starten.")
        else:
            state["on_seconds"] = on_seconds
            _state_set(manual_states, chat_id, state)
            telegram_client.edit_message_text(
                chat_id, message_id,
                "🌫️ *Sofort-Nebel — Pause*\n\nWie lange Pause zwischen den Stößen?",
                get_nebel_pause_keyboard("nebel_now_pause", "nebel_cancel")
            )

    elif data.startswith("nebel_now_pause_"):
        pause_minutes = int(data[len("nebel_now_pause_"):])
        telegram_client.answer_callback_query(cb_id)
        state = _state_get(manual_states, chat_id)
        if state is None or state.get("flow") != "nebel_now":
            telegram_client.edit_message_text(chat_id, message_id, "⌛ Vorgang abgelaufen. Bitte erneut über „Bewässern“ starten.")
        else:
            state["pause_minutes"] = pause_minutes
            _state_set(manual_states, chat_id, state)
            telegram_client.edit_message_text(
                chat_id, message_id,
                "🌫️ *Sofort-Nebel — Laufzeit*\n\nWie lange soll gekühlt werden?",
                get_nebel_now_keyboard()
            )

    elif data.startswith("nebel_dur_"):
        minutes = int(data.split("_")[2])
        telegram_client.answer_callback_query(cb_id)
        state = _state_get(manual_states, chat_id)
        if state is None or state.get("flow") != "nebel_now" or not state.get("valve"):
            telegram_client.edit_message_text(chat_id, message_id, "⌛ Vorgang abgelaufen. Bitte erneut über „Bewässern“ starten.")
        else:
            valve = state["valve"]
            on_seconds = state.get("on_seconds")
            pause_minutes = state.get("pause_minutes")
            _state_del(manual_states, chat_id)
            ok, msg = _start_sofort_nebel(valve, minutes, on_seconds, pause_minutes)
            if ok:
                telegram_client.edit_message_text(
                    chat_id, message_id,
                    f"🌫️ *Sofort-Nebel gestartet* für „{valve['wish_name']}“ "
                    f"({min(minutes, config.NEBEL_MANUAL_MAX_MINUTES)} Min, {on_seconds}s / {pause_minutes}min)."
                )
            else:
                telegram_client.edit_message_text(chat_id, message_id, f"❌ Fehler: {msg}")

    elif data == "nebel_stop":
        telegram_client.answer_callback_query(cb_id, "Nebel wird gestoppt")
        if _nebel_ctrl is not None:
            ok, msg = _nebel_ctrl.stop()
            telegram_client.edit_message_text(chat_id, message_id,
                                              "🛑 *Nebel gestoppt.*" if ok else f"ℹ️ {msg}")
        else:
            telegram_client.edit_message_text(chat_id, message_id, "❌ Nebel-Steuerung nicht initialisiert.")

    elif data == "nebel_cancel":
        _state_del(manual_states, chat_id)
        telegram_client.answer_callback_query(cb_id, "Abgebrochen")
        telegram_client.send_message(chat_id, "❌ Vorgang abgebrochen.", get_main_keyboard())

    # --- Stopp: gezielte Auswahl (Feature 0031) ---
    elif data == "stop_valve_all":
        telegram_client.answer_callback_query(cb_id, "Alles wird gestoppt")
        if _watering_ctrl:
            _watering_ctrl.stop_watering()
            for name in _watering_ctrl.get_unexpected_open_valves():
                _watering_ctrl.force_close(name)
        if _nebel_ctrl:
            _nebel_ctrl.stop()
        telegram_client.edit_message_text(chat_id, message_id, "🛑 *Alles gestoppt* (Güsse, extern offene Ventile und Nebel).")

    elif data.startswith("stop_nebel_"):
        name = data[len("stop_nebel_"):]
        telegram_client.answer_callback_query(cb_id, "Nebel wird gestoppt")
        if _nebel_ctrl:
            _nebel_ctrl.stop(name)
        valve = database.get_valve_by_mqtt_name(name)
        label = valve["wish_name"] if valve else name
        telegram_client.edit_message_text(chat_id, message_id, f"🛑 *Nebel gestoppt:* {label}")

    elif data.startswith("stop_extern_"):
        name = data[len("stop_extern_"):]
        telegram_client.answer_callback_query(cb_id, "Ventil wird geschlossen")
        if _watering_ctrl:
            _watering_ctrl.force_close(name)
        valve = database.get_valve_by_mqtt_name(name)
        label = valve["wish_name"] if valve else name
        telegram_client.edit_message_text(chat_id, message_id, f"🛑 *Ventil geschlossen:* {label} (extern geöffnet)")

    elif data.startswith("stop_valve_"):
        name = data[len("stop_valve_"):]
        telegram_client.answer_callback_query(cb_id, "Guss wird gestoppt")
        if _watering_ctrl:
            _watering_ctrl.stop_watering(name)
        valve = database.get_valve_by_mqtt_name(name)
        label = valve["wish_name"] if valve else name
        telegram_client.edit_message_text(chat_id, message_id, f"🛑 *Guss gestoppt:* {label}")

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
                f"🗑️ *Zeitplan löschen*\n\nMöchtest du den Zeitplan *'{_md_escape(target['name'])}'* wirklich löschen?\n\nDiese Aktion kann nicht rückgängig gemacht werden.",
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

    elif data.startswith("photoclear_confirm_"):
        wish_name = data[len("photoclear_confirm_"):]
        telegram_client.answer_callback_query(cb_id, "Lösche Bild-Historie...")
        from .. import scheduler
        deleted = scheduler.clear_camera_history(wish_name)
        telegram_client.send_message(
            chat_id,
            f"🗑️ Bild-Historie der Kamera *'{wish_name}'* gelöscht — *{deleted}* Bilder entfernt.",
            get_main_keyboard()
        )

    elif data.startswith("photoclear_"):
        wish_name = data[len("photoclear_"):]
        telegram_client.answer_callback_query(cb_id)
        _ask_photo_clear_confirmation(chat_id, wish_name)

    elif data == "phtadd_start":
        telegram_client.answer_callback_query(cb_id)
        telegram_client.send_message(
            chat_id,
            "📷 *Foto-Uhrzeit hinzufügen*\n\nZu welcher *Stunde* soll die Kamera aufnehmen?",
            _get_photo_time_hour_keyboard()
        )

    elif data.startswith("phtadd_h_"):
        hour = int(data[len("phtadd_h_"):])
        _phtadd_states[chat_id] = {"hour": hour}
        telegram_client.answer_callback_query(cb_id, f"Stunde: {hour:02d}")
        telegram_client.send_message(
            chat_id,
            f"📷 *Foto-Uhrzeit hinzufügen*\n\nStunde: *{hour:02d}* — Wähle jetzt die *Minute*:",
            _get_photo_time_minute_keyboard()
        )

    elif data.startswith("phtadd_m_"):
        state = _phtadd_states.pop(chat_id, None)
        if state is None:
            telegram_client.answer_callback_query(cb_id, "Sitzung abgelaufen.", show_alert=True)
        else:
            minute = int(data[len("phtadd_m_"):])
            hour = state["hour"]
            time_str = f"{hour:02d}:{minute:02d}"
            database.add_photo_time(time_str)
            telegram_client.answer_callback_query(cb_id, f"✅ {time_str} gespeichert")
            telegram_client.send_message(
                chat_id,
                f"✅ Foto-Uhrzeit *{time_str}* gespeichert.",
                get_main_keyboard()
            )

    elif data.startswith("phtime_del_ask_"):
        photo_time_id = int(data[len("phtime_del_ask_"):])
        telegram_client.answer_callback_query(cb_id)
        times = database.get_photo_times()
        entry = next((t for t in times if t["id"] == photo_time_id), None)
        label = entry["time"] if entry else f"#{photo_time_id}"
        telegram_client.send_message(
            chat_id,
            f"🗑️ Foto-Uhrzeit *{label}* wirklich löschen?",
            {"inline_keyboard": [[
                {"text": "✅ Ja, löschen", "callback_data": f"phtime_del_confirm_{photo_time_id}"},
                {"text": "❌ Abbrechen", "callback_data": "cancel"}
            ]]}
        )

    elif data.startswith("phtime_del_confirm_"):
        photo_time_id = int(data[len("phtime_del_confirm_"):])
        database.delete_photo_time(photo_time_id)
        telegram_client.answer_callback_query(cb_id, "Gelöscht.")
        telegram_client.send_message(chat_id, "✅ Foto-Uhrzeit gelöscht.", get_main_keyboard())

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
            valve_name = _schedule_valve_name(sched_id)
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"*✏️ Zeitplan bearbeiten — \"{_md_escape(schedule['name'])}\"*\n\n"
                f"• Zeit: {schedule['time']} Uhr\n"
                f"• Tage: {days_str}\n"
                f"• Dauer: {schedule['duration_minutes']} Min\n"
                f"• Menge: {'∞' if vol == 0 else str(vol) + ' L'}\n"
                f"• Ventil: {_md_escape(valve_name)}\n\n"
                "Was möchtest du ändern?",
                {"inline_keyboard": [
                    [{"text": "⏰ Zeit",   "callback_data": f"sched_editfield_time_{sched_id}"},
                     {"text": "📅 Tage",  "callback_data": f"sched_editfield_days_{sched_id}"}],
                    [{"text": "⏳ Dauer",  "callback_data": f"sched_editfield_duration_{sched_id}"},
                     {"text": "💧 Menge", "callback_data": f"sched_editfield_volume_{sched_id}"}],
                    [{"text": "✏️ Name",  "callback_data": f"sched_editfield_name_{sched_id}"},
                     {"text": "🚰 Ventil", "callback_data": f"sched_editfield_valve_{sched_id}"}],
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
                f"*✏️ Dauer — \"{_md_escape(schedule['name'])}\"*\n\nAktuell: *{schedule['duration_minutes']} Min*\n\nNeue Dauer wählen:",
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
                f"*✏️ Menge — \"{_md_escape(schedule['name'])}\"*\n\nAktuell: *{'∞ (kein Limit)' if cur_vol == 0 else str(cur_vol) + ' L'}*\n\nNeue Menge wählen:",
                {"inline_keyboard": rows}
            )

        elif field == "valve":
            valves = database.get_all_valves()
            current_ids = database.get_schedule_valves(sched_id)
            cur = current_ids[0] if current_ids else None
            rows = [[{"text": ("✅ " if v["id"] == cur else "🚰 ") + _md_escape(v["wish_name"]),
                      "callback_data": f"sched_setvalve_{sched_id}_{v['id']}"}] for v in valves]
            rows.append([{"text": "❌ Abbrechen", "callback_data": "sched_edit_cancel"}])
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"*✏️ Ventil — \"{_md_escape(schedule['name'])}\"*\n\nAktuell: *{_md_escape(_schedule_valve_name(sched_id))}*\n\nWelches Ventil soll dieser Zeitplan steuern?",
                {"inline_keyboard": rows}
            )

        elif field == "time":
            rows = []
            for i in range(0, 24, 6):
                rows.append([{"text": f"{h:02d}", "callback_data": f"sched_edithour_{sched_id}_{h}"} for h in range(i, i + 6)])
            rows.append([{"text": "❌ Abbrechen", "callback_data": "sched_edit_cancel"}])
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"*✏️ Zeit — \"{_md_escape(schedule['name'])}\"*\n\nAktuell: *{schedule['time']} Uhr*\n\nNeue Stunde wählen:",
                {"inline_keyboard": rows}
            )

        elif field == "name":
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"*✏️ Name — \"{_md_escape(schedule['name'])}\"*\n\nAktuell: *{_md_escape(schedule['name'])}*\n\nNeuen Namen eingeben:",
                {"inline_keyboard": [[{"text": "❌ Abbrechen", "callback_data": "sched_edit_cancel"}]]}
            )

        elif field == "days":
            current_days = schedule["days"].split(",") if schedule["days"] else []
            _state_set(edit_states, chat_id, {"sched_id": sched_id, "field": "days", "edit_days": list(current_days)})
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"*✏️ Tage — \"{_md_escape(schedule['name'])}\"*\n\nWochentage wählen:",
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

    elif data.startswith("sched_setvalve_"):
        parts = data.split("_")
        sched_id, valve_id = int(parts[2]), int(parts[3])
        valve = database.get_valve_by_id(valve_id)
        if valve is None:
            telegram_client.answer_callback_query(cb_id, "Ventil nicht mehr vorhanden.", show_alert=True)
            return
        database.set_schedule_valves(sched_id, [valve_id])
        telegram_client.answer_callback_query(cb_id, f"Ventil auf {valve['wish_name']} gesetzt.")
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
    elif "Zielmenge" in event.details:
        # Zeitlimit erreicht, bevor das Volumenziel ganz geschafft war — regulärer
        # Abschluss mit Hinweis (kein Notfall).
        msg = (
            f"🏁 *Zeitlimit erreicht*\n"
            f"⏱️ {event.duration_run} Min · 💧 {event.volume_run:.1f} l\n"
            f"ℹ️ Zielmenge nicht ganz geschafft."
        )
    else:
        msg = (
            f"🏁 *Zeitlimit erreicht*\n"
            f"⏱️ {event.duration_run} Min · 💧 {event.volume_run:.1f} l"
        )
    telegram_client.broadcast_notification(msg)

def _on_watering_failed(event: WateringCycleFailed):
    # Reserviert für echte Guss-Fehler (Hardware-/MQTT-Störung). Das normale Erreichen
    # des Zeitlimits ist KEIN Fehler mehr — das meldet WateringCycleCompleted.
    msg = (
        f"⚠️ *Guss fehlgeschlagen*\n"
        f"Abbruch nach {event.duration_run} Min · 💧 {event.volume_run:.1f} l geflossen."
    )
    telegram_client.broadcast_notification(msg)

def _on_watering_stopped(event: WateringCycleStopped):
    msg = (
        f"🛑 *Guss gestoppt*\n"
        f"⏱️ Laufzeit: ca. {event.duration_run} Min · 💧 {event.volume_run:.1f} l"
    )
    telegram_client.broadcast_notification(msg)

def _on_nebel_interval_started(event: NebelIntervalStarted):
    wish = _md_escape(_resolve_valve_wish_name(event.mqtt_name))
    end_str = ""
    try:
        end_str = datetime.fromisoformat(event.end_time).strftime("%H:%M")
    except (ValueError, TypeError):
        pass
    quelle = "Sofort" if event.source == "nebel_manual" else "Zeitplan"
    bis = f" bis {end_str} Uhr" if end_str else ""
    telegram_client.broadcast_notification(
        f"🌫️ *Nebel-Intervall gestartet*\n"
        f"„{wish}“ kühlt{bis}.\n"
        f"Quelle: {quelle}"
    )

def _on_nebel_interval_ended(event: NebelIntervalEnded):
    wish = _md_escape(_resolve_valve_wish_name(event.mqtt_name))
    telegram_client.broadcast_notification(
        f"🌫️ *Nebel-Intervall beendet*\n"
        f"„{wish}“: {event.burst_count} Nebelstöße in ca. {event.duration_run} Min."
    )

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
        f"Zeitplan '{_md_escape(event.schedule_name)}' übersprungen -- {event.details}"
    )

def _on_schedule_failed(event: ScheduleFailed):
    telegram_client.broadcast_notification(f"⚠️ *Fehler bei Zeitplan '{_md_escape(event.schedule_name)}'!*\n{event.details}")

def _on_watering_scaled(event: WateringScaled):
    pct = int(round(event.factor * 100))
    has_volume = event.volume_original > 0
    scaled = f"{event.duration_scaled} min" + (f" / {event.volume_scaled} L" if has_volume else "")
    original = f"{event.duration_original} min" + (f" / {event.volume_original} L" if has_volume else "")
    msg = f"💧 *Guss reduziert ({pct} %)*\nZeitplan '{_md_escape(event.schedule_name)}': {scaled} (statt {original})."
    if event.reasons:
        msg += f"\n{event.reasons[0]}"
    telegram_client.broadcast_notification(msg)

def _on_watering_rain_warning(event: WateringRainWarning):
    """Guss-Vorwarnung (Feature 0034): ~5 Min vor einem geplanten Guss, den der Regen
    überspringen oder reduzieren würde — mit Möglichkeit zur Regen-Übersteuerung."""
    name = _md_escape(event.schedule_name)
    valves = ", ".join(_md_escape(v) for v in event.valve_names)
    has_volume = event.volume_original > 0
    menge_orig = f" / {event.volume_original} L" if has_volume else ""
    pct = int(round(event.factor * 100))
    if event.factor <= 0:
        anpassung = "→ *Komplett übersprungen* (kein Guss)"
    else:
        menge_scaled = f" / {event.volume_scaled} L" if has_volume else ""
        anpassung = f"→ *Reduziert auf {event.duration_scaled} Min{menge_scaled}* ({pct} %)"
    begruendung = f"\n{event.reasons[0]}" if event.reasons else ""
    msg = (
        f"🌧 *Regen voraus — Guss in {config.RAIN_WARNING_LEAD_MINUTES} Min betroffen*\n"
        f"Zeitplan „{name}“ um {event.time} ({valves}) würde regenbedingt angepasst.\n"
        f"Geplant: {event.duration_original} Min{menge_orig}\n"
        f"{anpassung}{begruendung}\n\n"
        f"Soll trotzdem voll gegossen werden?"
    )
    markup = {"inline_keyboard": [[
        {"text": "🚿 Regen ignorieren",
         "callback_data": f"rainoverride_{event.schedule_id}_{event.run_date}"}
    ]]}
    telegram_client.broadcast_notification(msg, reply_markup=markup)

def _on_inactivity_alert(event: InactivityAlertTriggered):
    msg = (
        f"⚠️ *Verbindung verloren:* Ventil \"{_md_escape(event.device_name)}\" "
        f"hat seit {event.hours_silent:.1f} Stunden kein Signal gesendet."
    )
    telegram_client.broadcast_notification(msg)

def _on_inactivity_resolved(event: InactivityAlertResolved):
    msg = f"🟢 *Verbindung wiederhergestellt:* Ventil \"{_md_escape(event.device_name)}\" sendet wieder Signale."
    telegram_client.broadcast_notification(msg)

def _on_camera_inactivity_alert(event: CameraInactivityAlertTriggered):
    msg = (
        f"⚠️ *Kamera-Verbindung verloren:* Kamera \"{_md_escape(event.wish_name)}\" "
        f"hat seit {event.seconds_silent / 3600:.1f} Stunden kein Bild gesendet."
    )
    telegram_client.broadcast_notification(msg)

def _on_camera_inactivity_resolved(event: CameraInactivityAlertResolved):
    msg = f"🟢 *Kamera-Verbindung wiederhergestellt:* Kamera \"{_md_escape(event.wish_name)}\" sendet wieder Bilder."
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

def _resolve_wish_name(mqtt_name, fallback=None):
    """Löst den Wunschnamen eines Ventils aus der DB auf; Fallback bei unbekanntem Ventil."""
    valve = database.get_valve_by_mqtt_name(mqtt_name) if mqtt_name else None
    if valve:
        return valve["wish_name"]
    return fallback if fallback is not None else mqtt_name

def _on_watering_interrupted(event: WateringCycleInterrupted):
    valve_name = _resolve_wish_name(event.mqtt_name, "Ventil")
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

def _on_unexpected_valve_opened(event: UnexpectedValveOpened):
    wish_name = _md_escape(_resolve_wish_name(event.mqtt_name))
    safety_min = config.get_setting("SAFETY_TIMEOUT_MINUTES", 30)
    telegram_client.broadcast_notification(
        f"⚠️ *Ventil von außen geöffnet*\n"
        f"„{wish_name}“ wurde ohne aktiven Guss geöffnet.\n"
        f"Warst das nicht du, prüf die Leitung — das Hardware-Sicherheits-Timeout "
        f"schließt spätestens nach {safety_min} Min."
    )

def _on_unexpected_valve_resolved(event: UnexpectedValveResolved):
    wish_name = _md_escape(_resolve_wish_name(event.mqtt_name))
    telegram_client.broadcast_notification(
        f"✅ *Ventil wieder geschlossen*\n„{wish_name}“ ist wieder zu."
    )

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
    _global_bus.subscribe(WateringRainWarning, _on_watering_rain_warning)
    _global_bus.subscribe(ScheduleFailed, _on_schedule_failed)
    _global_bus.subscribe(InactivityAlertTriggered, _on_inactivity_alert)
    _global_bus.subscribe(InactivityAlertResolved, _on_inactivity_resolved)
    _global_bus.subscribe(CameraInactivityAlertTriggered, _on_camera_inactivity_alert)
    _global_bus.subscribe(CameraInactivityAlertResolved, _on_camera_inactivity_resolved)
    _global_bus.subscribe(RainSensorMeasured, _on_rain_sensor_measured)
    _global_bus.subscribe(WateringCycleInterrupted, _on_watering_interrupted)
    _global_bus.subscribe(RainSensorInactivityAlertTriggered, _on_rain_sensor_inactivity_alert)
    _global_bus.subscribe(RainSensorInactivityAlertResolved, _on_rain_sensor_inactivity_resolved)
    _global_bus.subscribe(UnexpectedValveOpened, _on_unexpected_valve_opened)
    _global_bus.subscribe(UnexpectedValveResolved, _on_unexpected_valve_resolved)
    _global_bus.subscribe(TimedPhotoCaptured, _on_timed_photo_captured)
    _global_bus.subscribe(NebelIntervalStarted, _on_nebel_interval_started)
    _global_bus.subscribe(NebelIntervalEnded, _on_nebel_interval_ended)
