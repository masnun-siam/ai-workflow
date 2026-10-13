# PRD — Workflow Control UI

**Status:** Draft · **Date:** 2026-10-07 · **Repo:** masnun-siam/ai-workflow

## Overview
A local web UI for driving the ai-workflow plugin without opening Claude Code. From the browser you can start workflow commands, watch them progress on the Board, read plans, and answer every gate and question. Sessions run in headless Claude by default (`claude --print --output-format stream-json`, continued with `--resume`, the same pattern as paperclip's `claude_local` adapter). The UI is an optional layer: the CLI and interactive Claude flow keep working unchanged, and `run.json` stays the only source of truth.

Codebase context:
- `run-engine/kanban.py` already serves a read-only Board (`aiw kanban serve`, stdlib `http.server`, polls `/board.json`) with one column per Station.
- Run state lives in `<data_dir>/runs/<owner>-<repo>-issue-<n>/run.json` (the Ledger) plus per-station JSON files. `data_dir` is `$CLAUDE_PLUGIN_DATA` or `~/.claude/plugins/data/ai-workflow`. Writes go only through `aiw set`.
- `commands/run-issue.md` has three human stops (plan approval around line 371, escalated finding at line 756, final handback at §9.3), all asked through `AskUserQuestion`, which headless mode can't show.
- `run-issue.md:1336-1343` states "no daemon, no ledger service, no dashboard". This PRD narrows that rule (see Decisions).
- `pr-grind` keeps its own state file and re-enters itself through `ScheduleWakeup`/`Monitor`.

## Problem
Every workflow command has to be started and supervised from an interactive Claude Code terminal. Long runs (run-issue, pr-grind) stop at gates and wait until someone happens to look at the terminal. There's no single place to see what is running across repos, what is waiting on a person, and what each run cost. Running several things in parallel means juggling terminals.

## Users
A single developer (the plugin's owner/user) on their own machine, working across several local repos.

## Goals
- Start the v1 commands and any custom prompt from the UI, in a chosen repo, headless by default.
- See every run's progress live: the Board, a per-run detail page and session history.
- Answer every gate and question from the UI, with no session ever stuck on a prompt nobody can see.
- Be able to hand any session over to an interactive terminal at any point.

## Non-goals
- Replacing the CLI or interactive flow. Everything keeps working without the UI.
- A ledger service or a second state store. `run.json` and the per-station files stay authoritative.
- Multi-user use, auth, or remote/LAN access.
- In v1: jira-to-gh, pr-fix-comments and issue-to-pr as named commands. They can still be run through the custom command box.
- Slack notifications.

## Requirements
- **FR-1 Launch** — `aiw ui` starts the UI on 127.0.0.1 and absorbs `aiw kanban serve`.
  - Acceptance: one command opens the UI; it can't be reached from another host; the old kanban command still works or points to `aiw ui`.
- **FR-2 Trigger commands** — a form starts any of `run-issue`, `pr-grind`, `prd`, `intake`, `dump`, `worklog` or `gh-issue` with its arguments in a selected repo, as a headless Claude session.
  - Acceptance: submitting the form starts a session whose working directory is the chosen checkout, and it appears in the UI within a few seconds.
- **FR-3 Custom command** — a free-text box sends any slash command or plain prompt to a headless session in a chosen repo.
  - Acceptance: `/pr-fix-comments 42` started from the box runs, streams output, and its questions reach the UI the same way as the named commands'.
- **FR-4 Repo picker** — repos come from `checkouts.json` and `projects.json`, and a local path can be added by hand.
  - Acceptance: known checkouts are listed; a manually entered path that isn't a git repo is rejected.
- **FR-5 Board** — the home view is the existing Board (one column per Station plus done, one Card per issue's latest run), now live.
  - Acceptance: a Card changes column within one poll interval of `run.json` changing.
- **FR-6 Run detail** — clicking a Card or session shows the station timeline (from the Ledger), the live Claude output stream, the plan document, any pending question, and token/cost totals.
  - Acceptance: during a running session, new stream-json events show up live; cost matches `total_cost_usd` from the session result.
- **FR-7 Pause on question** — when a headless session reaches a gate or any question (run-issue Gates 1/2a/2, epic gates, interview rounds in prd/gh-issue/intake/dump/worklog), it records the question (options, recommended option, free-text allowed, multi-question rounds) and the process exits. The session is shown as "waiting on you".
  - Acceptance: no headless process stays alive waiting for input; the question shows up in the UI with all its options.
- **FR-8 Answer** — the UI shows the options (recommended one marked) plus a free-text box. A multi-question round is submitted together. Submitting continues the same Claude session with `--resume <session_id>`, passing the answer along.
  - Acceptance: approving a plan in the UI moves run-issue on to its next station, the same as answering in a terminal would.
- **FR-9 Resume fallback** — if `--resume` fails (unknown or expired session, changed working directory), a new headless session re-enters the command from the Ledger with the answer passed along, and the Card records the fallback. For commands without a Ledger (prd, gh-issue…), the session is shown as failed and offers "Continue in terminal".
  - Acceptance: a deleted or invalid session_id still lets a run-issue gate answer go through, and the card notes "resumed fresh".
- **FR-10 Permissions** — headless sessions run with `--dangerously-skip-permissions` by default, the same as paperclip.
  - Acceptance: no session pauses on a tool-permission prompt.
- **FR-11 Stop / resume** — stop kills a session's process (the run is marked stopped and the Ledger keeps its position); resume re-enters a stopped run at its current station.
  - Acceptance: stop followed by resume continues from the same station without repeating finished stations.
- **FR-12 Continue in terminal** — every session offers an action that copies or launches `claude --resume <session_id>` in its repo.
  - Acceptance: running the copied command opens the same conversation interactively.
- **FR-13 Session history** — every session (any command) is listed with its command, repo, start/end time, outcome, cost, and a link to its transcript/stream.
  - Acceptance: history survives UI restarts.
- **FR-14 Notifications** — a "waiting on you" count in the header, plus a browser desktop notification when a session pauses.
  - Acceptance: with the tab in the background, a pausing session triggers one desktop notification.
- **FR-15 Concurrency** — no global cap on parallel sessions. Two concurrent runs on the same issue are blocked.
  - Acceptance: starting run-issue for an issue that already has a live session is refused with a clear message.
- **FR-16 Server-independent sessions** — sessions are detached and write their stream/state to the data dir. A UI restart picks them up again.
  - Acceptance: killing and restarting `aiw ui` mid-run loses no session, and live output resumes.

## Edge cases
- The UI server crashes mid-run: sessions keep going (FR-16).
- `--resume` fails: fresh session from the Ledger, or failed + terminal handoff (FR-9).
- Duplicate trigger for the same issue: refused (FR-15).
- A question is answered twice (two tabs) or after the session was already resumed: the second answer is rejected.
- A session waits on you for days: it stays "waiting" with no process alive. The answer resumes it, or falls back to FR-9.
- `pr-grind` relies on ScheduleWakeup/Monitor, which don't exist in a session that exits. The re-entry mechanism under headless is open (see Open questions).
- The selected repo has no checkout entry, or isn't a git repo: rejected at trigger time (FR-4).
- `claude` CLI missing or not logged in: shown as a clear error at trigger time, not a silent failure.
- Skip-permissions means destructive commands aren't gated. This is accepted as the cost of running unattended (Decisions).
- The same run is being driven interactively in a terminal: the UI still shows Ledger progress, and two concurrent drivers are blocked as in FR-15 where they can be detected.

## Success metrics
- A run-issue goes from trigger to the final handback with every gate answered in the UI, without opening Claude.
- Zero sessions stuck on a prompt the UI can't see.
- In a typical week, most workflow commands are started from the UI.

## Decisions
- Headless reference is paperclip's `claude_local` adapter (stream-json + `--resume`) — it's proven and runs locally.
- The UI is an optional add-on. The "no daemon/no dashboard" rule is narrowed to "no ledger service; a local UI server is allowed" — keeps a single source of truth and the CLI path intact.
- At a gate the session pauses and its process exits; the answer resumes it — nothing sits idle burning a process or tokens.
- v1 commands: prd, intake, dump, worklog, gh-issue, run-issue, pr-grind, plus the custom box — the user's chosen set.
- Skip permissions by default — the user prefers unattended runs over permission gating.
- Non-default mode is "Continue in terminal" through `claude --resume` — keeps an interactive escape hatch.
- The custom box accepts any slash command or prompt — this covers commands not in v1.
- localhost only, no auth — single user on their own machine.
- Board + detail page for progress — reuses the existing Board.
- Unlimited concurrency, one live run per issue — the user doesn't want a queue.
- Controls: stop, resume, session history.
- Browser notification + badge — enough without Slack.
- Sessions outlive the UI server — closing the UI never kills work.
- On a resume failure, start fresh from the Ledger — run state already lives there.
- Repos come from checkouts.json + a manual path — reuses existing mappings.
- Answers are options + free text, with rounds submitted together — fits both gates and grilling interviews.
- Phased rollout — P1: Board, detail, run-issue and pr-grind with gates. P2: prd, intake, dump, worklog, gh-issue (interview routing) + custom box.

## Open questions
- How a command's `AskUserQuestion` call becomes a recorded question plus process exit under `-p` (hook, a dedicated `aiw ask` tool, or instructions in the prompt). For the spec.
- How pr-grind re-enters itself headless without ScheduleWakeup/Monitor (a UI-side timer? external scheduler?). For the spec.
- Whether to extend `run-engine/kanban.py` or build a separate UI module, and the frontend stack (stdlib-only today). For the spec.
- Where session records live (`<data_dir>/sessions/`?) and how they relate to the Ledger. For the spec.
- CONTEXT.md needs a term for a headless invocation ("Session"), alongside Run/Card.

## Related
- `commands/run-issue.md`
- `run-engine/kanban.py`, `run-engine/route.py`
- `CONTEXT.md`
- paperclip `docs/adapters/claude-local.md`
