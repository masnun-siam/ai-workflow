# Reference

## Commands

| Command | Does |
|---|---|
| `/ai-workflow:create-prd <requirement>` | interview a requirement into a PRD with its technical design, saved to `docs/prds/<slug>.md`; `--update` records later decisions; `approve` files one epic per `## Epics` entry |
| `/ai-workflow:create-tasks <prd \| finding>` | split an Approved PRD into one-PR tasks, created as child issues of the epic with blocked-by links; or file one issue for a finding |
| `/ai-workflow:refine-issues <epic or issues>` | write a WHAT, WHY and HOW into each child issue, label it `refined` and move it to Ready on the board once unblocked |
| `/ai-workflow:implement-issue <n \| epic>` | one refined issue (or an epic's next Ready one) to a Ready PR: worktree, local checks, draft PR, CI, review comments; after the merge, close and clean up |
| `/ai-workflow:verifier-locally` | run the checks CI would run and exercise the change against its acceptance criteria |
| `/ai-workflow:pr-review <pr or branch> [--fix]` | review against the issue, the repo's rules and `guides/code-review.md`; report findings and a verdict. `--fix` fixes the review feedback on a PR through to green CI, replies and ready |
| `/ai-workflow:skill-feedback <feedback \| reconcile>` | turn feedback, or the learning logs of closed PRs, into approved edits to the skills and guides |
| `/ai-workflow:docs-updater` | bring `docs/` in line with the code |
| `/ai-workflow:sync-from-wasensi` | port Wasensi's skill, guide and template changes into this plugin |
| `/ai-workflow:pr-grind <pr>` | the Slack reviewer-bot loop on a PR; fixes inline, verifies before each push |
| `/ai-workflow:peer-review [--lenses <lens,lens>] [--since <sha\|@{u}>] [--herdr]` | a panel of read-only `peer-reviewer` lenses on the session's change (default critical) until every lens approves |
| `/ai-workflow:dump <text>` | file free-form input into the Obsidian vault's Project → Feature structure, after one confirmation |
| `/ai-workflow:release-pr [--dry-run] [head=staging] [base=master]` | open or refresh the `staging` → `master` release PR with a deploy checklist, post the Slack trigger, hand off to `/pr-grind`. Never merges |
| `/ai-workflow:worklog [date]` | today's worklog from GitHub activity and the daily note, written to the Obsidian daily note (runs as the `worklog-runner` agent) |
| `/ai-workflow:flow <idea \| folder \| PRD \| task list \| epic>` | the guided flow: dump → create-prd → create-tasks → refine-issues → herdr-dispatch of implement-issue; starts at the stage the input implies and stops for your go at each boundary |
| `herdr-dispatch` (skill) | open issues in herdr tabs, one `/ai-workflow:implement-issue <n>` each, in dependency order under a concurrency cap |

## The `aiw` CLI

```
aiw ui [--port N] [--allow-host HOST]   local web UI to start and track sessions
aiw paths                               resolve every path, create the state dirs
aiw ask                                 a headless session asks the user a question and pauses
aiw ci status                           check state plus the failing job's log
aiw threads list|resolve                PR review threads
aiw autopilot <owner/repo> <epic> on|off  switch autopilot for an epic (works without the UI)
```

## aiw ui

`aiw ui` serves a local web UI for starting and tracking headless Claude sessions. Until the
board rewrite lands it has three pages: **Sessions**, **New** and **Settings**. On first start
after an upgrade it deletes the old run data from the plugin data dir once and logs what it removed.

- It binds to loopback only. `--port` sets the port (default 8420).
- `--allow-host HOST` is repeatable and matches exactly: use `name:port`, or the bare name for the default 443 serve.
- To reach it over a tailnet: `tailscale serve --bg 8420`, then
  `aiw ui --allow-host <machine>.<tailnet>.ts.net`. It installs as a PWA.

**Planning.** One repo at a time; one card per PRD in `docs/prds/` (drafts included), in columns
PRD draft → In review → Approved → Tasks filed → Refined. The epic is the open issue labelled
`epic` and `prd-<slug>`; cards show its number, child-issue count and "x/y refined". Each card
offers the next step: a lens picker and panel progress on drafts, **Create tasks**, **Refine**, or
**Autopilot**. `GET /api/planning?repo=owner/repo`.

**Delivery.** One swimlane per open epic plus **No epic**, in columns Ready → In progress → Draft
PR → In review → Grinding → Merged (7 days). Only refined issues, or ones with a PR or live
session, show. A blocked card shows a lock with its open blockers and cannot start. Unblocked Ready
cards have **Start** (headless `/implement-issue`) and **Start in herdr**; In review cards have
**Grind** when the repo's auto-grind is off. Each lane has an **Autopilot** switch and shows
`running/cap`. A merged issue's worktree under `.worktrees/` and its branch are removed when clean;
otherwise the card is flagged and **Clean** lists what would be lost first.
`GET /api/delivery`, `POST /api/start` (409 for a live session, open PR or blocked issue),
`POST /api/autopilot`, `POST /api/cleanup`.

**Board data.** One GitHub GraphQL call per repo per poll, every 60 s (15 s while a PR's CI is
pending), kept in memory; a rate limit pauses fetching for 10 minutes and the boards show the last
data as stale. The stale banner says why (rate limit and its retry time, or gh's error) and has a
**Refresh** (`?refresh=1` on the board GET fetches now). No board shows before the first fetch. After each fresh poll the UI runs autopilot (refined, unblocked issues of switched-on
epics, by `priority:` label then number, up to the repo's cap), merge cleanup, and grind autostart
(a PR that turned ready on a repo with auto-grind on). Nothing runs on stale data, and the UI never
merges a PR.

**New.** Pick a skill (grouped, each with a one-line description; the last one is remembered),
a repo and the input. For `implement-issue`, `pr-review` and `pr-grind` the repo's open issues
or PRs are listed under the input (`GET /api/repos/<owner>/<repo>/open?kind=issue|pr`, one `gh`
page of 100); typing filters them. `worklog` offers Today, Yesterday, A day or A range (at most
31 days, one session per day, 3 running at once, the rest `queued`).

**Sessions.** Every session with its status, cost and token use (`$0.44 · 703k tok`, hover for
input and output), the transcript, and its answer page when it asked a question. Sessions
auto-resume after a rate limit, and the limit timer releases queued ones after a restart. A session
that has not finished has **Stop** on its page (`POST /api/sessions/<id>/stop`, after a confirm).

**Repo picker.** One picker for the registered checkouts (`checkouts.json`), searchable by name,
owner, project or path, recent first. A typed absolute path or **Browse for a folder…** registers a
checkout. **No repo yet** runs a session in the notes vault for create-prd and dump.

**Settings.** Named `claude` commands a session can launch with (one per account), the notes
vault path, the checkout list, the plan-usage (5h / 7d) per account shown in the header, and per
repo: auto-grind (default off), autopilot cap (1–5, default 2) and the Slack review channel grind
posts to (`repos[owner/repo]` in `ui_settings.json`; `autopilot` maps a repo to its epics).

**Notes vault.** With **No repo yet** and a new idea, New shows a **Vault folder**
(`05-Work/<Project>/<Feature>`) that follows the best match of your text as you type; **Suggest with
Claude** asks Haiku for an existing or new project and feature. create-prd writes its PRD to the
vault only (`--to obsidian`) there.

**Peer review.** New has a **Peer review** box. Ticking it shows the lenses the command offers
(`GET /api/peer-review`, from `config.json`), with critical ticked. A custom prompt becomes the
root session; its Ask file is the artifact. When the root ends its turn, the UI starts one
`peer-reviewer` session (Opus) per lens (`POST /api/review`, body `repo`, `artifact`, `lenses`,
optional `root_session`), each told to end with `Verdict: approve` or `Verdict: changes`. The UI
relays the verdicts to the root session, which revises and ends its turn, and the same lens sessions
re-review. A panel stops when every lens approves, or as **cap reached** after `peer_review.max_rounds`
(5) rounds; nothing auto-approves and nothing validates a verdict beyond that closing line (a missing
line counts as `changes`). `POST /api/review/<panel>/lens` drops or retries a lens. The session page
shows the panel's status; verdicts live under `peer-review/<panel>/round-<n>/<lens>.md`.

**AFK mode.** A timed autopilot run by the server, so it works with no browser open. Each tick it
answers every `aiw ask` round whose questions all carry a "(Recommended)" option, sends "Skip CI
for now" to a grind paused on CI (at most once per PR per window), and retries failed sessions on a
2m/10m/30m/1h backoff. When the window ends one push sums it up and the UI shows the log.
State is `afk.json`.

**Running it as a service.** `aiw ui` under supervisord or launchd (e.g. `brew services`) runs as
that daemon's process, not your terminal. On macOS, if the plugin or your repos live under
`~/Documents`, `~/Desktop` or `~/Downloads`, the daemon needs **Full Disk Access** or every start
fails with `Operation not permitted` (supervisord shows exit status 126). Grant it to the binary
that runs the daemon (for Homebrew supervisord, the `Python.app` of its Python, shown by
`ps -o command -p $(cat /opt/homebrew/var/run/supervisord.pid)`) in System Settings → Privacy &
Security → Full Disk Access, then `supervisorctl restart aiw-ui`. Keep `stderr_logfile` set in the
program's ini, or such a failure leaves no trace.

Optional push notifications and links live in `<data_dir>/ui.json` (the data dir is
`$CLAUDE_PLUGIN_DATA`, default `~/.claude/plugins/data/ai-workflow`):

```json
{"ntfy": {"server": "<ntfy-server-url>", "topic": "<topic>", "token": "<token>"},
 "public_url": "<https://your-ui-url>"}
```

The file must be mode 0600 (`chmod 600 <data_dir>/ui.json`) because it can hold a token;
a looser mode is ignored with a warning. `AIW_NTFY_SERVER`, `AIW_NTFY_TOPIC` and
`AIW_NTFY_TOKEN` override the file. `public_url` is the base for push click-through links.

**Security:** there is no app-level auth. Access relies on tailnet ACLs, so anyone who can
reach the URL can start sessions. Sessions run `claude --dangerously-skip-permissions` by
default, with no opt-out flag. Never use `tailscale funnel` (public exposure plus skip-permissions
is remote code execution), and on a shared machine any local user can reach the loopback port.

## Where state lives

Nothing stateful lives in this repo. `aiw paths` resolves it under `$CLAUDE_PLUGIN_DATA`
(default `~/.claude/plugins/data/ai-workflow`), which **survives plugin upgrades**.

| Path | Contents |
|---|---|
| `sessions/` | one directory per UI session: record, stream, answers |
| `ui_settings.json` | the named `claude` commands, the vault path |
| `checkouts.json` | the registered repo checkouts |
| `pr-grind/` | one markdown state file per PR under grind |
| `peer-review/` | one directory per panel: `panel.json` and `round-<n>/<lens>.md` verdicts |
| `afk.json` | the AFK window and its log |
| `ui.json` | push notifications and `public_url` (mode 0600) |
| `channels.json` | Slack ids and trigger templates for grind and release-pr |

The work's own state is on GitHub and in the repo's `docs/prds/` and `docs/tasks/`.

## Layout

```
skills/       create-prd, create-tasks, refine-issues, implement-issue, verifier-locally,
              pr-review, docs-updater, skill-feedback, sync-from-wasensi, pr-grind,
              peer-review, dump, release-pr, worklog, flow, herdr-dispatch
agents/       peer-reviewer, worklog-runner
guides/       engineering-workflow, code-review, skills
templates/    prd, epic, issue
commands/     code-review (a slash command)
run-engine/   route.py (the aiw CLI) · ui_*.py (the web UI) · peer_review, threads, ci, ask
              ui_static/ (vendored Preact/htm) · config.json · test_*.py
bin/aiw       PATH shim. NOT named `route`; see INSTALL.md Step 3.
docs/         HOW-IT-WORKS, INSTALL, REFERENCE, prds/, tasks/
```

## Tests

```bash
python3 run-engine/test_<name>.py     # one file
bash run-engine/run_tests.sh          # every test_*.py; also the pre-commit hook, the pre-push hook and CI
```

No network, no install step.
