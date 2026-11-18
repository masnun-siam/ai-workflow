# PRD — Align setu with blubird 1.2: business docs, locked PRDs, monorepos

**Status:** Approved · **Date:** 2026-11-18 · **Slug:** `blubird-1-2` · **Owner:** Masnun Siam · **Priority:** high · **Repo:** masnun-siam/ai-workflow

## Overview

setu's blubird screens still follow blubird 0.28. Version 1.2.0 removes `map-prds` and adds a business-documentation stage with three skills. It also locks a PRD once it is approved and keeps the monorepo path for a repo that has no repo map. This change brings setu in line: the right skills in the palette, a read-only view of the business docs, approved PRDs that can't be edited, a Start flow that turns an unmapped repo into a monorepo product, and the coordinator's new stale state.

Today:
- The step registry, Start palette, River ("create-prd · map-prds") and Ops list `map-prds`. blubird 1.2.0 has no such skill, so running it fails. The registry has no `collect-docs`, `refine-docs` or `business-code-validator`.
- On a feature page, the PRD tab offers **Edit** (writes and commits the file) and **Ask Claude to change it** whatever the PRD's status, including `Approved`.
- setu reads only `docs/prds/`. blubird 1.2 adds `docs/business/<module>/<feature>.md`, the lasting record of what is live: rules `R-n` with a Delivery mark, a dated Timeline whose `planned` bullets link a PRD or issue, and a checker script that is the gate for every write.
- Starting a docs-repo step (`create-prd`, `create-tasks`, `security-sweep`, `project-coordinator`) on a repo with no `.blubird/repos.json` and no `.blubird/docs-repo` fails before the session starts ("has no .blubird map or docs-repo pointer"). blubird's own fallback, "carry on as a monorepo" (writes a one-entry map with `"path": "."`), is never reached. A repo that already has a monorepo map works: setu registers it as a one-repo product on the next poll.
- The Coordinator monitor shows queue states from blubird's `queue.tsv`. 1.2.0 adds `in-progress-stale`: In progress, assigned to you, with no open PR and no run on it.
- setu reads the installed blubird version and offers Update, but it doesn't check that the installed version is new enough.
- The closest patterns: the Features page and PRD tab (product-scoped list, file read with a blob sha), and the Coordinator monitor's "needs you" events feeding the Inbox.

## Problem

Today setu offers a skill that no longer exists and lets you edit PRDs that blubird treats as locked. It can't start a PRD on a repo that isn't yet mapped, though blubird supports that repo as a monorepo. It also hides the business docs, which are now the record approval and delivery write to. Each mismatch either fails at run time or leaves the docs and setu disagreeing.

## Users

The single operator of setu, on the repos and products registered in it. No roles or tenants.

## Goals

- Every step setu offers exists in the installed blubird, and every 1.2 docs skill can be started from setu.
- An approved PRD is read-only in setu, and the two ways blubird allows changing approved work are one click away.
- A repo with no map can start a PRD: you choose monorepo or onboarding before the session starts, and the repo is a product from then on.
- Business docs, their rule status and their gate can be read in setu, per product and per feature.
- A stale coordinator issue is surfaced like other coordinator problems.

## Non-goals

- Editing business docs in setu. Docs change only through `collect-docs`, `refine-docs`, `create-prd` approval, `refine-issues` and `implement-issue` sessions.
- Re-implementing the business-docs checker's rules in setu. setu runs blubird's own checker and shows its output.
- Changing `docs/prds/ui/blubird-ui.md`. It is deprecated and left as it is.
- A UI for VibeXP, for `verifier-locally`'s visual check or critical-flow checklists, or for business-doc pointer files in code repos.
- Migrating old `map-prds` drafts. That is `collect-docs`'s job.
- Supporting blubird older than 1.2.0 beyond the banner in FR-11.
- Pushing or committing `.blubird/repos.json` for the user.

## Requirements

- **FR-1 Skill registry follows 1.2.** `map-prds` is removed from the step registry, the Start palette, the River stage label and Ops. Three steps are added, each run in the product's Documentation Repo:
  - `collect-docs` takes `[file or folder ...]`.
  - `refine-docs` takes `[module | docs/business/<module>/<feature>.md ...]`.
  - `business-code-validator` takes `[module | docs/business/<module>/<feature>.md ...]`.
  - Acceptance: the Start palette lists the three new steps and not `map-prds`. Starting each one opens a session in the docs repo whose first prompt is `/blubird:<skill> <args>`. A search of server and app finds no `map-prds` step.
- **FR-2 Docs stage.** A new pipeline stage `docs` ("Docs") comes before `prd`. The three steps of FR-1 belong to it. The River shows it as the first column, and the Start palette files these steps under "Plan".
  - Acceptance: a running `refine-docs` session appears as a card in the River's Docs column, left of PRD. Start shows the three steps in the Plan group.
- **FR-3 Approved PRDs are locked.** For a PRD whose status is `Approved` (or the legacy `Done`), the PRD tab shows the file read-only, with a line saying it is locked. It offers no Edit and no "Ask Claude to change it". The server refuses a write to such a PRD.
  - Acceptance: the PRD tab of an Approved PRD has no Edit button and no change box. A `PUT /api/prd` for that file returns 409 and leaves the file and git unchanged. A Draft PRD still offers both.
- **FR-4 Changing approved work.** The locked PRD tab offers two actions, each taking one line of text:
  - **New PRD for this change** starts `create-prd` in the docs repo with the text, the approved PRD's path and an instruction to name it under "Related".
  - **One small task** starts `small-change` with the text and the approved PRD's path. When the feature has an epic, it runs in the epic's repo and the task is filed as a child of the epic. Otherwise it runs in the docs repo.
  - Acceptance: each action starts one session whose prompt contains the typed text and the approved PRD's path. With an epic, the `small-change` prompt names the epic as parent.
- **FR-5 Approval says what it does.** The Approve PRD confirmation says that Claude checks the PRD against the business docs, asks you to confirm each rule it adds or changes, and then creates the epic.
  - Acceptance: the confirmation dialog for Approve PRD shows that text.
- **FR-6 Business docs list.** A top-level **Docs** page, next to Features and scoped to the selected product, lists every business doc under `docs/business/<module>/<feature>.md` of the product's docs repo, grouped by module. `README.md`, `open-questions-to-client.md`, `sources/` and `checklists/` are not docs. Each row shows:
  - the feature title and its Updated date;
  - its rule count;
  - counts of rules marked not delivered, partly delivered, drifted, and built differently from the design;
  - its planned count (rules with a `planned` Timeline bullet and no later `delivered` or `withdrawn` bullet);
  - its open questions count.

  With no `docs/business/`, the page shows an empty state naming **Collect docs** (FR-1) as the action.
  - Acceptance: a product with docs in modules `auth` (2 docs) and `billing` (1) shows two groups and three rows with correct counts against fixture docs. A product with no `docs/business/` shows the empty state with a working Collect docs action.
- **FR-7 Business doc reader.** Opening a doc shows its Markdown rendered with a table of contents, read-only, and the doc's path and branch. It offers **Refine this doc**, which starts `refine-docs <path>`, and **Validate this doc**, which starts `business-code-validator <path>`.
  - Acceptance: opening a doc renders its sections. Each action starts its step with the doc's path as the argument.
- **FR-8 Docs gate.** setu runs blubird's checker (`check-business-docs.py`, without `--confirmed`) on the product's `docs/business` whenever a file under it changes, and caches the result. The Docs page shows **Gate passes**, **Gate fails** with the checker's failure lines, or **Gate unavailable** with the reason: no `python3`, blubird older than 1.2.0, timed out, or no `docs/business`.
  - Acceptance: a fixture doc with an undated Timeline bullet shows Gate fails and the checker's line for it. Fixing the file shows Gate passes after the next change is seen. With `python3` absent, the page shows Gate unavailable naming it.
- **FR-9 Business tab on a feature.** Each feature page gets a **Business** tab. It lists the docs that match the feature, in this order:
  1. the doc at `docs/business/<module>/<feature>.md` with the same module and file name as the PRD;
  2. every doc whose Timeline has a `planned` bullet linking this PRD's path.

  Each match opens in the FR-7 reader, inline. With no match, the tab says no business doc covers this feature yet and names Collect docs.
  - Acceptance: a PRD `docs/prds/auth/login.md`, with `docs/business/auth/login.md` and a `billing/plans.md` holding a planned bullet linking that PRD, shows both docs. A PRD with neither shows the empty state.
- **FR-10 Business validation epics.** Open issues in the docs repo labelled both `epic` and `business-validation` (titled `Business validation: <Module>`) show on the Docs page under their module (`Other` when the title has no module). Each shows its child issues with the same states and row actions as a feature's issues (Refine, Implement, Merge), and a **Run epic** action as on Features. They never appear as Feature rows.
  - Acceptance: an open `Business validation: Auth` epic with two children shows under `auth` with both children and their actions. Features shows no row for it.
- **FR-11 Plugin too old.** When blubird is installed at a version below 1.2.0, a banner names the installed version and offers the existing Update action. Steps the installed plugin lacks (no `skills/<name>/SKILL.md`) show as unavailable in Start, with the reason, and can't be started.
  - Acceptance: with a fake 0.28.0 install, the banner shows and `collect-docs` is disabled with "needs blubird 1.2.0". After the update, the banner goes on the next status read.
- **FR-12 Monorepo choice before a docs step.** When a docs-repo step (any step that runs in the Documentation Repo), or a process action from FR-14, targets a repo with no `.blubird/repos.json` and no `.blubird/docs-repo`, setu asks before starting anything:
  - **Use `<owner/name>` as a monorepo** writes `.blubird/repos.json` in that repo's checkout. The map has one entry: the repo's name, role `docs`, its `owner/name` and `"path": "."`. The repo is registered as a product at once, and the step then starts there.
  - **Run agentic-onboard** starts `agentic-onboard` in that repo instead.
  - **Cancel** starts nothing.

  A local repo with no GitHub remote can't be made a monorepo, and the choice says to add a remote first.
  - Acceptance: on an unmapped repo, the Create box's Feature route shows the choice. Choosing monorepo writes the one-entry map. The product appears in the product picker, and a `create-prd` session starts in that repo. Cancel leaves the repo untouched.
- **FR-13 The map rides the next change.** setu doesn't commit the map it writes. A product whose `.blubird/repos.json` is not tracked in its checkout's current commit shows **Map not committed**, which says the first session's commit should carry it. The note clears once the file is tracked.
  - Acceptance: right after FR-12, the product shows Map not committed. After the file is committed on the checkout's branch, the note is gone on the next poll.
- **FR-14 Unmapped repos offer the choice.** Process actions that blubird runs (write PRD, create tasks, refine, implement, dispatch, coordinator) are no longer hidden on an unmapped repo. They lead to the FR-12 choice first. This replaces the earlier rule that unmapped repos are read-only.
  - Acceptance: an unmapped repo's River offers Refine on an open issue. Clicking it shows the monorepo choice, and choosing monorepo then starts `refine-issues`.
- **FR-15 Stale coordinator issues.** In the Coordinator monitor, a queue issue in state `in-progress-stale` is highlighted like a STOPPED issue. It carries blubird's hint: In progress and assigned to you, but no open PR and no run on it. It adds one Inbox item with **Implement** (starts `implement-issue <n>` in the issue's repo) and **Open issue**. The Inbox item goes when the state does.
  - Acceptance: a fixture run whose `queue.tsv` has one `in-progress-stale` line shows it highlighted with the hint and adds exactly one Inbox item. Removing the line removes the item on the next read.

## Edge cases

- **Concurrency.**
  - Two docs steps started at once on the same unmapped repo: the map write is atomic and refuses to overwrite. The second request sees the map already present with the same entry and goes on to start its step instead of failing.
  - A business doc changing while the gate runs: the cached result is dropped and the gate runs again.
  - A PRD approved while its PRD tab is open in Edit: the save is refused (FR-3), with the same reload prompt as a sha conflict.
- **Empty states.**
  - No `docs/business/`: FR-6 and FR-9 empty states.
  - No validation epics: no section.
  - No coordinator runs: unchanged.
- **Limits.**
  - Business docs are read with the same 2 MiB per-file cap as PRDs. A larger doc is listed with "too large" and no counts.
  - The gate has a 30-second timeout, then shows Gate unavailable (timed out).
  - The list reads only each doc's header and rule and Timeline lines, not the whole file.
- **Malformed docs.**
  - A doc with no `**Module:**` header line is listed under its folder's module.
  - A rule with no recognisable Delivery mark counts toward the rule total only.
  - Parse problems never hide a doc. The gate reports them.
- **Repos and products.**
  - A repo with a `.blubird/docs-repo` pointer to a missing or unmapped docs repo keeps today's error. The monorepo choice is offered only when neither file exists.
  - A repo already registered as a code repo of another product never gets the choice.
- **Access and data isolation.** One operator, no tenants. Business docs are read only from a registered product's docs checkout. Paths are validated as for PRDs: under `docs/business/`, `.md`, no `..`, and resolved inside the checkout. Nothing is sent to a network service.
- **Existing data.**
  - No migration. Existing PRDs keep their status. `Done` PRDs are treated as locked.
  - A Documentation Repo still holding old `map-prds` drafts shows them as Draft PRDs, as today. `refine-docs` itself tells the user to run `collect-docs` first.
  - Settings or sessions referring to the `map-prds` step keep their history. Rerunning one fails with "unknown step".

## Technical design

### Data

- No new store in `~/.setu`. Business docs, PRDs and the repo map stay files in the user's checkouts. The gate result is in-memory, keyed by product and the newest modification time under `docs/business`.
- **BusinessDoc** (internal data): `product`, `module`, `feature` (file name without `.md`), `path`, `title`, `updated` (from `**Updated:**`, may be empty), `repos` (from `**Repos:**`), `rules` (count), and `counts`:
  - `not_delivered`, `partly_delivered`, `drifted`, `built_differently`, `planned` and `open_questions`.
  - `prds`: the PRD paths its `planned` bullets link.
  - `error`: set when the doc is too large or unreadable.
- **Delivery marks** read, exactly as blubird's template has them: `delivered`, `partly delivered`, `not delivered`, `drifted`, `built differently from the design`, `delivered by later decision`. A rule marked "Withdrawn by …" is not counted.
- **BusinessGate:** `state` (`pass` | `fail` | `unavailable`), `failures` (the checker's lines, at most 200), `reason` (when unavailable) and `checked_at`.
- **ValidationEpic:** `repo`, `n`, `title`, `module`, `url` and `issues` (the existing feature-issue shape, with states and row actions).
- **Repo** gains `map`: `docs` (holds `.blubird/repos.json`), `pointer` (holds `.blubird/docs-repo`) or `none`.
- **Product** gains `map_committed` (boolean).
- **Feature** gains `business`: the matched doc paths, in FR-9 order.
- **Blubird status** gains `min_version` (`"1.2.0"`) and `too_old` (boolean).
- **Step** keeps its existing `available` and `reason` fields in `GET /api/registry`. A blubird step the installed plugin lacks is now `available: false`, with `reason: "needs blubird 1.2.0"`.
- Monorepo map file: `{"repos": [{"name": "<name>", "role": "docs", "repo": "<owner>/<name>", "path": "."}]}`. This is the shape blubird's guard rail writes, which setu's registration already accepts.

### API

All errors use the existing `{error}` JSON shape.

| Method and path | Request | Response | Errors | FR |
|---|---|---|---|---|
| `GET /api/products/{owner}/{name}/business` | — | `{docs: BusinessDoc[], gate: BusinessGate, epics: ValidationEpic[]}` | 404 unknown product | 6, 8, 10 |
| `GET /api/business?repo=<slug>&path=docs/business/...md` | — | `{repo, path, text, sha, branch}`, the same shape as `PRDFile` | 400 bad path; 404 no such file; 400 too large | 7, 9 |
| `POST /api/repos/{owner}/{name}/monorepo` | `{}` | `{product: Product}` | 404 not a registered repo; 400 no GitHub origin; 409 map or pointer already present, with a different entry (an identical map returns 200) | 12 |
| `PUT /api/prd` (changed) | unchanged | unchanged | new: 409 `approved PRDs are locked: start a new PRD or a task` when the file's status is Approved or Done | 3 |
| `GET /api/features` (changed) | unchanged | each feature gains `business` | — | 9 |
| `GET /api/repos`, `GET /api/products`, `GET /api/blubird`, `GET /api/registry` (changed) | unchanged | the fields added under Data | — | 11, 12, 13 |
| `POST /api/sessions` (changed) | unchanged | unchanged | new: 409 `needs a repo map` with `{repo}` when a docs-repo step, or an FR-14 action, targets a repo whose `map` is `none`. The UI answers with the FR-12 choice. Also 400 `step unavailable: <reason>` for an unavailable step | 11, 12, 14 |

- Step registry entries (API.md §9.1), all `blubird`, run in `docs`, stage `docs`:

  | Step | Label | Argument hint |
  |---|---|---|
  | `collect-docs` | Collect docs | `[file or folder ...]` |
  | `refine-docs` | Refine docs | `[module \| docs/business/<module>/<feature>.md ...]` |
  | `business-code-validator` | Validate business | `[module \| docs/business/<module>/<feature>.md ...]` |

  `map-prds` is deleted.
- SSE: `products{kind:"business"}` is published when a product's business docs or gate result change.

### Backend

- **Business docs reader (products).** Walks `docs/business/**/*.md` of a product's docs checkout and skips the non-doc files of FR-6. It reads each file up to the size cap and parses the header line, the rule lines, the Delivery lines, the Timeline bullets and the Open questions section into BusinessDoc. It is pure file reads with no git. It reuses the PRD path checks for the single-file read.
- **Docs gate (products).** Runs `python3 -I <blubird install path>/skills/collect-docs/scripts/check-business-docs.py docs/business` in the docs checkout, with a fixed argument list, a 30-second timeout and no shell.
  - Exit 0 is `pass`. Exit 1 is `fail`, with stdout's lines as failures. Anything else is `unavailable`.
  - It is triggered from the poll tick, only when the newest mtime under `docs/business` differs from the cached one. At most one run per product at a time, and a change during a run schedules one more.
  - It reads the install path from the blubird status. It is skipped (`unavailable`) when blubird is too old or `python3` is not on PATH.
- **Validation epics (views).** Come from the issues the poller already holds for the docs repo: labels `epic` and `business-validation`. The module is the title after `Business validation: `, lowercased. Children and their states and actions use the existing feature-issue builder.
- **Feature business match (views).** Same module and file name, plus the `prds` list of every doc (FR-9).
- **PRD lock (products).** The save path parses the current file's status before writing and refuses Approved or Done (FR-3). The check and the sha check happen together, so an approval landing mid-edit is caught.
- **Monorepo map (products).** Writes the map with the existing atomic write, without overwriting (FR-12), then calls the existing registration, so the product exists in the same request. It never runs `git add` or commit. `map_committed` comes from whether `.blubird/repos.json` is tracked at the checkout's HEAD. It is computed during the poll, not per request.
- **Session start (sessions).** Before resolving the Documentation Repo for a docs-repo step, a repo whose `map` is `none` returns `needs a repo map` (409) instead of today's 400 text, so the UI can offer the choice. The same check applies to the FR-14 actions.
- **Step availability (prompts, blubird).** A blubird step is available when the installed plugin has `skills/<skill>/SKILL.md`. The registry reads the skill list that blubird status already holds.
- **Stale coordinator (dispatch, inbox).** The `queue.tsv` reader already passes states through. `in-progress-stale` is added to the needs-you set beside STOPPED. The Inbox item key is `coord_stale:<run>:<issue>`.

### Frontend

- **Start palette.** Gets the new Docs steps under Plan and loses `map-prds`. Unavailable steps are disabled with their reason (FR-11). The River gets a Docs column first. Ops drops the `map-prds` row.
- **Docs page (new, top-level, product-scoped).**
  - At the top: the gate status with its failure lines, collapsible.
  - Then module groups of doc rows (FR-6), then validation epics under their module (FR-10).
  - States: loading, the empty state of FR-6, gate unavailable with its reason, and a load error banner as on other pages.
  - Selecting a row opens the doc reader (FR-7) in the page's detail pane or drawer, as Features does.
- **Feature page.**
  - New Business tab (FR-9), reusing the doc reader.
  - The PRD tab, for Approved and Done, drops Edit and the change box. It shows a "Locked" line and the two FR-4 actions instead.
  - The Approve confirmation gets the FR-5 text.
- **Monorepo choice dialog (FR-12).** Opened by the 409 `needs a repo map` from any start. It shows the three choices and retries the original start after the monorepo choice.
  - When the repo has no `origin/staging`, it adds one line: blubird skills target `staging` unless the repo's own instructions name another base.
  - For a `local/` repo it shows only "add a GitHub remote first" and Cancel.
- **Products.** The product header and the Settings → products pane show **Map not committed** (FR-13).
- **Blubird banner (FR-11).** Shown app-wide, under the existing header banners, with the Update button.
- **Coordinator monitor.** Highlights the stale row with the hint (FR-15).

### Realtime and other components

- SSE `products{kind:"business"}` refreshes the Docs page and the Business tabs. Other events are unchanged.
- blubird sessions write the same files setu reads: `create-prd` approval, `refine-issues`, `implement-issue` after merge (its new "mark delivered" docs PR), `collect-docs`, `refine-docs` and `business-code-validator`. setu only reads `docs/business`. The only file setu writes that blubird also writes is the monorepo map (FR-12), and setu never overwrites one.
- project-coordinator owns `queue.tsv`. setu only reads it.

### Non-functional

- Building the business list for a product with 200 docs takes under 200 ms on a warm disk, using header-bounded reads.
- The gate runs at most once per product per change. It never blocks a request: a request returns the cached result and whether a run is in progress.
- No new Go or npm dependency. The checker is blubird's, run through `python3` when present.

### Threats and mitigations

Not affected. The data is local, internal and single-operator. The checker is run from the installed plugin with fixed arguments and no shell, and file paths keep the PRD path validation.

### Testing

| What | Tests |
|---|---|
| FR-1, FR-2, FR-11 (registry, stages, availability) | Go unit tests over the step list and a fake blubird install. Web tests for the palette groups and disabled steps |
| FR-3 (lock) | Go test: `PUT /api/prd` returns 409 for Approved and Done and leaves file and git unchanged. Web test: no Edit on an Approved PRD |
| FR-4, FR-5 (change actions, approve text) | Web tests on the start request bodies and the confirm text |
| FR-6, FR-7, FR-9, FR-10 (business docs, tab, validation epics) | Go parser tests over fixture docs in every mark and Timeline kind, plus malformed ones. Views tests for matching and validation epics from fixture issues. Web tests for the Docs page states and the Business tab |
| FR-8 (gate) | Go test with a fake `python3` in `internal/testutil/fakebin` for exit 0, 1, other and timeout, plus the no-python case |
| FR-12, FR-13, FR-14 (monorepo) | Go tests: monorepo endpoint (write, idempotent repeat, 409 on a different map, no origin), session start 409 on an unmapped repo, `map_committed` before and after a commit in a temp repo. Web test for the dialog's retry flow |
| FR-15 (stale coordinator) | Go test over a fixture `queue.tsv`. Inbox test for one item and its removal |
| Manual | One run of each new step against a real docs repo with blubird 1.2.0. The new screens screenshotted at desktop and mobile widths |

## Rollout and cost

- Everyone at once, no flag. setu is a single-operator local app with no feature-flag mechanism, and the removals fix actions that fail today.
- No billing impact beyond the Claude sessions the user starts.
- Release notes say that blubird 1.2.0 is required for the new steps.
- Rollback is reverting the release. Maps written by FR-12 stay in the user's repos and are valid blubird maps.
- After release, watch for Start errors on unmapped repos, and for gate runs reported unavailable.
- Docs updated in the same change: `docs/setu/API.md` (types, endpoints, §9.1 steps), `CONTEXT.md` (`map-prds` → the docs steps, Business doc, Monorepo map), and `docs/setu/engine/sessions.md` (its step list).

## Success metrics

None formally defined.

## Epics

- **E1 Align setu with blubird 1.2** — covers FR-1 to FR-15. Issue: #1073

## Decisions

- 2026-11-18 Scope is the skill palette, locked approved PRDs, a business docs view and the coordinator stale state — all four were found to diverge from blubird 1.2.0. Decided by: Masnun Siam, "Skill palette, Lock approved PRDs, Business docs view, Coordinator stale state".
- 2026-11-18 Business docs show as a Business tab on each feature plus a product-level Docs page — blubird now shares the module/feature path between PRD and doc, and docs exist for live features with no PRD. Decided by: Masnun Siam, "Feature tab + Docs page".
- 2026-11-18 The business docs view is read-only; changes go through the docs skills — every writer of `docs/business` must run blubird's gate. Decided by: Masnun Siam, "Read-only + run skills".
- 2026-11-18 A blubird older than 1.2.0 gets a banner with Update, and steps it lacks show as unavailable — uses the version setu already reads. Decided by: Masnun Siam, "Banner, update button".
- 2026-11-18 The three docs skills form a new Docs stage before PRD, in the River and in the Start palette's Plan group — mirrors blubird's stages 0 and 0b. Decided by: Masnun Siam, "New 'Docs' stage first".
- 2026-11-18 Business validation epics show on the Docs page under their module, never as Feature rows — Features stays one row per PRD. Decided by: Masnun Siam, "On the Docs page".
- 2026-11-18 setu runs blubird's checker when `docs/business` changes and shows its result — setu never re-implements the checker's rules. Decided by: Masnun Siam, "Yes, on change".
- 2026-11-18 Priority high — `map-prds` fails today and approved PRDs can be edited against blubird's lock. Decided by: Masnun Siam, "High".
- 2026-11-18 An approved PRD offers "New PRD for this change" and "One small task" in place of editing — these are exactly blubird's "After approval" paths. Decided by: Masnun Siam, "New PRD + One task".
- 2026-11-18 The Business tab shows the doc at the same path plus docs whose `planned` bullets link the PRD — the approval gate writes those links into other modules' docs. Decided by: Masnun Siam, "Same path + planned links".
- 2026-11-18 One epic — blubird's default; the parts share screens. Decided by: Masnun Siam, "One".
- 2026-11-18 Released to everyone at once — a single-operator local app with no flag mechanism. Decided by: Masnun Siam, "All at once".
- 2026-11-18 A stale coordinator issue is highlighted and adds an Inbox item with Implement and Open issue — the same treatment as STOPPED. Decided by: Masnun Siam, "Highlight + Inbox item".
- 2026-11-18 Docs is a top-level page next to Features — business docs are the lasting truth that Features changes. Decided by: Masnun Siam, "Top-level, next to Features".
- 2026-11-18 Monorepo support is in scope — setu blocks blubird's monorepo path, so a PRD can't be started on an unmapped repo. Raised by: Masnun Siam, "I think you have missed the monorepo support that has brought in the plugin our UI still expects the multi-repo structure and can't let me create PRDL the follow-ups on monorepo".
- 2026-11-18 setu asks "monorepo or onboard" before starting a docs step on an unmapped repo, writes the map itself and registers the product at once — Features then works immediately, with the same outcome as blubird's guard rail. Decided by: Masnun Siam, "Ask in setu first".
- 2026-11-18 The map is left uncommitted, to be carried by the next change's commit, and setu shows "Map not committed" until then — as blubird's guard rail says. Decided by: Masnun Siam, "Rides the next change".
- 2026-11-18 Process actions on unmapped repos lead to the monorepo choice instead of being hidden. Decided by: Masnun Siam, "Offer the choice instead".
- 2026-11-18 At approval, with no business docs in the repo, a new business doc `docs/business/ui/blubird-integration.md` is created, with R-1 to R-15 planned and not delivered — the approval gate needs a doc to validate against. Decided by: Masnun Siam, "Create a doc now".
- 2026-11-18 `docs/prds/ui/blubird-ui.md` is deprecated and not edited; this PRD does not reference its requirements. Decided by: Masnun Siam, "those are deprecated, leave those".

## Open questions

None.

## Related

- blubird 1.2.0 (`blubird-interactiveltd/agentic-workflow`): `references/engineering-workflow.md` ("Products and repos" guard rails, "Business documentation", "PRDs"), `templates/business-doc.md`, `skills/collect-docs`, `skills/refine-docs`, `skills/business-code-validator`, `skills/project-coordinator/scripts/normalize.jq` (the `in-progress-stale` state).
- `docs/prds/ui/blubird-ui.md` — deprecated, superseded where it differs.
- `docs/prds/headless-idle-guard.md` — the idle-guard Stop hook is unchanged in 1.2.0 and stays covered there.
- Business doc: `docs/business/ui/blubird-integration.md` (R-1 to R-15).
