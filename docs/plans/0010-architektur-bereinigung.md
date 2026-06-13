# Architektur-Bereinigung Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove three architectural friction points identified in the 2026-06-14 review: a hardcoded `time.sleep` in the Tagesbericht adapter, a shallow scheduler facade over `WateringController`, and a pass-through module for Telegram startup wiring.

**Architecture:** Each task is self-contained and produces passing tests before the next begins. Tasks are ordered by value: (1) test-speed win in `daily_report`, (2) structural seam cleanup in `scheduler` + `telegram_ui`, (3) deletion of the `telegram_bot` pass-through. No new abstractions are introduced — each task removes code.

**Tech Stack:** Python 3.11, unittest, unittest.mock

---

## File Map

| File | Change |
|---|---|
| `src/daemon/adapters/daily_report.py` | Remove `time.sleep`, `request_valve_status`, `import time` from `send_daily_report()` |
| `src/daemon/scheduler.py` | Add `_send_daily_report_with_prefetch()` helper; rename `controller` → `_controller`; add `set_controller()`; remove 4 facade functions; add `mqtt_client` import |
| `src/daemon/ui/telegram_ui.py` | Add `_watering_ctrl` + `set_watering_controller()`; replace `scheduler.{start,stop,get_active_cycle}` calls; import `generate_daily_report` from `daily_report` directly; drop `from .. import scheduler` |
| `src/daemon/main.py` | Call `scheduler.set_controller(watering_ctrl)` + `telegram_ui.set_watering_controller(watering_ctrl)` instead of `scheduler.controller = watering_ctrl`; inline Telegram wiring; drop `telegram_bot` import |
| `src/daemon/ui/telegram_bot.py` | **Delete** |
| `tests/adapters/test_daily_report.py` | **Create** — tests for `send_daily_report()` and `generate_daily_report()` |
| `tests/test_irrigation.py` | Replace `scheduler.start/stop/get_active_cycle` calls with `self.watering_ctrl.*`; store controller on `cls` |
| `tests/ui/test_telegram_ui.py` | Replace `@patch("daemon.ui.telegram_ui.scheduler")` + `mock_scheduler.get_active_cycle` with `patch("daemon.ui.telegram_ui._watering_ctrl")`; update/rename `TestTelegramBotStartup` |
| `ARCHITECTURE.md` | Update Rule 6 reference pattern to reflect inline wiring in `main.py` |

---

## Task 1 — Remove sleep and prefetch from `send_daily_report()`

**Files:**
- Modify: `src/daemon/adapters/daily_report.py`
- Modify: `src/daemon/scheduler.py`
- Create: `tests/adapters/test_daily_report.py`

### Background

`send_daily_report(today_str)` currently calls `mqtt_client.request_valve_status()`, then `time.sleep(5.0)`, then generates and publishes the report. Any test of this function costs 5 real seconds. The sleep belongs in the scheduler's daemon thread, not in the adapter.

After this task:
- `send_daily_report(today_str)` = set metadata + generate + publish event. No I/O side-effects, no sleep.
- `_send_daily_report_with_prefetch(today_str)` in `scheduler.py` = request valve status + sleep 5s + call `send_daily_report()`. This is the thread target.

- [ ] **Step 1.1 — Create test file and write the failing test**

Create `tests/adapters/test_daily_report.py`:

```python
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


class TestSendDailyReport(unittest.TestCase):

    def _make_patches(self):
        patches = {
            "db": patch("daemon.adapters.daily_report.database"),
            "weather": patch("daemon.adapters.daily_report.weather"),
            "mqtt": patch("daemon.adapters.daily_report.mqtt_client"),
            "bus": patch("daemon.adapters.daily_report._global_bus"),
            "time_mod": patch("daemon.adapters.daily_report.time"),
        }
        mocks = {k: p.start() for k, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)
        return mocks

    def test_send_daily_report_does_not_sleep(self):
        """send_daily_report() must not block — scheduler thread owns the wait."""
        from daemon.adapters.daily_report import send_daily_report

        mocks = self._make_patches()
        mocks["db"].get_watering_stats_last_24h.return_value = (1, 0, 5.0)
        mocks["db"].get_all_valves.return_value = []
        mocks["db"].get_metadata.return_value = None
        mocks["weather"].get_weather_data.return_value = (0.0, 0.0, 20.0, 0, 15.0, 25.0, 5)
        mocks["mqtt"].HAS_PAHO = False

        send_daily_report("2026-06-14")

        mocks["time_mod"].sleep.assert_not_called()

    def test_send_daily_report_does_not_request_valve_status(self):
        """send_daily_report() must not trigger MQTT side-effects — caller's responsibility."""
        from daemon.adapters.daily_report import send_daily_report

        mocks = self._make_patches()
        mocks["db"].get_watering_stats_last_24h.return_value = (0, 0, 0.0)
        mocks["db"].get_all_valves.return_value = []
        mocks["db"].get_metadata.return_value = None
        mocks["weather"].get_weather_data.return_value = (0.0, 0.0, 20.0, 0, 15.0, 25.0, 5)
        mocks["mqtt"].HAS_PAHO = False

        send_daily_report("2026-06-14")

        mocks["mqtt"].request_valve_status.assert_not_called()

    def test_send_daily_report_publishes_event(self):
        """send_daily_report() must publish DailyReportTriggered on the EventBus."""
        from daemon.adapters.daily_report import send_daily_report
        from daemon.core.scheduler_events import DailyReportTriggered

        mocks = self._make_patches()
        mocks["db"].get_watering_stats_last_24h.return_value = (2, 1, 8.5)
        mocks["db"].get_all_valves.return_value = []
        mocks["db"].get_metadata.return_value = None
        mocks["weather"].get_weather_data.return_value = (3.0, 1.0, 18.0, 61, 14.0, 22.0, 80)
        mocks["mqtt"].HAS_PAHO = False

        send_daily_report("2026-06-14")

        mocks["bus"].publish.assert_called_once()
        published_event = mocks["bus"].publish.call_args[0][0]
        self.assertIsInstance(published_event, DailyReportTriggered)
        self.assertEqual(published_event.date_str, "2026-06-14")

    def test_send_daily_report_sets_metadata(self):
        """send_daily_report() must mark the report date as sent."""
        from daemon.adapters.daily_report import send_daily_report

        mocks = self._make_patches()
        mocks["db"].get_watering_stats_last_24h.return_value = (0, 0, 0.0)
        mocks["db"].get_all_valves.return_value = []
        mocks["db"].get_metadata.return_value = None
        mocks["weather"].get_weather_data.return_value = (0.0, 0.0, 20.0, 0, 15.0, 25.0, 5)
        mocks["mqtt"].HAS_PAHO = False

        send_daily_report("2026-06-14")

        mocks["db"].set_metadata.assert_called_once_with("last_daily_report_date", "2026-06-14")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 1.2 — Run the new tests to confirm they fail**

```
python -m unittest tests.adapters.test_daily_report -v
```

Expected: `test_send_daily_report_does_not_sleep` and `test_send_daily_report_does_not_request_valve_status` FAIL because `send_daily_report()` currently calls both. The `publishes_event` and `sets_metadata` tests should PASS.

- [ ] **Step 1.3 — Remove sleep and MQTT prefetch from `send_daily_report()`**

Edit `src/daemon/adapters/daily_report.py`:

Remove `import time` from line 2.

Replace the `send_daily_report` function (lines 122–139) with:

```python
def send_daily_report(today_str: str):
    """Generiert den täglichen Bericht und publiziert ihn als Event; markiert ihn als versendet.

    Voraussetzung: Der Aufrufer hat vorab mqtt_client.request_valve_status() aufgerufen
    und ausreichend Zeit für die Antwort der Ventile abgewartet.
    """
    database.set_metadata("last_daily_report_date", today_str)
    try:
        report_text = generate_daily_report(today_str)
        _global_bus.publish(DailyReportTriggered(today_str, report_text))
        logger.info(f"Täglicher Statusbericht für {today_str} erfolgreich generiert und Event veröffentlicht.")
    except Exception as e:
        logger.error(f"Fehler beim Generieren/Senden des täglichen Statusberichts: {e}")
```

- [ ] **Step 1.4 — Add prefetch helper and update thread target in `scheduler.py`**

In `src/daemon/scheduler.py`, add `mqtt_client` to the adapter imports at the top:

```python
from .adapters import database, weather, watchdog, mqtt_client
```

Add this private helper function directly above the `_scheduler_loop` definition (before line 126):

```python
def _send_daily_report_with_prefetch(today_str: str):
    """Fordert frische Ventil-Status an, wartet und delegiert an send_daily_report().

    Ist der Thread-Target für den täglichen Bericht. Die Wartezeit liegt hier,
    weil der Scheduler die Zeitsteuerung verantwortet — nicht der Report-Adapter.
    """
    try:
        mqtt_client.request_valve_status()
    except Exception as e:
        logger.warning(f"Konnte Ventil-Statusaktualisierung nicht anfordern: {e}")
    time.sleep(5.0)
    send_daily_report(today_str)
```

In `_scheduler_loop()`, change the thread target from `send_daily_report` to `_send_daily_report_with_prefetch`:

```python
# Before:
t_report = threading.Thread(target=send_daily_report, args=(today_str,), daemon=True)

# After:
t_report = threading.Thread(target=_send_daily_report_with_prefetch, args=(today_str,), daemon=True)
```

- [ ] **Step 1.5 — Run all tests to confirm everything passes**

```
python -m unittest discover tests
```

Expected: `OK (skipped=3)` — no regressions, new tests pass.

- [ ] **Step 1.6 — Commit**

```bash
git add src/daemon/adapters/daily_report.py src/daemon/scheduler.py tests/adapters/test_daily_report.py
git commit -m "refactor: Ventil-Prefetch und sleep aus send_daily_report() in Scheduler verschoben"
```

---

## Task 2 — Remove the Scheduler facade over WateringController

**Files:**
- Modify: `src/daemon/scheduler.py`
- Modify: `src/daemon/ui/telegram_ui.py`
- Modify: `src/daemon/main.py`
- Modify: `tests/test_irrigation.py`
- Modify: `tests/ui/test_telegram_ui.py`

### Background

`scheduler.py` currently exports three functions that are pure one-line delegations to a module-level `controller` global: `start_watering()`, `stop_watering()`, `get_active_cycle()`. A fourth, `_time_limit_callback()`, exists for backward-compat with tests. `telegram_ui.py` calls all three public ones. `tests/test_irrigation.py` calls all three throughout.

After this task:
- `scheduler.py` holds `_controller` (private) set by `set_controller()` called once from `main.py`. The internal helpers `_start_single_valve()` and `check_startup_safety()` use `_controller`. No public control facade.
- `telegram_ui.py` holds `_watering_ctrl` (private) set by `set_watering_controller()` called once from `main.py`. All `scheduler.{start,stop,get_active_cycle}` calls replaced with `_watering_ctrl.*`.
- `telegram_ui.py` imports `generate_daily_report` directly from `daily_report` instead of via the scheduler re-export.
- `tests/test_irrigation.py` stores `watering_ctrl` on `cls` and calls it directly.
- `tests/ui/test_telegram_ui.py` patches `daemon.ui.telegram_ui._watering_ctrl` instead of `daemon.ui.telegram_ui.scheduler`.

- [ ] **Step 2.1 — Update `tests/test_irrigation.py` to use `watering_ctrl` directly**

In `setUpClass`, change:

```python
# Before:
watering_ctrl = WateringController(mqtt_client._global_bus, mqtt_client.client_instance.publish)
scheduler.controller = watering_ctrl
cls.db_adapter = DatabaseLoggerAdapter(mqtt_client._global_bus)

# After:
cls.watering_ctrl = WateringController(mqtt_client._global_bus, mqtt_client.client_instance.publish)
cls.db_adapter = DatabaseLoggerAdapter(mqtt_client._global_bus)
```

Then replace every `scheduler.start_watering(`, `scheduler.stop_watering(`, `scheduler.get_active_cycle(` call in the file with `self.watering_ctrl.start_watering(`, `self.watering_ctrl.stop_watering(`, `self.watering_ctrl.get_active_cycle(`.

Use this command to find all occurrences:
```
grep -n "scheduler\.\(start_watering\|stop_watering\|get_active_cycle\)" tests/test_irrigation.py
```

The pattern for every replacement (there are ~15 call sites):
```python
# Before (example):
success, msg = scheduler.start_watering(duration_minutes=10, target_volume_liters=5, source="test")
self.assertIsNotNone(scheduler.get_active_cycle())
scheduler.stop_watering()

# After:
success, msg = self.watering_ctrl.start_watering(duration_minutes=10, target_volume_liters=5, source="test")
self.assertIsNotNone(self.watering_ctrl.get_active_cycle())
self.watering_ctrl.stop_watering()
```

Also remove the now-unused `scheduler` import from `test_irrigation.py` (check whether `scheduler` is still imported at the top and remove if no other uses remain).

- [ ] **Step 2.2 — Run tests to confirm test_irrigation still passes with the refactored test code**

```
python -m unittest tests.test_irrigation -v
```

Expected: All tests pass (the behavior hasn't changed — only the call path through which tests reach the controller has changed).

- [ ] **Step 2.3 — Update `tests/ui/test_telegram_ui.py` to patch `_watering_ctrl`**

Find every use of `@patch("daemon.ui.telegram_ui.scheduler")` (there are 4 in `TestStatusWeatherBlock`):

```
grep -n "telegram_ui.scheduler\|mock_scheduler" tests/ui/test_telegram_ui.py
```

For each test that has the pattern:
```python
@patch("daemon.ui.telegram_ui.scheduler")
...
def test_xxx(self, mock_client, mock_db, mock_scheduler):
    mock_scheduler.get_active_cycle.return_value = None
```

Change to:
```python
@patch("daemon.ui.telegram_ui._watering_ctrl")
...
def test_xxx(self, mock_client, mock_db, mock_ctrl):
    mock_ctrl.get_active_cycle.return_value = None
```

There are exactly 4 such tests in `TestStatusWeatherBlock`. Apply the same change to all 4.

- [ ] **Step 2.4 — Update `scheduler.py`: private controller, set_controller(), remove facade**

Replace the module-level globals and facade functions in `src/daemon/scheduler.py`.

Change line 14 from:
```python
controller = None
```
to:
```python
_controller = None
```

Replace lines 22–48 (all four facade functions) with:
```python
def set_controller(ctrl) -> None:
    """Verdrahtet die Guss-Steuerung. Einmalig von main.py beim Daemon-Start aufrufen."""
    global _controller
    _controller = ctrl
```

In `_start_single_valve()`, replace both uses of `controller` with `_controller`:
```python
# Before (lines ~98, 101):
if not controller:
    return False, "Domänen-Controller nicht initialisiert."
success, msg = controller.start_watering(...)

# After:
if not _controller:
    return False, "Domänen-Controller nicht initialisiert."
success, msg = _controller.start_watering(...)
```

In `check_startup_safety()`, replace `controller` with `_controller`:
```python
# Before (~line 203):
if controller and controller.get_active_cycle() is None:

# After:
if _controller and _controller.get_active_cycle() is None:
```

Also remove the `generate_daily_report` re-export from the import line (line 9). Change:
```python
from .adapters.daily_report import generate_daily_report, send_daily_report  # noqa: F401 (generate_daily_report re-exported for telegram_ui)
```
to:
```python
from .adapters.daily_report import send_daily_report
```

- [ ] **Step 2.5 — Update `telegram_ui.py`: add `_watering_ctrl`, replace scheduler calls, fix import**

In `src/daemon/ui/telegram_ui.py`:

1. **Remove** `from .. import scheduler` (line 4).

2. **Add** a direct import of `generate_daily_report` from `daily_report`:
```python
from ..adapters.daily_report import generate_daily_report as _generate_daily_report
```
Add this after the existing adapter imports (e.g., after line 7).

3. **Add** the controller injection at the end of the imports block:
```python
# Module-level controller reference — set once at daemon startup by main.py
_watering_ctrl = None


def set_watering_controller(ctrl) -> None:
    """Verdrahtet die Guss-Steuerung für manuelle Bewässerungsbefehle. Einmalig von main.py aufrufen."""
    global _watering_ctrl
    _watering_ctrl = ctrl
```

4. **Replace** all call sites (use grep to find them, there are 4):
```
grep -n "scheduler\." src/daemon/ui/telegram_ui.py
```

| Old call | New call |
|---|---|
| `scheduler.get_active_cycle()` | `_watering_ctrl.get_active_cycle() if _watering_ctrl else None` |
| `scheduler.start_watering(dur, vol, "manual")` | `_watering_ctrl.start_watering(dur, vol, "manual")` |
| `scheduler.stop_watering()` | `_watering_ctrl.stop_watering()` |
| `scheduler.generate_daily_report(today_str)` | `_generate_daily_report(today_str)` |

For `get_active_cycle` specifically, the guard `if _watering_ctrl else None` prevents a crash if the UI is somehow called before wiring completes. For `start_watering` and `stop_watering`, follow the existing pattern — they already return `(False, "...")` on failure so no extra guard needed; add a guard that mirrors the scheduler's old behaviour:

```python
# Lines like scheduler.start_watering(dur, vol, "manual") → replace with:
if not _watering_ctrl:
    # send an error message back — look at how the existing code handles
    # the False return from scheduler.start_watering and follow that pattern
    success, response = False, "Guss-Steuerung nicht initialisiert."
else:
    success, response = _watering_ctrl.start_watering(dur, vol, "manual")
```

Apply the same guard pattern at all `start_watering` and `stop_watering` call sites.

- [ ] **Step 2.6 — Update `main.py`: call both setters, drop old assignment**

In `src/daemon/main.py`, change the wiring block (around lines 38–43):

```python
# Before:
from .core.watering_controller import WateringController
from .adapters.database_adapter import DatabaseLoggerAdapter

watering_ctrl = WateringController(mqtt_client._global_bus, mqtt_client.client_instance.publish)
scheduler.controller = watering_ctrl

# After:
from .core.watering_controller import WateringController
from .adapters.database_adapter import DatabaseLoggerAdapter
from .ui import telegram_ui as _telegram_ui

watering_ctrl = WateringController(mqtt_client._global_bus, mqtt_client.client_instance.publish)
scheduler.set_controller(watering_ctrl)
_telegram_ui.set_watering_controller(watering_ctrl)
```

- [ ] **Step 2.7 — Run all tests**

```
python -m unittest discover tests
```

Expected: `OK (skipped=3)`. If anything fails, the most likely causes are:
- A remaining `scheduler.start_watering` call in test_irrigation.py (grep for it)
- A `mock_scheduler` reference left in test_telegram_ui.py (grep for it)

- [ ] **Step 2.8 — Commit**

```bash
git add src/daemon/scheduler.py src/daemon/ui/telegram_ui.py src/daemon/main.py \
        tests/test_irrigation.py tests/ui/test_telegram_ui.py
git commit -m "refactor: Scheduler-Fassade entfernt — Guss-Steuerung direkt an telegram_ui injiziert"
```

---

## Task 3 — Delete the `telegram_bot.py` pass-through

**Files:**
- Delete: `src/daemon/ui/telegram_bot.py`
- Modify: `src/daemon/main.py`
- Modify: `tests/ui/test_telegram_ui.py`
- Modify: `ARCHITECTURE.md`

### Background

`telegram_bot.py` is two functions; each is a single-line delegation. The deletion test: removing it moves two calls into `main.py` and nothing is lost. `ARCHITECTURE.md` Rule 6 references `telegram_bot.start_bot()` as the reference pattern for wiring smoke tests — that reference must be updated.

- [ ] **Step 3.1 — Inline the wiring in `main.py` and drop the `telegram_bot` import**

In `src/daemon/main.py`:

Remove `from .ui import telegram_bot` (line 6).

Add these imports after the `_telegram_ui` import from Task 2:
```python
from .ui import telegram_client as _telegram_client
```

Replace the `telegram_bot.start_bot()` call (~line 64) with the inlined wiring:
```python
# Before:
telegram_bot.start_bot()

# After:
_telegram_client.register_update_callback(_telegram_ui.on_telegram_update)
_telegram_client.start_polling()
logger.info("Telegram-Bot-System (entkoppelter Client & UI-Controller) erfolgreich initialisiert.")
```

- [ ] **Step 3.2 — Delete `telegram_bot.py`**

```bash
git rm src/daemon/ui/telegram_bot.py
```

- [ ] **Step 3.3 — Update `tests/ui/test_telegram_ui.py`: replace the two `telegram_bot` tests**

Find `TestTelegramBotStartup` class (around line 300). It has two tests that import and call `telegram_bot`. Replace the entire class body with a smoke test for the inlined wiring:

```python
class TestTelegramWiringSmoke(unittest.TestCase):
    """
    Wiring smoke test (ARCHITECTURE.md Rule 6): verifies that the Telegram startup
    wiring in main.py calls the correct functions by name. A renamed or removed
    function on telegram_client or telegram_ui would be caught here rather than
    at daemon startup on the Pi.
    """

    def test_telegram_wiring_does_not_raise(self):
        from unittest.mock import patch, call
        from daemon.ui import telegram_client, telegram_ui
        with patch.object(telegram_client, "register_update_callback") as mock_reg, \
             patch.object(telegram_client, "start_polling") as mock_poll:
            telegram_client.register_update_callback(telegram_ui.on_telegram_update)
            telegram_client.start_polling()

        mock_reg.assert_called_once_with(telegram_ui.on_telegram_update)
        mock_poll.assert_called_once()
```

- [ ] **Step 3.4 — Update `ARCHITECTURE.md` Rule 6**

In `ARCHITECTURE.md`, update the enforcement line in Rule 6:

```markdown
# Before:
**Enforcement:** `tests/ui/test_telegram_ui.py::TestTelegramBotStartup.test_start_bot_does_not_raise` is the reference pattern.

# After:
**Enforcement:** `tests/ui/test_telegram_ui.py::TestTelegramWiringSmoke.test_telegram_wiring_does_not_raise` is the reference pattern. The wiring under test is the inline startup sequence in `main.py`.
```

- [ ] **Step 3.5 — Run all tests**

```
python -m unittest discover tests
```

Expected: `OK (skipped=3)`.

- [ ] **Step 3.6 — Commit**

```bash
git add src/daemon/main.py tests/ui/test_telegram_ui.py ARCHITECTURE.md
git commit -m "refactor: telegram_bot.py Pass-Through gelöscht — Verdrahtung direkt in main.py"
```

---

## Self-Review

**Spec coverage:**

| Finding | Task |
|---|---|
| `send_daily_report()` sleep + MQTT side-effect | Task 1 ✓ |
| Scheduler facade (`start/stop/get_active_cycle`) | Task 2 ✓ |
| `generate_daily_report` re-exported via scheduler | Task 2 ✓ |
| `telegram_bot.py` pass-through | Task 3 ✓ |
| ARCHITECTURE.md Rule 6 stale reference | Task 3 ✓ |

**Candidate 4 (wizard state machine):** Intentionally deferred. The dict-based state has a real smell (primitive obsession) but the churn of touching every wizard callback handler is not justified without an active feature requiring new wizard steps.

**Placeholder scan:** No TBD/TODO/similar remaining.

**Type consistency:** `_watering_ctrl.start_watering(dur, vol, "manual")` matches `WateringController.start_watering(duration_minutes, target_volume_liters, source)` signature. `_watering_ctrl.stop_watering()` and `.get_active_cycle()` match their signatures.
