---
name: verifier-locally
description: Prove a change works before it is pushed - discover the repo's checks from its CI, hooks and build files, pick the ones that match the changed paths, run them the way CI does, exercise the behaviour against the acceptance criteria and report each result with evidence. Use before committing or opening a PR, when asked to verify, validate or test a change locally, or when another skill calls for verification.
---

# Verify locally

Answers one question with evidence: would this change pass CI and does it do what the issue asks? The verifier runs checks and reports. It is not meant to change code or what is staged; fixing belongs to `/implement-issue`. Some hooks can still touch files, see the traps below.

Paths below starting `../../` are relative to this skill's folder, at the plugin root. Read first: `../../guides/engineering-workflow.md` ("Repository settings" to resolve the base branch, and "Gates"), the commands in the repo's `CLAUDE.md` or `AGENTS.md`, and the repo's `tasks/lessons.md` if it has one.

## Steps

1. **Establish the scope.** Fetch `origin/<base>`, then list what changed against it: committed changes on the branch plus anything staged or unstaged. Note which areas are touched: each component or package of the repo, and tooling (CI workflows, scripts, build files, hook config, Docker files). Uncommitted changes are fine for early feedback, but the final run is on committed work.

2. **Discover the checks.** CI is the reference: read the workflow files (`.github/workflows/` or the repo's CI config) and note, for each job, what runs, on which paths, and the exact command. Then read the hook config (`.pre-commit-config.yaml`, `.husky/`, `lefthook.yml`), the `Makefile` or task runner, and the package manifests (`package.json` scripts, `composer.json`, `pyproject.toml`, `go.mod` and the like) for checks CI runs indirectly or does not run at all. Prefer the exact command CI runs over a convenience target that looks equivalent.

3. **Build the check table** for the touched areas, one row per check, and show it before running. The kinds of row to look for:

   | Kind | Applies when | Where to find the command |
   |---|---|---|
   | Lint and format | Any source in the area changed | CI job, hook config, package scripts |
   | Typecheck or static analysis | Typed or analysed code changed | CI job, package scripts, `Makefile` |
   | Unit and integration tests | Any code in the area changed | CI job, test runner config, `Makefile` |
   | Build | Build config, routing, dependencies or entry points changed | CI job, package scripts |
   | End-to-end tests | A flow the e2e suite covers changed | CI job, e2e config |
   | Generated artifacts (API spec, schema, types) | The surface they are generated from changed | CI job |
   | Commit hooks over the branch diff | Always | Hook config, run from `origin/<base>` to `HEAD` |
   | Repo tooling and script tests | The paths CI runs them on; often every change that is not docs-only, since they read config files across the repo | CI job, `Makefile`, hook config |
   | Checks not in CI | The area has a check CI skips | `Makefile`, package scripts, the repo's docs |

   Note what CI does that cannot be reproduced locally (remote caches, separate secret-scan actions, checks on the PR body) and report it under the differences from CI.

4. **Run the checks.** Run every row that applies; do not stop at the first failure.

   Traps to know:
   - A script that decides its own scope can print "not run" or "skipped" and exit 0 without running anything. That is not a pass. Read the output, not only the exit code.
   - A convenience target (`make lint`, `make test`) can run a different command over a different scope than CI, or exit 0 when the tool is missing. Use CI's command.
   - Hooks that autofix (formatters, whitespace, end-of-file, line endings) rewrite files and can re-stage them. Run them in check-only mode where the hook supports it; if a hook still reports modified files, report that as a failure and leave the fix to `/implement-issue`.
   - A hook or check that needs a tool missing on the host (a secret scanner, a language toolchain) is not run, not passed.
   - A Docker test image can hold stale source after local edits. If a result does not match the code, rebuild the image before trusting it.
   - A shallow clone can break checks that diff against `origin/<base>`; fix with `git fetch --unshallow origin`.
   - Parallel sessions: test runs isolated per worktree (their own containers or compose project) can run at once and only compete for CPU and memory. A dev stack is not shared safely: use one of your own if the repo supports it, never the default stack or another session's.
   - Processes you start for a check (a second server, a listener, a fake tree): record their PIDs (`$!`, `pgrep -P`) and stop only those, after checking each one's command. Never kill a computed PID list unchecked, never PID 0, never `pkill` by name; other sessions run on the same machine.
   - A fresh worktree has no installed dependencies: install them first (`/implement-issue` step 3), or hooks and tests fail with missing-file or missing-module errors that have nothing to do with the change.
   - A dev stack can export environment variables that override the repo's `.env` files. To verify a change to an env file or its example, run that part with those variables unset.
   - Local caches from a running dev stack (compiled routes, config, build output) can leak into test runs. If a test fails on something the change did not touch, suspect them first.

5. **Check the behaviour, not only the checks.** For each acceptance criterion in the issue, name the test that proves it, or exercise it against the local app (started the way the repo's docs say) and record what you observed. Where data isolation applies, confirm a second tenant or user cannot see or change the data. After the run, look at the application log and the browser console for new errors.

6. **Check what tools cannot.** No debug output left behind, no new lint or type suppressions, no secrets or customer data in the diff, no committed plans or generated docs, and nothing outside the issue's scope.

7. **Report.** One line per check: the command, pass, fail or not run, and the evidence (test counts, the failing output, the reason it was not run). Then the differences from CI, then a verdict:
   - **Pass**: every applicable check ran and passed, and every acceptance criterion is covered.
   - **Fail**: at least one check failed. List the failures with their output.
   - **Incomplete**: something applicable could not be run. Say what and why.

   Never report a pass for a check that did not run, and never describe a skipped check as green.

## Stop and ask when

- A required tool is missing (Docker not running, dependencies not installed, no toolchain). Report it; do not substitute a weaker check without saying so.
- A check fails on `origin/<base>` too. Say so and show it, since the branch did not cause it.
- Making a check pass would mean changing a gate, a config or a test expectation.

## Improve this skill

Each use of this skill is also a test of it. Full rules: `../../guides/skills.md`.

- **While working**, note privately any step here that failed or misled, any kind of check that was missing from the table, any trap you hit that is not listed and would hit other repos too, and anything the user had to explain or correct that this file could have said.
- **Before you finish**, keep only findings backed by what happened in this session that would recur for the next person in any repository. Facts about one codebase or its tooling go to its `tasks/lessons.md` or docs, not here.
- **If anything is left**, tell the user what happened and propose the exact edit to this file with `AskUserQuestion`, recommended option first. If nothing is left, say nothing.
- **On approval**, apply the edit in the plugin's source repository as `../../guides/skills.md` describes, keep the file short and free of code samples, and commit it on its own as `chore: update /verifier-locally skill - <what changed>`.
- **Never** edit this file without approval, and never use an edit to weaken a gate or contradict a repo's `CLAUDE.md` or `AGENTS.md`.
