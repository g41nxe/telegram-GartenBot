# Zeitplan-Bearbeitung — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jeder Zeitplan in der Liste erhält einen „✏️"-Button. Ein feldweises Bearbeitungs-Menü lässt gezielt Zeit, Tage, Dauer, Menge oder Name ändern und speichert via `database.update_schedule`.

**Architecture:** Reine `telegram_ui.py`-Änderung. Kein neues DB-Schema, keine Core-Änderung. Neues `edit_states`-Dict analog zu `wizard_states` (TTL-basiert, gleiche Hilfsfunktionen). Bearbeitungs-Callbacks starten mit `sched_edit_*`. Jede Feld-Änderung ist eine Ein-Schritt-Interaktion: aktuellen Wert zeigen → Eingabe → `update_schedule` aufrufen.

**Tech Stack:** Python 3.11, bestehende `database.update_schedule`, Telegram Inline-Keyboard.

---

### Task 1: ✏️-Button in der Zeitplan-Liste

**Files:**
- Modify: `src/daemon/ui/telegram_ui.py` (`get_schedules_inline_keyboard`, ca. Zeile 212)
- Modify: `tests/ui/test_telegram_ui.py`

- [ ] **Schritt 1: Failing-Test**

```python
class TestScheduleEditButton(unittest.TestCase):
    def test_keyboard_enthaelt_edit_button_pro_zeitplan(self):
        """Jeder Zeitplan im Inline-Keyboard hat einen ✏️-Bearbeiten-Button."""
        from daemon.ui.telegram_ui import get_schedules_inline_keyboard
        schedules = [{"id": 7, "name": "Abend", "time": "20:00", "is_active": 1}]
        kb = get_schedules_inline_keyboard(schedules)
        row = kb["inline_keyboard"][0]
        callbacks = [btn["callback_data"] for btn in row]
        self.assertIn("sched_edit_7", callbacks)

    def test_edit_button_text_ist_stift_emoji(self):
        """Der Bearbeiten-Button trägt das ✏️-Emoji."""
        from daemon.ui.telegram_ui import get_schedules_inline_keyboard
        schedules = [{"id": 3, "name": "Morgen", "time": "07:00", "is_active": 0}]
        kb = get_schedules_inline_keyboard(schedules)
        row = kb["inline_keyboard"][0]
        edit_btn = next(b for b in row if b["callback_data"] == "sched_edit_3")
        self.assertEqual(edit_btn["text"], "✏️")
```

- [ ] **Schritt 2: Test ausführen — muss FAIL**

```
python -m unittest tests.ui.test_telegram_ui.TestScheduleEditButton -v
```

- [ ] **Schritt 3: `get_schedules_inline_keyboard` erweitern**

```python
def get_schedules_inline_keyboard(schedules: list) -> dict:
    """Erstellt ein Inline-Keyboard mit Toggle-, Bearbeiten- und Lösch-Button pro Zeitplan."""
    rows = []
    for s in schedules:
        icon = "✅" if s["is_active"] else "⏸️"
        rows.append([
            {"text": f"{icon} {s['name']} ({s['time']})", "callback_data": f"sched_toggle_{s['id']}"},
            {"text": "✏️", "callback_data": f"sched_edit_{s['id']}"},
            {"text": "🗑️", "callback_data": f"sched_delete_ask_{s['id']}"},
        ])
    rows.append([{"text": "➕ Neuer Zeitplan", "callback_data": "wiz_start"}])
    return {"inline_keyboard": rows}
```

- [ ] **Schritt 4: Tests grün**

```
python -m unittest tests.ui.test_telegram_ui.TestScheduleEditButton -v
```

- [ ] **Schritt 5: Commit**

```bash
git add src/daemon/ui/telegram_ui.py tests/ui/test_telegram_ui.py
git commit -m "feat: ✏️-Button pro Zeitplan in der Zeitplan-Liste (0021)"
```

---

### Task 2: Edit-State-Infrastruktur und Feld-Auswahl-Menü

**Files:**
- Modify: `src/daemon/ui/telegram_ui.py`
- Modify: `tests/ui/test_telegram_ui.py`

`edit_states` ist ein Dict `{chat_id: {"sched_id": int, "field": str|None, "expires": float}}`. Die TTL-Hilfsfunktionen `_state_get/set/del/touch` aus `wizard_states` sind identisch — sie werden mit dem jeweiligen Dict aufgerufen, kein Duplikat der Logik.

- [ ] **Schritt 1: Failing-Test**

```python
def test_sched_edit_callback_zeigt_feld_auswahlmenue(self):
    """sched_edit_7 zeigt ein Menü mit den bearbeitbaren Feldern."""
    schedule = {"id": 7, "name": "Abend", "time": "20:00",
                "days": "Mo,Di", "duration_minutes": 15,
                "target_volume_liters": 0, "is_active": 1}
    with patch("daemon.adapters.database.get_schedule_by_id", return_value=schedule), \
         patch("daemon.ui.telegram_client.edit_message_text") as mock_edit, \
         patch("daemon.ui.telegram_client.answer_callback_query"):
        from daemon.ui.telegram_ui import on_telegram_update
        cb = {"id": "cb1", "from": {"id": 10929004},
              "message": {"chat": {"id": 10929004}, "message_id": 42},
              "data": "sched_edit_7"}
        on_telegram_update(None, cb)
        mock_edit.assert_called_once()
        text = mock_edit.call_args[0][2]
        self.assertIn("✏️", text)
        self.assertIn("Abend", text)
        kb = mock_edit.call_args[0][3]
        callbacks = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
        self.assertIn("sched_editfield_time_7", callbacks)
        self.assertIn("sched_editfield_days_7", callbacks)
        self.assertIn("sched_editfield_duration_7", callbacks)
        self.assertIn("sched_editfield_volume_7", callbacks)
        self.assertIn("sched_editfield_name_7", callbacks)
```

- [ ] **Schritt 2: Test ausführen — muss FAIL**

```
python -m unittest tests.ui.test_telegram_ui.TestScheduleEditButton.test_sched_edit_callback_zeigt_feld_auswahlmenue -v
```

- [ ] **Schritt 3: DB-Funktion + Edit-State-Dict + Callback-Handler**

In `database.py` die Funktion `get_schedule_by_id` hinzufügen (falls noch nicht vorhanden):

```python
def get_schedule_by_id(schedule_id: int) -> dict | None:
    """Gibt einen einzelnen Zeitplan anhand seiner ID zurück."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"Fehler beim Abrufen des Zeitplans {schedule_id}: {e}")
        return None
    finally:
        conn.close()
```

In `telegram_ui.py` — nach `wizard_states` das neue Dict und den Handler:

```python
edit_states: dict = {}  # {chat_id: {"sched_id": int, "step": str, "expires": float}}
```

Im Callback-Handler-Block (bei `elif data.startswith("sched_edit_")` — VOR dem bestehenden `sched_delete_ask_`):

```python
elif data.startswith("sched_edit_") and not data.startswith("sched_editfield_"):
    sched_id = int(data.split("_")[2])
    schedule = database.get_schedule_by_id(sched_id)
    if not schedule:
        telegram_client.answer_callback_query(cb_id, "Zeitplan nicht gefunden.")
        return
    telegram_client.answer_callback_query(cb_id)
    _state_set(edit_states, chat_id, {"sched_id": sched_id})
    days_str = format_days_german(schedule["days"].split(",") if schedule["days"] else [])
    vol = schedule.get("target_volume_liters") or 0
    telegram_client.edit_message_text(
        chat_id, message_id,
        f"*✏️ Zeitplan bearbeiten — \"{schedule['name']}\"*\n\n"
        f"• Zeit: {schedule['time']} Uhr\n"
        f"• Tage: {days_str}\n"
        f"• Dauer: {schedule['duration_minutes']} Min\n"
        f"• Menge: {vol} L\n\n"
        f"Was möchtest du ändern?",
        {"inline_keyboard": [
            [{"text": "⏰ Zeit",    "callback_data": f"sched_editfield_time_{sched_id}"},
             {"text": "📅 Tage",   "callback_data": f"sched_editfield_days_{sched_id}"}],
            [{"text": "⏳ Dauer",  "callback_data": f"sched_editfield_duration_{sched_id}"},
             {"text": "💧 Menge",  "callback_data": f"sched_editfield_volume_{sched_id}"}],
            [{"text": "✏️ Name",   "callback_data": f"sched_editfield_name_{sched_id}"}],
            [{"text": "❌ Abbrechen", "callback_data": "sched_edit_cancel"}],
        ]},
    )
```

Für `sched_edit_cancel`:

```python
elif data == "sched_edit_cancel":
    _state_del(edit_states, chat_id)
    telegram_client.answer_callback_query(cb_id, "Bearbeitung abgebrochen.")
    handle_schedules(chat_id)
```

- [ ] **Schritt 4: Tests grün**

```
python -m unittest tests.ui.test_telegram_ui -v
```

- [ ] **Schritt 5: Commit**

```bash
git add src/daemon/ui/telegram_ui.py src/daemon/adapters/database.py tests/ui/test_telegram_ui.py
git commit -m "feat: Zeitplan-Bearbeiten-Menü mit Feld-Auswahl (0021)"
```

---

### Task 3: Feld-Editierung — Zeit, Dauer, Menge, Name

**Files:**
- Modify: `src/daemon/ui/telegram_ui.py`
- Modify: `tests/ui/test_telegram_ui.py`

Jede Feld-Editierung ist ein Ein-Schritt-Inline-Keyboard (außer Name: freier Text). Danach direkt `update_schedule`.

- [ ] **Schritt 1: Failing-Tests**

```python
def test_editfield_duration_zeigt_dauer_keyboard(self):
    """sched_editfield_duration_7 zeigt ein Dauer-Auswahl-Keyboard."""
    schedule = {"id": 7, "name": "Abend", "time": "20:00",
                "days": "Mo", "duration_minutes": 15,
                "target_volume_liters": 0, "is_active": 1}
    with patch("daemon.adapters.database.get_schedule_by_id", return_value=schedule), \
         patch("daemon.ui.telegram_client.edit_message_text") as mock_edit, \
         patch("daemon.ui.telegram_client.answer_callback_query"):
        from daemon.ui.telegram_ui import on_telegram_update, edit_states, _state_set
        _state_set(edit_states, 10929004, {"sched_id": 7})
        cb = {"id": "cb1", "from": {"id": 10929004},
              "message": {"chat": {"id": 10929004}, "message_id": 42},
              "data": "sched_editfield_duration_7"}
        on_telegram_update(None, cb)
        mock_edit.assert_called_once()
        kb = mock_edit.call_args[0][3]
        callbacks = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
        self.assertTrue(any("sched_setduration_7_" in c for c in callbacks))

def test_sched_setduration_speichert_und_bestaetigt(self):
    """sched_setduration_7_20 ruft update_schedule mit neuer Dauer auf."""
    schedule = {"id": 7, "name": "Abend", "time": "20:00",
                "days": "Mo", "duration_minutes": 15,
                "target_volume_liters": 0, "is_active": 1}
    with patch("daemon.adapters.database.get_schedule_by_id", return_value=schedule), \
         patch("daemon.adapters.database.update_schedule") as mock_update, \
         patch("daemon.adapters.database.get_schedules", return_value=[]), \
         patch("daemon.ui.telegram_client.send_message"), \
         patch("daemon.ui.telegram_client.edit_message_text"), \
         patch("daemon.ui.telegram_client.answer_callback_query"):
        from daemon.ui.telegram_ui import on_telegram_update, edit_states, _state_set
        _state_set(edit_states, 10929004, {"sched_id": 7})
        cb = {"id": "cb1", "from": {"id": 10929004},
              "message": {"chat": {"id": 10929004}, "message_id": 42},
              "data": "sched_setduration_7_20"}
        on_telegram_update(None, cb)
        mock_update.assert_called_once_with(7, "Abend", "20:00", "Mo", 20, 0, 1)
```

- [ ] **Schritt 2: Tests ausführen — müssen FAIL**

```
python -m unittest tests.ui.test_telegram_ui.TestScheduleEditButton -v
```

- [ ] **Schritt 3: Callbacks für Zeit, Dauer, Menge, Name**

```python
elif data.startswith("sched_editfield_"):
    parts = data.split("_")
    # Format: sched_editfield_<field>_<id>
    field = parts[2]
    sched_id = int(parts[3])
    schedule = database.get_schedule_by_id(sched_id)
    if not schedule:
        telegram_client.answer_callback_query(cb_id, "Zeitplan nicht mehr vorhanden.")
        return
    telegram_client.answer_callback_query(cb_id)
    _state_set(edit_states, chat_id, {"sched_id": sched_id, "field": field})

    if field == "duration":
        durations = [5, 10, 15, 20, 25, 30, 45, 60]
        rows = []
        for i in range(0, len(durations), 4):
            rows.append([{"text": f"{d} Min", "callback_data": f"sched_setduration_{sched_id}_{d}"}
                         for d in durations[i:i+4]])
        rows.append([{"text": "❌ Abbrechen", "callback_data": "sched_edit_cancel"}])
        telegram_client.edit_message_text(
            chat_id, message_id,
            f"*✏️ Zeitplan bearbeiten — \"{schedule['name']}\"*\n\n"
            f"Aktuell: *{schedule['duration_minutes']} Min*\n\nNeue Dauer wählen:",
            {"inline_keyboard": rows}
        )

    elif field == "volume":
        volumes = [0, 5, 10, 15, 20, 25, 30, 40]
        rows = []
        for i in range(0, len(volumes), 4):
            rows.append([{"text": "∞" if v == 0 else f"{v} L",
                          "callback_data": f"sched_setvolume_{sched_id}_{v}"}
                         for v in volumes[i:i+4]])
        rows.append([{"text": "❌ Abbrechen", "callback_data": "sched_edit_cancel"}])
        cur_vol = schedule.get("target_volume_liters") or 0
        telegram_client.edit_message_text(
            chat_id, message_id,
            f"*✏️ Zeitplan bearbeiten — \"{schedule['name']}\"*\n\n"
            f"Aktuell: *{'∞ (kein Limit)' if cur_vol == 0 else str(cur_vol) + ' L'}*\n\nNeue Menge wählen:",
            {"inline_keyboard": rows}
        )

    elif field == "time":
        # Stunden-Auswahl (0–23)
        rows = []
        for i in range(0, 24, 6):
            rows.append([{"text": f"{h:02d}", "callback_data": f"sched_edithour_{sched_id}_{h}"}
                         for h in range(i, min(i+6, 24))])
        rows.append([{"text": "❌ Abbrechen", "callback_data": "sched_edit_cancel"}])
        telegram_client.edit_message_text(
            chat_id, message_id,
            f"*✏️ Zeitplan bearbeiten — \"{schedule['name']}\"*\n\n"
            f"Aktuell: *{schedule['time']} Uhr*\n\nNeue Stunde wählen:",
            {"inline_keyboard": rows}
        )

    elif field == "name":
        _state_set(edit_states, chat_id, {"sched_id": sched_id, "field": "name"})
        telegram_client.edit_message_text(
            chat_id, message_id,
            f"*✏️ Zeitplan bearbeiten — \"{schedule['name']}\"*\n\n"
            f"Aktuell: *{schedule['name']}*\n\nNeuen Namen eingeben:",
            {"inline_keyboard": [[{"text": "❌ Abbrechen", "callback_data": "sched_edit_cancel"}]]}
        )

    elif field == "days":
        current_days = schedule["days"].split(",") if schedule["days"] else []
        telegram_client.edit_message_text(
            chat_id, message_id,
            f"*✏️ Zeitplan bearbeiten — \"{schedule['name']}\"*\n\n"
            f"Wochentage auswählen (Tippen zum Ändern):\n\n"
            f"*Aktuell: {format_days_german(current_days)}*",
            get_days_wizard_keyboard(current_days, prefix=f"sched_editday_{sched_id}")
        )
```

Direkt-Speicher-Callbacks:

```python
elif data.startswith("sched_setduration_"):
    _, _, sched_id_s, dur_s = data.split("_")
    sched_id, dur = int(sched_id_s), int(dur_s)
    schedule = database.get_schedule_by_id(sched_id)
    if schedule:
        database.update_schedule(sched_id, schedule["name"], schedule["time"],
                                 schedule["days"], dur,
                                 schedule.get("target_volume_liters") or 0, schedule["is_active"])
        telegram_client.answer_callback_query(cb_id, f"Dauer auf {dur} Min gesetzt.")
        _state_del(edit_states, chat_id)
        handle_schedules(chat_id)

elif data.startswith("sched_setvolume_"):
    _, _, sched_id_s, vol_s = data.split("_")
    sched_id, vol = int(sched_id_s), int(vol_s)
    schedule = database.get_schedule_by_id(sched_id)
    if schedule:
        database.update_schedule(sched_id, schedule["name"], schedule["time"],
                                 schedule["days"], schedule["duration_minutes"],
                                 vol, schedule["is_active"])
        label = "∞ (kein Limit)" if vol == 0 else f"{vol} L"
        telegram_client.answer_callback_query(cb_id, f"Menge auf {label} gesetzt.")
        _state_del(edit_states, chat_id)
        handle_schedules(chat_id)
```

Zeit-Stunde/Minute (zweistufig wie im Anlege-Wizard):

```python
elif data.startswith("sched_edithour_"):
    parts = data.split("_")
    sched_id, hour = int(parts[2]), int(parts[3])
    _state_set(edit_states, chat_id, {"sched_id": sched_id, "field": "time", "hour": hour})
    telegram_client.answer_callback_query(cb_id)
    rows = []
    for i in range(0, 60, 15):
        rows.append([{"text": f":{m:02d}", "callback_data": f"sched_editminute_{sched_id}_{hour}_{m}"}
                     for m in range(i, min(i+15, 60), 5)])
    rows.append([{"text": "❌ Abbrechen", "callback_data": "sched_edit_cancel"}])
    telegram_client.edit_message_text(
        chat_id, message_id,
        f"*✏️ Zeit bearbeiten*\n\nStunde: *{hour:02d}*\nMinuten wählen:",
        {"inline_keyboard": rows}
    )

elif data.startswith("sched_editminute_"):
    parts = data.split("_")
    sched_id, hour, minute = int(parts[2]), int(parts[3]), int(parts[4])
    schedule = database.get_schedule_by_id(sched_id)
    if schedule:
        new_time = f"{hour:02d}:{minute:02d}"
        database.update_schedule(sched_id, schedule["name"], new_time,
                                 schedule["days"], schedule["duration_minutes"],
                                 schedule.get("target_volume_liters") or 0, schedule["is_active"])
        telegram_client.answer_callback_query(cb_id, f"Zeit auf {new_time} Uhr gesetzt.")
        _state_del(edit_states, chat_id)
        handle_schedules(chat_id)
```

- [ ] **Schritt 4: Tests grün**

```
python -m unittest tests.ui.test_telegram_ui -v
```

- [ ] **Schritt 5: Commit**

```bash
git add src/daemon/ui/telegram_ui.py tests/ui/test_telegram_ui.py
git commit -m "feat: Zeitplan-Feld-Editierung (Zeit, Dauer, Menge, Name, Tage) (0021)"
```

---

### Task 4: Tage-Editierung mit Vorauswahl + Texteingabe für Namen

**Files:**
- Modify: `src/daemon/ui/telegram_ui.py`
- Modify: `tests/ui/test_telegram_ui.py`

Tage-Editierung nutzt `get_days_wizard_keyboard` mit einem angepassten Prefix für die Callbacks sowie einem eigenen Speichern-Button.

- [ ] **Schritt 1: Failing-Test**

```python
def test_editfield_days_zeigt_vorausgewaehlte_tage(self):
    """sched_editfield_days_7 zeigt Tage-Keyboard mit aktuellen Tagen vorausgewählt."""
    schedule = {"id": 7, "name": "Abend", "time": "20:00",
                "days": "Mo,Mi", "duration_minutes": 15,
                "target_volume_liters": 0, "is_active": 1}
    with patch("daemon.adapters.database.get_schedule_by_id", return_value=schedule), \
         patch("daemon.ui.telegram_client.edit_message_text") as mock_edit, \
         patch("daemon.ui.telegram_client.answer_callback_query"):
        from daemon.ui.telegram_ui import on_telegram_update, edit_states, _state_set
        _state_set(edit_states, 10929004, {"sched_id": 7})
        cb = {"id": "cb1", "from": {"id": 10929004},
              "message": {"chat": {"id": 10929004}, "message_id": 42},
              "data": "sched_editfield_days_7"}
        on_telegram_update(None, cb)
        text = mock_edit.call_args[0][2]
        self.assertIn("Mo", text)
        self.assertIn("Mi", text)

def test_sched_editday_toggle_und_save(self):
    """sched_editday_save_7 speichert die aktuell ausgewählten Tage."""
    schedule = {"id": 7, "name": "Abend", "time": "20:00",
                "days": "Mo,Mi", "duration_minutes": 15,
                "target_volume_liters": 0, "is_active": 1}
    with patch("daemon.adapters.database.get_schedule_by_id", return_value=schedule), \
         patch("daemon.adapters.database.update_schedule") as mock_update, \
         patch("daemon.adapters.database.get_schedules", return_value=[]), \
         patch("daemon.ui.telegram_client.send_message"), \
         patch("daemon.ui.telegram_client.edit_message_text"), \
         patch("daemon.ui.telegram_client.answer_callback_query"):
        from daemon.ui.telegram_ui import on_telegram_update, edit_states, _state_set
        _state_set(edit_states, 10929004, {"sched_id": 7, "field": "days", "edit_days": ["Mo", "Di", "Mi"]})
        cb = {"id": "cb1", "from": {"id": 10929004},
              "message": {"chat": {"id": 10929004}, "message_id": 42},
              "data": "sched_editday_save_7"}
        on_telegram_update(None, cb)
        mock_update.assert_called_once()
        call_days = mock_update.call_args[0][3]
        self.assertEqual(call_days, "Mo,Di,Mi")
```

- [ ] **Schritt 2: Test ausführen — muss FAIL**

```
python -m unittest tests.ui.test_telegram_ui.TestScheduleEditButton.test_sched_editday_toggle_und_save -v
```

- [ ] **Schritt 3: Tage-Toggle + Speichern-Callbacks**

`get_days_wizard_keyboard` akzeptiert bereits einen `prefix`-Parameter nicht — wir brauchen eine Variante für die Edit-Tage. Füge Callbacks `sched_editday_{sched_id}_{day}` und `sched_editday_save_{sched_id}` hinzu:

Im `sched_editfield_days` Zweig im Code aus Task 3 wird der State mit `edit_days` befüllt:

```python
elif field == "days":
    current_days = schedule["days"].split(",") if schedule["days"] else []
    _state_set(edit_states, chat_id, {"sched_id": sched_id, "field": "days", "edit_days": list(current_days)})
    days_keyboard = _get_edit_days_keyboard(sched_id, current_days)
    telegram_client.edit_message_text(
        chat_id, message_id,
        f"*✏️ Zeitplan bearbeiten — \"{schedule['name']}\"*\n\n"
        f"Wochentage wählen:\n*Aktuell: {format_days_german(current_days)}*",
        days_keyboard
    )
```

Hilfsfunktion `_get_edit_days_keyboard`:

```python
def _get_edit_days_keyboard(sched_id: int, selected: list) -> dict:
    _DAYS = [("Mo","Mo"),("Di","Di"),("Mi","Mi"),("Do","Do"),("Fr","Fr"),("Sa","Sa"),("So","So")]
    rows = [[
        {"text": f"{'✅' if d[0] in selected else '⬜'} {d[1]}",
         "callback_data": f"sched_editday_{sched_id}_{d[0]}"}
        for d in _DAYS[:4]
    ],[
        {"text": f"{'✅' if d[0] in selected else '⬜'} {d[1]}",
         "callback_data": f"sched_editday_{sched_id}_{d[0]}"}
        for d in _DAYS[4:]
    ],[
        {"text": "🔁 Täglich", "callback_data": f"sched_editday_{sched_id}_everyday"}
    ],[
        {"text": "💾 Speichern", "callback_data": f"sched_editday_save_{sched_id}"},
        {"text": "❌ Abbrechen",  "callback_data": "sched_edit_cancel"},
    ]]
    return {"inline_keyboard": rows}
```

Toggle-Callback:

```python
elif data.startswith("sched_editday_") and not data.startswith("sched_editday_save_"):
    parts = data.split("_")
    sched_id, day = int(parts[2]), parts[3]
    state = _state_get(edit_states, chat_id)
    if state:
        days = state.get("edit_days", [])
        if day == "everyday":
            days = ["everyday"] if "everyday" not in days else []
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
        days_keyboard = _get_edit_days_keyboard(sched_id, days)
        telegram_client.edit_message_text(
            chat_id, message_id,
            f"*✏️ Zeitplan bearbeiten — \"{schedule['name'] if schedule else ''}\"*\n\n"
            f"Wochentage wählen:\n*Gewählt: {format_days_german(days)}*",
            days_keyboard
        )

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
            database.update_schedule(sched_id, schedule["name"], schedule["time"],
                                     days_str, schedule["duration_minutes"],
                                     schedule.get("target_volume_liters") or 0, schedule["is_active"])
            telegram_client.answer_callback_query(cb_id, f"Tage gespeichert.")
            _state_del(edit_states, chat_id)
            handle_schedules(chat_id)
```

Texteingabe für Name (in `_handle_text_input` / direkt im Nachrichten-Handler):

```python
# Im Nachrichten-Handler, VOR dem Wizard-Check:
edit_state = _state_get(edit_states, chat_id)
if edit_state and edit_state.get("field") == "name":
    sched_id = edit_state["sched_id"]
    new_name = text.strip()
    if not new_name or len(new_name) > 50:
        telegram_client.send_message(chat_id, "❌ Name muss zwischen 1 und 50 Zeichen lang sein.")
        return
    schedule = database.get_schedule_by_id(sched_id)
    if schedule:
        database.update_schedule(sched_id, new_name, schedule["time"],
                                 schedule["days"], schedule["duration_minutes"],
                                 schedule.get("target_volume_liters") or 0, schedule["is_active"])
        _state_del(edit_states, chat_id)
        telegram_client.send_message(chat_id, f"✅ Name auf *\"{new_name}\"* geändert.")
        handle_schedules(chat_id)
    return
```

- [ ] **Schritt 4: Gesamte Testsuite grün**

```
python -m unittest discover tests -v
```

- [ ] **Schritt 5: Commit**

```bash
git add src/daemon/ui/telegram_ui.py tests/ui/test_telegram_ui.py
git commit -m "feat: Tage-Editierung mit Vorauswahl, Namens-Texteingabe (0021)"
```

---

### Task 5: Abschluss

- [ ] **Gesamte Testsuite**

```
python -m unittest discover tests -v
```

- [ ] **`telegram-nachrichten.html` aktualisieren** (`.claude/rules/telegram_messages.md`)

Neue Nachrichten eintragen:
- Feld-Auswahl-Menü (`sched_edit_*` · Zeitplan-Bearbeitung)
- Bestätigungen nach Feldänderungen

- [ ] **Feature-Doc verschieben**

```bash
git mv docs/features/0021-zeitplan-bearbeitung.md docs/features/completed/
git mv docs/plans/0021-zeitplan-bearbeitung-plan.md docs/plans/completed/
git commit -m "docs: Feature 0021 abgeschlossen — Zeitplan-Bearbeitung"
```
