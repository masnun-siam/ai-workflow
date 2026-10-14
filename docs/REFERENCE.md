# Reference

## Commands

| Command | Does |
|---|---|
| `/ai-workflow:run-issue <n> [--full] [--no-review] [--grind]` | the full pipeline: issue → reviewed PR (`--no-review` skips review and fix; `--grind` keeps working the PR's review rounds after the handback, off by default). Accepts an epic parent. |
| `/ai-workflow:intake <source> [--review [<lens,lens>] [--herdr]]` | normalize a Sentry link, BRD file, or vault note into an issue brief — used internally by `/gh-issue` and `/run-issue` (which never pass `--review`) |
| `/ai-workflow:dump <text> [--review [<lens,lens>] [--herdr]]` | file free-form input into the Obsidian vault's Project → Feature structure, after one confirmation |
| `/ai-workflow:gh-issue [--review [<lens,lens>] [--herdr]]` | file exactly one well-formed issue. It decomposes first; when the input splits into 2 or more tasks it creates nothing and ends `→ next: /create-prd <input>`. A standalone run ends `→ next: herdr-dispatch <n>` |
| `/ai-workflow:create-prd <requirement \| feature-folder> [--to <local,obsidian,wiki>] [--review [<lens,lens>] [--herdr]]` | grill a requirement into a PRD with its technical design (contracts, never code) and its epics, saved to `docs/prds/<slug>.md` (status Draft, In review, then Approved) and mirrored to the vault; `--review` runs the picked reviewer lenses (default critical; also CEO, CTO, security, QA, UX, performance) until every one approves (`--herdr`: one herdr tab per reviewer, terminal only); `--update <prd> <decisions>` records later decisions (plus a `## Change log` line once Approved); `/create-prd approve <prd-path \| slug>` sets Approved, files one epic per `## Epics` entry labelled `epic` + `prd-<slug>`, and writes the numbers back |
| `/ai-workflow:peer-review [--lenses <lens,lens>] [--since <sha\|@{u}>] [--herdr]` | a reviewer panel on Opus (critical, CEO, CTO, security, QA, UX, performance; default critical) on the session's change: the diff plus your final answer, checked against what you asked, until every picked lens approves. `--review` on `/create-prd`, `/intake`, `/dump` and `/gh-issue` runs the same loop on their draft before anything is saved or filed |
| `/ai-workflow:create-tasks <prd>` | split an Approved PRD into a saved, ordered list of one-PR tasks (`docs/tasks/<slug>.md`): each with an Area, a Parallel flag and dependencies inside its own epic, plus Waves and Shared files; tasks are never renumbered, only marked Changed or Dropped. Files no issues; ends `→ next: /refine-issues docs/tasks/<slug>.md` |
| `/ai-workflow:refine-issues docs/tasks/<slug>.md` | file each task as a `refined` sub-issue of its epic, after one confirmation, with `Depends on: #n` in the body and native blocked-by links (on an older `gh`, `/fix-blockers` sets them); runs one `aiw epic split` per epic; ends `→ next: herdr-dispatch <epic>` (when `--blocked-by` fell back, the report says to run `/fix-blockers <epic>` first) |
| `/ai-workflow:fix-blockers <parent>` | set GitHub's native "blocked by" relations between an epic's children from their `Depends on:` lines: previews, asks once, writes only the missing edges, reports (never deletes) edges no line names. A standalone command, not a Flow step |
| `/ai-workflow:jira-to-gh <KEY>` | turn a Jira ticket into exactly one issue the same way as `/gh-issue`; 2 or more tasks create nothing and end `→ next: /create-prd <jira-key-or-url>` |
| `/ai-workflow:pr-fix-comments <pr>` | work through a PR's review comments, confirming each |
| `/ai-workflow:issue-to-pr` | the interactive, non-unattended variant |
| `/ai-workflow:flow <idea \| folder \| PRD \| task list \| parent \| issue numbers>` | the guided flow (`/flow` for short): dump → create-prd → (Continue approves the PRD and files its epics) → create-tasks → refine-issues → herdr-dispatch for one feature; a bug goes gh-issue → dispatch. It starts at whichever stage the input implies and stops for your go at each boundary |

The default roster is researcher → planner → dev → reviewer → fixer. `run-dev` writes the
RED tests first, implements, and runtime-verifies in one dispatch, and also applies the
review findings. `--full` (or a `full` label) runs the seven-station roster with an
independent `run-sdet` and `run-verifier`. Use it for auth, migrations, payments, or public
API contracts. `--lean` and the `lean` label are deprecated aliases of the default. A
`refined` issue whose body passes `aiw refined` also skips the researcher and planner.

## The `aiw` CLI

The orchestrator never eyeballs a decision it can compute. Everything mechanical is a
subcommand:

```
aiw paths                          resolve every path, create the state dirs
aiw init | route | set             the ledger and the router
aiw precheck <station>             a station's pre-guard, before dispatching it
aiw refined                        plan from a refined issue body (skips researcher + planner)
aiw classify | resolve-review      score a diff, pick the specialist panel
aiw stack up|down|rebuild|status   the per-issue Docker test stack
aiw worktree create                the per-issue worktree
aiw pr open                        link the branch to the issue, push, open the PR
aiw threads list|resolve           PR review threads
aiw ci status                      check state plus the failing job's log
aiw gitnexus sync|index|clean      the code graph (best-effort)
aiw project-status                 GitHub Projects (best-effort)
aiw epic split|init|next|status    epic decomposition and sequencing
aiw epic blockers <dir> [--dry-run]   GitHub blocked-by edges from the children's Depends on lines
aiw peer-review new|next|verdict|diff   peer review: a fresh dir per run, open/decide rounds, record a checked verdict, the change to review
aiw ui [--port N] [--allow-host HOST]  local web UI to start and track sessions
```

## aiw ui

`aiw ui` serves a local web UI for starting and tracking headless Claude sessions.

- It binds to loopback only. `--port` sets the port (default 8420).
- `--allow-host HOST` is repeatable and matches exactly: use `name:port`, or the bare name for the default 443 serve.
- To reach it over a tailnet: `tailscale serve --bg 8420`, then
  `aiw ui --allow-host <machine>.<tailnet>.ts.net`.

**Flow and an approved PRD.** When the PRD step's feature folder already has an Approved PRD, Flow
doesn't rerun create-prd on it: it runs `create-prd --update "<folder>/PRD.md" <your request>` (the
request is added as a decision and, when it adds scope, a new FR) and then Tasks, which adds only
the new tasks and keeps existing issue numbers. When Dump files the input as a task and Flow skips
PRD and Tasks, those steps say so and offer **Write a PRD instead**.

**No repo yet.** For a new idea, the repo picker on New run and Flow has **No repo yet**: the
session runs in the notes vault (Settings → Notes vault) instead of a checkout. It works for
create-prd, dump, intake and a custom prompt; other commands say they need a repo. New run then
shows a **Vault folder** (`05-Work/<Project>/<Feature>`): it follows the best match of your text
against the existing folders as you type, **Suggest with Claude** asks Haiku (with your default
account) for an existing or new project and feature, and you can type either name. The session
gets the folder as a suggestion and confirms it with you before writing; create-prd writes its PRD
to the vault only (`--to obsidian`).

**Create repo.** Once a no-repo create-prd's PRD is **Approved**, its session page offers
**Create repo…**; Flow shows the same step before Tasks when it has no repo; and the repo picker has
**Create a new repo…** at any time. It asks for a name and a parent folder: type or paste it (`~` works), pick one of
the folders your repos already live in, or, in a browser on the Mac itself, use **Choose…** for
the macOS folder dialog. Over the tailnet only the node owner reaches it. It then makes `<parent>/<name>` with `git init`, a README (the PRD's
title and Overview, or just the name) and the PRD in `docs/prds/<feature>.md`. Nothing is committed
or pushed, and no GitHub repo is made. It is registered as `local/<name>`; GitHub commands (create-tasks included, since it files the
epic) refuse a `local/` repo until it has a GitHub `origin`, and the next repo listing re-registers it
under that `owner/repo`. In Flow, Tasks and Issues on a `local/` repo show **Publish to GitHub…**:
pick the owner (your account or an org, from `gh`), name and visibility (private by default); it
makes the first commit (README and PRD) if there is none, runs `gh repo create --source --push`,
re-registers the repo as `owner/name`, and the flow carries on (`POST /api/repos/publish`,
`GET /api/github/owners`). Routes: `GET /api/vault/folders`, `POST /api/vault/suggest`,
`GET /api/vault/prd?folder=`, `POST /api/repos/create`.

**Tokens.** Wherever a session's cost shows (board cards, the board's today total, Sessions, the
run page and its sessions tab, a transcript's result), its token use shows beside it, e.g.
`$0.44 · 703k tok`; hover for input (with the cached part) and output. The count comes from the
same `result` event as the cost; sessions recorded before this get theirs once from their stream.

**Repo picker.** New run, Flow, Dispatch and the Board filter share one repo picker
(`ui_static/repopicker.js`). It shows the repo's name and owner; click it (or press ↓) to open a
search box over the registered repos. Recently picked repos come first. Words match the repo name,
owner, project name or path. ↑/↓, Home/End, Enter and Esc work as in a menu. Where a run can use
any checkout (New run, Flow), typing an absolute path offers **Use this path**, and **Browse for a
folder…** opens the macOS folder dialog; a path that is a registered checkout becomes that repo.

**New run.** Commands are grouped (Build, Review, Plan, Capture), each with a one-line
description; the last one started is remembered. For `run-issue`, `issue-to-pr`, `pr-review` and
`pr-fix-comments`, the selected repo's open issues or PRs are listed under the input
(`GET /api/repos/<owner>/<repo>/open?kind=issue|pr`, one `gh` page of 100). Typing filters the list
by number or by words in the title and labels; clicking one fills the input in the form that
command takes. A typed number or URL still works when `gh` cannot answer.

**Worklog dates.** For `worklog`, New run offers Today, Yesterday, A day (a date picker) or A range
(from/to, at most 31 days, none in the future). A range starts one worklog run per day, since each
run writes that day's daily note. The runs share a batch (`batch` in POST /api/sessions), and the
server runs 3 of a batch at once: the rest wait as `queued` and start as earlier ones end, even with
the page closed (the limit timer also releases them after a UI restart). Stopping a queued run takes
it out of the queue. If some days fail to start, Start becomes **Retry N failed days**.

**Board.** A search box (`/` focuses it) matches `#N`, the title or the repo. **need you** counts
runs waiting on an answer, escalated, or with a paused grind; click it to show only those.
**Filters** adds Status (in progress, done), PR (none, open, merged, closed), CI (passing,
failing, running) and Grind (not started, grinding, paused, done); each option shows how many cards
it would leave, filters combine, and the active ones show as removable chips with "Showing N of M".
The repo and these filters are remembered; the search is not. A run whose Ledger lacks a PR or plan link is matched to its repo from the
registered checkouts, not guessed from the run dir name. A title `gh` could not fetch is retried
after 5 minutes, and a title fetched before is kept.

**Dispatch pipeline page.** A row whose PR GitHub reports merged shows **Merged**, whatever this
pipeline's own attempt did (a retry that could not start, say), and offers no Retry. Rows filter by
All, Needs attention, In progress, Open PRs and Merged. **Merge order** lists each PR with its state,
CI and review, highlights the first unmerged one as **Merge next**, and sits above the rows while any
PR is unmerged (collapsed at the bottom once all are merged).

**Merge.** The PR popup (any PR link) and each open PR in a pipeline's Merge order have a merge
button. It always squash-merges (`gh pr merge --squash`; the branch is kept, nothing else happens
after). A confirm comes first (focus on Cancel) and lists what is not ready: draft, conflicts,
failing or running CI, no approval or changes requested, behind the base, and, in a merge order,
earlier PRs not merged yet; merging anyway is allowed and GitHub still enforces its own rules
(`GET`/`POST /api/pulls/<owner>/<repo>/<n>/merge`).

**Clean up.** The dialog lists runs by repo with their issue titles; a repo's box ticks all its
runs. Quick picks: Safe (nothing unsaved, the default), Merged PRs, None. Neither a quick pick nor a
repo's box ever ticks a run with unsaved work: each needs its own tick, and the footer says how
many ticked ones will lose it.

**Running it as a service.** `aiw ui` under supervisord or launchd (e.g. `brew services`) runs as
that daemon's process, not your terminal. On macOS, if the plugin or your repos live under
`~/Documents`, `~/Desktop` or `~/Downloads`, the daemon needs **Full Disk Access** or every start
fails with `Operation not permitted` (supervisord shows exit status 126). Grant it to the binary
that runs the daemon (for Homebrew supervisord, the `Python.app` of its Python, shown by
`ps -o command -p $(cat /opt/homebrew/var/run/supervisord.pid)`) in System Settings → Privacy &
Security → Full Disk Access, then `supervisorctl restart aiw-ui`. Keep `stderr_logfile` set in the
program's ini, or such a failure leaves no trace.

**Peer review.** New run (both forms) and the Flow's PRD step have a **Peer review** box. Ticking
it shows the reviewers the command offers (from `GET /api/peer-review`, read from `config.json`),
with critical ticked. A doc command gets `--review <lenses>`. A custom prompt gets a fresh review
dir holding the prompt as `ask.md`, plus one line asking the session to run `/peer-review` with
that dir, the lenses and the HEAD at start. That line is not a gate. The session page shows
**peer review: approved / cap reached / unfinished / not run**, read from the review's rounds.

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

Nothing stateful lives in this repo. `aiw paths` resolves it at run start, under
`$CLAUDE_PLUGIN_DATA` (default `~/.claude/plugins/data/ai-workflow`), which **survives
plugin upgrades** — in-flight runs are not lost when you update.

| Key | Contents |
|---|---|
| `runs_dir` | one directory per run; `run.json` is the only source of truth |
| `pr_grind_dir` | one markdown file per PR under review |
| `channels` | `channels.json` — Slack ids and trigger templates |

## Layout

```
commands/     run-issue (the orchestrator) + 5 intake commands
agents/       12 run-* pipeline agents + ship, worklog-runner, gh-issue-factchecker
skills/       pr-review, pr-grind, herdr-dispatch, worklog, dump, create-prd, create-tasks, refine-issues, fix-blockers, flow, peer-review, 7 Laravel reviewers
run-engine/   engine.py (pure) · route.py (CLI) · checks.py (station post-checks)
              stack/worktree/threads/pr/ci/gitnexus/project/epic (mechanical phases)
              config.json (policy) · test_engine.py + test_scripts.py
bin/aiw       PATH shim. NOT named `route` — see INSTALL.md Step 3.
docs/         HOW-IT-WORKS, INSTALL, REFERENCE, adr/, prds/, tasks/
```

## Tests

```bash
python3 run-engine/test_engine.py     # the pure engine: routing, caps, contracts
python3 run-engine/test_scripts.py    # the mechanical phases
bash run-engine/run_tests.sh          # every test_*.py (~2 min); also the pre-push hook and CI
```

No network, no Docker, no install step.
