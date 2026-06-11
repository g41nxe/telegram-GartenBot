# Implementation Plan: Codebase Architecture Deepening

This plan outlines the refactoring of three key architectural friction points: consolidating watering cycle state, decoupling the notification pipeline, and separating weather API retrieval from database logging.

## User Review Required

> [!IMPORTANT]
> This refactor will completely clean up the legacy global states and callbacks (`mqtt_client.active_cycle_volume`, `scheduler.notification_callback`). All test files using these global states will be updated to test against the new interfaces or events.

## Open Questions

None. All architectural decisions were aligned and approved during the grilling session.

---

## Proposed Changes

### 1. Consolidate Watering Cycle State & Flow Integration

#### [MODIFY] [watering_controller.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/core/watering_controller.py)
- Maintain `_active_cycle_volume` (or `current_volume` inside `_active_cycle`) and `_last_flow_update_time` internally within `WateringController`.
- Implement full flow integration within `_on_valve_status_reported(event: ValveStatusReported)` using local state and the re-entrant lock `self._lock`.
- Remove any read or write access to `mqtt_client.active_cycle_volume`.

#### [MODIFY] [mqtt_client.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/adapters/mqtt_client.py)
- Remove global variables `active_cycle_volume` and `last_flow_update_time`.
- Remove legacy functions `get_active_volume()`, `reset_active_volume()`.
- Simplify global `on_message` to only update local `valve_status` variables and not perform flow integration.
- Ensure the adapter is completely stateless concerning the active watering cycle, only firing `ValveStatusReported`.

---

### 2. Decouple Notification Pipelines from Scheduler

#### [NEW] [scheduler_events.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/core/scheduler_events.py)
- Define event classes:
  - `DailyReportTriggered(Event)`: fired when the daily report timer triggers.
  - `WeatherDataFetched(Event)`: fired when new weather data is retrieved.

#### [MODIFY] [scheduler.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/scheduler.py)
- Remove `register_notification_callback` and `send_notification`.
- Remove all local event subscriptions (`_on_event_started`, `_on_event_completed`, etc.) and their user-facing string formatting.
- In `_scheduler_loop`, instead of calling `send_daily_report` directly, publish the `DailyReportTriggered` event.
- Ensure all scheduler actions are purely core logic or event publications.

#### [MODIFY] [telegram_ui.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/ui/telegram_ui.py)
- Subscribe to `WateringCycleStarted`, `WateringCycleCompleted`, `WateringCycleFailed`, and `WateringCycleStopped`.
- Format user-facing notifications for these cycle transitions and call `telegram_client.broadcast_notification`.
- Subscribe to `DailyReportTriggered`. In the callback, fetch the statistics, generate the daily report text, and broadcast it.

---

### 3. Decouple Weather Adapter from Database Persistence

#### [MODIFY] [weather.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/adapters/weather.py)
- Remove direct imports of `database`.
- Remove database logging `database.log_weather(...)` from `get_weather_data(...)`.
- Remove database fallback read `database.get_last_weather()` on exception; let the function raise the network or parsing exception to the caller.

#### [MODIFY] [database_adapter.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/adapters/database_adapter.py)
- Subscribe to the new `WeatherDataFetched` event.
- In the listener, log the weather data to the database using `database.log_weather`.

---

### 4. Tests Refactoring

#### [MODIFY] [test_irrigation.py](file:///d:/Projects/Repositories/telegram-GartenBot/tests/test_irrigation.py)
- Refactor test assertions that relied on `mqtt_client.active_cycle_volume` or `mqtt_client.get_active_volume` to assert on `WateringController.get_active_volume()` or handle events from `EventBus`.

#### [MODIFY] [test_mqtt_client.py](file:///d:/Projects/Repositories/telegram-GartenBot/tests/adapters/test_mqtt_client.py)
- Remove assertions verifying adapter-level flow integration and global variable mutation.

---

## Verification Plan

### Automated Tests
- Run existing test suites:
  `pytest tests/`
- Verify that tests run clean and pass without referencing global variables in the MQTT client.

### Manual Verification
1. Start the daemon in simulated mode.
2. Trigger manual watering through the Telegram bot. Verify that volume updates are correctly logged in the bot interface and database.
3. Verify that cycle starting, stopping, and completion notifications are successfully sent via Telegram.
4. Verify that the daily report is correctly triggered via event.
