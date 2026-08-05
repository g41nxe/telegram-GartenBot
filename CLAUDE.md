# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd update <id> --status awaiting_acceptance   # Umsetzung fertig, Feld-Abnahme offen
bd close <id>         # Complete work
```

**Eigener Status `awaiting_acceptance`** (konfiguriert in `.beads/config.yaml`): Umsetzung fertig
und ausgeliefert, aber die Feld-Abnahme (Testplan unter `docs/testplans/`) ist noch nicht
protokolliert. Weder „in Arbeit" noch „erledigt" — `bd ready` blendet solche Vorgänge aus, sie
gelten aber nicht als abgeschlossen. Erst `bd close`, wenn ein Ergebnis-Commit zum Testplan
existiert (Muster: `docs(testplan): … — GO`).

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.
<!-- END BEADS INTEGRATION -->

## Agent Memory

Persistent memory for this project lives in `.claude/memory/`. Read `MEMORY.md` there at the start of each session for context on past decisions, feedback, and project state. Update it when you learn something worth remembering.

## Project Overview

This is a Python daemon for a smart garden irrigation system running on a **Raspberry Pi Zero W**. It controls a Sonoff Hydro ONE Zigbee water valve via Telegram bot, with weather-based skip logic, scheduled watering, and flood-prevention safety features.

**Domain language** is defined in `CONTEXT.md`. Use the exact German terms from that file. Key terms: *Ventil* (not "Schalter"), *Bewässerungs-Daemon* (not "Backend"), *Ereignis-Kanal* (not "Event-Bus"), *Guss-Steuerung* (not "Cycle-Controller"), *Mittelweg-Dienst* (Zigbee2MQTT, not "Bridge-Server").

## Commands

### Run all tests (no hardware required)
```bash
python -m pytest tests
```

### Run a single test
```bash
python -m pytest tests/test_irrigation.py::TestGardenIrrigation::test_01_config_defaults
```

### Run with coverage (Linux/Pi)
```bash
bash scripts/run_coverage.sh
```

### Run with coverage (Windows)
```powershell
.\scripts\run_coverage.ps1
```

### Run the daemon locally (simulation mode)
```bash
python -m src.daemon.main
# Matches the Pi's actual systemd invocation (scripts/setup.sh) — running it as
# `python -m daemon.main` instead lets both `daemon.*` and `src.daemon.*` resolve at once,
# silently splitting event classes into two distinct objects (see camera_receiver.py history).
# paho-mqtt absence automatically activates SimulatedMqttAdapter
```

### Deploy to Raspberry Pi (Windows → Pi)
```powershell
.\scripts\deploy.ps1
# Builds vendor/zigbee2mqtt locally via npm, then scp-transfers src/, scripts/, config/, tools/ to the Pi
# Add -CopyEnv to also transfer .env (first-time setup only)
```

### Releases (NUR über den `release`-Skill)
Ein Release wird **ausschließlich** über den `release`-Skill ausgelöst — **niemals** `git tag vX.Y.Z` von Hand. Der CI erzeugt die GitHub-Release-Notes aus dem obersten `## `-Abschnitt der `CHANGELOG.md`; taggt man ohne CHANGELOG-Update, veröffentlicht der CI die *alten* Notes des Vorgänger-Releases. Der Skill aktualisiert die CHANGELOG **vor** dem Tag; ein CI-Guard (`CHANGELOG passt zum Tag` in `release.yml`) lässt das Release fehlschlagen, wenn CHANGELOG-Kopf und Tag divergieren.

### Apply Python/DB changes on Pi (no full setup needed)
For Python source changes and DB schema migrations, only a service restart is required — do **not** re-run `setup.sh`:
```bash
sudo systemctl restart garden-irrigation
journalctl -u garden-irrigation -n 50 --no-pager
```
`database.init_db()` runs the migration automatically on startup. Re-run `setup.sh` only when systemd unit definitions change or new OS packages are required.

### Check systemd service status on Pi
```bash
sudo systemctl status mosquitto zigbee2mqtt garden-irrigation
```

## Architecture

The daemon follows **Hexagonal Architecture** with an event-driven inner core. Startup order in [src/daemon/main.py](src/daemon/main.py): DB init → MQTT client → EventBus + WateringController wiring → Scheduler → Telegram bot.

### Layer map

```
src/daemon/
├── config.py              # Loads config/garden.conf then .env; all runtime config constants live here
├── scheduler.py           # Scheduler loop (1-min poll); facade over WateringController
├── main.py                # Entry point; wires all layers together (IoC)
│
├── core/                  # Domain logic — no I/O allowed here
│   ├── event_bus.py       # Thread-safe synchronous EventBus (publish/subscribe)
│   ├── watering_controller.py  # WateringController: Kombinierter Guss, volume integration, timers
│   ├── scheduler_events.py    # Event types: DailyReportTriggered, WateringSkipped, ScheduleFailed, WeatherDataFetched
│   └── valve_events.py        # Event types: ValveStatusReported, DeviceJoinedEvent
│
├── adapters/              # Stateless outer boundary — no cross-adapter imports
│   ├── database.py        # SQLite CRUD (schedules, watering_history, weather_history, device_status_log)
│   ├── database_adapter.py     # DatabaseLoggerAdapter: subscribes to domain events → writes to DB
│   ├── mqtt_client.py     # MqttClient interface + PahoMqttAdapter (prod) / SimulatedMqttAdapter (test)
│   ├── weather.py         # Open-Meteo HTTP adapter; publishes WeatherDataFetched event
│   ├── chart.py           # QuickChart.io adapter; builds Chart.js config, returns PNG bytes or None
│   ├── daily_report.py    # Tagesbericht-Generierung und -Versand
│   └── pairing.py         # Ventil-Kopplung logic
│
└── ui/
    ├── telegram_client.py # Raw HTTP Telegram API (stdlib only — no external SDK)
    └── telegram_ui.py     # Bot commands, wizards, notifications & event handlers
```

### Architecture rules (enforced by `.agents/rules/architecture.md`)

1. **Stateless adapters**: Adapters in `adapters/` must not import each other or hold domain state.
2. **Event-driven side effects**: Cross-cutting concerns (DB logging, UI notifications) are wired through the `EventBus` (`_global_bus` in `mqtt_client.py`), not via direct calls. The `DatabaseLoggerAdapter` and Telegram UI subscribe to events; they are never called directly by core logic.

Violations of these rules should be refactored before proceeding.

### Key flows

**Kombinierter Guss (First-to-Hit):** `WateringController.start_watering()` opens the valve via MQTT, arms a `threading.Timer` for the time limit, and integrates incoming `ValveStatusReported` events to track volume. Whichever limit (time or volume) triggers first closes the valve and publishes a completion event.

**Scheduler loop:** Runs in a daemon thread, wakes every minute, checks `HH:MM` against active schedules in the DB. Calls `weather.should_skip_watering()` before each scheduled run; on skip, publishes `WateringSkipped`; on failure, publishes `ScheduleFailed`. Daily report fires once at 08:00.

**Offline simulation:** If `paho-mqtt` is not installed, `SimulatedMqttAdapter` is used instead — simulates a valve at 5 L/min. Tests force this path by setting `mqtt_client.HAS_PAHO = False` in `setUpClass`.

**Telegram messages:** Every user-facing message the bot sends (commands, wizards, `_on_*` event notifications, daily report, errors) is catalogued faithfully in [`docs/design/telegram-nachrichten.html`](docs/design/telegram-nachrichten.html). When you add, change, or remove a message in `ui/telegram_ui.py` or `adapters/daily_report.py`, update that reference in the same change — see `.claude/rules/telegram_messages.md`.

**Database migrations:** `database.init_db()` runs `ALTER TABLE` statements wrapped in `try/except OperationalError` to handle schema drift on existing deployments — no migration framework used.

**Zigbee2MQTT vendoring:** `vendor/zigbee2mqtt/` holds a locally modified copy with `debounce` downgraded to `^1.2.1` (CommonJS compat for Node.js v20.11.1 on ARMv6). TypeScript is compiled on the Windows host via `deploy.ps1` (not on the Pi, which lacks RAM for `tsc`).

## Code-Sprache (Namensgebung)

Code-Bezeichner — Klassen, Funktionen, Variablen, Module — werden **englisch** benannt (konsistent zu `WizardSpec`, `compute_next_sleep_seconds`, den englischen Ereignisklassen). **Deutsch** bleibt ausschließlich in den **Nutzertexten** (Telegram-Nachrichten) und in **bestehenden** deutschen Domänen-Bezeichnern, die nicht umbenannt werden. Neue technische Module sind englisch. `CONTEXT.md` bleibt das (deutsche) Garten-Glossar für Domänenbegriffe — nicht für Infrastruktur-Konzepte.

## Configuration

Configuration is split into two files (ADR 0030):

- **`config/garden.conf`** (versioned, deployed with each release): generic non-secret settings — thresholds, timeouts, MQTT topics, camera settings. No personal data.
- **`.env`** (gitignored, never overwritten by OTA): secrets and location-specific values — `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS`, `LATITUDE`/`LONGITUDE`, `GITHUB_PAT`, deploy credentials.

Copy `.env.template` to `.env` and fill in secrets and coordinates. All other defaults come from `config/garden.conf`.

## Testing

All tests run fully offline (no MQTT broker, no Telegram, no weather API) via the simulation layer.

Tests are in `tests/test_irrigation.py` (integration-style) and split unit tests in `tests/core/` and `tests/adapters/`.

**TDD rule:** Write a failing test before any new logic. Run coverage after changes — coverage must not regress (`scripts/run_coverage.sh`).

When writing tests that involve the `WateringController` or scheduler, set up the wiring from `setUpClass` in `tests/test_irrigation.py` as the reference pattern.

## Planning

Before implementing any feature or refactor, read in order:
1. `CONTEXT.md` — domain terminology
2. `ARCHITECTURE.md` — structural rules
3. `docs/adr/` — prior decisions (ADRs 0001–0013)

ADR deviations must be flagged explicitly for review.

If the feature touches the Telegram UI, also review [`docs/design/telegram-nachrichten.html`](docs/design/telegram-nachrichten.html) for existing message style, and keep it in sync per `.claude/rules/telegram_messages.md`.

When a feature is complete, follow the Definition of Done in `.agents/rules/feature-done.md`: close the Beads issue, move feature and plan docs to `completed/`, commit together.
