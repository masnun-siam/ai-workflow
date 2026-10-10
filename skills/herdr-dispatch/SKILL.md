---
name: herdr-dispatch
description: Dispatch a batch of GitHub issues into separate herdr tabs (one `/ai-workflow:run-issue <n>` per tab) and supervise them from this controller session — dependency order, concurrency cap, Gate 2 detection, "tab is waiting on you" notices. Use whenever the user wants to run several issues in herdr tabs, fan out run-issue, work through a label or GitHub issue-search URL, an epic's sub-issues or a list of issue numbers, or says "dispatch these issues", "run all these issues sequentially or in parallel in herdr", even if they don't name this skill.
---

# herdr-dispatch

> **Paths.** `<...>` placeholders below are keys from `aiw paths` (run it; `aiw` is
> on `PATH` via the plugin's `bin/`). Substitute the printed value; never guess a path.

You are the **controller**. Each issue runs in its own herdr tab as an independent Claude session; you launch them in a safe order, watch them, and tell the user when something needs them. You do not do the issue work, answer a tab's gates, merge, or post to GitHub.

## Inputs
`<input>` is a GitHub issues search URL, a label name, issue numbers, or one epic parent number. Flags: `--sequential` (one at a time), `--max N` (concurrency, default 2), `--cmd "<template with {n}>"` (default `/ai-workflow:run-issue {n}`), `--dry-run`, `--no-worktree` (every issue runs in the main checkout as `/ai-workflow:run-issue {n} --no-worktree`; it requires `--sequential` — without it, stop and tell the user main-tree runs go one at a time).

## Flow

1. **Context.** `herdr pane current` → `workspace_id` (tabs open here). `gh repo view --json nameWithOwner -q .nameWithOwner` → `<repo>`.
2. **Resolve.** `bash <plugin_root>/skills/herdr-dispatch/scripts/resolve.sh <repo> <input>` prints `n<TAB>title<TAB>deps` (deps = "Depends on #N" refs inside the set). Print the order once: independent issues can run together; an issue starts only after all its deps reach Gate 2 **Ready**. `--sequential` chains everything oldest-first. No confirmation prompt.
3. **Skip what is already running or done** (stateless resume): `herdr tab list` has a label ending `issue-<n>`, or the issue already has a `🤖 /run-issue report` comment. State lives in GitHub and herdr, not in a file of yours.
4. **`--dry-run` stops here** after printing the order, the launch commands and the poll plan.
5. **Launch** each startable issue while running < `--max`:
   - Clean the main checkout first (skip this with `--no-worktree`: the owner's uncommitted work rides along on purpose and run-issue's preflight allows it): `git status --porcelain`; if it lists modified tracked files, discard them **by path** with `git checkout -- <file>...` and remember the list. Untracked files stay. A wholesale `git checkout -- .` is blocked by the user's hook, and run-issue's preflight stops on a dirty tree, so skipping this makes the tab die silently.
   - `herdr tab create --workspace <ws> --cwd <repo dir> --label issue-<n>` → pane id.
   - `herdr agent start issue-<n> --kind claude --pane <pane>`, then `herdr agent prompt issue-<n> "<cmd with n>" --wait`. This confirms the command actually started; a stall is an error you can see, not a silent loss.
6. **Watch.** Run `bash <plugin_root>/skills/herdr-dispatch/scripts/poll.sh <repo> <running issues...>` with `run_in_background`, env `PREV="n=state,..."` carrying the last reported states. It exits printing `<n> <state>` on the first change:
   - `blocked` — the tab sits at a human gate (plan approval, or a finding needing confirmation). Tell the user which tab. Say it once; stay quiet until the state changes. Never answer it for them: the gates exist so a person reads the plan in context.
   - `ready` — Gate 2 report says Ready and CI is green. Rename the tab `✓ issue-<n>` with `herdr tab rename` and **leave it open** (pr-grind keeps running in it). Free the slot, clean the checkout, launch newly unblocked dependents. With `--no-worktree`, the next tab's run waits in the main-tree queue on its own (`aiw maintree acquire`) until this one's grind finishes approved and CI is green: its tab then shows `waiting for #N`, which is not `blocked`.
   - `not-ready` / `red` — mark every transitive dependent as blocked and skip them; don't build on a broken base. Free the slot.
   Restart the poll for the remaining issues after each event.
7. **Finish** when nothing is running or startable. Report per issue: PR URL and verdict, skipped dependents and why, files discarded from the checkout (this can include a lesson the run wrote to `tasks/lessons.md`), and the merge order (dependencies first; the PRs are stacked).

## Rules
- Never answer a gate, merge, or comment on GitHub from here.
- Cap concurrency: each run raises its own Docker test stack and uncapped stacks have pegged the machine.
- A Gate 2 verdict is read from the report comment, not inferred from the pane. A new push re-runs CI, so `poll.sh` reports `working` again until checks settle; that is expected.
