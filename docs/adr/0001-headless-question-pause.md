Decision: headless sessions ask through a dedicated `aiw ask` subcommand that records the question round to a file and ends the turn, and the session is continued later with `claude -p --resume <session_id>`. A PreToolUse hook on `AskUserQuestion` is rejected: under `claude -p` the tool is never offered to the model, so the hook never fires.

## Context

The workflow-control UI (PRD `workflow-control-ui`, FR-7, FR-8, FR-10) starts headless `claude -p` sessions. When a command reaches a gate or interview question, the session must record the question, exit, and later continue from the human's answer. Open question in the PRD: how does an `AskUserQuestion` call become a recorded question plus a process exit? Two options were on the table:

- (a) a PreToolUse hook matched on `AskUserQuestion`, injected with `--settings`
- (b) an `aiw ask` subcommand the command prose calls (via Bash) when running headless

The question shape both must carry is the `AskUserQuestion` shape: a multi-question round (several questions answered together), each with a header, a list of options (label plus description), a `multiSelect` flag, and a recommended-option marker (the label carries `(Recommended)` and is listed first). The human may always answer with an option or with free text.

## Evidence

Run with Claude Code 2.1.289 in `--print` mode (`-p`), `--model haiku`, in a throwaway git repo. The `claude` binary was called directly, not through any shell alias, so no extra permission flags leaked in. Prompt: ask a Gate-1-shaped round (Approve and start (Recommended) / Revise / Abort) plus a second question (base branch).

**Baseline, no hook.** `claude -p --output-format stream-json --verbose "<prompt>"`: exit 0. The init event lists no `AskUserQuestion` tool. The model runs `ToolSearch select:AskUserQuestion`, gets "No matching deferred tools found", and replies in prose that the tool is unavailable. With `--input-format stream-json` the model forces the call and gets:

```
{"type":"tool_result","is_error":true,"content":"<tool_use_error>Error: No such tool available: AskUserQuestion. AskUserQuestion is disabled for this session, in subagents as well as here.</tool_use_error>"}
{"type":"result","subtype":"success","terminal_reason":"completed",...}
```

`--tools default,AskUserQuestion` and `--tools AskUserQuestion` do not change this (tool still absent from init, exit 0). So headless never pauses on its own: it silently carries on with exit 0.

**Option (a), PreToolUse hook.** `--settings` with `{"hooks":{"PreToolUse":[{"matcher":"AskUserQuestion","hooks":[{"type":"command","command":"python3 hook.py"}]}]}}`, where `hook.py` logs that it ran. Run with `-p` and again with `--dangerously-skip-permissions`: exit 0 both times, the hook log file was never created. The hook never fired because the tool is never offered. The mechanism itself works; with the matcher changed to `Bash` it fired:

- exit 2: only blocks the tool. `PreToolUse:Bash hook error: ... recorded` goes back to the model as a tool error, the model retries, and the run ends `error_max_turns` with process exit 1.
- stdout `{"continue":false,"stopReason":"awaiting-answer"}`: the tool still ran (`touch` / `echo hi` executed), then `"terminal_reason":"hook_stopped"`, exit 0.
- stdout `{"continue":false,...,"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny"}}`: the tool did not run, `"terminal_reason":"hook_stopped"`, exit 0.

**Option (b), `aiw ask` stub.** A stub `aiw` on PATH reads `{"questions":[...]}` on stdin, writes `{"id","questions","status":"pending"}` to a record file, and prints `RECORDED q-... End your turn immediately`. Prompt tells the model to pipe a two-question JSON to `aiw ask` via Bash.

```
$ claude -p --model haiku --max-turns 4 --allowedTools Bash --output-format stream-json --verbose "<prompt>"
{"type":"tool_use","name":"Bash","input":{"command":"echo '{\"questions\":[{\"header\":\"Gate 1\",...}]}' | aiw ask"}}
{"type":"tool_result","content":"RECORDED q-1791314022. The question is now with the human. ..."}
{"type":"result","subtype":"success","terminal_reason":"completed","num_turns":3}
exit=0
```

The record file held both questions, all options, the `(Recommended)` label and `multiSelect`. The same run with `--dangerously-skip-permissions` (no `--allowedTools`) also recorded and exited 0.

**Resume.** `session_id` comes from the `system`/`init` event. The recorded run was continued with the answer for the whole round (option for Gate 1, free text, option for Branch):

```
$ claude -p --model haiku --max-turns 3 --resume d3eeee39-... --output-format stream-json --verbose \
    'Answer to q-1791314022: {"Gate 1":"Revise","Gate 1 other":"free text: drop task 3","Branch":"staging"}. Reply with exactly: GOT <answer>'
{"type":"system","subtype":"init","session_id":"d3eeee39-..."}
{"type":"assistant", ... "text":"GOT {\"Gate 1\":\"Revise\",\"Gate 1 other\":\"free text: drop task 3\",\"Branch\":\"staging\"}"}
exit=0
```

Same session id, the model saw the earlier turns, and no dangling tool_use problem: the `aiw ask` Bash call has a real tool_result. The `hook_stopped` session from option (a) was also resumed with `--resume` and a plain answer, exit 0 (the session survives a hook stop).

**Corner cases.**

- `aiw ask` missing: with the real `aiw` on PATH (no `ask` subcommand yet) the Bash call returned `Exit code 2 ... invalid choice: 'ask'`, the model said "Done. Awaiting answer." and the process exited 0 with no record file. A missing tool fails silently, so the engine must treat "exit 0 and no new record" as an error, never as "answered".
- asked twice: the stub overwrote its single record file; this was not experimented further. The record must therefore be append-only with a per-call `id` (see shape below), and the engine acts on the newest `pending` record; a second `aiw ask` in one session while one is pending is rejected by `aiw ask`.
- never answered: nothing consumes the record, the process is already gone (exit 0), and the session stays resumable by its `session_id`. The record with `"status":"pending"` is what the UI shows as "waiting on you". There is no timeout or hang to clean up.
- A model that does not follow "end your turn" after `aiw ask`: option (a)'s result is reusable as hardening. A PreToolUse hook on `Bash` returning `{"continue":false}` ran the command and then ended the process with `hook_stopped`, exit 0. That was verified on Bash with a stub command, not on `aiw ask`.

## Consequences

- Chosen: (b) `aiw ask`. Rejected: (a) PreToolUse on `AskUserQuestion`, because the hook cannot fire when the tool is not offered under `-p`, with or without `--dangerously-skip-permissions`. (a) would only work if the CLI re-enabled the tool headlessly, which 2.1.289 does not.
- Headless marker: the engine starts UI sessions with `AIW_HEADLESS=1` in the environment (and `AIW_RUN_DIR` pointing at the run directory). Each command's question sites say: when `AIW_HEADLESS=1`, call `aiw ask` instead of `AskUserQuestion`. Interactive runs have no marker and are unchanged: `AskUserQuestion` works exactly as today. The marker was chosen, not tested; the experiments used the stub on PATH and `AIW_RUN_DIR` only.
- Record shape written by `aiw ask` (stdin is the same `questions` array `AskUserQuestion` takes):

```json
{"id":"q-<n>","status":"pending","questions":[{"header":"Gate 1","question":"Approve plan?","multiSelect":false,"options":[{"label":"Approve and start (Recommended)","description":"..."}]}]}
```

  The answer is a message to `--resume`, one entry per question (option label or free text). A multi-question round is answered in one message.
- `--dangerously-skip-permissions` (FR-10) does not suppress capture: `aiw ask` is a Bash call, permissions do not gate it, and the experiments show the record written with and without the flag.
- Task 15 (pending question and answer API): reads the newest `pending` record, takes the whole round's answers, calls `claude -p --resume <session_id>` with them, and marks the record answered. Task 16 (emit run-issue gates as recorded questions): switches the run-issue sites to `aiw ask` under `AIW_HEADLESS=1`, and checks after each process exit that a new record exists (the `missing` case above). Task 26 (interview routing): the same for the interview commands.
- Where `aiw ask` registers: the `register` loop in `run-engine/route.py` (`for module in (stack, worktree, ..., kanban): module.register(sub, add)`, around line 396); `ask` is one more module in that tuple.
- Every `AskUserQuestion` site under `commands/` that the mechanism must cover (current lines):
  - `commands/run-issue.md`: 371 (Gate 1), 760 (escalated-finding gate), 1135 (epic Approve all / Revise child), 1202 (per parked child).
  - `commands/gh-issue.md`: 44 (grill-me interview), 62, 75, 186, 197, 204, 207.
  - `commands/intake.md`: 88.
  - `commands/jira-to-gh.md`: 106, 122, 221.
  - `commands/issue-to-pr.md`: 35.
  - `commands/pr-fix-comments.md`: 4 (allowed-tools), 36.
  - The PRD also names prd, dump and worklog interview rounds; those commands are not in this repo's `commands/` (nothing to edit here), and Task 26 must cover them wherever they live.
- The `aiw ask` subcommand and the command-prose changes are not built here; this ADR is the spike result only.
