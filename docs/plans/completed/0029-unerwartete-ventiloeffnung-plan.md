# Unerwartete Ventilöffnung — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Erkennen, wenn ein Ventil ohne aktiven Guss geöffnet wird (Unerwartete Ventilöffnung), und den Benutzer per Telegram-Bot benachrichtigen (Push). Der Daemon schließt das Ventil **nicht** (Hardware-Sicherheits-Timeout ist der Flutschutz). Siehe Feature 0029 und ADR 0032.

**Architecture:** Die Erkennung lebt in der Guss-Steuerung (`WateringController`, Core), die `ValveStatusReported` bereits verarbeitet und die aktiven Zyklen kennt. Sie hält pro Ventil im Speicher den zuletzt gemeldeten Zustand und ein Episode-Flag, erkennt flankengesteuert den Übergang *Nicht-ON → ON ohne aktiven Zyklus* und veröffentlicht `UnexpectedValveOpened` / `UnexpectedValveResolved` über den Ereignis-Kanal. Der Telegram-Bot (UI) abonniert die Ereignisse, löst den `wish_name` aus der DB auf und benachrichtigt. Abschaltbar via `UNEXPECTED_VALVE_ALERT_ENABLED`.

**Tech Stack:** Python 3.11, EventBus (synchron), SQLite, stdlib Telegram-Client, unittest + pytest.

**Schlüssel-Invarianten (aus dem Grill, ADR 0032):**
- Nur melden, nicht schließen.
- Flankenerkennung (keine Karenz-Konstante); reguläres Daemon-Schließen erzeugt keinen Fehlalarm.
- Cold-Start-Regel: bei unbekanntem letztem Zustand (None) **nicht** melden → kein Doppelfeuer mit `check_startup_safety()`.
- Ereignisse publizieren **außerhalb** des Locks (EventBus ist synchron, Re-Entrancy vermeiden).
- Episode-Flag im Speicher, nicht DB-persistiert.

---

### Task 1: Domänen-Ereignisse + Konfigurations-Schalter

**Files:**
- Modify: `src/daemon/core/valve_events.py`
- Modify: `src/daemon/config.py`
- Modify: `config/garden.conf`
- Test: `tests/core/test_watering_controller.py` (Import-Smoke), `tests/test_irrigation.py` (Config-Default)

- [ ] **Step 1: Failing test (Config-Default)**

In `tests/test_irrigation.py` bei den Config-Default-Assertions ergänzen:

```python
self.assertTrue(config.UNEXPECTED_VALVE_ALERT_ENABLED)
```

- [ ] **Step 2: Test ausführen — muss fehlschlagen** (`AttributeError`).

- [ ] **Step 3: Ereignisse ergänzen** in `src/daemon/core/valve_events.py`:

```python
class UnexpectedValveOpened(Event):
    """Ein Ventil wurde ohne aktiven Guss geöffnet (Unerwartete Ventilöffnung)."""
    def __init__(self, mqtt_name: str):
        self.mqtt_name = mqtt_name


class UnexpectedValveResolved(Event):
    """Ein zuvor unerwartet geöffnetes Ventil ist wieder geschlossen."""
    def __init__(self, mqtt_name: str):
        self.mqtt_name = mqtt_name
```

- [ ] **Step 4: Config-Schalter** — in `src/daemon/config.py` analog zu `WATCHDOG_ENABLED`:

```python
UNEXPECTED_VALVE_ALERT_ENABLED = os.getenv("UNEXPECTED_VALVE_ALERT_ENABLED", "true").lower() == "true"
```

In `config/garden.conf` (bei den anderen Schaltern):

```
UNEXPECTED_VALVE_ALERT_ENABLED=true
```

- [ ] **Step 5: Test grün.** Commit: `feat(valve): Ereignisse + Schalter für Unerwartete Ventilöffnung`.

---

### Task 2: Erkennung in der Guss-Steuerung (Kern)

**Files:**
- Modify: `src/daemon/core/watering_controller.py`
- Test: `tests/core/test_watering_controller.py`

- [ ] **Step 1: Failing tests** — neue `TestUnexpectedValveOpen`-Fälle, die nur Außenverhalten prüfen (veröffentlichte Ereignisse). Mindestens:
  - Echter Übergang OFF→ON ohne Zyklus → genau **ein** `UnexpectedValveOpened`.
  - Wiederholte ON-Reports → kein erneutes Feuern.
  - ON **mit** aktivem Zyklus → kein Ereignis.
  - Zyklus läuft (ON) → Daemon schließt (Zyklus weg) → Ventil meldet noch kurz ON → **kein** Fehlalarm; dann OFF → kein `Resolved` (Episode war nie aktiv).
  - Episode aktiv → OFF → `UnexpectedValveResolved`.
  - Cold-Start: allererster Report ist ON → **kein** Ereignis.
  - Zwei Ventile parallel → Erkennung pro `mqtt_name`.
  - `UNEXPECTED_VALVE_ALERT_ENABLED=false` (patchen) → kein Ereignis.

  Muster für einen Fall:

```python
def test_external_open_emits_event_once(self):
    from daemon.core.valve_events import ValveStatusReported, UnexpectedValveOpened
    opened = []
    self.bus.subscribe(UnexpectedValveOpened, lambda e: opened.append(e))
    # bekannter Vorzustand OFF (kein Cold-Start)
    self.bus.publish(ValveStatusReported("garden_valve", "OFF", 0.0, 95, 120))
    # externe Öffnung ohne aktiven Zyklus
    self.bus.publish(ValveStatusReported("garden_valve", "ON", 0.0, 95, 120))
    self.bus.publish(ValveStatusReported("garden_valve", "ON", 0.0, 95, 120))
    self.assertEqual(len(opened), 1)
    self.assertEqual(opened[0].mqtt_name, "garden_valve")
```

- [ ] **Step 2: Tests ausführen — müssen fehlschlagen.**

- [ ] **Step 3: Zustand in `__init__`** ergänzen:

```python
self._last_valve_state: Dict[str, Optional[str]] = {}
self._unexpected_open: Dict[str, bool] = {}
```

- [ ] **Step 4: Erkennung in `_on_valve_status_reported`.** Zustand **unter** dem Lock ermitteln/aktualisieren, das zu sendende Ereignis aber **nach** dem Lock publizieren. Skizze:

```python
event_to_publish = None
with self._lock:
    enabled = config.UNEXPECTED_VALVE_ALERT_ENABLED
    has_cycle = mqtt_name in self._active_cycles
    last_state = self._last_valve_state.get(mqtt_name)
    if enabled:
        if event.state == "ON" and not has_cycle:
            # Cold-Start (last_state None) feuert NICHT; nur echte Flanke Nicht-ON -> ON
            if last_state is not None and last_state != "ON" and not self._unexpected_open.get(mqtt_name):
                self._unexpected_open[mqtt_name] = True
                event_to_publish = UnexpectedValveOpened(mqtt_name)
        elif event.state != "ON" and self._unexpected_open.get(mqtt_name):
            self._unexpected_open[mqtt_name] = False
            event_to_publish = UnexpectedValveResolved(mqtt_name)
    self._last_valve_state[mqtt_name] = event.state

if event_to_publish is not None:
    self.event_bus.publish(event_to_publish)
```

Einfügen, ohne die bestehende `_latest_device_volume`-Erfassung und Flow-Logik zu stören (die Volumen-/Flow-Verarbeitung bleibt unverändert).

- [ ] **Step 5: Tests grün** (gesamte `tests/core/test_watering_controller.py`). Commit: `feat(guss-steuerung): Erkennung Unerwartete Ventilöffnung (flankengesteuert)`.

---

### Task 3: Telegram-Benachrichtigung (Push)

**Files:**
- Modify: `src/daemon/ui/telegram_ui.py`
- Test: `tests/ui/test_telegram_ui.py`

- [ ] **Step 1: Failing tests** — Handler löst `wish_name` auf und sendet die richtige Meldung; `SAFETY_TIMEOUT_MINUTES` dynamisch. Muster:

```python
@patch("daemon.ui.telegram_ui.config.get_setting", return_value=30)
@patch("daemon.ui.telegram_ui.database")
@patch("daemon.ui.telegram_ui.telegram_client")
def test_unexpected_open_benachrichtigt(self, mock_client, mock_db, mock_get):
    from daemon.core.valve_events import UnexpectedValveOpened
    from daemon.ui.telegram_ui import _on_unexpected_valve_opened
    mock_db.get_valve_by_mqtt_name.return_value = {"wish_name": "Rasen"}
    _on_unexpected_valve_opened(UnexpectedValveOpened("garden_valve"))
    msg = mock_client.broadcast_notification.call_args[0][0]
    self.assertIn("Rasen", msg)
    self.assertIn("von außen geöffnet", msg)
    self.assertIn("30", msg)
```

(Falls kein `get_valve_by_mqtt_name` existiert: vorhandene Lookup-Funktion verwenden bzw. ergänzen — `database.get_all_valves()` filtern.)

- [ ] **Step 2: Tests ausführen — müssen fehlschlagen.**

- [ ] **Step 3: Handler implementieren** (bei den anderen `_on_*`-Handlern):

```python
def _on_unexpected_valve_opened(event: UnexpectedValveOpened):
    wish_name = _resolve_wish_name(event.mqtt_name)
    safety_min = config.get_setting("SAFETY_TIMEOUT_MINUTES", 30)
    telegram_client.broadcast_notification(
        f"⚠️ *Ventil von außen geöffnet*\n"
        f"„{wish_name}" wurde ohne aktiven Guss geöffnet.\n"
        f"Warst das nicht du, prüf die Leitung — das Hardware-Sicherheits-Timeout "
        f"schließt spätestens nach {safety_min} Min."
    )

def _on_unexpected_valve_resolved(event: UnexpectedValveResolved):
    wish_name = _resolve_wish_name(event.mqtt_name)
    telegram_client.broadcast_notification(
        f"✅ *Ventil wieder geschlossen*\n„{wish_name}" ist wieder zu."
    )
```

`_resolve_wish_name(mqtt_name)`: vorhandene Hilfsfunktion nutzen oder klein ergänzen (DB-Lookup, Fallback auf `mqtt_name`).

- [ ] **Step 4: Abonnements** im Event-Wiring-Block (~Zeile 2168 ff.):

```python
_global_bus.subscribe(UnexpectedValveOpened, _on_unexpected_valve_opened)
_global_bus.subscribe(UnexpectedValveResolved, _on_unexpected_valve_resolved)
```

- [ ] **Step 5: Tests grün.** Commit: `feat(telegram): Push bei Unerwarteter Ventilöffnung + Entwarnung`.

---

### Task 4: Integrationstest (End-to-End)

**Files:**
- Test: `tests/test_irrigation.py`

- [ ] **Step 1:** Test über das bestehende Wiring (`SimulatedMqttAdapter`, `HAS_PAHO=False` in `setUpClass`): Ventil ohne Zyklus von OFF nach ON → `UnexpectedValveOpened` wird veröffentlicht; nach OFF → `UnexpectedValveResolved`. Abonnent auf `_global_bus` registrieren (Muster wie `check_startup_safety`-Test).

- [ ] **Step 2:** Regressionsfall: regulärer Guss (Start → volumen-/zeitbedingtes Schließen) erzeugt **keine** `UnexpectedValveOpened`.

- [ ] **Step 3:** Vollständiger Lauf `python -m pytest tests` — alle grün. Commit: `test: Integrationstest Unerwartete Ventilöffnung`.

---

### Task 5: Referenz-Doku + Abschluss

**Files:**
- Modify: `docs/design/telegram-nachrichten.html`
- Move: `docs/features/0029-...md` → `docs/features/completed/`
- Move: `docs/plans/0029-...-plan.md` → `docs/plans/completed/`

- [ ] **Step 1:** Beide neuen Meldungen (Auslösung + Entwarnung) in `docs/design/telegram-nachrichten.html` eintragen (Regel `.claude/rules/telegram_messages.md`). Falls die `/status`-Ventilzeile geändert wurde, dort die Variante „von außen geöffnet" ergänzen.

- [ ] **Step 2:** Coverage prüfen (`scripts/run_coverage.sh` bzw. `.ps1`) — darf nicht regredieren.

- [ ] **Step 3:** Feature- und Plan-Dokument nach `completed/` verschieben.

- [ ] **Step 4:** Abschluss-Commit: `docs: Feature 0029 Referenz aktualisiert + abgeschlossen`.

---

## Offene Punkte / bewusst nicht im Plan

- **Debounce gegen Funk-Flackern**, **Auto-Schließen mit Bestätigungs-Button** (nach Feature 0018), **separate DB-Protokollierung/Tagesbericht-Zählung** — alle out-of-scope laut Feature 0029.
