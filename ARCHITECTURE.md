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
