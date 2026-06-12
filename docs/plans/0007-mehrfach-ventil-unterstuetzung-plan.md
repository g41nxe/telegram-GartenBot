# Implementierungsplan: Multi-Ventil-Unterstützung und flexible Zeitpläne

Wir erweitern das Gartenbewässerungs-System um die Unterstützung mehrerer Ventile. Die Ventile können dynamisch über den Bot registriert, Zeitplänen zugewiesen und manuell oder automatisch (sequentiell/parallel) bewässert werden.

## Design-Entscheidungen

- **Sequentieller Modus:** Der Scheduler verwaltet die Ventil-Warteschlange extern. Er abonniert `WateringCycleCompleted` und startet das nächste Ventil, sobald das aktuelle fertig ist. Der `WateringController` selbst bleibt zustandslos bezüglich Sequenzen — er steuert immer nur einen aktiven Zyklus pro Ventil.
- **Event-Identifikation:** `ValveStatusReported` erhält das Feld `mqtt_name: str`, damit der Controller und der DB-Adapter das Event dem richtigen Ventil zuordnen können.
- **API-Abwärtskompatibilität:** `mqtt_client.get_valve_status(mqtt_name: str = None)` gibt ohne Argument den Status des ersten/Standard-Ventils zurück. Bestehende Aufrufer bleiben kurzfristig kompatibel und werden schrittweise migriert.
- **Dynamischer MQTT-Name bei Kopplung:** Beim Koppeln wird der `mqtt_name` als `valve_<letzte 4 IEEE-Stellen>` generiert (z. B. `valve_1122`). Der Wunschname (`wish_name`) ist der benutzerfreundliche Anzeigename.

---

## Proposed Changes

### 1. Datenbank (Database Schema & Migration)
#### [MODIFY] [database.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/adapters/database.py)
* **Tabelle `valves`**: Neu anlegen.
  ```sql
  CREATE TABLE IF NOT EXISTS valves (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      wish_name TEXT NOT NULL,
      mqtt_name TEXT NOT NULL UNIQUE,
      is_paired INTEGER DEFAULT 1,
      battery INTEGER DEFAULT 100,
      linkquality INTEGER DEFAULT 0,
      last_update TEXT,
      valve_abnormal_state TEXT DEFAULT 'normal'
  )
  ```
* **Tabelle `schedule_valves`**: Neu anlegen (n-zu-m zwischen `schedules` und `valves`).
  ```sql
  CREATE TABLE IF NOT EXISTS schedule_valves (
      schedule_id INTEGER NOT NULL,
      valve_id INTEGER NOT NULL,
      PRIMARY KEY (schedule_id, valve_id)
  )
  ```
* **Tabelle `schedules`**: Spalte `execution_mode TEXT DEFAULT 'sequential'` hinzufügen.
* **Tabelle `watering_history`**: Spalte `valve_id INTEGER` hinzufügen.
* **Tabelle `device_status_log`**: Spalte `device_name TEXT` hinzufügen.
* **Migrationen (in `init_db()`):**
  * Wenn `valves`-Tabelle fehlt: anlegen und Standard-Ventil eintragen (`id=1`, `wish_name="Ventil"`, `mqtt_name="garden_valve"`, `is_paired=1`).
  * Alle bestehenden Zeitpläne mit `valve_id=1` in `schedule_valves` verknüpfen.
  * Bestehende `watering_history`-Einträge ohne `valve_id` auf `valve_id=1` setzen.
  * Bestehende `device_status_log`-Einträge ohne `device_name` auf `device_name="garden_valve"` setzen.
* **Neue CRUD-Funktionen:**
  * `get_all_valves() -> list[dict]`
  * `get_valve_by_id(valve_id: int) -> dict | None`
  * `get_valve_by_mqtt_name(mqtt_name: str) -> dict | None`
  * `add_valve(wish_name: str, mqtt_name: str) -> int`
  * `update_valve_status(mqtt_name: str, battery: int, linkquality: int, last_update: str, valve_abnormal_state: str)`
  * `get_schedule_valves(schedule_id: int) -> list[int]` (gibt Valve-IDs zurück)
  * `set_schedule_valves(schedule_id: int, valve_ids: list[int])`
  * `get_device_status_stats_last_24h(device_name: str) -> dict` (ergänzt `device_name`-Filter)
  * `log_device_status(device_name: str, battery: int, linkquality: int)` (Signatur erweitern)

---

### 2. Valve Events
#### [MODIFY] [valve_events.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/core/valve_events.py)
* `ValveStatusReported` erhält neues Pflichtfeld `mqtt_name: str` als erstes Argument.
  ```python
  class ValveStatusReported(Event):
      def __init__(self, mqtt_name: str, state: str, flow_rate: float, battery: int, linkquality: int, valve_abnormal_state: str = "normal"):
  ```

---

### 3. MQTT-Client (Adapter-Ebene)
#### [MODIFY] [mqtt_client.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/adapters/mqtt_client.py)
* Ersetzt `valve_status: dict` durch `valves_status: Dict[str, Dict[str, Any]]` (indiziert nach `mqtt_name`).
* Beim Verbindungsaufbau: liest alle Ventile aus der DB und abonniert deren Topics dynamisch (`zigbee2mqtt/{mqtt_name}`).
* `get_valve_status(mqtt_name: str = None) -> dict`: Ohne Argument gibt der erste Eintrag (Abwärtskompatibilität). Mit Argument gibt den spezifischen Ventilstatus.
* `open_valve(mqtt_name: str)` und `close_valve(mqtt_name: str)` nehmen den Topic-Namen entgegen.
* `request_valve_status(mqtt_name: str = None)`: Optional für einzelnes Ventil oder alle.
* `ValveStatusReported` wird mit `mqtt_name` gefeuert.
* Statisches `config.MQTT_VALVE_TOPIC` wird nur noch für die Standard-Migrations-Fallback-Kopplung genutzt; alle aktiven Topics kommen aus der DB.

---

### 4. Ventil-Kopplung
#### [MODIFY] [pairing.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/adapters/pairing.py)
* `start_pairing(chat_id: int, notify_fn, wish_name: str)` erhält den Wunschnamen als Parameter.
* Nach erfolgreichem Beitritt: `mqtt_name = f"valve_{ieee_address[-4:]}"` berechnen.
* Gerät in Zigbee2MQTT auf `mqtt_name` umbenennen.
* Neues Ventil per `database.add_valve(wish_name, mqtt_name)` in DB anlegen.
* Client-Adapter anweisen, das neue Topic zu abonnieren (via `client_instance.subscribe()`).
* Hardcoded `VALVE_NAME = "garden_valve"` entfernen.

---

### 5. Datenbank-Adapter
#### [MODIFY] [database_adapter.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/adapters/database_adapter.py)
* `_on_valve_status_reported`: Übergibt `event.mqtt_name` an `database.log_device_status(event.mqtt_name, event.battery, event.linkquality)`.
* Zusätzlich: `database.update_valve_status(event.mqtt_name, event.battery, event.linkquality, now.isoformat(), event.valve_abnormal_state)` aufrufen.

---

### 6. Guss-Steuerung (Watering Controller & Events)
#### [MODIFY] [watering_controller.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/core/watering_controller.py)
* `_active_cycle: Optional[dict]` → `_active_cycles: Dict[str, dict]` (indiziert nach `mqtt_name`).
* `start_watering(duration_minutes, target_volume_liters, source, mqtt_name: str, valve_topic: str)`: Neues Ventil-spezifisches Interface.
  * Baut das MQTT-Topic dynamisch aus `valve_topic` statt `config.MQTT_VALVE_TOPIC`.
  * Integriert den Flow nur für Events, deren `event.mqtt_name == mqtt_name`.
* `stop_watering(mqtt_name: str = None)`: Stoppt ein bestimmtes oder alle aktiven Zyklen.
* `get_active_cycle(mqtt_name: str = None)`: Gibt Zyklus-Info für ein Ventil zurück.
* Domain-Events (`WateringCycleStarted`, `WateringCycleCompleted`, `WateringCycleFailed`, `WateringCycleStopped`) erhalten das Feld `valve_id: int` und `valve_name: str` für ventilgenaue Benachrichtigungen.
* `_on_valve_status_reported` filtert nach `event.mqtt_name`.

---

### 7. Scheduler (Zeitsteuerung)
#### [MODIFY] [scheduler.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/scheduler.py)
* `_trigger_scheduled_watering(sched)`: Liest per `database.get_schedule_valves(sched["id"])` die zugewiesenen Ventile.
* **Paralleler Modus (`execution_mode = "parallel"`):** Startet alle Ventile gleichzeitig über `controller.start_watering(...)` pro Ventil.
* **Sequentieller Modus (`execution_mode = "sequential"`):** Startet das erste Ventil; abonniert einmalig `WateringCycleCompleted` und startet beim Empfang das nächste Ventil aus der Queue. Deregistriert sich, sobald die Queue leer ist.
* `check_startup_safety()`: Iteriert alle Ventile aus der DB und prüft jeden Zustand.
* `start_watering(duration, volume, source)`: Fasaden-Methode bleibt für manuelle Einzel-Ventil-Aufrufe, ergänzt um optionales `valve_ids: list[int] = None` und `execution_mode: str = "sequential"`.

---

### 8. Täglicher Statusbericht
#### [MODIFY] [daily_report.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/adapters/daily_report.py)
* Iteriert alle Ventile per `database.get_all_valves()`.
* Fragt für jedes Ventil `mqtt_client.get_valve_status(valve["mqtt_name"])` ab.
* Gibt Batterie, LQI und letzten Zeitstempel pro Ventil aus.
* `get_device_status_stats_last_24h(device_name)` wird pro Ventil aufgerufen.
* `get_watering_stats_last_24h()` bleibt global (Gesamtstatistik); kann später nach `valve_id` aufgesplittet werden (Out of Scope).

---

### 9. Telegram-Bot Benutzeroberfläche
#### [MODIFY] [telegram_ui.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/ui/telegram_ui.py)
* **Kopplungs-Assistent (`/setup`)**: Fragt vor dem Start nach dem Wunschnamen des Ventils; übergibt `wish_name` an `pairing.start_pairing()`.
* **Zeitplan-Assistent (`/zeitplan`)**:
  * Neuer Schritt: Multi-Select-Keyboard zur Ventilauswahl (Toggle mit ✅). *Wird übersprungen, falls nur 1 Ventil registriert ist.*
  * Neuer Schritt: Auswahl Ausführungsmodus (sequentiell/parallel), falls >1 Ventil gewählt. *Wird übersprungen, falls nur 1 Ventil.*
* **Manueller Start (`🟢 Bewässern starten`)**: Analog zum Zeitplan-Assistenten.
* **Statusanzeige (`/status`)**: Listet alle registrierten Ventile einzeln auf (Zustand, Batterie, LQI, letztes Signal).
* **Hauptmenü-Tastatur**: Zeigt `"🔧 Ventil koppeln"` immer an (nicht nur wenn kein Ventil gekoppelt ist), da mehrere Ventile möglich sind.

---

## Implementierungsreihenfolge

```
1. database.py           — Schema + Migrationen + CRUD (Basis für alles)
2. valve_events.py       — mqtt_name zu ValveStatusReported hinzufügen
3. mqtt_client.py        — Multi-Dict, dynamische Topics, API-Compat
4. pairing.py            — wish_name + dynamischer mqtt_name + DB-Schreiben
5. database_adapter.py   — device_name + valve_status weiterleiten
6. watering_controller.py — _active_cycles mit mqtt_name-Filterung
7. scheduler.py          — schedule_valves lesen, sequentielle Übergabe via EventBus
8. daily_report.py       — pro Ventil iterieren
9. telegram_ui.py        — Ventilauswahl-Wizard, Status-Anzeige
```

TDD-Regel: Für jede Schicht zuerst einen fehlschlagenden Test schreiben, dann implementieren.

---

## Verification Plan

### Automated Tests
* **`tests/adapters/test_database.py`** (neu): Schema-Migration, CRUD für `valves`, `schedule_valves`.
* **`tests/core/test_watering_controller.py`**: Erweitern um Multi-Ventil-Szenarien (parallele Zyklen, mqtt_name-Filterung).
* **`tests/test_irrigation.py`**: Sequentielle Bewässerung, Einzelventil-Kompatibilität.
* **`tests/adapters/test_pairing.py`**: Kopplung mit wish_name, DB-Schreiben.

### Manual Verification
* Simulation des Telegram-Dialogs zur Erstellung eines Multi-Ventil-Zeitplans.
* Validierung des Ein-Ventil-Modus (kein zusätzlicher Auswahlschritt).
* Validierung von `/status` und `/report` mit zwei registrierten Ventilen.
