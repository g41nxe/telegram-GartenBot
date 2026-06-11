# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python daemon for a smart garden irrigation system running on a **Raspberry Pi Zero W**. It controls a Sonoff Hydro ONE Zigbee water valve via Telegram bot, with weather-based skip logic, scheduled watering, and flood-prevention safety features.

**Domain language** is defined in `CONTEXT.md`. Use the exact German terms from that file. Key terms: *Ventil* (not "Schalter"), *Bewässerungs-Daemon* (not "Backend"), *Ereignis-Kanal* (not "Event-Bus"), *Guss-Steuerung* (not "Cycle-Controller"), *Mittelweg-Dienst* (Zigbee2MQTT, not "Bridge-Server").

## Commands

### Run all tests (no hardware required)
```bash
python -m unittest discover tests
```

### Run a single test
```bash
python -m unittest tests.test_irrigation.TestGardenIrrigation.test_01_config_defaults
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
python -m daemon.main
# paho-mqtt absence automatically activates SimulatedMqttAdapter
```

### Deploy to Raspberry Pi (Windows → Pi)
```powershell
.\scripts\deploy.ps1
# Builds vendor/zigbee2mqtt locally via npm, then scp-transfers src/, scripts/, .env, tools/ to the Pi
```

### Check systemd service status on Pi
```bash
sudo systemctl status mosquitto zigbee2mqtt garden-irrigation
```

## Architecture

The daemon follows **Hexagonal Architecture** with an event-driven inner core. Startup order in [src/daemon/main.py](src/daemon/main.py): DB init → MQTT client → EventBus + WateringController wiring → Scheduler → Telegram bot.

### Layer map

```
src/daemon/
├── config.py              # Loads .env; all runtime config constants live here
├── scheduler.py           # Scheduler loop (1-min poll); facade over WateringController
├── main.py                # Entry point; wires all layers together (IoC)
│
├── core/                  # Domain logic — no I/O allowed here
│   ├── event_bus.py       # Thread-safe synchronous EventBus (publish/subscribe)
│   ├── watering_controller.py  # WateringController: Kombinierter Guss, volume integration, timers
│   └── scheduler_events.py    # Event types: DailyReportTriggered, WateringSkipped, ScheduleFailed, WeatherDataFetched
│
├── adapters/              # Stateless outer boundary — no cross-adapter imports
│   ├── database.py        # SQLite CRUD (schedules, watering_history, weather_history, device_status_log)
│   ├── database_adapter.py     # DatabaseLoggerAdapter: subscribes to domain events → writes to DB
│   ├── mqtt_client.py     # MqttClient interface + PahoMqttAdapter (prod) / SimulatedMqttAdapter (test)
│   ├── weather.py         # Open-Meteo HTTP adapter; publishes WeatherDataFetched event
│   └── pairing.py         # Ventil-Kopplung logic
│
└── ui/
    ├── telegram_bot.py    # Bot command handlers + inline keyboard wizards
    ├── telegram_client.py # Raw HTTP Telegram API (stdlib only — no external SDK)
    └── telegram_ui.py     # UI helpers / formatters
```

### Architecture rules (enforced by `.agents/rules/architecture.md`)

1. **Stateless adapters**: Adapters in `adapters/` must not import each other or hold domain state.
2. **Event-driven side effects**: Cross-cutting concerns (DB logging, UI notifications) are wired through the `EventBus` (`_global_bus` in `mqtt_client.py`), not via direct calls. The `DatabaseLoggerAdapter` and Telegram UI subscribe to events; they are never called directly by core logic.

Violations of these rules should be refactored before proceeding.

### Key flows

**Kombinierter Guss (First-to-Hit):** `WateringController.start_watering()` opens the valve via MQTT, arms a `threading.Timer` for the time limit, and integrates incoming `ValveStatusReported` events to track volume. Whichever limit (time or volume) triggers first closes the valve and publishes a completion event.

**Scheduler loop:** Runs in a daemon thread, wakes every minute, checks `HH:MM` against active schedules in the DB. Calls `weather.should_skip_watering()` before each scheduled run; on skip, publishes `WateringSkipped`; on failure, publishes `ScheduleFailed`. Daily report fires once at 08:00.

**Offline simulation:** If `paho-mqtt` is not installed, `SimulatedMqttAdapter` is used instead — simulates a valve at 5 L/min. Tests force this path by setting `mqtt_client.HAS_PAHO = False` in `setUpClass`.

**Database migrations:** `database.init_db()` runs `ALTER TABLE` statements wrapped in `try/except OperationalError` to handle schema drift on existing deployments — no migration framework used.

**Zigbee2MQTT vendoring:** `vendor/zigbee2mqtt/` holds a locally modified copy with `debounce` downgraded to `^1.2.1` (CommonJS compat for Node.js v20.11.1 on ARMv6). TypeScript is compiled on the Windows host via `deploy.ps1` (not on the Pi, which lacks RAM for `tsc`).

## Configuration

Copy `.env.template` to `.env` and fill in required values:
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_ALLOWED_USER_IDS` — whitelist-based access control
- `LATITUDE` / `LONGITUDE` — for Open-Meteo weather queries
- `MQTT_VALVE_TOPIC` — default `zigbee2mqtt/garden_valve`
- `SAFETY_TIMEOUT_MINUTES` — hardware fail-safe sent to the valve on connect (default: 30)

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
