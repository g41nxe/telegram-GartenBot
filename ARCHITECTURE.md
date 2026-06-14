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
Any code path that calls `event_bus.subscribe()` inside a **function scope with limited lifetime** (e.g. a pairing worker thread, a one-shot request handler) MUST call `event_bus.unsubscribe()` in a corresponding `finally` block.
- Subscriptions that outlive their intended scope are reference leaks; in a long-running daemon they accumulate and fire stale callbacks.
- `EventBus` exposes `unsubscribe(event_type, callback)` for this purpose.
- Daemon-lifetime subscriptions live in explicit setup functions (`initialize()`, `subscribe_event_handlers()`); they never need `unsubscribe()` but MUST NOT be placed at bare module level (see Rule 5).

## 5. EventBus-Subscriptions müssen in expliziten Setup-Funktionen stehen
Dauerhaft aktive EventBus-Listener (Lebensdauer = gesamte Daemon-Laufzeit) DÜRFEN NICHT auf Modulebene registriert werden. Sie müssen in eine explizite Setup-Funktion ausgelagert sein, die ausschließlich von `main.py` aufgerufen wird.

- **Korrekt:** `watchdog.initialize()`, `telegram_ui.subscribe_event_handlers()` — explizite Initialisierung durch den Wiring-Layer (`main.py`).
- **Verboten:** `_global_bus.subscribe(...)` direkt auf Modulebene.

**Begründung:** Modulebene-Subscriptions werden beim ersten Import ausgelöst — auch während der Test-Discovery. Jedes Domain-Event, das in einem Test publiziert wird, würde damit sofort echte Telegram-Nachrichten oder MQTT-Befehle auslösen, unabhängig vom Test-Setup. Das explizite Muster entkoppelt Import von Initialisierung sauber.

**Konsequenz für Tests:** Da kein UI-Modul mehr beim Import subscribt, erzeugen Domain-Events in Tests keine Seiteneffekte. `tests/__init__.py` setzt zusätzlich `config.TELEGRAM_BOT_TOKEN = ""` als letztes Sicherheitsnetz.

**Enforcement:** `grep -rn "_global_bus.subscribe" src/daemon/ui/` darf keine Treffer auf Modulebene (außerhalb von Funktionen) liefern.

## 6. Wiring Functions Must Have Smoke Tests
Functions whose sole job is to wire modules together (e.g. `telegram_bot.start_bot()`) call functions on imported modules by name. If the target function is renamed or removed, the failure is silent until the daemon starts on the Pi.

- Every wiring function MUST have a smoke test that calls it under mocked I/O and asserts it does not raise `AttributeError`.
- When a function is removed from an adapter or core module, search for all callers before deleting it.

**Enforcement:** `tests/ui/test_telegram_ui.py::TestTelegramWiringSmoke.test_telegram_wiring_does_not_raise` is the reference pattern. The wiring under test is the inline startup sequence in `main.py`.
