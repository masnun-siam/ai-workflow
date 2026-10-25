# Reference

## Commands

| Command | Does |
|---|---|
| `/ai-workflow:create-prd <requirement>` | interview a requirement into a PRD with its technical design, saved to `docs/prds/<slug>.md`; `--update` records later decisions; `approve` files one epic per `## Epics` entry |
| `/ai-workflow:create-tasks <prd \| finding>` | split an Approved PRD into one-PR tasks, created as child issues of the epic with blocked-by links; or file one issue for a finding |
| `/ai-workflow:refine-issues <epic or issues>` | write a WHAT, WHY and HOW into each child issue, label it `refined` and move it to Ready on the board once unblocked |
| `/ai-workflow:implement-issue <n \| epic>` | one refined issue (or an epic's next Ready one) to a Ready PR: worktree, local checks, local review, draft PR, CI, review comments; after the merge, close and clean up |
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
| `/ai-workflow:flow <idea \| folder \| PRD \| task list \| epic>` | the guided flow: dump → create-prd → create-tasks → refine-issues → a dispatch of the epic; starts at the stage the input implies and stops for your go at each boundary |
| `/ai-workflow:herdr-dispatch <epic> [--max N] [--grind off\|simple\|full] [--ci wait\|defer\|ignore] [--auto-merge] [--feature-branch <name>] [--model M] [--effort E]` | run an epic's issues as a dispatch in herdr tabs: preview, confirm, start, then relay what needs you (see **Dispatches**) |

## The `aiw` CLI

```
aiw ui [--port N] [--allow-host HOST]   local web UI to start and track sessions
aiw paths                               resolve every path, create the state dirs
aiw ask                                 a headless session asks the user a question and pauses
aiw ci status                           check state plus the failing job's log
aiw threads list|resolve                PR review threads
aiw grind-mode [--pr <url>]             print the grind mode, deep or simple: the PR's dispatch decides, else
                                        Settings (read by /pr-grind each round)
aiw dispatch plan|start <epic> [flags]  preview or start a dispatch (flags as herdr-dispatch, plus
                                        --runner herdr|headless and --workspace <herdr workspace id>);
                                        an epic only: picked issues dispatch from the UI
aiw dispatch ls|show <id>               list dispatches, or one as JSON (also those of picked issues
                                        started from the UI, listed by title)
aiw dispatch set <id> key=value...      change max, grind, ci, auto_merge, model, effort while it runs
aiw dispatch pause|resume|cancel <id>   the whole dispatch (pause stops new lanes only)
aiw dispatch lane <id> <n> <action>     pause, resume, retry, skip, merge, hold, unhold, or send "<text>"
aiw dispatch watch <id> [--since T]     block until an event needs you; prints it and the next --since
aiw dispatch end <id> open-pr|qa|grind-pr  an end-of-dispatch action, run by the server
```

## aiw ui

`aiw ui` serves a local web app for starting and tracking headless Claude sessions and for seeing
what needs you across every watched repo. It is a React + TypeScript app (source in `ui/`) served
from the committed build in `run-engine/ui_dist/`, so using it never needs Node. On first start
after an upgrade it deletes the old run data from the plugin data dir once and logs what it removed.

- Every text it hands to Claude (a start, a queued or rate-limited start when it begins, an answer, a typed prompt, a resume) is rewritten by `repo_skills.resolve` against the session's working directory: a plugin skill command becomes `/<name>` when the repo has `.claude/skills/<name>/SKILL.md`, else `/ai-workflow:<name>`. A session's stored `command` is what its latest own start ran; answers and resumes leave it alone. A queued or limited session shows the raw text until it starts.
- It binds to loopback only. `--port` sets the port (default 8420).
- `--allow-host HOST` is repeatable and matches exactly: use `name:port`, or the bare name for the default 443 serve.
- To reach it over a tailnet: `tailscale serve --bg 8420`, then
  `aiw ui --allow-host <machine>.<tailnet>.ts.net`. It installs as a PWA.
- `/` serves the app (`index.html`, never cached); `/assets/*` are hashed and cached for a year;
  `/sw.js`, `/manifest.webmanifest` and `/icons/*` are served from the root.

**Routes** (hash routes, each with an optional `?repo=owner/name` that a shared link keeps):
`#/inbox` (default, and `#/`), `#/features[?tab=active|shipped|changes]` (`active` when absent),
`#/features/<slug>[/<tab>]`, `#/issues` (redirects to `#/features?tab=changes`),
`#/dispatches[?new=<owner/repo#n>]` (`new` opens Run an epic on that epic),
`#/dispatches/<id>[?lane=<owner/repo#n>]`, `#/activity`, `#/sessions/<id>`, `#/settings[/<section>]`.
Anything else is a not-found page. **Shortcuts:** `N` Start, `G` then `I/F/D/A/S` to go to a page, `?` lists them, `Esc` closes the top panel. The palette
(⌘K / Ctrl+K) finds pages, every Start command, features, issues, PRs, sessions, switches repo and
turns Away mode on or off. Its first group, **Actions here**, lists every enabled action registered on the page, the open panel and the selected row (and the items of mounted menus, via `Menu`'s `paletteLabel`), labelled as the button is, with its key; choosing one does what a click does.

**Inbox.** Everything that needs you, across repos, grouped Blocking everything, Answer Claude, Decide,
Fix, Set up and Waiting (nothing to do); the rail badge and tab title count all but Waiting. Items: GitHub CLI
signed out; a session asking a question (answered inline); a peer review at its round cap or with every
lens approving (Approve PRD anyway, Run 2 more rounds); a PR ready to merge (Review and merge, see
**Merge rule**); a PR with merge conflicts (Resolve conflicts); a paused grind (Skip CI and continue, Stop grind); a failed session (Retry, Continue in
terminal); a merged issue whose worktree has unsaved work (Review and clean up); a `local/` repo with no
GitHub remote (Publish to GitHub); a usage-limited session (Resume on another account); a queued session
(Start now, Cancel); an issue in a dispatch that needs you, is held or hit a usage limit (Open, Retry), its
PR waiting for your merge (Merge), and a finished dispatch (What next, Dismiss). An issue a running dispatch
owns shows once, as its dispatch row: the generic PR-ready, conflict, paused-grind and failed-session rows
are dropped for it. An item disappears within a poll after its condition clears.
`GET /api/inbox[?repo=]` builds it on the server from sessions, panels, grind state, cleanup flags, the
repo registry and the board polls; a repo whose board data is stale is listed in `stale` and contributes
session items only.

**Features.** One row per PRD in the current repo with its stage (PRD draft, PRD review, Approved,
Tasks, Building, Shipped), progress, its running dispatch (or that it needs you), a **Merge #n** button
for each of its PRs ready to merge, and one next-step button, under three tabs: **In progress**,
**Shipped** and **Small changes** (the tab is `?tab=` in the URL). A PRD whose header says `**Status:** Done` counts as Shipped. **Small changes** holds the open
issues of the repo that belong to no feature (no epic, or an epic with no PRD here), grouped by status
in the same table as a feature's Issues tab. Above them, **Describe a bug or small change** and
**Create task** start one headless `/create-tasks` session (on `opus` at `medium`) that files the issue
with no PRD and refines it in the same session; while it lives it shows as a pending row (Queued,
Creating… or Needs you, with Watch or Answer) and Refine is locked on unrefined rows. A pick bar: tick
unrefined, ready or blocked rows a dispatch does not own, then **Refine N** (one `/refine-issues`
session on the picked unrefined ones), **Run N** (Run small changes on the picked refined ones) or
**Clear**. A feature page shows a stage stepper, a
**Next step** box and tabs **Issues**, **PRD**, **Peer review** and **Sessions**. Issues: a table by
status with signals (priority, PR, CI, review, grind, live session, failed last run, cleanup), one
action per row (Refine, Start, Retry, Answer, Merge, Grind, Skip CI, Clean up; an issue a dispatch owns
shows its dispatch stage, what it is doing, and **In dispatch** instead), **Run epic** (opens Run an epic
on the feature's epic; also in the page head and the Next step box, which become **Open dispatch** with
its progress while one runs), **Add task** (`/create-tasks` with the text as a finding) and refine-picked.
PRD: rendered, **Edit** (**Save and commit** commits only that file on the checkout's current branch, not
pushed; refused if the file changed on disk since it opened) or **Ask Claude** (`/create-prd <path>
--update <request>`). The More menu has **Close epic** (closes the epic and every open child as
completed, `POST /api/epics/close`). `GET /api/planning?repo=`.

Issues start one at a time from their row (**Start**); a whole epic runs as a dispatch. `GET
/api/delivery` (the issue data behind Features and Small changes), `POST /api/start` (headless only; 409
for a live session, an open PR, a blocked issue or an issue a running dispatch owns), `POST
/api/cleanup`.

**Issue data.** A PR belongs to an issue when GitHub links it, when its body says Closes, Fixes or
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
with the reason and a **Refresh** (`?refresh=1` on the board GET fetches now). After each fresh poll the server runs merge cleanup and grind autostart (a PR that
turned ready whose issue has grinding on, unless a dispatch lane owns it; a PR with no issue follows the
repo's auto-grind). Nothing runs on stale data, and outside a dispatch with auto-merge on nothing merges
a PR without a click.

**Merge rule.** Each issue has a **Grinding** switch (in its panel); an untouched issue follows the
repo's auto-grind. A PR shows Merge (Inbox, Features list, feature Issues tab, Small changes tab) when it is not a
draft, does not conflict with its base (GitHub's `mergeable` is not `CONFLICTING`), CI is green and GitHub's review decision is approved (skipped when the repo's owner is your `gh`
login), and with grinding on its grind is also done (stopped from the UI counts). Turning grinding
on starts a grind at once when the PR is already ready and has none; turning it off stops a running or
paused grind (the PR stays open). Delivery cards carry `grind_on` and `mergeable`. The switches are in
`issue_grind.json`. `POST /api/grind/issue` (`{repo, issue, on}`).

**Panels.** An issue and its PR share one side panel (full screen on a phone): an **Issue** tab, and
once the issue has a PR, **PR overview**, Checks, Conversation, Files and Commits beside it. Opened on
an issue it starts on Issue; opened from a PR action (Merge, Open PR) on PR overview; a PR with no
issue has only the PR tabs. The header holds the **Grinding** switch (for an issue a dispatch owns: its
dispatch stage and **Open dispatch** instead, since the dispatch grinds and merges by its own settings) and, while a grind
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

**Dispatches.** `#/dispatches` lists running dispatches as cards (progress, the issues that need you)
and the rest as history; **Run an epic** takes an epic (typed, or picked from the repo's
epics), grind mode (Off, Simple, Full), auto-merge, lanes at once (1–10), a feature branch, model and
effort, then **Preview** shows the waves and warnings (unrefined issues, cycles, missing checkouts,
repos without a Slack channel, open blockers outside the epic) before **Start**. Lanes started here run
as headless sessions (the same dialog, given picked issues, becomes **Run small changes**: chips instead of the epic field, no feature branch, `issues` in the request; lists show it by its title, "Small changes: #412, #415", and `owner/repo`); `herdr-dispatch` starts herdr ones, and both show here. `aiw dispatch plan|start` and `herdr-dispatch` take an epic only. A dispatch page has the
live settings, **Pause**/**Resume**/**Cancel**, a one-sentence summary with time and spend, a **Needs
you** strip (each issue waiting on you with its one action: Merge, Answer, Retry), the issues as a
**Graph** (Starts first, Then: columns by what they wait for, edges to dependents, the repo on cards when
the epic spans repos) or a **List**, each with a plain line on what it is doing now, an issue panel (what
is happening and its main action, a step bar, the question form when its session asks one, a message box,
its transcript or herdr pane text, and Pause, Merge now, Hold the merge, Retry, Skip in a menu) and the
activity feed in plain sentences. **Retry** on red CI asks the issue's session to fix CI. When every lane is done it offers **Open PR from
<branch>**, **Run QA** and **Grind the final PR**; none runs by itself, and a dispatch of picked issues offers none of them.
The server ticks every running dispatch every 30 s from the board poll, the grind state files and each
lane's session; grind rounds a lane owns are typed into the lane (`dispatch-due:` in the grind state)
instead of starting a separate session, and the epic is re-read every 5 minutes so new children join; a finished (`done`) dispatch that gains one goes to `paused` until the new issues are refined and the user presses **Resume** (a dispatch of picked issues re-reads only its listed issues; none joins).
`GET /api/dispatches`, `GET /api/dispatches/<id>` (with events; `issues` is the list or null), `GET /api/dispatches/<id>/lane?key=`,
`POST /api/dispatches` (`{epic, settings}` or `{issues: ["owner/repo#n", ...], settings}`, never both; 1 to 30 issues in one repo, no `feature_branch` (`settings.base_branch` is allowed); 400 for both or neither, a bad ref, more than 30, two repos, a feature branch or no open issue; 409 when a picked issue is a lane of a dispatch not done or cancelled), `POST /api/dispatches/plan` (the same body), `POST
/api/dispatches/<id>/settings|state|lane|end|seen`. `settings.base_branch` (a branch name or null, same name rule as `feature_branch`, must differ from it) is fixed at start: a settings edit that contains it is 400 `base_branch is fixed at start`.

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
composer (a prompt queues while a turn runs), and a facts box with cost, tokens (`$0.44 · 703k tok`), model and effort.
Sessions auto-resume after a rate limit, and the limit timer releases queued ones after a restart.
Actions: **Stop** (`POST /api/sessions/<id>/stop`, after a confirm), **Resume**, **Rerun** (replays the
recorded start request, same repo and account; `POST /api/sessions/<id>/rerun`), and **Start now**
(`POST /api/sessions/<id>/start-now`: starts a batch-queued session at once, past the batch cap; 409 when
the session is not queued or is waiting on an account limit, which starts by itself at the reset).

**Away mode.** A timed run by the server, so it works with no browser open (30 min to 4 h or an end
time; **+30 min** and **I'm back** end or extend it). Each tick it answers every `aiw ask` round: at once
when all its questions carry a "(Recommended)" option (planning interviews included), otherwise through a
read-only **answerer** (`agents/away-answerer.md`, Opus, medium effort, started without the permission bypass
and with `--allowedTools` set to the agent's `tools:` list). A valid reply resumes the session and is logged
`by: opus`; a hold, or a second failed answerer (failed, rate limited, invalid reply, over 10 min), is logged
`kind: held` and the round waits for you. Your own answer, or the window ending, stops the answerer with no
log row. It also sends "Skip CI for now" to a grind paused on CI (at most
once per PR per window), and retries failed sessions, and held or stopped dispatch issues, on a 2m/10m/30m/1h backoff (a
dispatch issue asking a question gets the recommended answer like any session). When the window ends
one push sums it up and the Inbox shows a "While you were away" summary until dismissed: one row per answered or held round (time, session, picker chip Recommended/Opus/Held, each question and pick, Opus's reasons, cost and answerer transcript link, a checkbox on answers not yet changed). **Change N selected** beside Dismiss opens a dialog with the question form for each ticked round, prefilled with the logged picks; Submit posts `POST /api/afk/change` and one toast reports each session as sent, queued or the refusal; sent and queued rows then show **Changed**; retry and older entries stay one-liners. Each answer entry carries `id` (`<session id>:<round id>`), `by` (`recommended` or `opus`), `questions` (the round as the session holds it, plus `picked` and `why`), `answerer`, `cost` and `changed`, besides the `question`/`picked` summary strings. State is
`afk.json`. `POST /api/afk` (start), `POST /api/afk/stop|dismiss`.
`POST /api/afk/change` sends changed answers back: body `{"changes": [{"id": "<sid>:<round>", "answers": {"0": {"labels": [...]} | {"other": "text"}, ...}}]}` (1 to 50 answer entries of the undismissed summary that are not `changed`; answers validated like a human answer; an entry with no changed question is refused). Each session gets one turn (old and new answer of each changed question, then "Redo whatever depended on the old answers") through `send_prompt` with a 60,000-character limit. 200 `{"results": [{"sid", "ids", "state": "sent"|"queued"} | {"sid", "ids", "error"}]}`: a session waiting on a question, with a queued prompt, blocked by another live session for its issue, or gone is refused alone and its entries stay changeable; the others are sent and set `changed`. 400 for a malformed body or failed validation (nothing sent), 409 with no undismissed summary.

**Settings** (`#/settings/repos|accounts|notifications|review|vault|server`). **Repositories**: the global
**Grinding** mode, Deep (default: a grind runs until the reviewer has no blocker or should-fix left) or
Simple (a grind stops, fixing nothing more, at the round where the PR is approved: the reviewer's
review is an approval or GitHub's reviewDecision is approved). `/pr-grind` reads it every round, so a
change reaches running grinds too (`grind_mode` in `ui_settings.json`). The last-used run model
(`opus`, `sonnet`, `haiku`) and effort (`low` to `max`) are `run_model` / `run_effort` there (null: Claude's
default); `POST /api/sessions` and `POST /api/start` take optional `model` / `effort`, added as `--model` /
`--effort` on every spawn of that session and replayed by Rerun; only a settings save changes the saved pair. The feature flow's PRD, tasks and refine starts always send `opus` / `medium` (`PLAN_RUN`) and never touch the saved pair. Then one table of
the registered checkouts (`checkouts.json`) with GitHub status or **Publish**, auto-grind (default off),
the Slack review channel grind posts to (`repos[owner/repo]` in `ui_settings.json`; a repo without one
skips grinding in a dispatch) and **Remove** (its clone is untouched), plus
scan folders, **Find repos** and **Check remotes** (`gh repo view` on every repo, failures first).
**Claude accounts**: the named `claude` commands a session can launch with, one per account; their plan
usage (5h / 7d) shows in the rail. **Notifications** shows the matrix of 11 events by Browser, ntfy and This Mac: one switch per cell, saved at once. Each column header shows the channel's state and a Send test button (Browser tests itself; ntfy and This Mac call `POST /api/settings/notify/test` and toast the result; This Mac is disabled off a Mac) (`POST /api/settings/notify/channel`; a failed save reverts the switch and toasts). Below it, "Phone push (ntfy)" edits `ui.json` (written mode 0600; a token or
password is never sent back to the browser, and an empty box keeps the saved one). **Peer review**
sets the rounds cap, the lenses ticked by default and each lens prompt; changes are saved to
`<data_dir>/config.json` and laid over the shipped `run-engine/config.json`, so **Reset to defaults**
just removes that file. **Notes vault** sets the vault path. With no repos registered the app opens
an onboarding page that checks `gh` and a Claude account, then scans folders.
`GET|POST /api/settings/notify`, `POST /api/settings/notify/test` (`{channel: "ntfy"|"mac"}`: one sample push on that channel alone, ignoring the matrix and Away mode; 200 `{ok}` or `{ok: false, error}` with an HTTP status, error type or "ntfy is not set up" / "Only on macOS", never a credential; `browser` or an unknown channel is 400), `POST /api/settings/notify/channel` (one event × channel switch,
`{event, channel, on}`; `GET` also returns `matrix`, `events`, `ntfy_ready` and `mac`), `GET|POST /api/settings/review`, `POST /api/repos/remove`,
`POST /api/repos/check`.
`GET /api/notifications?after=<id>` is the in-memory browser feed (`ui_feed.py`, newest 200, empty after
a restart): `{latest, events}` with the entries newer than `after`, at most the 5 newest, oldest first;
no `after`, or one above `latest`, gives `events: []`; a non-integer `after` is 400. Browser notifications
need an open aiw tab or the installed PWA with permission granted: `useBrowserNotifier` (mounted in `Shell`) polls
this feed, shows each new event via the service worker (`ui/src/lib/notifier.ts`), and `sw.js` handles the click.

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
 "public_url": "<https://your-ui-url>",
 "channels": {"done": {"ntfy": false}}}
```

`channels` holds only the matrix cells (event → `browser`/`ntfy`/`mac` → bool) changed from their
defaults; unknown keys and non-boolean values are ignored and dropped on the next save.

The file must be mode 0600 (`chmod 600 <data_dir>/ui.json`) because it can hold a token;
a looser mode is ignored with a warning. `AIW_NTFY_SERVER`, `AIW_NTFY_TOPIC` and
`AIW_NTFY_TOKEN` override the file. `public_url` is the base for push click-through links.

For clickable macOS banners run `brew install terminal-notifier` on the host and restart `aiw ui`; without it banners still show (through AppleScript) but cannot open a link.

**Security:** there is no app-level auth. Access relies on tailnet ACLs, so anyone who can
reach the URL can start sessions. Sessions run `claude --dangerously-skip-permissions` by
default, with no opt-out flag. Never use `tailscale funnel` (public exposure plus skip-permissions
is remote code execution), and on a shared machine any local user can reach the loopback port.

## Repo copies of skills

A repo can replace any plugin skill with its own copy. The same name wins, even when the repo's
skill does something else. To undo it, delete the copy.

**The rule** (`run-engine/repo_skills.py`):

- A copy is `<cwd>/.claude/skills/<name>/SKILL.md`, a readable file (symlinks followed), where
  `<cwd>` is the session's or herdr tab's working directory.
- It is checked at every spawn and every send, never cached: new sessions, queued and rate-limited
  starts when they begin, answers, typed prompts (Start dialog, Send box), auto-resumes, pr-grind
  re-entries, peer-review panels and herdr tabs alike.
- Every plugin skill command in the text, at the start or inline, in either spelling, becomes
  `/<name>` when the copy exists, else `/ai-workflow:<name>`. Only names under the plugin's
  `skills/` (folders with a `SKILL.md`) are rewritten.
- The stored command shows which copy ran (`/implement-issue 12` or `/ai-workflow:implement-issue 12`).
- The one exception is the vault's name suggestion (`claude -p` with no skill and no session record).

**Hand-offs between skills** follow the guide's "Repo skills win" rule
(`guides/engineering-workflow.md`, Repository settings): the skill checks
`<worktree root>/.claude/skills/<name>/SKILL.md` with Read or Glob and runs `/<name>` if it exists,
else `/ai-workflow:<name>`.

**Guides and templates:** the repo's `docs/guides/<name>.md` and `docs/templates/<name>.md` win
over the plugin's `guides/` and `templates/`. Every workflow skill now reads "Repository settings"
first (all but `skill-feedback`, `sync-from-wasensi` and `worklog`, which work on the plugin or
your notes).

**Agents are never overridden:** `ai-workflow:peer-reviewer`, `away-answerer` and `worklog-runner` are always the plugin's.

**Caveats:**

- Commit repo copies to the base branch. The engine checks the checkout, and a skill's hand-off
  checks its worktree, which is made from the base branch; a copy left uncommitted or on another
  branch is missed by one of them.
- Do not keep a personal skill (`~/.claude/skills/<name>`) named like a plugin skill. Claude Code
  ranks it above the repo's, so it runs while the stored command still reads like the repo copy.
- Trust: a repo copy runs with the session's permissions (`--dangerously-skip-permissions`). Only
  run the workflow on repos whose `.claude/` you trust.

**What a copy must keep so the UI can still drive it:**

| Skill | Keep | Read by |
|---|---|---|
| pr-grind | State file `<pr_grind_dir>/<owner>-<repo>-<pr>.md` with the header keys `owner`, `repo`, `number`, `thread`, `author`, `reviewer`, `paused`, `done`, `next-poll`, `poll-since`, `ci-seen`, `dispatch-due` | `ui_runner._valid`, `_new_review`, `prgrind_tick`; `ui_dispatch` (`dispatch-due`); `ui_grind.index`. pr-grind's own list: `## State file` |
| pr-grind | One `## Round ` heading per round | `ui_grind.index` counts them |
| pr-grind | `## Re-entry` (the "On-wake branch"), `## Step 8 — Paused stop`, and the headless re-arm: write `next-poll`, end the turn | `REENTRY_PROMPT` (`ui_runner.py`), `LANE_GRIND` (`dispatch_run.py`) |
| peer-review | The `--root <panel id>` round protocol | `ui_panel.py` starts `/ai-workflow:peer-review --root <panel id> <artifact>` |
| any | `aiw ask` for gate questions in a headless run | `HEADLESS_PROMPT` (`ui_runner.py`) |

- The tick always runs the plugin's own `skills/pr-grind/scripts/poll-reviews.sh` (`_POLL_SH`),
  whichever copy of pr-grind runs.
- Relative `../../guides/` and `../../templates/` paths in a copied skill no longer reach the
  plugin: point them at the repo's own copies or an absolute source.

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
| `restart.log`, `restart.exit` | output and exit code of the last Settings → Server **Rebuild and restart** (`make restart`, a detached child; `GET/POST /api/restart`) |
| `afk.json` | the Away mode window and its log |
| `dispatches/` | one `<id>.json` per dispatch (settings, lanes, events) and its `.lock` |
| `ui.json` | push notifications and `public_url` (mode 0600) |
| `config.json` | peer-review overrides from Settings, laid over `run-engine/config.json` |
| `channels.json` | Slack ids and trigger templates for grind and release-pr |

The work's own state is on GitHub and in the repo's `docs/prds/` and `docs/tasks/`.

## Layout

```
skills/       create-prd, create-tasks, refine-issues, implement-issue, verifier-locally,
              pr-review, docs-updater, skill-feedback, sync-from-wasensi, pr-grind,
              peer-review, dump, release-pr, worklog, flow, herdr-dispatch
agents/       away-answerer, peer-reviewer, worklog-runner
guides/       engineering-workflow, code-review, skills
templates/    prd, epic, issue
commands/     code-review (a slash command)
run-engine/   route.py (the aiw CLI) · ui_*.py (the web UI server) · peer_review, threads, ci, ask
              dispatch_run (the lane engine), dispatch_runners (herdr, headless), dispatch_cli
              ui_dist/ (the built UI, committed) · config.json · test_*.py
ui/           the web UI source: React + TypeScript + Vite
site/         the GitHub Pages showcase (Vite + React), deployed by .github/workflows/pages.yml;
              scripts/ re-capture its media from a running `aiw ui` (raw captures stay in site/raw/, ignored)
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
