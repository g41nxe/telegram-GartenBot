# Test Coverage Expansion Plan

## Goal Description
The objective is to make the codebase more resilient by increasing test coverage in critical areas. A recent coverage report showed that while our core domain model (`WateringController`, `EventBus`, `weather.py`) is well tested (>85%), other critical components like the `scheduler.py` background loops and the real `mqtt_client.py` implementation are lacking coverage.

Current state:
- `scheduler.py`: 46% coverage.
- `mqtt_client.py`: 57% coverage (tests only cover the simulated adapter).
- UI/Telegram layer: 0% coverage.

This plan focuses on writing tests for the core daemon logic first, specifically `scheduler.py` and `mqtt_client.py`, before tackling the UI layer.

## Proposed Changes

### Tests Refactoring and Additions

#### [MODIFY] tests/test_irrigation.py
Add new test cases to cover the missing branches in `scheduler.py`:
- Test the `run_scheduler_loop` logic (mocking `time.sleep` to avoid real delays).
- Test the weather-skip logic (`_check_weather_and_skip`).
- Test the daily report triggering at 08:00 AM.
- Test error handling paths within the scheduler loops.

#### [MODIFY] tests/adapters/test_mqtt_client.py
Add specific tests for the Paho MQTT implementation:
- Mock the `paho.mqtt.client.Client` and verify that `connect()`, `subscribe()`, and `publish()` behave correctly.
- Test the `_on_message` routing to ensure incoming MQTT payloads are correctly translated into domain events like `ValveStatusReported`.
- Test `_configure_safety_timeout()` to ensure the hardware timeout is set correctly on connect.

## Verification Plan

### Automated Tests
- Run `python -m unittest discover tests`
- Run `python -m coverage run -m unittest discover tests` followed by `python -m coverage report -m` to verify that `scheduler.py` and `mqtt_client.py` coverage has increased significantly (target >80%).
