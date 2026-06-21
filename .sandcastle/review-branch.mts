// Review-only — runs the Sandcastle reviewer against an EXISTING branch.
//
// Unlike main.mts (implement → review → integrate), this script does not
// implement or merge. It checks out an existing branch in a sandbox and runs
// the reviewer phase only, so we can review work an earlier run produced.
//
// The reviewer's diff (git diff {{TARGET_BRANCH}}...{{BRANCH}}, three-dot)
// compares against the merge-base, so only the branch's own changes are
// reviewed — master drift since the branch forked is excluded.
//
// Usage:
//   npx tsx .sandcastle/review-branch.mts [branch-name]

import * as sandcastle from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";

const BRANCH =
  process.argv[2] ?? "sandcastle/sequential-reviewer/1781991368410";

// The target branch predates requirements-dev.txt, so install pytest/coverage
// directly rather than via that file (which does not exist on the branch).
const hooks = {
  sandbox: {
    onSandboxReady: [
      { command: "pip install -r requirements.txt pytest coverage --quiet" },
    ],
  },
};

console.log(`Reviewing existing branch: ${BRANCH}\n`);

const sandbox = await sandcastle.createSandbox({
  branch: BRANCH,
  sandbox: docker(),
  hooks,
});

try {
  await sandbox.run({
    name: "reviewer",
    maxIterations: 1,
    agent: sandcastle.claudeCode("claude-sonnet-4-6"),
    promptFile: "./.sandcastle/review-prompt.md",
    // TARGET_BRANCH is a built-in (host branch); only BRANCH is custom.
    promptArgs: { BRANCH },
  });
  console.log("\nReview complete. Correction commits (if any) are on the branch.");
} finally {
  await sandbox.close();
}
