// Sequential Reviewer — implement-then-review loop
//
// This template drives a three-phase workflow per issue:
//   Phase 1 (Implement):  An agent picks an open issue, works on it on a
//                         dedicated branch, commits the changes, and signals
//                         completion.
//   Phase 2 (Review):     A second agent reviews the branch diff and either
//                         approves it or makes corrections directly on the branch.
//   Phase 3 (Integrate):  The host merges the reviewed branch back into master
//                         (local only, no push), closes the finished Beads
//                         issue(s), and refreshes issues.jsonl so the next
//                         iteration picks the next issue.
//
// Phases 1 and 2 share a single sandbox created via createSandbox(), so the
// implementer and reviewer work on the same explicit branch. Phase 3 runs on
// the host after the sandbox is closed.
//
// The outer loop repeats up to MAX_ITERATIONS times, processing one issue per
// iteration and stopping early once the backlog is exhausted (an implement
// phase that produces no commits). This is a middle-complexity option between
// the simple-loop (no review gate) and the parallel-planner (concurrent
// execution with a planning phase).
//
// Usage:
//   npx tsx .sandcastle/main.mts
// Or add to package.json:
//   "scripts": { "sandcastle": "npx tsx .sandcastle/main.mts" }

import * as sandcastle from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";
import { execSync } from "child_process";

// ---------------------------------------------------------------------------
// Host shell helpers
// ---------------------------------------------------------------------------

// execSync uses the platform default shell (cmd.exe on Windows), which handles
// the `>`, `&&`, and `||` operators used below. Passing a custom `shell` string
// like "cmd.exe /c" makes Node try to spawn an executable named "cmd.exe /c"
// (ENOENT) — so we deliberately do NOT set `shell`.

/** Run a host command, streaming its output to the console. */
const sh = (cmd: string) =>
  execSync(cmd, { stdio: "inherit" });

/** Run a host command and capture its stdout as a string. */
const shOut = (cmd: string) =>
  execSync(cmd, { encoding: "utf8" }).toString();

/**
 * Extract the Beads issue IDs the agent claimed to finish, by scanning the
 * `Closes: <ID>` lines in the commits that exist on `branch` but not yet on
 * master. Beads is read-only inside the sandbox, so this commit convention is
 * the only channel the agent has to report which issue it completed.
 */
function extractClosedIssues(branch: string): string[] {
  const body = shOut(`git log master..${branch} --format=%B`);
  const ids = new Set<string>();
  for (const m of body.matchAll(/Closes:\s*([A-Za-z0-9_-]+)/gi)) ids.add(m[1]);
  return [...ids];
}

/**
 * Refresh the git-tracked Beads artifacts the container reads, then commit them.
 *
 * - issues.jsonl: full state, kept as an audit record.
 * - ready.jsonl:  the actionable work queue. We use `bd ready` (not a jq filter
 *                 over issues.jsonl) because only Beads knows that a dependency
 *                 on a *closed* issue no longer blocks — the exported
 *                 `dependency_count` still counts closed deps.
 */
function refreshBeadsArtifacts(commitMsg: string) {
  sh("bd export > .beads/issues.jsonl");
  sh("bd ready --json > .beads/ready.jsonl");
  sh(`git add .beads/issues.jsonl .beads/ready.jsonl && git diff --cached --quiet || git commit -m "${commitMsg}"`);
}

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

// Maximum number of implement→review cycles to run before stopping.
// Each cycle works on one issue. Raise this to process more issues per run.
const MAX_ITERATIONS = 1;

// Models per phase. Kept separate so the reviewer can run on a stronger model
// than the implementer if desired.
const IMPLEMENTER_MODEL = "claude-sonnet-4-6";
const REVIEWER_MODEL = "claude-sonnet-4-6";

// Hooks run inside the sandbox before the agent starts each iteration.
// pip install ensures the sandbox always has fresh dependencies.
const hooks = {
  sandbox: { onSandboxReady: [{ command: "pip install -r requirements.txt --quiet" }] },
};

// Python projects have no node_modules to copy.
const copyToWorktree: string[] = [];

// ---------------------------------------------------------------------------
// Main loop
// ---------------------------------------------------------------------------

// Export current Beads state so the container has a fresh, correctly-filtered
// work queue (ready.jsonl) plus a full record (issues.jsonl).
try {
  refreshBeadsArtifacts("chore: Beads-Artefakte vor Sandcastle-Lauf aktualisieren");
  console.log("Beads-Artefakte exportiert und committed.");
} catch (e) {
  console.warn("Beads-Export fehlgeschlagen — Container verwendet letzten committed Stand.", e);
}

for (let iteration = 1; iteration <= MAX_ITERATIONS; iteration++) {
  console.log(`\n=== Iteration ${iteration}/${MAX_ITERATIONS} ===\n`);

  // Generate a unique branch name for this iteration.
  const branch = `sandcastle/sequential-reviewer/${Date.now()}`;

  // Create a single sandbox that both the implementer and reviewer share.
  // This gives both agents a real, named branch that persists across phases.
  const sandbox = await sandcastle.createSandbox({
    branch,
    sandbox: docker(),
    hooks,
    copyToWorktree,
  });

  try {
    // -----------------------------------------------------------------------
    // Phase 1: Implement
    //
    // The implementer agent picks the next ready issue, writes the
    // implementation (using RGR: Red → Green → Repeat → Refactor), and
    // commits the result.
    //
    // The agent signals completion via <promise>COMPLETE</promise> when done.
    // -----------------------------------------------------------------------
    // One iteration so each outer pass implements a single issue on its own
    // branch, then hands it to the reviewer. A higher value lets the agent
    // drain the whole backlog onto this one branch in a single pass, which
    // defeats the per-issue review.
    const implement = await sandbox.run({
      name: "implementer",
      maxIterations: 1,
      agent: sandcastle.claudeCode(IMPLEMENTER_MODEL),
      promptFile: "./.sandcastle/implement-prompt.md",
    });

    if (!implement.commits.length) {
      // No commits means the backlog is empty or every remaining issue is
      // blocked — there is nothing left to implement or review, so stop.
      console.log("Implementation agent made no commits. Stopping.");
      break;
    }

    console.log(`\nImplementation complete on branch: ${branch}`);
    console.log(`Commits: ${implement.commits.length}`);

    // -----------------------------------------------------------------------
    // Phase 2: Review
    //
    // The reviewer agent reviews the diff of the branch produced by
    // Phase 1. It uses the {{BRANCH}} prompt argument to inspect the right
    // branch, and either approves or makes corrections directly on the branch.
    // -----------------------------------------------------------------------
    await sandbox.run({
      name: "reviewer",
      maxIterations: 1,
      agent: sandcastle.claudeCode(REVIEWER_MODEL),
      promptFile: "./.sandcastle/review-prompt.md",
      promptArgs: {
        BRANCH: branch,
        TARGET_BRANCH: "master",
      },
    });

    console.log("\nReview complete.");
  } finally {
    await sandbox.close();
  }

  // -------------------------------------------------------------------------
  // Phase 3: Integrate (A1 — auto-merge + close)
  //
  // The sandbox is closed but the branch ref persists in the host repo.
  // Merge it back into master (LOCAL only — no push), then close the
  // finished Beads issue(s) and refresh issues.jsonl so the next iteration
  // branches from an updated master and picks the *next* issue rather than
  // redoing this one.
  // -------------------------------------------------------------------------
  const closed = extractClosedIssues(branch);

  try {
    sh(`git merge --no-ff ${branch} -m "Merge ${branch} (Sandcastle-Iteration ${iteration})"`);
  } catch {
    sh("git merge --abort");
    console.error(`Merge von ${branch} fehlgeschlagen (Konflikt). Branch bleibt erhalten, Schleife stoppt.`);
    break;
  }

  if (closed.length === 0) {
    console.warn(
      "Kein 'Closes: <ID>' im Branch gefunden — Issue-Status bleibt unverändert. " +
        "Stoppe, um Wiederholung desselben Issues zu vermeiden.",
    );
    break;
  }

  for (const id of closed) {
    sh(`bd close ${id} --reason="Von Sandcastle implementiert und reviewt (${branch})"`);
  }
  refreshBeadsArtifacts("chore: Beads-Status nach Sandcastle-Iteration aktualisieren");
  console.log(`Integriert und geschlossen: ${closed.join(", ")}`);
}

console.log("\nAll done.");
