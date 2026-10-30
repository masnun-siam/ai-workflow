# Changelog

## Unreleased

### Added

- **Dispatch account** (#670): a dispatch gets an **Account** setting (New dispatch dialog, live editor, `aiw dispatch set <id> account=<label>`); lane sessions started after it run on that saved account. Headless lanes only; a label deleted from Settings falls back to the default.
- **Bootstrap runs: phase strip on the session page** (epic #645, #656): a bootstrap phase session's page shows the run's `PhaseStrip` above the transcript (its own phase marked "this session", the others linked), and the Start dialog describes "Bootstrap repo" as one branch and one PR, each phase its own session.
- **Bootstrap runs: Inbox cards and phase strip** (epic #645, #655): a Decide card for a waiting run (Continue bootstrap, Stop) and a Fix card for a stopped one (Retry phase, Stop, Open session), each with the shared `PhaseStrip` (six phases, state as text, current step marked, links to each phase's session).
- **Cross-repo boards: picks stay within one repo** (#669): in the Small changes All repos view, Ready rows have pick checkboxes and "Run N as a dispatch". The first pick disables other repos' checkboxes with a note until cleared, picks that stop being ready drop on refresh, and the dispatch dialog opens on the picked repo.
- **Bootstrap runs: API and Inbox items** (epic #645, #654): `GET /api/bootstraps[?repo=]`, `POST /api/bootstraps/<id>/continue|retry|stop`, Inbox items `bootstrap_waiting` (group decide) and `bootstrap_stopped` (group fix), and a `bootstrap` field on session rows. A failed phase session makes no generic `session_failed` item.
- **Bootstrap runs: chain** (epic #645, #653): starting `/repo-bootstrap` through `POST /api/sessions` creates a bootstrap run under `<data_dir>/bootstraps/` and its first phase session; when a phase ends with `BOOTSTRAP: <phase> done #<issue>` the server starts the next phase as a new headless session (`waiting` after the audit, `done` after docs), any other ending stops the run at that phase, and a second run for a repo is a 409. A restart re-checks running runs.
- **Cross-repo boards: capture bar repo picker** (#666): `CaptureBar` takes `pickRepo`, which adds a "Capture repo" picker defaulting to the switcher's repo; Feature, Small change and Auto then start on the picked repo. Wired into the pages by #667 and #668.
- **PR panel: Close PR… and Reopen PR** (#651): the footer shows "Close PR…" (inline confirm, branch kept) on open and draft PRs and "Reopen PR" on closed ones, calling `POST /api/pulls/<o>/<r>/<n>/state`; GitHub's refusal shows in the footer and the panel refetches. Merged PRs show neither.
- **Question form: "Select all" and "None of these"** (#648): every multi-select question (Inbox, session page, Away Change dialog) shows a "Select all" link and a "None of these" checkbox that sends the `none` answer kind.
- **Answer endpoint accepts "none"** (#647): `{"none": true}` answers a multi-select question even with free text off (400 on single-select), resumes as `{"other":"None of these"}`, and works in `POST /api/afk/change`.
- **Share a PRD for review** (epic #584, #603): the PRD tab's Share button and the "Public (n)" badge publish a Draft or In review PRD at a token link on a separate read-only listener behind a tailscale funnel; reviewers read it, comment on selected text and Approve (a signal, never the PRD's status) without an account; the author replies, resolves and sends open comments to a `/create-prd --update` session, and an Inbox item and `prd-comment` event announce new comments. Needs the `funnel` node attribute in the tailnet policy (`docs/INSTALL.md`); the UI itself is still never funnelled.
- **Share links: PRD tab thread rail** (#600): the PRD tab highlights each commented sentence and lists the share's threads beside the text (open in text order, resolved collapsed, Outdated with their quote). The author can reply, resolve, reopen and delete comments and threads, and delete the record of an ended share. While the tab is open it marks the share seen.
- **Share links: Send open comments button** (#601): the thread rail gets "Send open comments (n)". It shows the exact prompt in a confirm dialog (with warnings for a running panel or update session and for older comments that will be dropped), then starts the PRD update session and links to it, reporting threads still unsent.
- **Share links: Send open comments** (#592): `POST /api/shares/<id>/send` builds one `/create-prd <path> --update` prompt from a share's unsent open threads (reviewer text in one delimited untrusted block, capped at 32,000 characters), previews it without `confirm: true`, otherwise starts the update session and marks only the threads it sent; `GET /api/shares/<id>` gains `unsent`.
- **Share page read view** (#595): `ui/share.html` is a second Vite entry, built to `run-engine/ui_dist/share.html` with a build manifest (`.vite/manifest.json`) listing the files the page may load. It shows one shared PRD read-only from `/s/<token>/api/prd` with the PRD tab's Markdown and Mermaid rendering, polling every 30 s; fonts are no longer inlined as `data:` URLs.

- **Share page commenting** (#596): a reviewer selects text in the shared PRD, gives a name once (kept in `localStorage`), and posts a thread anchored to the selection; threads sit beside their text (below it on a narrow screen) with the quote underlined, and replies, resolved threads, an Outdated list, the 500-comment "Share is full" state and draft-keeping errors are handled. Reviewer text renders as plain text.
- **Share page Approve** (#597): a reviewer approves under their display name; the page keeps the withdraw key in `localStorage`, shows "You approved · Withdraw" or "Approved as <name>", lists approvers with a count and marks approvals older than the PRD's last edit. It never changes the PRD status.

### Removed

- **`/flow` skill** (#621): the deprecated guided flow and the Start dialog's "Plan a flow" are gone; run `/create-prd`, `/create-tasks`, `/refine-issues` and `/herdr-dispatch` directly.

### Changed

- **`/repo-bootstrap` is one PR, one phase per run** (#652): every phase commits to `bootstrap/<issue>`, one draft PR opened by constitution and ready after docs with a per-phase checklist; each run does one phase and ends with the next command and a `BOOTSTRAP: <phase> done #<issue>` last line. The per-phase-PR mode is removed.
- **Strip board look for `aiw ui`**: the UI is restyled as an air-traffic strip board. Items sit as strips in sunken bays on a grey-green console, a coloured left edge shows the stage, items that need you are amber and pushed out of line, and the header is a dark plate. Archivo (variable width) replaces Geist and Geist Mono for UI text; code stays monospace.

- **Dispatch page: now, next, done**: the wave graph and list views are gone. The page shows one progress tick per issue with totals, then **Building now** (a card per running lane with its four steps), **Up next** (ready first, each with what it waits for) and **Done** (PR, time, cost), with the activity feed or the picked issue's panel beside them. Issue titles drop the epic-name prefix.
- **Subway UI**: the dark sidebar is gone. A top bar holds the repo, page links with counts, search, an orange "n need you" button, an Away menu (Away mode, usage, theme, shortcuts) and New. Features is a map with one line per feature through the stages; a feature page shows its line and its build map as tracks; Inbox items are cards; Activity's live sessions are a departures board; a dispatch page is a header card over a timetable of waves with its activity feed below, and the Dispatches list draws each running dispatch as a track of wave stops; the Start dialog ("What should we start?") shows the six command groups as cards with each command a pill. Warm paper palette, pill buttons; page names and routes are unchanged.
- **Grind logs jev hints** (#581): `/pr-grind` logs jev's CI and finding hints (FR-7, FR-8) in its state file as `jev-ci-hint:` and `jev-finding-hint:` lines; advisory only, nothing is written with jev off or missing.
- **Inbox sorts by urgency** (#575): inside each group, question, paused-grind, failed-session and PR-conflict items sort by a jev urgency score (1–5, highest first), then newest first; `GET /api/inbox` items gain `urgency` (null when unscored or Use jev is off). A 30 s background scorer fills the cache; the Inbox never waits on jev.
- **Inbox order holds while an item is open** (#576): with a question expanded (including the default-open one) or the issue/PR side panel showing, a poll that brings a new order does not move rows, the selection or focus. New items join the end of their group; the server's order applies once nothing is open or on the next visit.
- **Away mode risk check** (#573): before auto-picking a round whose questions all carry a recommended option, a jev worker (off the tick, two at a time) asks whether any recommended option is irreversible or outward-facing and stores `risk` on the round. At 0.5 or more the round goes to the Opus answerer and its log entry carries `risk`; with jev off, missing or failing it is auto-picked as before.

### Added

- **Duplicate warning on the New page** (#579): once a repo is chosen and the text is 20+ characters, the page asks `POST /api/duplicate` 800 ms after typing stops and shows "Looks like #n <title>" as a link that opens in a new tab. It only advises: both start buttons work as before.
- **`aiw jev` verb** (#580): `aiw jev ci-hint --file <log>` (flaky or real) and `aiw jev finding-hint --file <json>` (fix or rebut, at most 20 findings, four at a time) print jev's advisory hint as JSON and always exit 0; `status` is `ok`, `off`, `missing` or `failed`. Text goes to jev on stdin, is never cached or counted.
- **Duplicate check endpoint** (#578): `POST /api/duplicate {repo, text}` asks `jev` whether the capture text matches one of the repo's newest 100 open issues or its PRDs (needs 20+ characters and a 0.6+ pick), and returns the match with a server-built link, or a null match with a `why`. The New page warning follows in #579.
- **Readiness warnings in the dispatch preview** (#577): jev scores each refined lane's issue body 1–5 (at most 30 lanes, five at a time, 8 s in all); a score of 2 or less adds "may be underspecified (jev n/5)" and the lane still runs; lanes it could not score share one "Readiness unavailable for …" line. Plan lanes gain `readiness`; bodies are read only for the preview and never returned. The jev answer cache is now server-only.
- **Risk line in the Away summary** (#574): a round the risk check sent to Opus shows "Risk check: sent to Opus (p=…)" on its row in "While you were away" (p rounded to two decimals); other rows are unchanged.
- **jev answer cache and call ceiling** (#571): the Inbox urgency, readiness and duplicate points reuse earlier answers (kept in memory, flushed to `jev_cache.json` in the plugin data dir every minute; 2000 entries, 7 days) and stop at 500 jev calls an hour (`capped`). Risk checks, the capture route and hints are never cached or counted.
- **Shared jev helper** (#570): `run-engine/jev.py` is the one place that runs `jev` (pinned model, 8 s timeout, 4000-character input, token-shaped strings redacted first); any failure gives a null answer. The capture router now uses it, and with the switch off `POST /api/route` answers `jev is off`. jev will also see Inbox question, pause and error text, refined issue bodies in a dispatch preview, the capture text plus the repo's open issue and PRD titles, failing CI log tails, review findings, and Away mode round text; **Settings → Use jev** turns all of it off.
- **jev switch in Settings** (#572): Settings → jev has a **Use jev** switch (saved at once, reverts on a failed save) and a read-only "jev found / not found" line; the UI's API types gain the fields later jev issues use.
- **Use jev setting** (#569): `GET /api/settings` returns `use_jev` (default on) and a read-only `jev_installed`; `PUT /api/settings` accepts `use_jev` (boolean, else 400) and keeps it when omitted.
- **Issue and PR links open the side panel** (#582): a plain click on any GitHub issue or PR link in `aiw ui` opens its panel instead of a GitHub tab (modified clicks and the "on GitHub" buttons still go to GitHub). Sessions started by refine, or by a feature's create-tasks and refine steps, link to their issue or epic; `POST /api/start` takes an optional `issue`.
- **Features redesign**: a new look app-wide (Geist, a dark sidebar, stages from pale to deep teal, solid orange only for what needs you) and new Features screens. Features is a pipeline of stage tiles over one card per feature with its issues as squares and the next step. A feature page has stage blocks, an orange alert when its dispatch needs you, a **Build map** of issues in dependency waves, the dispatch's time, cost and events, and the PRD's sections, above the existing tabs. **Small changes** is its own page (`#/changes`): a priority-by-state grid that filters, a **Ready to run** panel that starts a dispatch, and **Needs refining first** cards. One **capture box** starts either kind of work; **Auto** routes it with `jev` (`POST /api/route`) on a New page where you confirm the route.
- **UI redesign (framed sheet)**: `aiw ui` has a new look. The sidebar and a 48px top bar share one teal-grey frame and every page sits on a white sheet; IBM Plex Sans replaces Hanken Grotesk, with Plex Mono for IDs, commands and figures. Colour is cut to two signals, orange for needs-you and red for failed; stages are a grey ramp and the feature track fills in ink with the current stage in teal. Primary buttons are near-black. Away mode warms the whole frame. Dense rows, flat surfaces, right-aligned figures, real icons in the dispatch feed. Light and dark are designed together. `PRODUCT.md` and `DESIGN.md` record the system.
- **Repo bootstrap**: `/repo-bootstrap` makes an existing repo ready for agents and this workflow, the way Wasensi was set up: a read-only audit issue (`templates/repo-audit.md`), the decisions it raises, a short protected `CLAUDE.md` (`templates/claude-md.md`) with a confirm-before-edit hook and pre-commit guards, conventions guides and a tested README quickstart, gate gaps filed as issues, then `/docs-updater full`. One PR per phase. Started from **Bootstrap repo** in the Start launcher's Maintain group.
- **FAQ updater** (epic #540): `/faq-updater` writes and updates the product's plain-language user guide and FAQ in `docs/faq.md` from the code, answers the team's questions and opens a PR (#543). It uses `templates/faq.md` (#542) and has an **Update FAQ** entry in the Start launcher's Maintain group (#548). Listed in `guides/skills.md`, `docs/REFERENCE.md` and `docs/HOW-IT-WORKS.md` (#549). It publishes the guide in every language given with `--lang`, protecting `team`-edited translations (#546).
- **Keyboard-first UI** (epic #484): every page works without the mouse. `J`/`K` and arrows select rows, `Enter` opens them, action keys with badges press the buttons, `[`/`]` switch tabs, question rounds take digits, `Tab` and ⌘↵, and ⌘K lists **Actions here**. `docs/REFERENCE.md` lists all the keys (#503).
- A **Base branch** setting for a dispatch (#486): a searchable picker of the repo's branches in the New dispatch dialog (also for Run small changes), `--base-branch` on `aiw dispatch plan|start` and `herdr-dispatch`, and `GET /api/github/branches?repo=<owner/name>`. PRs land in it, a missing feature branch is cut from it, and Open PR goes into it. It is fixed at start, must exist in every lane repo, and empty keeps today's behaviour (#511).
- Issue/PR panel buttons take their keys: `M` opens the merge confirm (`Enter` merges, `Esc` cancels back to Merge…), `S` Skip CI, `X` Stop, `E` Refine, `C` focuses the comment box, and the card action in the panel head takes `A`, `R`, `E`, `S`. The panel's keys win over the row's (#496).
- `[` and `]` switch to the previous and next tab on Features and the Feature page, stopping at the first and last tab, under the same guards as the other single-key shortcuts (#491).
- The dispatch page works from the keyboard (#501): `J`/`K` select a lane in graph or list order, `Enter` opens the lane panel, which follows the selection, `Esc` closes it, and the lane, panel and page buttons take their keys (`M`, `A`, `R`, `C`, `X`, `O`).
- The Activity page works from the keyboard (#502): `J`/`K` select a session through the Live cards then the History rows, `Enter` opens it, and the selected History row's main button takes its key (`A` Answer, `R` Retry or Resume).
- The session page works from the keyboard (#497): `R` presses Resume, Retry or Rerun, `T` Continue in terminal, `X` Stop, and `C` focuses the message box.
- The Feature page's buttons take keys (#499): `P` Approve PRD / Approve without review / Approve anyway, `E` Refine N and Refine N picked, `M` Review and merge. A key does what its click does.
- The Inbox works from the keyboard (#495): `J`/`K` select an item across the groups, `Enter` expands a question or presses the item's primary button, each item's buttons take a key with a badge, and `Esc` leaves an expanded question round.

### Changed

- **`/repo-bootstrap` is one PR, one phase per run** (#652): every phase commits to `bootstrap/<issue>`, one draft PR opened by constitution and ready after docs with a per-phase checklist; each run does one phase and ends with the next command and a `BOOTSTRAP: <phase> done #<issue>` last line. The per-phase-PR mode is removed.
- A dispatch with `base_branch` set now sends lanes to it: with no feature branch, each lane branches from it and opens its PR into it (conflict-fix and followups prompts name it). **Open PR** opens the feature branch into `base_branch` instead of the default branch. The followups prompt now ends "Close #n if it is still open." whenever a base is given (#507).
- Away mode now answers `/create-prd`, `/create-tasks`, `/refine-issues` and `/dump` rounds when every question has a recommended option (the #188 exclusion applies only outside a window). Answer entries in `afk.json` gain `id`, `by`, `questions`, `answerer`, `cost` and `changed` (#460).
- A copy of a plugin skill in a repo's `.claude/skills/<name>/` now takes over everywhere: UI sessions, dispatch lanes and herdr tabs, peer-review panels, pr-grind re-entries and skill-to-skill hand-offs. Stored commands now read `/<name>` (repo copy) or `/ai-workflow:<name>` (plugin). If you keep a stale copy there, delete or update it. `docs/REFERENCE.md` "Repo copies of skills" lists what a copy must keep so the UI can still drive it (#440).

### Fixed

- Rows in the ⌘K palette and the repo and branch pickers no longer all show the blue keyboard-selection ring; only the active row is highlighted. `J`/`K` selection keeps its ring (#538).
- The Features → Small changes tab sections (describe box, pending rows, pick bar, issue table) are now spaced 12px apart instead of touching, and no empty bordered list shows when nothing is pending (#476).
- Stopping a session that was re-attached after a UI restart now always leaves it `stopped`; before, the follower could race the stop and record it as `failed`, which also made `test_ui_runner.py` flaky (#415).
- `GET /api/sessions` rows now carry the session's `slug`, resolved by real path, so a session started from a symlinked checkout (macOS `/tmp`) still shows its pending row on Small changes and locks Refine (#421).
- A finished dispatch that gains new epic children (typically bugs filed by Run QA) now goes to `paused` with an event, instead of running again and ending `done` with a queued lane nothing starts. Refine the new issues, then press **Resume** to start their lanes.

### Added

- ⌘K shows an **Actions here** group first: the enabled actions on the current page, open panel and selected row, labelled like the button with its key (`Resume (R)`), plus the items of mounted menus (`Resume on personal`). Running one does what a click does (#490).
- The "While you were away" summary gets **Change N selected**: a dialog with the question form for each ticked answered round, prefilled with the logged picks, that posts `/api/afk/change` and toasts sent, queued or the refusal per session (#466).
- Every headless session spawn and send resolves plugin skill commands against the session's working directory (`repo_skills.resolve`): a repo with `.claude/skills/implement-issue/SKILL.md` runs and shows `/implement-issue 12`, elsewhere `/ai-workflow:implement-issue 12`, whichever spelling was typed. Queued and rate-limited starts resolve when they begin and write the resolved command back; answers, typed prompts and resumes are sent resolved and leave the stored command unchanged (#439).
- "Repository settings" in `guides/engineering-workflow.md` gains **Repo skills win**: before one plugin skill runs another, it checks for the repo's own `.claude/skills/<name>/SKILL.md` and runs `/<name>` if it exists, else `/ai-workflow:<name>`. Every hand-off line points to the rule, flow, herdr-dispatch, pr-grind, release-pr, peer-review and dump now read "Repository settings" first, and `run-engine/test_repo_skills_text.py` keeps it that way (#435).
- Settings gets a **Server** section (`#/settings/server`) with a **Rebuild and restart** button that runs `make restart` as a detached child and reloads the page when it succeeds, or shows the log tail when it fails. `GET /api/restart` reports `available`, `running`, `exit_code` and `log_tail`; `POST /api/restart` starts it (409 while one runs, 400 without a `make restart` target) (#429).
- New GitHub Pages showcase in `site/` replaces the old Field Guide: a landing page, a scroll-driven pipeline, a UI tour and a case study. All of it uses real captures from one todoman run (idea to ready PR in 11.5 min). `.github/workflows/pages.yml` builds and deploys it on pushes to master that touch `site/`.
- Features gains a third tab, **Small changes**, after **In progress** and **Shipped**, and the selected tab is now in the URL (`#/features?tab=shipped|changes`). Small changes holds the open issues that belong to no feature, grouped by status, under a **Describe a bug or small change** box whose **Create task** starts one headless `/create-tasks` session that files the issue with no PRD and refines it in the same session.
- `POST /api/dispatches` and `POST /api/dispatches/plan` take `issues: ["owner/repo#n", ...]` in place of `epic` (never both; 1 to 30 open issues in one repo; no `feature_branch`): 400 for a bad request, 409 when a picked issue is a lane of a dispatch that is not done or cancelled. `GET /api/dispatches[/<id>]` returns `issues` (the list, or null) and `title`. Such a dispatch re-reads only its listed issues, so no lane joins it later. `aiw dispatch plan|start` and `herdr-dispatch` still take an epic only.
- Small changes tab: unrefined, ready and blocked rows that no dispatch owns get a checkbox, and a pick bar shows **Refine N** (one headless `/refine-issues` on the picked unrefined issues, locked while a small change is being filed), **Run N** (the Run small changes dialog on the picked refined issues) and **Clear**. The counts follow the board; switching repo clears the picks. On a feature's Issues tab an unrefined issue a dispatch owns no longer has a checkbox.
- The run dialog has an issue-list mode, "Run small changes": it shows the picked issues as chips, has no epic or feature branch field, and previews and starts with `issues` instead of `epic`. The live settings of an issue-list dispatch have no Feature branch either. Run N on the Small changes tab opens it.
- Small changes tab: each live small-change `/create-tasks` session of the repo shows as a row above the issues (Queued, Creating… or Needs you, with Watch or Answer) until it ends, counts in the tab, and disables Refine on unrefined rows meanwhile.
- The Dispatches list, the dispatch page and the Inbox show an issue-list dispatch (`epic: null`, `issues` set) by its title, "Small changes: #412, #415", with `owner/repo` in place of the epic reference. It offers no Run QA, Open PR or Grind action when finished, and the Features page skips it.
- Dispatch merge gate follows the CI mode: `defer` merges only on green or no CI, holds as "waiting for green CI (defer)" and sends the CI-fix prompt once per red head commit (`pr.sha` in lane facts); `ignore` skips the CI check and a merge with red or pending CI adds a "merged with red CI" / "merged with CI pending" warning event and notification. `wait` is unchanged.
- Approve PRD (Inbox and feature page, one shared `approveArgs`) now also tells the session to commit only the PRD file, push onto the PRD's open PR or a `prd/<slug>` branch, open a ready PR, merge it with `--merge` right away when the repo owner is the signed-in `gh` user, and report any failed step. Both confirm dialogs say so.
- The question form (Inbox, session page, dispatch lane panel) renders question text and option descriptions as markdown, like the transcript (escaped, http(s) links in a new tab). An option's `preview` shows as a monospace, whitespace-preserving block that scrolls sideways. Labels stay plain text.
- Browser notifications work again: while permission is granted, every aiw tab polls `/api/notifications` (also in the background) and shows each new event as a system notification through the service worker. The same tag shows once across tabs, a tab shows only events after it opened, and a click focuses or opens an aiw window on the event's page.
- Settings → Notifications: each column header shows its channel's state (Browser On / Off with Enable / Blocked / Not supported, ntfy Set up / Not set up, This Mac Clickable / No links / install hint / Only on macOS) and a Send test button. Browser tests itself through the service worker; ntfy and This Mac post to `/api/settings/notify/test` and toast the result. The separate "This browser" block is gone.
- Settings → Notifications shows the notification matrix: 11 events in three groups by Browser, ntfy and This Mac, one instant-save switch per cell. The ntfy form moves below it under "Phone push (ntfy)".
- The notification matrix store: `ui.json` keeps per-event, per-channel (`browser`, `ntfy`, `mac`) overrides under `channels`. `GET /api/settings/notify` now returns `matrix`, `events`, `ntfy_ready` and `mac`, and `POST /api/settings/notify/channel` saves one cell. Matrix and ntfy form saves share one lock.
- `ui_notify.send_mac` sends the macOS banner through `terminal-notifier` when it is on the server's PATH (clickable when given a link) and falls back to AppleScript; it replaces `ui_dispatch.mac_notify`. Run `brew install terminal-notifier` and restart `aiw ui` for clickable banners.
- A session started from the UI can carry a `model` (`opus`, `sonnet`, `haiku`) and an `effort` (`low` to `max`): optional fields on `POST /api/sessions` and `POST /api/start`, applied on every spawn and replayed by Rerun. `GET|PUT /api/settings` stores the last-used pair as `run_model` / `run_effort` The Start dialog now shows Model and Effort dropdowns for every command, preselected from the saved pair and saved on change.

### Changed

- **`/repo-bootstrap` is one PR, one phase per run** (#652): every phase commits to `bootstrap/<issue>`, one draft PR opened by constitution and ready after docs with a per-phase checklist; each run does one phase and ends with the next command and a `BOOTSTRAP: <phase> done #<issue>` last line. The per-phase-PR mode is removed.
- The **Other issues** row of Features and its `#/issues` page are gone: those issues are the Small changes tab, and `#/issues` redirects to `#/features?tab=changes`.
- `ui_notify.notify` routes each event by the notification matrix: the browser feed, ntfy and This Mac each get it when their cell is on, independently, with one shared title, body and link. A dispatch no longer shows its own macOS banner; it reaches the Mac through the `dispatch` cell.
- The session transcript renders assistant and result text as markdown (headings, lists, code, links, bold, italics), and the markdown renderer now handles pipe tables.
- `make restart` rebuilds the UI and restarts the supervisord-managed server. The `ui-rewrite` PRD is marked Done.
- The New dispatch dialog and a dispatch's live settings use the shared Model and Effort dropdowns instead of the free-text model box; the dialog starts from the saved pair and a pick updates the saved defaults.
- A feature's own starts of `/create-prd`, `/create-tasks` and `/refine-issues` (Write the PRD, Approve PRD, Create tasks, Refine, Start update, Inbox approve, Add task) run on `opus` at `medium` effort (`PLAN_RUN` in `ui/src/lib/vocab.ts`), whatever the Start dialog saved.
- `/implement-issue` reviews the local branch with `/pr-review` before the first push, then merges the base branch, pushes and opens the draft PR (steps 12 to 14); `/pr-review`, `/skill-feedback`, the guides and `/verifier-locally` follow (synced from Wasensi 637579d4).
- **The Board is gone.** A feature's Issues tab holds its issues, and a new **Other issues** page
  (the last row of Features, `#/issues`) holds open issues that belong to no feature. `G` then `D` now
  opens Dispatches. "Start N now" is gone too: start one issue from its row, or run the epic.
- **The rest of the app follows dispatches.** A feature shows its running dispatch in the header, the
  Next step box and the Issues tab, where each issue a dispatch owns shows its dispatch stage and what
  it is doing, and links there instead of offering Start. The issue panel shows the dispatch in place
  of the Grinding switch. The Inbox shows an issue in a dispatch once, as its dispatch row.
- A dispatch issue's question is answered in its issue panel. Away mode also retries held or stopped
  dispatch issues. **Retry** on red CI asks the issue's session to fix CI.
- A dispatch issue tracks its PR as soon as it opens. A ready PR whose CI is red shows **CI is red**, not
  "stopped without a ready PR", and **Retry** on an issue that has a PR continues that PR instead of
  starting implement-issue over.
- Push links that went to the Board open the session instead; their buttons say **Open Inbox**.
- **Removed:** the `/next/` alias and the redirects from the old hash routes (`#/planning`,
  `#/delivery`, `#/board`, `#/answer/<id>`, `#/session/<id>`, `#/dispatch/<id>`, `#/new`); those
  addresses now show the not-found page.

- **Auto-build is gone**, with its per-repo cap, the `aiw autopilot` verb and `POST /api/autopilot`:
  dispatches run an epic's issues instead. A card or Start no longer opens a herdr tab (`POST
  /api/start` is headless only), and `herdr-dispatch` is no longer a Start command; it is the skill
  you run in herdr. Stored Auto-build settings are ignored. `/flow` ends by starting a dispatch.
- **UI rewrite.** `aiw ui` has a new interface, and it is organised around "what needs me". The
  **Inbox** collects everything that needs you across repos: questions from Claude, PRs ready to
  merge, paused grinds, failed sessions, reviews at their round cap, worklogs to clean up. You act on
  each item in place. A **Feature** is now one page from PRD draft to shipped, with one obvious next
  step; Planning and Delivery are gone (the **Board** keeps the issues, in five columns), and the
  Answer page is part of the session page. **Start** (the New button, `N`, or ⌘K) replaces New run.
  Issues and PRs open in a side panel with their comments, checks, files and merge.
  "AFK" is now **Away mode**, and epic autopilot is replaced by dispatches (below). Light and dark themes, a phone layout, and keyboard shortcuts (`?` lists them) are built in.
  Old bookmarks and push-notification links still open the right page; push links now point at the
  new routes. Plugin users do not need Node: the built app ships in `run-engine/ui_dist/`.
- Developers: the UI source is in `ui/` (React, TypeScript, Vite). Rebuild with `npm run build` and
  commit `run-engine/ui_dist/`; a new `ui` CI job checks the build is current. `run-engine/ui_static/`
  and its source-reading tests are removed, and `run_tests.sh` now uses a throwaway plugin data dir.
- `aiw ui` spends far less of the GitHub rate limit. Each board poll is a 1-point probe, and the full
  6-point query runs only when the probe sees a change. A repo nobody is viewing (no UI request for 2
  minutes, no live session) polls every 10 minutes instead of every minute. Under 1000 GraphQL points
  left, every repo slows to 10 minutes, so the poller leaves the budget to the agents. A rate limit now
  waits for GitHub's reported reset instead of a fixed 10 minutes.

### Added

- **Dispatches.** Give an epic and its refined child issues run as parallel lanes in dependency
  order: `/implement-issue`, then a grind (off, simple or full), then the merge (automatic only with
  auto-merge on, a merge commit once CI is green, a review approves and the grind is done), then
  implement-issue's followups, then the next unblocked issue. Start one from the UI (**Dispatches**,
  or **Run epic** on a feature or board lane; lanes are headless sessions) or with the rewritten
  `herdr-dispatch` skill (lanes are herdr tabs, closed when their followups are done); both see and
  steer the same dispatches. A lane that needs you is held and shows in the Inbox and as a macOS
  notification while the rest go on; settings change mid-run; usage limits pause new lanes; a
  conflict at merge time is fixed in the lane. With a feature branch, the end offers its PR, a QA
  pass whose bugs join as new lanes, and a grind of the final PR. `aiw dispatch` drives it all from a
  terminal, and `aiw grind-mode --pr <url>` lets a dispatch set its PRs' grind mode.

- UI: a **Grinding** switch per issue (default: the repo's auto-grind). Merge appears once CI is green
  and the PR is approved on GitHub (no approval needed on a repo you own), and with grinding on only
  once the grind is done too. With it on, the grind starts by itself when the PR turns ready (or at
  once, if it already is). Turning it off stops a running grind. The
  Inbox, Features list (**Merge #n** per PR), Issues tab and Board all follow this rule.
- UI: a PR that conflicts with its base can't be merged from the UI and shows **Resolve conflicts** (PR
  panel, Inbox, Board/Issues row). It starts a session that merges the base branch in, resolves the
  conflicts, verifies and pushes; the PR shows up as ready to merge in the Inbox once the merge rule
  holds again.
- **Grinding mode** in Settings → Repositories: Deep (default, as before) or Simple, where a grind
  stops at the round the PR is approved instead of fixing the remaining findings. It applies to every
  grind, running ones included, from their next round. `aiw grind-mode` prints it.
- UI: an issue and its PR now open in one panel: an Issue tab, then the PR's tabs beside it once there
  is a PR. **Open Slack thread** shows while a grind runs.
- UI: **Start now** on a queued session starts it at once past the batch cap
  (`POST /api/sessions/<id>/start-now`). A session waiting on an account limit still starts at the reset.
- UI: `day` and `skill-feedback` are in the Start dialog.
- `GET /api/inbox`, `POST /api/sessions/<id>/rerun`, `POST /api/grind/skip-ci|stop|issue` and
  `POST /api/review/<panel>/rounds`; `GET /api/prd` returns a `sha` and a save is refused when the file
  changed on disk.

### Removed

- The `grind_round` field on Delivery cards (use `grind.round`) and the `/static/` route.

- UI: a UX pass. Boards use the full window width and shrink empty columns to a strip; Delivery
  has a Blocked column, one **Start** with a ▾ for herdr, and **Close epic** in a lane ⋯ menu. A
  banner on every page shows the oldest waiting question. Sessions pins waiting and queued sessions,
  groups by issue or PR by default (fixing groups that missed object links), names each row's issue
  or PR and opens a session from its row. New run keeps the input and Start in a side panel, with
  Custom as one more card. Settings shows one section at a time.
- `/skill-feedback`: turn feedback, or `reconcile` over closed PRs' learning logs, into approved
  skill and guide edits (synced from Wasensi c6d1971f).
- `/implement-issue <epic>` picks the epic's lowest-numbered Ready issue; after the merge it
  closes the issue, sets it to Done, deletes the remote branch and moves unblocked issues to Ready.
- `/pr-review <pr> --fix` fixes the review feedback already on a PR through to green CI, replies
  and ready.
- UI: **Stop** on a session page for a session that has not finished. `skill-feedback` in New run.
  The board's stale banner says why (rate limit with retry time, or the fetch error) and has a
  **Refresh**.
- UI: refine one child at a time from the Planning card, a Needs refinement column on Delivery or
  the issue drawer; Approve PRD and Add task on the Planning card; Close epic (with its open
  children) on the card and the lane. Refine with several issue numbers works (it was refused).
- UI: Delivery collapses lanes with nothing open and has an epic filter; boards show one column at a
  time on a phone with column tabs. The palette finds the repo's issues, PRs and PRDs and switches
  repo. New run lists open PRs for `pr-grind` and fills the PR URL.
- UI: Settings edits notifications (`ui.json`) and peer review (rounds, default lenses, lens
  prompts, saved as overrides in the data dir), filters the per-repo list, checks every repo's
  GitHub remote and removes a repo from the registry.
- UI: Sessions has Stop and Rerun per row (Rerun on the session page too), a repo filter, search,
  cost totals (today, 7 days, current filters), paging and grouping by issue or PR.
- UI: a card opens in a side drawer. Comment on issues and PRs, close (completed or not planned)
  or reopen an issue, merge a PR (merge commit; warns on failing checks or no approval), read and
  edit a PRD (commits only that file, not pushed) or ask Claude to change it.
- UI: one repo choice for every page, in the URL as `?repo=owner/name`; New run opens on it.

### Fixed

- Delivery cards did not move past Ready in a repo whose PRs target a non-default branch (staging):
  GitHub only links "Closes #n" for the default branch. The poller now also links a PR to its issue
  by a closing keyword in the body or an `issue-<n>-` branch; an issue whose PR merged into staging
  shows only in Merged and autopilot does not start it again.
- Autopilot started more implement-issue sessions every poll (60 s) beyond its cap: live sessions
  were never counted, because a session's `repo` is its checkout path, not `owner/repo`. The
  Delivery board's running count and the start guard had the same blind spot.

- UI: a Planning card in Tasks filed whose issues have no epic now offers **Refine** with the
  unrefined issue numbers. Boards no longer render before the first GitHub fetch, where every
  PRD looked unstarted and offered Create tasks.
- UI: a PRD's ` ```mermaid ` diagrams render (click one for full size), and `[text](url)` links
  and code blocks render instead of showing as raw text.
- UI: the repo switcher is searchable, groups repos by owner, pins the current one and names each
  by its repo, so repos sharing a project name are told apart; it works on mobile too. Dropdowns
  match the app's style, and repo filters show `owner/repo` when two repos share a name.
- UI: a page opened from a scrolled one starts at the top. Wide tables show a shadow where they
  scroll, long session prompts are cut to two lines, and the PRD's "Ask Claude" panel stays in view.

### Changed

- **`/repo-bootstrap` is one PR, one phase per run** (#652): every phase commits to `bootstrap/<issue>`, one draft PR opened by constitution and ready after docs with a per-phase checklist; each run does one phase and ends with the next command and a `BOOTSTRAP: <phase> done #<issue>` last line. The per-phase-PR mode is removed.
- New issues and epics start in Backlog; `/refine-issues` moves an unblocked refined issue to
  Ready. `/implement-issue` stops on an unrefined issue, merges the latest base before marking
  ready and always logs a run over 50 minutes. Findings are reproduced before they are filed.

## 2.2.0 — 2026-10-20

### Added

- **Planning board.** One card per PRD (drafts included), PRD draft → In review → Approved → Tasks
  filed → Refined, with the next step on each card: lens-panel review with progress, Create tasks,
  Refine, Autopilot.
- **Delivery board.** Epic swimlanes × Ready, In progress, Draft PR, In review, Grinding, Merged
  (7 days); blocked cards show their blockers; Start (headless or herdr), Grind, Clean.
- **Autopilot** per epic: starts refined, unblocked issues by priority then number, up to the
  repo's cap (default 2), re-evaluated every poll. `aiw autopilot <owner/repo> <epic> on|off`.
- **Merge-detect cleanup**: a merged issue's clean worktree under `.worktrees/` and its branch are
  removed; otherwise the card is flagged and Clean lists what would be lost.
- **Grind autostart** when a PR turns ready on a repo with auto-grind on; `/pr-grind` refuses a
  draft PR and takes `--channel`.
- **Per-repo settings**: auto-grind, autopilot cap, Slack channel. The global auto-grind toggle is
  gone; its value seeded every registered repo.
- Notifications for a PR turning ready, needs-cleanup, and a panel reaching its cap.

### Changed

- **`/repo-bootstrap` is one PR, one phase per run** (#652): every phase commits to `bootstrap/<issue>`, one draft PR opened by constitution and ready after docs with a per-phase checklist; each run does one phase and ends with the next command and a `BOOTSTRAP: <phase> done #<issue>` last line. The per-phase-PR mode is removed.
- Boards read GitHub with one GraphQL call per repo per poll (60 s, 15 s while CI is pending) and
  pause 10 minutes on a rate limit, showing the last data as stale.
- `/flow` runs dump → create-prd (with the panel) → approval → create-tasks → refine-issues →
  autopilot, confirming at each stage.

## 2.1.0 — 2026-10-20

### Added

- **Peer-review panels as lens sessions.** `POST /api/review` starts one read-only `peer-reviewer`
  session (Opus) per picked lens, linked to a root session. When every lens has reported, the UI
  resumes the root with the round's verdicts; the root revises the artifact in place and the same
  lenses re-review. The panel ends `approved`, or `cap reached` after 5 rounds with the open
  findings kept for you. A failed lens is re-run or dropped with `POST /api/review/<panel>/lens`.
- The custom prompt box's lens picker starts such a panel with that session as root.

### Changed

- **`/repo-bootstrap` is one PR, one phase per run** (#652): every phase commits to `bootstrap/<issue>`, one draft PR opened by constitution and ready after docs with a per-phase checklist; each run does one phase and ends with the next command and a `BOOTSTRAP: <phase> done #<issue>` last line. The per-phase-PR mode is removed.
- Lens verdicts reach the root through the UI (each lens's final message, ending
  `Verdict: approve|changes`, is saved as `round-<n>/<lens>.md`). Built-in messaging between
  `--print` sessions was tested and does not reach a session whose turn has ended.

### Removed

- `aiw peer-review` and verdict validation (quote, stale-sha and schema checks). The
  `peer_review` config keeps only the lenses, their prompts, the offers per kind and the round cap.

## 2.0.0 — 2026-10-20

ai-workflow drops its own issue-to-PR machine and adopts the dev-workflow process:
PRD → tasks → refined issues → `/implement-issue` → `/pr-review`. See
`docs/prds/dev-workflow-replacement.md`.

**Before upgrading:** finish or abandon any in-flight `/run-issue` run. Its PRs and branches stay
on GitHub untouched, but nothing will resume it. After upgrading, reinstall the plugin and remove
the `shahria-skills` local marketplace (`claude plugin marketplace remove shahria-skills`).

### Added

- **dev-workflow skills, imported as-is** from Shahria-skills `0a487c6`: `implement-issue`,
  `verifier-locally`, `docs-updater`, `sync-from-wasensi`, plus `guides/` and `templates/`.
  `create-prd`, `create-tasks`, `refine-issues` and `pr-review` are replaced wholesale by the
  dev-workflow versions (`/pr-review` posting is now opt-in).
- **`peer-reviewer` agent** (read-only, Opus) runs each `/peer-review` lens.
- **First-start cleanup.** `aiw ui` deletes the old run-issue data from the plugin data dir once
  (`runs/`, `pipelines/`, `flows/`, `maintree/`, `locks/`, `gh-status.json`, `titles.json`,
  `grind_requests.json`, `grind_notified.json`) and logs what it removed.

### Changed

- **`/repo-bootstrap` is one PR, one phase per run** (#652): every phase commits to `bootstrap/<issue>`, one draft PR opened by constitution and ready after docs with a per-phase checklist; each run does one phase and ends with the next command and a `BOOTSTRAP: <phase> done #<issue>` last line. The per-phase-PR mode is removed.
- **`/pr-grind` fixes inline:** fix → `/verifier-locally` → commit → reply/resolve → push → CI →
  Slack, with no subagents. One CI fix attempt per head SHA, recorded in its state file.
- **herdr-dispatch** runs `/ai-workflow:implement-issue {n}`; a tab is done when its PR is ready.
- **`/flow`** ends at herdr-dispatch of implement-issue; **`/dump`** loses `--review`.
- **`aiw ui`** is Sessions, New and Settings until the Planning and Delivery boards land. Session
  cleanup moves to `/api/sessions/cleanup` and removes finished sessions' records only.
- The engine-tests pre-commit hook runs the whole suite.

### Removed

- **Commands:** `/run-issue`, `/gh-issue`, `/intake`, `/jira-to-gh`, `/pr-fix-comments`, `/issue-to-pr`.
- **Agents:** every `run-*` station (planner, researcher, sdet, dev, verifier, reviewer, specialist,
  fixer, ci, grinder, lessons, laravel-review), `gh-issue-factchecker` and `ship`.
- **Skills:** `fix-blockers`, `api-hardening-patterns`, `migration-index-reviewer`,
  `resilient-check`, `deployment-readiness`, `frontend-performance-review`,
  `data-migration-strategy`, `upgrade-assistant`.
- **`aiw` verbs:** `init`, `route`, `precheck`, `classify`, `resolve-review`, `skip-review`, `set`,
  `stack`, `worktree`, `maintree`, `pr`, `gitnexus`, `epic`, `refined`, `project-status`, `review`.
  `aiw` keeps `ui`, `paths`, `ask`, `ci`, `threads` and `peer-review`.
- **Engine and ledger:** the routing engine, `run.json`, post-checks, Docker stacks, worktree and
  main-tree modules, the `.run-issue.json` overlay and the engine keys in `config.json`.
- **UI:** the Board, Run, Flow, Dispatch and Pipeline pages, their endpoints, and the PR merge
  endpoint and dialog (the UI never merges).
- **Files:** `definition-of-done.md`, `definition-of-ready.md`, `kanban.html`, `docs/overview.html`
  and its Pages workflow, old ADRs, PRDs, task docs and superpowers plans, and `tasks/lessons.md`.

## 1.12.x — unreleased work, superseded by 2.0.0

### Added

- **`/release-pr`.** Opens or refreshes the staging → master release PR with a summary built from
  the PRs really on staging since the last release, a deploy checklist and env/migration notes,
  then posts the Slack trigger and hands off to `/pr-grind`. Supports partial releases and `--dry-run`.
- **Merge PRs from the UI.** Squash and merge from the PR popup or a pipeline's merge order, after
  a confirm that lists what isn't ready (CI, review, conflicts, draft, unmerged PRs before it).
- **No repo yet: start from an idea.** New run and Flow can run create-prd, dump, intake or a custom
  prompt in the notes vault, with the vault folder suggested from your text (keywords, or Claude
  on request) and confirmed by the session. Create repo turns an approved idea into a local git
  repo with its PRD and README, registered as `local/<name>` until it gets a GitHub remote.
- **Token use beside every cost.** Board cards and today's total, Sessions, the run page and
  transcripts show tokens next to the cost; hover for in/cached/out. Older sessions are filled in
  once from their transcripts.
- **Worklog date picker.** New run picks today, yesterday, a day or a date range for `worklog`;
  a range starts one run per day (up to 31), 3 at a time with the rest queued on the server.
- **Board filters.** Status, PR, CI and grind filters with live counts, combinable, shown as
  removable chips, and remembered.
- **Dispatch pipeline page.** A merged PR shows as Merged even when the pipeline's own attempt
  failed; rows filter by attention, progress, open PRs or merged; the merge order shows each PR's
  state, CI and review and marks the one to merge next.
- **Clean up dialog.** Runs grouped by repo with titles, a box per repo, and Safe / Merged PRs /
  None quick picks; nothing with unsaved work is ever ticked in bulk.
- **One repo picker everywhere.** New run, Flow, Dispatch and the Board filter now pick a repo the
  same way: a searchable list with recently used repos first, each repo shown by its own name, its
  owner and its path (so two repos sharing a project name no longer look alike), keyboard support,
  and, where any checkout is allowed, a typed path or the folder dialog. It replaces a text
  combobox with a separate folder button, a plain dropdown on Dispatch, and one on the Board.
- **New run lists the repo's open issues and PRs.** Pick one instead of looking up its number;
  typing filters by number, title words or labels. Commands are grouped with a one-line
  description each, and the last one used is remembered.
- **Board filter and "need you" toggle.** Filter cards by `#N`, title or repo; click the
  need-you count to show only the runs waiting on you. Cards show how long ago they changed.
- **Flow in the command palette** (`g f`).

- **Skills improve themselves with approval.** Every skill under `skills/` now ends with a
  `## Self-improve` pointer to `self-improve.md`. During a run the skill notes what its
  instructions got wrong or left out. When the run finishes it asks once which fixes to write
  back to its SKILL.md. Unattended runs (headless, `/run-issue`, `/pr-grind`, `/flow`, herdr)
  never ask: they append to `~/.claude/skills/_shared/pending-improvements.md` instead.
- **Peer review picker in `aiw ui`.** New run's named form (for `create-prd`, `intake`, `dump` and
  `gh-issue`), its Custom command form, and the Flow's PRD step each have a Peer review box. Tick
  it to pick the reviewers the command offers; critical starts ticked. A custom prompt is asked to
  run `/peer-review` when it's done, against a fresh review dir holding the prompt verbatim. The
  session page then shows whether the review approved, reached the round cap, didn't finish, or never
  ran, read from the review's own rounds, not from what the session claims.
- **`/peer-review` and `--review` on `/intake`, `/dump` and `/gh-issue`.** The reviewer panel
  `/create-prd --review` uses is now the `peer-review` skill. Run it on its own after any work and it
  reviews the change (the diff since a point you choose, plus the final answer) against what you
  asked. The diff never includes secret-like files, binaries or lockfiles. `/intake`, `/dump` and
  `/gh-issue` review their draft before anything is saved or filed (`/gh-issue` reviews its
  issue body, then its factchecker still runs). A programmatic
  call (`/gh-issue` and `/run-issue` running `/intake --whole`) never reviews. The reviewers run on
  Opus, in subagents and in herdr tabs (checked: the tab's init event reports `claude-opus-5-5`);
  `/run-issue`'s code-review specialists stay on Sonnet.
- **`/create-prd --review [<lens,lens>]`: a reviewer panel before the review gate.** You pick the
  lenses from a pool of seven: critical (completeness), CEO (product value), CTO (feasibility
  against the repo), security, QA (testability), UX (design) and performance. Bare `--review`
  runs critical alone. Every picked lens must approve. They review the draft in parallel as
  `run-specialist` in its peer review mode, and `aiw peer-review` checks every verdict and decides
  each round: blockers are fixed and every finding gets a recorded disposition, product decisions
  are asked of you and written into `## Decisions`, a finding you dismissed that its lens raises
  again is yours to settle, and after the round budget you choose to accept known gaps, run one
  more round, or stop.
  `--herdr` (terminal) opens one herdr tab per reviewer that you can watch and talk to, started
  as `claude --agent ai-workflow:run-specialist` with Write/Edit disallowed. Checked: the tab has
  no file-editing tools, but its shell is not narrowed (a probe's `touch` ran), so shell commands
  follow your normal permissions; it is not read-only. Code search works through `rg`. Tabs
  are reused across rounds, so a reviewer remembers its earlier rounds. In `aiw ui`, a **Peer
  review** checkbox on the Flow's PRD step and on New run for `create-prd` adds `--review` (critical;
  the UI always uses subagents).
- **`aiw peer-review new|next|verdict|diff`.** The engine for peer review. `new <kind>` makes a
  fresh review directory for one run (never reused, so a second review of the same PRD starts at
  round 1). `next` opens and decides rounds for a panel picked per run from the lenses the kind
  offers (`peer_review` in `config.json`: the lens pool, two severity rubrics, `doc` and `change`,
  and per-kind offers for `create-prd`, `intake`, `dump`, `gh-issue` and `custom`). `verdict` refuses a
  finding that neither quotes the artifact nor names one of its headings, a stale artifact hash,
  an old round, more than 8 findings, or a blocker/major that doesn't say whether it re-raises a
  prior finding. `next` decides: every picked lens blocks, a finding that needs a product decision
  or re-raises one you dismissed goes to you, and a spent round budget asks you (`--more` opens
  exactly one more round), never auto-approving. `diff --since <sha|@{u}>` prints the change to
  review, with secret-like files (tracked or not), binaries and lockfiles dropped and named, and
  a long diff capped with a note. The other commands and custom prompts get `--review` in later
  releases. A PRD review that was mid-round under the earlier `aiw prd-review` can't resume:
  start the review again.
- **`/fix-blockers <parent>`.** Previews and then sets an epic's GitHub "blocked by" relations
  through `aiw epic blockers`, after one confirmation. A parent filed on another machine is split
  first, as Epic mode does.
- **`aiw epic blockers <epic_dir> [--dry-run]`.** Sets GitHub's native "blocked by" relation
  between an epic's children, derived from their `Depends on:` lines (the single source,
  ADR 0003). It checks the dependency graph first, writes only the edges GitHub lacks (so a
  re-run writes nothing twice), and reports, never deletes, an edge that no `Depends on:` line
  names. `--dry-run` prints the edges it would add.
- **`/create-tasks` and `/refine-issues`.** `/create-tasks` splits an Approved PRD into a saved
  list of one-PR tasks (`docs/tasks/<slug>.md`) with Area, Parallel, Waves and Shared files,
  without filing anything. `/refine-issues` files that list as `refined` sub-issues of the PRD's
  epics (ADR 0004).
- **Full test suite on push and in CI.** `run-engine/run_tests.sh` runs every
  `run-engine/test_*.py`. `pre-commit install` now also installs a pre-push hook that runs it,
  and a `Tests` GitHub Actions job runs it on pull requests and on pushes to `master`. Fixes the
  stale `test_ui_events.py` assertions this exposed (`flow_id`, the `usage`/`afk` keys).
- **Flow history.** Every flow is saved on the aiw server at `#/flow/<id>`. **Flows** lists
  earlier ones with their step and last activity, archive hides one, and **New flow** starts
  another. A draft is saved as you type. Past `/dump`, `/prd` and `/gh-issue` sessions are
  imported into flows once, and "Continue in Flow" on a session opens its own flow.
- **Step output beside the steps.** With no question waiting, the Flow page shows the selected
  step's `Dump.md` or `PRD.md` (read-only, from the new **Notes vault** setting) or one row per
  issue as `/gh-issue` creates, fact-checks and fixes it. Click a done step to show its output.
- **Flow auto mode.** Sessions started from Flow ask only grilling questions: `/create-prd`'s, which
  now cover acceptance criteria, priority, users and corner cases and run until the PRD has no open
  questions, and `/gh-issue`'s on a bug's or task's open questions. `/dump` picks the folder itself.
  `/gh-issue` assigns you and `/refine-issues` leaves them unassigned; both add issues to the repo's
  linked project and fill its fields without asking.
- **Questions answered in Flow.** A step's question opens beside the steps (in the step on narrow
  screens), and answering from the Answer page returns to the flow or the session.

### Changed

- **`/repo-bootstrap` is one PR, one phase per run** (#652): every phase commits to `bootstrap/<issue>`, one draft PR opened by constitution and ready after docs with a per-phase checklist; each run does one phase and ends with the next command and a `BOOTSTRAP: <phase> done #<issue>` last line. The per-phase-PR mode is removed.
- **`/prd` is now `/create-prd`, and planning runs `/create-prd` → `/create-tasks` → `/refine-issues` (ADR 0004).**
  Breaking: a hard rename with no `/prd` alias, and PRDs move from `docs/prd/` to
  `docs/prds/<slug>.md`. A PRD has a technical design (contracts allowed, code not), its epics
  and a change log, and a status of Draft, In review or Approved. `/create-prd approve <prd>`
  sets Approved and files one epic per `## Epics` entry, labelled `epic` + `prd-<slug>`.
  `/create-tasks` works only from an Approved PRD and adds Area, Parallel, Waves and Shared
  files. `/refine-issues` files each task as a `refined` sub-issue of its epic with
  `Depends on: #n` and blocked-by links, then runs `aiw epic split` per epic. `/gh-issue` and
  `/jira-to-gh` now file exactly one issue: input that splits into 2 or more tasks creates
  nothing and ends `→ next: /create-prd <input>`, and `/run-issue` Preflight stops there too.
  `/dump` sends bugs to `/gh-issue <Bugs.md>`, which files the one bug you pick (newest first).
  `/create-prd` offers to `git mv` a legacy `docs/prd/<slug>.md` to `docs/prds/`. The peer-review
  kind `prd` is now `create-prd`; an in-flight `prd` review stops with a clear error.
  `aiw refined` also rejects a `<placeholder>` Test root or Base branch. Old `/prd` sessions in
  `aiw ui` still map to the PRD step.
- **Bare `/create-prd --review` runs the critical reviewer alone.** It used to run critical, CEO, CTO
  and security, with only critical able to hold the PRD. Pick more lenses with
  `--review critical,ceo,cto,security`; every picked lens now has to approve.
- **The Guided Flow has five steps.** `/flow` and the `aiw ui` Flow page run dump → PRD
  (`/create-prd`) → tasks (`/create-tasks`) → issues (`/refine-issues`) → dispatch. The `→ next:`
  lines follow: `/create-prd` hands off to `/create-tasks`, `/create-tasks` to `/refine-issues`,
  and `/refine-issues` hands an epic to `herdr-dispatch`. There is no Blockers step:
  `/refine-issues` sets the blocked-by links itself, and on an older `gh` its report says to run
  `/fix-blockers <epic>` first, which stays a standalone command. A bug's dump goes to
  `/gh-issue`, which files one issue for `herdr-dispatch`.
  A flow saved mid-way at the old Issues step with a PRD now resumes at Tasks, and one saved at
  the old Blockers step resumes at Issues (a re-run matches the existing issues). The new commands
  can be started from the UI and are never auto-answered in AFK mode.
- **Epics are linked and blocked natively (ADR 0003).** An epic's children are linked as
  sub-issues by `aiw epic split`, which also writes the `epic.json` Epic mode reads, and their
  `Depends on:` lines become GitHub blocked-by relations. `/create-prd approve` files the epics
  and `/refine-issues` files their children (ADR 0004). `/run-issue` refuses an epic labelled
  `epic` and `prd-<slug>` that has no sub-issues; a team's own `epic` label runs as before.
- **Grinding is opt-in.** `/run-issue` runs phase 10 (`pr-grind`) only with `--grind`;
  without it the run ends at the Gate 2 handback. Breaking: a run that used to grind by
  default no longer does. `--no-grind` still parses but does nothing. `herdr-dispatch` and
  `/flow` pass `--grind` through. This also fixes `aiw ui` runs in a worktree, which grinded
  in-session even with auto-grind off; the UI's auto-grind setting is now the only switch
  for them.

- **`/dump` writes a problem statement.** A new feature, change request or bug is filed as
  Problem / Who / Evidence / Expected / Open questions, taken only from the input, followed by
  the raw text verbatim. Bugs in `Bugs.md` get the same block instead of a one-line bullet.
  Tasks, meeting notes and unclassifiable input are still filed verbatim.
- **The repo PRD is canonical.** `/create-prd` saves to `docs/prds/<slug>.md` and the Obsidian
  vault by default (`--to local,obsidian`), and the vault copy is a mirror of the repo copy.
  The two are linked at save time (a `**Mirror:**` line in the repo copy, a `canonical`
  property on the vault note). Outside a git repo it writes the vault only. New
  `/create-prd --update <prd> <decisions>` appends decisions made later to `## Decisions`, resolves
  the open questions they answer, reports every edited requirement as before → after, and
  mirrors the edit; a vault PRD with no canonical copy is updated alone.
- **Docs restructure.** `README.md` is now a short link hub. The agent setup protocol moved to
  `docs/INSTALL.md`, and commands, the `aiw` CLI, `aiw ui`, state and layout moved to
  `docs/REFERENCE.md`. `CLAUDE.md` is a stable, agent-first overview of the project that
  changes only on explicit request, and `AGENTS.md` is a symlink to it. New `CONTRIBUTING.md`
  says which docs to update. A pre-commit hook warns, without blocking, when `CLAUDE.md`
  changes. `docs/agents/` was removed.
- **`aiw gitnexus` no longer writes into CLAUDE.md/AGENTS.md.** `analyze` passes
  `--skip-agents-md` (gitnexus 1.5.0+), and its npx fallback pins `gitnexus@latest`. Repos
  indexed by a run no longer get the GitNexus block added to their agent docs; a block
  already there stays as-is and is no longer refreshed, so its symbol counts go stale.
- **Pre-commit hooks.** File hygiene, gitleaks, ruff (lint and format, via the repo's own
  `ruff.toml`), shellcheck, and `test_engine.py` on engine changes, all blocking. The
  Python sources were reformatted once (listed in `.git-blame-ignore-revs`), and the
  existing lint findings were fixed.

### Removed

- **`aiw project-board` and `aiw dispatch plan`.** Nothing in the plugin calls either
  subcommand any more: the flat task list stopped creating epic boards in 1.9.0, and the
  `aiw ui` dispatch page uses `dispatch.py` directly. Breaking: scripts that call
  `aiw project-board` or `aiw dispatch plan` must stop.
- **Stale design docs:** the epic-decomposition spec and plan, the intake-command spec and
  plan, and the finished `docs/tasks/gh-issue-flat-task-list.md`.

### Fixed

- **Board status stays under GitHub's rate limit.** Cards refetch every 5 min (45 s only while a
  PR's CI runs), stop for good once the PR is merged or the issue is deleted (shown as "issue
  deleted"), survive a server restart from a cache on disk, and pause all fetches for 10 min when
  GitHub reports the rate limit spent.
- **A question no longer locks for minutes.** When a session asked a question but a background
  task kept `claude` alive, it is ended 30 s later so the answer form unlocks.
- **Default-mode dev no longer escalates.** A test that already failed on the base branch made dev
  escalate, which left a draft PR and a failed pipeline item. Dev now always reports passed with what
  is unmet in its summary; the post-check and the final report carry it, and `aiw route` rejects a
  dev bounce or escalate there.
- **Retry a blocked pipeline item.** A row skipped because its blocker failed now has Retry: a
  blocker whose PR you merged by hand counts as done, so the item starts.
- **Flow lost a new request routed into an approved feature.** Dump filed it as a task, Issues sent
  it back to PRD, and create-prd/create-tasks found the old approved PRD and task list unchanged.
  Now Flow's PRD step adds the request to an approved PRD (`create-prd --update`, which may add a
  new FR) and moves on to Tasks, which adds only the new tasks. A skipped PRD/Tasks step says why
  (Dump filed it as a task) and offers **Write a PRD instead**; a quoted `→ next:` path no longer
  keeps its quotes.
- **Flow's Issues pane showed a phantom "#42 Untitled issue"**: it took `gh issue create --help`
  for a create and its help text's example URL for a new issue. Help runs no longer count, and only
  issue URLs of the flow's own repo do.
- **Flow stalled after Create repo**: Tasks needs a GitHub repo for the epic, but a local repo let it
  run and fail with "Unexpected next command". Flow now offers **Publish to GitHub** (first commit,
  `gh repo create`, re-registered) before Tasks; a step that stops itself shows its own reason; the
  PRD pane shows the vault copy once the PRD lives in a repo.
- **Create repo failed over the tailnet** ("folder picker is only available locally on macOS"):
  the parent folder can now be typed or picked from where your repos live; Choose… shows only
  where the Mac's folder dialog can open.
- **Run page overflowed sideways** when a main-tree run was blocked: the chip carried the whole pause
  reason on one line. The chip now says only "Main tree: blocked" (the reason is in its tooltip and
  the grind panel). "Skip CI for now" no longer shows for a grind paused by a "stall check".
- **Repo picker focus, Board card animation and the Flows list's arrow keys did nothing**: they used
  `this.base`, which the vendored preact 11 no longer sets. They use refs now.
- **Board cards under a guessed repo.** A run dir like `masnun-siam-typevocal-issue-70` with no PR
  link showed as `masnun/siam-typevocal` with no title; registered checkouts now resolve it.
- **Titles stuck on "(title unavailable)".** A failed `gh` fetch (a rate limit, say) is retried
  after 5 minutes instead of cached until restart, and never replaces a title already known.
- **Run output put a list above its heading** when the list started right under a paragraph line
  (`**What you need to do:**` then `- …`).
- **Run page said "running" for a run queued behind another in the main checkout**; it says
  "queued" now. Board cards keep their Issue/PR links inside the card, and a missing title no
  longer repeats `#N`. The header says "No questions waiting" so it no longer reads as
  contradicting the board's need-you count. New run fits on one header row on a phone.
- **`test_ui_static.py` skipped most of its checks.** The per-view suites only ran with
  `--view`, which CI never passed, and seven of nine had gone stale. The plain run now runs them all.
- **`aiw gitnexus` no longer installs gitnexus skills into the repo.** `analyze` now passes
  `--skip-skills` alongside `--skip-agents-md`, so it stops writing `.claude/skills/gitnexus/`.
- **A waiting session's answer form no longer gets stuck.** A headless session that scheduled a
  wakeup stayed alive after `aiw ask`, so every Submit got "session process is still running". The
  headless prompt now forbids ScheduleWakeup, and the answer form disables Submit with a note while
  the process runs, then unlocks itself when it exits. A UI restart while such a process is alive
  now watches it and stamps `ended_at` when it exits; before, nothing did, and the form stayed
  locked for good.
- **The flow.js stepper checks run again.** They sat in a `test_ui_static.py --view` block that
  nothing runs (and that fails earlier on unrelated stale checks); they now run in its default
  mode, so in the pre-push hook and CI.
- **AFK failed-run retries on Python 3.10.** `ui_afk` parsed the runner's `…Z` timestamps
  with `datetime.fromisoformat`, which rejects a trailing `Z` before 3.11, so on 3.10 the
  retry never fired. It now uses the same tolerant parser as `review.py`.
- **`aiw refined` reads a linked `Test root:` / `Base branch:`.** A value written as a markdown
  link (`[tests/](https://…)`) used to become the test root verbatim; it now takes the link
  text. A new contract test pins the `/gh-issue` body format to what `aiw refined` parses.

## 1.12.0 — 2026-10-09

### Added

- **Issue and PR popups in `aiw ui`.** Clicking an issue or PR link opens an overview
  instead of a new tab: state, labels, people and the GitHub-rendered body and comments
  for an issue; description, conversation with review verdicts, changed files with inline
  diffs, commits and CI checks for a PR. "Open on GitHub" is in the footer, and
  Cmd/Ctrl-click still opens GitHub directly. Served by `/api/issues/...` and
  `/api/pulls/...`, read-only through `gh`.

### Changed

- **`/repo-bootstrap` is one PR, one phase per run** (#652): every phase commits to `bootstrap/<issue>`, one draft PR opened by constitution and ready after docs with a per-phase checklist; each run does one phase and ends with the next command and a `BOOTSTRAP: <phase> done #<issue>` last line. The per-phase-PR mode is removed.
- **`/prd` default destination is Obsidian.** `--to` now defaults to `obsidian` instead of `local`, and `/prd` fills the seeded `PRD.md` that `/dump` leaves in a feature folder (`status: seed`, set to `draft` once filled). `local` and `wiki` are written only when named in `--to`.
- **Run page.** The header groups the title, status chips and actions, the stations list
  is compact and sticky, assistant output renders as markdown in a readable measure, only
  the latest 80 events render until "Show earlier events", and "Jump to latest" appears
  when you scroll up. On phones the page scrolls instead of the log.
- **Flow page.** The steps sit on a vertical rail that fills as each one hands off; only
  the current step opens into a panel, and later steps are one line saying what they
  produce. Buttons name the outcome ("File the idea", "Write the PRD", "Create the
  issues"), errors sit under their field, and "Start over" asks before clearing progress.
- **Flow uses the New run repo picker.** Search repos, type an absolute path or browse
  for a folder; the combobox is now shared by both pages.

### Fixed

- Dispatch's "Add" button no longer wraps to "Ad / d".

## 1.11.0 — 2026-10-07

### Added

- **The `aiw ui` Dispatch tab runs `/run-issue` over a batch of issues.** Paste a GitHub
  issue search URL, issue URLs, issue numbers or an epic number; the UI lists the issues
  with their readiness, dependencies and skip reasons, and starts a pipeline from the
  ones you tick. A pipeline runs in parallel (up to N at once) or one at a time, always
  honouring `Depends on: #n` lines, and skips the dependents of an issue that fails or is
  stopped. Several pipelines can run at once. The detail page shows each ticket's
  station, session status, PR and CI, with pause, resume, stop, retry, skip, add-issues
  and a merge-order list. Pipelines survive a UI restart.
- **A new look for `aiw ui`, built from the design canvas (#175).** Board summary strip
  and cards that glide between columns, run detail with the issue title, PR link and
  station stepper, a redesigned answer view, new-run form with a searchable repo picker
  and folder browse, sessions table, an in-app transcript viewer, toasts, keyboard
  shortcuts and a Cmd/Ctrl+K command palette.
- **Settings page with named Claude commands.** Pick which account a run uses; a run
  that hits its usage limit shows as limited, resumes by itself when the limit resets,
  or can be resumed on another account. Header chips show limited and near-limit
  accounts.
- **`aiw ui` serves itself on your tailnet when Tailscale is running.** It runs
  `tailscale serve` to `https://<node>.<tailnet>.ts.net` (tailnet-only, never funnel),
  limited to the node owner by the `Tailscale-User-Login` header, and removes the handler
  when it exits. A port that already has a handler is never overwritten.
  `--tailscale-port` picks 443 (default), 8443 or 10000; `--no-tailscale` turns it off.
- **ntfy pushes are richer.** An emoji icon and run/repo/issue tags, a title naming the
  issue, a body that leads with the question or error, and an Answer / Open run button
  when `public_url` is set. Auth is a Bearer token or `user` + `password`, and pushes
  send their own User-Agent so Cloudflare's Browser Integrity Check lets them through.
- **Dispatch asks where a repo's clone is instead of failing.** A repo aiw has not seen
  (for example one pasted as a search URL) shows a "Where is owner/repo on this Mac?" step with
  clones found on disk, a path field and Browse; the pick is remembered and the preview re-runs.
  Settings has a Repos panel with "Find my repos", which registers every clone with a GitHub
  origin under the folders you list. Clones whose remote is `ssh://git@ssh.github.com:443/...`
  are recognised now (they were skipped before).
- **`/worklog` includes non-GitHub work.** It reads the daily note's `## Log` section
  (meetings, support, reviews) and adds those items to `## Worklog` under their project,
  or `Other`, as `done`. Plans and deferred items are skipped, and a day with only log
  items still gets a worklog.
- **GitHub status on the board and run detail.** Issue state, PR link, review approval
  and CI, read-only and cached.
- **Clean up finished runs from the UI.** Removes a run's worktree, run directory and
  sessions, and the local branch of a finished run; live sessions and escalated runs are
  never offered.

### Fixed

- **The Board loads instantly (#175).** Issue titles are fetched off the request thread,
  junk repos are skipped, and polling times out instead of hanging.
- **Sessions that outlived the UI are re-attached on start.** `reconcile()` existed but
  was never called, so a restart left their status stuck on running.

## 1.10.0 — 2026-10-07

### Added

- **`aiw ui` is a local web UI for driving and watching runs (#107-#114, #121-#129).**
  It serves a live Board of every run, a session list, a run-detail view with the
  streamed events, a session history view, and a new-run form for any command (or a
  custom prompt) that starts a detached headless `claude` session. A session that
  stops at a gate or an interview round shows a waiting badge, a browser notification
  and an answer view; answering resumes it, with a fallback to the ledger when the
  session id is lost. Sessions are re-attached after a UI restart. The server only
  answers requests whose Host and Origin are local (`--allow-host` adds more).
- **Optional ntfy pushes when a session is waiting, done or failed (#121).** Configure
  them in the UI JSON config.
- **`aiw ask` records a gate or interview question for the UI instead of blocking on
  a prompt (#118, #128).** `/run-issue` gates and the `/prd`, `/intake`, `/dump`,
  `/worklog` and `/gh-issue` interviews go through it when a UI session is running.
- **`/pr-grind` can run headless (#127).** `poll-reviews.sh once` does a single poll,
  and the UI ticks it to re-enter the grind loop.

### Changed

- **`/repo-bootstrap` is one PR, one phase per run** (#652): every phase commits to `bootstrap/<issue>`, one draft PR opened by constitution and ready after docs with a per-phase checklist; each run does one phase and ends with the next command and a `BOOTSTRAP: <phase> done #<issue>` last line. The per-phase-PR mode is removed.
- **`aiw kanban serve` and `kanban.py` are gone (#108).** Use `aiw ui`.
- **The docs describe the Session term and the `aiw ui` server (#130).** Two ADRs
  record the headless question pause (#103) and the pr-grind re-entry (#104).

## 1.9.0 — 2026-10-02

### Added

- **`/prd` turns a rough requirement into a reviewed PRD (#100).** It scans the codebase
  first, interviews you with the `grilling` skill, shows the full draft for approval, then
  saves it to `docs/prd/<slug>.md`, the Obsidian vault and/or the GitHub wiki. Run
  `/gh-issue` on the saved PRD to file its tasks.

### Changed

- **`/repo-bootstrap` is one PR, one phase per run** (#652): every phase commits to `bootstrap/<issue>`, one draft PR opened by constitution and ready after docs with a per-phase checklist; each run does one phase and ends with the next command and a `BOOTSTRAP: <phase> done #<issue>` last line. The per-phase-PR mode is removed.
- **`/gh-issue` and `/jira-to-gh` file flat issues instead of a parent plus children (#78,
  #79, #80, #81, #83, #84).** Decomposition applies a size rubric (one layer-scoped
  deliverable, 3 or fewer production files, 1-4 acceptance criteria, one verify command)
  and asks "Create as shown" or "Let me edit the list". Two or more tasks save the
  approved list to `docs/tasks/<slug>.md` (optionally also Obsidian or the GitHub wiki),
  then create one standalone issue per task, labelled `prd-<slug>` and ordered by `Depends
  on: #n` lines, writing each number back into the list. A partial failure offers "Retry
  the missing ones" or "Stop here", and "Resume this list" picks a saved list back up
  without duplicating issues. `4-EPIC` and `5-EPIC` are gone.
- **`/gh-issue` asks the assignee and project questions once per run, factchecks every
  created issue, and returns the ordered list of issue URLs (#82).**
- **`/run-issue` lists the issues and stops when `/gh-issue` returns two or more (#85).**
  Run `/run-issue <n>` on each, dependencies first. Epic mode is unchanged for epics that
  already exist.

## 1.8.0 — 2026-09-30

### Added

- **`/gh-issue` restructures issue bodies to What / Why / How and applies the `refined`
  label (#71, #74).** `/jira-to-gh` follows the same body shape and label, including the
  epic parent step.
- **`/jira-to-gh` decomposes Jira tickets into a parent issue plus sub-issues (#42, #50).**

### Fixed

- **CI-red rails now have a fallback when `gh run rerun` is denied (#29, #34).** `run-ci`
  and `pr-grind` retrigger with an empty commit, and document the rerun-denied
  marker-match terminal state.

## 1.6.1 — 2026-09-26

### Added

- **Agent-facing domain docs**: `CONTEXT.md` (domain glossary), `docs/agents/issue-tracker.md`
  (GitHub-issues-as-tracker conventions), `docs/agents/triage-labels.md` (canonical triage
  label mapping), and `docs/agents/domain.md` (how skills should consume this repo's domain
  docs when exploring). CLAUDE.md now points at all three under a new "Agent skills" section.
- `.gitignore` now excludes `.gstack/`.

## 1.6.0 — 2026-09-24

### Added

- **`/gh-issue` always decomposes a request into a task list before creating any issue
  (#38).** Step 3.5 is no longer a size-triggered "Epic check" — it runs unconditionally
  after grilling, presents the task list via a three-choice `AskUserQuestion` (create /
  edit / file as one issue), and routes on the approved list's task count: 1 task files a
  single issue as before, 2+ go to `4-EPIC`. More than ~8 tasks proposes a coarser split
  instead of creating anything. `4-EPIC`'s child-creation loop now handles partial
  failure explicitly: a failed `gh issue create` at child *k* of *N* stops the loop,
  reports created-vs-missing issues by number/title, and offers retry-missing or
  stop-here — nothing already created is ever auto-closed.
- **Every issue `/gh-issue` creates now requires an `Implementation Guide` section
  (#39).** Ordered steps, exact `path:line`/symbol references, an existing pattern to
  copy (or "net-new"), a verify command, and a one-line done-check — required on every
  non-parent issue. `run-planner` reads it as its starting point instead of re-deriving
  an approach from scratch, and `gh-issue-factchecker` verifies its `path:line`/symbol
  claims the same way it already verifies "Context / Affected Code".
- **`aiw epic split` now writes the parent epic's `## Tasks` checklist (#40).** After
  validating the child DAG, it fetches each child's title and idempotently splices a
  dependency-ordered checklist into the parent body — replacing an existing section
  rather than duplicating it, fence-aware so a `## Tasks`-looking line inside a quoted
  code block in the BRD doesn't corrupt the body.
- **`/intake`'s BRD adapter can pass a multi-outcome document through whole (#41).** A
  caller-only `--whole` flag (passed by `/gh-issue` and `/run-issue`, never typed by a
  human) skips the old "pick one candidate" narrowing and instead lists every outcome as
  its own Summary/Scope/Acceptance-criteria block, so `/gh-issue`'s own decomposition
  (#38) has every outcome to work with instead of just one.
- **`/jira-to-gh` decomposes multi-outcome Jira tickets into a parent plus sub-issues
  (#42).** Mirrors `/gh-issue`'s decomposition and `4-EPIC` pattern (including the
  Implementation Guide requirement and partial-failure retry/stop handling) instead of
  always collapsing a ticket into one flat issue. Attachments and the `## Original Jira`
  section go to the parent (or the single issue) only, never duplicated onto children.

## 1.5.0 — 2026-09-23

### Added

- **`/gh-issue` and `/jira-to-gh` auto-apply a `lean` label at intake (#15).** A
  smallness heuristic (one shippable outcome, ~1-2 files, no new dependency, no new
  public API, none of auth/authz, migrations, payment, or a public API contract)
  idempotently labels an issue `lean` so `/run-issue` can pick the lean 5-station
  roster without a human remembering `--lean`. `/run-issue` gains an explicit `--full`
  flag; precedence is both flags → full, `--full` alone → full, `--lean` alone → lean,
  neither → the issue's label if present else full. Epic parents are never labelled;
  each child is judged independently, and `epic init --lean-children <n>,<n>` lets
  individual children opt into lean without losing their DAG wiring.
- **`.run-issue.json` can now pin `test_cmd` per repo (#27).** A top-level `test_cmd`
  override in the overlay is used verbatim by `aiw stack up` in place of the derived
  command, and survives every degraded stack path (lock-held, up-failed, no-app-service)
  instead of being silently overwritten with `""`. `run_suite` now also treats
  `stack=failed` as unconditionally unrunnable regardless of a leftover `test_cmd`,
  closing a false-RED hole a preserved override would otherwise open.
- **Post-check suite timeout is configurable per repo (#25).** The hardcoded 900s
  timeout on the sdet/dev post-check's test run is now `checks.suite_timeout` in
  `.run-issue.json`, validated (positive int, bool excluded) and falling back to 900
  with a stderr warning on any invalid value.
- **`aiw pr open`'s push timeout is configurable per repo (#28).** A new `pr.push_timeout`
  key (default 600s) follows the same validate-and-fallback pattern as `suite_timeout`.
  A genuine timeout (return code 124) now reports a distinct message naming the
  effective timeout and noting the push may still be running, instead of a generic
  "push failed:" with no context.

### Fixed

- **`pr-grind` Step 1 discarded real review findings to a same-commit rubber-stamp
  review (#24).** A reviewer bot posting a substantive `COMMENTED` review followed
  seconds later by a zero-comment `APPROVED` rubber stamp on the identical commit made
  "take the newest only" silently reinstate the exact bug the round was meant to catch.
  A new `run-engine/review.py` (`aiw review pick`) prefers the comment-carrying review
  within a 60s same-commit window regardless of posting order; different-commit rounds
  and genuine multi-comment re-reviews still resolve to newest, unchanged.
- **Exit-6 (test-ownership violation) recovery could be blocked by a git safety hook
  (#26).** The documented `git checkout <sdet_sha> -- <paths>` recovery is now paired
  with a fallback — `git show <sdet_sha>:<path> > /tmp/<file>` plus a plain file write —
  for environments where a discard-pattern command is blocked even scoped to one file.
  Mirrored in the engine's own exit-6 stderr message, not just the docs.

## 1.4.1 — 2026-09-22

### Fixed

- **Parallel `/run-issue` runs could collide on Docker test stacks (#21).** `-p
  runissue-<issue>` namespaced container names only, never published host ports, and
  had no repo component — so the same issue number in two different repos shared one
  Compose project (a `down -v` from either tore down the other's containers/volumes),
  and two different issues in the same repo with any `ports:` mapping collided on the
  host port. `stack.py` now keys the Compose project (and its lock) on both repo and
  issue (`runissue-<repo-slug>-<digest>-<issue>`), force-publishes every declared port
  to an OS-chosen one, and reads the real port back via `docker compose port` after
  `up --wait`. The host-wide lock is now per-project: a live lock on an unrelated
  project never blocks a new run, while a second `up` on the *same* project still
  serializes as before. Also closes a lock/teardown leak in the "no app service
  identified" branch, and raises `epic.max_stacks`'s default (1 → 3) now that the
  port-collision blocker forcing it to 1 is gone.

## 1.4.0 — 2026-09-22

### Added

- **`aiw dispatch plan`: batch roster resolution and DoR pre-screen (#14).** Resolves a
  batch of issues to run from `--issues`, `--query`, `--project`+`--status`, or `--epic`,
  then mechanically pre-screens each for Definition-of-Ready gaps, skip reasons (already
  has an open PR, already closed), and lane mode — before any of them reach `/run-issue`.
  Adds an atomic `checkouts.json` registry, mirroring `epic.py`'s file shape, so concurrent
  dispatches share one source of truth for which repo checkout each issue runs against.
- **Per-host stack lock (#14).** `aiw stack up`/`down` now serialize against each other
  across separate OS processes, not just threads within one interpreter, using an atomic
  `O_CREAT|O_EXCL` lock file. Staleness reclaim is ledger-status-based (`done`/`escalated`
  reclaim immediately; a still-`running` holder is bounded by `LOCK_GRACE`), not a bare
  timer, so a lock abandoned by a finished run no longer outlives every contender's
  `--lock-timeout`. `stack up` gained a `--lock-timeout` flag (default 900s) and degrades
  to `stack=failed` + `tests_unverified` on timeout instead of racing another run's writes.

## 1.3.1 — 2026-09-22

### Fixed

- **`/gh-issue`'s and `/intake`'s HARD RULE blocks silently halted `/run-issue`.**
  Both rules were unbounded, so once read into context they were treated as binding
  for the rest of `/run-issue`'s turn — silently halting the pipeline right after an
  intake-routed issue was filed, instead of continuing on to Preflight step 3 and
  Gate 1 as designed. Both rules are now explicitly scoped to their own skill's
  steps, with an explicit handback stated both where the rule is defined and at
  `/run-issue`'s call site.

## 1.3.0 — 2026-09-21

### Added

- **Content-oriented intake.** `/run-issue` and `/gh-issue` now accept a Sentry issue
  link, a BRD file path, an Obsidian vault note, or free text — not only a GitHub issue
  number/URL. A new `/intake` command normalizes any of those into an issue brief
  (auto-detected, no flags); `/gh-issue` files it as a real issue exactly as it would a
  hand-written description, and `/run-issue` runs `/intake` then `/gh-issue` automatically
  when its argument isn't already an issue reference. The GitHub issue stays the single
  source of truth — nothing downstream of Preflight step 1 changed. A BRD describing more
  than one independently-shippable outcome prompts once to pick which one to run now; every
  other source never prompts.

## 1.2.1 — 2026-09-21

### Changed

- **`/repo-bootstrap` is one PR, one phase per run** (#652): every phase commits to `bootstrap/<issue>`, one draft PR opened by constitution and ready after docs with a per-phase checklist; each run does one phase and ends with the next command and a `BOOTSTRAP: <phase> done #<issue>` last line. The per-phase-PR mode is removed.
- **Worklog now writes through Obsidian, not ZenNotes.** `worklog-runner` was the only
  agent in this plugin that saved notes through the ZenNotes MCP server
  (`mcp__zennotes__*`) — every other vault-touching agent (`dump`, `run-researcher`,
  `run-issue` phase 9.1, `gh-issue` step 7) goes through the `obsidian` CLI against the
  same vault. Two note backends for one vault meant the worklog path could break
  independently of everything else and carried a dependency (the ZenNotes MCP server)
  nothing else in the plugin needed. `worklog-runner` now resolves the daily note via
  `obsidian vault=notes daily:path`, and reads/writes it with the same
  `read`/`create ... overwrite`/`daily:append` sequence `dump` already uses, including
  its "check the output text, not the exit code, for `not found`" gotcha. The
  `mcp__zennotes__*` tool grants are gone from `worklog-runner`'s frontmatter.

## 1.2.0 — 2026-09-21

### Added

- **Stack-aware runtime QA.** Phase 4.5's verifier no longer delegates to gstack's
  `qa-only` and is no longer browser-only. It routes on `backend`/`frontend` glob
  signals (deterministic, in `classification.signals`, overridable per repo) computed
  from the diff:
  - **Backend** is verified over real HTTP against `api_url` — one call per response
    state (200/401/403/404/422/500), intersected with the diff-touched routes and the
    plan's acceptance criteria. `tinker`/SQL seed preconditions and assert side effects
    only; auth is always minted via the real login endpoint, never in-process.
  - **Frontend** is verified with real Playwright specs against `web_url`, using
    `page.route()` to force every state (loading/empty/error/permission-denied/success)
    instead of hoping an exploratory pass reaches them, plus one unmocked smoke run.
    Reuses a repo's own Playwright/`npx` setup before installing anything.
  - A PR touching both runs backend first; its captured responses become the
    frontend's mocks, so the two halves can't quietly disagree. A failing backend
    still lets the frontend run, flagged provisional.
  - `stack.py` now records `api_url`/`web_url` alongside `app_url` when a compose file
    exposes two distinct buildable app services. The envelope's rollup verdict is the
    worst of the dispatched modes, and `checks.py` validates each mode independently.

## 1.1.0 — 2026-09-19

### Added

- **Epic decomposition.** `/gh-issue` can split a large brief into a parent issue plus
  bite-sized children, each independently satisfying the Definition of Ready and declaring
  its order with a `Depends on: #n` line. `/run-issue <parent>` then drives them all —
  parallel where independent, sequential where dependent — behind **one** set of three
  human gates, not three per child. Dependent children stack their branch on the branch
  they depend on, so sequencing falls out of the DAG rather than being enforced separately.
  A blocker parks its child; the epic keeps going.
- **Station post-checks.** A `passed` envelope is now a claim the engine tries to refute
  from something with no incentive to agree — an exit code, a git object, a GitHub
  response, a file on disk. Five stations are checked; three gained a cheap pre-guard
  (`aiw precheck`). The motivating case: `run-fixer` could report success with review
  threads still open and nothing pushed. A refuted claim self-bounces on a budget that can
  never spend a real one; an exhausted budget advances and reports at the final gate.
- **The mechanical phases are code.** What used to be ~250 lines of procedure written in
  English is now `aiw stack|worktree|threads|pr|ci|gitnexus|project-status|project-board`.
  Each writes the ledger keys it produces itself, so there is no follow-up step to forget.
- **`docs/HOW-IT-WORKS.md`** — the system explained in layers, each usable on its own.
- **`CHANGELOG.md`** — this file.

### Changed

- **`/repo-bootstrap` is one PR, one phase per run** (#652): every phase commits to `bootstrap/<issue>`, one draft PR opened by constitution and ready after docs with a per-phase checklist; each run does one phase and ends with the next command and a `BOOTSTRAP: <phase> done #<issue>` last line. The per-phase-PR mode is removed.
- **The CLI is now `aiw`, not `route`.** `route` is also the macOS, BSD and net-tools
  *network* command, and `/sbin` precedes plugin bin directories on a default macOS `PATH`
  — so `route paths` ran `/sbin/route`, printed a usage error to stderr, and **exited 0**
  while every path the orchestrator needed silently resolved to nothing. Preflight now
  verifies identity (`aiw paths` must print JSON whose first key is `plugin_root`) instead
  of testing for absence, which was never the failure mode.
- **New exit code 7** from `aiw route`: a post-check refuted the envelope and the bounce is
  already routed. Exit 6 (test-root ownership) is unchanged.
- **The README is a setup protocol**, executable by an AI agent handed the repo link, with
  a human copy-paste install at the top.
- `epic.max_stacks` defaults to **1**. `-p runissue-<n>` namespaces container names, not
  published host ports, so two children sharing a compose file with any published port
  collide and both fail.

### Fixed

- **The plugin was uninstallable.** Both `userConfig` entries carried a `title` and no
  `description`, which the manifest schema rejects — `claude plugin install` failed
  outright. Nothing in `installed_plugins.json`, for the whole of 1.0.0.
- Four agents (`run-ci`, `run-grinder`, `run-researcher`, `run-specialist`) were told to run
  the CLI while their `tools:` line granted no permission for it.
- `aiw epic split` linked sub-issues by issue *number* where the API wants the database
  *id*, and only warned on failure — so it exited 0 having linked nothing, and a parent with
  no sub-issues then ran as one ordinary issue, turning the whole brief into a single PR.
- Several places conflated a failed `gh` call with a legitimately empty result: `epic split`
  silently dropping a child's dependencies (producing a DAG that validates and orders
  wrongly), and `project-board` creating a **second** board on a resumed epic.
- `definition-of-ready.md` told `run-researcher` to return `status: "blocked"`. The engine
  accepts `passed`/`bounce`/`escalate` only, so that envelope fails validation — and
  `run-issue.md` has long said readiness is advisory and surfaces at Gate 1.
- README commands were unpasteable: `<repo>` inside a bash fence is a shell input redirect,
  so `claude plugin marketplace add <repo>` ran with no argument at all.

### Notes

52 checks across `test_engine.py` (17) and `test_scripts.py` (35). No network, no Docker, no
install step.

**Epic mode has not been exercised against a live epic.** Its pure logic is covered and its
`gh` paths are stubbed, but the prose halves — the relay, the gate collapse, the
`base_branch` handoff — have no executable surface and are verified by reading only.

## 1.0.0

Initial packaging of the `/run-issue` pipeline as a Claude Code plugin.
