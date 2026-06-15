# Plan: Feature 0015 — Kamera-Setup Wizard (Auflösung + Qualität) + Menü-Reorganisation

## Kontext

Feature 0015 erweitert den Kamera-Kopplungs-Assistenten von 2 auf 4 Schritte (Name → Intervall → Auflösung → Bildqualität) und reorganisiert das Hauptmenü des Telegram-Bots, indem selten genutzte Kopplungsbefehle hinter einem ⚙️ Setup-Untermenü versteckt werden.

**Was bereits fertig ist (kein Änderungsbedarf):**
- HTTP `/config`-Endpunkt gibt bereits `resolution` und `quality` aus der DB zurück (`camera_receiver.py`)
- `database.update_camera_settings(mac, sleep_seconds, resolution, quality)` hat bereits die richtige Signatur
- `cameras`-Tabelle hat bereits `resolution TEXT DEFAULT 'XGA'` und `quality INTEGER DEFAULT 10`

**Was fehlt:**
1. `camera_pairing.start_pairing()` kennt `resolution` und `quality` noch nicht
2. Wizard hat keinen Auflösungs- und Qualitätsschritt
3. Hauptmenü enthält Kopplungsbuttons direkt; kein ⚙️ Setup-Untermenü
4. Firmware wendet `resolution` aus `/config` nicht auf `set_framesize()` an

---

## Implementierungsplan (TDD — strikt Red → Green pro Schritt)

### Schritt 1 — RED: Tests für `camera_pairing.start_pairing()` Erweiterung

**Datei:** `tests/adapters/test_camera_pairing.py`

Zwei neue Tests hinzufügen:
- `test_resolution_and_quality_saved_after_successful_pairing`: ruft `start_pairing(..., resolution="VGA", quality=25)` → prüft `cam["resolution"] == "VGA"` und `cam["quality"] == 25` in der DB
- `test_default_resolution_and_quality_when_not_specified`: lässt Parameter weg → prüft `cam["resolution"] == "UXGA"` und `cam["quality"] == 10`

Bestehende `_start_and_trigger()`-Hilfsmethode um optionale `resolution`- und `quality`-kwargs erweitern.

→ Tests laufen rot (Parameter existieren noch nicht).

---

### Schritt 2 — GREEN: `camera_pairing.py` erweitern

**Datei:** `src/daemon/adapters/camera_pairing.py`

- `start_pairing(chat_id, notify_fn, wish_name, sleep_seconds=900, resolution="UXGA", quality=10)` → neue Parameter an `_pairing_worker()` durchreichen
- `_pairing_worker(...)` → `update_camera_settings(mac, sleep_seconds=sleep_seconds, resolution=resolution, quality=quality)` statt des bisherigen Aufrufs mit `cam["resolution"]` / `cam["quality"]`

→ Tests grün.

---

### Schritt 3 — RED: Tests für Wizard State-Transitions und Menü

**Datei:** `tests/ui/test_camera_wizard.py` (neu, analog zu `tests/ui/test_telegram_ui.py`)

Setup-Muster: temp-DB patchen, `wizard_states` vor jedem Test leeren, `camera_pairing.start_pairing` mocken.

Tests:
1. Nach Schritt `setup_camera_interval` (text "15"): Callback `camsetup_res_VGA` → State wechselt auf `setup_camera_quality`, `state["resolution"] == "VGA"`
2. Nach Schritt `setup_camera_resolution`: Callback `camsetup_qual_high` → `camera_pairing.start_pairing` wird mit `resolution="VGA"`, `quality=10` aufgerufen, State gelöscht
3. Ungültiger Callback `camsetup_res_INVALID` → wird ignoriert (kein Absturz, kein State-Wechsel)
4. `get_main_keyboard()` enthält **nicht** mehr `🔧 Ventil koppeln` oder `📷 Kamera koppeln`
5. `get_main_keyboard()` enthält `⚙️ Setup` und `📸 Foto anzeigen`
6. Nachricht `⚙️ Setup` → `telegram_client.send_message` wird mit Inline-Keyboard aufgerufen, das `🔧 Ventil koppeln` enthält

→ Tests laufen rot.

---

### Schritt 4 — GREEN: Wizard-Schritte + Callbacks + Menü in `telegram_ui.py`

**Datei:** `src/daemon/ui/telegram_ui.py`

**4a — Neue Keyboard-Generatoren:**
```python
def get_camera_resolution_keyboard() -> dict:
    return {"inline_keyboard": [
        [{"text": "🏔 Hoch (1600×1200)", "callback_data": "camsetup_res_UXGA"},
         {"text": "⚡ Mittel (1024×768)", "callback_data": "camsetup_res_XGA"}],
        [{"text": "💨 Niedrig (640×480)", "callback_data": "camsetup_res_VGA"}],
        [{"text": "❌ Abbrechen", "callback_data": "camsetup_cancel"}]
    ]}

def get_camera_quality_keyboard() -> dict:
    return {"inline_keyboard": [
        [{"text": "🌟 Hoch", "callback_data": "camsetup_qual_high"},
         {"text": "⚡ Mittel", "callback_data": "camsetup_qual_medium"}],
        [{"text": "💨 Niedrig", "callback_data": "camsetup_qual_low"}],
        [{"text": "❌ Abbrechen", "callback_data": "camsetup_cancel"}]
    ]}
```

**4b — Wizard-Schritt `setup_camera_interval` ändern:**
Statt direkt `camera_pairing.start_pairing()` aufzurufen → State auf `"setup_camera_resolution"` setzen und Resolution-Keyboard senden.

**4c — Neue Callbacks in `_process_callback_query()`:**
- `data.startswith("camsetup_res_")`: val aus letztem Segment extrahieren, gegen `{"VGA","XGA","UXGA"}` validieren → State `step = "setup_camera_quality"`, `state["resolution"] = val`, Quality-Keyboard senden
- `data.startswith("camsetup_qual_")`: val gegen `{"high","medium","low"}` validieren → quality-Wert mappen (`high→10, medium→25, low→40`), `camera_pairing.start_pairing(...)` aufrufen, State löschen
- `data == "camsetup_cancel"`: State löschen, Abbruchmeldung
- `data == "camsetup_start"`: `handle_camera_setup(chat_id)` aufrufen
- `data == "camsetup_settings"`: Kamera-Einstellungen-Wizard starten (Intervall ändern)

**4d — Menü-Reorganisation:**
```python
def get_main_keyboard() -> dict:
    rows = [
        [{"text": "📊 Status anzeigen"}, {"text": "📅 Zeitpläne"}],
        [{"text": "🟢 Bewässern starten"}, {"text": "🔴 Sofort Stopp"}],
        [{"text": "📸 Foto anzeigen"}, {"text": "⚙️ Setup"}],
    ]
    return {"keyboard": rows, "resize_keyboard": True}
```

Neue Funktion `handle_setup_menu(chat_id)`:
```python
def handle_setup_menu(chat_id):
    telegram_client.send_message(chat_id, "⚙️ *Setup*\nWas möchtest du einrichten?", {
        "inline_keyboard": [
            [{"text": "🔧 Ventil koppeln", "callback_data": "setup_confirm"},
             {"text": "📷 Kamera koppeln", "callback_data": "camsetup_start"}],
            [{"text": "⏱ Kamera-Einstellungen", "callback_data": "camsetup_settings"}],
        ]
    })
```

Routing in `_process_message()`:
- `"⚙️ Setup"` → `handle_setup_menu(chat_id)`
- `"📸 Foto anzeigen"` statt `"📷 Foto anzeigen"` (Emoji geändert)

→ Tests grün.

---

### Schritt 5 — Firmware: Auflösung anwenden

**Datei:** `m5-GartenKamera/src/main.cpp` (separates Repo)

Im `/config`-Block, im bestehenden `if (s)` Block nach `s->set_quality()`:
```cpp
String resolution = confDoc["resolution"] | "UXGA";
framesize_t fs = FRAMESIZE_UXGA;
if (resolution == "VGA") fs = FRAMESIZE_VGA;
else if (resolution == "XGA") fs = FRAMESIZE_XGA;
s->set_framesize(s, fs);
Serial.printf("Config geladen: Sleep=%ds, Quality=%d, Resolution=%s\n",
              sleep_interval, quality, resolution.c_str());
```

Kein automatisierter Test möglich (keine Hardware-Emulation). Verifikation via Serial-Monitor.

---

## Betroffene Dateien

| Datei | Art der Änderung |
|-------|-----------------|
| `src/daemon/adapters/camera_pairing.py` | `resolution` + `quality` Parameter zu `start_pairing()` und `_pairing_worker()` |
| `src/daemon/ui/telegram_ui.py` | Neue Keyboard-Generatoren, Wizard-Steps 3+4, neue Callbacks, Menü-Reorganisation |
| `tests/adapters/test_camera_pairing.py` | 2 neue Tests |
| `tests/ui/test_camera_wizard.py` | Neue Testdatei (6 Tests) |
| `m5-GartenKamera/src/main.cpp` | `set_framesize()` nach `set_quality()` (separates Repo) |

---

## Verifikation

```powershell
# Nur neue Tests
python -m unittest tests.adapters.test_camera_pairing tests.ui.test_camera_wizard -v

# Gesamte Testsuite (Coverage darf nicht sinken)
python -m unittest discover -v tests
.\scripts\run_coverage.ps1
```

Firmware: Serial-Monitor nach Flash → Zeile `Config geladen: Sleep=..., Quality=..., Resolution=UXGA` muss erscheinen.
