# In-Chat-Einstellungen — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `RAIN_THRESHOLD_MM`, `BATTERY_WARNING_THRESHOLD` und `SAFETY_TIMEOUT_MINUTES` können im Telegram-Bot gelesen und geändert werden. Änderungen wirken sofort, ohne Neustart. Werte werden in `system_metadata` persistiert.

**Architecture:** `config.py` erhält drei Funktionen: `get_setting(name, default)`, `set_setting(name, value)`, `reset_setting(name)`. Alle Lesestellen der drei Parameter werden von `config.CONSTANT` auf `config.get_setting(...)` umgestellt. Ein neuer `/einstellungen`-Handler in `telegram_ui.py` zeigt die aktuellen Werte und erlaubt Inline-Änderungen. DB-Key-Schema: `setting_<NAME>` in `system_metadata`.

**Tech Stack:** Python 3.11, bestehende `database.get_metadata` / `database.set_metadata`, neues `database.delete_metadata`.

---

### Task 1: `database.delete_metadata` + `config.get_setting / set_setting / reset_setting`

**Files:**
- Modify: `src/daemon/adapters/database.py`
- Modify: `src/daemon/config.py`
- Modify: `tests/test_config.py`

- [ ] **Schritt 1: Failing-Tests**

In `tests/test_config.py` zur Klasse `TestConfigLoading` hinzufügen:

```python
def test_get_setting_gibt_db_override_zurueck(self):
    """get_setting liefert den DB-Wert wenn ein Override gesetzt ist."""
    with patch("daemon.adapters.database.get_metadata", return_value="4.5"):
        import importlib
        import daemon.config as cfg
        importlib.reload(cfg)
        result = cfg.get_setting("RAIN_THRESHOLD_MM", 2.0)
        self.assertAlmostEqual(result, 4.5)

def test_get_setting_faellt_auf_modulkonstante_zurueck(self):
    """get_setting liefert den Modulwert wenn kein DB-Override vorhanden."""
    with patch("daemon.adapters.database.get_metadata", return_value=None):
        import daemon.config as cfg
        result = cfg.get_setting("RAIN_THRESHOLD_MM", 2.0)
        self.assertAlmostEqual(result, cfg.RAIN_THRESHOLD_MM)

def test_get_setting_liefert_default_wenn_attribut_fehlt(self):
    """get_setting liefert den angegebenen Default wenn weder DB noch Modul-Attr vorhanden."""
    with patch("daemon.adapters.database.get_metadata", return_value=None):
        import daemon.config as cfg
        result = cfg.get_setting("NONEXISTENT_SETTING", 99.0)
        self.assertAlmostEqual(result, 99.0)

def test_reset_setting_loescht_db_override(self):
    """reset_setting entfernt den DB-Override."""
    with patch("daemon.adapters.database.delete_metadata") as mock_del:
        import daemon.config as cfg
        cfg.reset_setting("RAIN_THRESHOLD_MM")
        mock_del.assert_called_once_with("setting_RAIN_THRESHOLD_MM")
```

- [ ] **Schritt 2: Tests ausführen — müssen FAIL**

```
python -m unittest tests.test_config -v
```

- [ ] **Schritt 3: `delete_metadata` in `database.py`**

```python
def delete_metadata(key: str) -> None:
    """Entfernt einen Metadatenwert aus der system_metadata-Tabelle."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM system_metadata WHERE key = ?", (key,))
        conn.commit()
    except Exception as e:
        logger.error(f"Fehler beim Löschen des Metadatenwerts für {key}: {e}")
    finally:
        conn.close()
```

- [ ] **Schritt 4: `get_setting`, `set_setting`, `reset_setting` in `config.py`**

Am Ende von `config.py` hinzufügen:

```python
def get_setting(name: str, default=None):
    """Liest einen Konfigurationswert — DB-Override hat Vorrang vor Modulkonstante."""
    try:
        from .adapters import database
        db_val = database.get_metadata(f"setting_{name}")
        if db_val is not None:
            if isinstance(default, float):
                return float(db_val)
            if isinstance(default, int):
                return int(db_val)
            return db_val
    except Exception:
        pass
    import sys
    return getattr(sys.modules[__name__], name, default)


def set_setting(name: str, value) -> None:
    """Speichert einen Laufzeit-Override für einen Konfigurationswert in der DB."""
    from .adapters import database
    database.set_metadata(f"setting_{name}", str(value))


def reset_setting(name: str) -> None:
    """Entfernt den DB-Override — der Wert aus garden.conf/.env greift wieder."""
    from .adapters import database
    database.delete_metadata(f"setting_{name}")
```

- [ ] **Schritt 5: Tests grün**

```
python -m unittest tests.test_config -v
```

- [ ] **Schritt 6: Gesamte Testsuite**

```
python -m unittest discover tests -v
```

- [ ] **Schritt 7: Commit**

```bash
git add src/daemon/adapters/database.py src/daemon/config.py tests/test_config.py
git commit -m "feat: config.get_setting/set_setting/reset_setting + database.delete_metadata (0022)"
```

---

### Task 2: Lesestellen auf `config.get_setting` umstellen

**Files:**
- Modify: `src/daemon/adapters/weather.py`
- Modify: `src/daemon/adapters/chart.py`
- Modify: `src/daemon/adapters/daily_report.py`
- Modify: `src/daemon/ui/telegram_ui.py` (Zeile 395: `getattr(config, "BATTERY_WARNING_THRESHOLD", 20)`)
- Modify: `src/daemon/adapters/mqtt_client.py`

Kein neuer Test nötig — bestehende Tests prüfen das Verhalten weiterhin. Die `get_setting`-Tests aus Task 1 decken die Logik ab.

- [ ] **Schritt 1: `weather.py` — RAIN_THRESHOLD_MM**

```python
# Vorher (in should_skip_watering):
result = evaluate_rain_window(rain_last, rain_next, config.RAIN_THRESHOLD_MM)

# Nachher:
result = evaluate_rain_window(rain_last, rain_next, config.get_setting("RAIN_THRESHOLD_MM", 2.0))
```

- [ ] **Schritt 2: `chart.py` — RAIN_THRESHOLD_MM**

```python
# Vorher:
result = evaluate_rain_window(rain_last_24h_mm, rain_next_24h_mm, config.RAIN_THRESHOLD_MM)

# Nachher:
result = evaluate_rain_window(rain_last_24h_mm, rain_next_24h_mm, config.get_setting("RAIN_THRESHOLD_MM", 2.0))
```

- [ ] **Schritt 3: `daily_report.py` — BATTERY_WARNING_THRESHOLD**

```python
# Vorher (beide Stellen):
if battery <= config.BATTERY_WARNING_THRESHOLD:

# Nachher:
if battery <= config.get_setting("BATTERY_WARNING_THRESHOLD", 20):
```

Auch die Textstellen:
```python
# Vorher:
f" (Grenzwert: {config.BATTERY_WARNING_THRESHOLD}%)"

# Nachher:
f" (Grenzwert: {config.get_setting('BATTERY_WARNING_THRESHOLD', 20)}%)"
```

- [ ] **Schritt 4: `telegram_ui.py` — BATTERY_WARNING_THRESHOLD**

```python
# Vorher (ca. Zeile 395):
threshold = getattr(config, "BATTERY_WARNING_THRESHOLD", 20)

# Nachher:
threshold = config.get_setting("BATTERY_WARNING_THRESHOLD", 20)
```

- [ ] **Schritt 5: `mqtt_client.py` — SAFETY_TIMEOUT_MINUTES**

```python
# Vorher (beide Stellen, ca. Zeile 226 und 229):
"irrigation_duration": config.SAFETY_TIMEOUT_MINUTES,
"fail_safe": config.SAFETY_TIMEOUT_MINUTES,

# Nachher:
"irrigation_duration": config.get_setting("SAFETY_TIMEOUT_MINUTES", 30),
"fail_safe": config.get_setting("SAFETY_TIMEOUT_MINUTES", 30),
```

- [ ] **Schritt 6: Gesamte Testsuite**

```
python -m unittest discover tests -v
```

Alle Tests grün (kein Regression).

- [ ] **Schritt 7: Commit**

```bash
git add src/daemon/adapters/weather.py src/daemon/adapters/chart.py \
        src/daemon/adapters/daily_report.py src/daemon/ui/telegram_ui.py \
        src/daemon/adapters/mqtt_client.py
git commit -m "refactor: Lesestellen auf config.get_setting umgestellt (0022)"
```

---

### Task 3: `/einstellungen`-Handler in `telegram_ui.py`

**Files:**
- Modify: `src/daemon/ui/telegram_ui.py`
- Modify: `tests/ui/test_telegram_ui.py`

Einstellungsmenü zeigt aktuelle Werte der drei Parameter mit je einem Ändern-Button. Validierungsgrenzen: `RAIN_THRESHOLD_MM` 0.1–50.0, `BATTERY_WARNING_THRESHOLD` 5–90, `SAFETY_TIMEOUT_MINUTES` 5–30.

- [ ] **Schritt 1: Failing-Tests**

```python
class TestEinstellungenHandler(unittest.TestCase):

    def test_einstellungen_zeigt_aktuelle_werte(self):
        """handle_einstellungen zeigt die aktuellen Werte der drei Einstellungen."""
        with patch("daemon.config.get_setting", side_effect=lambda name, d: {"RAIN_THRESHOLD_MM": 2.5,
              "BATTERY_WARNING_THRESHOLD": 20, "SAFETY_TIMEOUT_MINUTES": 30}.get(name, d)), \
             patch("daemon.ui.telegram_client.send_message") as mock_send:
            from daemon.ui.telegram_ui import handle_einstellungen
            handle_einstellungen(12345)
            text = mock_send.call_args[0][1]
            self.assertIn("2.5", text)
            self.assertIn("20", text)
            self.assertIn("30", text)

    def test_set_rain_threshold_gueltig(self):
        """set_rain_4.0 speichert 4.0 mm als neuen Schwellwert."""
        with patch("daemon.config.set_setting") as mock_set, \
             patch("daemon.ui.telegram_client.answer_callback_query"), \
             patch("daemon.ui.telegram_client.edit_message_text"), \
             patch("daemon.config.get_setting", return_value=4.0):
            from daemon.ui.telegram_ui import on_telegram_update
            cb = {"id": "cb1", "from": {"id": 10929004},
                  "message": {"chat": {"id": 10929004}, "message_id": 42},
                  "data": "set_rain_4.0"}
            on_telegram_update(None, cb)
            mock_set.assert_called_once_with("RAIN_THRESHOLD_MM", 4.0)

    def test_set_rain_threshold_ungueltig_wird_abgelehnt(self):
        """set_rain_99.0 wird abgelehnt (über dem Maximum von 50 mm)."""
        with patch("daemon.config.set_setting") as mock_set, \
             patch("daemon.ui.telegram_client.answer_callback_query") as mock_ans:
            from daemon.ui.telegram_ui import on_telegram_update
            cb = {"id": "cb1", "from": {"id": 10929004},
                  "message": {"chat": {"id": 10929004}, "message_id": 42},
                  "data": "set_rain_99.0"}
            on_telegram_update(None, cb)
            mock_set.assert_not_called()
            self.assertTrue(mock_ans.call_args[1].get("show_alert") or
                            mock_ans.call_args[0][1] if mock_ans.called else False)

    def test_reset_rain_threshold_entfernt_override(self):
        """reset_setting_RAIN_THRESHOLD_MM entfernt den DB-Override."""
        with patch("daemon.config.reset_setting") as mock_reset, \
             patch("daemon.ui.telegram_client.answer_callback_query"), \
             patch("daemon.ui.telegram_client.edit_message_text"), \
             patch("daemon.config.get_setting", return_value=2.0):
            from daemon.ui.telegram_ui import on_telegram_update
            cb = {"id": "cb1", "from": {"id": 10929004},
                  "message": {"chat": {"id": 10929004}, "message_id": 42},
                  "data": "reset_setting_RAIN_THRESHOLD_MM"}
            on_telegram_update(None, cb)
            mock_reset.assert_called_once_with("RAIN_THRESHOLD_MM")
```

- [ ] **Schritt 2: Tests ausführen — müssen FAIL**

```
python -m unittest tests.ui.test_telegram_ui.TestEinstellungenHandler -v
```

- [ ] **Schritt 3: `handle_einstellungen` + Callbacks**

```python
_SETTINGS_META = {
    "RAIN_THRESHOLD_MM": {
        "label": "Regenschwelle",
        "unit": "mm",
        "default": 2.0,
        "min": 0.1,
        "max": 50.0,
        "options": [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0],
        "cb_prefix": "set_rain",
    },
    "BATTERY_WARNING_THRESHOLD": {
        "label": "Batterie-Warnschwelle",
        "unit": "%",
        "default": 20,
        "min": 5,
        "max": 90,
        "options": [10, 15, 20, 25, 30],
        "cb_prefix": "set_battery",
    },
    "SAFETY_TIMEOUT_MINUTES": {
        "label": "Sicherheits-Timeout",
        "unit": "Min",
        "default": 30,
        "min": 5,
        "max": 30,
        "options": [5, 10, 15, 20, 25, 30],
        "cb_prefix": "set_safety",
        "hint": "⚠️ Wirkt erst beim nächsten Verbindungsaufbau zum Ventil.",
    },
}


def handle_einstellungen(chat_id: int):
    lines = ["*⚙️ Einstellungen*\n"]
    rows = []
    for key, meta in _SETTINGS_META.items():
        val = config.get_setting(key, meta["default"])
        lines.append(f"*{meta['label']}:* {val} {meta['unit']}")
        rows.append([
            {"text": f"✏️ {meta['label']}", "callback_data": f"einst_edit_{key}"},
            {"text": "↩️ Standard",          "callback_data": f"reset_setting_{key}"},
        ])
    rows.append([{"text": "❌ Schließen", "callback_data": "einst_close"}])
    telegram_client.send_message(chat_id, "\n".join(lines), {"inline_keyboard": rows})
```

Callbacks in `handle_callback`:

```python
elif data.startswith("einst_edit_"):
    key = data[len("einst_edit_"):]
    meta = _SETTINGS_META.get(key)
    if not meta:
        telegram_client.answer_callback_query(cb_id, "Unbekannte Einstellung.")
        return
    telegram_client.answer_callback_query(cb_id)
    cur = config.get_setting(key, meta["default"])
    option_rows = []
    for i in range(0, len(meta["options"]), 4):
        option_rows.append([
            {"text": f"{v} {meta['unit']}", "callback_data": f"{meta['cb_prefix']}_{v}"}
            for v in meta["options"][i:i+4]
        ])
    option_rows.append([{"text": "❌ Abbrechen", "callback_data": "einst_close"}])
    hint = f"\n_{meta['hint']}_" if "hint" in meta else ""
    telegram_client.edit_message_text(
        chat_id, message_id,
        f"*⚙️ {meta['label']}*\n\nAktuell: *{cur} {meta['unit']}*{hint}\n\nNeuen Wert wählen:",
        {"inline_keyboard": option_rows}
    )

elif data.startswith("set_rain_"):
    raw = data[len("set_rain_"):]
    _apply_setting(chat_id, cb_id, message_id, "RAIN_THRESHOLD_MM", raw)

elif data.startswith("set_battery_"):
    raw = data[len("set_battery_"):]
    _apply_setting(chat_id, cb_id, message_id, "BATTERY_WARNING_THRESHOLD", raw)

elif data.startswith("set_safety_"):
    raw = data[len("set_safety_"):]
    _apply_setting(chat_id, cb_id, message_id, "SAFETY_TIMEOUT_MINUTES", raw)

elif data.startswith("reset_setting_"):
    key = data[len("reset_setting_"):]
    meta = _SETTINGS_META.get(key)
    if meta:
        config.reset_setting(key)
        new_val = config.get_setting(key, meta["default"])
        telegram_client.answer_callback_query(cb_id, f"Zurückgesetzt auf {new_val} {meta['unit']}.")
        handle_einstellungen(chat_id)

elif data == "einst_close":
    telegram_client.answer_callback_query(cb_id)
    handle_einstellungen(chat_id)
```

Hilfsfunktion `_apply_setting`:

```python
def _apply_setting(chat_id: int, cb_id: str, message_id: int, key: str, raw: str):
    meta = _SETTINGS_META[key]
    try:
        val = float(raw) if isinstance(meta["default"], float) else int(raw)
    except ValueError:
        telegram_client.answer_callback_query(cb_id, "❌ Ungültiger Wert.", show_alert=True)
        return
    if not (meta["min"] <= val <= meta["max"]):
        telegram_client.answer_callback_query(
            cb_id,
            f"❌ Erlaubter Bereich: {meta['min']}–{meta['max']} {meta['unit']}.",
            show_alert=True
        )
        return
    config.set_setting(key, val)
    hint = f"\n_{meta.get('hint', '')}_" if "hint" in meta else ""
    telegram_client.answer_callback_query(cb_id, f"✅ {meta['label']} auf {val} {meta['unit']} gesetzt.")
    telegram_client.edit_message_text(
        chat_id, message_id,
        f"*⚙️ {meta['label']}* gesetzt auf *{val} {meta['unit']}*.{hint}",
        None
    )
```

- [ ] **Schritt 4: `/einstellungen` im Nachrichten-Handler registrieren**

```python
elif text.startswith("/einstellungen"):
    handle_einstellungen(chat_id)
```

- [ ] **Schritt 5: Tests grün**

```
python -m unittest tests.ui.test_telegram_ui.TestEinstellungenHandler -v
```

- [ ] **Schritt 6: Gesamte Testsuite**

```
python -m unittest discover tests -v
```

- [ ] **Schritt 7: Commit**

```bash
git add src/daemon/ui/telegram_ui.py tests/ui/test_telegram_ui.py
git commit -m "feat: /einstellungen — In-Chat-Konfiguration für Regenschwelle, Batterie, Timeout (0022)"
```

---

### Task 4: `setMyCommands` aktualisieren + Abschluss

**Files:**
- Modify: `src/daemon/main.py` — `/einstellungen` zur Befehlsliste hinzufügen

- [ ] **Schritt 1: Befehlsliste in `register_telegram_commands` erweitern**

```python
{"command": "einstellungen", "description": "Regenschwelle und Schwellwerte anpassen"},
```

- [ ] **Schritt 2: Gesamte Testsuite**

```
python -m unittest discover tests -v
```

- [ ] **Schritt 3: `telegram-nachrichten.html` aktualisieren**

Neue Nachrichten eintragen:
- Einstellungsmenü (Übersicht mit aktuellen Werten)
- Feld-Editierung (Wert-Auswahl mit Optionen)
- Bestätigung (alt → neu mit Einheit)
- Reset-Bestätigung

- [ ] **Schritt 4: Commit**

```bash
git add src/daemon/main.py docs/reference/telegram-nachrichten.html
git commit -m "feat: /einstellungen in Befehlsmenü, Nachrichten-Referenz aktualisiert (0022)"
```

- [ ] **Schritt 5: Feature-Doc verschieben**

```bash
git mv docs/features/0022-in-chat-einstellungen.md docs/features/completed/
git mv docs/plans/0022-in-chat-einstellungen-plan.md docs/plans/completed/
git commit -m "docs: Feature 0022 abgeschlossen — In-Chat-Einstellungen"
```
