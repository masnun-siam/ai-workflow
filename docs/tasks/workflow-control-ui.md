# Task list — Workflow Control UI

- **Source:** `docs/prd/workflow-control-ui.md` + the "Workflow Control UI" design canvas (claude.ai artifact KTawSxehhAR3hjUWwEmbxw, private)
- **Date:** 2026-10-07
- **Repo:** masnun-siam/ai-workflow
- **Label:** `prd-workflow-control-ui`

Decisions recorded while grilling (they override the PRD where they differ):
- `kanban.py` is replaced by the UI: `aiw kanban serve` is removed, not aliased.
- Reachable from a phone through `tailscale serve`; the server still binds 127.0.0.1. No app-level auth (tailnet ACLs only); Host/Origin allowlist stays, extended by `--allow-host`.
- Vanilla vendored Preact/htm, no build step, stdlib Python server. Mobile-responsive (design canvas has 390px frames).
- Notifications: browser Notification API plus ntfy (config in `<data_dir>/ui.json`, 0600). Events: waiting on you, failed, run done.
- Pause mechanism and pr-grind re-entry are spikes with ADRs; dependent tasks follow the ADR outcome.
- Sessions live in `<data_dir>/sessions/<id>/`. macOS/Linux only. Port in use fails with a clear message.

## Task 1 — Spike: record a command's question and exit under `claude -p`
Outcome: an ADR choosing between a PreToolUse hook on AskUserQuestion and an `aiw ask` command, backed by a working experiment.
Files/symbols: `docs/adr/0001-headless-question-pause.md` (new)
Acceptance criteria:
- ADR starts with a `Decision:` line and lists the rejected option with the reason
- The experiment shows a headless run-issue Gate 1 question recorded to a file with the process exiting, and `--resume <session_id>` continuing with an answer
- Covers multi-question rounds and the recommended-option marker
Verify command: `grep -q '^Decision:' docs/adr/0001-headless-question-pause.md`
Depends on: none
Issue: #103

## Task 2 — Spike: pr-grind re-entry without ScheduleWakeup/Monitor
Outcome: an ADR choosing UI-side timer vs external scheduler for pr-grind headless re-entry.
Files/symbols: `docs/adr/0002-pr-grind-headless-reentry.md` (new); reads `skills/pr-grind/SKILL.md`
Acceptance criteria:
- ADR starts with a `Decision:` line and states how re-entry survives a UI restart
- Names how the pr-grind state file (`<pr_grind_dir>/<owner>-<repo>-<pr>.md`) is reused
Verify command: `grep -q '^Decision:' docs/adr/0002-pr-grind-headless-reentry.md`
Depends on: task 1
Issue: #104

## Task 3 — Session store
Outcome: a module that creates, updates and lists session records under `<data_dir>/sessions/<id>/`.
Files/symbols: `run-engine/ui_sessions.py` (new); reuses `shared.data_dir`, `shared.write_json`
Acceptance criteria:
- `meta.json` holds command, repo path, owner/repo/issue link, claude `session_id`, pid, status, cost, start/end, pending question
- Writes are atomic; an interrupted write never leaves a corrupt meta.json
- `list_sessions()` returns newest first and survives a process restart
Verify command: `python3 run-engine/test_ui_sessions.py`
Depends on: none
Issue: #105

## Task 4 — Board data module
Outcome: the Board's pure logic and I/O edges live in a UI module with the existing behavior and tests.
Files/symbols: `run-engine/ui_board.py` (new; `build_board`, `scan_records`, `load_projects`, `memoize_title_fetcher` moved from `run-engine/kanban.py:26-136`)
Acceptance criteria:
- `build_board` output is byte-identical to `kanban.py` for the same fixtures
- Tests from `run-engine/test_kanban.py` run against the new module as `test_ui_board.py`
Verify command: `python3 run-engine/test_ui_board.py`
Depends on: none
Issue: #106

## Task 5 — `aiw ui` server skeleton
Outcome: `aiw ui` serves `/board.json` and `/api/health` on 127.0.0.1 with request guards.
Files/symbols: `run-engine/ui_server.py` (new), `run-engine/route.py` (`register` near line 396)
Acceptance criteria:
- Binds 127.0.0.1 only; `--port` default 8420; `--allow-host <name>` adds a permitted Host
- Requests with a disallowed Host, or an Origin that differs from the Host, get 403
- A taken port prints a clear message naming the owning PID/URL and exits non-zero
- `/board.json` returns the shape `{"columns":[...]}` from `ui_board`
Verify command: `python3 run-engine/test_ui_server.py`
Depends on: task 4
Issue: #107

## Task 6 — Remove `kanban`
Outcome: the old kanban server and command are gone; `aiw ui` is the only Board.
Files/symbols: `run-engine/kanban.py` (delete), `run-engine/route.py` (import at line 58, register loop at line 396), `docs/overview.html` (line 579)
Acceptance criteria:
- `aiw kanban` is no longer a subcommand; `aiw ui` still works
- `kanban.py` and `test_kanban.py` are deleted, no remaining imports
- README no longer mentions `aiw kanban serve`
Verify command: `python3 run-engine/test_scripts.py`
Depends on: task 5
Issue: #108

## Task 7 — Static serving and vendored Preact/htm
Outcome: the server serves static files from `run-engine/ui_static/`, with Preact and htm vendored.
Files/symbols: `run-engine/ui_server.py`, `run-engine/ui_static/vendor/preact.mjs`, `run-engine/ui_static/vendor/htm.mjs`
Acceptance criteria:
- `/` serves `index.html`; `/static/<path>` serves files with correct content types
- Path traversal (`/static/../`) returns 404
- Vendored files carry a header comment with version and license; no package manager is added
Verify command: `python3 run-engine/test_ui_static.py`
Depends on: task 5
Issue: #109

## Task 8 — App shell
Outcome: the header, nav, "Waiting on you" badge and polling skeleton from the design.
Files/symbols: `run-engine/ui_static/index.html`, `run-engine/ui_static/app.js`, `run-engine/ui_static/app.css`
Acceptance criteria:
- Hash router for Board, Run, Answer, Launcher, Sessions views
- Dark palette and layout match the design canvas; works at 390px width without horizontal page scroll
- Header badge shows the waiting count from `/api/sessions`
Verify command: `python3 run-engine/test_ui_static.py --view shell`
Depends on: task 7
Issue: #110

## Task 9 — Board view
Outcome: the live Board from the design (columns per Station, Cards with state chips and cost).
Files/symbols: `run-engine/ui_static/board.js`, `run-engine/ui_static/app.css`
Acceptance criteria:
- A Card moves column within one poll interval of `run.json` changing
- Chips show running / waiting / stopped / merged and the "resumed fresh" note
- At 390px the columns scroll sideways and snap one at a time
Verify command: `python3 run-engine/test_ui_static.py --view board`
Depends on: task 5, task 8
Issue: #111

## Task 10 — Headless runner
Outcome: a module that starts, tracks and stops detached `claude` sessions.
Files/symbols: `run-engine/ui_runner.py` (new); uses `ui_sessions`
Acceptance criteria:
- Starts `claude --print --output-format stream-json --verbose --dangerously-skip-permissions` in the chosen checkout as its own process group; the child keeps running if the server exits
- Writes stream events to `stream.jsonl`, and captures `session_id` and `total_cost_usd` into meta.json
- Stop sends SIGTERM to the group, then SIGKILL after 10 seconds
- Missing or logged-out `claude` is reported as a clear error at start, not a silent failure
Verify command: `python3 run-engine/test_ui_runner.py`
Depends on: task 3
Issue: #112

## Task 11 — Re-attach sessions after a UI restart
Outcome: restarting `aiw ui` loses no session.
Files/symbols: `run-engine/ui_sessions.py`, `run-engine/ui_runner.py`
Acceptance criteria:
- On startup, sessions whose pid is alive are tracked again and their live output continues
- Sessions whose pid is gone are closed as done or failed from the last stream result
- History is unchanged by a restart
Verify command: `python3 run-engine/test_ui_runner.py --restart`
Depends on: task 10
Issue: #113

## Task 12 — Sessions read API
Outcome: the endpoints the UI uses for history, detail and live output.
Files/symbols: `run-engine/ui_events.py` (new), `run-engine/ui_server.py`
Acceptance criteria:
- `GET /api/sessions` lists sessions with command, repo, outcome, cost, times
- `GET /api/sessions/<id>/stream?offset=N` returns only new events and the next offset
- Cost matches `total_cost_usd` from the session result; an unknown id returns 404
Verify command: `python3 run-engine/test_ui_events.py`
Depends on: task 3, task 5, task 10
Issue: #114

## Task 13 — Run (Ledger) read API
Outcome: a run's station timeline, plan document and totals from the Ledger.
Files/symbols: `run-engine/ui_server.py`, `run-engine/ui_board.py`
Acceptance criteria:
- `GET /api/runs/<owner>/<repo>/<n>` returns stations with status (the Ledger records no timestamps, so no durations), plan markdown from the station envelope's `handoff.plan_md`, and trace
- Read-only: nothing here writes the Ledger
- Unknown run returns 404
Verify command: `python3 run-engine/test_ui_server.py --runs`
Depends on: task 4, task 5
Issue: #115

## Task 14 — Repo list and trigger API
Outcome: start a session for a command in a validated repo.
Files/symbols: `run-engine/ui_repos.py` (new), `run-engine/ui_server.py`
Acceptance criteria:
- `GET /api/repos` lists entries from `checkouts.json` and `projects.json`
- `POST /api/sessions` rejects a path that is not a git repository, and an unknown command shape
- Starting run-issue or pr-grind for an issue with a live session returns 409 with a clear message
- The session's working directory is the chosen checkout
Verify command: `python3 run-engine/test_ui_repos.py`
Depends on: task 5, task 10
Issue: #116

## Task 15 — Pending question and answer API
Outcome: a recorded question can be shown, answered once, and continues the session.
Files/symbols: `run-engine/ui_sessions.py`, `run-engine/ui_server.py`, `run-engine/ui_runner.py`
Acceptance criteria:
- A pending question stores options, the recommended option, free-text allowed, and multi-question rounds; the session shows "waiting" with no live process
- `POST /api/sessions/<id>/answer` submits a round together and resumes with `--resume <session_id>`
- A second answer to the same round (another tab) returns 409
- An answer after the session already resumed is rejected
Verify command: `python3 run-engine/test_ui_runner.py --answer`
Depends on: task 1, task 3, task 10, task 12
Issue: #117

## Task 16 — Emit run-issue gates as recorded questions
Outcome: run-issue's Gate 1, Gate 2a and epic gates pause headless via the ADR's mechanism.
Files/symbols: `commands/run-issue.md` (gates at ~lines 371, 760, 1135), `run-engine/ask.py` (new), `run-engine/route.py`
Acceptance criteria:
- Under a headless session each gate records its question (options, recommended) and the process exits
- Interactive runs still use AskUserQuestion unchanged
- Approving Gate 1 from the UI moves run-issue to its next station
Verify command: `python3 run-engine/test_ask.py`
Depends on: task 1, task 15
Issue: #118

## Task 17 — Resume fallback
Outcome: a failed `--resume` still lets the answer through for Ledger commands.
Files/symbols: `run-engine/ui_runner.py`, `run-engine/ui_sessions.py`
Acceptance criteria:
- An unknown/expired session id or changed cwd starts a fresh session re-entering from the Ledger with the answer passed along, and the Card records "resumed fresh"
- A command without a Ledger (prd, gh-issue) is marked failed with a "Continue in terminal" action
Verify command: `python3 run-engine/test_ui_runner.py --fallback`
Depends on: task 15
Issue: #119

## Task 18 — Stop and resume API
Outcome: stop a session and re-enter a stopped run at its current station.
Files/symbols: `run-engine/ui_server.py`, `run-engine/ui_runner.py`
Acceptance criteria:
- `POST /api/sessions/<id>/stop` stops the process and marks the run stopped; the Ledger keeps its position
- Resume re-enters at the current station without repeating finished stations
- Each session exposes the copyable `claude --resume <session_id>` command and its repo path
Verify command: `python3 run-engine/test_ui_runner.py --stop`
Depends on: task 10, task 17
Issue: #120

## Task 19 — ntfy pushes and `ui.json`
Outcome: a push to the user's ntfy topic when a session needs them.
Files/symbols: `run-engine/ui_notify.py` (new), `run-engine/ui_runner.py`
Acceptance criteria:
- Reads `<data_dir>/ui.json` (`ntfy.server`, `ntfy.topic`, `ntfy.token`, `public_url`); refuses to use it if the file mode is looser than 0600
- Sends on waiting-on-you, failed, and run done; the click link opens that session under `public_url`
- An ntfy failure is logged and never fails or blocks the session; the token appears in no log or endpoint
Verify command: `python3 run-engine/test_ui_notify.py`
Depends on: task 3, task 10
Issue: #121

## Task 20 — Run detail view
Outcome: the run detail screen from the design.
Files/symbols: `run-engine/ui_static/run.js`, `run-engine/ui_static/app.css`
Acceptance criteria:
- Station timeline, live output pane, plan tab, cost and token totals
- Stop, Resume and "Continue in terminal" (copies the `claude --resume` command) actions
- Stacks to one column at 390px
Verify command: `python3 run-engine/test_ui_static.py --view run`
Depends on: task 8, task 12, task 13, task 18
Issue: #122

## Task 21 — Answer view
Outcome: answer a gate or a multi-question round from the browser.
Files/symbols: `run-engine/ui_static/answer.js`, `run-engine/ui_static/app.css`
Acceptance criteria:
- Options with the recommended one marked, plus a free-text box; a round is submitted together
- The "already answered" rejection from the API is shown without losing the typed text
- Usable one-handed at 390px; 44px minimum touch targets
Verify command: `python3 run-engine/test_ui_static.py --view answer`
Depends on: task 8, task 15
Issue: #123

## Task 22 — Header badge and browser notification
Outcome: waiting-on-you count in the header and tab title, plus a desktop notification when a session pauses.
Files/symbols: `run-engine/ui_static/notify.js` (new), `run-engine/ui_static/app.js`
Acceptance criteria:
- Count appears in the header and in `document.title`
- One Notification API notification per newly waiting session, only after permission is granted
- No notification when permission is denied or the API is unavailable (insecure context)
Verify command: `python3 run-engine/test_ui_static.py --view notify`
Depends on: task 8, task 15
Issue: #124

## Task 23 — New run form (run-issue, pr-grind)
Outcome: start run-issue and pr-grind from the browser.
Files/symbols: `run-engine/ui_static/launcher.js`, `run-engine/ui_static/app.css`
Acceptance criteria:
- Repo picker from `/api/repos` plus a manual path with the not-a-git-repo error shown inline
- The duplicate-run refusal message from the API is shown
- Submitting opens the new session within a few seconds
Verify command: `python3 run-engine/test_ui_static.py --view launcher`
Depends on: task 8, task 14
Issue: #125

## Task 24 — Session history view
Outcome: the sessions table from the design.
Files/symbols: `run-engine/ui_static/history.js`, `run-engine/ui_static/app.css`
Acceptance criteria:
- Columns: command, repo, started, ended, outcome, cost, transcript link, action
- Failed rows offer "Continue in terminal"; waiting rows offer "Answer"
- Table scrolls sideways inside its own box at 390px
Verify command: `python3 run-engine/test_ui_static.py --view history`
Depends on: task 8, task 12
Issue: #126

## Task 25 — pr-grind headless re-entry
Outcome: pr-grind keeps looping when run headless, per ADR 0002.
Files/symbols: `skills/pr-grind/SKILL.md`, `run-engine/ui_runner.py`
Acceptance criteria:
- Re-entry works without ScheduleWakeup/Monitor and reuses the pr-grind state file
- Re-entry survives an `aiw ui` restart
- Interactive pr-grind behavior is unchanged
Verify command: `python3 run-engine/test_ui_runner.py --prgrind`
Depends on: task 2, task 10
Issue: #127

## Task 26 — Interview routing for prd, intake, dump, worklog, gh-issue
Outcome: each command's interview rounds pause and surface in the UI like gates.
Files/symbols: files named by ADR 0001 (command/skill files that call AskUserQuestion), `run-engine/ask.py`
Acceptance criteria:
- A headless run of each command records its multi-question round and exits
- Answering resumes the same session; no process waits for input
Verify command: `python3 run-engine/test_ask.py --interviews`
Depends on: task 1, task 16
Issue: #128

## Task 27 — New run form: all commands and custom box
Outcome: the launcher offers every v1 command plus a free-text slash command or prompt.
Files/symbols: `run-engine/ui_static/launcher.js`
Acceptance criteria:
- Command picker lists run-issue, pr-grind, prd, intake, dump, worklog, gh-issue
- The custom box sends any slash command or prompt (e.g. `/pr-fix-comments 42`) and its questions reach the Answer view
Verify command: `python3 run-engine/test_ui_static.py --view launcher-all`
Depends on: task 23
Issue: #129

## Task 28 — Docs
Outcome: the repo documents the UI, its remote setup and the new glossary term.
Files/symbols: `CONTEXT.md`, `commands/run-issue.md` (lines 1336-1343), `README.md`
Acceptance criteria:
- `CONTEXT.md` defines "Session" next to Run and Card
- The "no daemon, no ledger service, no dashboard" rule reads "no ledger service; a local UI server is allowed"
- README documents `aiw ui`, `tailscale serve` with `--allow-host`, and `ui.json` (ntfy keys, 0600)
Verify command: `grep -q 'Session' CONTEXT.md && grep -q 'aiw ui' README.md`
Depends on: task 6
Issue: #130
