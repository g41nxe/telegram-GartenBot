---
name: implement-feature
description: Use when implementing a planned feature from docs/features with a corresponding docs/plans file. Triggers full project-compliance workflow including architecture checks, TDD cycle, joint test session, and moving completed docs.
---

# implement-feature

## Overview

Implements a feature from `docs/features/` guided by its plan in `docs/plans/`, under all project rules: domain language, architecture boundaries, ADRs, and TDD.

## Step 1 — Load context

Read in this order before writing a single line of code:

1. The feature spec file from `docs/features/` (named by the user or inferred from context)
2. The corresponding plan file from `docs/plans/`
3. `CONTEXT.md` — adopt exact German domain terms; never use _Avoid_ words
4. `ARCHITECTURE.md` — internalize all six rules
5. Skim `docs/adr/` — note any ADR relevant to the feature area

Then **claim the Beads issue** for this feature so the work is visible as in-progress and not picked up twice. Find it by its `Referenz:` to the feature spec (`bd list --json` and match the path, or `bd ready`), then:

```bash
bd update <issue-id> --claim
```

If no Beads issue exists yet for this feature, create one first (see `to-feature`'s Beads step) so the lifecycle stays tracked.

## Step 2 — Architecture pre-check

Before touching code, run the enforcement commands from `ARCHITECTURE.md`:

```powershell
# Rule 3: core must not import adapters
grep -r "from ..adapters" src/daemon/core/

# Rule 5: no module-level subscriptions
grep -rn "_global_bus.subscribe" src/daemon/adapters/ src/daemon/ui/
```

If the feature plan itself would introduce a violation (e.g. an adapter calling another adapter, or core importing an adapter), **stop and flag it to the user**. Describe the violation, explain the correct pattern (EventBus, callable injection), and propose an alternative. Do not proceed without explicit user confirmation.

## Step 3 — TDD cycle (Red → Green → Refactor)

For every piece of new behaviour, strictly in this order:

1. **Red** — write the test first. Run it and confirm it fails.
2. **Green** — write the minimal production code to make it pass.
3. **Refactor** — apply SOLID / SRP / Clean Code; keep all tests green.

Reference the wiring pattern in `tests/test_irrigation.py::setUpClass` when tests need `WateringController` or the scheduler.

Mark `threading.Timer` and `threading.Thread` instances as `daemon = True` (see Testing Rule §2).

## Step 4 — Incremental plan execution

Work through plan steps one at a time. After each step:

- Run the full test suite: `python -m pytest tests`
- Report result (pass count, failures) before moving to the next step
- If a step reveals an ADR conflict (the code diverges from a recorded decision), flag it with the ADR number and ask the user how to proceed

## Step 5 — Coverage check

After all plan steps are green:

```powershell
.\scripts\run_coverage.ps1
```

Coverage must not regress. If it drops, add targeted tests before declaring the implementation done.

## Step 6 — Joint test session

When all tests are green and coverage holds, **do not close out the feature silently**. Instead:

1. Summarise what was built (one short paragraph in German domain language)
2. List the test cases added and what each verifies
3. Ask the user to perform a manual smoke test or review:
   - Confirm the expected Telegram interactions work (if applicable)
   - Verify the scheduler or MQTT flow (if applicable)
   - Check any edge cases called out in the feature spec
4. Wait for the user's explicit sign-off ("passt", "fertig", "ok", or equivalent)

## Step 7 — Close out

Only after the user has confirmed the feature is done:

```powershell
Move-Item "docs/features/<feature-file>.md" "docs/features/completed/"
Move-Item "docs/plans/<plan-file>.md"       "docs/plans/completed/"
```

Then close the Beads issue claimed in Step 1, with a meaningful reason:

```bash
bd close <issue-id> --reason="<concise summary of what was implemented>"
```

Report the two moves and the closed issue ID to the user.

---

## Quick reference — common violations

| Situation | Wrong | Correct |
|---|---|---|
| Core needs to publish MQTT | `from ..adapters.mqtt_client import …` | Inject `publish` callable at wiring time in `main.py` |
| Adapter needs result from another adapter | Direct import | Publish a domain event; other adapter subscribes |
| New daemon-lifetime listener | `_global_bus.subscribe(…)` at module level | Put inside `initialize()` or `subscribe_event_handlers()` |
| Timer in production code | `threading.Timer(…)` | `t = threading.Timer(…); t.daemon = True` |

## Red flags — stop and re-read ARCHITECTURE.md

- You are about to write `from ..adapters` inside `core/`
- You are about to write `from ..` inside an adapter that references another adapter
- You are about to call a Telegram send function directly from a scheduler or core module
- You are about to place `_global_bus.subscribe(…)` outside of a function
