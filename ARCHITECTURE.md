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
