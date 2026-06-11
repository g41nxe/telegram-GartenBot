---
name: Enforce Clean Architecture
description: Strict architectural boundaries for adapters and domain events.
---

# Architecture Rules

When working on this codebase, you must continuously enforce the project's clean architecture rules.

You MUST read the `ARCHITECTURE.md` file in the root directory to understand the exact structural boundaries and rules.

If you detect any code that violates the rules defined in `ARCHITECTURE.md` during a task, you must automatically propose refactoring it (e.g., using the `EventBus` for decoupling) before proceeding.

## Quick violation checks

Before starting any task that touches `core/`, `adapters/`, or `ui/`, run these checks:

```powershell
# Rule 3: core must not import from adapters
grep -r "from ..adapters" src/daemon/core/
# Expected: no output

# Rule 1: adapters must not import each other
grep -rn "from \. import\|from \.\." src/daemon/adapters/ | grep -v "__init__"
# Review any cross-adapter imports manually

# Rule 4: subscribe without unsubscribe
grep -n "event_bus.subscribe\|_global_bus.subscribe" src/daemon/adapters/ src/daemon/ui/
# Every result must have a corresponding unsubscribe in the same scope
```

## Injection pattern for core I/O

When core needs to send a message (MQTT publish, etc.), inject the minimal callable — not the full adapter:

```python
# Correct: inject Callable at wiring time (main.py)
WateringController(event_bus, mqtt_client.client_instance.publish)

# Violation: core importing adapter
from ..adapters.mqtt_client import MqttClient  # NOT allowed in core/
```

## Domain state vs. protocol state in adapters

Adapters may hold **protocol state** (is the connection open? last-known hardware values such as `valve_status`, `bridge_status`). They must NOT hold **domain state** (volumes flowed, cycle durations, watering counts). The test: if swapping the adapter for a different implementation requires moving the value, it is domain state and belongs in `core/`.
