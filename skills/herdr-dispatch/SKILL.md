---
name: herdr-dispatch
description: Dispatch a batch of GitHub issues into separate herdr tabs (one `/ai-workflow:implement-issue <n>` per tab) and supervise them from this controller session — dependency order, concurrency cap, PR-ready detection, "tab is waiting on you" notices. Use whenever the user wants to run several issues in herdr tabs, fan out implement-issue, work through a label or GitHub issue-search URL, an epic's sub-issues or a list of issue numbers, or says "dispatch these issues", "run all these issues sequentially or in parallel in herdr", even if they don't name this skill.
---

# herdr-dispatch

> **Paths.** `<...>` placeholders below are keys from `aiw paths` (run it; `aiw` is
> on `PATH` via the plugin's `bin/`). Substitute the printed value; never guess a path.

You are the **controller**. Each issue runs in its own herdr tab as an independent Claude session; you launch them in a safe order, watch them, and tell the user when something needs them. You do not do the issue work, answer a tab's gates, merge, or post to GitHub.

## Inputs
`<input>` is a GitHub issues search URL, a label name, issue numbers, or one epic parent number. Flags: `--sequential` (one at a time), `--max N` (concurrency, default 2), `--cmd "<template with {n}>"` (default `/ai-workflow:implement-issue {n}`), `--dry-run`, `--close-done` (close each tab once its issue is ready and its agent is idle, instead of keeping it open; the user may also ask for this mid-run). A `--cmd` template may name its placeholder differently (`{issue-id}`); substitute the issue number for it.

## Flow

1. **Context.** `herdr pane current` → `workspace_id` (tabs open here). `gh repo view --json nameWithOwner -q .nameWithOwner` → `<repo>`.
2. **Resolve.** `bash <plugin_root>/skills/herdr-dispatch/scripts/resolve.sh <repo> <input>` prints `repo<TAB>n<TAB>title<TAB>deps` (deps = "Depends on #N" refs inside the set). An epic's sub-issues can live in other repos (backend here, frontend elsewhere): each row names its own repo, so open that issue's tab with `--cwd` at that repo's checkout (find it next to this one, or ask), and pass it to poll.sh as `<repo>#<n>`. Also check the native blockers (`gh api repos/<repo>/issues/<n>/dependencies/blocked_by`); refined issues often carry only those. Print the order once: independent issues can run together; an issue starts only after all its deps are **ready** (open non-draft PR). `--sequential` chains everything oldest-first. No confirmation prompt.
3. **Skip what is already running or done** (stateless resume): `herdr tab list` has a label ending `issue-<n>`; an issue whose PR is already ready is done. State lives in GitHub and herdr, not in a file of yours.
4. **`--dry-run` stops here** after printing the order, the launch commands and the poll plan.
5. **Launch** each startable issue while running < `--max`:
   - If the issues name a base branch (`feature/...`) that does not exist on origin yet, push it once before the first tab: `git push origin origin/master:refs/heads/<base>` (cut from the branch the issue names). Parallel tabs told "create it if missing" race each other.
   - `herdr tab create --workspace <ws> --cwd <repo dir> --label issue-<n>` → pane id.
   - `herdr agent start issue-<n> --kind claude --pane <pane>`, then `herdr agent prompt issue-<n> "<cmd with n>" --wait`. This confirms the command actually started; a stall is an error you can see, not a silent loss.
   - If the prompt stalls, read the pane (`herdr pane read <pane>`). A fresh session can open on a "new MCP servers found in this project" dialog: ask the user once how to answer it (Enter keeps the selection, Escape rejects all), apply that to every tab, and dismiss it before typing. `agent start` can also time out before Claude is up, which drops the typed command. Poll `herdr pane read` until the input prompt shows, then send the command with `herdr pane send-text <pane> "<cmd>"` followed by `herdr pane send-keys <pane> Enter`, and check that the tab reports `working`. Keep each typed message under ~500 characters: a longer `send-text` can arrive with its head cut off (the tab saw only `…tisan …php81…`). Put extra instructions (base branch, merge policy, toolchain) in a second message, and `herdr pane read` to confirm the line starting with the slash command is there. Run `--wait` only in the foreground with a short timeout: once the command is running it blocks until the whole run ends. If the slash command sits unsent in the input after `send-keys Enter` (slash autocomplete can swallow the Enter), press Escape and resend it with `herdr agent prompt issue-<n> "<cmd>"` without `--wait`, then check the tab reports `working`.
6. **Watch.** Run `bash <plugin_root>/skills/herdr-dispatch/scripts/poll.sh <repo> <running issues...>` with `run_in_background`, env `PREV="n=state,..."` carrying the last reported states. It exits printing `<n> <state>` on the first change:
   - `blocked` — the tab sits at a human gate (a permission prompt or a question). Tell the user which tab. Say it once; stay quiet until the state changes. Never answer it for them.
   - `ready` — the issue has an open, non-draft linked PR with green checks (implement-issue marks its draft PR ready only after CI is green and review is handled). Rename the tab `✓ issue-<n>` with `herdr tab rename` and **leave it open**. Free the slot, launch newly unblocked dependents.
   - `idle` — the tab stopped with no ready PR. A tab waiting on its own background monitors counts as `working`, so `idle` means it ended its turn. Read the pane and tell the user what it is asking for. It keeps its slot.
   - `red` — the PR's checks fail. Mark every transitive dependent as blocked and skip them; don't build on a broken base. Free the slot.
   With `--close-done`, on `ready` run `herdr tab close <tab>` once its `agent_status` is `idle` or `done`, instead of renaming it. A tab still `working` after `ready` is finishing its report: close it at a later event.
   implement-issue refuses to start while a blocker is open, so a dependent can't start until the dependency's PR is **merged**, not just ready. Hold the dependent and tell the user. When the user authorises the tabs to merge (put it in the prompt; it overrides implement-issue's "never merge"), set env `BASE=<base branch>` and wait for `merged` (PR merged, the tab still closing the issue) then `done` (issue closed): `done` frees the slot and starts dependents. A PR into a non-default base never fires `Closes #n`, so the prompt must tell the tab to `gh issue close` it.
   Restart the poll for the remaining issues after each event.
7. **Finish** when nothing is running or startable. Report per issue: PR URL and verdict, skipped dependents and why, and the merge order (dependencies first; the PRs are stacked).

## Rules
- Never answer a gate, merge, or comment on GitHub from here.
- Cap concurrency (`--max`, default 2): each run builds and tests in its own worktree and uncapped runs peg the machine.
- Readiness is read from the PR, not inferred from the pane. A new push re-runs CI, so `poll.sh` reports `working` again until checks settle; that is expected.

## Self-improve

After the task, follow `../../self-improve.md` (relative to this skill's directory).
