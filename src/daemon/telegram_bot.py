import json
import logging
import urllib.request
import urllib.error
import threading
import time
from datetime import datetime
from . import config, database, scheduler, weather

logger = logging.getLogger("garden_telegram")

# Liste der Chat-IDs, die sich erfolgreich authentifiziert haben, um Push-Benachrichtigungen zu erhalten
active_chats = set()

def send_message(chat_id: int, text: str, reply_markup: dict = None) -> bool:
    """Sendet eine Textnachricht (mit optionaler Tastatur) über die Telegram-API."""
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram Bot Token nicht konfiguriert. Nachricht wird nicht gesendet.")
        return False
        
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
        
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status == 200
    except Exception as e:
        logger.error(f"Fehler beim Senden der Telegram-Nachricht an {chat_id}: {e}")
        return False

def answer_callback_query(callback_query_id: str, text: str = None, show_alert: bool = False):
    """Quittiert einen Inline-Button-Klick in Telegram, damit das 'Sanduhr'-Laden verschwindet."""
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    payload = {
        "callback_query_id": callback_query_id
    }
    if text:
        payload["text"] = text
    if show_alert:
        payload["show_alert"] = True
        
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as e:
        logger.error(f"Fehler beim Quittieren der Callback-Query: {e}")

def broadcast_notification(message: str):
    """Sendet eine Push-Meldung an alle bekannten autorisierten Benutzer."""
    # Füge standardmäßig die erlaubten User-IDs zu den aktiven Chats hinzu
    for user_id in config.TELEGRAM_ALLOWED_USER_IDS:
        active_chats.add(user_id)
        
    for chat_id in active_chats:
        send_message(chat_id, message)

# --- Hauptmenüs (Tastaturen) ---

def get_main_keyboard() -> dict:
    """Erstellt die permanente Haupttastatur unten im Chat."""
    return {
        "keyboard": [
            [{"text": "📊 Status anzeigen"}, {"text": "📅 Zeitpläne"}],
            [{"text": "🟢 Bewässern starten"}, {"text": "🔴 Sofort Stopp"}]
        ],
        "resize_keyboard": True
    }

# Zustandsbasierter Zeitplan-Assistent (Wizard) und manuelle Bewässerung
wizard_states = {}  # { chat_id: { "step": int/str, "name": str, "hour": int, "minute": int, "duration": int, "volume": int, "days": list } }
manual_states = {}  # { chat_id: { "step": int/str, "duration": int, "volume": int } }

def edit_message_text(chat_id: int, message_id: int, text: str, reply_markup: dict = None) -> bool:
    """Editiert den Text einer bestehenden Nachricht."""
    if not config.TELEGRAM_BOT_TOKEN:
        return False
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status == 200
    except Exception as e:
        logger.error(f"Fehler beim Editieren der Nachricht {message_id} für {chat_id}: {e}")
        return False

def get_schedules_keyboard() -> dict:
    """Erstellt ein Inline-Keyboard zum Starten des geführten Zeitplan-Assistenten."""
    return {
        "inline_keyboard": [
            [{"text": "➕ Neuer Zeitplan", "callback_data": "wiz_start"}]
        ]
    }

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
        "Mon": "Mo",
        "Tue": "Di",
        "Wed": "Mi",
        "Thu": "Do",
        "Fri": "Fr",
        "Sat": "Sa",
        "Sun": "So"
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

def _get_wmo_description(code: int) -> str:
    """Übersetzt den WMO-Wettercode in eine deutsche qualitative Beschreibung mit passendem Emoji."""
    mapping = {
        0: "☀️ Sonnig / Klar",
        1: "🌤️ Leicht bewölkt",
        2: "⛅ Teilweise bewölkt",
        3: "☁️ Bedeckt / Bewölkt",
        45: "🌫️ Nebelig",
        48: "🌫️ Raureifnebel",
        51: "🌧️ Leichter Nieselregen",
        53: "🌧️ Mäßiger Nieselregen",
        55: "🌧️ Starker Nieselregen",
        61: "🌧️ Leichter Regen",
        63: "🌧️ Mäßiger Regen",
        65: "🌧️ Starker Regen",
        80: "🌧️ Leichte Regenschauer",
        81: "🌧️ Mäßige Regenschauer",
        82: "🌧️ Starke Regenschauer",
        95: "⚡ Gewitter"
    }
    return mapping.get(code, "🌡️ Unbekannt")

# --- Befehlsverarbeitung ---

def handle_status(chat_id: int):
    """Erstellt und sendet die Statusübersicht."""
    # 1. Ventil-Status
    from . import mqtt_client
    status = mqtt_client.get_valve_status()
    
    state_icon = "🟢 OFFEN" if status["state"] == "ON" else "🔴 GESCHLOSSEN"
    battery_icon = "🔋" if status["battery"] > 20 else "🪫"
    
    # 2. Verbindungsstatus ermitteln
    if not mqtt_client.HAS_PAHO:
        broker_status = "⚡ Simulationsmodus (Lokaler Test)"
    else:
        broker_status = "🟢 Aktiv (Verbunden)" if mqtt_client.is_broker_connected() else "🔴 Inaktiv (Kein Dongle / Keine Verbindung)"
        if status["last_update"] is None:
            valve_connected = "🔴 Nicht gekoppelt / Offline"
            warning_text = "⚠️ **Achtung:** Ventil hat nie ein Signal gesendet."
        else:
            warning_text = ""
            try:
                last_up = datetime.fromisoformat(status["last_update"])
                time_str = last_up.strftime("%d.%m. %H:%M:%S Uhr")
                valve_connected = f"🟢 Gekoppelt (Letztes Signal: {time_str})"
                # Check for 5‑minute timeout
                if (datetime.now() - last_up).total_seconds() > 300:
                    warning_text = "⚠️ **Achtung:** Ventil seit über 5 Minuten kein Signal mehr."
            except Exception:
                valve_connected = "🟢 Gekoppelt / Aktiv"
                warning_text = ""
            
    # 3. Aktive Bewässerung
    active = scheduler.get_active_cycle()
    active_text = ""
    if active:
        active_text = (
            f"\n⚡ **Laufender Zyklus:**\n"
            f"   - Gestartet: {active['source'].upper()}\n"
            f"   - Restzeit: {int(active['remaining_seconds']/60)} Min ({active['remaining_seconds'] % 60} Sek)\n"
        )
        
    # 4. Wetterdaten
    last_weather = database.get_last_weather()
    weather_text = "   - Keine Daten vorhanden"
    if last_weather:
        try:
            timestamp_dt = datetime.fromisoformat(last_weather["timestamp"])
            time_str = timestamp_dt.strftime("%H:%M Uhr")
        except Exception:
            time_str = "Unbekannt"
            
        temp = last_weather.get("current_temp", 0.0)
        code = last_weather.get("weather_code", 0)
        desc = _get_wmo_description(code)
        
        weather_text = (
            f"   - **Aktuell:** {temp} °C | {desc}\n"
            f"   - **Stand:** {time_str}\n"
            f"   - **Regen letzte 24h:** {last_weather['rain_last_24h_mm']} mm\n"
            f"   - **Erwartet nächste 24h:** {last_weather['rain_next_24h_mm']} mm"
        )
        
    # 5. Historie
    history = database.get_recent_history(3)
    history_lines = []
    for h in history:
        time_obj = datetime.fromisoformat(h['timestamp'])
        time_str = time_obj.strftime("%d.%m. %H:%M")
        status_char = "✅" if h['status'] == "completed" else "🌤️" if h['status'] == "skipped" else "❌"
        history_lines.append(f"{status_char} {time_str} ({h['duration_minutes']} Min, {h['source']})")
    history_text = "\n".join(history_lines) if history_lines else "Keine Einträge vorhanden"
    
    msg = (
        f"📊 **System-Status Gartenbewässerung**\n\n"
        f"🔌 **MQTT-Broker:** {broker_status}\n"
        f"📶 **Ventil-Verbindung:** {valve_connected}\n"
        f"{warning_text}\n"
        f"\n"
        f"💧 **Ventil-Zustand:** {state_icon}\n"
        f"{battery_icon} **Batterie:** {status['battery']}%\n"
        f"📡 **Signalqualität:** {status['linkquality']} LQI\n"
        f"{active_text}\n"
        f"🌤️ **Wetter:**\n"
        f"{weather_text}\n\n"
        f"📜 **Letzte Zyklen:**\n{history_text}"
    )
    
    send_message(chat_id, msg, get_main_keyboard())

def handle_schedules(chat_id: int):
    """Listet alle aktiven Zeitpläne auf."""
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
        send_message(chat_id, msg, get_schedules_keyboard())
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
            f"   - Löschen: `/delete {s['id']}` | Umschalten: `/toggle {s['id']}`\n"
        )
        
    msg = "📅 **Aktuelle Zeitsteuerung (Zeitpläne):**\n\n" + "\n".join(lines)
    send_message(chat_id, msg, get_schedules_keyboard())

def handle_add_schedule(chat_id: int, text: str):
    """Fügt einen Zeitplan hinzu. Syntax: /add Name, Uhrzeit, Tage, Dauer, [Menge_Liter]"""
    try:
        # Extrahiere Argumente nach /add
        args = text.split(" ", 1)[1]
        parts = [p.strip() for p in args.split(",")]
        
        if len(parts) < 4:
            raise ValueError
            
        name, time_str, days, duration_raw = parts[:4]
        duration = int(duration_raw)
        volume = int(parts[4]) if len(parts) > 4 else 0
        
        # Validierung der Uhrzeit
        datetime.strptime(time_str, "%H:%M")
        
        db_id = database.add_schedule(name, time_str, days, duration, volume)
        if db_id > 0:
            send_message(chat_id, f"📅 Zeitplan **'{name}'** erfolgreich mit ID {db_id} angelegt!")
            handle_schedules(chat_id)
        else:
            send_message(chat_id, "❌ Fehler beim Speichern des Zeitplans in der Datenbank.")
    except Exception:
        send_message(
            chat_id,
            "❌ **Ungültiges Format.**\n\n"
            "Nutzen Sie folgendes Format:\n"
            "`/add Name, HH:MM, Tage, Dauer, [Menge_Liter]` (z.B. `/add Abend, 20:00, Mon,Wed,Fri, 12, 30`)\n\n"
            "Tage: `everyday` oder kommagetrennt: `Mon,Tue,Wed,Thu,Fri,Sat,Sun`."
        )

def handle_delete_schedule(chat_id: int, text: str):
    """Löscht einen Zeitplan über ID."""
    try:
        sched_id = int(text.split(" ")[1])
        if database.delete_schedule(sched_id):
            send_message(chat_id, f"🗑️ Zeitplan ID {sched_id} erfolgreich gelöscht.")
            handle_schedules(chat_id)
        else:
            send_message(chat_id, f"❌ Zeitplan ID {sched_id} nicht gefunden.")
    except Exception:
        send_message(chat_id, "❌ **Ungültiges Format.** Nutzen Sie: `/delete <ID>` (z.B. `/delete 2`)")

def handle_toggle_schedule(chat_id: int, text: str):
    """Schaltet einen Zeitplan aktiv/inaktiv."""
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
            send_message(chat_id, f"📅 Zeitplan **'{target['name']}'** wurde {status_text}.")
            handle_schedules(chat_id)
        else:
            send_message(chat_id, f"❌ Zeitplan ID {sched_id} nicht gefunden.")
    except Exception:
        send_message(chat_id, "❌ **Ungültiges Format.** Nutzen Sie: `/toggle <ID>` (z.B. `/toggle 1`)")

# --- Polling Schleife (Hintergrund-Thread) ---

def _process_message(msg_obj: dict):
    """Verarbeitet eine autorisierte Chat-Nachricht."""
    chat_id = msg_obj["chat"]["id"]
    text = msg_obj.get("text", "").strip()
    
    # Push-Verbindung merken
    active_chats.add(chat_id)
    
    # --- Intercept messages for Wizards if they are active ---
    if chat_id in wizard_states:
        state = wizard_states[chat_id]
        step = state.get("step")
        
        # Check if the user wants to cancel using a command or menu option
        if text.startswith("/") or text in ["📊 Status anzeigen", "📅 Zeitsteuerung", "📅 Zeitpläne", "🟢 Bewässern starten", "🔴 Sofort Stopp"]:
            del wizard_states[chat_id]
            # fall through to process command normally
        else:
            if step == 1:
                # Name entered
                if not text:
                    send_message(chat_id, "❌ Der Name darf nicht leer sein. Bitte gib einen Namen ein:")
                    return
                state["name"] = text
                state["step"] = 2
                send_message(
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
                    send_message(
                        chat_id,
                        f"🆕 **Neuen Zeitplan '{state['name']}' (Schritt 5/6)**\n\nWie viel Wasser soll **maximal** fließen? (Volumenlimit)",
                        get_volume_wizard_keyboard("wiz")
                    )
                except ValueError:
                    send_message(chat_id, "❌ **Ungültige Eingabe.** Bitte gib eine Zahl zwischen 1 und 25 Minuten ein:")
                return
            elif step == "custom_volume":
                try:
                    vol = int(text)
                    if vol <= 0:
                        raise ValueError
                    state["volume"] = vol
                    state["step"] = 6
                    state["days"] = []
                    send_message(
                        chat_id,
                        f"🆕 **Neuen Zeitplan '{state['name']}' (Schritt 6/6)**\n\nWähle die **Wochentage** aus, an denen bewässert werden soll:\n\n*Ausgewählt: Keine*",
                        get_days_wizard_keyboard([])
                    )
                except ValueError:
                    send_message(chat_id, "❌ **Ungültige Eingabe.** Bitte gib eine Zahl größer als 0 Liter ein:")
                return
            
    if chat_id in manual_states:
        state = manual_states[chat_id]
        step = state.get("step")
        
        # Check if the user wants to cancel using a command or menu option
        if text.startswith("/") or text in ["📊 Status anzeigen", "📅 Zeitsteuerung", "📅 Zeitpläne", "🟢 Bewässern starten", "🔴 Sofort Stopp"]:
            del manual_states[chat_id]
            # fall through to process command normally
        else:
            if step == "man_custom_duration":
                try:
                    dur = int(text)
                    if not (1 <= dur <= 25):
                        raise ValueError
                    state["duration"] = dur
                    state["step"] = 2
                    send_message(
                        chat_id,
                        "🟢 **Manuelle Bewässerung starten (Schritt 2/2)**\n\nWie viel Wasser soll **maximal** fließen? (Volumenlimit)",
                        get_volume_wizard_keyboard("man")
                    )
                except ValueError:
                    send_message(chat_id, "❌ **Ungültige Eingabe.** Bitte gib eine Zahl zwischen 1 und 25 Minuten ein:")
                return
            elif step == "man_custom_volume":
                try:
                    vol = int(text)
                    if vol <= 0:
                        raise ValueError
                    state["volume"] = vol
                    dur = state["duration"]
                    del manual_states[chat_id]
                    
                    success, response = scheduler.start_watering(dur, vol, "manual")
                    if not success:
                        send_message(chat_id, f"❌ Fehler beim Starten: {response}", get_main_keyboard())
                except ValueError:
                    send_message(chat_id, "❌ **Ungültige Eingabe.** Bitte gib eine Zahl größer als 0 Liter ein:")
                return
                
    if text.startswith("/start"):
        send_message(
            chat_id,
            "👋 **Willkommen bei der Gartenbewässerung-Steuerung!**\n\n"
            "Ich bin Ihr lokaler Assistent. Nutzen Sie die Buttons unten oder "
            "die Chat-Befehle `/status` und `/zeitplan`, um Ihr System zu steuern.",
            get_main_keyboard()
        )
    elif text == "📊 Status anzeigen" or text.startswith("/status"):
        handle_status(chat_id)
    elif text == "📅 Zeitsteuerung" or text == "📅 Zeitpläne" or text.startswith("/zeitplan"):
        handle_schedules(chat_id)
    elif text == "🟢 Bewässern starten":
        # Launch manual wizard
        manual_states[chat_id] = {"step": 1}
        send_message(
            chat_id,
            "🟢 **Manuelle Bewässerung starten (Schritt 1/2)**\n\nWie lange soll **maximal** bewässert werden? (Zeitlimit)\n\n*Aus Sicherheitsgründen max. 25 Min.*",
            get_duration_wizard_keyboard("man")
        )
    elif text == "🔴 Sofort Stopp" or text.startswith("/stop"):
        success, response = scheduler.stop_watering()
        if not success:
            send_message(chat_id, f"ℹ️ {response}")
    elif text.startswith("/add"):
        handle_add_schedule(chat_id, text)
    elif text.startswith("/delete"):
        handle_delete_schedule(chat_id, text)
    elif text.startswith("/toggle"):
        handle_toggle_schedule(chat_id, text)
    else:
        send_message(
            chat_id,
            "❓ **Unbekannter Befehl.**\n\n"
            "Verwenden Sie die Buttons oder `/status` für eine Übersicht."
        )

def _process_callback_query(cb_obj: dict):
    """Verarbeitet Klicks auf Inline-Buttons."""
    cb_id = cb_obj["id"]
    chat_id = cb_obj["message"]["chat"]["id"]
    message_id = cb_obj["message"]["message_id"]
    data = cb_obj["data"]
    
    if data == "cancel":
        answer_callback_query(cb_id, "Abgebrochen")
        send_message(chat_id, "❌ Vorgang abgebrochen.", get_main_keyboard())
    elif data.startswith("water_"):
        duration = int(data.split("_")[1])
        answer_callback_query(cb_id, "Starte Bewässerung...")
        success, response = scheduler.start_watering(duration, 0, "manual")
        if not success:
            send_message(chat_id, f"❌ Fehler: {response}", get_main_keyboard())
            
    # --- Assistent (Guided Wizard) Callbacks ---
    elif data == "wiz_start":
        answer_callback_query(cb_id, "Zeitplan-Assistent gestartet")
        wizard_states[chat_id] = {"step": 1}
        send_message(
            chat_id,
            "🆕 **Neuen Zeitplan anlegen (Schritt 1/6)**\n\nBitte gib einen **Namen** für den Zeitplan ein (z. B. *Rasen morgens* oder *Hochbeet*):",
            {"inline_keyboard": [[{"text": "❌ Abbrechen", "callback_data": "wiz_cancel"}]]}
        )
        
    elif data.startswith("wiz_hour_"):
        hour = int(data.split("_")[2])
        if chat_id in wizard_states:
            state = wizard_states[chat_id]
            state["hour"] = hour
            state["step"] = 3
            answer_callback_query(cb_id, f"Stunde: {hour:02d}")
            edit_message_text(
                chat_id, message_id,
                f"🆕 **Neuen Zeitplan '{state['name']}' um {hour:02d}:?? (Schritt 3/6)**\n\nZu welcher **Minute** soll die Bewässerung starten?",
                get_minute_keyboard()
            )
            
    elif data.startswith("wiz_min_"):
        minute = int(data.split("_")[2])
        if chat_id in wizard_states:
            state = wizard_states[chat_id]
            state["minute"] = minute
            state["step"] = 4
            answer_callback_query(cb_id, f"Minute: {minute:02d}")
            edit_message_text(
                chat_id, message_id,
                f"🆕 **Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{minute:02d} (Schritt 4/6)**\n\nWie lange soll **maximal** bewässert werden? (Zeitlimit)\n\n*Aus Sicherheitsgründen max. 25 Min.*",
                get_duration_wizard_keyboard("wiz")
            )
            
    elif data.startswith("wiz_dur_"):
        dur_str = data.split("_")[2]
        if chat_id in wizard_states:
            state = wizard_states[chat_id]
            answer_callback_query(cb_id)
            if dur_str == "custom":
                state["step"] = "custom_duration"
                edit_message_text(
                    chat_id, message_id,
                    f"🆕 **Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{state['minute']:02d} (Schritt 4/6)**\n\nBitte gib die gewünschte Dauer in Minuten über die Tastatur ein (Zahl von 1 bis 25):",
                    {"inline_keyboard": [[{"text": "❌ Abbrechen", "callback_data": "wiz_cancel"}]]}
                )
            else:
                dur = int(dur_str)
                state["duration"] = dur
                state["step"] = 5
                edit_message_text(
                    chat_id, message_id,
                    f"🆕 **Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{state['minute']:02d} (Schritt 5/6)**\n\nWie viel Wasser soll **maximal** fließen? (Volumenlimit)\n\n*Ausgewählte Dauer: {dur} Min.*",
                    get_volume_wizard_keyboard("wiz")
                )
                
    elif data.startswith("wiz_vol_"):
        vol_str = data.split("_")[2]
        if chat_id in wizard_states:
            state = wizard_states[chat_id]
            answer_callback_query(cb_id)
            if vol_str == "custom":
                state["step"] = "custom_volume"
                edit_message_text(
                    chat_id, message_id,
                    f"🆕 **Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{state['minute']:02d} (Schritt 5/6)**\n\nBitte gib die gewünschte Wassermenge in Litern über die Tastatur ein (Zahl > 0):",
                    {"inline_keyboard": [[{"text": "❌ Abbrechen", "callback_data": "wiz_cancel"}]]}
                )
            else:
                vol = int(vol_str)
                state["volume"] = vol
                state["step"] = 6
                state["days"] = []
                edit_message_text(
                    chat_id, message_id,
                    f"🆕 **Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{state['minute']:02d} (Schritt 6/6)**\n\nWähle die **Wochentage** aus, an denen bewässert werden soll:\n\n*Ausgewählt: Keine*",
                    get_days_wizard_keyboard([])
                )
                
    elif data.startswith("wiz_day_"):
        day = data.split("_")[2]
        if chat_id in wizard_states:
            state = wizard_states[chat_id]
            answer_callback_query(cb_id)
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
            days_str = format_days_german(days)
            edit_message_text(
                chat_id, message_id,
                f"🆕 **Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{state['minute']:02d} (Schritt 6/6)**\n\nWähle die **Wochentage** aus, an denen bewässert werden soll:\n\n*Ausgewählt: {days_str}*",
                get_days_wizard_keyboard(days)
            )
            
    elif data == "wiz_save":
        if chat_id in wizard_states:
            state = wizard_states[chat_id]
            days = state.get("days", [])
            if not days:
                answer_callback_query(cb_id, "⚠️ Wähle mind. einen Tag!", show_alert=True)
                return
            
            state["step"] = 7
            answer_callback_query(cb_id)
            days_str = format_days_german(days)
            edit_message_text(
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
        if chat_id in wizard_states:
            state = wizard_states[chat_id]
            answer_callback_query(cb_id, "Zeitplan erfolgreich gespeichert!")
            
            name = state["name"]
            time_str = f"{state['hour']:02d}:{state['minute']:02d}"
            days_str = ",".join(state["days"])
            duration = state["duration"]
            volume = state["volume"]
            
            db_id = database.add_schedule(name, time_str, days_str, duration, volume)
            del wizard_states[chat_id]
            
            if db_id > 0:
                send_message(chat_id, f"📅 Zeitplan **'{name}'** erfolgreich angelegt!", get_main_keyboard())
                handle_schedules(chat_id)
            else:
                send_message(chat_id, "❌ Fehler beim Speichern des Zeitplans in der Datenbank.", get_main_keyboard())
                
    elif data == "wiz_cancel":
        if chat_id in wizard_states:
            del wizard_states[chat_id]
        answer_callback_query(cb_id, "Abgebrochen")
        send_message(chat_id, "❌ Vorgang abgebrochen.", get_main_keyboard())
        
    # --- Manuelle Bewässerung (Guided Manual) Callbacks ---
    elif data.startswith("man_dur_"):
        dur_str = data.split("_")[2]
        answer_callback_query(cb_id)
        if dur_str == "custom":
            manual_states[chat_id] = {"step": "man_custom_duration"}
            edit_message_text(
                chat_id, message_id,
                "🟢 **Manuelle Bewässerung starten (Schritt 1/2)**\n\nBitte gib die gewünschte Dauer in Minuten über die Tastatur ein (Zahl von 1 bis 25):",
                {"inline_keyboard": [[{"text": "❌ Abbrechen", "callback_data": "man_cancel"}]]}
            )
        else:
            dur = int(dur_str)
            manual_states[chat_id] = {"step": 2, "duration": dur}
            edit_message_text(
                chat_id, message_id,
                f"🟢 **Manuelle Bewässerung starten (Schritt 2/2)**\n\nWie viel Wasser soll **maximal** fließen? (Volumenlimit)\n\n*Ausgewählte Dauer: {dur} Min.*",
                get_volume_wizard_keyboard("man")
            )
            
    elif data.startswith("man_vol_"):
        vol_str = data.split("_")[2]
        if chat_id in manual_states:
            state = manual_states[chat_id]
            answer_callback_query(cb_id)
            if vol_str == "custom":
                state["step"] = "man_custom_volume"
                edit_message_text(
                    chat_id, message_id,
                    "🟢 **Manuelle Bewässerung starten (Schritt 2/2)**\n\nBitte gib die gewünschte Wassermenge in Litern über die Tastatur ein (Zahl > 0):",
                    {"inline_keyboard": [[{"text": "❌ Abbrechen", "callback_data": "man_cancel"}]]}
                )
            else:
                vol = int(vol_str)
                dur = state["duration"]
                del manual_states[chat_id]
                
                success, response = scheduler.start_watering(dur, vol, "manual")
                if not success:
                    send_message(chat_id, f"❌ Fehler beim Starten: {response}", get_main_keyboard())
                else:
                    edit_message_text(chat_id, message_id, f"🟢 **Befehl gesendet:** Bewässerung gestartet ({dur} Min / {vol}l).")
                    
    elif data == "man_cancel":
        if chat_id in manual_states:
            del manual_states[chat_id]
        answer_callback_query(cb_id, "Abgebrochen")
        send_message(chat_id, "❌ Vorgang abgebrochen.", get_main_keyboard())
        
    else:
        answer_callback_query(cb_id)

def _polling_loop():
    """Hintergrund-Long-Polling-Schleife zur Abfrage neuer Nachrichten."""
    logger.info("Telegram-Polling gestartet.")
    offset = 0
    
    while True:
        if not config.TELEGRAM_BOT_TOKEN:
            logger.error("Kein Telegram Bot Token konfiguriert. Polling ausgesetzt.")
            time.sleep(10)
            continue
            
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates?offset={offset}&timeout=30"
        
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'GardenIrrigationDaemon/1.0'})
            with urllib.request.urlopen(req, timeout=35) as response:
                result = json.loads(response.read().decode("utf-8"))
                
            if not result.get("ok"):
                logger.error(f"Fehlerantwort von Telegram-API: {result}")
                time.sleep(5)
                continue
                
            updates = result.get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                
                # Prüfe Absender (Security Whitelist)
                msg_obj = update.get("message")
                cb_obj = update.get("callback_query")
                
                sender_id = None
                if msg_obj:
                    sender_id = msg_obj["from"]["id"]
                elif cb_obj:
                    sender_id = cb_obj["from"]["id"]
                    
                if sender_id not in config.TELEGRAM_ALLOWED_USER_IDS:
                    logger.warning(f"Unautorisierter Zugriff von User-ID {sender_id} blockiert!")
                    # Sende unhöflichen Einbrechern keine Nachricht zurück zur Absicherung
                    continue
                    
                # Event verarbeiten
                if msg_obj:
                    _process_message(msg_obj)
                elif cb_obj:
                    _process_callback_query(cb_obj)
                    
        except urllib.error.URLError as e:
            # Häufig bei kurzzeitigen Internetunterbrechungen auf Pi
            logger.debug(f"Verbindungsfehler im Telegram-Polling: {e}")
            time.sleep(5)
        except Exception as e:
            logger.error(f"Unerwarteter Fehler im Telegram-Polling: {e}")
            time.sleep(5)

def start_bot():
    """Initialisiert und startet den Telegram-Bot."""
    # Scheduler mit Push-Benachrichtigung verbinden
    scheduler.register_notification_callback(broadcast_notification)
    
    t = threading.Thread(target=_polling_loop, daemon=True)
    t.start()
    logger.info("Telegram-Bot-Dienst im Hintergrund gestartet.")
