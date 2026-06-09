---
name: Implementation Planning Requirements
description: Guidelines ensuring all implementation plans align with project context, architecture, and previous decisions.
---

# Planning Requirements

When you are placed into "Planning Mode" and asked to create an Implementation Plan for a new feature, bug fix, or refactoring, you MUST perform the following research steps before proposing the plan:

## 1. Context and Domain Language
You MUST read `CONTEXT.md`. 
- Ensure that the terminology you use in the implementation plan perfectly matches the domain language defined in `CONTEXT.md`. 
- Avoid using prohibited terminology (the `_Avoid_` words).

## 2. Architectural Boundaries
You MUST read `ARCHITECTURE.md`.
- Ensure your proposed changes do not violate the core architectural boundaries. 
- Specifically verify that no new tight-coupling is introduced (e.g., proposing an adapter to import another adapter directly). Ensure side-effects are planned using the EventBus.

## 3. Architecture Decision Records (ADRs)
You MUST check the `docs/adr/` directory (if it exists).
- Review any relevant Architecture Decision Records to understand previous technical decisions.
- Your implementation plan must align with these established decisions. If your plan proposes a deviation, you must explicitly highlight it as a major design decision for the user to review.
