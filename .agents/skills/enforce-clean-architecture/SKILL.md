---
name: enforce-clean-architecture
description: Analyzes the codebase for structural leaks (e.g., adapters importing other adapters) and strictly enforces the project's Architecture Rules using the EventBus.
---

# Enforce Clean Architecture

## Description
This skill automates the detection and resolution of architectural leaks in the codebase. It ensures that the project remains tightly aligned with the rules defined in `ARCHITECTURE.md`.

## Workflow

1. **Review Rules:**
   - Always read the project rules in `ARCHITECTURE.md` to understand the domain boundaries (e.g., Stateless Adapters, Event-Driven Side Effects).

2. **Scan for Violations:**
   - Search the `src/daemon/adapters/` directory for any imports referencing other adapters (e.g., `from .adapters import database` inside `weather.py`).
   - Search the core domain modules (`src/daemon/core/`, `src/daemon/scheduler.py`) for direct invocations of UI presentation logic (e.g., directly importing or calling `telegram_ui`).

3. **Draft a Decoupling Plan:**
   - If leaks are found, draft an `implementation_plan.md` to resolve them.
   - Propose using `EventBus` (`_global_bus`) to dispatch explicitly defined Domain Events instead of direct cross-boundary function calls.
   - Get user approval.

4. **Implement Decoupling:**
   - Replace the direct imports and function calls with event publications.
   - Create any necessary new domain events in `src/daemon/core/scheduler_events.py` or similar domain event modules.
   - Update the respective targets (e.g., the UI layer or the target adapter) to subscribe to the new event instead.

5. **Verify:**
   - Run the test suite (`python -m unittest discover tests`) to ensure no functionality is broken.
   - Update tests as necessary (e.g., mocking the `EventBus` instead of asserting direct callback invocations).

6. **Document & Commit:**
   - Generate a `walkthrough.md` detailing the architectural leaks found and how they were decoupled.
   - Commit changes referencing the Architecture Rules (e.g., `refactor: enforce stateless adapter rule by decoupling [module]`).
