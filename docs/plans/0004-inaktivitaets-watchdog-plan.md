# Implementierungsplan: Inaktivitäts-Watchdog (Ventil-Überwachung)

Dieser Plan beschreibt die zu ändernden Dateien für die Implementierung der Ventil-Inaktivitätsüberwachung. Grundlage sind die Entscheidungen aus der Grill-Session (Feature 0005) und ADR-0018.

## Design-Entscheidungen (Zusammenfassung)

- **Scope:** Nur Ventile. Der Füllstandssensor wird in Feature 0003 nachgezogen.
- **Neues Modul `adapters/watchdog.py`:** Enthält die gesamte Watchdog-Logik. Der Scheduler ruft `run_watchdog_check()` stündlich in einem eigenen Thread auf (analog zur Wetter-Hintergrundabfrage). Die Funktion `initialize(event_bus)` wird einmalig in `main.py` aufgerufen.
- **Sofortige Entwarnung:** `watchdog.py` abonniert `ValveStatusReported` dauerhaft auf Modulebene. Sendet ein Ventil wieder ein Signal, wird `InactivityAlertResolved` sofort publiziert — nicht erst beim nächsten stündlichen Check.
- **`last_update IS NULL` → überspringen:** Frisch gekoppelte Ventile ohne erstes Signal lösen keinen Alert aus.
- **Tagesbericht:** Aktive Watchdog-Flags erscheinen als Warnzeile im Tagesbericht.
- **Referenz:** ADR-0018, ADR-0016, ADR-0014.

---

## Proposed Changes

### 1. Konfiguration

#### [MODIFY] [.env.template](file:///c:/Users/g41nx/Repositories/garden/.env.template)
```env
# --- Inaktivitäts-Watchdog ---
WATCHDOG_ENABLED=true
WATCHDOG_VALVE_TIMEOUT_HOURS=24
```

#### [MODIFY] [config.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/config.py)
Neue Konstanten:
```python
WATCHDOG_ENABLED = os.getenv("WATCHDOG_ENABLED", "true").lower() == "true"
WATCHDOG_VALVE_TIMEOUT_HOURS = float(os.getenv("WATCHDOG_VALVE_TIMEOUT_HOURS", "24"))
```

---

### 2. Event-Typen

#### [NEW] [core/watchdog_events.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/core/watchdog_events.py)
```python
from .event_bus import Event

class InactivityAlertTriggered(Event):
    def __init__(self, device_name: str, valve_id: int, hours_silent: float, timeout_hours: int): ...

class InactivityAlertResolved(Event):
    def __init__(self, device_name: str, valve_id: int): ...
```

Platzierung in `core/` folgt dem Muster von `core/valve_events.py`, damit `telegram_ui.py` importieren kann ohne einen Adapter zu referenzieren.

---

### 3. Watchdog-Adapter

#### [NEW] [adapters/watchdog.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/adapters/watchdog.py)

Zwei öffentliche Funktionen:

**`initialize(event_bus)`** — beim Daemon-Start einmalig aufrufen:
- Prüft `config.WATCHDOG_ENABLED`; bei `false` sofortiger Rücksprung ohne Abonnements.
- Registriert dauerhaften Modulebene-Listener auf `ValveStatusReported` (ADR-0016: kein `unsubscribe()` nötig).
- Der Listener prüft für das eingetroffene Ventil, ob `watchdog_alert_active_valve_<id> == "1"` in `system_metadata` gesetzt ist. Falls ja: Flag auf `"0"` setzen, `InactivityAlertResolved` publizieren.

**`run_watchdog_check()`** — stündlich in einem Daemon-Thread aufrufen (kein `event_bus`-Argument — `_global_bus` wird wie in allen anderen Adaptern auf Modulebene aus `mqtt_client` importiert):
- Prüft `config.WATCHDOG_ENABLED`; bei `false` sofortiger Rücksprung.
- Lädt alle Ventile via `database.get_all_valves()`.
- Pro Ventil:
  - `last_update IS NULL` → überspringen.
  - Zeitdifferenz zu `datetime.now()` berechnen.
  - Differenz > `WATCHDOG_VALVE_TIMEOUT_HOURS` **und** Flag nicht gesetzt → Flag auf `"1"` setzen, `InactivityAlertTriggered` publizieren.
  - Differenz ≤ `WATCHDOG_VALVE_TIMEOUT_HOURS` **und** Flag gesetzt → Flag auf `"0"` setzen, `InactivityAlertResolved` publizieren.
    *(Absicherung für den Fall, dass das Ventil zwischen zwei Watchdog-Checks reaktiviert wurde, ohne dass `ValveStatusReported` gefeuert wurde — z.B. nach einem Daemon-Neustart.)*

---

### 4. Scheduler

#### [MODIFY] [scheduler.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/scheduler.py)

Import hinzufügen:
```python
from .adapters import watchdog
```

In `_scheduler_loop()` denselben `time.time()`-Guard wie für die Wetter-Hintergrundabfrage einführen:
```python
last_watchdog_check = 0.0

# In der Loop:
if current_timestamp - last_watchdog_check >= 3600:
    last_watchdog_check = current_timestamp
    t_watchdog = threading.Thread(
        target=watchdog.run_watchdog_check, daemon=True
    )
    t_watchdog.start()
```

---

### 5. Daemon-Start

#### [MODIFY] [main.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/main.py)

Nach MQTT-Client- und EventBus-Initialisierung:
```python
from .adapters import watchdog
watchdog.initialize(_global_bus)
```

---

### 6. Präsentationsschicht

#### [MODIFY] [telegram_ui.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/ui/telegram_ui.py)

Modulebene-Listener für beide Watchdog-Events registrieren:

```python
# Warnung
def _on_inactivity_alert(event: InactivityAlertTriggered):
    msg = (f"⚠️ *Verbindung verloren:* Ventil \"{event.device_name}\" "
           f"hat seit {event.hours_silent:.1f} Stunden kein Signal gesendet.")
    telegram_client.broadcast_notification(msg)

# Entwarnung
def _on_inactivity_resolved(event: InactivityAlertResolved):
    msg = f"🟢 *Verbindung wiederhergestellt:* Ventil \"{event.device_name}\" sendet wieder Signale."
    telegram_client.broadcast_notification(msg)

_global_bus.subscribe(InactivityAlertTriggered, _on_inactivity_alert)
_global_bus.subscribe(InactivityAlertResolved, _on_inactivity_resolved)
```

---

### 7. Tagesbericht

#### [MODIFY] [adapters/daily_report.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/adapters/daily_report.py)

In `generate_daily_report()` aktive Watchdog-Flags auslesen und als Warnzeile ergänzen:

```python
# Alle Ventile mit aktivem Watchdog-Flag laden
for valve in database.get_all_valves():
    flag_key = f"watchdog_alert_active_valve_{valve['id']}"
    if database.get_metadata(flag_key) == "1":
        report_lines.append(f"🔴 *Watchdog-Warnung:* Ventil \"{valve['wish_name']}\" ist inaktiv.")
```

---

### 8. Datenbankzugriffe

Keine neuen DB-Funktionen erforderlich — folgende bestehende Funktionen werden genutzt:
- `database.get_all_valves()` — alle Ventile inkl. `last_update` und `wish_name`
- `database.get_valve_by_mqtt_name(mqtt_name)` — Lookup im `ValveStatusReported`-Handler
- `database.get_metadata(key)` / `database.set_metadata(key, value)` — Flag-Verwaltung

Die Spalte `device_name` in `device_status_log` ist bereits durch Feature 0006 vorhanden. Keine Migration erforderlich.

---

## Verification Plan

### Automatisierte Tests (`tests/test_watchdog.py`)

| Szenario | Erwartung |
|---|---|
| Ventil mit `last_update` vor > 24h, kein Flag | `InactivityAlertTriggered` wird publiziert, Flag auf `"1"` gesetzt |
| Ventil mit aktivem Flag, erneuter Check nach > 24h | Kein zweites `InactivityAlertTriggered` (Spam-Schutz) |
| `ValveStatusReported` für Ventil mit aktivem Flag | Sofortiges `InactivityAlertResolved`, Flag auf `"0"` gesetzt |
| Ventil mit `last_update IS NULL` | Kein Event, kein Flag |
| `WATCHDOG_ENABLED=false` | Kein Event, keine Abonnements |
| Mehrere Ventile, eines inaktiv | Nur für das inaktive Ventil wird Alert ausgelöst |

### Manuelle Verifikation

1. `WATCHDOG_VALVE_TIMEOUT_HOURS=0.01` in `.env` setzen (≈ 36 Sekunden).
2. Daemon starten, auf `InactivityAlertTriggered`-Warnung in Telegram warten.
3. Künstliche MQTT-Nachricht für das Ventil senden → `InactivityAlertResolved`-Entwarnung prüfen.
4. Tagesbericht per `/report` abrufen → Warnzeile für inaktives Ventil prüfen.
