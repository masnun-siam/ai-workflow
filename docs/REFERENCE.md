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
aiw grind-mode                          print the grind mode, deep or simple (read by /pr-grind each round)
```

## aiw ui

`aiw ui` serves a local web app for starting and tracking headless Claude sessions and for seeing
what needs you across every watched repo. It is a React + TypeScript app (source in `ui/`) served
from the committed build in `run-engine/ui_dist/`, so using it never needs Node. On first start
after an upgrade it deletes the old run data from the plugin data dir once and logs what it removed.

- It binds to loopback only. `--port` sets the port (default 8420).
- `--allow-host HOST` is repeatable and matches exactly: use `name:port`, or the bare name for the default 443 serve.
- To reach it over a tailnet: `tailscale serve --bg 8420`, then
  `aiw ui --allow-host <machine>.<tailnet>.ts.net`. It installs as a PWA.
- `/` serves the app (`index.html`, never cached); `/assets/*` are hashed and cached for a year;
  `/sw.js`, `/manifest.webmanifest` and `/icons/*` are served from the root. `/next/` serves the same
  app for one more release.

**Routes** (hash routes, each with an optional `?repo=owner/name` that a shared link keeps):
`#/inbox` (default), `#/features`, `#/features/<slug>[/<tab>]`, `#/board`, `#/activity`,
`#/sessions/<id>`, `#/settings[/<section>]`. Old routes still open the matching page, so old
bookmarks and push-notification links work: `#/planning`, `#/delivery`, `#/answer/<id>`,
`#/session/<id>`, `#/dispatch/<id>`, `#/sessions` and `#/new` (opens Start). **Shortcuts:** `N` Start,
`G` then `I/F/B/A/S` to go to a page, `?` lists them, `Esc` closes the top panel. The palette
(⌘K / Ctrl+K) finds pages, every Start command, features, issues, PRs, sessions, switches repo and
turns Away mode on or off.

**Inbox.** Everything that needs you, across repos, grouped Blocking everything, Answer Claude, Decide,
Fix, Set up and Waiting (nothing to do); the rail badge and tab title count all but Waiting. Items: GitHub CLI
signed out; a session asking a question (answered inline); a peer review at its round cap or with every
lens approving (Approve PRD anyway, Run 2 more rounds); a PR ready to merge (Review and merge, see
**Merge rule**); a PR with merge conflicts (Resolve conflicts); a paused grind (Skip CI and continue, Stop grind); a failed session (Retry, Continue in
terminal); a merged issue whose worktree has unsaved work (Review and clean up); a `local/` repo with no
GitHub remote (Publish to GitHub); a usage-limited session (Resume on another account); a queued session
(Start now, Cancel). An item disappears within a poll after its condition clears.
`GET /api/inbox[?repo=]` builds it on the server from sessions, panels, grind state, cleanup flags, the
repo registry and the board polls; a repo whose board data is stale is listed in `stale` and contributes
session items only.

**Features.** One row per PRD in the current repo with its stage (PRD draft, PRD review, Approved,
Tasks, Building, Shipped), progress, a **Merge #n** button for each of its PRs ready to merge, and one
next-step button. A feature page shows a stage stepper, a
**Next step** box and tabs **Issues**, **PRD**, **Peer review** and **Sessions**. Issues: a table by
status with signals (priority, PR, CI, review, grind, live session, failed last run, cleanup), one
action per row (Refine, Start, Retry, Answer, Merge, Grind, Skip CI, Clean up), the **Auto-build**
switch with the repo's cap, **Add task** (`/create-tasks` with the text as a finding) and refine-picked.
PRD: rendered, **Edit** (**Save and commit** commits only that file on the checkout's current branch, not
pushed; refused if the file changed on disk since it opened) or **Ask Claude** (`/create-prd <path>
--update <request>`). The More menu has **Close epic** (closes the epic and every open child as
completed, `POST /api/epics/close`). `GET /api/planning?repo=`.

**Board.** Five columns: Needs refinement, Ready (blocked issues last, with a lock), Building (draft
PRs included), In review (grinding included), Merged (7 days). Grouped by feature (each lane shows
progress and its Auto-build switch) or All issues. Cards show their signals and one action; j/k and
h/l move between cards and columns. A ready issue with open blockers cannot start. `GET
/api/delivery`, `POST /api/start` (409 for a live session, open PR or blocked issue; herdr starts
answer `{session: null, via: "herdr", tab}` because herdr tabs are not tracked), `POST
/api/autopilot` (the Auto-build switch), `POST /api/cleanup`.

**Board data.** A PR belongs to an issue when GitHub links it, when its body says Closes, Fixes or
Resolves #n, or when its branch starts `issue-<n>-` (GitHub links closing keywords only for PRs into
the default branch, so a staging-based repo needs the last two). Each poll of a watched repo is a
1-point GraphQL probe (newest issue and PR update, open PRs' CI, conflict and review state); the full
query (about 6 points) runs only when the probe's answer changed, on **Refresh** or after a write, and
at least every 10 minutes. Results are kept in memory. A repo is watched while it has a live session or
was opened in the last 7 days. It polls every 60 s (15 s while a PR's CI is pending) while it has a live
session or the UI asked about it in the last 2 minutes (the global Inbox counts for every watched
repo), else every 10 minutes. Every response reports the token's GraphQL budget, which the agents share:
under 1000 points left, every repo polls every 10 minutes until the reset. A rate limit pauses fetching
until that reset (10 minutes when the budget was not low) and the boards show the last data as stale
with the reason and a **Refresh** (`?refresh=1` on the board GET fetches now). After each fresh poll the server runs Auto-build (refined, unblocked issues of
switched-on epics, by `priority:` label then number, up to the repo's cap), merge cleanup, and grind
autostart (a PR that turned ready whose issue has grinding on; a PR with no issue follows the repo's
auto-grind). Nothing runs on stale data, and nothing merges a PR without a click.

**Merge rule.** Each issue has a **Grinding** switch (in its panel); an untouched issue follows the
repo's auto-grind. A PR shows Merge (Inbox, Features list, feature Issues tab, Board) when it is not a
draft, does not conflict with its base (GitHub's `mergeable` is not `CONFLICTING`), CI is green and GitHub's review decision is approved (skipped when the repo's owner is your `gh`
login), and with grinding on its grind is also done (stopped from the UI counts). Turning grinding
on starts a grind at once when the PR is already ready and has none; turning it off stops a running or
paused grind (the PR stays open). Delivery cards carry `grind_on` and `mergeable`. The switches are in
`issue_grind.json`. `POST /api/grind/issue` (`{repo, issue, on}`).

**Panels.** An issue and its PR share one side panel (full screen on a phone): an **Issue** tab, and
once the issue has a PR, **PR overview**, Checks, Conversation, Files and Commits beside it. Opened on
an issue it starts on Issue; opened from a PR action (Merge, Open PR) on PR overview; a PR with no
issue on the board has only the PR tabs. The header holds the **Grinding** switch and, while a grind
runs or is paused, **Open Slack thread**. The Issue tab shows the body, comments (with a comment box),
blockers and sessions, and close (completed or not planned) or reopen. PR overview has grind state with
**Skip CI** and **Stop**; the footer has **Merge** on every tab
(a merge commit, never squash; the confirm lists failing or running checks, requested changes and a
missing approval but does not block; disabled while the PR conflicts with its base, next to **Resolve
conflicts**). Resolve conflicts, also
the row action and an Inbox Fix item for a conflicting PR, starts one session that merges the base into
the PR branch in its worktree (never a rebase or force-push), resolves, runs `/verifier-locally` and
pushes; while it runs the button is a **Resolving…** link to it. Once the merge rule holds the usual
ready-to-merge Inbox item appears.
`POST /api/issues/<o>/<r>/<n>/comment|state`, `POST /api/pulls/<o>/<r>/<n>/comment|merge`,
`POST /api/grind/skip-ci|stop` (`{repo, pr}`; 409 when there is nothing to skip or stop),
`GET /api/prd?repo=&path=` (returns `sha`), `POST /api/prd` (takes `base_sha`; 409 when it changed).

**Start** (the New button, `N` or ⌘K). Commands grouped Plan, Build, Review, Ship, Capture and
Maintain, each with a one-line description; the last one is remembered. Pick **Where** (a registered repo,
or **No repo yet** for `create-prd`, `dump`, `day` and the custom prompt, which run in the notes vault
with a **Vault folder**), the input, and **Run on** an account (a limited account says the run will
queue). `implement-issue`, `pr-review` and `pr-grind` list the repo's open issues or PRs under the
input (`GET /api/repos/<owner>/<repo>/open?kind=issue|pr`, one `gh` page of 100); a pasted issue or PR URL
of a registered repo switches the repo. `worklog` offers Today, Yesterday, A day or A range (at most 31
days, one session per day, 3 running at once, the rest `queued`). **Custom** takes any prompt and runs
with permissions skipped. Starting anything opens its session page; a duplicate start (409) offers to
open the running session.

**Activity and sessions.** Live sessions as cards, history as a table with search, a result filter
and cost today; **Clean up** lists finished sessions by repo before removing them. A session page
has banners for waiting (inline answer), limited (reset time, **Resume on another account**, **Don't
auto-resume**), failed (**Retry**, **Continue in terminal**) and queued (**Start now**), the transcript, a
composer (a prompt queues while a turn runs), and a facts box with cost and tokens (`$0.44 · 703k tok`).
Sessions auto-resume after a rate limit, and the limit timer releases queued ones after a restart.
Actions: **Stop** (`POST /api/sessions/<id>/stop`, after a confirm), **Resume**, **Rerun** (replays the
recorded start request, same repo and account; `POST /api/sessions/<id>/rerun`), and **Start now**
(`POST /api/sessions/<id>/start-now`: starts a batch-queued session at once, past the batch cap; 409 when
the session is not queued or is waiting on an account limit, which starts by itself at the reset).

**Away mode.** A timed run by the server, so it works with no browser open (30 min to 4 h or an end
time; **+30 min** and **I'm back** end or extend it). Each tick it answers every `aiw ask` round whose
questions all carry a "(Recommended)" option, sends "Skip CI for now" to a grind paused on CI (at most
once per PR per window), and retries failed sessions on a 2m/10m/30m/1h backoff. When the window ends
one push sums it up and the Inbox shows a "While you were away" log until dismissed. State is
`afk.json`. `POST /api/afk` (start), `POST /api/afk/stop|dismiss`.

**Settings** (`#/settings/repos|accounts|notifications|review|vault`). **Repositories**: the global
**Grinding** mode, Deep (default: a grind runs until the reviewer has no blocker or should-fix left) or
Simple (a grind stops, fixing nothing more, at the round where the PR is approved: the reviewer's
review is an approval or GitHub's reviewDecision is approved). `/pr-grind` reads it every round, so a
change reaches running grinds too (`grind_mode` in `ui_settings.json`). Then one table of
the registered checkouts (`checkouts.json`) with GitHub status or **Publish**, auto-grind (default off),
Auto-build cap (1–5, default 2), the Slack review channel grind posts to (`repos[owner/repo]` in
`ui_settings.json`; `autopilot` maps a repo to its epics) and **Remove** (its clone is untouched), plus
scan folders, **Find repos** and **Check remotes** (`gh repo view` on every repo, failures first).
**Claude accounts**: the named `claude` commands a session can launch with, one per account; their plan
usage (5h / 7d) shows in the rail. **Notifications** edits `ui.json` (written mode 0600; a token or
password is never sent back to the browser, and an empty box keeps the saved one). **Peer review**
sets the rounds cap, the lenses ticked by default and each lens prompt; changes are saved to
`<data_dir>/config.json` and laid over the shipped `run-engine/config.json`, so **Reset to defaults**
just removes that file. **Notes vault** sets the vault path. With no repos registered the app opens
an onboarding page that checks `gh` and a Claude account, then scans folders.
`GET|POST /api/settings/notify`, `GET|POST /api/settings/review`, `POST /api/repos/remove`,
`POST /api/repos/check`.

**Notes vault.** With **No repo yet** and a new idea, Start shows a **Vault folder**
(`05-Work/<Project>/<Feature>`) that follows the best match of your text as you type; **Suggest with
Claude** asks Haiku for an existing or new project and feature. create-prd writes its PRD to the
vault only (`--to obsidian`) there; **Create repo** later turns it into a repo.

**Peer review.** The feature page's **Peer review** tab (and Start's lens picker for `peer-review` and
Custom) lists the lenses the command offers (`GET /api/peer-review`, from `config.json`), with
critical ticked. A custom prompt becomes the root session; its Ask file is the artifact. When the
root ends its turn, the UI starts one `peer-reviewer` session (Opus) per lens (`POST /api/review`, body
`repo`, `artifact`, `lenses`, optional `root_session`), each told to end with `Verdict: approve` or
`Verdict: changes`. The UI relays the verdicts to the root session, which revises and ends its turn,
and the same lens sessions re-review. A panel stops when every lens approves, or as **cap reached**
after `peer_review.max_rounds` (5) rounds; `POST /api/review/<panel>/rounds` (`{add: 1..5}`) raises
a capped panel's limit. Nothing auto-approves and nothing validates a verdict beyond that closing
line (a missing line counts as `changes`). `POST /api/review/<panel>/lens` drops or retries a lens.
Verdicts live under `peer-review/<panel>/round-<n>/<lens>.md`.

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
| `issue_grind.json` | each issue's Grinding switch, by repo (unset issues follow the repo's auto-grind) |
| `peer-review/` | one directory per panel: `panel.json` and `round-<n>/<lens>.md` verdicts |
| `afk.json` | the Away mode window and its log |
| `ui.json` | push notifications and `public_url` (mode 0600) |
| `config.json` | peer-review overrides from Settings, laid over `run-engine/config.json` |
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
run-engine/   route.py (the aiw CLI) · ui_*.py (the web UI server) · peer_review, threads, ci, ask
              ui_dist/ (the built UI, committed) · config.json · test_*.py
ui/           the web UI source: React + TypeScript + Vite
bin/aiw       PATH shim. NOT named `route`; see INSTALL.md Step 3.
docs/         HOW-IT-WORKS, INSTALL, REFERENCE, prds/, tasks/
```

## Tests

```bash
python3 run-engine/test_<name>.py     # one file
bash run-engine/run_tests.sh          # every test_*.py; also the pre-commit hook, the pre-push hook and CI
```

No network, no install step. The UI has its own checks, in `ui/` (Node 20; plugin users never need it):

```bash
cd ui && npm ci && npm run typecheck && npm test && npm run build
```

The `ui` CI job runs those and fails if the committed `run-engine/ui_dist/` differs from the build.
`run-engine/test_ui_static.py` checks the server's static serving, Host/Origin guard and cache headers
against the committed build.
