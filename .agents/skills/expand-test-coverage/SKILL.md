---
name: expand-test-coverage
description: Analyzes the codebase using coverage, identifies the module with the lowest test coverage, and systematically implements new tests to improve resilience.
---

# Expand Test Coverage

## Description
This skill automates the process of identifying untested code paths and writing tests to cover them. It uses `coverage` to find the weakest links in the codebase and iteratively improves them.

## Workflow

1. **Run Coverage Report:**
   - Execute the coverage script: `scripts/run_coverage.sh` (or `scripts\run_coverage.ps1` on Windows).
   - Alternatively, manually run:
     ```bash
     python -m coverage run --source=src/daemon -m pytest tests
     python -m coverage report -m
     ```

2. **Identify Target Module:**
   - Review the generated coverage report.
   - Select the module with the lowest coverage percentage that contains domain logic (e.g., exclude pure configuration or raw UI entry points if they are meant to be thin wrappers).
   - Look at the `Missing` lines for that module to understand which specific branches or functions lack tests.

3. **Draft a Coverage Expansion Plan:**
   - Create an `implementation_plan.md` using the standard planning mode workflow.
   - Outline the specific functions or branches that will be tested.
   - Propose where the tests will live (e.g., `tests/test_irrigation.py` or a dedicated file).
   - Get user approval.

4. **Implement Tests:**
   - Write unit or integration tests targeting the missing lines.
   - Use `unittest.mock` (`patch`, `MagicMock`) to simulate external dependencies (e.g., weather API, MQTT broker, time delays).
   - Ensure the new tests do not introduce artificial delays (e.g., by patching `time.sleep`).

5. **Verify:**
   - Rerun the coverage script to confirm that the coverage percentage for the target module has significantly increased.
   - Ensure all tests still pass (`FAILED (failures=0, errors=0)`).

6. **Document & Commit:**
   - Create a `walkthrough.md` summarizing the new tests and the coverage improvements.
   - Commit the changes with a meaningful message (e.g., `test: expand coverage for [module]`).
