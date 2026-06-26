# Plan: Getimte Kamera-Aufnahmen (Feature 0030)

## Übersicht

Rein serverseitige Erweiterung: Die Steuerzentrale berechnet Aufnahme-Zeitpunkte
(nach zeitgesteuerten Güssen + global konfigurierte Uhrzeiten) und setzt die Kamera-
Schlafdauer dynamisch. Timed-Fotos werden aktiv per Telegram zugestellt.

## Schritt 1 — Core: reines Kalkulations-Modul + neues Ereignis

**Dateien:** `src/daemon/core/camera_schedule.py` (NEU), `src/daemon/core/camera_events.py`

```python
# camera_schedule.py — keine I/O
def compute_next_sleep_seconds(
    now: datetime,
    schedules: list,          # DB-Zeilen: {time:"HH:MM", duration_minutes:int, is_active:1}
    photo_times: list,        # DB-Zeilen: {time:"HH:MM"}
    interval_seconds: int,    # obere Schlaf-Grenze der Kamera
    after_offset_minutes: int # Nach-Guss-Offset (config)
) -> int:
    """Gibt Min(interval_seconds, Sekunden_bis_nächsten_Aufnahme_Zeitpunkt) zurück.
    Berücksichtigt Zeitpunkte für die nächsten 24 h. Minimum 60 Sekunden."""

def find_matching_photo_target(
    now: datetime,
    schedules: list,
    photo_times: list,
    after_offset_minutes: int,
    tolerance_minutes: int    # config TIMED_PHOTO_TOLERANCE_MINUTES
) -> str | None:
    """Gibt die Beschriftung zurück, wenn 'now' innerhalb des Toleranzfensters
    eines Aufnahme-Zeitpunkts liegt, sonst None.
    Mehrere Treffer → nächstgelegener. Beispiele:
    '📷 Nach dem Guss um 06:00' (Guss-Zeitplan), '📷 Foto um 18:00' (absolut)."""
```

**Ereignis** in `camera_events.py`:
```python
class TimedPhotoCaptured(Event):
    def __init__(self, wish_name: str, file_path: str, caption: str): ...
```

**Tests:** `tests/core/test_camera_schedule.py`
- `compute_next_sleep_seconds` → Guss-Ziel (start+dauer+offset), absolute Uhrzeit,
  kein Ziel im Fenster → interval, Deckelung durch interval, mehrere Ziele → kleinster Wert,
  Tagesgrenze (Ziel morgen)
- `find_matching_photo_target` → innerhalb Toleranz, außerhalb, mehrere Treffer → nächster,
  kein Treffer → None, Beschriftung korrekt

---

## Schritt 2 — Config-Konstanten

**Dateien:** `config/garden.conf`, `src/daemon/config.py`

```ini
# garden.conf
TIMED_PHOTO_TOLERANCE_MINUTES=5
CAMERA_AFTER_GUSS_OFFSET_MINUTES=2
```

```python
# config.py
TIMED_PHOTO_TOLERANCE_MINUTES = int(...)  # Default 5
CAMERA_AFTER_GUSS_OFFSET_MINUTES = int(...)  # Default 2
```

---

## Schritt 3 — DB: Tabelle camera_photo_times + CRUD

**Datei:** `src/daemon/adapters/database.py`

```sql
CREATE TABLE IF NOT EXISTS camera_photo_times (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT NOT NULL UNIQUE   -- "HH:MM"
)
```

CRUD-Funktionen:
- `add_photo_time(time_str: str) -> bool` (IGNORE bei Duplikat)
- `get_photo_times() -> list[dict]` (sortiert nach time)
- `delete_photo_time(id: int) -> bool`

**Tests:** Erweiterung von `tests/adapters/test_database.py`

---

## Schritt 4 — camera_receiver: dynamische Schlafdauer + Ereignis-Veröffentlichung

**Datei:** `src/daemon/adapters/camera_receiver.py`

`handle_config` — nach Kamera-Lookup:
```python
schedules = database.get_schedules()
photo_times = database.get_photo_times()
interval = camera["sleep_duration_seconds"]
sleep_secs = camera_schedule.compute_next_sleep_seconds(
    datetime.now(), schedules, photo_times, interval,
    config.CAMERA_AFTER_GUSS_OFFSET_MINUTES
)
settings["sleep_duration_seconds"] = sleep_secs
```

`handle_upload` — nach Speichern:
```python
caption = camera_schedule.find_matching_photo_target(
    now, database.get_schedules(), database.get_photo_times(),
    config.CAMERA_AFTER_GUSS_OFFSET_MINUTES,
    config.TIMED_PHOTO_TOLERANCE_MINUTES
)
if caption and _global_bus:
    _global_bus.publish(TimedPhotoCaptured(wish_name, str(file_path), caption))
```

**Tests:** Erweiterung von `tests/adapters/test_camera_receiver.py`
- `/config` gibt dynamische Schlafdauer zurück (mit aktivem Zeitplan)
- `/upload` innerhalb Toleranz → `TimedPhotoCaptured` auf Bus
- `/upload` außerhalb Toleranz → kein Ereignis

---

## Schritt 5 — Telegram-UI: Ereignis-Handler + Wizard `/camera_times`

**Datei:** `src/daemon/ui/telegram_ui.py`

**Ereignis-Handler:**
```python
def _on_timed_photo_captured(event: TimedPhotoCaptured):
    path = Path(event.file_path)
    if not path.exists():
        return
    for uid in _allowed_user_ids:
        telegram_client.send_photo(uid, path.read_bytes(), event.caption)
```

Subscription in `subscribe_event_handlers()`:
```python
_global_bus.subscribe(TimedPhotoCaptured, _on_timed_photo_captured)
```

**Befehl `/camera_times`** — Übersicht + Verwaltung:
- Ohne gespeicherte Zeiten: kurze Info + Button „➕ Uhrzeit hinzufügen"
- Mit Zeiten: Liste + je Eintrag 🗑️-Button + „➕ Uhrzeit hinzufügen"
- Wizard (2 Schritte): Stunden-Keyboard → Minuten-Keyboard → Speichern
- Callback-Prefixe: `phtadd_h_`, `phtadd_m_`, `phtime_del_ask_`, `phtime_del_confirm_`

**Dispatcher:** `/camera_times` vor `/camera` einsortieren (analog `/photo_clear` < `/photo`)

**Tests:** `tests/ui/test_photo_times.py`
- `_on_timed_photo_captured` schickt Foto mit Beschriftung
- `/camera_times` ohne Einträge
- `/camera_times` mit Einträgen
- Wizard: Stunde → Minute → Speichern
- Löschen (mit Rückfrage)
- Kein Menü-Button (Feature-Spec: out of scope)

---

## Schritt 6 — Wiring in main.py

- Menü-Eintrag `/camera_times` hinzufügen
- `subscribe_event_handlers()` enthält bereits neues Abo (aus Schritt 5)

---

## Schritt 7 — telegram-nachrichten.html

- Neue Karte: getimtes Foto mit Beschriftung (zwei Varianten: nach Guss / absolut)
- Neue Karte: `/camera_times`-Übersicht (ohne Zeiten / mit Zeiten)
- Neue Karte: Wizard-Dialog (Stunden- / Minuten-Auswahl / Bestätigung)

---

## Reihenfolge-Rationale

Core-Funktionen zuerst (keine I/O → schnelle TDD-Schleife), dann DB (Voraussetzung für
adapter), dann adapter, dann UI. Jeder Schritt: RED → GREEN → REFACTOR, dann volle
Test-Suite.
