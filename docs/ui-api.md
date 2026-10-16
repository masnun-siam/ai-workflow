# aiw ui HTTP API

Covers: `run-engine/ui_server.py`

Every route lives in `ui_server._Handler` (`do_GET`, `do_POST`, `do_PUT`), and every request passes `_guard` first ([security model](ui.md#security-model)). The server and its modules: [ui.md](ui.md).

## Conventions

- JSON in and out. A POST body must be a JSON object of at most 64 KiB (`_read_body`): 400 for a bad body or `Content-Length`, 413 when too large.
- Errors are `{"error": "<message>"}`. `_dispatch` maps module exceptions: `ValueError`/`TypeError` → 400, `NotFound` → 404, `Conflict` → 409, `ui_dispatch.NeedsCheckout` → 409 with `code: "no_checkout"`, `slug` and `candidates`.
- Any other verb, and any unknown POST or PUT path, gets 405 with `Allow: GET`. An unknown GET path gets 404.
- A session in a response is the `_public(rec)` shape, never the raw record. It adds `waiting`, `outcome` (the status), `peer_review` and `resume_command` (`cd <path> && claude --resume <id>`).
- Path parts are validated before use: session ids by `ui_sessions._ID_RE`, owner/repo/number by `ui_issue.valid` / `ui_pr.valid`, run ids by `ui_board.load_run`.

## GET

| Path | Handler | Returns |
|---|---|---|
| `/` | `_serve_static` | `index.html` |
| `/sw.js` | `_serve_static` | Service worker, served at the root so its scope is the whole app |
| `/static/<path>` | `_serve_static` | Files under `ui_static/`, `Cache-Control: no-cache` |
| `/api/health` | inline | `{"ok": true}` |
| `/board.json` | `build_board` + `ui_grind.for_card`, `_gh_status`, `ui_dispatch.membership` | Board columns, cards with `grind`, `gh`, `pipeline` |
| `/api/repos` | `ui_repos.list_repos`, `default_roots` | `repos`, `can_browse`, `scan_roots` |
| `/api/settings` | `ui_settings.load` | `commands`, `default`, `auto_grind`, `vault_dir` |
| `/api/github/owners` | `ui_vault.github_owners` | Your account and orgs from `gh`, for Publish |
| `/api/vault/folders` | `ui_vault.vault`, `folders` | Vault path and its `05-Work` folders |
| `/api/vault/prd?folder=` | `ui_vault.prd_info` | The folder's PRD and its status |
| `/api/peer-review` | `peer_review.offers` | Lenses each command offers |
| `/api/cleanup` | `ui_cleanup.find_targets`, `describe` | Cleanable items with titles, flags and PR merge state |
| `/api/flows[?archived=1]` | `ui_flows.list_all`, `summary` | Flow summaries |
| `/api/flows/<id>` | `ui_flows.load` | One flow |
| `/api/flows/<id>/issues` | `ui_flows.issues_for` | Per-issue progress of the flow's Issues session |
| `/api/notes?path=` | `ui_flows.read_note` | One vault note (read-only, at most 2 MiB) |
| `/api/pipelines` | `ui_dispatch.list_all`, `summary` | Pipeline summaries |
| `/api/pipelines/<id>` | `ui_dispatch.detail` | Pipeline with items, sessions, timelines, PR/CI and `grind` |
| `/api/sessions` | `ui_sessions.list_sessions` | `sessions`, `limits` (`ui_runner.limits`), `usage` (`ui_usage.snapshot`), `afk` (`ui_afk.public`) |
| `/api/sessions/<id>` | `_session` | One session (`_public`) |
| `/api/sessions/<id>/stream?offset=N` | `_session` → `ui_events.read_from` | `events` from byte `offset`, and the new `offset` |
| `/api/runs/<owner>/<repo>/<n>` | `_run` → `load_run` | Ledger view plus `title`, `gh`, `grind`, `maintree`, `autoGrind` |
| `/api/issues/<owner>/<repo>/<n>` | `ui_issue.fetch` | Issue popup: GitHub-rendered body and comments |
| `/api/repos/<owner>/<repo>/open?kind=issue\|pr` | `ui_issue.open_items` | Open issues or PRs, one `gh` page of 100 |
| `/api/pulls/<owner>/<repo>/<n>` | `ui_pr.fetch` | PR popup: description, conversation, files, commits, checks |
| `/api/pulls/<owner>/<repo>/<n>/merge` | `ui_pr.readiness` | What is not ready to merge |

- `/api/sessions` is the app's heartbeat (the shell polls it every 3 s). It also marks a client present, which keeps the usage poller running.
- The stream endpoint returns only whole lines. Once a session has ended, it also returns an unterminated last line.

## POST

| Path | Handler | Does |
|---|---|---|
| `/api/sessions` | `_start` → `ui_repos.start_session` | Start a session. 201 with the session, 409 when a `run-issue`/`pr-grind` for that issue is live, 502 when the runner fails. |
| `/api/sessions/<id>/answer` | `_answer` | Answer the pending round: `{round_id, answers}`. Needs `Content-Type: application/json`. 409 when not waiting, the process still runs, or the round was already claimed. |
| `/api/sessions/<id>/prompt` | `_prompt` → `ui_runner.send_prompt` | Send free text. 200 `sent`, 202 `queued` while the session runs. |
| `/api/sessions/<id>/stop` | `_stop` → `ui_runner.stop` | Stop it. 409 when already finished or still starting. |
| `/api/sessions/<id>/resume` | `_resume` → `ui_runner.resume_stopped` | Resume a stopped, limited or failed session. An optional `{claude_cmd: <saved label>}` moves it to another account. |
| `/api/sessions/<id>/cancel-auto` | `ui_runner.cancel_auto` | Turn off auto-resume of a limited session |
| `/api/runs/<owner>/<repo>/<n>/options` | `ui_options.apply` | `{review: false}` and/or `{auto_grind: bool}` on a started run |
| `/api/grind/start\|pause\|resume\|rerun-ci\|reply` | `_grind` → `ui_grind` | Body `{owner, repo, issue}` (`text` for reply) |
| `/api/maintree/release` | `maintree.release` | Free a repo's main tree: `{owner, repo}` |
| `/api/pulls/<owner>/<repo>/<n>/merge` | `ui_pr.merge` | Squash-merge (`gh pr merge --squash`) after the UI's confirm |
| `/api/cleanup` | `_cleanup` → `ui_cleanup.clean` | `{items: [{key, force?}]}`. Keys are matched against server-side targets. |
| `/api/repos/register` | `ui_repos.register` | Register `{slug, path}` as a checkout |
| `/api/repos/scan` | `ui_repos.scan_and_register` | Find clones under absolute `roots` (default `default_roots()`) |
| `/api/repos/browse` | `ui_repos.browse_folder` | macOS folder dialog. Local browser on darwin only, else 403. |
| `/api/repos/create` | `ui_vault.create_repo` | `{parent, name, prd_folder}`: a local repo for an idea. 201. |
| `/api/repos/publish` | `ui_vault.publish_repo` | `{slug, owner, name, private}`: push a `local/` repo to GitHub. 201. |
| `/api/vault/suggest` | `ui_vault.suggest` | Ask Claude for a `05-Work/<Project>/<Feature>` folder for `{text}` |
| `/api/settings/test` | `ui_settings.check_login` | `{cmd}`: run `<cmd> auth status --json` |
| `/api/dispatch/preview` | `ui_dispatch.preview` | Parse `{input, repo}` into screened issues: title, readiness, lane, deps, in run order |
| `/api/pipelines` | `ui_dispatch.create` | New pipeline. 201. |
| `/api/pipelines/<id>/delete` | `ui_dispatch.delete` | Delete. 409 while an item is live. |
| `/api/pipelines/<id>/<action>` | `ui_dispatch.act` | `pause`, `resume`, `stop`, `update` |
| `/api/pipelines/<id>/items/<n>/<action>` | `ui_dispatch.act` | `retry`, `skip` |
| `/api/flows` | `ui_flows.create` | New flow. 201. |
| `/api/flows/<id>/update\|archive\|unarchive` | `ui_flows.update`, `set_archived` | Store flow fields (`repo`, `text`, `folder`, `prd`, `tasks`, `parent`, `issues`, `sid`, `dispatched`) |
| `/api/afk` | `ui_afk.start` | `{until}` (epoch seconds, within 24 h): start or extend AFK |
| `/api/afk/stop`, `/api/afk/dismiss` | `ui_afk.stop`, `dismiss` | End AFK now, or hide its summary |

### POST /api/sessions body

| Key | Type | Meaning |
|---|---|---|
| `command` + `args` | string | One of `ui_repos.NAMED`, sent as `/<command> <args>`. Exactly one of `command` or `text`. |
| `text` | string | A custom prompt (at most 32000 chars, no leading `-`) |
| `repo` | string | Registered `owner/repo` or an absolute checkout path. An issue URL in the prompt picks its registered repo instead. |
| `issue` | int | Links the session to an issue (inferred for `run-issue`) |
| `claude_cmd` | string | A label saved in Settings |
| `worktree`, `review` | bool | `false` adds `--no-worktree` / `--no-review` to `run-issue` |
| `auto_grind` | bool | Grind when the run finishes (default from Settings) |
| `peer_review` | list | Lens names |
| `no_repo`, `vault_folder` | bool, string | Run in the notes vault, with a suggested `05-Work/...` folder |
| `batch` | string | Batch id. At most `BATCH_MAX` of a batch run at once. |
| `flow_id` | string | The Flow this session belongs to |

## PUT

| Path | Handler | Does |
|---|---|---|
| `/api/settings` | `ui_settings.save` | Replace settings. `ui_settings.validate` checks: at most 20 commands, labels of at most 40 chars, each command resolvable on PATH, `vault_dir` absolute or starting with `~`. |
