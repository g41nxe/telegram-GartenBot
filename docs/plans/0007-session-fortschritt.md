# Feature 0006 — Mehrfach-Ventil-Unterstützung: Sessionfortschritt

**Datum:** 2026-06-12  
**Teststand:** 75/75 grün, 3 skipped  
**Schritte abgeschlossen:** 1–6 von 9  
**Schritte offen:** 7 (scheduler), 8 (daily_report), 9 (telegram_ui)

---

## Was bisher implementiert wurde

### Schritt 1 — `src/daemon/adapters/database.py`
- Neue Tabellen `valves` und `schedule_valves` in `init_db()`.
- Neue Spalten via `ALTER TABLE` + `try/except OperationalError` (bestehende Deployments):
  - `schedules.execution_mode TEXT DEFAULT 'sequential'`
  - `watering_history.valve_id INTEGER`
  - `device_status_log.device_name TEXT`
- Datenmigration: Standard-Ventil `id=1, wish_name="Ventil", mqtt_name="garden_valve"` anlegen; bestehende `schedules` in `schedule_valves` verknüpfen; bestehende `watering_history`- und `device_status_log`-Zeilen auf `valve_id=1` bzw. `device_name="garden_valve"` setzen.
- Geänderte Signaturen:
  - `log_device_status(device_name: str, battery: int, linkquality: int)`
  - `get_device_status_stats_last_24h(device_name: str) -> dict`
- Neue CRUD-Funktionen: `get_all_valves`, `get_valve_by_id`, `get_valve_by_mqtt_name`, `add_valve`, `update_valve_status`, `get_schedule_valves`, `set_schedule_valves`

### Schritt 2 — `src/daemon/core/valve_events.py`
`ValveStatusReported` hat `mqtt_name: str` als **erstes** Pflichtargument:
```python
class ValveStatusReported(Event):
    def __init__(self, mqtt_name: str, state: str, flow_rate: float,
                 battery: int, linkquality: int, valve_abnormal_state: str = "normal"):
        self.mqtt_name = mqtt_name
        # ...
```

### Schritt 3 — `src/daemon/adapters/mqtt_client.py`
Drei Stellen feuern jetzt `ValveStatusReported(mqtt_name, ...)`:
- `PahoMqttAdapter._on_message`: `mqtt_name = msg.topic.split("/")[-1]`
- `SimulatedMqttAdapter.publish`: `mqtt_name = topic.split("/")[1] if topic.count("/") >= 2 else "garden_valve"`
- `SimulatedMqttAdapter._simulation_loop`: hardcoded `"garden_valve"` (Single-Ventil-Sim)

Das globale `valve_status`-Dict und die alte `on_message`-Funktion bleiben für Abwärtskompatibilität erhalten.

### Schritt 4 — `src/daemon/adapters/pairing.py`
- `start_pairing(chat_id, notify_fn, wish_name: str)` — `wish_name` ist neuer Pflichtparameter.
- Nach IEEE-Beitritt: `mqtt_name = f"valve_{ieee[-4:]}"` (z. B. `valve_3a1f`)
- Gerät in Z2M via `bridge/request/device/rename` umbenennen.
- `database.add_valve(wish_name, mqtt_name)` aufrufen.
- `mqtt_client.client_instance.subscribe(f"zigbee2mqtt/{mqtt_name}")` aufrufen.
- `VALVE_NAME = "garden_valve"` hardcode entfernt.

### Schritt 5 — `src/daemon/adapters/database_adapter.py`
```python
def _on_valve_status_reported(self, event: ValveStatusReported):
    database.log_device_status(event.mqtt_name, event.battery, event.linkquality)
```
**Noch offen:** `database.update_valve_status(event.mqtt_name, ...)` wird hier noch nicht aufgerufen (in DB schon implementiert, aber die Verdrahtung fehlt). Dies kann in Schritt 5 nachgeholt oder mit Schritt 7 kombiniert werden.

### Schritt 6 — `src/daemon/core/watering_controller.py`
Vollständig auf Multi-Ventil umgebaut:
```python
# Alt:
self._active_cycle: Optional[Dict[str, Any]] = None
self._last_flow_update_time: Optional[datetime] = None

# Neu:
self._active_cycles: Dict[str, Dict[str, Any]] = {}
self._last_flow_update_time: Dict[str, Optional[datetime]] = {}
```

Geänderte/neue Methoden:
- `start_watering(duration_minutes, target_volume_liters, source, mqtt_name="garden_valve", valve_topic=None)` — `valve_topic` defaults zu `f"zigbee2mqtt/{mqtt_name}"`
- `stop_watering(mqtt_name=None)` — None stoppt alle aktiven Zyklen
- `get_active_cycle(mqtt_name=None)` — None gibt erstes aktives zurück
- `get_active_volume(mqtt_name=None)` — None gibt erstes aktives zurück
- `_integrate_flow(flow_rate, elapsed_seconds, mqtt_name="garden_valve")`
- `_on_valve_status_reported(event)` — filtert: `if mqtt_name not in self._active_cycles: return`
- `_time_limit_callback(mqtt_name="garden_valve", valve_topic=None)` — per `Timer(args=(mqtt_name, valve_topic))`

---

## Neue/geänderte Testdateien

| Datei | Was |
|-------|-----|
| `tests/adapters/test_database.py` | NEU — 20 Tests für Schema-Migration und alle CRUD-Funktionen |
| `tests/adapters/test_pairing.py` | Umgeschrieben — `wish_name` in allen Calls, Test für DB-Schreiben |
| `tests/adapters/test_mqtt_client.py` | `event.mqtt_name`-Assertions in bestehenden Tests ergänzt |
| `tests/core/test_watering_controller.py` | 5 neue Multi-Ventil-Tests (Zeilen 101–180) |
| `tests/test_irrigation.py` | test_05/08: `_active_cycle` → `_active_cycles["garden_valve"]`; test_09: `stop_watering()`-Guard + `valve_status["state"] = "OFF"` gegen Race-Condition |

---

## Bekannte technische Details / Gotchas

1. **Race-Condition in test_09:** `SimulatedMqttAdapter._simulation_loop` läuft in eigenem Thread und feuert jede Sekunde `ValveStatusReported`. Wenn `_last_flow_update_time` künstlich auf `now - 75s` gesetzt wird, kann der Loop zwischen Setzen und Publish das 75s-Fenster konsumieren. Fix: `mqtt_client.valve_status["state"] = "OFF"` setzt den Loop auf inaktiv während der kritischen Sektion.

2. **`daily_report.py` ist ein Übergangszustand:** `get_device_status_stats_last_24h("garden_valve")` und `mqtt_client.get_valve_status()` sind noch auf das erste Ventil hardcoded. Schritt 8 ersetzt das durch eine `get_all_valves()`-Schleife.

3. **`scheduler.py` Fassade:** `start_watering(duration, volume, source)` delegiert an `controller.start_watering(duration, volume, source)` mit Default-`mqtt_name="garden_valve"`. Schritt 7 erweitert dies um Ventil-Lookup aus der DB.

4. **`telegram_ui.py` ruft `pairing.start_pairing(chat_id, notify_fn)` ohne `wish_name`:** Schritt 9 ergänzt den Wizard-Schritt, der den Namen abfragt.

5. **`database_adapter.py` fehlt `update_valve_status`-Call:** In `_on_valve_status_reported` wird `log_device_status` aufgerufen, aber `update_valve_status` (aktualisiert Batterie/LQI im `valves`-Eintrag) noch nicht. Kann mit Schritt 7 nachgeholt werden.

---

## Offene Schritte

### Schritt 7 — `src/daemon/scheduler.py`

**TDD: zuerst Tests in `tests/test_irrigation.py` schreiben.**

Änderungen:
- `_trigger_scheduled_watering(sched)`: Ventile aus DB laden via `database.get_schedule_valves(sched["id"])`. Falls leer → Standard-Ventil `garden_valve` nutzen.
- **Sequentieller Modus:** Queue als `list[dict]` (Ventil-Objekte). Erstes Ventil starten, dann `WateringCycleCompleted` einmalig abonnieren und beim Event das nächste aus der Queue starten. Bei leerer Queue: Subscription deregistrieren.
- **Paralleler Modus** (`execution_mode == "parallel"`): Alle Ventile gleichzeitig via `controller.start_watering(...)` starten — eine Schleife.
- `check_startup_safety()`: Alle Ventile aus DB iterieren, für jedes `mqtt_client.get_valve_status(mqtt_name)` abfragen (sobald `get_valve_status` multi-valve-fähig ist, bis dahin Fallback auf aktuelle Methode).
- Fassaden-Methode `start_watering` kann vorerst unverändert bleiben.

Skelett für sequentielle Übergabe:
```python
def _trigger_scheduled_watering(sched: dict):
    valve_ids = database.get_schedule_valves(sched["id"])
    valves = [database.get_valve_by_id(vid) for vid in valve_ids]
    if not valves:
        # Fallback: Standard-Ventil
        valves = [{"mqtt_name": "garden_valve", "wish_name": "Ventil"}]

    execution_mode = sched.get("execution_mode", "sequential")

    if execution_mode == "parallel":
        for valve in valves:
            _start_single_valve(valve, sched)
    else:
        _start_sequential(list(valves), sched)

def _start_sequential(queue: list, sched: dict):
    if not queue:
        return
    valve = queue.pop(0)
    success, msg = _start_single_valve(valve, sched)
    if success and queue:
        from .core.watering_controller import WateringCycleCompleted, WateringCycleFailed
        def on_completed(event):
            _global_bus.unsubscribe(WateringCycleCompleted, on_completed)
            _global_bus.unsubscribe(WateringCycleFailed, on_completed)
            _start_sequential(queue, sched)
        _global_bus.subscribe(WateringCycleCompleted, on_completed)
        _global_bus.subscribe(WateringCycleFailed, on_completed)

def _start_single_valve(valve: dict, sched: dict) -> tuple[bool, str]:
    duration = sched.get("duration_minutes", 10)
    volume = sched.get("target_volume_liters", 0)
    name = sched.get("name", "Zeitplan")
    mqtt_name = valve["mqtt_name"]
    valve_topic = f"zigbee2mqtt/{mqtt_name}"
    return controller.start_watering(duration, volume, "schedule", mqtt_name=mqtt_name, valve_topic=valve_topic)
```

### Schritt 8 — `src/daemon/adapters/daily_report.py`

**TDD: zuerst Tests in `tests/test_irrigation.py` oder `tests/adapters/test_daily_report.py` schreiben.**

Änderungen in `generate_daily_report`:
```python
# Aktuell (Übergangszustand):
status = mqtt_client.get_valve_status()
conn_stats = database.get_device_status_stats_last_24h("garden_valve")

# Neu: alle Ventile iterieren
valves = database.get_all_valves()
valve_sections = []
for valve in valves:
    mqtt_name = valve["mqtt_name"]
    wish_name = valve["wish_name"]
    status = mqtt_client.get_valve_status()  # TODO: multi-valve nach Schritt 3-Erweiterung
    conn_stats = database.get_device_status_stats_last_24h(mqtt_name)
    # ... Warnungen + Verbindungssektion pro Ventil generieren
    valve_sections.append(f"**{wish_name}** ({mqtt_name}): ...")
```

Außerdem `database_adapter.py` ergänzen:
```python
def _on_valve_status_reported(self, event: ValveStatusReported):
    now = datetime.now()
    database.log_device_status(event.mqtt_name, event.battery, event.linkquality)
    database.update_valve_status(
        event.mqtt_name, event.battery, event.linkquality,
        now.isoformat(), event.valve_abnormal_state
    )
```

### Schritt 9 — `src/daemon/ui/telegram_ui.py`

**TDD: manuell via Simulation testen (Telegram-Bot hat keine Unit-Tests, da I/O-heavy).**

Änderungen:
- **`/setup`-Handler**: Vor `pairing.start_pairing()` nach dem Wunschnamen fragen. Wizard-Zustand `{"step": "await_wish_name"}` in der bestehenden `_pending_wizard`-State-Machine eintragen.
  ```python
  # Neuer Wizard-Schritt vor Kopplung:
  # 1. User drückt "🔧 Ventil koppeln"
  # 2. Bot: "Wie soll das neue Ventil heißen? (z. B. Rasen, Terrasse)"
  # 3. User antwortet mit Namen
  # 4. Bot startet pairing.start_pairing(chat_id, notify_fn, wish_name=user_text)
  ```
- **`/status`-Handler**: Alle Ventile per `database.get_all_valves()` ausgeben statt hardcoded.
- **Manueller Start-Wizard**: Wenn >1 Ventil in DB → Auswahlschritt per Inline-Keyboard; bei 1 Ventil wie bisher direkt.
- **Hauptmenü-Tastatur**: `"🔧 Ventil koppeln"` immer anzeigen (nicht nur wenn kein Ventil vorhanden).

---

## Startpunkt für die nächste Session

```
Tests laufen: python -m unittest discover tests
Stand: 75/75 grün, 3 skipped
Nächster Schritt: Schritt 7 (scheduler.py)
TDD-Reihenfolge: erst fehlschlagende Tests für sequentielle Multi-Ventil-Planung schreiben,
                 dann _trigger_scheduled_watering + _start_sequential implementieren
```
