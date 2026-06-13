# Architecture Rules

These rules govern the structural integrity of the codebase. They must be strictly adhered to during development.

## 1. Stateless Adapters
Adapters (e.g., `weather`, `database`, `mqtt_client`) MUST be stateless. They are the outer boundary of the Hexagonal Architecture. 
- They MUST NOT import other adapters directly.
- They MUST NOT maintain long-lived application state that governs domain logic.

## 2. Event-Driven Side Effects
Cross-cutting concerns and side-effects (like logging to the database, or sending UI notifications) MUST NOT be executed via direct function calls across module boundaries.
- Instead, components MUST handle side-effects by publishing Domain Events to the system's `EventBus` (Ereignis-Kanal).
- Other components (like the UI or the database adapter) should subscribe to these events independently.

## 3. Core Must Not Import from Adapters
Modules inside `core/` MUST NOT import anything from `adapters/` or `ui/`.
- Domain events that `core/` subscribes to MUST be defined in `core/`, not in the adapter that publishes them.
- When core logic needs to perform I/O (e.g. publishing an MQTT message), inject the minimal callable at wiring time in `main.py` — never import the adapter directly.

**Enforcement:** `grep -r "from ..adapters" src/daemon/core/` must return no results.

## 4. Event Listener Lifecycle
Any code path that calls `event_bus.subscribe()` inside a function scope (not at module load time) MUST call `event_bus.unsubscribe()` in a corresponding `finally` block.
- Subscriptions that outlive their intended scope are reference leaks; in a long-running daemon they accumulate and fire stale callbacks.
- `EventBus` exposes `unsubscribe(event_type, callback)` for this purpose.

## 5. Test Isolation at Transport Boundaries
Modules that subscribe to the `EventBus` at **module load time** (e.g. `telegram_ui.py`) install their handlers into the global bus the moment they are imported — including during test discovery. Any domain event published in an integration test will therefore fire those handlers and make real outbound calls (HTTP, MQTT) unless the transport layer is mocked.

- `setUpClass` of every integration test suite MUST mock all outbound I/O functions on `telegram_client` (`send_message`, `edit_message_text`, `answer_callback_query`, `broadcast_notification`, `start_polling`) before any event is published.
- The same principle applies to any future module that subscribes at import time.

**Enforcement:** `grep -r "telegram_client" tests/` must show patches for all five sending functions in every `setUpClass` that publishes domain events.

## 6. Wiring Functions Must Have Smoke Tests
Functions whose sole job is to wire modules together (e.g. `telegram_bot.start_bot()`) call functions on imported modules by name. If the target function is renamed or removed, the failure is silent until the daemon starts on the Pi.

- Every wiring function MUST have a smoke test that calls it under mocked I/O and asserts it does not raise `AttributeError`.
- When a function is removed from an adapter or core module, search for all callers before deleting it.

**Enforcement:** `tests/ui/test_telegram_ui.py::TestTelegramBotStartup.test_start_bot_does_not_raise` is the reference pattern.
