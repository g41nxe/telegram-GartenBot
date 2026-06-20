---
name: run-telegram-gartenbot
description: Run, test, or smoke-check the telegram-GartenBot daemon. Use when asked to run the app, verify a change works, run tests, or check that the scheduler/watering logic behaves correctly.
---

# run-telegram-gartenbot

Python daemon that controls a Sonoff Zigbee irrigation valve via MQTT on a Raspberry Pi. The full daemon needs real hardware (MQTT broker, Zigbee dongle, Telegram token). For development and CI the driver runs everything in simulation mode — no broker, no hardware, no network required.

Driver: `.claude/skills/run-telegram-gartenbot/smoke.py`

## Prerequisites

```bash
pip install paho-mqtt
```

Python 3.11+ is required (standard library `urllib`, `sqlite3`, `threading` — no other deps).

## Run (agent path)

### Smoke check — simulation mode, no hardware

```bash
PYTHONIOENCODING=utf-8 python .claude/skills/run-telegram-gartenbot/smoke.py
```

Exercises: `database` CRUD, simulated MQTT valve open/close, `WateringController` start/stop cycle, weather offline-fallback, daily report generation. All 20 assertions print `OK  <label>` and exit 0, or `FAIL  <label>` and exit 1.

### Smoke + full test suite

```bash
PYTHONIOENCODING=utf-8 python .claude/skills/run-telegram-gartenbot/smoke.py --tests
```

Runs the 33-test `unittest` suite in `tests/` after the smoke checks. Total runtime ~5 s.

### Test suite only

```bash
PYTHONIOENCODING=utf-8 python -m unittest discover -s tests
```

### Direct module invocation

Import any module directly for targeted checks without the full startup:

```python
import sys; sys.path.insert(0, 'src')
from daemon.adapters import mqtt_client, database
mqtt_client.HAS_PAHO = False   # simulation mode — must set before start_client()
database.init_db()
mqtt_client.start_client()
print(mqtt_client.client_instance.__class__.__name__)  # SimulatedMqttAdapter
```

## Run (human path — real hardware)

Requires `.env` at repo root with `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS`, `MQTT_BROKER_HOST`. Then:

```bash
PYTHONIOENCODING=utf-8 python -m daemon.main
```

Starts MQTT connection, scheduler, Telegram long-polling. Ctrl-C for clean shutdown. Not useful in headless environments without a running broker.

## Gotchas

- **`UnicodeEncodeError` on Windows**: The daily report contains emoji (📊 💧). Always set `PYTHONIOENCODING=utf-8` or call `sys.stdout.reconfigure(encoding='utf-8')` before printing. The smoke driver does this automatically.
- **`HAS_PAHO = False` must be set before `start_client()`**: Toggling it after has no effect — the adapter is instantiated during `start_client()`. Get it wrong and you see `ImportError` (if paho not installed) or a real connection attempt.
- **`garden.db` is shared**: `database.init_db()` writes to `garden.db` at the repo root. Tests that insert rows may leave data visible to later tests. The test suite clears specific tables where isolation matters; the smoke script uses unique names and deletes after.
- **Scheduler threads persist across test classes**: Call `scheduler.stop_scheduler()` before `start_scheduler()` in any test that starts the scheduler, or threads leak into the next test.
- **Weather API is live in smoke by default**: The first smoke run calls the real Open-Meteo API if the network is reachable. Returns 0.0 values on timeout (offline-first fallback). Tests mock `urllib.request.urlopen` directly.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'daemon'` | Run from repo root; `sys.path.insert(0, 'src')` must point at `src/` |
| `UnicodeEncodeError: 'charmap' codec can't encode` | Prefix with `PYTHONIOENCODING=utf-8` |
| `AttributeError: 'NoneType' object has no attribute '_active_cycle'` | `scheduler.controller` is `None`; wire up `WateringController` before calling scheduler methods |
| Tests hang on `time.sleep(3)` in test_05 | Expected — the volume-watchdog thread sleeps 2 s; test waits 3 s for it to fire |
