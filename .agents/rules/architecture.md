---
name: Enforce Clean Architecture
description: Strict architectural boundaries for adapters and domain events.
---

# Architecture Rules

When working on this codebase, you must continuously enforce the project's clean architecture rules.

You MUST read the `ARCHITECTURE.md` file in the root directory to understand the exact structural boundaries and rules.

If you detect any code that violates the rules defined in `ARCHITECTURE.md` during a task, you must automatically propose refactoring it (e.g., using the `EventBus` for decoupling) before proceeding.
