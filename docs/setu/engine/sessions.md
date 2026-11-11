# Sessions core: behavioural spec (for the Go rewrite)

Source: `run-engine/` (ui_runner, harness_claude, ui_sessions, ask, ui_events, ui_usage, ui_settings, ui_config, ui_feed, ui_start, ui_repos, repo_skills, skill_registry(.json), ui_restart, ui_actions, ui_server, shared, route, ui_origin, ui_notify). Python 3.10 stdlib, one process, many threads, state on disk only.

Legend: **[DROP]** = feature being dropped (one line only). "Data dir" = `$CLAUDE_PLUGIN_DATA` else `~/.claude/plugins/data/ai-workflow` (`shared.data_dir()`, read on every call, never cached).

---

## 0. Data dir layout (files touched by this area)

| Path (under data dir) | Owner | Content |
|---|---|---|
| `sessions/<id>/meta.json` | ui_sessions | the session record (JSON, indent 2, trailing newline) |
| `sessions/<id>/stream.jsonl` | runner (child stdout, append) | raw `claude` stream-json, one event per line |
| `sessions/<id>/stderr.log` | runner (child stderr, append) | |
| `sessions/<id>/.lock` | ui_sessions | flock target for read-modify-write |
| `ui_settings.json` | ui_settings | settings (see section 4) |
| `issue_grind.json` | ui_settings | `{ "owner/repo"(lowercase): {"<issue>": bool} }` per-issue grind switch (own file; Settings form never rewrites it) |
| `channels.json` | external (read only here) | `{channels:{slug:slackChannelId}, bot_uid, bot_label}` seeds reviewers once |
| `checkouts.json` | dispatch | `{ "owner/repo": "/abs/path" }` repo registry (also `local/<name>` keys) |
| `products.json` | ui_products | `{docsRepoSlug: path}` |
| `ui.json` (mode 0600 enforced) | ui_config | `{ntfy:{server,topic,token,user,password}, public_url, channels:{event:{browser,ntfy,mac:bool}}}` |
| `config.json` | ui_config / shared.load_config | `{peer_review:{max_rounds,default_lenses,lenses:{name:{prompt}}}}` overrides over shipped `run-engine/config.json` |
| `pr-grind/*.md` (+`.lock`) | pr-grind skill + runner | grind state files (header `key: value` lines, then `## Round N`) |
| `afk.json`, `ui_opened.json`, `restart.log`, `restart.exit`, `migrated-dev-workflow` | misc | see sections 7, 8 |
| `peer-review/asks/ui-<UTCstamp>-<hex6>.md` | ui_repos | custom-review artifact (`## Ask\n\n<text>\n`) |

Atomic write everywhere: temp file in same dir + fsync + `os.replace`. Cross-process mutual exclusion: `flock(LOCK_EX)` on a sibling `.lock` file (`json_lock(path)` = `<path>.lock`). Corrupt JSON files are moved to `<path>.corrupt-<unix ts>` before a write (`backup_if_corrupt`); readers treat missing/corrupt as empty.

---

## 1. Launching a headless Claude session

### 1.1 Entry points (all converge on `ui_runner.start`)
`POST /api/sessions` (ui_repos.start_session), `POST /api/start` (ui_start.start, board cards), rerun, pr-grind timer re-entry, batch release, limit-timer auto-resume, panel lens sessions, Away answerer, bootstrap, dispatch lanes (others' docs).

### 1.2 `ui_runner.start(command_text, cwd, link=None, *, instructions=(), direct_effort, env_extra, pass_fds, gate_questions, claude_cmd, batch, agent, model, run_model, effort, allowed_tools, fields)` step order
1. `command_text` must be non-empty str, must not start with `-` (else ValueError).
2. `path = checkouts.get(cwd, cwd)` (cwd may be a slug or abs path); must be an existing directory, else ValueError.
3. Account: `claude_cmd or ui_origin.account_for(cwd, text, link) or ui_settings.default_cmd()` (section 3.3).
4. If `agent` or `allowed_tools` and the account harness is codex -> `AgentRefused` **[DROP codex]**. Go: harness is always `claude`; omit.
5. Create record (`ui_sessions.create`), then optional updates: `fields` (arbitrary extra record fields, applied first so even a preflight failure carries them); `run_model`/`run_effort` (stored as `run_model`, `run_effort`); `direct_model`/`direct_effort` (codex only, stored but Claude ignores on resume); `allowed_tools` (list, stored; every later spawn re-applies it).
6. **Batch cap** (`batch=(id,max)`): under `_batch_lock`, count sessions with same `batch` and status in {starting, running}; if >= max -> record gets `batch`, `batch_max`, `cwd_path`, `status:"queued"`, `note:"queued: <max> of this batch run at once"` and start returns the record (no spawn). Otherwise `batch`, `batch_max`, `cwd_path` stored and start continues.
7. **Account-limit queue**: `limits()[claude_cmd].limited_until` set AND none of {instructions, env_extra, pass_fds, agent, model, direct_effort} given -> record becomes `status:"limited"`, `limit_resets_at=until`, `auto_resume=true`, `cwd_path`, `note:"queued: account is rate limited"`; returned without spawning (limit timer starts it at reset). A Start-dialog `run_model`/`effort` alone does NOT bypass the queue (pinned by golden test).
8. `exe = _preflight(sid)`; `argv = start_argv(...)`; `_spawn(...)` with `command=repo_skills.resolve(command_text, path)` (record's `command` is overwritten with the resolved text; queued/limited records keep raw text until they start), `cwd_path=path`.

### 1.3 Preflight (every spawn and resume, synchronous, up to 30 s)
`exe = ui_settings.argv(claude_cmd)` then run `[*exe, "auth","status","--json"]` (timeout 30s); stdout JSON must be an object with `loggedIn === true`. Failure -> record `status:"failed"`, `error`, `ended_at`, then raise `RunnerError`. Messages:
- argv failure: default cmd -> `claude CLI not found on PATH`; other -> `claude command '<cmd>' unusable: <err>`.
- not logged in: default -> ``claude CLI is not logged in, run `claude auth login` ``; other -> ``... run `<cmd> auth login` ``; timeout/OS/JSON error appends ` (auth status check failed: <e>)`.

### 1.4 Exact argv

`BASE = ["--print","--output-format","stream-json","--verbose","--dangerously-skip-permissions"]`.
Permission model: **there is no interactive permission handling**. Sessions run with the bypass flag. If `allowed_tools` is set, the bypass flag is removed and `["--allowedTools", ",".join(tools)]` is appended after BASE (one comma-joined value because the flag is variadic and would eat the prompt). Used by lens and Away-answerer sessions (read-only agents; tool list comes from the `tools:` line of `agents/<name>.md`, split on `", "`).

`HEADLESS_PROMPT` (exact text, appended via `--append-system-prompt`):
```
Headless run: ask via aiw ask. AskUserQuestion is not available: wherever a skill says to ask the user with AskUserQuestion, run `aiw ask --json '<the AskUserQuestion input>'` instead, then end your turn; the answer arrives as your next message. Never call ScheduleWakeup: a pending wakeup keeps this process alive, and the UI cannot take an answer until it exits.
```

Fresh start (`start_argv`): `[*exe, *BASE', *(--append-system-prompt "\n\n".join(instructions) if instructions), *(--effort <direct_effort>), *(--agent <agent>), *(--model <model>), *(--model <run_model>), *(--effort <run_effort>), <prompt>]` where BASE' is BASE or the allowedTools variant. `instructions = [HEADLESS_PROMPT if gate_questions] + extra` (extra = grind re-entry text). Note ordering: direct `--effort` then `--agent` then direct `--model` then run `--model`/`--effort`. `allowed_tools` falls back to the record's.
Resume (`resume_argv`): `[*exe, *BASE', "--append-system-prompt", HEADLESS_PROMPT, *(--model run_model), *(--effort run_effort), "--resume", <claude session_id>, <prompt>]`. `--agent` and the direct (non-run) `--model` are NOT re-added. The Away answerer's `--effort medium` survives resume only because it is also stored as `run_effort`; its golden resume argv is `RESTRICTED --allowedTools AWAY_TOOLS --append-system-prompt HEADLESS --effort medium --resume sess-A again`.
Resume ALWAYS adds HEADLESS_PROMPT (even for a session that started without gate).
Prompt is the last positional argument. No stdin (`stdin=DEVNULL`). Never a shell; argv list only.

Golden argv (pinned, `test_harness_golden.py`):
| Path | argv after exe |
|---|---|
| start plain | `BASE "/ai-workflow:implement-issue 1"` |
| start gated | `BASE --append-system-prompt HEADLESS <prompt>` |
| start gated + run model/effort | `BASE --append-system-prompt HEADLESS --model opus --effort high <prompt>` |
| allowed_tools | `--print --output-format stream-json --verbose --allowedTools "Read,Bash(git status:*)" go` |
| answer resume | `BASE --append-system-prompt HEADLESS [--model M --effort E] --resume <sid> "Answer to q-1: x"` |
| Continue (stopped) | `BASE --append-system-prompt HEADLESS --model opus --effort high --resume <sid> "Continue from where you were stopped."` |
| Continue, limited before any session id | fresh `_restart_argv`: `BASE(or RESTRICTED+allowedTools) --append-system-prompt HEADLESS [--model --effort] <resolved command>` |
| batch start | same as `_restart_argv` |
| lens | `RESTRICTED --allowedTools <peer-reviewer tools> --agent ai-workflow:peer-reviewer --model opus <prompt "Review the artifact at <path> through the <lens> lens...">` |
| Away answerer | `RESTRICTED --allowedTools <away tools> --agent ai-workflow:away-answerer --model opus --effort medium "Answer the question round below..."` (role=`away-answerer`) |
| pr-grind re-entry | `BASE --append-system-prompt REENTRY "/ai-workflow:pr-grind <slack thread url>"`; env `AIW_HEADLESS=1`; pass_fds=[lock fd] |
| headless dispatch lane (others' doc) | `BASE --append-system-prompt HEADLESS --effort high --model opus <prompt>` |

REENTRY text: `This is an automated headless pr-grind re-entry from the aiw ui timer. Take the On-wake branch, never clear `paused:`, never call ScheduleWakeup or Monitor, follow the headless steps in SKILL.md, then exit. A stop that needs a human decision is asked through `aiw ask` as Step 8 says; any other stop stays a plain paused stop.`

`gate_questions=True` is passed by `ui_repos.start_session` (all UI-started sessions). Starts from the grind timer, panels etc. do not pass it (they rely on `instructions`).

### 1.5 Process spawn (`_spawn`)
- `Popen(argv, cwd=<checkout path>, stdin=DEVNULL, stdout=<stream.jsonl append>, stderr=<stderr.log append>, start_new_session=True, close_fds=True, pass_fds=pass_fds, env=...)`. The child writes straight to the files (survives the UI process). New session => it is its own process-group leader; pgid == pid.
- Env = `os.environ` +
  - `PATH = <plugin>/bin : $PATH` (so `aiw` is found)
  - `AIW_UI_SESSION = <ui session id>` (this is how `aiw ask` finds the record)
  - `CLAUDE_PLUGIN_DATA = <data dir>`
  - `BLUBIRD_IDLE_GUARD = off`
  - `env_extra` (e.g. `AIW_HEADLESS=1` for the grind re-entry)
  - NOT set: `CLAUDE_CONFIG_DIR`. The account is selected solely by the command (`cc <profile>` -> `cc-profile <profile>`, an external script that selects the profile dir).
- Spawn failure (OSError/ValueError) -> `failed`, error `failed to spawn claude: <e>`, RunnerError.
- Success: record updated `pid`, `pid_started` (string from `ps -o lstart= -p <pid>` with `LC_ALL=C`, timeout 5s; used as pid-reuse fingerprint, 1 s resolution), `status:"running"`, plus caller fields. `_procs[sid] = Popen`. A daemon thread `_follow` starts with `offset = size of stream.jsonl before spawn` (so resumed runs only read new lines).

### 1.6 Prompt building / skill resolution
See section 5. `harness.skill_text(text, cwd) = repo_skills.resolve(text, cwd)` is what is sent; for resumes the record's stored `command` stays unchanged and the answer text is also resolved.

### 1.7 Stream parsing (`harness_claude.parse_line` over `ui_events.parse_line`)
Each line is JSON (invalid JSON / non-object lines are silently ignored). Events produced (internal "kinds"):

| stream-json line | event(s) |
|---|---|
| `type=assistant`, `message.content[]` block `type=text` (str) | `{kind:"text", text}` |
| same, block `type=tool_use` with str `name` | `{kind:"tool", name, input}` |
| `type=result` | `{kind:"result", cost: total_cost_usd (number, not bool, else None), is_error: bool(is_error), text: result (str|None), tokens}`; plus below |
| `type=system, subtype=init` | `{kind:"session_id", id: session_id, model: model if non-empty str else None}` (appended after other events) |
| `type=rate_limit_event` with object `rate_limit_info` | `{kind:"limit", resets_at: int(resetsAt) if number (not bool) else None, type: rateLimitType, info: <whole info object>}` (this is the only event returned) |
| result with `is_error` and non-empty `errors` list | each result event gets `error = str(errors[0])` |
| result whose `permission_denials[]` contains `tool_name` in {Edit,Write,MultiEdit,NotebookEdit} with `tool_input.file_path` (or `notebook_path`) whose basename lowercased is `claude.md`/`agents.md` | extra `{kind:"guard_ask", edits:[denial,...]}` placed BEFORE the result event |
| result whose `result` text starts with `UserPromptSubmit operation blocked by hook:` | extra `{kind:"prompt_blocked", reason}`, reason = text after the prefix up to `\n\nOriginal prompt:`, stripped, default `the prompt holds a secret` |
All other event types (`user`/tool_result, etc.) are ignored by the parser (they stay in stream.jsonl; `ui_origin` re-reads raw lines).

`tokens_of(usage)` -> `{input, cached, output}`: `input = input_tokens + cache_creation_input_tokens + cache_read_input_tokens`, `cached = cache_read_input_tokens`, `output = output_tokens`; non-int/negative/bool counted 0; `None` if usage is not an object or input and output are both 0.

Fixtures: `fixtures/claude_guard_ask.jsonl` (Edit of `@ROOT@/CLAUDE.md` denied; result carries `permission_denials`), `fixtures/claude_secret_block.jsonl` (result `UserPromptSubmit operation blocked by hook:\n...\n\nOriginal prompt: ...`).

Transcript view (`GET /api/sessions/<id>/stream`) keeps only kinds `text`, `tool`, `result` and strips the `error` key.

### 1.8 Follower thread (`_follow`) — the state machine driver
One daemon thread per spawned/re-attached process. Poll every `POLL_SECONDS=0.2` while the process is alive: read new bytes from `stream.jsonl` from `offset`, split on `\n`, keep the unterminated tail in `buf`, feed each whole line to parse_line. After exit: drain once more (FileNotFoundError tolerated only for re-attached), flush `buf` if non-blank.

Per-process locals reset on every `session_id` event (so a replayed stream after a UI restart only counts the last process): `asked`, `guard`, `blocked`, `saw_result`, `is_error`, `run_tokens`.

Event handling:
- `session_id`: `update(session_id=id)`; `update(model=...)` if present. `saw_init=true`.
- `tool`: `asked |= (name=="Bash" and input.command.lstrip().startswith("aiw ask"))`.
- `guard_ask`: remember first edit only (warn if more).
- `prompt_blocked`: remember reason.
- `limit`: `_usage[cmd] = info` (in-memory per claude command; lost on restart). If `info` is not an object, or `info.status` not in {None, "allowed", "allowed_warning"} -> remember as `limit` (the rejection).
- `result`: `is_error`, `saw_result`. First error text (`error` > `text` > `"claude reported an error"`) stored as `first_err`. Claude accounting: `run_tokens` = sum of every result's tokens since the last session_id event; `update(cost=ev.cost, tokens=run_tokens)` — **cost and tokens are overwritten, not accumulated across resumes** (`tokens` is per latest process; `cost` is the last result's `total_cost_usd`, may overwrite with null).
- Reap (asked exit grace): if a result was seen with no error, `asked` is true, and `ASKED_EXIT_GRACE_SECONDS=30` has passed since first seeing that, AND record status is `waiting`, send SIGTERM to the process group once (claude --print otherwise waits on background tasks); exit code then treated as 0.

Outcome decision when the process is gone (skipped entirely if `sid in _stopping` or record status already `stopped`), in this order:
1. `is_error` and (a `limit` event seen OR `first_err` matches `/usage limit|limit reached|rate.?limit|hit your limit/i`) -> `_mark_limited` (section 2.3).
2. (`answer` given or `resuming`) and rc != 0 and no `session_id` event seen and `first_err` is not None -> `failed`, `ended_at`, `pending_question=None`, `error="cannot resume: <first_err>"`.
3. re-attached (no Popen) and not (result seen and not error) -> `failed`, `pending_question=None`, `error="claude exited while the UI was down without a successful result; see stderr.log"`.
4. (rc==0 or re-attached) and not is_error:
   - `blocked` -> `failed`, clears `pending_question` and `pending_answer`, `error="blocked by mask-secrets: <reason>"`.
   - record status `waiting` (child `aiw ask` set it) -> stay waiting; set `ended_at=now`, `pending_answer=None`, `limit_backoff=None` (ended_at unlocks the answer form).
   - `guard` and `_relay_guard` true -> `ended_at=now`, `pending_answer=None`, `limit_backoff=None` (status becomes `waiting` via set_pending, see 1.10).
   - `asked` but nothing recorded -> `failed`, `error="aiw ask ran but recorded no question; see stream.jsonl"`.
   - else -> `done`, `ended_at`, `pending_answer=None`, `limit_backoff=None`.
5. else -> `failed`, `ended_at`, `pending_question=None`, `error="claude exited with code <rc>; see stderr.log"`.
Then always `_deliver_queued(sid)` (section 2.5). In `finally`: if `_procs[sid]` is this proc, pop it and discard from `_stopping`; then `release_batch(rec.batch)`.
Any exception in the thread: warn; if status is starting/running and not stopping -> `failed`, `error="follower failed: <e>"`.

### 1.9 Questions (AskUserQuestion / gate questions) and answers
Mechanism: **no stdin and no control channel**. Headless prompt tells the model to run the CLI `aiw ask --json '<AskUserQuestion input>'` (Bash tool) and end its turn.
- `aiw ask [--json STR]` (payload from `--json` or stdin): reads `AIW_UI_SESSION`; if missing/invalid/unknown record -> stderr message `aiw ask needs a UI session (AIW_UI_SESSION); interactive runs use AskUserQuestion`, exit 2. Payload must be a JSON object (else ValueError -> exit 5 via route). If the record is already `waiting` with a `pending` round: identical signature (list of (question text, [option labels])) -> reuse the same round id (idempotent); different -> stderr `a question round (<rid>) is already waiting for the human; end your turn and wait for its answer instead of asking again`, exit 2. Otherwise new round id `q-<8 hex>` and `ui_sessions.set_pending(sid, {id, questions: payload.questions})`. Prints `RECORDED <rid>. The question is now with the human. End your turn immediately; the answer arrives as your next message: Answer to <rid>: {...}` exit 0. **The CLI writes meta.json directly (cross-process, via flock), and triggers the `waiting` notification from that process.** Go: keep `aiw ask` as a subcommand of the same binary writing the same record format.
- `set_pending` validation (ValueError): round object with non-empty str `id`; non-empty `questions` list of objects; `multiSelect`, `allowFreeText` must be bool if present (defaults false/true); `options` non-empty list of objects with non-empty unique `label`; kept option fields `label`, `description`, optional str `preview`. Stored round: `{id, status:"pending", allowFreeText:true, questions:[{header, question, multiSelect, options, recommended (first option label ending "(Recommended)" else null), allowFreeText}]}` plus `held:true` when held. Sets `status:"waiting"`, `pending_question`.
- Follower: a turn that ended with status already `waiting` keeps `waiting`.
- Answer flow `POST /api/sessions/<id>/answer` body `{round_id, answers}` (checks in order): 404 unknown session; 415 Content-Type not `application/json*`; 400 missing/invalid Content-Length; 413 > 65536; 400 body not an object; 409 not `waiting` or no pending object; 409 `session process is still running` (sid in `_procs`); 409 no `session_id`; 400 `round_id required`; 409 `round_id is not the current pending round`; 400 `answer_text` errors; 409 account refused (`resume_target`); 409 `round already answered` (atomic `claim_answer` lost); then `guard_resume_text` + `ui_runner.resume`; RunnerError/ValueError/OSError -> 500; success 200 `_public(rec)`.
- `answers` shape: object with exactly keys `"0".."n-1"`; each value exactly one of `{labels:[...]}` (non-empty unique strings, each an option label, single-select allows 1, no NUL), `{other:"free text"}` (needs `allowFreeText`, non-empty, no NUL, <=4000 chars, valid UTF-8), `{none:true}` (multi-select only; becomes `{other:"None of these"}`).
- Text fed back: `Answer to <round id>: <compact JSON of {idx: {labels:[..]}|{other:".."}}>` (`json.dumps(ensure_ascii=False, separators=(",",":"))`). It is delivered as the **prompt argument of a new process** `claude ... --resume <session_id> <text>` (section 1.4), after `claim_answer` set `pending_question=None, status="starting"`. `resume()` also sets `ended_at=None,error=None,pending_answer=<text>,resumed_fresh=None,note=None,terminal_handoff=None,tokens_base=rec.tokens_total`.
- `claim_answer` is an atomic compare-and-set under the record flock: requires status `waiting`, pending round `status=="pending"` and id match; else returns None.
- Helpers: `restore_round(sid, pq)` (re-pend a claimed round as `held`, only if still `starting`/`failed` with no pending round, clears `error`), `update_pending(sid, round_id, **fields)` (set fields on the pending round only while still that waiting round).

### 1.10 CLAUDE.md / AGENTS.md guard relay (FR-5)
When a result carries `guard_ask` (a protected root-file edit denied headless) and the session otherwise ended OK: `_relay_guard` creates a held (never auto-answered by Away/AFK) round `id = "guard-<tool_use_id|4 random hex>"`, one question `header:"Protected file"`, `multiSelect:false`, `allowFreeText:false`, options `Approve` ("Apply this edit") / `Deny` ("Leave the file unchanged"), question text = reason + file path (backticked unless it contains a backtick; with `(the file written: <realpath>)` when symlinked) + fenced `diff` of the change (`- old` / `+ new` per edit, Write shows `New content:\n<content>`; truncated at 1500 chars with `… N more characters not shown; Approve applies all of it`). The denied edit is stored on the record as `guard_edit` `{tool_name, tool_input, tool_use_id}`. Only for tools Edit/Write/MultiEdit and a path that is the cwd's root `CLAUDE.md`/`AGENTS.md` (`samefile`, symlinks followed; a not-yet-existing file matches by realpath). NotebookEdit is not relayed. On answer, `guard_resume_text` clears `guard_edit`; `Approve` (answer `{"0":{"labels":["Approve"]}}`) applies the edit to the file (Write: write content; Edit/MultiEdit: exact replace, must be unique unless `replace_all`, all-or-nothing, UTF-8, no newline translation) then appends to the resume text a sentence: `The human approved the edit to <path> and the UI applied it. Continue.` / `...approved the edit but the UI could not apply it: <err>. Say so and continue.` / `The human denied this edit to <path>. Leave it unchanged and continue without it.` (separated from the answer text by `\n`).

### 1.11 Stop / kill
`stop(sid)` (`POST .../stop`):
- `limited` -> `stopped` (`ended_at`, `auto_resume=false`) without killing; `queued` -> `stopped` (`note=None`).
- `waiting` whose process is gone (no `_procs` entry or exited, and not a re-attached live pid) -> `stopped`, `pending_question=None`.
- Not in {starting, running, waiting} or no pid -> returns record unchanged. If Popen already exited -> unchanged (follower records outcome).
- Else add to `_stopping`, `killpg(pid, SIGTERM)`, wait up to `STOP_GRACE_SECONDS=10` polling every 50 ms for the group to vanish (`killpg(pgid,0)`; reap zombie via `proc.poll()`; `PermissionError` counts as gone), then `SIGKILL`, wait up to 2 s more. Then `update(status="stopped", ended_at, pending_question=None)`, `release_batch`, drop `_stopping` unless a follower still owns it. Whole process group is killed (tools spawned by claude die too).
HTTP: 404 unknown; 409 `session already finished` if status done/failed/stopped; 409 `session is starting, retry` if the result is not `stopped`; 200 `_public`.

### 1.12 Resume / continue
- `resume(sid, answer_text)`: used by the answer flow and queued prompts. Non-empty, not starting with `-`; needs `session_id` (else `_fail` "cannot resume: session has no claude session_id"); cwd = `checkouts.get(repo, repo)` must be a directory; `resume_target` (3.4); preflight; `_spawn(resume_argv, answer=text, ...)`.
- `resume_stopped(sid, claude_cmd=None)` (`POST .../resume`, also limit auto-resume): under `_resume_lock` (in-process): status must be stopped/limited/failed and `sid not in _procs` (else Conflict "session is not stopped, limited or failed"); for `implement-issue`/`pr-grind` sessions refuses if another session for the same `(repo, "<skill>:<number>")` is starting/running/waiting (`session <id> is already live for this issue`); optional account rebind (same harness required) copies the transcript `~/.claude*/projects/<slug>/<session_id>.jsonl` (`slug = realpath with every non-[A-Za-z0-9] char -> "-"`) from old config dir into the new account's; missing -> Conflict `transcript not found at <src>`. Claims: `status=starting, pid=None, limit_resets_at=None, limit_type=None, auto_resume=None, claude_cmd=<new>`. Prompt = the record's `pending_answer` if it was `limited`, else `"Continue from where you were stopped."`. A limited record with no `session_id` restarts fresh via `_restart_argv`; otherwise `claude ... --resume`. `tokens_base` reset.
- `send_prompt(sid, text)` (`POST .../prompt`, max 4000 chars, no NUL, not starting with `-`): `waiting` -> Conflict "answer the pending question first"; `starting|running|limited` -> stores `queued_prompt`, returns `"queued"`; terminal states: needs `session_id`, same-issue liveness guard, `resume_target`, claims `status=starting, pid=None, queued_prompt=None`, then `resume()`; returns `"sent"`. `_deliver_queued` runs at every follower end and on `release`: if `queued_prompt` set, not `hold`, status done/failed -> `send_prompt`; ValueError drops the prompt, other failures keep it, both set `note="queued prompt not sent: <e>"`.
- `hold(sid)` (status starting/running/waiting/limited else 409) sets `hold:true`; `release(sid)` (409 "session is not held" otherwise) clears it and delivers queued prompt. `cancel_auto(sid)` (409 unless limited) sets `auto_resume=false`. `start_now(sid)`: `limited` without `session_id` -> NotQueued("this account is rate limited: the session starts by itself when the limit resets"); not `queued` -> NotQueued("session is not queued"); claims `starting` and spawns (409 for NotQueued).

### 1.13 Restart recovery (`ui_runner.reconcile()` at server start)
For each record (any exception per record is warned and skipped):
- `waiting`, has `pid_started`, no `ended_at`: if `sid not in _procs` -> `_watch_waiting` (put `_procs[sid]=None` so no second process is resumed, watcher thread polls `ps` every 1 s; when the pid fingerprint changes/ps fails 25 times, set `ended_at` if still waiting, which unlocks the form). Never touches status or the round.
- not `starting|running`, or already in `_procs`: skip.
- no `pid` -> `failed`, `error="session never started (UI exited before spawn)"`.
- `pid_started` equals current `ps lstart` of pid -> still alive: `_procs[sid]=None`, daemon `_follow(sid, None, pid, started)` (non-child tail: liveness by fingerprint compare; up to 25 consecutive `ps` errors tolerated).
- else dead: `_follow` inline (drains stream from offset 0, applies outcome rules 3/4: not child so rc is None; success if result seen and not error).
Also: `limit_tick` runs once immediately at startup (catch-up of limits that reset while down) and `release_batch` for queued sessions; pr-grind timer re-enters loops.

### 1.14 pr-grind headless re-entry (timer) — runner part
Timer `PRGRIND_TICK_SECONDS=60`; `PRGRIND_HEARTBEAT=1500` s; `MAX_GRINDS=2` concurrent. For each `<data>/pr-grind/*.md` with `next-poll`, not `paused`, not `done`: parse header (lines before first `## `; `key: value`; also honour `done: <ISO>T...` lines under rounds). Required & validated: `owner`,`repo` `[A-Za-z0-9_.-]+`, `number` digits, `thread` https URL. Decision order: invalid; paused; done; a live `/pr-grind <thread>` session -> `busy`; non-blocking `flock` on `<state>.lock` (`locked`); `gh pr view <n> --repo <slug> --json state` MERGED/CLOSED -> write `done: <ISO> — merged|closed`; trigger if `next-poll` due, or new review via `bash skills/pr-grind/scripts/poll-reviews.sh <owner> <repo> <n> <login(s)> <since> <mode> once` (120 s timeout; `reviewer: UNRESOLVED`->login=`author`, mode `not-author`; else `reviewers:` comma list or `reviewer`, mode `reviewer`), or CI change (`ci.snapshot` -> `"<head_sha> <state>"` vs header `ci-seen`); dispatch-owned lane -> write `dispatch-due`, `next-poll`, return; need a cwd from a prior session on that repo; `grind_live() >= MAX_GRINDS` -> `queued`; else `start("/pr-grind <thread>", cwd, link=<pr url>, instructions=[REENTRY], env_extra={AIW_HEADLESS:1}, pass_fds=[lock fd])` and set `next-poll = now+1500s`. The flock fd is inherited by the child so the lock lives as long as the round.

---

## 2. Session record

### 2.1 Id and storage
Id: `YYYYMMDDTHHMMSSffffffZ-<8 hex>` (UTC, microseconds; regex `[0-9]{8}T[0-9]{12}Z-[0-9a-f]{8}`; also the path-traversal guard; invalid id -> ValueError -> HTTP 404 on read routes). `mkdir` exclusive; `stream.jsonl` created empty. Listing = directories sorted descending by name (newest first); unreadable/non-object `meta.json` is skipped with a warning. Every `update` is flock(read-modify-write-atomic-replace) and returns the new record; `id` immutable. `update` also computes notification dedupe (below). No in-memory cache.

### 2.2 Fields
Core (written at create):
| Field | Type | Notes |
|---|---|---|
| `id` | str | |
| `command` | str | prompt text; after spawn the skill-resolved text (`/ai-workflow:...` or `/...`) |
| `repo` | str | the `cwd` argument given to start (checkout absolute path as resolved, or slug) |
| `link` | `{owner,repo,issue}` or null | issue/PR the session is about |
| `session_id` | str/null | Claude's session id (from init event); needed to resume |
| `pid` | int/null | process-group id of the child (cleared to null on claim) |
| `status` | enum | starting, running, waiting, limited, queued, done, failed, stopped |
| `cost` | number/null | last result's `total_cost_usd` |
| `tokens` | `{input,cached,output}`/null | latest process's summed result usage; backfilled lazily |
| `started_at` | ISO-8601 UTC str | |
| `ended_at` | str/null | |
| `pending_question` | round/null | section 1.9 |
| `claude_cmd` | str | account command bound at start (not label) |
| `harness` | `"claude"` | absent on old records = claude **[DROP codex]** |

Runner / feature optional fields: `pid_started` (str), `model` (from init event), `cwd_path` (resolved checkout dir used for spawns), `error`, `note`, `pending_answer`, `queued_prompt`, `resumed_fresh`, `terminal_handoff`, `hold` (bool), `run_model`, `run_effort`, `allowed_tools` (list), `direct_model`/`direct_effort`/`sandbox`/`agent` (codex/agent), `run_note`, `batch`, `batch_max`, `limit_resets_at` (epoch seconds), `limit_type`, `auto_resume` (bool/null), `limit_backoff`, `tokens_base`, `tokens_total` (codex), `request` (replayable start body, section 6), `no_repo` (bool), `vault_folder`, `pin_account` (bool), `dismissed` (bool, failed only), `guard_edit`, `notified` (list of dedupe keys), `role` (`"away-answerer"` => hidden from lists), `answers_for`, `answers_round`, `afk_retries`, `afk_retry_at`, `afk_retry_for`, `panel`, `panel_role` (`root|lens`), `panel_lens`, `bootstrap` (run id).

`_public(rec)` (what the API returns for a session): `id, command, repo, link, slug` (registered slug, symlink-safe via realpath of cwd_path/repo, or null), `session_id, outcome (=status), cost, tokens, model (=model||run_model), effort (=run_effort), started_at, ended_at, waiting (pending_question != null), pending_question, error, resumed_fresh, note, terminal_handoff, pending_answer, queued_prompt, claude_cmd, limit_resets_at, limit_type, auto_resume, hold (== true), no_repo (== true), vault_folder, peer_review (panel status + role + lens, or null), bootstrap (run or null), repo_path (=cwd_path), harness (default claude), run_note, resume_command`. `resume_command` = ``cd <shell-quoted cwd_path> && claude --resume <shell-quoted session_id>`` or null (the account command is ignored).

### 2.3 Lifecycle
```
create -> starting
starting -> running            (_spawn success)           starting -> failed (preflight/spawn error)
queued   -> starting -> running (batch slot freed / start-now)
(any start) -> limited         (account limited at start; or run ended on limit)
running -> waiting             (aiw ask recorded a round; set by the child's CLI)
waiting -> starting -> running (answer claimed; resume spawns)
waiting -> stopped             (stop with dead process, or stop kills)
running -> done | failed | limited | waiting(stays)   (follower outcome rules 1.8)
running/waiting/starting -> stopped   (stop)
limited -> starting -> running (limit timer / POST resume / account switch)
stopped|failed|limited -> starting -> running  (Continue)
done|failed|stopped -> starting -> running     (prompt/answer resumes)
failed -> failed+dismissed:true (POST dismiss; does not delete)
```
- Live set (`_LIVE`) = starting, running, waiting, limited, queued. Terminal = done, failed, stopped.
- `_mark_limited`: `status=limited, pending_question=None, error=<first_err>, ended_at=None, limit_resets_at=<resetsAt epoch>, limit_type=<rateLimitType>, auto_resume=(resets is not None)`. Non-claude harness backoff **[DROP codex]**.
- Cleanup (`POST /api/sessions/cleanup`) deletes the session directory of non-live sessions only.

### 2.4 Notifications driven by status changes
In `update`: when `status` is in the updated fields, `ui_notify.dedupe_key(event, record)`: `waiting` -> `waiting:<round id>` (or `waiting`); `done`/`failed` -> the event name; others none. Keys stored in `record.notified`; a repeat key is not re-sent; moving to `starting`/`running` removes `done`/`failed` keys (so a resumed run re-notifies). Push sent after the lock is released. `ui_notify.notify(event, rec)` runs in a non-daemon thread: skipped for `role=away-answerer`; `done` skipped for `/pr-grind` sessions and `command.startswith("Start the review grind for PR ")`; `waiting|failed|grind-paused` skipped while Away (AFK) is active. Channels per event from matrix (section 4.5): `browser` (adds to `ui_feed`), `ntfy` (HTTP POST), `mac` (terminal-notifier / osascript).

### 2.5 Cost / token accounting
Only from `result` events (section 1.8). Lazy backfill: `list_sessions()` for a non-live record lacking the `tokens` key reads its stream once, takes the LAST result's tokens and writes `tokens` (even `null`, so it's scanned once). No aggregation across sessions exists in the server.

### 2.6 Transcript storage / API
Transcript = `stream.jsonl` itself. `GET /api/sessions/<id>/stream?offset=N` returns `{events, offset}`: reads bytes from N, only up to the last `\n` (partial last line withheld), parses lines; for terminal sessions (done/failed/stopped) the unterminated tail is also parsed and offset advanced past it. Offset is a byte offset; clients echo the returned offset. Bad/negative offset -> 400 `bad offset` (text/plain).

---

## 3. Accounts, usage meters, pinning

### 3.1 Accounts (stored in `ui_settings.json`)
`commands[]`: `{label, cmd, harness: "claude"|"codex" [DROP], models? [codex only]}`. The built-in account is always first: `{label: <claude_label or "claude">, cmd: "claude", builtin: true, harness: "claude"}`; its label is renamable (stored as `claude_label`), cmd fixed, never removable; stored commands whose label equals the built-in's label are dropped on load. `default` = a label (the built-in's alias if unset/unknown). `default_cmd()` = cmd of the account whose label == default, else `"claude"`. Max 20 commands; label 1..40 chars non-blank, unique; cmd <= 200 chars, must resolve via `argv()`; with a full save (body contains `commands`) each cmd must be unique (`each account needs its own command`); `default` must be one of the labels.
`argv(cmd)`: reject non-str/NUL; `shlex.split`; empty -> error; if first token is `cc` it is rewritten to `cc-profile`; first token resolved with `shutil.which` -> absolute path (error `'<tok>' not found on PATH`); rest of tokens kept. Executed directly, never through a shell.
`config_dir(cmd)`: tokens `cc|cc-profile <profile> ...` -> `~/.claude-profiles/<profile>`; else `$CLAUDE_CONFIG_DIR` or `~/.claude`.
`POST /api/settings/test {cmd}`: `cmd` must be a saved command (else 400 `cmd must be a command saved in Settings: save the account first`); blank cmd -> 200 `{ok:false,message:"cmd required"}`; runs `<argv> auth status --json` (30s) -> `{ok:true,message:"logged in <email|account>"}` or `{ok:false,message:"not logged in"|"auth status check failed: <e>"}`.

### 3.2 Usage meters (`ui_usage`)
- Per Claude account: keychain service = `Claude Code-credentials` if `config_dir == ~/.claude`, else `Claude Code-credentials-` + first 8 hex of `sha256(config_dir)`. Read with `security find-generic-password -s <service> -w` (macOS only, 15s); JSON `claudeAiOauth{accessToken, expiresAt(ms)}`. Expired token -> `{error:"re-login needed"}` (token is never refreshed here, to not rotate the refresh token). Keychain failure -> `usage unavailable (keychain read denied or no login)`.
- `GET https://api.anthropic.com/api/oauth/usage` with headers `Authorization: Bearer <token>`, `anthropic-beta: oauth-2025-04-20`, 15 s timeout. Response `five_hour`, `seven_day` each `{utilization: number, resets_at}` -> `{pct: utilization, resets_at}` (or null if malformed). Errors -> `{error:"usage unavailable"}` (log type name only; never token).
- Cache per `cmd`: `{five_hour, seven_day, at, error}`; on error keep last numbers, set `error`, retry in `RETRY=900 s`; on success next fetch in `POLL=300 s`. Codex accounts get `{error:"not available for Codex", at:null}` **[DROP]**.
- Loop thread `ui-usage` ticks every 5 s but only calls `refresh()` if a client called `snapshot()` within the last `ACTIVE=120 s` (`GET /api/sessions` is the poller that marks the UI present).
- Go risk: depends on macOS Keychain; Linux needs another credential source.

### 3.3 Rate-limit state (separate from usage meters)
`limits()` => `{claudeCmd: {limited_until?: max(limit_resets_at of its limited sessions still in future), warning?: {type, utilization}}}`; `warning` from in-memory `_usage[cmd]` when `info.status=="allowed_warning"` and `info.resetsAt` in future (`utilization` from `info.utilization`). Returned as `limits` in `GET /api/sessions`.
`limit_tick` (thread, first run immediately, then every `LIMIT_TICK_SECONDS=30`): (a) `release_batch` for each batch having queued sessions; (b) for each `limited` session with `auto_resume` and `limit_resets_at + 5s <= now`, skipping `hold` and answerer-role sessions and those not on a still-valid account (`_on_own_account`), call `resume_stopped(id)` and sleep 2 s between (stagger).

### 3.4 Switching / pinning rules
- Default account for new work = settings default. A session is bound to `claude_cmd` at creation and always resumes on it.
- `POST .../resume {claude_cmd: <label>}` rebinds (label must be saved: 400 `claude_cmd must be a label saved in Settings`); transcript is copied between config dirs (1.12); cross-harness rebind -> 409 `this session ran on claude; pick a claude account` **[codex DROP: always same harness]**.
- `resume_target(rec)`: account no longer saved and harness claude -> resumes on the recorded command unchanged (FR-15).
- Pinning: `pin_account:true` on a session start marks the record `pin_account` (and it must have `claude_cmd`). `ui_origin.account_for(cwd, text, link)` runs when no explicit account is passed: for sessions with `pin_account` on the same repo (oldest first), parse their raw `stream.jsonl` for what they made — PRD files written via the `Write` tool (path matches `docs/prds/<stem>.md`) and issue numbers from `gh issue create` Bash tool_use whose tool_result contains `/issues/<n>` — cached by stream size; if the new prompt references a made PRD stem, an issue it filed, or an issue within the PRD's family (epic + children + closed children from the poller snapshot), the new session uses that pinned session's account if still saved. Issue numbers of the new work come from `link.issue`, `/cmd 12 13` args, and PRs mentioned (mapped via snapshot). Pinned-session list cached 5 s. Any error returns None (never blocks a start). `prd_label` exposes the label for the planning board (`account` per PRD).
- Unsaved-account label sent to `/api/sessions` or `/api/start` -> 400.

---

## 4. Settings

File `<data>/ui_settings.json`, written by `PUT /api/settings` (`save`) = `validate(body)` then atomic write; GET returns `load()` plus `grind_reviewers.settings_view` additions.

### 4.1 Stored schema (what `validate` returns)
```
{ claude_label: str,            // built-in alias (default "claude")
  commands: [{label,cmd,harness,models?}],   // excludes the built-in
  default: str|null,            // label; null when it equals the alias
  repos: { "owner/repo": {auto_grind: bool, slack_channel: str, reviewers: [ids]|null} },
  slack_channels: [{id,name}],          // <=50; id /^[CGD][A-Z0-9]{8,12}$/, name 1..60
  reviewers: [{id,name,slack_id,github_login}],   // <=50; id r-<8hex> generated if absent
  active_reviewers: [ids],
  vault_dir: str|null,          // abs path or ~ ; default ~/Documents/notes; <=500, no NUL
  grind_mode: "deep"|"simple",  // default deep
  use_jev: bool,                // default true
  run_model: "opus"|"sonnet"|"haiku"|null,
  run_effort: "low"|"medium"|"high"|"xhigh"|"max"|null }
```
`load()` output (GET): all of the above normalized with defaults, plus read-only: `commands` (built-in first, each with `harness`), `default` (label), `repos` (every registered checkout slug + stored extra slugs; each `{auto_grind, slack_channel, reviewers, channel_invalid}` where `channel_invalid` = channel set but not in `slack_channels`; reviewers filtered to known ids), `jev_installed` (`which jev`), `personal_plugin` (see 5.5) **[DROP]**, `harnesses` (static list: claude {models opus,sonnet,haiku; efforts low..max; usage:true}, codex {...} **[codex DROP]**). GET only: each `repos[slug].path` and `bot_label`.
Partial save: body without `commands` is merged onto the current commands/default (board per-repo PUT). Any omitted key keeps its stored value (`vault_dir`, `grind_mode`, `use_jev`, `run_model`, `run_effort`, `slack_channels`, `reviewers`, `active_reviewers`). `repos` entries replace that repo's entry only; per-repo `reviewers` kept if not sent. Removing a channel used by a repo -> 400 `channel <id> is used by <slug>`; picking an unlisted channel -> 400 `slack_channel <id> is not a listed channel` (an unchanged legacy value is allowed); channel string <=100. Repo keys must match `^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`. Errors are ValueError -> 400 `{error}`. Corrupt file: `save` moves it aside first.
Reviewers validation: name 1..60, need slack_id or github_login; slack id `/^[UW][A-Z0-9]{8,12}$/`; login `/^[A-Za-z0-9-]{1,39}$/`; unique slack ids and lowercase logins.
First-load migration (idempotent, locked): drops legacy global `auto_grind` onto every registered repo; if `reviewers` key absent, seeds `slack_channels`, `reviewers` (the channels.json `bot_uid` as "Review bot"/`bot_label`, GitHub logins from old per-repo `reviewer`), `active_reviewers`, and writes the file (so even a missing file is created on first `load(persist=True)`). Corrupt file is never overwritten by a load.
Per-issue grind: `issue_grind.json`; `set_issue_grind(slug, issue, on)`.

### 4.2 Models / effort validation (`check_run`)
Claude (or no cmd): `model` None or in {opus, sonnet, haiku} (aliases — passed straight to `--model`), `effort` None or in {low, medium, high, xhigh, max}; else ValueError `model must be one of opus, sonnet, haiku` / `effort must be one of low, medium, high, xhigh, max`. For codex accounts any non-empty string **[DROP]**. Applied in `start_session`/`ui_start.start` against the chosen account (`claude_cmd` label -> cmd, else default cmd) and in settings save for `run_model`/`run_effort`.

### 4.3 Notify settings (`ui.json`) — `GET/POST /api/settings/notify`
Response `notify_public()`: `{matrix:{event:{browser,ntfy,mac}}, events:[{key,label,group}], ntfy_ready, mac:{available,notifier,clickable}, server, topic, user, public_url, token_set, password_set, env:[keys overridden by AIW_NTFY_*]}`. Secrets never returned. POST body keys `server, topic, user, token, password, public_url`: strings, one line, <=500; blank clears; a secret key omitted or `null` is kept; `server`/`public_url` must start `http://|https://`. File written mode 0600 (tmp then rename). `ui_notify.load_config` ignores the file with a warning if mode has any group/other bit; env `AIW_NTFY_{SERVER,TOPIC,TOKEN,USER,PASSWORD}` override. `POST /api/settings/notify/channel {event, channel, on:bool}` sets one matrix cell. Events (key: default cells): waiting, failed, dispatch, panel-cap, prd-comment (browser only), pr-ready, needs-cleanup, grind-paused, grind-done, done, pipeline, afk. Default: ntfy always on; browser/mac on except group "Finished" and `grind-done`; `prd-comment` browser only. ntfy push: `POST <server>/<topic>` body text, headers `Title, Priority (default for done/pipeline/grind-done/afk else high), Tags, Click, Actions, User-Agent: "aiw-ui (ntfy publisher)", Authorization (Bearer token wins over Basic)`; 5 s timeout. `POST /api/settings/notify/test {channel:"ntfy"|"mac"}` -> `{ok, error?}`.

### 4.4 Peer-review settings — `GET/POST /api/settings/review`
GET `{max_rounds, default_lenses, lenses:{name:prompt}, shipped:{...}, overridden}`; POST `{max_rounds 1..10 int, default_lenses non-empty subset of known lenses, lenses:{name:prompt 1..8000 chars}}` writes only differing prompts to `<data>/config.json`; `{reset:true}` deletes the override file.

---

## 5. Skills, prompts, repos

### 5.1 Skill registry (`skill_registry.json`, read and validated on every call, no cache)
`{steps:{<step id>: {plugin, skill, runs_in}}}`. Validation: plugin in {`blubird`,`ai-workflow`,`ai-workflow-personal`}, skill `^[a-z0-9-]+$`, runs_in in {`docs`,`issue`,`any`}; bad entry -> ValueError naming the step. `command(step)` = `/<plugin>:<skill>`. `GET /api/registry` -> `{steps:{id:{plugin,skill,runs_in,command}}}`.
Shipped steps (id -> plugin:skill, runs_in): create-prd, create-tasks (blubird, docs); small-change (blubird:create-tasks, any); refine-issues, implement-issue, pr-review, verifier-locally, docs-updater, reproduce-bug (blubird, issue); after-merge (blubird:implement-issue, issue); pr-review-unmapped (ai-workflow:pr-review, issue); security-sweep, map-prds (blubird, docs); agentic-onboard, ci-optimize, skill-feedback (blubird, any); release-pr, faq-updater (ai-workflow, any); pr-grind (ai-workflow, issue); peer-review (ai-workflow, any); dump, worklog (ai-workflow-personal, any) **[DROP both]**.

### 5.2 Building the prompt (`/plugin:skill args`)
`POST /api/sessions` body: exactly one of `command` (a registry step id) or `text` (free prompt); optional `args` (string, default ""). `build_command(step,args) = "/<plugin>:<skill> <args>"` right-stripped. `text`: non-blank, no NUL, must not start with `-` (after lstrip). `ui_start.start` (cards) builds `args` itself from `skill` in {create-tasks, refine-issues, implement-issue, pr-grind, peer-review}: arg non-empty, not starting `-`, no NUL/newline; implement-issue `#?\d+` -> number; refine-issues `#?\d+([\s,]+#?\d+)*` -> space-joined; pr-grind `#?\d+` or `https://\S+` (via `ui_grind.grind_text` for the real text).
Prompt length cap `MAX_PROMPT_CHARS=32000`.

### 5.3 Skill resolution at spawn (`repo_skills.resolve(text, cwd)`)
Rewrites every plugin-skill slash command in the text. A command is `/` + optional `ai-workflow:` or `ai-workflow-personal:` prefix + a known skill name (folders of `<plugin>/skills/*/SKILL.md` plus `dump, worklog, sync-from-wasensi`, longest names first) located at start / after whitespace or `( [ " ' \``, and followed by end / whitespace / `, ; ! ? ) ] " ' \`` / or `.`/`:` not followed by a word char. Spelling: if `<cwd>/.claude/skills/<name>/SKILL.md` is a readable file -> `/<name>` (repo copy wins); otherwise `/ai-workflow:<name>`. Personal skills (`dump, worklog, sync-from-wasensi`) -> `/ai-workflow-personal:<name>` only if that plugin is installed, else left untouched **[DROP]**. NOTE: registry steps from the `blubird` plugin produce `/blubird:<skill>` and are NOT rewritten by resolve (only names present in this plugin's `skills/` dir match, and `/blubird:` is not a recognized prefix).
`parse(command)` -> `(name, rest)` for `^/(?:[\w-]+:)?([\w-]+)(?:\s+(.*))?$` (DOTALL, lstrip first); `is_skill(cmd, name, arg=None)`. `codex_prompt`/`codex_pointer` **[DROP]**.

### 5.4 runs_in routing and repo resolution (`ui_repos.start_session`)
Validation order (each failure -> 400 `{error}`): `repo` must be str if present; `issue` positive int (not bool) if present; prompt build; NUL; length; if the prompt contains `github.com/<o>/<r>/issues/<n>` and that slug is a registered checkout, that repo overrides the picked one. Then:
- `no_repo:true` (new idea): allowed only for step/family in `dump, intake` or custom text (`NO_REPO_COMMANDS`) **[dump DROP]**; cwd = `ui_vault.vault()` (settings `vault_dir`; must exist), no slug; the prompt gets `_vault_hint(vault_folder)` appended; `vault_folder` must match `05-Work/<Project>[/<Feature>]` (`valid_folder`).
- else `repo` required; `resolve_repo(repo)`: registered slug (case-insensitive) -> its path; else `repo` must be an absolute path with no `..` inside a git checkout (`git rev-parse --show-toplevel`, 10 s); returns `(toplevel, slug)` (slug from registry match by realpath, else parsed from `origin` remote `github.com[:port][:/]owner/repo(.git)`).
- `runs_in == "docs"` (create-prd, create-tasks, security-sweep, map-prds): cwd is switched to the Documentation Repo of the checkout: `docs_repo(cwd)` = cwd if `<cwd>/.blubird/repos.json` exists; else the folder named by first line of `<cwd>/.blubird/docs-repo` (relative path, `..` allowed, must be a git repo holding `.blubird/repos.json`); else ValueError `... has no .blubird map or docs-repo pointer: map it, or run /blubird:agentic-onboard`; then `resolve_repo` again on it.
- `runs_in == "issue"` and `"any"`: run in the resolved checkout (the issue repo). (Issue-vs-any difference is not enforced server-side; the UI uses it for placement.)
- `local/<name>` slug and family in {create-tasks, refine-issues, implement-issue, pr-grind, pr-review, release-pr} -> 400 (`... has no GitHub remote yet: add one (git remote add origin …), then run <fam>` or "origin already registered to another checkout").
- `claude_cmd` is a saved LABEL (raw commands rejected); `batch` `[A-Za-z0-9_-]{1,64}`, `BATCH_MAX=3`; `model`/`effort` via check_run; `peer_review` non-empty list of lens names validated by `peer_review.check_lenses(kind, picked)` (kind = step skill or `custom`).
- Issue link: for `implement-issue`/`pr-grind` with no `issue`, parsed from first token of args (`#12`, `12`, `.../issues/12`, `.../pull/12`). `link = {owner,repo,issue}` from the issue URL if present and matching, else from the slug.
- Under global `_start_lock`: duplicate guard for `implement-issue`/`pr-grind`: another non-terminal session of the same family+issue+repo whose pid group is alive -> 409 `{error:"<fam> already running for o/r#N (session <id>)", id, link, href:"/api/sessions/<id>"}`. `repo-bootstrap` family creates a bootstrap run (conflict 409 with `bootstrap`, `id`, `href`). With `peer_review`, writes the ask artifact file and appends the "append `## Answer` and `## Diff`" line, then after start creates a panel for it; failure stops the session.
- Then `ui_runner.start(text, cwd, link, claude_cmd, gate_questions=True, run_model, effort, batch=(batch,3))`; stores `request` (replayable body: keys repo,no_repo,vault_folder,command,args,text,issue,claude_cmd,pin_account,batch,model,effort, `peer_review`->`lenses`), `no_repo`, `vault_folder`, `pin_account`; registers the checkout (`_remember`) if slug unknown. Responses: 201 `_public`, 400 ValueError, 502 RunnerError (preflight/spawn failure).
- `rerun(rec)`: replays `rec.request` through `start_session` (guards again); legacy records replay `command` as `text` (+ account label, `no_repo`); no request/command -> 400 `nothing to rerun: ...`.

### 5.5 Repo registration / checkouts
`checkouts.json` slug -> path. `promote_local` renames `local/<name>` to the real slug once a GitHub origin appears (no-op if taken). `register(slug, path)`: slug matches `owner/repo`, path is a git checkout whose origin slug equals slug (case-insensitive) else ValueError `that folder's origin is X, not Y`; stores git toplevel. `find_clones(roots, max_depth=4, budget_s=4 (scan uses 20))`: walk, a dir with a real `.git` dir is a clone (worktrees skipped), skip dot dirs and `node_modules, vendor, venv, dist, build, target, Library, Applications`. `scan_and_register(roots)` -> `{added:[{slug,path}], duplicates:[...]}` (first clone wins). Default scan roots: existing of `~/Documents/Projects, ~/Projects, ~/Developer, ~/code, ~/work, ~/dev, ~/src, ~/Documents`. `list_repos()` -> `[{slug, name (from board projects or slug), path}]` sorted by slug. Folder picker: `osascript` `choose folder` (300 s) — only for Host `127.0.0.1|localhost` on macOS. Personal plugin detection reads `$CLAUDE_CONFIG_DIR|~/.claude` `/plugins/installed_plugins.json` `plugins` keys `ai-workflow-personal@...` **[DROP]**.

---

## 6. HTTP API

### 6.1 Conventions
- Server: Python `ThreadingHTTPServer`, `request_queue_size=128`, `allow_reuse_address`. Handlers are wrapped: unexpected exception => `500 {"error":"internal error"}` JSON (if headers not yet sent); BrokenPipe/ConnectionReset propagate. No access log. No CORS headers ever.
- JSON responses `application/json; charset=utf-8`; request bodies must be a JSON object, `Content-Length` required (else 400 `bad Content-Length`), `MAX_BODY=65536` (413 `body too large`), non-object/invalid JSON -> 400 `body must be a JSON object`.
- `_dispatch` error mapping for most POSTs: ValueError/TypeError -> 400 `{error}`; Conflict classes (ui_start, ui_grind, ui_actions, dispatch_run, ui_restart, ui_afk, ui_bootstrap) -> 409 `{error, id?}`; RuntimeError/OSError/RunnerError -> 502 `{error}`; else 500.
- Guard on every request (all verbs, before routing; failure 403 text/plain): `Host` header (lowercased) must be in allowed_hosts (loopback `127.0.0.1:<port>`, `localhost:<port>`, plus tailnet hosts / `--allow-host`); if Host is not a loopback host, header `Tailscale-User-Login` (lowercased) must equal the node owner's login; if `Origin` present its netloc (lowercased) must equal Host. `HEAD/OPTIONS/TRACE/CONNECT` after the guard -> 405 `Allow: GET`. Unknown verbs on routes -> 405 text/plain `method not allowed` with `Allow: GET`. Missing Host -> 403.
- Static (`GET /`, `/sw.js`, `/manifest.webmanifest`, `/assets/*`, `/icons/*`) from `run-engine/ui_dist/`; `/` serves `index.html`; path `unquote`d once, `realpath` containment inside dist (else 404 `not found` text/plain), directory -> 404, other OSError 500 `internal error`. Cache: files under `assets/` `public, max-age=31536000, immutable`; everything else `no-cache`. `.js/.mjs` -> `text/javascript; charset=utf-8`, `.webmanifest` -> `application/manifest+json`, text types get charset. Other unknown GET path -> 404 `not found`.
- Removed prefixes (POST returns 404 text/plain): `/api/{runs,pipelines,flows,notes,dispatch,maintree,grind,autopilot}/...` (note: `/api/grind/issue|skip-ci|stop` are matched earlier and live; `/api/dispatch` singular is the removed one).
- No SSE, no websockets, no long-poll. Everything is short polling (client polls `/api/sessions`, `/api/inbox`, `/api/notifications?after=`, transcript `?offset=`).

### 6.2 Endpoints

Session endpoints (this area):
| Method | Path | In | Out / status |
|---|---|---|---|
| GET | `/api/sessions` | — | 200 `{sessions:[_public...] (answerer-role hidden, newest first), limits:{cmd:{limited_until?,warning?}}, usage:{cmd:{five_hour:{pct,resets_at}|null, seven_day, at, error}}, afk:{...}, gh:{ok,login,error}}`; side effect: marks UI present for usage polling |
| POST | `/api/sessions` | `{repo?, no_repo?, vault_folder?, command? XOR text?, args?, issue?, claude_cmd?(label), pin_account?, batch?, model?, effort?, peer_review?[]}` | 201 `_public`; 400; 409 `{error,id,link,href}`; 502 |
| GET | `/api/sessions/<id>` | — | 200 `_public`; 404 text `not found` |
| GET | `/api/sessions/<id>/stream?offset=N` | — | 200 `{events:[{kind:text|tool|result,...}], offset}`; 400 `bad offset`; 404 |
| POST | `/api/sessions/<id>/answer` | `{round_id, answers}` | 200 `_public`; 400/409/413/415/500 per 1.9; 404 |
| POST | `/api/sessions/<id>/prompt` | `{text}` (<=4000) | 200 `{state:"sent"}` / 202 `{state:"queued"}`; 400; 404; 409; 500 |
| POST | `/api/sessions/<id>/stop` | — (no body read) | 200 `_public`; 404; 409 |
| POST | `/api/sessions/<id>/resume` | optional `{claude_cmd: label}` (body only read when Content-Length > 0) | 200 `_public`; 400 bad label; 404; 409; 500 |
| POST | `/api/sessions/<id>/cancel-auto` | — | 200 `_public`; 404; 409 |
| POST | `/api/sessions/<id>/hold` / `release` | — | 200 `_public`; 404; 409 |
| POST | `/api/sessions/<id>/start-now` | — | 200 `_public`; 404; 409 |
| POST | `/api/sessions/<id>/rerun` | — | 201 `_public` of the new session, or start_session errors; 404 `{error:"not found"}` |
| POST | `/api/sessions/<id>/dismiss` | — | 200 `_public` with `dismissed:true`; 409 `only a failed session can be dismissed`; 404 |
| GET | `/api/sessions/cleanup` | — | 200 `{items:[{key,label,repo,flags:[]}]}` finished sessions newest first |
| POST | `/api/sessions/cleanup` | `{keys:[str]}` | 200 `{removed:[keys]}`; 400 `keys must be a list of session keys` |
| POST | `/api/start` | `{repo, skill, arg, via?(null|"headless"), lenses?, model?, effort?, issue?, claude_cmd?, pin_account?}` | 200 `{session:<id>}` or `{panel:<id>}` (peer-review); 400; 409 `{error,id?}` (live session, open/merged PR, blocker, dispatch lane, 30 s duplicate window `RECENT_SECONDS`); 502 |
| GET | `/api/notifications?after=N` | digits only | 200 `{latest, events:[{id,event,title,body,path,tag,ts}]}` (in-memory deque 200, max 5 newest, none if N absent or > latest); 400 `after must be a whole number` |
| GET | `/api/registry` | — | 200 `{steps:{...}}` |
| GET | `/api/health` | — | 200 `{"ok": true}` |
| GET | `/api/restart` | — | 200 `{available, running, exit_code, log_tail}` |
| POST | `/api/restart` | `{}` | 202 `{ok:true}`; 400 `no make restart target in this install`; 409 `a restart is already running` |
| GET | `/api/settings` | — | 200 settings view (section 4.1) |
| PUT | `/api/settings` | settings (partial allowed) | 200 `load()`; 400 |
| POST | `/api/settings/test` | `{cmd}` | 200 `{ok,message}`; 400 |
| GET/POST | `/api/settings/notify` | section 4.3 | 200 `notify_public`; 400 |
| POST | `/api/settings/notify/channel` | `{event,channel,on}` | 200; 400 |
| POST | `/api/settings/notify/test` | `{channel}` | 200 `{ok,error?}`; 400 |
| GET/POST | `/api/settings/review` | section 4.4 | 200; 400 |
| GET | `/api/repos` | — | 200 `{repos:[{slug,name,path}], can_browse:bool, scan_roots:[...]}` |
| POST | `/api/repos/register` | `{slug,path}` | 200 `{path, repos}`; 400 |
| POST | `/api/repos/remove` | `{slug}` | 200 `{ok:true, repos}`; 400 `<slug> is not registered` |
| POST | `/api/repos/check` | `{}` | 200 `{problems:{slug: null|msg}}` (one `gh repo view <slug> --json nameWithOwner` each, 8 in parallel, 20 s each; `local/*` -> "no GitHub remote") |
| POST | `/api/repos/scan` | `{roots?:[abs paths, no ..]}` | 200 `{added,duplicates,repos}`; 400 |
| POST | `/api/repos/browse` | `{start?}` | 200 `{path|null}`; 403 `folder picker is only available locally on macOS` |
| POST | `/api/repos/publish` | `{slug,owner,name,private=true}` | 201; ui_vault.publish_repo (gh repo create from `local/` repo) |
| POST | `/api/repos/create` | `{parent,name,prd_folder?}` | 201; ui_vault.create_repo (mkdir, git init, seeds docs/prds + README from a vault PRD) |
| GET | `/api/github/owners` | — | `(status, {login, owners})` from gh |
| GET | `/api/github/branches?repo=o/r` | — | `(status, body)` all branches, default first; never cached |
| GET | `/api/issues/<owner>/<repo>/<n>` | — | issue popup `ui_issue.fetch`: 200 shaped issue+comments; 400 `bad issue id`; 404; 502 |
| GET | `/api/pulls/<owner>/<repo>/<n>` | — | PR popup `ui_pr.fetch` (REST pr, files, commits, comments, reviews, CI rollup); 400/404/502 |
| GET | `/api/repos/<owner>/<repo>/open?kind=issue\|pr` | — | open issues/PRs for the New-run picker; 400 `bad repo` |
| POST | `/api/issues/<o>/<r>/<n>/comment` and `/api/pulls/<o>/<r>/<n>/comment` | `{text}` (<=65536) | 200 `{ok,url}`; 400; 502 (gh error) |
| POST | `/api/issues/<o>/<r>/<n>/state` | `{state:"open"\|"closed", reason?:"completed"\|"not_planned"}` | 200 `{ok,state}`; repolls the repo; 400/502 |
| POST | `/api/pulls/<o>/<r>/<n>/state` | `{state:"open"\|"closed"}` | 200 `{ok,state}` (`gh pr reopen\|close`); 400/502 |
| POST | `/api/pulls/<o>/<r>/<n>/merge` | `{sha: 40-hex}` | 200 `{ok:true}` (`gh pr merge -R slug --merge --match-head-commit sha`, never squash); 400/502 |
| POST | `/api/epics/close` | `{repo, epic:int>=1}` | 200 `{ok, closed:[nums]}` (closes open children as completed, then epic; stops at first failure); 400/502 |
| GET | `/api/prd?repo=&path=docs/prds/<name>.md` | — | 200 `{path,text,sha (git blob hash),branch}`; 400 |
| POST | `/api/prd` | `{repo,path,text,base_sha?}` | 200 `{ok,committed,branch,commit?,sha}` (writes + `git commit -m "docs(prd): edit <slug> from aiw ui" -- <path>` on current branch, 30 s, no push; <=512 KiB); 409 `changed on disk`; 400/502 |
| POST | `/api/route` | `{text}` | 200 `{route:"feature"\|"small_change"\|null, confidence, why}` via `jev` (min confidence 0.4) |
| POST | `/api/duplicate` | `{repo,text}` | 200 duplicate check vs open issues/PRDs (`ui_duplicate.check`) |
| GET | `/api/products` / POST `/api/products` | `{path}` | product registry (`ui_products`) |
| GET | `/api/planning?repo=&refresh=1` / `/api/delivery?repo=&refresh=1` | — | board body per repo (or `{repos:[...], stale:[...]}` for all watched repos when `repo` omitted); 400 unknown repo; marks repo viewed (poller) |
| GET | `/api/inbox?repo=` | — | `{items, stale, afk, gh}` ranked inbox |
| POST | `/api/cleanup` | `{repo,issue,confirm:true}` | 200 `{removed}`; 409 if PR not merged — merged-worktree cleanup |
| POST | `/api/grind/issue` | `{repo,issue,on}` | per-issue grind switch |
| POST | `/api/grind/skip-ci` / `/api/grind/stop` | `{repo,pr}` | grind controls |
| POST | `/api/afk`, `/api/afk/change`, `/api/afk/stop`, `/api/afk/dismiss` | `{until}` (epoch s, within 24 h) / changed answers | Away-mode (`ui_afk`) |
| POST | `/api/review`; `/api/review/<panel>/lens`; `/api/review/<panel>/rounds` | peer-review panels (`ui_panel`) | 200 `{panel}`; 404/400/409 |
| GET | `/api/peer-review` | — | `{default, max_rounds, kinds:{kind:[lenses]}}` |
| GET | `/api/dispatches`, `/api/dispatches/<id>`, `/api/dispatches/<id>/lane?key=` ; POST `/api/dispatches`(201), `/plan`, `/<id>/settings|state|lane|retry-failed|end|seen` | dispatch epic runner (other doc) |
| GET | `/api/bootstraps?repo=`; POST `/api/bootstraps/<id>/continue\|retry\|stop` | repo-bootstrap runs (other doc); 404 unknown id |
| GET | `/api/vault/folders`, `/api/vault/prd?folder=`; POST `/api/vault/suggest {text}` | notes-vault helpers (`ui_vault`; suggest asks Claude Haiku) |
| GET/POST/PATCH/DELETE | `/api/shares...` | **[DROP]** public PRD shares (owner routes, `ui_share_api`, funnel/runtime) |

**[DROP] summary:** shares/public share + Tailscale funnel; codex harness (`harness_codex`, `AGENT_SANDBOX_VERIFIED`, `install_skills`/`aiw install-skills`); herdr (`herdr-dispatch`, `Herdr` dispatch runner, "codex_pointer"); personal plugin (`dump`, `worklog`, `sync-from-wasensi`, `personal_plugin`, `/api/vault/*` if tied only to dump).

---

## 7. Server process

- CLI: `aiw ui [--port 8420] [--allow-host HOST]... [--no-tailscale] [--tailscale-port 443|8443|10000 (default 443)]`. Binds `127.0.0.1:<port>` only. Before binding: probes `connect(127.0.0.1:port)` (1 s) — if it answers, fails with `port N is already in use by PID p (name)` (via `lsof`) exit 1 (macOS lets a 127.0.0.1 bind succeed over a 0.0.0.0 holder, hence the probe).
- Remote access: if `tailscale` is running, runs `tailscale serve --bg --https=<port> http://127.0.0.1:<port>` (refuses to overwrite a foreign handler on that port; adopts one already pointing here); on exit `tailscale serve --https=<port> off`. Allowed Hosts then include the node DNS name (bare on 443, `name:port` otherwise); `tailnet_login` = the node's owner login; non-loopback requests require header `Tailscale-User-Login` == owner (set by tailscale serve). `--allow-host` also requires the tailscale owner login (die otherwise).
- Startup order: `ui_migrate.clear_old_data` (removes old engine paths once, marker `migrated-dev-workflow`) -> bind -> tailscale -> shares hooks **[DROP]** -> `ui_runner.reconcile()` -> timers: `ui_grind` (ntfy on grind pause/finish), pr-grind timer (60 s), limit timer (30 s, immediate first tick), poller (`ui_poller`, boards; hot repos = viewed within `VIEW_SECONDS=120` or with live sessions/dispatch lanes, others every few minutes), bootstrap timer, panel timer, usage timer (5 s tick, polls only while UI active), dispatch timer, jev cache flush, urgency scorer, AFK timer (`TICK_SECONDS=5`), share runtime **[DROP]**. SIGTERM/SIGHUP -> clean exit (finally: close server, remove tailscale handler).
- Restart endpoint: `POST /api/restart` runs `sh -c 'make restart; echo $? > restart.exit'` in the plugin root, detached (`start_new_session`), stdout+stderr to `<data>/restart.log`; `available` = Makefile has a `restart:` line and `make` exists; `running` = log exists, no exit file, log mtime < 600 s; status returns last 40 lines of the log and the exit code. Old log/exit files removed first. The target restarts the UI via launchd/supervisord; detached sessions survive via 1.13.
- `aiw paths` prints `{plugin_root, data_dir, pr_grind_dir (created), channels, checkouts}`. `route.py` dispatches subcommands; ValueError / `dispatch_run.Conflict` in a subcommand -> stderr message, exit 5; `die(code,msg)` exits with code (`ask` uses 2). Verbs registered in code: `ui, paths, ask, ci, threads, grind-mode, grind-reviewers, dispatch, jev, install-skills [DROP]` (CLAUDE.md also lists `local-review`, which route.py does not register).

---

## 8. Constants, guards, edge cases pinned

| Constant | Value |
|---|---|
| Server port default | 8420 |
| MAX_BODY | 65536 |
| Free text per answer | 4000 chars; send_prompt cap 4000; `MAX_PROMPT_CHARS` 32000 |
| POLL_SECONDS (follower) | 0.2 |
| STOP_GRACE_SECONDS | 10 (+2 after SIGKILL) |
| ASKED_EXIT_GRACE_SECONDS | 30 |
| LIMIT_TICK_SECONDS / LIMIT_BUFFER_SECONDS | 30 / 5 (stagger 2 s between resumes) |
| MAX_GRINDS / PRGRIND tick / heartbeat | 2 / 60 s / 1500 s |
| BATCH_MAX (UI) | 3 sessions per batch at once |
| Preflight auth status timeout | 30 s; `ps` timeout 5 s; keychain 15 s; usage fetch 15 s |
| Usage POLL / RETRY / ACTIVE | 300 / 900 / 120 s |
| Notifications feed | 200 entries, replay <= 5 |
| ui_start RECENT_SECONDS | 30 |
| MAX_COMMANDS | 20; label 40 chars; cmd 200 |
| Guard diff shown | 1500 chars |
| Repo scan | depth 4, 4 s (20 s for scan endpoint) |

Edge cases / non-obvious behaviours (confirmed in code and tests):
1. The `claude` CLI is always spawned detached in a new session; UI death does not kill it. State is recovered by re-reading `stream.jsonl` + `ps lstart` fingerprint; a pid recycled within the same second is mis-identified (accepted).
2. An answer arrives as a NEW `claude --resume` process; there is no stdin channel. The previous process must have exited (`sid in _procs` -> 409 "session process is still running"); the 30 s reap SIGTERMs a process that hangs after asking.
3. `cost`/`tokens` are overwritten per run, not summed across resumes.
4. `list_sessions()` can write (token backfill) — reads are not pure.
5. `aiw ask` runs in the child's Bash tool, not in the server; it updates `meta.json` itself (flock) and fires the `waiting` notification from that process. Go must keep the same on-disk contract and locking (`.lock` flock) if a separate `aiw` binary writes records.
6. HTTP `/api/sessions/<id>/stop` and similar ops pass the session id through the id regex; any non-matching id is "not found", never a path.
7. `limits()` and `_usage` rate-limit warnings are in-memory only (lost on restart); limited sessions persist with `limit_resets_at` and are re-driven by the tick.
8. Two accounts of the same login share nothing: `cc-profile` (external script) must exist for non-default accounts; account config dir is derived from the command text, so the copy-transcript logic assumes `~/.claude-profiles/<name>` layout.
9. Claude registry steps from the `blubird` plugin are spelled `/blubird:<skill>` and never rewritten to repo copies; only this plugin's own skills (ai-workflow) get the repo-copy-wins rewrite.
10. `GET /api/settings` and `PUT /api/settings` return different shapes (GET adds repo `path` and `bot_label`).
11. `POST /api/sessions/<id>/resume` only reads a body if `Content-Length` is non-zero; other `POST .../stop|cancel-auto|hold|release|start-now|rerun|dismiss` never read the body.
12. HEAD/OPTIONS/TRACE/CONNECT and unknown methods answer 405 (after the host guard so a bad Host still gets 403).
13. Static path traversal: double-encoded `%252e` stays literal; containment is by `realpath`, not string checks.
14. The guard (Host, Tailscale-User-Login, Origin) is the only auth. There is no token. Loopback requests are trusted entirely.
15. Rate-limit detection has two triggers: a `rate_limit_event` whose status is not allowed/allowed_warning, or an error text regex; both need `is_error` on the final result to mark `limited`.
16. Tests use fake `claude` shell scripts that answer `auth status --json` with `{"loggedIn": true}` and otherwise `cat` a canned stream — a Go port can reuse that harness (`test_ui_limits.py`, `test_ui_runner.py`).
