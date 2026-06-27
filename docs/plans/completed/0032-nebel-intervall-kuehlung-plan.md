# Nebel-Intervall (Terrassen-Kühlung) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eine wiederkehrende Kühlfunktion (**Nebel-Intervall**), die ein eigenes Ventil in regelmäßigen Abständen sekundenkurz öffnet (**Nebelstoß**) und dazwischen pausiert — als eigener Zeitplan-Modus (`mode="nebel"`), getrieben von einer eigenen Engine (**Nebel-Steuerung**). Geplante **Nebel-Fenster** (Start–Ende) und manueller **Sofort-Nebel**. Siehe Feature 0032 und ADR 0033.

**Architecture:** Neue Kernkomponente `NebelController` (`core/nebel_controller.py`), Pendant zur Guss-Steuerung: eigener `threading.Timer`-Burst-Loop, injizierte `publish_fn` (ADR 0017). Der Scheduler verzweigt nach `mode` und hält das Nebel-Fenster zustandslos (idempotentes Anstoßen je Minute). Die Nebel-Steuerung „beansprucht" ihr Ventil; die Guss-Steuerung nimmt beanspruchte Ventile von der Unerwartete-Ventilöffnung-Erkennung (ADR 0032) aus — die einzige Kopplung der beiden Engines. Protokollierung nur pro Fenster (Beginn/Ende) + eine Tagesbericht-Zeile.

**Tech Stack:** Python 3.11, EventBus (synchron), SQLite, stdlib Telegram-Client, unittest + pytest, `SimulatedMqttAdapter`.

**Schlüssel-Invarianten (aus dem Grill, ADR 0033):**
- Kühlen ≠ Bewässern: kein Volumenlimit, kein Regen-Skip, keine Mindest-Flussrate-Defekterkennung.
- Sekundengenauer Takt in eigener Engine (1-Min-Scheduler reicht nicht).
- Ventil-Beanspruchung deckt die **ganze** Fensterdauer (inkl. Pausen) → kein Fehlalarm je Stoß.
- Einzelne Nebelstöße werden **nicht** protokolliert.
- Geplantes Fenster zustandslos aus dem Zeitplan (ADR 0011) → Wiederaufnahme nach Neustart; Sofort-Nebel verfällt.
- Kurzer Hardware-Fail-Safe fürs Nebel-Ventil (~90 s) als Absturz-Backstop.
- Ereignisse **außerhalb** des Locks publizieren (EventBus synchron → Re-Entrancy meiden).
- Tests deterministisch über direkte Transitions-Methoden, **keine** `sleep`-basierten Tests.

**Default-Werte (hier final):** `NEBEL_ON_SECONDS=20`, `NEBEL_PAUSE_MINUTES=5`, `NEBEL_MANUAL_MAX_MINUTES=120`, `NEBEL_VALVE_FAIL_SAFE_SECONDS=90`.

---

### Task 1: Konfiguration + DB-Schema + CRUD

**Files:**
- Modify: `src/daemon/config.py`, `config/garden.conf`
- Modify: `src/daemon/adapters/database.py`
- Test: `tests/test_irrigation.py` (Config-Defaults), `tests/adapters/test_database.py`

- [ ] **Step 1: Failing tests.**
  - In `tests/test_irrigation.py` bei den Config-Default-Assertions:
    ```python
    self.assertEqual(config.NEBEL_ON_SECONDS, 20)
    self.assertEqual(config.NEBEL_PAUSE_MINUTES, 5)
    self.assertEqual(config.NEBEL_MANUAL_MAX_MINUTES, 120)
    ```
  - In `tests/adapters/test_database.py`: ein Nebel-Zeitplan lässt sich anlegen/lesen, `mode`/`end_time`/`on_seconds`/`pause_minutes` werden korrekt persistiert; ein „alter" Zeitplan ohne diese Felder liefert `mode == "watering"`.

- [ ] **Step 2: Tests ausführen — müssen fehlschlagen** (`AttributeError` / fehlende Spalten).

- [ ] **Step 3: Config-Konstanten** in `src/daemon/config.py` (analog `SAFETY_TIMEOUT_MINUTES`):
  ```python
  NEBEL_ON_SECONDS = int(os.getenv("NEBEL_ON_SECONDS", "20"))
  NEBEL_PAUSE_MINUTES = int(os.getenv("NEBEL_PAUSE_MINUTES", "5"))
  NEBEL_MANUAL_MAX_MINUTES = int(os.getenv("NEBEL_MANUAL_MAX_MINUTES", "120"))
  NEBEL_VALVE_FAIL_SAFE_SECONDS = int(os.getenv("NEBEL_VALVE_FAIL_SAFE_SECONDS", "90"))
  ```
  In `config/garden.conf` (bei den anderen Bewässerungs-Einstellungen) dieselben Schlüssel dokumentiert ergänzen.

- [ ] **Step 4: Schema-Migration** in `database.init_db()` — neue Spalten via `ALTER TABLE … ADD COLUMN`, je in `try/except OperationalError` (Muster wie `execution_mode`):
  ```python
  cursor.execute("ALTER TABLE schedules ADD COLUMN mode TEXT DEFAULT 'watering'")
  cursor.execute("ALTER TABLE schedules ADD COLUMN end_time TEXT")
  cursor.execute("ALTER TABLE schedules ADD COLUMN on_seconds INTEGER")
  cursor.execute("ALTER TABLE schedules ADD COLUMN pause_minutes INTEGER")
  ```
  (Im `CREATE TABLE`-Block ebenfalls ergänzen, damit Neuanlagen die Spalten direkt führen.)

- [ ] **Step 5: CRUD erweitern** — `add_schedule`/`update_schedule` um optionale Parameter `mode="watering"`, `end_time=None`, `on_seconds=None`, `pause_minutes=None` ergänzen (rückwärtskompatible Defaults, bestehende Aufrufer bleiben unverändert). `get_schedules`/`get_schedule_by_id` geben die neuen Felder mit.

- [ ] **Step 6: Tests grün.** Commit: `feat(db): Zeitplan-Modus Nebel — Schema, Migration, CRUD + Config-Defaults`.

---

### Task 2: Nebel-Steuerung (Kern) + Ereignisse + Ventil-Beanspruchung

**Files:**
- Create: `src/daemon/core/nebel_controller.py`
- Create: `src/daemon/core/nebel_events.py`
- Modify: `src/daemon/core/watering_controller.py` (Beanspruchungs-Hook)
- Test: `tests/core/test_nebel_controller.py` (neu), `tests/core/test_watering_controller.py`

- [ ] **Step 1: Failing tests (Nebel-Steuerung).** Referenzmuster `tests/core/test_watering_controller.py` (`EventBus` + `SimulatedMqttAdapter` + Komponente). Nur Außenverhalten (Ventilzustand, Ereignisse), Timing über direkte Transitions-Methoden — **kein** `sleep`. Mindestens:
  - Start eines Fensters → `NebelIntervalStarted` veröffentlicht, erster Nebelstoß öffnet das Ventil (Status `ON`).
  - Stoß-Ende (`_end_burst`) schließt das Ventil (`OFF`), kein Folge-Ereignis je Stoß.
  - Nach Pause (`_begin_burst`) öffnet erneut.
  - Erreicht die aktuelle Zeit `end_time` → Fenster endet, Ventil sicher `OFF`, genau **ein** `NebelIntervalEnded`.
  - `stop()` (manuell) → Ventil `OFF`, `NebelIntervalEnded`.
  - Parallelbetrieb getrennt vom Garten-Ventil (eigener `mqtt_name`).

  Sketch:
  ```python
  def test_burst_opens_and_pause_closes(self):
      started, ended = [], []
      self.bus.subscribe(NebelIntervalStarted, lambda e: started.append(e))
      self.bus.subscribe(NebelIntervalEnded, lambda e: ended.append(e))
      end = datetime.now() + timedelta(minutes=30)
      self.nebel.start(mqtt_name="terrace_mist", on_seconds=20, pause_minutes=5,
                       end_time=end, source="nebel")
      self.assertEqual(self.client.get_valve_status("terrace_mist")["state"], "ON")
      self.nebel._end_burst("terrace_mist")          # Stoß-Ende
      self.assertEqual(self.client.get_valve_status("terrace_mist")["state"], "OFF")
      self.nebel._begin_burst("terrace_mist")        # nächster Stoß
      self.assertEqual(self.client.get_valve_status("terrace_mist")["state"], "ON")
      self.assertEqual(len(started), 1)
  ```

- [ ] **Step 2: Tests ausführen — müssen fehlschlagen.**

- [ ] **Step 3: Ereignisse** in `src/daemon/core/nebel_events.py`:
  ```python
  from .event_bus import Event

  class NebelIntervalStarted(Event):
      def __init__(self, mqtt_name: str, source: str, end_time: str):
          self.mqtt_name = mqtt_name; self.source = source; self.end_time = end_time

  class NebelIntervalEnded(Event):
      def __init__(self, mqtt_name: str, source: str, duration_run: int, burst_count: int, details: str):
          self.mqtt_name = mqtt_name; self.source = source
          self.duration_run = duration_run; self.burst_count = burst_count; self.details = details
  ```

- [ ] **Step 4: `NebelController`** in `src/daemon/core/nebel_controller.py`. Struktur analog `WateringController`:
  - `__init__(self, event_bus, publish_fn, claim_fn=None, release_fn=None)` — `claim_fn`/`release_fn` sind die Beanspruchungs-Callables der Guss-Steuerung (ADR 0017 Port-Injektion).
  - Zustand pro Ventil unter `RLock`: `end_time`, `on_seconds`, `pause_minutes`, `source`, `burst_count`, `start_time`, aktiver `threading.Timer`.
  - `start(mqtt_name, on_seconds, pause_minutes, end_time, source, valve_topic=None)` — idempotent (läuft bereits → no-op, ermöglicht zustandsloses Anstoßen durch den Scheduler), `claim_fn(mqtt_name)`, `NebelIntervalStarted` publizieren, ersten `_begin_burst`.
  - `_begin_burst(mqtt_name)` — wenn `now >= end_time` → `_finish`; sonst Ventil `ON`, `burst_count += 1`, `threading.Timer(on_seconds, _end_burst)`.
  - `_end_burst(mqtt_name)` — Ventil `OFF`, wenn `now >= end_time` → `_finish`; sonst `threading.Timer(pause_minutes*60, _begin_burst)`.
  - `_finish(mqtt_name, reason)` — Timer canceln, Ventil `OFF`, `release_fn(mqtt_name)`, `NebelIntervalEnded` publizieren, Zustand entfernen.
  - `stop(mqtt_name=None)` — manueller/fenster-externer Abschluss → `_finish`.
  - `is_active(mqtt_name) -> bool`, `get_active(mqtt_name) -> dict|None` für Scheduler/UI/Status.
  - Ventil-Ansteuerung ausschließlich über `publish_fn(f"{valve_topic}/set", '{"state": "ON"|"OFF"}')`. **Keine** Volumen-/Flow-/Regen-Logik.
  - Publish der Ereignisse **außerhalb** des Locks.

- [ ] **Step 5: Beanspruchungs-Hook in `WateringController`.** Failing test zuerst in `tests/core/test_watering_controller.py`: ein OFF→ON ohne Guss-Zyklus auf einem **beanspruchten** Ventil löst **kein** `UnexpectedValveOpened` aus; nach `release` wieder normal. Dann implementieren:
  ```python
  # __init__:
  self._claimed_valves: set[str] = set()
  def claim_valve(self, mqtt_name: str) -> None:
      with self._lock: self._claimed_valves.add(mqtt_name)
  def release_valve(self, mqtt_name: str) -> None:
      with self._lock: self._claimed_valves.discard(mqtt_name)
  ```
  In `_on_valve_status_reported` die Unerwartete-Ventilöffnung-Erkennung überspringen, solange `mqtt_name in self._claimed_valves` (Prüfung unter dem Lock, zusammen mit `has_cycle`). Volumen-/Flow-Pfad unverändert.

- [ ] **Step 6: Tests grün** (`tests/core/test_nebel_controller.py` + `tests/core/test_watering_controller.py`). Commit: `feat(nebel-steuerung): Burst-Loop, Ereignisse + Ventil-Beanspruchung`.

---

### Task 3: Scheduler-Integration (Modus-Verzweigung + zustandsloses Fenster)

**Files:**
- Modify: `src/daemon/scheduler.py`, `src/daemon/main.py` (Verdrahtung)
- Test: `tests/test_irrigation.py`

- [ ] **Step 1: Failing tests** (Integration, bestehendes Wiring aus `setUpClass`, `HAS_PAHO=False`):
  - Ein aktiver Nebel-Zeitplan, dessen Fenster die aktuelle Zeit umschließt → Nebel-Steuerung läuft fürs Nebel-Ventil; **kein** `weather`-Check aufgerufen (mocken/spyen).
  - Aktueller Zeitpunkt außerhalb `[time, end_time)` → Nebel-Steuerung läuft **nicht**.
  - Wiederaufnahme: Nebel-Steuerung inaktiv + Zeit im Fenster → ein Scheduler-Tick startet sie (idempotent: zweiter Tick startet keinen zweiten Lauf).
  - Bewässerungs-Zeitplan bleibt unverändert (`mode="watering"` → alter Pfad).

- [ ] **Step 2: Tests ausführen — müssen fehlschlagen.**

- [ ] **Step 3: `main.py`** — `NebelController` instanziieren (mit `publish`-Fn des MQTT-Clients und `claim_valve`/`release_valve` der Guss-Steuerung), via Setter an den Scheduler übergeben (Muster `set_controller`). Reihenfolge: nach WateringController-Wiring, vor Scheduler-Start.

- [ ] **Step 4: `scheduler.py`** — im Auslöse-/Prüfblock je Minute:
  - Bewässerungs-Zeitpläne: unverändert (`_trigger_scheduled_watering`).
  - Nebel-Zeitpläne (`mode=="nebel"`, aktiv, heutiger Tag): **fensterbasiert** behandeln — eine Hilfsfunktion `_ensure_nebel_window(sched, now)` prüft `time <= HH:MM < end_time`; ist die Zeit im Fenster und die Nebel-Steuerung fürs Ventil **nicht** aktiv → `nebel.start(...)` mit `end_time = heute end_time`, Ventil aus `schedule_valves`. Ist die Zeit außerhalb und die Steuerung aktiv (für ein vom Scheduler verwaltetes Fenster) → nichts erzwingen (die Engine beendet sich selbst zur `end_time`).
  - Kein Wetter-Check, keine Skalierung im Nebel-Pfad.

- [ ] **Step 5: Tests grün** (`python -m pytest tests/test_irrigation.py`). Commit: `feat(scheduler): Nebel-Fenster auslösen + zustandslos wiederaufnehmen`.

---

### Task 4: Telegram-UI — Zeitplan-Wizard (Nebel-Zweig) + Sofort-Nebel

**Files:**
- Modify: `src/daemon/ui/telegram_ui.py`
- Test: `tests/ui/test_telegram_ui.py`

- [ ] **Step 1: Failing tests:**
  - Wizard: Verzweigung „Nebel" sammelt Endzeit, ON-Sekunden, Pause und ruft `database.add_schedule(..., mode="nebel", end_time=..., on_seconds=..., pause_minutes=...)`.
  - Sofort-Nebel: Start-Befehl mit Laufzeit-Button (z. B. 60) ruft `nebel.start(...)` mit `source="nebel_manual"` und `end_time = now + min(60, NEBEL_MANUAL_MAX_MINUTES)`; Stopp-Button ruft `nebel.stop(...)`.
  - Handler `_on_nebel_interval_started` / `_on_nebel_interval_ended` senden die richtige Benachrichtigung (Wunschname aufgelöst).

- [ ] **Step 2: Tests ausführen — müssen fehlschlagen.**

- [ ] **Step 3: Wizard-Zweig.** Am Einstieg des Zeitplan-Wizards eine Auswahl „Bewässerung / Nebel" (neue Keyboard-Helper analog `get_duration_wizard_keyboard`/`get_volume_wizard_keyboard`). Im Nebel-Zweig die Schritte: Name → Tage → Startzeit → Endzeit → ON-Sekunden → Pause-Minuten. Bestehende Bewässerungs-Schritte bleiben unberührt. Zeitplan-Liste/-Detail kennzeichnen Nebel-Zeitpläne sichtbar (z. B. „🌫️ Nebel") und zeigen die passenden Felder.

- [ ] **Step 4: Sofort-Nebel.** Neuer Menüpunkt/Befehl „Sofort-Nebel" mit Laufzeit-Buttons (30/60/120) und Stopp-Button. Zielventil: bei genau einem registrierten Ventil dieses; bei mehreren eine Ventil-Auswahl (bestehende Ventil-Auswahl-UI wiederverwenden, falls vorhanden). Laufzeit hart auf `NEBEL_MANUAL_MAX_MINUTES` deckeln. Standard-Takt aus `config.NEBEL_ON_SECONDS`/`NEBEL_PAUSE_MINUTES`.

- [ ] **Step 5: Benachrichtigungs-Handler + Abonnements** (bei den anderen `_on_*` / im Wiring-Block):
  ```python
  _global_bus.subscribe(NebelIntervalStarted, _on_nebel_interval_started)
  _global_bus.subscribe(NebelIntervalEnded, _on_nebel_interval_ended)
  ```
  Meldungen: Beginn („🌫️ Nebel-Intervall gestartet …"), Ende mit Dauer/Stoß-Anzahl. Wunschname über vorhandene Auflösung.

- [ ] **Step 6: Tests grün.** Commit: `feat(telegram): Nebel-Zeitplan-Wizard + Sofort-Nebel + Meldungen`.

---

### Task 5: Protokollierung (pro Fenster) + Tagesbericht-Zeile

**Files:**
- Modify: `src/daemon/adapters/database_adapter.py`
- Modify: `src/daemon/adapters/daily_report.py`
- Test: `tests/adapters/test_database_adapter.py`, `tests/adapters/test_daily_report.py`

- [ ] **Step 1: Failing tests:**
  - `DatabaseLoggerAdapter` schreibt bei `NebelIntervalStarted`/`NebelIntervalEnded` je **einen** kompakten Eintrag (Quelle z. B. `"nebel"`); einzelne Stöße erzeugen nichts.
  - Tagesbericht zeigt eine Zusammenfassungszeile nur, wenn im Zeitraum genebelt wurde (Fenster, Dauer, Anzahl Stöße); sonst keine.

- [ ] **Step 2: Tests ausführen — müssen fehlschlagen.**

- [ ] **Step 3: Persistenz.** Im `DatabaseLoggerAdapter` die beiden Nebel-Ereignisse abonnieren und über `database.log_watering(...)` mit eigenem `source="nebel"`-Tag protokollieren (Beginn = `status="started"`, Ende = `status="completed"`, `details` mit Stoß-Anzahl; `watered_volume=0`). So bleibt es aus der Guss-Auswertung heraushaltbar (Filter über `source`).

- [ ] **Step 4: Tagesbericht.** In `daily_report.py` die Nebel-Einträge des Berichtszeitraums separat aggregieren und eine kompakte Zeile rendern (keine Auflistung einzelner Stöße). Bewässerungs-Zusammenfassung unverändert.

- [ ] **Step 5: Tests grün.** Commit: `feat(report): Nebel-Intervall protokollieren (pro Fenster) + Tagesbericht-Zeile`.

---

### Task 6: Integrationstest, Referenz-Doku, Hardware-Fail-Safe & Abschluss

**Files:**
- Test: `tests/test_irrigation.py`
- Modify: `docs/design/telegram-nachrichten.html`
- Docs/Deploy: Hinweis Nebel-Ventil-Fail-Safe
- Move: Feature- & Plan-Dokument nach `completed/`

- [ ] **Step 1: End-to-End-Integrationstest** über das bestehende Wiring: Nebel-Zeitplan im Fenster → Ventil taktet ON/OFF (über simulierten Status getrieben), kein `UnexpectedValveOpened` (Beanspruchung greift); zur Endzeit Fenster-Ende. Regression: paralleler Bewässerungs-Guss am Garten-Ventil bleibt unbeeinflusst.

- [ ] **Step 2: Telegram-Referenz.** Alle neuen/geänderten Meldungen (Wizard-Nebel-Zweig, Sofort-Nebel-Buttons/Stopp, Beginn/Ende-Meldung, Tagesbericht-Zeile) in `docs/design/telegram-nachrichten.html` eintragen (Regel `.claude/rules/telegram_messages.md`).

- [ ] **Step 3: Hardware-Fail-Safe Nebel-Ventil.** Kurzen `manual_default_settings.fail_safe` (≈ `NEBEL_VALVE_FAIL_SAFE_SECONDS`, 90 s) fürs Nebel-Ventil über den Mittelweg-Dienst dokumentieren (Geräte-Einstellung, kein Daemon-Code-Pfad) — als Betriebs-/Einrichtungshinweis bei der Ventil-Kopplung bzw. im Deploy-Hinweis festhalten.

- [ ] **Step 4: Coverage** prüfen (`scripts/run_coverage.ps1`/`.sh`) — darf nicht regredieren. Voller Lauf `python -m pytest tests` grün.

- [ ] **Step 5: Abschluss** — Feature `docs/features/0032-…md` und Plan `docs/plans/0032-…-plan.md` nach `completed/` verschieben; Beads-Issue schließen (Definition of Done, `.agents/rules/feature-done.md`). Commit: `docs: Feature 0032 Nebel-Intervall Referenz aktualisiert + abgeschlossen`.

---

## Offene Punkte / bewusst nicht im Plan

- **Temperatur-Gating** und **Regen-Pause** des Nebel-Intervalls — out of scope laut Feature 0032 / ADR 0033 (spätere optionale Verfeinerungen).
- **Persistenz eines Sofort-Nebels** über Neustart — bewusst nicht (verfällt).
- **Mehrere Nebel-Ventile parallel pro Fenster** — zunächst ein Nebel-Ventil je Zeitplan.
- **Volumen-/Defekterkennung der Nebeldüse** — entfällt (Telemetrie ignoriert).
