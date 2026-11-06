# Reference

## Commands

| Command | Does |
|---|---|
| `/ai-workflow:create-prd <requirement>` | interview a requirement into a PRD with its technical design, saved to `docs/prds/<slug>.md`; asking it to update a PRD records later decisions; `approve` files one epic per `## Epics` entry and opens the PRD's pull request (UI prompt conventions; the skill takes them as plain text) |
| `/ai-workflow:create-tasks <prd \| finding>` | split an Approved PRD into one-PR tasks, created as child issues of the epic with blocked-by links; or file one issue for a finding |
| `/ai-workflow:refine-issues <epic or issues>` | write a WHAT, WHY and HOW into each child issue, label it `refined` and move it to Ready on the board once unblocked |
| `/ai-workflow:implement-issue <n \| epic>` | one refined issue (or an epic's next Ready one) to a Ready PR: worktree, local checks, local review, draft PR, CI, review comments; after the merge, close and clean up |
| `/ai-workflow:verifier-locally` | run the checks CI would run and exercise the change against its acceptance criteria |
| `/ai-workflow:pr-review <pr or branch> [--fix]` | review against the issue, the repo's rules and `guides/code-review.md`; report findings and a verdict. `--fix` fixes the review feedback on a PR through to green CI, replies and ready |
| `/ai-workflow:skill-feedback <feedback \| reconcile [owner/name] [--since <date\|PR>] [--prs <n,n>] [--merged-only]>` | turn feedback, or the learning logs of closed PRs, into approved edits to the skills and guides |
| `/ai-workflow:docs-updater` | bring `docs/` in line with the code |
| `/ai-workflow:repo-bootstrap [audit\|decide\|constitution\|guides\|gates\|docs] [issue]` | make a repo ready for agents in phases on one branch and one PR, one phase per run (it prints the next command and a `BOOTSTRAP:` last line): a read-only audit issue, the decisions, a short protected `CLAUDE.md` (`templates/claude-md.md`) with its guards, guides and a tested README, the gates, then `/docs-updater full` |
| `/ai-workflow:faq-updater [full\|--full] [--lang <codes>] [--videos <url>] [questions…]` | write and update the product's user guide and FAQ (`docs/faq.md`) from the code, through a PR |
| `/ai-workflow:sync-from-wasensi` | port Wasensi's skill, guide and template changes into this plugin |
| `/ai-workflow:pr-grind <slack thread url \| PR url> [--channel <id>] [--reviewer <login\|copilot>]` | the reviewer loop on a PR: a Slack reviewer bot, or with `--reviewer` (no Slack) a GitHub reviewer asked with `gh pr edit --add-reviewer`, read through `gh api .../reviews`; reads the reviewers from `aiw grind-reviewers` each round (unless pinned by `--reviewer`); fixes inline, verifies before each push |
| `/ai-workflow:peer-review [--lenses <lens,lens>] [--root <panel_id>]` | a panel of read-only `peer-reviewer` lenses on the session's change (default critical) until every lens approves |
| `/ai-workflow:dump <text>` | file free-form input into the Obsidian vault's Project → Feature structure, after one confirmation |
| `/ai-workflow:close-epic <epic> [--dry-run]` | verify every child issue and PRD requirement shipped, run `/verifier-locally` on the base branch, set the PRD to `Done` and close the epic; lists the gaps and stops otherwise, never closes children |
| `/ai-workflow:revert-pr <pr> [--dry-run]` | revert a merged PR: open a revert PR into its base branch, file the finding through `/create-tasks` and reopen the issue it closed. Never merges |
| `/ai-workflow:release-pr [--dry-run] [head=staging] [base=master]` | open or refresh the `staging` → `master` release PR with a deploy checklist, post the Slack trigger, hand off to `/pr-grind`. Never merges |
| `/ai-workflow:worklog [date]` | today's worklog from GitHub activity and the daily note, written to the Obsidian daily note (runs as the `worklog-runner` agent) |
| `/ai-workflow:herdr-dispatch <epic> [--max N] [--grind off\|simple\|full] [--ci wait\|defer\|ignore] [--auto-merge] [--skip-approval] [--feature-branch <name>] [--base-branch <name>] [--model M] [--effort E]` | run an epic's issues as a dispatch in herdr tabs: preview, confirm, start, then relay what needs you (see **Dispatches**) |

## The `aiw` CLI

```
aiw ui [--port N] [--allow-host HOST]   local web UI to start and track sessions
aiw paths                               resolve every path, create the state dirs
aiw ask                                 a headless session asks the user a question and pauses
aiw ci status                           check state (green, red, pending, conflict when the PR conflicts with its base, or error when gh could not be read) plus the failing job's log
aiw threads list|resolve                PR review threads
aiw grind-mode [--pr <url>]             print the grind mode, deep or simple: the PR's dispatch decides, else
                                        Settings (read by /pr-grind each round)
aiw grind-reviewers --pr <url>          print the PR's resolved path, channel, mentions, logins, unlogged and
                                        skip as JSON (Settings and channels.json; read by /pr-grind each round)
aiw install-skills --harness codex [--remove]
                                        link the plugin skills into Codex's skills folder (~/.agents/skills)
                                        for interactive Codex; --remove deletes the links this command made
aiw dispatch plan|start <epic> [flags]  preview or start a dispatch (flags as herdr-dispatch, including
                                        --feature-branch and --base-branch, plus
                                        --runner herdr|herdr-app|headless and --workspace <herdr workspace id>;
                                        herdr-app opens lanes as tabs of the Herdr desktop app, with
                                        --workspace its app space id from `herdr-app ls`; the web UI still
                                        labels herdr-app dispatches as background sessions);
                                        a herdr dispatch on a Codex account starts `--kind codex` lanes
                                        and needs an account whose command is `codex` (else refused:
                                        "herdr can only start the codex binary; ..."); a herdr-app dispatch
                                        on a Codex account runs the account's own command (any, `cc-codex`
                                        included) with the Codex flags and the inlined skill prompt;
                                        herdr and herdr-app Claude lanes ignore the account; an epic only: picked issues dispatch from the UI
aiw jev ci-hint|finding-hint --file <path>
                                        advisory jev hint for /pr-grind as JSON; reads the text from a file;
                                        always exits 0
aiw dispatch ls|show <id>               list dispatches, or one as JSON (also those of picked issues
                                        started from the UI, listed by title)
aiw dispatch archive [--days N]      move dispatches finished over N days ago (default 30) to dispatches/archive/; prints the ids (the server does this daily)
aiw dispatch doctor [<id>]          why a live dispatch cannot move (skipped blocker, cycle, stale snapshot,
                                        dead server, needs you, held); exits 1 on a problem
aiw dispatch set <id> key=value...      change max, grind, ci, auto_merge, skip_approval, model, effort, account, max_cost while it runs (`max_cost=20` pauses the dispatch once its headless lanes have cost $20; never on a Codex account, whose sessions report no cost; `max_cost=` clears it; `model` is 1–80 letters, digits, `.`, `-`, `_`, `:`, `/`, `[`, `]`, starting with a letter or digit)
                                        (feature_branch and base_branch are fixed at start)
aiw dispatch pause|resume|cancel <id>   the whole dispatch (pause stops new lanes only)
aiw dispatch lane <id> <n> <action>     pause, resume, retry, skip, merge, hold, unhold, or send "<text>"
aiw dispatch watch <id> [--since T]     block until an event needs you; prints it and the next --since (restarts the UI server if its port is closed)
aiw dispatch retry-failed <id>          retry every lane that failed to start, needs you or is held; prints their keys
aiw dispatch end <id> open-pr|qa|grind-pr  an end-of-dispatch action, run by the server
```

**`aiw install-skills --harness codex`** (`run-engine/install_skills.py`) links each plugin skill
folder into `~/.agents/skills/<name>`, creating the folder when missing, so an interactive Codex finds
them. Every link it makes is recorded in `<data_dir>/install_skills.json` (`{"codex": [<link path>, ...]}`).
A rerun repoints a recorded link that points elsewhere, deletes a recorded link whose skill left the plugin,
and leaves `unchanged` the rest; a recorded path that is no longer a symlink, or an existing path it did not
make, is skipped and reported, never touched. `--remove` deletes only its own recorded links. It prints one
line per skill, then counts (`linked`, `repointed`, `removed`, `unchanged`, `skipped`).

## aiw ui

`aiw ui` serves a local web app for starting and tracking headless coding-agent sessions (Claude Code or Codex) and for seeing
what needs you across every watched repo. It is a React + TypeScript app (source in `ui/`) served
from the committed build in `run-engine/ui_dist/`, so using it never needs Node. On first start
after an upgrade it deletes the old run data from the plugin data dir once and logs what it removed.

- Every text it hands to a session (a start, a queued or rate-limited start when it begins, an answer, a typed prompt, a resume) is rewritten by `repo_skills.resolve` against the session's working directory: a plugin skill command becomes `/<name>` when the repo has `.claude/skills/<name>/SKILL.md`, else `/ai-workflow:<name>`. A session's stored `command` is what its latest own start ran; answers and resumes leave it alone. A queued or limited session shows the raw text until it starts. The stored `command` is this short form on both harnesses; a session on a Codex account is sent the skill's text instead, built by `repo_skills.codex_prompt` at every spawn and send (see **Repo copies of skills**).
- It binds to loopback only. `--port` sets the port (default 8420).
- `--allow-host HOST` is repeatable and matches exactly: use `name:port`, or the bare name for the default 443 serve.
  Every non-loopback host, including these, needs the node owner's `Tailscale-User-Login` header, so it only works
  behind `tailscale serve` on the owner's node; a reverse proxy that does not add it is refused. `aiw ui` refuses to
  start with `--allow-host` when the owner login cannot be read from `tailscale status`.
- To reach it over a tailnet: `tailscale serve --bg 8420`, then
  `aiw ui --allow-host <machine>.<tailnet>.ts.net`. It installs as a PWA.
- `/` serves the app (`index.html`, never cached); `/assets/*` are hashed and cached for a year;
  `/sw.js`, `/manifest.webmanifest` and `/icons/*` are served from the root.

**Routes** (hash routes, each with an optional `?repo=owner/name` that a shared link keeps):
`#/inbox` (default, and `#/`), `#/features`, `#/features/<slug>[/<tab>]`, `#/changes` (Small changes;
`#/issues` and the old `#/features?tab=changes` redirect here), `#/new[?text=<idea>&route=feature|small]` (opens the create box over Features),
`#/dispatches[?new=<owner/repo#n>&only=<owner/repo>&show=needs|live|finished]` (`new` opens Run an epic on that epic, `only` narrows the list to one repo, `show` picks a filter tab; no `show` is All),
`#/dispatches/<id>[?lane=<owner/repo#n>]`, `#/activity`, `#/sessions/<id>`, `#/settings[/<section>]`.
Anything else is a not-found page. **Shortcuts:** `N` the create box, `G` then `I/F/D/A/S` to go to a page, `G` then `R` to open the repo switcher (the compact one on narrow screens), `[` and `]` switch to the previous and next page tab (the Feature page, stopping at the ends), `?` lists the keys that work on the current page, `Esc` closes the top panel. Single keys are ignored while typing in a field or when ⌘/Ctrl/Alt is held. On every list (Inbox, Features and the Feature Issues tab, Dispatches, a dispatch's lanes, Activity), `J`/`K` or the arrow keys select a row (the open PR, issue or lane panel follows), `Enter` opens it (on the Inbox: expands a question or presses the item's primary button), and `Esc` closes the panel with the row still selected. The action keys, shown as a badge on each button, act on the selected row, the open panel or the page, and press the same button a click does; the panel's keys win over the row's. The map: `M` Review and merge (in the confirm: `Enter` merges, `Esc` cancels), `S` Skip CI and continue, `R` Retry, Resume or Rerun, `A` Answer, `P` Approve PRD, `E` Refine, `X` Stop or Cancel, `O` Open PR, `T` Continue in terminal, `C` focuses the message or comment box. In a question round: `1`–`9` pick an option (toggle in multi-select), `0`/`O` picks Something else, `Tab` goes to the next question (multi-select questions also show a "Select all" link and a "None of these" checkbox, reached by `Tab` and `Space` with no key of their own; "None of these" sends `{"none": true}`), ⌘↵ sends a complete round, and `Esc` collapses it with focus back on the row. On a session page, `R`, `T`, `X` and `C` work as above. Below 760 px the badges are hidden, though the keys still work with a hardware keyboard. The palette
(⌘K / Ctrl+K) finds pages, the create box, every Start command, features, issues, PRs, sessions, switches repo and
turns Away mode on or off. Its groups run Open, Go to, then **Actions here** (nothing is pre-selected, so Enter does nothing until you move), and so on. **Actions here** lists every enabled action registered on the page, the open panel and the selected row (and the items of mounted menus, via `Menu`'s `paletteLabel`), labelled as the button is, with its key; choosing one does what a click does. From any page it also lists **Answer the first waiting question** while a session is waiting on you, which opens the oldest such session.

**Inbox.** Everything that needs you, across repos, grouped Blocking everything, Answer Claude, Decide,
Fix, Set up and Waiting (nothing to do), each item its own card; the rail's Inbox count, the top bar's amber "n need you" button and the tab title count all but Waiting. Items: GitHub CLI
signed out; a session asking a question (answered inline); a peer review at its round cap or with every
lens approving (Approve PRD anyway, Run 2 more rounds); reviewers' comments or approvals on a shared PRD (Open PRD; one item per share, cleared when the share is marked seen); a PR ready to merge (Review and merge, see
**Merge rule**); a PR with merge conflicts (Resolve conflicts); a paused grind (Skip CI and continue, Stop grind); a failed session (Retry, Continue in
terminal); a bootstrap run waiting after the audit (Continue bootstrap, Stop) or stopped at a phase (Retry phase, Stop, Open session), each with its phase strip (the six phases, the current one marked, a link to each phase's session); a merged issue whose worktree has unsaved work (Review and clean up); a `local/` repo with no
GitHub remote (Publish to GitHub); a usage-limited session (Resume on another account); a queued session
(Start now, Cancel); an issue in a dispatch that needs you, is held or hit a usage limit (Open, Retry), its
PR waiting for your merge (Merge), and a finished dispatch (What next, Dismiss). A bootstrap run waiting after its audit (**decide**: Continue bootstrap, Stop) or stopped at a phase
(**fix**: Retry phase, Stop; carries the session's error); the failed phase session of a run makes no failed-session row. An issue a running dispatch
owns shows once, as its dispatch row: the generic PR-ready, conflict, paused-grind and failed-session rows
are dropped for it. An item disappears within a poll after its condition clears. Inside each group items sort
by `urgency` (1–5, highest first), then newest first: a background scorer asks `jev` every 30 s about question,
paused-grind, failed-session and PR-conflict items (at most 3 calls a pass, none once 400 of the hour's 500 are
spent) and the Inbox only reads the cached answers. An unscored item, a dispatch row, or any item with Use jev
off has `urgency: null` and keeps time order.
`GET /api/inbox[?repo=]` builds it on the server from sessions, panels, grind state, cleanup flags, the
repo registry and the board polls; a repo whose board data is stale is listed in `stale` and contributes
session items only. While an item is open (a question expanded or the side panel showing), polls do not reorder rows; the new order applies once nothing is open or on the next visit.

**Create box.** One dialog, "What should change?", for a feature or a small change. The New button, `N`, the palette and the
prompts on Features and Small changes all open it (Small changes opens it on Small change). Describe the work; 600 ms after typing
stops it asks `POST /api/route {text}` for a route and says why it picked it, and a click on **Feature** or **Small change** overrides that
until **Use Auto's pick**. The repo picker defaults to the repo it was opened with. With more than one account, **Run on** picks the account (default: the Settings default) and pins it: later sessions on the PRD that session writes, its epic, its issues or their PRs, or the issue a small change files, run on that account unless one is picked for them, and a dispatch of the epic opens on it. `run-engine/ui_origin.py` reads what the session made from its stream, and an account removed from Settings falls back to the default. **Feature** starts `/create-prd` (on `opus` at `medium`) with any picked PRD review lenses and opens
the session. **Small change** (with an optional priority) starts one headless `/create-tasks` session that files the issue with no
PRD and refines it in the same session, and the page stays. ⌘↵ submits, Cancel keeps the text until something is created, and **Run a command instead** opens Start. For the route,
the server runs `jev choice` through `run-engine/jev.py` (pinned to `jev-1.14.0`) and answers `{route: feature|small_change|null,
confidence, why}`. A null route (jev missing, switched off in Settings with `why: "jev is off"`, failing, unsure, or under 0.4) leaves the choice to you. `jev` is optional.
`POST /api/duplicate {repo, text}` (400 for an unregistered repo or blank text) asks `jev` which of the repo's newest 100
open issues (from the board poll, no GitHub call) or its PRDs the text already covers, with "none of these" as an option (at most 254
options, oldest PRDs dropped first). Text under 20 characters runs no check. A pick at 0.6 or more answers
`{match: {kind: issue|prd, title, url, n|path}, confidence, why}` with a server-built url (a GitHub issue, or the Feature page `#/features/<slug>?repo=`);
otherwise `match` is null and `why` says why (jev off or missing, issues not loaded yet, no likely duplicate, hourly limit).
The create box calls it 800 ms after typing stops (repo chosen, 20+ characters) and shows "Looks like #n <title>" below the route line, linked in a new tab; it hides on any edit, never blocks either start button, and shows nothing for a null match or a failed check.

**Features.** One strip per feature in progress, in bays by who has the next move: **Stopped on you** (a dispatch waits on you; the strip
sits out of line in amber), **Waiting for your go** and **Running on their own**. A strip shows the title, repo, epic, running dispatch with time and cost,
the stage, merged of total with a bar of the issues by state, the next step, a **Merge #n** button for each PR ready to merge and one next-step button.
Clicking a strip or `Enter` opens the feature in the detail panel: its stage, Next step box and issues grouped by state (each opens its issue panel); a modified click on the title, or **Open the feature page**, goes to the full page.
Below the bays: the create prompt, a note for a repo still loading or stale (never shown as empty), a line of quiet repos (a click filters to that repo) and a collapsed list of shipped features.
The page opens on all repos; the repo dropdown in the page head (`?only=<owner/repo>`, independent of the repo switcher) narrows it to one repo. The head also counts what waits in the Inbox.
A PRD whose header says `**Status:** Done` counts as Shipped.

**Small changes** (`#/changes`, its own top-bar link) opens on **All repos**: the grid totals the open
small changes of every watched repo, and Ready to run, Needs refining first and the issue list are grouped
by repo (each with its own repo's Refine lock and pick bar; a loading or stale repo shows a note, never as
empty; Ready to run has pick checkboxes and **Run N as a dispatch**, but picks stay within one repo: the first pick disables the other repos' checkboxes, with a note, until the picks are cleared, and the dispatch dialog opens on the picked repo, not the switcher's). The repo dropdown in the page head (`?only=<owner/repo>`, independent of
the switcher) narrows it to the single-repo page described next, which holds the open issues of one repo that belong to
no feature (no epic, or an epic with no PRD here): **Where they stand**, a priority by state grid
(Needs refining, Ready, In flight) whose cells filter the list; **Ready to run**, the refined,
unblocked issues no dispatch owns, to pick and **Run N as a dispatch**; **Needs refining first**, cards
with **Refine**; then every issue in the same table as a feature's Issues tab. While a small-change
session lives it shows as a pending row (Queued, Creating… or Needs you, with Watch or Answer) and
Refine is locked on unrefined issues. The table's pick bar: tick unrefined, ready or blocked rows a
dispatch does not own, then **Refine N** (one `/refine-issues` session on the picked unrefined ones),
**Run N** (Run small changes on the picked refined ones) or **Clear**.

A feature page opens on one strip (the title, epic and PRD path, stage ticks, `merged/total` with the issue bar, and
the **Next step** buttons with the live dispatch link or **Run epic** and the More menu), with the next step's title and hint
on one line under it (naming each lane that waits, with the strip marked, when its dispatch needs you). Below it, a **Build map** (one
tile per issue in number order, a state bar on each and a legend counting each state; a tile opens the issue, and one a
dispatch stopped on says **Needs you**), the running dispatch (time, cost, tokens, recent
events), the PRD's sections, and tabs **Issues**, **PRD**, **Peer review** and **Sessions**. Issues: a table by
status with signals (priority, PR, CI, review, grind, live session, failed last run, cleanup), one
action per row (Refine, Start, Retry, Answer, Merge, Grind, Skip CI, Clean up; an issue a dispatch owns
shows its dispatch stage, what it is doing, and **In dispatch** instead), **Run epic** (opens Run an epic
on the feature's epic; also in the strip and the Next step box, which become **Open dispatch** with
its progress while one runs), **Add task** (`/create-tasks` with the text as a finding) and refine-picked.
PRD: rendered, **Edit** (**Save and commit** commits only that file on the checkout's current branch, not
pushed; refused if the file changed on disk since it opened) or **Ask Claude** (`/create-prd <path>
--update <request>`). The More menu has **Close epic** (closes the epic and every open child as
completed, `POST /api/epics/close`). `GET /api/planning?repo=`. Without `repo` it returns `{repos, stale}`: one `?repo=` body per watched repo, sorted by slug, from memory (a repo whose build fails is a meta-only entry); `stale` lists watched repos with a missing or stale snapshot; `?refresh=1` polls them all off the request thread.

Issues start one at a time from their row (**Start**); a whole epic runs as a dispatch. `GET
/api/delivery` (same no-`repo` form; the issue data behind Features and Small changes), `POST /api/start` (headless only; 409
for a live session, an open PR, a blocked issue or an issue a running dispatch owns), `POST
/api/cleanup`.

**Issue data.** A PR belongs to an issue when GitHub links it, when its body says Closes, Fixes or
Resolves #n, or when its branch starts `issue-<n>-` (GitHub links closing keywords only for PRs into
the default branch, so a staging-based repo needs the last two). Each poll of a watched repo is a
1-point GraphQL probe (newest issue and PR update, open PRs' CI, conflict and review state); the full
query (about 6 points) runs only when the probe's answer changed, on **Refresh** or after a write, and
at least every 10 minutes. Results are kept in memory. A repo is watched while it has a live session or
was opened in the last 7 days. It polls every 60 s (15 s while a PR's CI is pending) while it has a live
session or the UI asked about it in the last 2 minutes (the global Inbox and the boards without `repo` count for every watched
repo), else every 10 minutes. Every response reports the token's GraphQL budget, which the agents share:
under 1000 points left, every repo polls every 10 minutes until the reset. A rate limit pauses fetching
until that reset (10 minutes when the budget was not low) and the boards show the last data as stale
with the reason and a **Refresh** (`?refresh=1` on the board GET fetches now). After each fresh poll the server runs merge cleanup and grind autostart (a PR that
turned ready whose issue has grinding on, unless a dispatch lane owns it; a PR with no issue follows the
repo's auto-grind). Nothing runs on stale data, and outside a dispatch with auto-merge on nothing merges
a PR without a click.

**Merge rule.** Each issue has a **Grinding** switch (in its panel); an untouched issue follows the
repo's auto-grind. A PR shows Merge (Inbox, Features list, feature Issues tab, Small changes tab) when it is not a
draft, does not conflict with its base (GitHub's `mergeable` is not `CONFLICTING`), CI is green and the PR is approved (GitHub's review decision, or an approving review on a repo with no review rule; never with a changes-requested review; no unresolved, non-outdated review threads; approval is skipped when the repo's owner is your `gh`
login), and with grinding on its grind is also done (stopped from the UI counts). Turning grinding
on starts a grind at once when the PR is already ready and has none; turning it off stops a running or
paused grind (the PR stays open). Delivery cards carry `grind_on` and `mergeable`. The switches are in
`issue_grind.json`. `POST /api/grind/issue` (`{repo, issue, on}`).

**Links.** A plain click on any GitHub issue or PR link in the app (transcripts, PRD, bodies, comments, dispatch) opens that item's side panel; Cmd/Ctrl/Shift/Alt or middle click, the panels' "on GitHub" buttons (`data-ext`) and other links still open GitHub. `POST /api/start` takes an optional `issue` that links the session to it; a single-issue `refine-issues` links itself, and a feature's create-tasks and refine steps pass the epic.

**Long pages.** A page that scrolls shows jump-to-top and jump-to-bottom buttons at the bottom-right of the page column (`shell/ScrollJump.tsx`); they appear only after the page is scrolled a screen down and each shows only when it has somewhere to go, and the jump is instant under reduced motion.

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
`POST /api/issues/<o>/<r>/<n>/comment|state`, `POST /api/pulls/<o>/<r>/<n>/comment|merge|state` (`state`: `{state: open|closed}` runs `gh pr reopen|close`, branch kept; 502 with GitHub's message when refused),
`POST /api/grind/skip-ci|stop` (`{repo, pr}`; 409 when there is nothing to skip or stop),
`GET /api/prd?repo=&path=` (returns `sha`), `POST /api/prd` (takes `base_sha`; 409 when it changed).

**Share a PRD.** The PRD tab's **Share** button publishes one PRD for human review at
`https://<node>.<tailnet>.ts.net:<share port>/s/<token>` (the token has at least 128 random bits).
Only the owner can start it, only for a Draft or In review PRD, and a PRD has one live share. The
share ends when the PRD becomes Approved or any other status, when the author presses **Stop**, or
when the file is gone or no longer a regular file under `docs/prds/`; it is checked on every share
request and once a minute. The author can also pick an expiry (Never, 1, 7 or 30 days) when sharing; at that time the share ends by itself with `end_reason: expired`, like Stop. Sharing again takes a new expiry. An ended share's link returns 404 at once, its
threads stay in the UI, and sharing again issues a new token, keeps the threads and clears the
approvals. The PRD text is public as written, header and paths included, so Share asks to confirm
that on every press. A reviewer is anyone holding the link, with a typed display name and no account;
names and comments are visible to everyone who holds the same link. A reviewer's **Approve** is a
signal shown to the author and never sets the PRD to Approved. Reviewer text reaches a session only
through the author's **Send open comments**. While any share is live the top bar shows a **Public (n)**
badge listing them. The share runs on a separate read-only listener that `aiw ui` starts while a share
is live, behind a tailscale funnel (port 8443, or 10000 when the UI's serve uses 8443, never the UI's
port). Shares persist; after a clean exit the listener and funnel go down and come back on the same
link at the next start. After an unclean exit a leftover handler of ours on the recorded port is
reclaimed; a foreign handler there shows the share as "not reachable" and no new port is chosen.

Limits per share: names 1 to 60 characters and comments 1 to 2,000 (Unicode code points, trimmed),
500 reviewer comments, 100 approvals, 20 reviewer writes a minute, request bodies of 16 KB.

Owner routes (UI port; errors as `{error}`):

| Route | Does | Status |
|---|---|---|
| `GET /api/shares` | `[{id, repo, path, title, state, url, comments, unread, reachable, end_reason, expires_at}]` | 200 |
| `POST /api/shares` | `{repo, path, confirm: true, expires_in_days?}` starts a share (`expires_in_days` an integer 1 to 90, else none); an existing live share comes back without confirm | 201; 200 existing; 400 no `confirm`, bad path or repo or `expires_in_days`; 409 PRD not Draft or In review, or funnel port taken; 503 tailscale missing or stopped, or funnel not permitted (tailscale's message) |
| `GET /api/shares/<id>` | the share with `threads`, `approvals` and `last_opened_at` (ISO or null; set by a reviewer page load, at most once a minute) | 200; 404 |
| `DELETE /api/shares/<id>` | Stop (`end_reason: stopped`) | 200; 404 |
| `DELETE /api/shares/<id>/threads/<tid>`, `.../comments/<cid>`, `.../approvals/<aid>` | delete one | 204; 404 |
| `DELETE /api/shares/<id>/record` | remove an ended share with its threads and approvals | 204; 404; 409 still live |
| `POST /api/shares/<id>/threads/<tid>/comments` | `{body}` author reply | 201; 400; 404 |
| `PATCH /api/shares/<id>/threads/<tid>` | `{resolved: bool}` | 200; 400; 404 |
| `POST /api/shares/<id>/send` | `{confirm: true}`; without it, the prompt preview | 201 `{session_id, threads, remaining, dropped}`; 409 nothing unsent; 502 session failed to start |
| `POST /api/shares/<id>/seen` | marks the share seen (Inbox) | 204 |

Public routes (share listener only; any other path, unknown or ended token, foreign `Host`, or a
non-GET without `Content-Type: application/json` and an `Origin` equal to the share host gets the same
404):

| Route | Does | Status |
|---|---|---|
| `GET /s/<token>`, `/s/<token>/assets/<file>` | share page and its bundle files | 200; 404 |
| `GET /s/<token>/api/prd` | `{title, status, text, updated_at}` | 200; 404 |
| `GET /s/<token>/api/threads` | threads with their comments | 200; 404 |
| `POST /s/<token>/api/threads` | `{name, body, anchor:{exact, prefix, suffix}}` | 201; 400; 409 share full; 413; 429 |
| `POST /s/<token>/api/threads/<tid>/comments` | `{name, body}` | 201; 400; 404; 409; 413; 429 |
| `GET /s/<token>/api/approvals` | `[{name, at}]` | 200; 404 |
| `POST /s/<token>/api/approvals` | `{name}`; the withdraw `key` is returned only on the first approval of a name | 201; 200 name already recorded; 400; 409 100 approvals; 413; 429 |
| `DELETE /s/<token>/api/approvals` | `{name, key}` withdraws | 204; 400; 404 unknown name or wrong key |

Responses carry `Referrer-Policy: no-referrer`, `X-Robots-Tag: noindex`, a strict
`Content-Security-Policy` and `Cache-Control: no-store`.

**Dispatches.** `#/dispatches` is one table of every dispatch, live and past (State, Dispatch, Issues, Took, Spent): Needs you, Running, Paused, then Finished and Cancelled together, newest first in each group. A running or paused dispatch with an issue that needs you shows Needs you and the first such issue. Tabs (All, Needs you, Live, Finished) and the Features repo control narrow the rows, and the repo control narrows the tab counts too; a dispatch needing you counts under both Needs you and Live. A row opens the dispatch page, which holds every action.
**Run an epic** takes an epic (typed, or picked from a select of every open epic of the repo, newest first, read from the
delivery lanes; the select and the text box stay in step, and the select shows "Loading epics…", "No open epics in <repo>",
"Pick a repo first" or a "Could not load epics" hint when it has nothing to pick; a hint says when only the newest 500 open issues were read, so an older epic is typed), grind mode (Off, Simple, Full), auto-merge, skip approval (merge without an approving review; CI, the grind, conflicts, changes requested and open threads still gate), lanes at once (1–10), a base branch (a searchable list of the repo's branches, also in Run small changes), a feature branch, model and
effort, then **Preview** shows the waves and warnings (unrefined issues, cycles, missing checkouts,
repos without a Slack channel, open blockers outside the epic, issues jev reads as underspecified, readiness unavailable) before **Start**. With Use jev on, Preview (and `aiw dispatch plan`) scores each refined lane's body 1–5 for up to 8 s: plan lanes carry `readiness` (int or null), a score of 2 or less warns and the lane still runs, and bodies are fetched only for this read and never returned. Lanes started here run
as headless sessions (the same dialog, given picked issues, becomes **Run small changes**: chips instead of the epic field, no feature branch, `issues` in the request; lists show it by its title, "Small changes: #412, #415", and its repo); `herdr-dispatch` starts herdr ones, and both show here. `aiw dispatch plan|start` and `herdr-dispatch` take an epic only. A dispatch page has the
live settings (including the **Account** lane sessions run on, headless lanes only), **Pause**/**Resume**/**Cancel** (Pause asks **After the running issues**: they carry on and no new one starts, or **Now**, `{"state": "paused", "now": true}`: every running lane is paused and its session stopped, and Resume starts each in its stage in a fresh session; a lane you paused yourself stays paused), one progress tick per issue with done, building, waiting, time and spend, a **Needs
you** strip (each issue waiting on you with its one action: Merge, Answer, Retry), then the issues in three lists (issue
titles lose the epic-name prefix; `J`/`K` walk them in this order): **Building now** (a card per lane at work with its
Build, Grind, Merge, Wrap up steps, time and cost), **Up next** (waiting lanes, ready ones first, each with what it waits
for) and **Done** (latest first, with PR, time and cost), an issue panel (what
is happening and its main action, a step bar, the question form when its session asks one, a message box,
its transcript or herdr pane text, and Pause, Merge now, Hold the merge, Retry, Skip in a menu) and the
activity feed in plain sentences beside the lists (the issue panel takes its place while open). **Retry** on red CI asks the issue's session to fix CI. When every lane is done it offers **Open PR from
<branch>** (into `base_branch` when set, else the default branch), **Run QA** and **Grind the final PR**; none runs by itself, and a dispatch of picked issues offers none of them.
The server ticks every running dispatch every 30 s from the board poll, the grind state files and each
lane's session; grind rounds a lane owns are typed into the lane (`dispatch-due:` in the grind state)
instead of starting a separate session, and the epic is re-read every 5 minutes so new children join; a finished (`done`) dispatch that gains one goes to `paused` until the new issues are refined and the user presses **Resume** (a dispatch of picked issues re-reads only its listed issues; none joins).
`GET /api/bootstraps[?repo=]` (`{runs: [record]}`, newest first; 400 for an unregistered repo), `POST /api/bootstraps/<id>/continue` (only from `waiting`: starts the decide phase), `/retry` (only from `stopped`: a new session for the failed phase, same account, model and effort) and `/stop` (from `waiting`, `stopped` or `running`: the run becomes `ended`, a running run's live session is stopped); each returns the run record; 409 for a wrong state, 404 for an unknown id, and a failed start leaves the run as it was. Every session row in `GET /api/sessions[/<id>]` carries `bootstrap`: the run it belongs to, or null.
`GET /api/dispatches`, `GET /api/dispatches/<id>` (with events; `issues` is the list or null), `GET /api/dispatches/<id>/lane?key=`,
`POST /api/dispatches` (`{epic, settings}` or `{issues: ["owner/repo#n", ...], settings}`, never both; 1 to 30 issues in one repo, no `feature_branch` (`settings.base_branch` is allowed); 400 for both or neither, a bad ref, more than 30, two repos, a feature branch or no open issue; 409 when a picked issue is a lane of a dispatch not done or cancelled), `POST /api/dispatches/plan` (the same body), `POST
/api/dispatches/<id>/settings|state|lane|retry-failed|end|seen`. `settings.base_branch` (a branch name or null, same name rule as `feature_branch`, must differ from it) is fixed at start: a settings edit that contains it is 400 `base_branch is fixed at start`. Preview warns `<repo>: base branch <b> does not exist` per lane repo, Start refuses with that message (400, CLI exit non-zero) before creating anything, and a missing `feature_branch` is cut from the head of `base_branch` when set.
`GET /api/github/branches?repo=<owner/name>` lists the repo's branches for the Base branch picker: 200 `{branches, default}` (the default first, the rest sorted), 400 `repo must be owner/name`, 502 with `gh`'s error.

**Start** (⌘K, or **Run a command instead** in the create box), titled "What should we start?". Commands grouped Plan, Build, Review, Ship, Capture and
Maintain as six cards across the top, each command a pill (its description shows above the options below); the last one is remembered. Maintain has **Update FAQ**, whose optional input takes new questions, one per line, and the options `full`, `--lang <codes>` and `--videos <url>`, and **Bootstrap repo**, whose optional input takes a phase and the bootstrap issue number. Pick **Where** (a registered repo,
or **No repo yet** for `create-prd`, `dump`, `day` and the custom prompt, which run in the notes vault
with a **Vault folder**), the input, and **Run on** an account of either harness (a limited account says the run will
queue; switching it keeps a model and effort the new harness offers and resets the rest to Default). `implement-issue`, `pr-review` and `pr-grind` list the repo's open issues or PRs under the
input (`GET /api/repos/<owner>/<repo>/open?kind=issue|pr`, one `gh` page of 100); a pasted issue or PR URL
of a registered repo switches the repo. `worklog` offers Today, Yesterday, A day or A range (at most 31
days, one session per day, 3 running at once, the rest `queued`). **Custom** takes any prompt and runs
with permissions skipped. Starting anything opens its session page; a duplicate start (409) offers to
open the running session.

**Activity and sessions.** Live sessions as a departures board (one dark row each), history as a table with search, a result filter
and cost today; **Clean up** lists finished sessions by repo before removing them. A session page
has banners for waiting (inline answer), limited (reset time, **Resume on another account**, **Don't
auto-resume**), failed (**Retry**, **Continue in terminal**) and queued (**Start now**), the run's phase strip when the session is a bootstrap phase (its own entry marked "this session", the others linked), the transcript, a
composer (a prompt queues while a turn runs), and a facts box with the account, its harness (Claude Code or Codex; a record with no `harness` reads as Claude Code), cost, tokens (`$0.44 · 703k tok`; the latest run's own usage on both harnesses: Codex reports usage over the whole thread, so the record keeps `tokens_total` and each run that continues the thread records the rise over its `tokens_base`), model, effort and the run's `run_note`; a fact with no value (no cost, tokens, model or effort, or no repo) is left out, not shown as "—" or Default. **Continue in terminal** (header, failed banner, `T`) shows only when the session JSON carries a `resume_command` and copies exactly that string; the UI never builds a resume command itself.
Sessions auto-resume after a rate limit, and the limit timer releases queued ones after a restart. A session resumes only on an account of its own harness (another is a 409); a Claude session can move to another Claude account (its transcript is copied), a Codex one auto-resumes only on its own account and, with no reset time, after a doubling wait (1 min to 60 min, `limit_backoff`). A Codex run counts as limited when its `turn.failed` or `error` message matches `usage limit|limit reached|rate.?limit|hit your limit`, and it carries no reset time: build gate G1 (Codex's real limit text and reset format) is not recorded yet, so this fallback is what ships. A Codex session whose account is gone or switched harness stays limited with auto-resume off and a note; a manual resume of one whose account was removed uses the Settings default only when that is a Codex account.
Actions: **Pause** on a starting, running, waiting or limited session asks **After this run** (`POST /api/sessions/<id>/hold`: the run finishes, then nothing continues the session on its own until **Resume** on the held banner, `POST /api/sessions/<id>/release`; a queued prompt stays unsent, Away mode neither answers nor retries it, a limited session does not auto-resume, a dispatch tick stores its prompt as the queued prompt and the lane waits, a peer-review panel waits in its phase, and you can still answer it by hand) or **Now** (the same as Stop). **Stop** (`POST /api/sessions/<id>/stop`, after a confirm), **Resume**, **Rerun** (replays the
recorded start request, same repo and account; `POST /api/sessions/<id>/rerun`), **Dismiss** on a failed session's Inbox item (`POST /api/sessions/<id>/dismiss`: sets `dismissed`, 409 unless failed; the session stays on Activity), and **Start now**
(`POST /api/sessions/<id>/start-now`: starts a batch-queued session at once, past the batch cap; 409 when
the session is not queued or is waiting on an account limit, which starts by itself at the reset).

**Away mode.** A timed run by the server, so it works with no browser open (30 min to 4 h or an end
time; **+30 min** and **I'm back** end or extend it). Each tick it answers every `aiw ask` round: at once
when all its questions carry a "(Recommended)" option (planning interviews included), otherwise through a
read-only **answerer** (`agents/away-answerer.md`, Opus, medium effort, started without the permission bypass
and with `--allowedTools` set to the agent's `tools:` list). A valid reply resumes the session and is logged
`by: opus`; a hold, or a second failed answerer (failed to start, failed, rate limited, invalid reply, over 10 min), is logged
`kind: held` and the round waits for you; so is a round whose resume fails after Away claimed it (restored as pending and held, reason `resume failed: …`). Your own answer, or the window ending, stops the answerer with no
log row. Before a fully recommended round is auto-picked, a small worker (off the tick, two at a time, each round once) asks jev "is any recommended option irreversible or outward-facing?" and stores `risk: {p}` on the round; the tick waits for it. At `p >= 0.5`, or when jev is on but the check fails (stored as `{p: null, unknown: true}`, also when the worker raises), the round goes to the Opus answerer instead (not told it was flagged) and its log entry carries `risk: <p>`; under 0.5, or with Use jev off or jev missing (`{p: null}`, stored at once), it is auto-picked as before. Non-recommended rounds get no check. Before anything answers a round (recommended or not), a round whose option labels or descriptions contain `push`, `merge`, `delete`, `force`, `publish`, `deploy`, `release`, `drop`, `rm -rf` or `post a comment` (case-insensitive, `HOLD_WORDS`) is logged `held` and waits for you. No answerer starts once the round's answerers cost `ROUND_COST_CAP` ($2.00) or the answerers of the window cost `WINDOW_COST_CAP` ($10.00); the round is held with the cap named. A running answerer is never cut short, the caps act between answerers; the caps and words are constants in `ui_afk.py`. It also sends "Skip CI for now" to a grind paused on CI (at most
once per PR per window), and retries failed sessions, and held or stopped dispatch issues, on a 2m/10m/30m/1h backoff (a
dispatch issue asking a question gets the recommended answer like any session). When the window ends
one push sums it up and the Inbox shows a "While you were away" summary until dismissed: one row per answered or held round (time, session, picker chip Recommended/Opus/Held, each question and pick, Opus's reasons, cost and answerer transcript link, a risk line, "Risk check: sent to Opus (p=…)", on rounds the risk check sent to Opus, a checkbox on answers not yet changed). A **Held only** toggle (shown when a round was held) lists just the held rows; **Change N selected** beside Dismiss opens a dialog with the question form for each ticked round, prefilled with the logged picks; Submit posts `POST /api/afk/change` and one toast reports each session as sent, queued or the refusal; sent and queued rows then show **Changed**; retry and older entries stay one-liners. Each answer entry carries `id` (`<session id>:<round id>`), `by` (`recommended` or `opus`), `questions` (the round as the session holds it, plus `picked` and `why`), `answerer`, `cost` and `changed`, besides the `question`/`picked` summary strings. State is
`afk.json`. `POST /api/afk` (start), `POST /api/afk/stop|dismiss`.
`POST /api/afk/change` sends changed answers back: body `{"changes": [{"id": "<sid>:<round>", "answers": {"0": {"labels": [...]} | {"other": "text"} | {"none": true}, ...}}]}` (1 to 50 answer entries of the undismissed summary that are not `changed`; answers validated like a human answer; an entry with no changed question is refused). Each session gets one turn (old and new answer of each changed question, then "Redo whatever depended on the old answers") through `send_prompt` with a 60,000-character limit. 200 `{"results": [{"sid", "ids", "state": "sent"|"queued"} | {"sid", "ids", "error"}]}`: a session waiting on a question, with a queued prompt, blocked by another live session for its issue, or gone is refused alone and its entries stay changeable; the others are sent and set `changed`. 400 for a malformed body or failed validation (nothing sent), 409 with no undismissed summary.

**Settings** (`#/settings/repos|channels|reviewers|accounts|notifications|review|vault|server`). **Repositories**: the global
**Grinding** mode, Deep (default: a grind runs until the reviewer has no blocker or should-fix left) or
Simple (a grind stops, fixing nothing more, at the round where the PR is approved: the reviewer's
review is an approval or GitHub's reviewDecision is approved). `/pr-grind` reads it every round, so a
change reaches running grinds too (`grind_mode` in `ui_settings.json`). The last-used run model
(`opus`, `sonnet`, `haiku`) and effort (`low` to `max`) are `run_model` / `run_effort` there (null: Claude's
default); `POST /api/sessions` and `POST /api/start` take optional `model` / `effort`, added as `--model` /
`--effort` on every spawn of that session and replayed by Rerun; only a settings save changes the saved pair. On a Codex account they accept any non-empty value (`ui_settings.check_run(model, effort, cmd)`; Claude accounts and the saved pair keep Claude's lists and 400s) and become `--model=<m>` (only a model saved on the account) and `-c model_reasoning_effort=<e>` (`low` to `xhigh`); `default` adds nothing, any other value adds no flag and the session records `run_note` ("`` `<value>` `` is not a Codex model; ran on Codex's default", or "... not a Codex effort ...", the value cut to 80 characters, two notes joined with `; `). A direct model or effort (lens, Away, dispatch) wins over the pick and is recorded as `direct_model` / `direct_effort`, so every Codex resume re-applies it (`harness_codex.model_flags`, also for the herdr Codex lane). The Start and dispatch pickers list the selected account's harness's choices (`harnesses` in `GET /api/settings`; none: Claude's): a Codex account offers Default plus its saved `models` and efforts `low` to `xhigh`, a pick on it is never saved to the pair, changing the account resets a pick the new harness does not offer to Default, and dispatch settings note "Cost cap does not apply on Codex accounts". The feature flow's PRD, tasks and refine starts always send `opus` / `medium` (`PLAN_RUN`) and never touch the saved pair. Then one table of
the registered checkouts (`checkouts.json`) with GitHub status or **Publish**, auto-grind (default off),
the Slack review channel grind posts to (a select over the saved **Slack channels** plus None, saved on change; a stored value that is not a channel id, `channel_invalid` in the GET, stays shown as a disabled option with a red **invalid** chip, and a save of the row keeps it until another channel is picked) and its **Reviewers** (a cell showing **Default (names)**, the active set, muted, or the repo's override as chips marked "override"; a button that opens a popover with a checkbox per saved reviewer and **Use default**: a tick saves `reviewers` as the new id list, the first tick on a repo without an override starts from the active set, **Use default** saves `null`, every control is disabled until its save resolves and a failed save reverts; an entry the repo's `path` can't use is dimmed with "not used: no Slack id" or "not used: no GitHub login", and a Slack-path entry with no login reads "login learned from its first review"; with no saved reviewers the cell links to Settings → Reviewers, and with no active reviewer it reads "Default (none, mentions <bot_label>)" on a Slack-path repo or "Default (none, grinding skips)" on a GitHub-path one) (`repos[owner/repo]` in `ui_settings.json`). Grind start (auto-grind, the per-issue switch, the board's
pr-grind start, dispatch lanes) and the dispatch preview ask the resolver (`aiw grind-reviewers`): a UI-started
grind passes `--channel <id>` when the repo picks one and never `--reviewer`, and a repo the resolver skips
starts no grind (auto-grind logs it, the switch and the board start answer 400 with the skip text, the preview
warns and its lanes skip grinding) and **Remove** in the row's ··· menu (its clone is untouched), plus
scan folders, **Find repos** and **Check remotes** (`gh repo view` on every repo, failures first).
**Slack channels**: a table of the saved channels (name, editable; id, read-only; **Delete**) and an Add row. Ids must match `^[CGD][A-Z0-9]{8,12}$`, names are 1 to 60 characters, ids are unique and the list holds at most 50; this is checked inline before saving. Add, rename (on blur or Enter) and delete each send the whole list (`PUT /api/settings {slack_channels}`); a server `400`, such as deleting a channel a repo picks, is toasted and the list reverts.
**Reviewers**: a table of the saved grind reviewers (name, editable; Slack id and GitHub login, read-only, "—" when empty; an **Active** checkbox; **Delete**) and an Add row. Each entry needs a Slack id (`^[UW][A-Z0-9]{8,12}$`), a GitHub login (`^[A-Za-z0-9-]{1,39}$`, `copilot` included) or both; names are 1 to 60 characters, Slack ids and logins (ignoring case) are unique, and the list holds at most 50, all checked inline before saving. Add, rename and delete send the whole list (`PUT /api/settings {reviewers}`, a new entry without an `id`); delete asks first and names where the entry is used ("It is active and overrides org/api."). The **Active** ticks are the reviewer swap: each tick sends `{active_reviewers}`, every tick is disabled until it resolves, and a failed save reverts. With no active reviewer the section warns that Slack repos mention the `channels.json` bot (`bot_label`) and GitHub repos skip grinding.
**jev**: a **Use jev** switch (`PUT /api/settings {use_jev}`, reverts on a failed save) and a read-only "jev found / not found" line. **Accounts**: the named commands a session can launch with, one per account and each command unique. Each row has a **Harness** (Claude Code or Codex; the built-in `claude` row is fixed to Claude Code) and a Codex row a comma-separated **Models** field (at most 20 names, each 1–80 letters, digits, `.`, `-`, `_`, `:`, `/`, starting with a letter or digit). The check button runs the account's harness's login check (`POST /api/settings/test`): Codex reports "codex CLI not found on PATH" (another command: "codex command '<cmd>' unusable: ...") or "`` codex CLI is not logged in, run `<cmd> login` ``" plus the CLI's first output line; Claude reports "not logged in" or "auth status check failed: ...". A command that is not the harness's CLI fails the check, since it does not answer that harness's login command. Claude accounts' plan
usage (5h / 7d) shows at the foot of the rail (the Away menu on a phone); an account whose usage entry has an `error` shows "usage unavailable" with the error as tooltip, and no meter when it also has no numbers (a Codex account: the poller never fetches one and reports `error: "not available for Codex"`). **Notifications** shows the matrix of 12 events by Browser, ntfy and This Mac: one switch per cell, saved at once. Each column header shows the channel's state and a Send test button (Browser tests itself; ntfy and This Mac call `POST /api/settings/notify/test` and toast the result; This Mac is disabled off a Mac) (`POST /api/settings/notify/channel`; a failed save reverts the switch and toasts). Below it, "Phone push (ntfy)" edits `ui.json` (written mode 0600; a token or
password is never sent back to the browser, and an empty box keeps the saved one). **Peer review**
sets the rounds cap, the lenses ticked by default and each lens prompt; changes are saved to
`<data_dir>/config.json` and laid over the shipped `run-engine/config.json`, so **Reset to defaults**
just removes that file. **Notes vault** sets the vault path. With no repos registered the app opens
an onboarding page that checks `gh` and a Claude account, then scans folders.
`GET /api/settings` returns each account in `commands` with its `harness` (`claude` or `codex`; a stored account with none, or an unknown value, is `claude`; the built-in `claude` row is always `claude`, 400 `the built-in account is always claude`) and, for a Codex account, `models` (at most 20 names of 1–80 letters, digits, `.`, `-`, `_`, `:`, `/`, starting with a letter or digit; 400 `models must be a list of at most 20 model names`; ignored and not stored on a Claude account), plus the read-only `harnesses` (each harness's `id`, `label`, `models` (`null`: from the account), `efforts` and `usage`; never stored). A `PUT` that includes `commands` needs a distinct command per account, the built-in `claude` counted (400 `each account needs its own command`); a partial `PUT` skips that check and keeps a stored duplicate. `ui_settings.harness_of(cmd)` and `models_of(cmd)` map a command to its account's harness and models (`claude` / `[]` for an unknown command). It also returns `slack_channels` (`[{id, name}]`, at most 50; an id is `C`, `G` or `D` plus 8–12 uppercase letters or digits, ids unique, a name 1–60 characters; a `PUT` with it replaces the whole list, one that omits it keeps it; 400 on a bad entry, a duplicate id, over 50, dropping a channel a repo still picks ("channel C… is used by owner/repo"), or a repo `slack_channel` that is not listed, `""` or its own unchanged stored value), each repo's read-only `channel_invalid` (non-empty `slack_channel` not in the list; never stored), `reviewers` (`[{id, name, slack_id, github_login}]`, at most 50; the server generates `id` (`r-` plus 8 hex) for an entry sent without one and keeps a sent one, so ids survive renames; a name is 1–60 characters, at least one of `slack_id` (`U` or `W` plus 8–12 uppercase letters or digits) and `github_login` (`copilot` included); Slack ids unique, logins unique ignoring case; a `PUT` with it replaces the whole list, one that omits it keeps it; 400 on a bad entry, a bad or duplicate sent id, a duplicate or over 50), `active_reviewers` (ids, may be empty) and each repo's `reviewers` (`null` (default: follow `active_reviewers`) or its own ids; a repo entry that omits it keeps the stored one). Both take only listed ids (400 `unknown reviewer id r-…`, including one the same `PUT` removes), and removing a reviewer removes its id from `active_reviewers` and from every repo override; the first load after the upgrade (no `reviewers` key in the file) seeds `slack_channels`, `reviewers` and `active_reviewers` once, under the settings lock: each repo's valid `slack_channel` and each valid `channels.json` channel id become id-named channels, a valid `channels.json` `bot_uid` becomes the only active reviewer (named `bot_label`, or `Review bot`), each repo's valid old `reviewer` becomes one login-only reviewer (deduped ignoring case) that the repo overrides with when it has no channel in Settings or `channels.json`, and the old `reviewer` values are dropped; a corrupt file is left alone; `use_jev` (bool, default true; a `PUT` that omits it keeps it, a non-boolean is 400) and the read-only `jev_installed` (is `jev` on `PATH`; never stored) and `personal_plugin` (is a plugin `ai-workflow-personal@…` in `$CLAUDE_CONFIG_DIR/plugins/installed_plugins.json`, default `~/.claude`; never stored). Without it the Start dialog and palette hide `dump`, `worklog` and `sync-from-wasensi`, and a session runs them as `/ai-workflow-personal:<name>` when it is installed, else leaves the text as typed. `GET|POST /api/settings/notify`, `POST /api/settings/notify/test` (`{channel: "ntfy"|"mac"}`: one sample push on that channel alone, ignoring the matrix and Away mode; 200 `{ok}` or `{ok: false, error}` with an HTTP status, error type or "ntfy is not set up" / "Only on macOS", never a credential; `browser` or an unknown channel is 400), `POST /api/settings/notify/channel` (one event × channel switch,
`{event, channel, on}`; `GET` also returns `matrix`, `events`, `ntfy_ready` and `mac`), `GET|POST /api/settings/review`, `POST /api/repos/remove`,
`POST /api/repos/check`.
`GET /api/products` lists the products (`ui_products.py`): `[{docs_repo, path, repos: [{name, role, repo, path, cloned, conflict?}], error?}]`, read from each docs repo's `.blubird/repos.json` on every call (entry paths resolve against the docs repo; `cloned` is a `.git` in that path; `conflict` names the other docs repo that lists the same repo; a map that breaks later lists `repos: []` and `error`). `POST /api/products {path}` registers a docs repo checkout and returns its row: it and every cloned code repo of its map go into `checkouts.json`; 400 when `path` is not a git checkout with a GitHub origin, the map is missing or invalid, a clone's origin is not the map's `repo`, or a code repo is already registered at another path. `ui_products.sync()` registers code repos cloned since; `ui_products.mapped(path)` says whether a checkout has `.blubird/repos.json` or `.blubird/docs-repo`.
`GET /api/health` returns `{ok: true}`. `GET /api/vault/folders` returns `{vault, folders}`, the vault path and every `05-Work/<Project>[/<Feature>]` folder. `GET /api/vault/prd?folder=<05-Work/Project/Feature>` returns `{exists, status, title, folder}` for that folder's `PRD.md` (400 on a bad folder). `GET /api/github/owners` returns `{owners}`, the `gh` login and its orgs that Publish can create a repo under (502 when `gh` is not logged in). `GET /api/sessions/cleanup` lists the finished sessions that can be removed (`{items}`); `POST /api/sessions/cleanup {keys}` removes those sessions and returns `{removed}`.
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
root ends its turn, the UI starts one read-only `peer-reviewer` session (Opus, `--allowedTools` from the agent's `tools:` list, kept on every resume) per lens (`POST /api/review`, body
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

`make restart` (and Settings → Server **Rebuild and restart**) rebuilds the UI, then restarts the
launchd agent `dev.aiw.ui` (`launchctl kickstart -k`) when it is loaded, else the supervisord
program `aiw-ui`.

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
`AIW_NTFY_TOKEN` override the file. `AIW_NO_MAC_BANNER` (any non-empty value) turns the Mac
banner off (`run_tests.sh` sets it; the Settings "Send test" then reports the off-switch). `public_url` is the base for push click-through links.

For clickable macOS banners run `brew install terminal-notifier` on the host and restart `aiw ui`; without it banners still show (through AppleScript) but cannot open a link.

**Security:** when `aiw ui` is fronted by `tailscale serve`, every request that does not arrive on loopback must carry the
node owner's `Tailscale-User-Login` (added by `tailscale serve` for tailnet traffic only), so other tailnet
users and funnelled traffic are refused; with no tailscale, or on loopback, there is no app-level auth: anyone who can reach the URL can start sessions. Sessions run `claude --dangerously-skip-permissions` by
default, with no opt-out flag; on a Codex account they run `--dangerously-bypass-approvals-and-sandbox` (approvals and
sandbox bypassed, the same trust level). Agent sessions (peer-review lenses, the Away answerer) are the exception: on
Claude they get only their allowed tools, and on Codex they are refused (see **Repo copies of skills**). Only run
sessions on repos whose `.claude/` and `.agents/` you trust. Never use `tailscale funnel` for the UI (public exposure plus skip-permissions
is remote code execution), and on a shared machine any local user can reach the loopback port. The one
exception is the share listener (see Share a PRD): a separate, read-only listener that serves only
`/s/<token>` for one PRD, cannot start sessions and answers anything else with the same 404. The UI's
own port is never funnelled.

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
- For a Codex session, `codex_prompt(text, cwd)` inlines the copy `resolve` picked: `Base directory for this
  skill: <folder>`, the `SKILL.md` body without frontmatter, then `ARGUMENTS: <args>`. Personal skills come
  from the installed `ai-workflow-personal` plugin's `installPath`; anything else is `resolve`'s text.
  The adapter's `skill_text` sends it at every spawn and send (start, queued start, answer, typed prompt,
  continue, re-entry); the stored command is still `resolve`'s short form.
- A Codex session runs `codex exec --json --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check
  [model/effort flags] <prompt>` and continues with `codex exec resume <same flags> <thread id> <prompt>`. A fresh start that carries
  instructions (the headless rules, the grind re-entry) puts them, then `TOOL_MAPPING` (Claude Code tool names to
  `aiw ask`, `SKILL.md` paths, in-session work, end the turn), before the skill prompt; a resume sends the
  prompt alone. Login is the exit code of `<cmd> login status` (`` codex CLI is not logged in, run `<cmd> login` ``
  plus the CLI's first output line in parentheses). Resume in terminal is `cd <path> && <cmd> resume <id>`,
  every word quoted. Pins (`ui_origin`) read a Codex stream's `file_change` paths and `gh issue create` output.
- Agent sessions on Codex (peer-review lenses, the Away answerer; any start with `agent` or `allowed_tools`):
  while `harness_codex.AGENT_SANDBOX_VERIFIED` is `False` (as committed: on codex-cli 0.166.0 gate G2 passed,
  `exec resume` takes `-c sandbox_mode="read-only"`, but G3 failed, the read-only sandbox blocks the network `gh` needs) `ui_runner.start` raises `AgentRefused` ("panels and Away answers need a Claude account: Codex's
  read-only sandbox cannot run gh") before any record or process; `ui_panel.start` refuses the same way before
  the panel or its root exists (a 400), and `ui_afk` holds the round at once with that message as its reason, no
  second attempt. With it `True` the session runs `--sandbox read-only` (never the bypass flag), its first prompt
  is the agent file's body without frontmatter (`away_answerer.agent_body`) then the prompt, with no
  `TOOL_MAPPING`; the record gets `sandbox: "read-only"` and `agent`, so every resume adds
  `-c sandbox_mode="read-only"` (`exec resume` has no `--sandbox`) and a start-over sends the agent text again.
- The one exception is the vault's name suggestion (`claude -p` with no skill and no session record).

**Hand-offs between skills** follow the guide's "Repo skills win" rule
(`guides/engineering-workflow.md`, Repository settings): the skill checks
`<worktree root>/.claude/skills/<name>/SKILL.md` with Read or Glob and runs `/<name>` if it exists,
else `/ai-workflow:<name>`. Inside a Codex session, `TOOL_MAPPING` turns such a hand-off into reading the
other skill's `SKILL.md` (the repo copy when it exists) and following it.

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
- Trust: a repo copy runs with the session's permissions (`--dangerously-skip-permissions`, or the Codex
  bypass flag). Only run the workflow on repos whose `.claude/` you trust.

**What a copy must keep so the UI can still drive it:**

| Skill | Keep | Read by |
|---|---|---|
| pr-grind | State file `<pr_grind_dir>/<owner>-<repo>-<pr>.md` with the header keys `owner`, `repo`, `number`, `thread`, `author`, `reviewer`, `reviewers`, `paused`, `done`, `next-poll`, `poll-since`, `ci-seen`, `dispatch-due` | `ui_runner._valid`, `_new_review`, `prgrind_tick`; `ui_dispatch` (`dispatch-due`); `ui_grind.index`. pr-grind's own list: `## State file` |
| pr-grind | One `## Round ` heading per round | `ui_grind.index` counts them |
| pr-grind | `## Re-entry` (the "On-wake branch"), `## Step 8 — Paused stop`, and the headless re-arm: write `next-poll`, end the turn | `REENTRY_PROMPT` (`ui_runner.py`), `LANE_GRIND` (`dispatch_run.py`) |
| peer-review | The `--root <panel id>` round protocol | `ui_panel.py` starts `/ai-workflow:peer-review --root <panel id> <artifact>` |
| any | `aiw ask` for gate questions in a headless run | `HEADLESS_PROMPT` (`harness_claude.py`); on Codex also `TOOL_MAPPING` (`harness_codex.py`) |

- The tick always runs the plugin's own `skills/pr-grind/scripts/poll-reviews.sh` (`_POLL_SH`),
  whichever copy of pr-grind runs. It watches every login in `reviewers:` (comma-separated, compared
  ignoring case), falling back to `reviewer:` when that line is missing, and the PR author with
  `not-author` while `reviewer:` is `UNRESOLVED`.
- Relative `../../guides/` and `../../templates/` paths in a copied skill no longer reach the
  plugin: point them at the repo's own copies or an absolute source.

## Where state lives

Nothing stateful lives in this repo. `aiw paths` resolves it under `$CLAUDE_PLUGIN_DATA`
(default `~/.claude/plugins/data/ai-workflow`), which **survives plugin upgrades**.

| Path | Contents |
|---|---|
| `sessions/` | one directory per UI session: record, stream, answers |
| `ui_settings.json` | the named accounts (command, harness, Codex models), the vault path |
| `checkouts.json` | the registered repo checkouts |
| `products.json` | registered products: docs repo `owner/name` → checkout path (code repos are read from its map, not stored) |
| `pr-grind/` | one markdown state file per PR under grind |
| `issue_grind.json` | each issue's Grinding switch, by repo (unset issues follow the repo's auto-grind) |
| `peer-review/` | one directory per panel: `panel.json` and `round-<n>/<lens>.md` verdicts |
| `restart.log`, `restart.exit` | output and exit code of the last Settings → Server **Rebuild and restart** (`make restart`, a detached child; `GET/POST /api/restart`) |
| `afk.json` | the Away mode window and its log |
| `dispatches/` | one `<id>.json` per dispatch (settings, lanes, events) and its `.lock`; finished ones older than 30 days move to `dispatches/archive/` (not listed, restore by hand) |
| `bootstraps/` | one `<id>.json` per bootstrap run (repo, issue, branch, six phases with their session ids, state, error) and its `.lock` |
| `ui.json` | push notifications and `public_url` (mode 0600) |
| `config.json` | peer-review overrides from Settings, laid over `run-engine/config.json` |
| `jev_cache.json` | cached jev answers for Inbox urgency, readiness and duplicates: at most 2000 entries, ignored after 7 days, written by the server only (never by `aiw jev`); safe to delete |
| `channels.json` | Slack ids and trigger templates for grind and release-pr; schema in INSTALL Step 6 |
| `shares/` | one JSON record per shared PRD with its threads and approvals (mode 0600), kept until the author deletes the share record |
| `share-runtime.json` | the share listener's loopback port and the funnel port, so a restart serves the same link |

The work's own state is on GitHub and in the repo's `docs/prds/`.

## Layout

```
skills/       create-prd, create-tasks, refine-issues, implement-issue, verifier-locally,
              pr-review, docs-updater, faq-updater, skill-feedback, sync-from-wasensi, pr-grind,
              peer-review, dump, release-pr, revert-pr, close-epic, worklog, herdr-dispatch, repo-bootstrap
agents/       away-answerer, peer-reviewer, worklog-runner
guides/       engineering-workflow, code-review, skills
templates/    prd, epic, issue, faq, claude-md, repo-audit
run-engine/   route.py (the aiw CLI) · ui_*.py (the web UI server) · peer_review, threads, ci, ask
              dispatch_run (the lane engine), dispatch_runners (herdr, herdr-app, headless), dispatch_cli
              harness (the adapter registry: a session's recorded `harness`, `claude` when missing, picks its adapter)
              harness_claude (the Claude adapter: login check, start/resume argv, skill text)
              harness_codex (the Codex adapter: login check, exec/resume argv, tool-name mapping, parser; fixture in fixtures/)
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
bash run-engine/run_tests.sh          # every test_*.py; also the pre-push hook and CI
```

No network, no install step. The UI has its own checks, in `ui/` (Node 20; plugin users never need it):

```bash
cd ui && npm ci && npm run typecheck && npm run lint && npm test && npm run build
```

The `ui` CI job runs those and fails if the committed `run-engine/ui_dist/` differs from the build.
`run-engine/test_ui_static.py` checks the server's static serving, Host/Origin guard and cache headers
against the committed build.
