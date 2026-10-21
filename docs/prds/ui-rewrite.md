# PRD — aiw ui rewrite

**Status:** Draft · **Date:** 2026-10-21 · **Slug:** `ui-rewrite` · **Owner:** Masnun Siam · **Priority:** high · **Repo:** masnun-siam/ai-workflow

Status is `Draft`, `In review` or `Approved`. This document is the source of truth for the feature: every issue is derived from it, and a decision that is not written here has not been made.

## Overview

`aiw ui` is the web app that starts the workflow's skills as headless Claude sessions and shows where every feature, issue, PR and session stands. This rewrite replaces its frontend with a React + TypeScript app built by Vite, organised around one question: what needs me now? The approved clickable prototype is the design reference: https://claude.ai/artifact/STDuy2tBd4ALq8roggYmGV

Today:
- A Preact + htm frontend in `run-engine/ui_static/` with no build step, served by the stdlib Python server. Pages: Planning board, Delivery board, Sessions, Session transcript, Answer, New run, Settings, plus issue, PR and PRD drawers.
- The server polls GitHub into memory and the client polls the server. There is no push channel.
- The UI is organised by system artifact (PRDs, issues, sessions), so the same thing shows up in several places and the next action is often buried.

## Problem

The UI is hard to operate. A finding from the functional inventory of the current code:
- "Waiting on you" is shown in five places with different rules. Approvals, merges, failures, paused grinds and cleanups each live on a different page.
- A feature's life is split across two boards (Planning and Delivery), with an 8-column Delivery board that needs horizontal scrolling.
- Actions are buried: grind can't be stopped, a paused grind isn't visible on the board, merging only works inside a drawer, and starting a run lands on the Sessions list instead of the run.
- "Autopilot" names two unrelated features (AFK and epic autopilot). "In review" and "Draft" each mean two different things.
- Bugs: the session page crashes for peer-review sessions, the board keyboard shortcuts do nothing, a herdr start links to a "Session not found" page, Rerun loses the original arguments, and a local repo can't be published to GitHub because the dialog is unreachable.

Each audit so far has patched the same structure. The structure itself is the problem.

## Users

One developer (the repo owner) running the workflow on their own machine, on desktop and on a phone over their tailnet.

## Goals

- Everything that needs the user is in one Inbox, across repos, and can be acted on there.
- A feature is one page from PRD draft to shipped, with one obvious next step.
- Every action in the current UI is still reachable, in fewer clicks.
- Every failure and empty state says what happened and what to do.
- The app works at phone width and in light and dark themes.

## Non-goals

- A push channel (SSE or websockets). Polling stays.
- Multi-user support, logins or roles.
- Changing what the skills do. Only the UI and the API it needs change.
- Server-side rendering, or any runtime Node dependency for plugin users.

## Requirements

### Shell and navigation

- **FR-1 App shell.** A left rail with the repo switcher, nav (Inbox, Features, Board, Activity), a "Running now" list, the Away mode card, account usage meters, Settings, a theme toggle (system, light, dark) and a shortcuts button. A top bar with a search field (opens the palette) and a New button. Below 760 px the rail becomes a bottom tab bar, and the repo mark in the top bar opens the palette.
  - Acceptance: every page is reachable from the rail and from the bottom tab bar at 375 px, with no horizontal page scroll.
- **FR-2 Routing.** Hash routes `#/inbox` (default), `#/features`, `#/features/<slug>[/<tab>]`, `#/board`, `#/activity`, `#/sessions/<id>`, `#/settings[/<section>]`, each with optional `?repo=owner/name`. Old routes redirect: `#/planning` → features, `#/delivery` → board, `#/answer/<id>` and `#/session/<id>` → `#/sessions/<id>`, `#/new` → current page with the Start dialog open.
  - Acceptance: an old bookmark and an ntfy link from the old UI open the matching new page.
- **FR-3 Repo choice.** One current repo, held in the URL and remembered in one localStorage key. Inbox and Activity are cross-repo, with a repo filter. Features and Board show the current repo.
  - Acceptance: switching repo on any page changes Features and Board; a shared link with `?repo=` opens that repo.
- **FR-4 Palette.** ⌘K opens a palette over navigation, every Start command, the current repo's features, open issues and PRs, every session, repo switching, and Away mode on or off. Arrow keys and Enter work.
  - Acceptance: typing `801` and pressing Enter opens issue #801's panel.
- **FR-5 Shortcuts.** `N` opens Start, `G` then `I/F/B/A/S` navigates, `?` lists shortcuts, `Esc` closes the topmost panel or dialog, ⌘↵ submits a form. The shortcuts sheet lists exactly what works.
  - Acceptance: each listed shortcut works; none fires while typing in a field.
- **FR-6 Detail panel.** Issues and PRs open in a right-side panel that keeps the page underneath. Below 1180 px it overlays; below 760 px it is full screen.
  - Acceptance: opening an issue from Board, Features, Inbox or the palette shows the same panel.

### Inbox

- **FR-7 Inbox list.** Items are grouped as Blocking everything, Answer Claude, Decide, Fix, Set up, and Waiting (nothing to do). The rail badge and document title count every item except Waiting. Item types:
  - Blocking: GitHub CLI not signed in.
  - Answer: a session waiting on a question.
  - Decide: a peer review at its round cap; a peer review where every lens approves; a PR that is approved with green checks.
  - Fix: a failed session; a grind paused (with its reason); a merged issue whose worktree has unsaved work.
  - Set up: a registered `local/` repo with no GitHub remote.
  - Waiting: a session paused by a usage limit (with its reset time); a queued session (with why).
  - Acceptance: each type appears when its condition holds and disappears within one poll after it clears.
- **FR-8 Inline actions.** Each item carries its actions. Answer items expand an inline question form. Others: Approve PRD anyway, Run 2 more rounds, Open review, Review and merge, Skip CI and continue, Stop grind, Retry, Continue in terminal, Review and clean up, Publish to GitHub, Resume on another account, Start now, Cancel.
  - Acceptance: every action works from the Inbox without opening another page, except those that open a panel by design (merge, cleanup review).
- **FR-9 Question form.** Used in the Inbox and the session page. One fieldset per question, radio or checkbox by `multiSelect`, the recommended option pre-selected and tagged, "Something else" free text when allowed (max 4000 characters). The submit button says how many answers it sends. While the Claude process is still running, the button is disabled with an explanation and re-checks every 3 s. A 409 shows "Already answered" with a reload.
  - Acceptance: answering moves the session to running and removes the Inbox item.
- **FR-10 Empty inbox.** Says nothing needs the user and how many sessions are working, with a link to Activity.

### Features

- **FR-11 Features list.** One row per PRD in the current repo: title, epic, last update, stage chip, a progress track, and the next-step button. Tabs: In progress and Shipped. The stages are PRD draft, PRD review, Approved, Tasks, Building, Shipped. The track shows the four planning stages as segments and the build stage as issue counts by status.
  - Acceptance: each PRD appears once, in the stage its server data says.
- **FR-12 Feature page.** A stage stepper with an issue legend, a Next step box (one primary action, at most one secondary), and tabs Issues, PRD, Peer review and Sessions. The More menu holds Open PRD on GitHub, Add a task, and Close epic.
  - Next step by stage: Draft → Start peer review (secondary: Approve without review). Review running → Watch review (secondary: Approve now). Review at cap → Decide. Review approved → Approve PRD. Approved → Create tasks. Tasks → Refine N (secondary: Start N ready). Building with an approved green PR → Review and merge. Building, auto-build off with ready issues → Turn on auto-build (secondary: Start N now). Shipped → Close epic.
  - Acceptance: the Next step box matches this table for each stage.
- **FR-13 Issues tab.** A table grouped by status, each row with status, signals (priority, PR, CI, review decision, grind state, live session, last run failed, needs cleanup) and one action. The auto-build switch with the repo's cap, and an Add task field, sit above it. Unrefined children can be picked and refined together.
  - Row actions: Refine; "after #a, #b" when blocked; Start with a menu (Start here, Start in a herdr tab, Start on another account); Retry when the last run failed; Queued; Answer or Watch for a live session; Merge, Grind or Open PR in review; Skip CI on a paused grind; Clean up when merged with unsaved work.
- **FR-14 PRD tab.** Read (rendered markdown), Edit (commits only that file on the checkout's current branch, not pushed, with that warning shown), and Ask Claude (starts `/create-prd <path> --update <request>` and opens its session). Unsaved edits ask before they are discarded. A save is refused with a clear message if the file changed on disk since it was opened.
- **FR-15 Peer review tab.** With no panel: a lens picker and Start review (draft PRDs only, explaining why otherwise). With a panel: round x of max, state, one row per lens with verdict and latest note, Re-run and Drop on failed lenses, and at the cap: Run 2 more rounds and Approve anyway. A link opens the root session.
- **FR-16 Sessions tab.** The feature's sessions, using the Activity table.
- **FR-17 Empty repo.** With no PRDs, the Features page shows an idea box that starts `/create-prd`, and a link to start it in the notes vault instead.

### Board

- **FR-18 Board.** Five columns: Needs refinement, Ready (blocked issues listed last, with a lock), Building (including draft PRs), In review (including grinding), Merged (7 days). Group by feature (default; one lane per feature with open issues, header shows progress and the auto-build switch, always visible) or All issues. Cards show signals and their row action, open the issue panel on click or Enter, and are outlined when they need the user. j/k move between cards in a column and h/l between columns.
  - Acceptance: at 1440 px a lane fits without horizontal scroll; an issue never appears in two columns.

### Activity and sessions

- **FR-19 Activity.** Live sessions as cards (status, command, what it is for, duration, account and cost, or the limit or queue reason). History as a table with search, a result filter, cost today, and per-row actions. Clean up old sessions opens a dialog listing finished sessions by repo before removing them.
- **FR-20 Session page.** Header with command, status and what it is for; banners for waiting (inline question form), limited (reset time, Resume on another account, Don't auto-resume), failed (error, Continue in terminal, Retry) and queued (reason, Start now). A transcript in time order with tool calls collapsed to one line and expandable, auto-scroll while live, and search. A composer that sends a prompt, or queues it while a turn is running, disabled while a question is pending. A facts box with repo, account, start, duration, cost, tokens and PR. For a finished no-repo `create-prd` session: the vault PRD's status and Create repo.
- **FR-21 Session actions everywhere.** Stop (with confirm), Retry or Resume, Rerun with the original request, Continue in terminal (copies the resume command). Starting anything opens its session page. A duplicate start (409) links to the running session.

### Start dialog

- **FR-22 Start dialog.** Commands grouped Plan, Build, Review, Ship, Capture, Maintain, each with a plain name, the skill name and a one-line description. Per command: a Where picker (registered repos, and "No repo yet" for vault-capable commands with the folder chooser and Suggest with Claude), its input (free text, a ready-issue list, an open-PR list, an approved PRD, issue numbers, or a day / range for worklog), optional peer-review lenses, and Run on (account, showing limited accounts and that the run will queue). A pasted issue or PR URL of a registered repo switches the repo. Custom prompt warns that permission checks are skipped. Worklog ranges start one session per day and offer Retry N failed days.
- **FR-23 Create and publish a repo.** The Create repo dialog (name, parent folder, optional vault PRD) from the session page and from the Where picker. Publish to GitHub (owner, private) for any `local/` repo, from the Inbox and Settings.

### Panels

- **FR-24 Issue panel.** Ref, title, status, feature link, the row action and signals, blocked-by links, PR summary (opens the PR panel), sessions for the issue, the body, comments with a comment box, Refine again, Close as completed or not planned, Reopen when closed, and Open on GitHub.
- **FR-25 PR panel.** Tabs Overview (branch, +/−, body, grind state with Skip CI and Stop, reviews), Checks, Conversation, Files (lazy per-file diffs) and Commits. Merge asks for confirmation inside the panel and lists warnings (failing or running checks, changes requested, no approval); with warnings the button reads Merge anyway. A merge commit, never squash.

### Away mode, accounts and settings

- **FR-26 Away mode.** The rail card sets 30 min, 1 h, 2 h, 4 h or an end time; while on, a banner and the card show the end time and held count, with +30 min and I'm back. On return, the Inbox shows a "While you were away" summary until dismissed.
- **FR-27 Usage and limits.** Per-account 5-hour and 7-day meters in the rail; a limited account shows its reset time in red.
- **FR-28 Settings.** Sections Repositories (one table: path, GitHub status or Publish, auto-grind, auto-build cap, Slack channel, Remove; plus scan folders, Find repos and Check remotes), Claude accounts (label, command, default, Test, add, remove), Notifications (browser permission state including blocked, ntfy fields with saved-secret handling and env overrides, Send test push), Peer review (rounds, default lenses, per-lens prompts with an edited marker, reset) and Notes vault. Each section saves on its own, so unsaved edits in one never travel with another.
- **FR-29 Onboarding.** With no registered repos: checks for the GitHub CLI and a Claude account, then scan folders and add repos.

### States

- **FR-30 Failure states.** Each has a designed banner or page, never a raw error alone:
  - Server unreachable: a top banner; actions are refused with a toast while offline.
  - GitHub CLI signed out: a blocking Inbox item and a banner on Features and Board with the fix command.
  - GitHub rate limit: data age and next refresh shown; Refresh hidden.
  - Board never fetched: skeleton, then "unavailable, retrying".
  - Session not found, issue or PR fetch error with Retry.
  - Notifications blocked: shown in Settings.
  - herdr start: a toast that herdr tabs are not tracked, no session link.
- **FR-31 Confirmations.** Destructive and outward actions (Stop, Approve PRD, Close epic, Merge, Remove repo, Clean up, Reset review config, Discard PRD edits, Publish) use in-app dialogs that say what happens, never `window.confirm`.
- **FR-32 Theme and accessibility.** Light and dark from one token set, visible keyboard focus, labelled controls, reduced motion respected, status never shown by colour alone.

## Edge cases

- A session can be waiting while its process is still alive: the answer form explains and unlocks on exit (FR-9).
- Two tabs answer the same question: the second gets 409 "Already answered".
- Starting an issue that already has a live session or an open PR: 409 links to it (FR-21).
- A blocked issue's blocker merges: it moves to Ready on the next poll.
- Away mode muting: Inbox items still appear while away; only the badge pulse and browser notifications are held.
- A repo removed from Settings while it is the current repo: switch to the first remaining repo, or onboarding when none remain.
- A PRD edited on disk while the Edit tab is open: the save is refused (FR-14).
- Data isolation: not applicable (single user).
- Existing data: none migrated. Old localStorage keys (`aiw.repo`, `aiw.boardRepo`, `aiw.lastRepo`) are read once into the new key and then ignored.

## Technical design

### Data

No new stores. Session records gain one field, `request`: the original start body (repo or vault folder, command, args, issue, account label, lenses, batch). It is written at start and read by Rerun (FR-21). Records without it fall back to today's text rerun.

### API

Existing endpoints keep their contracts unless listed here. All responses stay JSON with `{error}` on 4xx.

- **`GET /api/inbox`** (new, FR-7). Query: optional `repo`. Response `{items: [Item], afk, gh}` where `Item` is `{key, group: block|answer|decide|fix|setup|wait, type, repo, at, ...type fields}`. Types and their fields:
  - `gh_auth {error}`
  - `question {session_id, command, link, questions, process_alive}`
  - `review_cap {prd_path, panel, round, max_rounds, note}`
  - `review_approved {prd_path, panel}`
  - `pr_ready {pr, issue, title, reviewer, checks}`
  - `grind_paused {pr, issue, round, reason}`
  - `session_failed {session_id, command, link, error}`
  - `needs_cleanup {issue, uncommitted, unpushed}`
  - `repo_unpublished {slug, path}`
  - `limited {session_id, account, resets_at, auto_resume}`
  - `queued {session_id, reason}`

  `key` is stable across polls so the client keeps an expanded item open. Built from session records, panels, the grind index, cleanup flags, the repo registry and the poller snapshots of watched repos. A repo whose snapshot is stale or missing contributes session items only and is listed in `stale: [repo]`.
- **`GET /api/sessions`** gains `gh: {ok, login, error}`. The gh check runs at most once a minute and is cached.
- **`GET /api/delivery`** card changes: `grind_round` is replaced by `grind: {state: running|idle|paused, round, reason} | null`. `pr` gains `review: approved|changes_requested|review_required|none`, from `reviewDecision`, which the poller adds to its PR query.
- **`POST /api/start`** response for herdr becomes `{session: null, via: "herdr", tab: <label>}` (today `session` is `herdr:<label>`, which the old UI linked to a missing page).
- **`POST /api/sessions/<id>/rerun`** (new, FR-21). Replays `request` through the same path as the original start, guards included. 201 with the new session; 409 duplicate with `{id, href}`; 400 if the record has no `request` and no command.
- **`POST /api/grind/skip-ci`** `{repo, pr}` (new, FR-8, FR-25). The action AFK already takes for a grind paused on CI, now user-triggered. 409 if the grind is not paused.
- **`POST /api/grind/stop`** `{repo, pr}` (new). Marks the loop done with the reason "stopped from the UI"; the re-entry timer skips done loops. The PR stays open. 409 if no loop exists.
- **`GET /api/prd`** response gains `sha` (blob hash of the file as read). **`POST /api/prd`** accepts `base_sha`; 409 `{error: "changed on disk"}` when it no longer matches (FR-14).
- **`POST /api/review/<panel>/rounds`** `{add: 1..5}` (new, FR-15). Raises a capped panel's round limit and resumes the relay loop. 409 unless the panel is at its cap.
- Static: `/` and `/assets/*` serve the built app from `run-engine/ui_dist/`; `/sw.js` and the manifest stay at the root. During the parallel period (see Rollout) the new app is served at `/next/`.

### Backend

- `ui_inbox` (new module) builds the inbox from the sources above. Pure function over its inputs so it is tested with fixtures, like `ui_delivery.build`.
- The poller's PR fragment adds `reviewDecision`.
- The poller watches every registered repo with a GitHub remote that was opened in the UI in the last 7 days or has a live session, so the Inbox covers more than the repo on screen. Today it watches only repos a board has requested.
- Session start stores `request`; rerun replays it.
- Grind skip-ci and stop reuse the grind state file writers that AFK and the loop already use.

### Frontend

- Source in `ui/` at the repo root: React 18, TypeScript (strict), Vite. Dependencies kept to: `react-router-dom` (hash router), `@tanstack/react-query` (polling, cache, mutations, invalidation after writes), Radix primitives (dialog, dropdown menu, popover, tabs, switch, tooltip) for accessible overlays, `cmdk` for the palette, and `@fontsource` packages for Hanken Grotesk and IBM Plex Mono so fonts load offline. No CSS framework: one token stylesheet ported from the prototype, plus CSS modules per component.
- The markdown renderer is ported from the current `md.js`, so rendering and sanitising behaviour don't change.
- Polling intervals match today: sessions 3 s, inbox 5 s, boards 15 s, a live transcript 1 s. Polling pauses while the tab is hidden unless notifications are on. After a write, the affected queries are invalidated instead of waiting a fixed 2 s.
- Typed API client generated by hand from the contracts above, in one module.
- Feature pages join `/api/planning` (the PRD) and `/api/delivery` (the lane whose epic matches) on the client. No new feature endpoint.
- Build output goes to `run-engine/ui_dist/` and is committed, so installing the plugin never needs Node. `index.html` is served no-cache; assets have content hashes.
- PWA: the manifest, icons and the offline-page service worker carry over.

### Realtime and other services

Not affected. Polling stays (see Non-goals). ntfy notifications are unchanged, except that their links use the new routes; old routes still redirect (FR-2).

### Non-functional

- The first load is at most 250 KB gzipped of JS and CSS, fonts excluded.
- It works in current Safari, Chrome and Firefox, desktop and iOS.
- Security is unchanged: Host and Origin guard, loopback or tailnet only. The built app loads nothing from outside the server.

### Testing

- Python: assert-based `test_ui_inbox.py` (every item type and its clearing condition), and additions to the delivery, poller, prd, start/rerun, grind and review tests for the API changes. Run by `run_tests.sh` as today.
- Frontend: Vitest for pure logic (next-step table, board column mapping, inbox grouping, route redirects, question-form validation) and React Testing Library for the question form, Start dialog, merge confirm and palette.
- The static-source tests (`test_ui_static.py` JS checks, `test_ui_boards_static.py`, `test_ui_planning_static.py`, `test_ui_delivery_static.py`, `test_ui_settings_static.py`) are deleted at cutover. Their static-serving, guard and service-worker checks move to a slimmer `test_ui_static.py` pointed at `ui_dist/`.
- CI gains a Node job: `npm ci`, typecheck, Vitest, `npm run build`, then fail if `run-engine/ui_dist/` differs from the build. That proves the committed build matches the source.
- Manual: every state in FR-30 and every flow in the parity checklist, at 1440 px and 375 px, in light and dark.

## Rollout and cost

- Phase 1: API changes land first. They stay compatible with the old UI (the old UI ignores new fields; `grind_round` is kept alongside `grind` until cutover).
- Phase 2: the new app is served at `/next/` next to the old one at `/`, until every item in the parity checklist (FR-7 to FR-29) passes.
- Phase 3: cutover. `/` serves the new app, old routes redirect, `run-engine/ui_static/` and its tests are deleted, `grind_round` is removed.
- Docs updated at cutover: `CLAUDE.md` (the "no frontend build step" rule becomes "Python is stdlib only; the UI is built from `ui/` with Vite and the build output is committed, so users never need Node"), `docs/REFERENCE.md` (UI section), `docs/INSTALL.md` (developer setup for `ui/`), `CONTRIBUTING.md`, `CHANGELOG.md`.
- No cost impact. GitHub API use rises with the wider watched-repo set: one GraphQL call per watched repo per minute.

## Success metrics

None formally defined. Informal check: a full day of real use without going to the GitHub website to find out what needs doing.

## Epics

- **E1 aiw ui rewrite** — covers FR-1 to FR-32. Issue: —

## Decisions

- React + TypeScript + Vite, with the build committed to the repo — users install the plugin without Node, while the UI gets a typed component model and accessible primitives.
- Inbox is built on the server — one request instead of a fetch per repo, testable in plain Python, and reusable by ntfy and Away mode later.
- Polling, not SSE — the current intervals are fast enough for one user, and a push channel adds connection handling that nothing here needs yet.
- Planning and Delivery merge into Features and Board, with no new feature endpoint — the client joins the two existing responses by epic number.
- Board has 5 columns — blocked folds into Ready, draft PRs into Building, grinding into In review. Their state still shows on the card.
- "AFK" is renamed Away mode and epic autopilot is renamed Auto-build — the two features no longer share a name.
- The Answer page is merged into the session page — one page per session.
- No CSS framework — the prototype's token stylesheet already covers the design, in both themes.
- Old and new UIs run side by side until parity — no feature is lost at cutover.
- The 7-day watch cutoff is fixed, not a setting — one user, and a repo comes back into the set the moment it is opened or a session starts in it.
- "Start in a herdr tab" stays, inside the Start menu, with a toast saying herdr tabs are not tracked — it is the existing dispatch path and removing it is out of scope.

## Open questions

## Change log

## Related

- Prototype: https://claude.ai/artifact/STDuy2tBd4ALq8roggYmGV
- `docs/REFERENCE.md` (current UI and API), `CONTEXT.md` (vocabulary)
