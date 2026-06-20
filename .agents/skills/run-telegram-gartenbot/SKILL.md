---
name: run-telegram-gartenbot
description: Run, test, or smoke-check the telegram-GartenBot daemon. Use when asked to run the app, verify a change works, run tests, or check that the scheduler/watering logic behaves correctly.
---

# run-telegram-gartenbot

Python daemon that controls Sonoff Zigbee irrigation valves via MQTT on a Raspberry Pi. The full daemon needs real hardware (MQTT broker, Zigbee dongle, Telegram token). For development and CI, the smoke driver runs the entire core in simulation mode — no broker, no hardware, no network required.

Driver: `.claude/skills/run-telegram-gartenbot/smoke.py`

## Prerequisites

```bash
pip install paho-mqtt
```

Python 3.8+ required. All other deps are stdlib (`urllib`, `sqlite3`, `threading`).

## Run (agent path)

### Smoke check — simulation mode, no hardware

```bash
PYTHONIOENCODING=utf-8 python .claude/skills/run-telegram-gartenbot/smoke.py
```

Exercises 20 checks covering: `database` CRUD, simulated MQTT valve open/close, `WateringController` start/stop cycle, scheduler lifecycle, weather offline-fallback (8-tuple), daily report generation. Each prints `  OK  <label>` or `FAIL  <label>` and exits 0/1.

### Smoke + full test suite

```bash
PYTHONIOENCODING=utf-8 python .claude/skills/run-telegram-gartenbot/smoke.py --tests
```

Runs smoke checks first, then the full `unittest` suite (385 tests across `tests/`).

### Test suite only

```bash
PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -v
```

### Direct module invocation

Import any module directly for targeted checks without the full startup:

```python
import sys, os
sys.path.insert(0, os.path.join('src'))      # enables: from daemon import ...
sys.path.insert(0, os.path.abspath('.'))     # enables: from src.daemon import ... (camera_events workaround)
from daemon.adapters import mqtt_client, database
mqtt_client.HAS_PAHO = False   # must be set before start_client()
database.init_db()
mqtt_client.start_client()
print(mqtt_client.client_instance.__class__.__name__)  # SimulatedMqttAdapter
```

## Run (human path — real hardware)

Requires `.env` at repo root with `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS`, `MQTT_BROKER_HOST`. Then:

```bash
PYTHONIOENCODING=utf-8 python -m daemon.main
```

Starts MQTT connection, scheduler, Telegram long-polling. Ctrl-C for clean shutdown.

## Gotchas

- **Two sys.path entries required**: `camera_events.py` and `camera_receiver.py` use `from src.daemon...` absolute imports, which require the repo root in `sys.path` in addition to `src/`. The smoke driver handles this; raw one-liner imports that only add `src/` will fail with `ModuleNotFoundError: No module named 'src'`.
- **`HAS_PAHO = False` must be set before `start_client()`**: Toggling it after has no effect — the adapter is instantiated during `start_client()`.
- **`WateringController` takes `publish_fn`, not the adapter**: `WateringController(bus, mqtt_client.client_instance.publish)` — not `client_instance` itself.
- **`generate_daily_report` lives in `adapters/daily_report`**: `from daemon.adapters.daily_report import generate_daily_report` — not in `scheduler`.
- **`weather.get_weather_data` returns an 8-tuple or None**: `(rain_last, rain_next, temp, code, tmin, tmax, rain_prob, rain_last_source)`. Returns `None` on network failure; handle both cases.
- **`UnicodeEncodeError` on Windows**: The daily report contains emoji. Always set `PYTHONIOENCODING=utf-8` or call `sys.stdout.reconfigure(encoding='utf-8')` before printing. The smoke driver does this automatically.
- **`garden.db` is shared**: `database.init_db()` writes to `garden.db` at the repo root. Tests that insert rows may leave data visible to subsequent tests.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'src'` | Both repo root and `src/` must be in `sys.path` — see Direct module invocation above |
| `ModuleNotFoundError: No module named 'daemon'` | `src/` must be in `sys.path` |
| `UnicodeEncodeError: 'charmap' codec can't encode` | Set `PYTHONIOENCODING=utf-8` |
| `TypeError: __init__() takes … positional arguments` | `WateringController` takes `publish_fn` callable, not the adapter object |
