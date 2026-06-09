import json
import logging
from datetime import datetime
from .. import config, scheduler
from ..adapters import database, weather
from . import telegram_client
from ..core.event_bus import EventBus
from ..adapters.mqtt_client import _global_bus
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

logger = logging.getLogger("garden_telegram_ui")

# Zustandsbasierter Zeitplan-Assistent (Wizard) und manuelle Bewässerung
wizard_states = {}  # { chat_id: { "step": int/str, "name": str, ... } }
manual_states = {}  # { chat_id: { "step": int/str, "duration": int, "volume": int } }

# --- Hauptmenüs (Tastaturen) ---

def get_main_keyboard() -> dict:
    """Erstellt die permanente Haupttastatur unten im Chat."""
    from ..adapters import mqtt_client
    valve_paired = mqtt_client.get_valve_status()["last_update"] is not None

    rows = [
        [{"text": "📊 Status anzeigen"}, {"text": "📅 Zeitpläne"}],
        [{"text": "🟢 Bewässern starten"}, {"text": "🔴 Sofort Stopp"}]
    ]
    if not valve_paired:
        rows.append([{"text": "🔧 Ventil koppeln"}])

    return {
        "keyboard": rows,
        "resize_keyboard": True
    }

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

def _get_wmo_description(code: int) -> str:
    mapping = {
        0: "☀️ Sonnig / Klar", 1: "🌤️ Leicht bewölkt", 2: "⛅ Teilweise bewölkt", 3: "☁️ Bedeckt / Bewölkt",
        45: "🌫️ Nebelig", 48: "🌫️ Raureifnebel", 51: "🌧️ Leichter Nieselregen", 53: "🌧️ Mäßiger Nieselregen",
        55: "🌧️ Starker Nieselregen", 56: "🌧️ Leichter gefrierender Nieselregen", 57: "🌧️ Dichter gefrierender Nieselregen",
        61: "🌧️ Leichter Regen", 63: "🌧️ Mäßiger Regen", 65: "🌧️ Starker Regen",
        66: "🌧️ Leichter gefrierender Regen", 67: "🌧️ Starker gefrierender Regen",
        71: "❄️ Leichter Schneefall", 73: "❄️ Mäßiger Schneefall", 75: "❄️ Starker Schneefall",
        77: "❄️ Schneegriesel", 80: "🌧️ Leichte Regenschauer", 81: "🌧️ Mäßige Regenschauer", 82: "🌧️ Starke Regenschauer",
        85: "❄️ Leichte Schneeschauer", 86: "❄️ Starke Schneeschauer", 95: "⚡ Gewitter",
        96: "⚡ Gewitter mit leichtem Hagel", 99: "⚡ Gewitter mit starkem Hagel"
    }
    return mapping.get(code, "🌡️ Unbekannt")

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

def _start_pairing(chat_id: int):
    from ..adapters import pairing
    telegram_client.send_message(
        chat_id,
        "🔧 *Ventil-Kopplung gestartet*\n\n"
        "Bitte drücke jetzt den *Reset-Knopf* am Sonoff Hydro ONE für "
        "*5 Sekunden*, bis die LED schnell blinkt.\n\n"
        "⏱️ Das System wartet bis zu 90 Sekunden auf das Ventil."
    )
    pairing.start_pairing(chat_id, telegram_client.send_message)

def handle_setup(chat_id: int):
    from ..adapters import mqtt_client, pairing

    if pairing.is_pairing_active():
        telegram_client.send_message(
            chat_id,
            "⏳ Eine Ventil-Kopplung läuft bereits im Hintergrund. Bitte warten."
        )
        return

    valve_paired = mqtt_client.get_valve_status()["last_update"] is not None

    if valve_paired:
        telegram_client.send_message(
            chat_id,
            "⚠️ *Ein Ventil ist bereits aktiv.*\n\n"
            "Möchtest du trotzdem eine neue Ventil-Kopplung starten?\n"
            "Das bestehende Ventil wird dabei überschrieben.\n\n"
            "_(Nur sinnvoll bei Gerätetausch)_",
            {
                "inline_keyboard": [[
                    {"text": "❌ Abbrechen",       "callback_data": "setup_cancel"},
                    {"text": "✅ Ja, neu koppeln", "callback_data": "setup_confirm"}
                ]]
            }
        )
        return

    _start_pairing(chat_id)

def handle_status(chat_id: int):
    from ..adapters import mqtt_client
    import time
    
    # Fordere vorab aktuelle Werte vom Ventil an und warte kurz (Option B)
    mqtt_client.request_valve_status()
    time.sleep(1.5)
    
    status = mqtt_client.get_valve_status()
    
    state_icon = "🟢 OFFEN" if status["state"] == "ON" else "🔴 GESCHLOSSEN"
    battery_icon = "🔋" if status["battery"] > 20 else "🪫"
    
    broker_connected = mqtt_client.is_broker_connected()
    bridge_online = mqtt_client.get_bridge_status() == "online"
    
    if not mqtt_client.HAS_PAHO:
        services_status = "⚡ Simulationsmodus (Lokaler Test)"
        if status["last_update"] is None:
            valve_connected = "🔴 Nicht gekoppelt / Offline"
        else:
            valve_connected = "🟢 Gekoppelt / Aktiv"
    else:
        if not broker_connected:
            services_status = "🔴 Inaktiv (MQTT-Broker nicht erreichbar)"
            valve_connected = "🔴 Offline (Dienste gestört)"
        elif not bridge_online:
            services_status = "🔴 Inaktiv (Mittelweg-Dienst offline)"
            valve_connected = "🔴 Offline (Dienste gestört)"
        else:
            services_status = "🟢 Aktiv"
            if status["last_update"] is None:
                valve_connected = "🔴 Nicht gekoppelt / Offline"
            else:
                try:
                    last_up = datetime.fromisoformat(status["last_update"])
                    time_str = last_up.strftime("%d.%m. %H:%M:%S Uhr")
                    valve_connected = f"🟢 Gekoppelt (Letztes Signal: {time_str})"
                except Exception:
                    valve_connected = "🟢 Gekoppelt / Aktiv"
            
    active = scheduler.get_active_cycle()
    active_text = ""
    if active:
        active_text = (
            f"\n⚡ **Laufender Zyklus:**\n"
            f"   - Gestartet: {active['source'].upper()}\n"
            f"   - Restzeit: {int(active['remaining_seconds']/60)} Min ({active['remaining_seconds'] % 60} Sek)\n"
        )
        
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
        
        temp_min = last_weather.get("temp_min")
        temp_max = last_weather.get("temp_max")
        rain_prob = last_weather.get("rain_probability")
        
        if temp_min is None: temp_min = temp - 5.0
        if temp_max is None: temp_max = temp + 5.0
        if rain_prob is None: rain_prob = 0
        
        weather_text = (
            f"   - **Aktuell:** {temp} °C (Min: {temp_min} °C / Max: {temp_max} °C) | {desc}\n"
            f"   - **Regenwahrscheinlichkeit:** {rain_prob}%\n"
            f"   - **Stand:** {time_str}\n"
            f"   - **Regen letzte 24h:** {last_weather['rain_last_24h_mm']} mm\n"
            f"   - **Erwartet nächste 24h:** {last_weather['rain_next_24h_mm']} mm"
        )
        
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
        f"🔌 **System-Dienste:** {services_status}\n"
        f"📶 **Ventil-Verbindung:** {valve_connected}\n\n"
        f"💧 **Ventil-Zustand:** {state_icon}\n"
        f"{battery_icon} **Batterie:** {status['battery']}%\n"
        f"📡 **Signalqualität:** {_get_lqi_description(status['linkquality'])}\n"
        f"{active_text}\n"
        f"🌤️ **Wetter:**\n"
        f"{weather_text}\n\n"
        f"📜 **Letzte Zyklen:**\n{history_text}"
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
            f"   - Löschen: `/delete {s['id']}` | Umschalten: `/toggle {s['id']}`\n"
        )
        
    msg = "📅 **Aktuelle Zeitsteuerung (Zeitpläne):**\n\n" + "\n".join(lines)
    telegram_client.send_message(chat_id, msg, get_schedules_keyboard())

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
    chat_id = msg_obj["chat"]["id"]
    text = msg_obj.get("text", "").strip()
    
    if chat_id in wizard_states:
        state = wizard_states[chat_id]
        step = state.get("step")
        
        if text.startswith("/") or text in ["📊 Status anzeigen", "📅 Zeitsteuerung", "📅 Zeitpläne", "🟢 Bewässern starten", "🔴 Sofort Stopp"]:
            del wizard_states[chat_id]
        else:
            if step == 1:
                if not text:
                    telegram_client.send_message(chat_id, "❌ Der Name darf nicht leer sein. Bitte gib einen Namen ein:")
                    return
                state["name"] = text
                state["step"] = 2
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
                    telegram_client.send_message(
                        chat_id,
                        f"🆕 **Neuen Zeitplan '{state['name']}' (Schritt 6/6)**\n\nWähle die **Wochentage** aus, an denen bewässert werden soll:\n\n*Ausgewählt: Keine*",
                        get_days_wizard_keyboard([])
                    )
                except ValueError:
                    telegram_client.send_message(chat_id, "❌ **Ungültige Eingabe.** Bitte gib eine Zahl größer als 0 Liter ein:")
                return
            
    if chat_id in manual_states:
        state = manual_states[chat_id]
        step = state.get("step")
        
        if text.startswith("/") or text in ["📊 Status anzeigen", "📅 Zeitsteuerung", "📅 Zeitpläne", "🟢 Bewässern starten", "🔴 Sofort Stopp"]:
            del manual_states[chat_id]
        else:
            if step == "man_custom_duration":
                try:
                    dur = int(text)
                    if not (1 <= dur <= 25):
                        raise ValueError
                    state["duration"] = dur
                    state["step"] = 2
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
                    state["volume"] = vol
                    dur = state["duration"]
                    del manual_states[chat_id]
                    
                    success, response = scheduler.start_watering(dur, vol, "manual")
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
        from ..adapters import mqtt_client
        import time
        
        # Vorab aktuelle Werte vom Ventil anfordern und kurz warten
        mqtt_client.request_valve_status()
        time.sleep(1.5)
        
        today_str = datetime.now().strftime("%Y-%m-%d")
        report_text = scheduler.generate_daily_report(today_str)
        telegram_client.send_message(chat_id, report_text, get_main_keyboard())
    elif text == "📅 Zeitsteuerung" or text == "📅 Zeitpläne" or text.startswith("/zeitplan"):
        handle_schedules(chat_id)
    elif text == "🔧 Ventil koppeln" or text.startswith("/setup"):
        handle_setup(chat_id)
    elif text == "🟢 Bewässern starten":
        manual_states[chat_id] = {"step": 1}
        telegram_client.send_message(
            chat_id,
            "🟢 **Manuelle Bewässerung starten (Schritt 1/2)**\n\nWie lange soll **maximal** bewässert werden? (Zeitlimit)\n\n*Aus Sicherheitsgründen max. 25 Min.*",
            get_duration_wizard_keyboard("man")
        )
    elif text == "🔴 Sofort Stopp" or text.startswith("/stop"):
        success, response = scheduler.stop_watering()
        if not success:
            telegram_client.send_message(chat_id, f"ℹ️ {response}")
    elif text.startswith("/add"):
        handle_add_schedule(chat_id, text)
    elif text.startswith("/delete"):
        handle_delete_schedule(chat_id, text)
    elif text.startswith("/toggle"):
        handle_toggle_schedule(chat_id, text)
    else:
        telegram_client.send_message(
            chat_id,
            "❓ **Unbekannter Befehl.**\n\n"
            "Verwenden Sie die Buttons oder `/status` für eine Übersicht."
        )

def _process_callback_query(cb_obj: dict):
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
        success, response = scheduler.start_watering(duration, 0, "manual")
        if not success:
            telegram_client.send_message(chat_id, f"❌ Fehler: {response}", get_main_keyboard())
            
    elif data == "wiz_start":
        telegram_client.answer_callback_query(cb_id, "Zeitplan-Assistent gestartet")
        wizard_states[chat_id] = {"step": 1}
        telegram_client.send_message(
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
            telegram_client.answer_callback_query(cb_id, f"Stunde: {hour:02d}")
            telegram_client.edit_message_text(
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
            telegram_client.answer_callback_query(cb_id, f"Minute: {minute:02d}")
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"🆕 **Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{minute:02d} (Schritt 4/6)**\n\nWie lange soll **maximal** bewässert werden? (Zeitlimit)\n\n*Aus Sicherheitsgründen max. 25 Min.*",
                get_duration_wizard_keyboard("wiz")
            )
            
    elif data.startswith("wiz_dur_"):
        dur_str = data.split("_")[2]
        if chat_id in wizard_states:
            state = wizard_states[chat_id]
            telegram_client.answer_callback_query(cb_id)
            if dur_str == "custom":
                state["step"] = "custom_duration"
                telegram_client.edit_message_text(
                    chat_id, message_id,
                    f"🆕 **Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{state['minute']:02d} (Schritt 4/6)**\n\nBitte gib die gewünschte Dauer in Minuten über die Tastatur ein (Zahl von 1 bis 25):",
                    {"inline_keyboard": [[{"text": "❌ Abbrechen", "callback_data": "wiz_cancel"}]]}
                )
            else:
                dur = int(dur_str)
                state["duration"] = dur
                state["step"] = 5
                telegram_client.edit_message_text(
                    chat_id, message_id,
                    f"🆕 **Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{state['minute']:02d} (Schritt 5/6)**\n\nWie viel Wasser soll **maximal** fließen? (Volumenlimit)\n\n*Ausgewählte Dauer: {dur} Min.*",
                    get_volume_wizard_keyboard("wiz")
                )
                
    elif data.startswith("wiz_vol_"):
        vol_str = data.split("_")[2]
        if chat_id in wizard_states:
            state = wizard_states[chat_id]
            telegram_client.answer_callback_query(cb_id)
            if vol_str == "custom":
                state["step"] = "custom_volume"
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
                telegram_client.edit_message_text(
                    chat_id, message_id,
                    f"🆕 **Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{state['minute']:02d} (Schritt 6/6)**\n\nWähle die **Wochentage** aus, an denen bewässert werden soll:\n\n*Ausgewählt: Keine*",
                    get_days_wizard_keyboard([])
                )
                
    elif data.startswith("wiz_day_"):
        day = data.split("_")[2]
        if chat_id in wizard_states:
            state = wizard_states[chat_id]
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
            days_str = format_days_german(days)
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"🆕 **Neuen Zeitplan '{state['name']}' um {state['hour']:02d}:{state['minute']:02d} (Schritt 6/6)**\n\nWähle die **Wochentage** aus, an denen bewässert werden soll:\n\n*Ausgewählt: {days_str}*",
                get_days_wizard_keyboard(days)
            )
            
    elif data == "wiz_save":
        if chat_id in wizard_states:
            state = wizard_states[chat_id]
            days = state.get("days", [])
            if not days:
                telegram_client.answer_callback_query(cb_id, "⚠️ Wähle mind. einen Tag!", show_alert=True)
                return
            
            state["step"] = 7
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
        if chat_id in wizard_states:
            state = wizard_states[chat_id]
            telegram_client.answer_callback_query(cb_id, "Zeitplan erfolgreich gespeichert!")
            
            name = state["name"]
            time_str = f"{state['hour']:02d}:{state['minute']:02d}"
            days_str = ",".join(state["days"])
            duration = state["duration"]
            volume = state["volume"]
            
            db_id = database.add_schedule(name, time_str, days_str, duration, volume)
            del wizard_states[chat_id]
            
            if db_id > 0:
                telegram_client.send_message(chat_id, f"📅 Zeitplan **'{name}'** erfolgreich angelegt!", get_main_keyboard())
                handle_schedules(chat_id)
            else:
                telegram_client.send_message(chat_id, "❌ Fehler beim Speichern des Zeitplans in der Datenbank.", get_main_keyboard())
                
    elif data == "wiz_cancel":
        if chat_id in wizard_states:
            del wizard_states[chat_id]
        telegram_client.answer_callback_query(cb_id, "Abgebrochen")
        telegram_client.send_message(chat_id, "❌ Vorgang abgebrochen.", get_main_keyboard())
        
    elif data.startswith("man_dur_"):
        dur_str = data.split("_")[2]
        telegram_client.answer_callback_query(cb_id)
        if dur_str == "custom":
            manual_states[chat_id] = {"step": "man_custom_duration"}
            telegram_client.edit_message_text(
                chat_id, message_id,
                "🟢 **Manuelle Bewässerung starten (Schritt 1/2)**\n\nBitte gib die gewünschte Dauer in Minuten über die Tastatur ein (Zahl von 1 bis 25):",
                {"inline_keyboard": [[{"text": "❌ Abbrechen", "callback_data": "man_cancel"}]]}
            )
        else:
            dur = int(dur_str)
            manual_states[chat_id] = {"step": 2, "duration": dur}
            telegram_client.edit_message_text(
                chat_id, message_id,
                f"🟢 **Manuelle Bewässerung starten (Schritt 2/2)**\n\nWie viel Wasser soll **maximal** fließen? (Volumenlimit)\n\n*Ausgewählte Dauer: {dur} Min.*",
                get_volume_wizard_keyboard("man")
            )
            
    elif data.startswith("man_vol_"):
        vol_str = data.split("_")[2]
        if chat_id in manual_states:
            state = manual_states[chat_id]
            telegram_client.answer_callback_query(cb_id)
            if vol_str == "custom":
                state["step"] = "man_custom_volume"
                telegram_client.edit_message_text(
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
                    telegram_client.send_message(chat_id, f"❌ Fehler beim Starten: {response}", get_main_keyboard())
                else:
                    telegram_client.edit_message_text(chat_id, message_id, f"🟢 **Befehl gesendet:** Bewässerung gestartet ({dur} Min / {vol}l).")
                    
    elif data == "man_cancel":
        if chat_id in manual_states:
            del manual_states[chat_id]
        telegram_client.answer_callback_query(cb_id, "Abgebrochen")
        telegram_client.send_message(chat_id, "❌ Vorgang abgebrochen.", get_main_keyboard())

    elif data == "setup_confirm":
        telegram_client.answer_callback_query(cb_id, "Ventil-Kopplung wird gestartet...")
        _start_pairing(chat_id)

    elif data == "setup_cancel":
        telegram_client.answer_callback_query(cb_id, "Abgebrochen")
        telegram_client.send_message(chat_id, "❌ Ventil-Kopplung abgebrochen.", get_main_keyboard())

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
    telegram_client.broadcast_notification(event.report_text)

def _on_watering_skipped(event: WateringSkipped):
    telegram_client.broadcast_notification(f"🌤️ **Zeitplan '{event.schedule_name}' übersprungen!**\n{event.details}")

def _on_schedule_failed(event: ScheduleFailed):
    telegram_client.broadcast_notification(f"⚠️ **Fehler bei Zeitplan '{event.schedule_name}'!**\n{event.details}")

_global_bus.subscribe(WateringCycleStarted, _on_watering_started)
_global_bus.subscribe(WateringCycleCompleted, _on_watering_completed)
_global_bus.subscribe(WateringCycleFailed, _on_watering_failed)
_global_bus.subscribe(WateringCycleStopped, _on_watering_stopped)
_global_bus.subscribe(DailyReportTriggered, _on_daily_report)
_global_bus.subscribe(WateringSkipped, _on_watering_skipped)
_global_bus.subscribe(ScheduleFailed, _on_schedule_failed)
