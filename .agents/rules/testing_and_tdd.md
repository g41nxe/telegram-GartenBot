---
name: Test-Driven Development and Coverage Enforcement
description: Strict guidelines requiring TDD methodology and maintaining/improving code coverage.
---

# Testing and TDD Rules

When working on features, bug fixes, or refactoring in this codebase, you must adhere to the following testing standards:

## 1. Test-Driven Development (TDD)
You must employ the Test-Driven Development (TDD) methodology (Red-Green-Refactor loop).
- **Rule:** Before implementing any new logic or modifying existing behavior, you MUST first write a failing test that explicitly validates the expected behavior.
- **Rule:** Only after verifying the test fails (Red) should you implement the minimal production code necessary to make the test pass (Green).
- **Rule:** Refactor the code for cleanliness and architecture adherence while ensuring tests remain green.

## 2. Code Coverage Maintenance
Test coverage is a critical metric for the system's resilience.
- **Rule:** All new domain logic and adapter integrations MUST be covered by unit or integration tests.
- **Rule:** You MUST use the provided scripts (`scripts/run_coverage.sh` or `scripts/run_coverage.ps1`) to measure test coverage after your changes.
- **Rule:** You must ensure that the overall codebase coverage does not drop as a result of your changes. If you modify a lightly-tested module, you should proactively improve its coverage where feasible.
