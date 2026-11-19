# Blubird integration — business documentation

**Module:** ui · **Updated:** 2026-11-19 · **Repos:** ai-workflow

The source of truth for how this feature works for the business, as it is live today. A PRD is the temporary source of truth for one change, from request to delivery, and locked once approved; after delivery, this doc says what is true. Meeting notes, chats and specs are the material it was built from, never the truth on their own.

## What it does

setu runs the blubird plugin's skills as headless Claude Code sessions and shows their artifacts: PRDs, epics, issues, coordinator runs and, from blubird 1.2, business docs. This doc covers how setu follows blubird's workflow rules. Every rule below was delivered by the blubird 1.2 alignment PRD on 2026-11-19.

## Rules

- **R-1 Only existing skills are offered.** The step registry offers no skill blubird 1.2 lacks (`map-prds` is gone) and offers `collect-docs`, `refine-docs` and `business-code-validator`, each run in the product's Documentation Repo.
  - Acceptance: Start lists the three docs steps and not `map-prds`; each starts `/blubird:<skill> <args>` in the docs repo.
  - Delivery: delivered 2026-11-19 (#1083), PRD `docs/prds/ui/blubird-1-2.md` FR-1
  - Sources: `docs/prds/ui/blubird-1-2.md` FR-1
- **R-2 Docs stage first.** The three docs steps form a Docs stage before PRD, first in the River and under Plan in Start.
  - Acceptance: a running `refine-docs` session shows in the River's Docs column, left of PRD.
  - Delivery: delivered 2026-11-19 (#1083), PRD `docs/prds/ui/blubird-1-2.md` FR-2
  - Sources: `docs/prds/ui/blubird-1-2.md` FR-2
- **R-3 Approved PRDs are locked.** An Approved or Done PRD is read-only in setu and the server refuses to write it.
  - Acceptance: no Edit on an Approved PRD; `PUT /api/prd` returns 409 and changes nothing.
  - Delivery: delivered 2026-11-19 (#1084), PRD `docs/prds/ui/blubird-1-2.md` FR-3
  - Sources: `docs/prds/ui/blubird-1-2.md` FR-3
- **R-4 Approved work changes through a new PRD or one task.** A locked PRD offers "New PRD for this change" and "One small task" (under its epic when it has one).
  - Acceptance: each action starts one session whose prompt holds the text and the approved PRD's path.
  - Delivery: delivered 2026-11-19 (#1084), PRD `docs/prds/ui/blubird-1-2.md` FR-4
  - Sources: `docs/prds/ui/blubird-1-2.md` FR-4
- **R-5 Approval says it validates against business docs.** The Approve PRD confirmation says Claude checks the PRD against the business docs, asks to confirm each rule it adds or changes, then creates the epic.
  - Acceptance: the confirm dialog shows that text.
  - Delivery: delivered 2026-11-19 (#1084), PRD `docs/prds/ui/blubird-1-2.md` FR-5
  - Sources: `docs/prds/ui/blubird-1-2.md` FR-5
- **R-6 Business docs are listed per product.** A top-level Docs page lists every doc under `docs/business/<module>/<feature>.md` by module, with its rule, delivery-mark, planned and open-question counts; empty, it names Collect docs.
  - Acceptance: fixture docs in two modules show two groups with correct counts.
  - Delivery: delivered 2026-11-19 (#1085, #1088), PRD `docs/prds/ui/blubird-1-2.md` FR-6
  - Sources: `docs/prds/ui/blubird-1-2.md` FR-6
- **R-7 Business docs are read-only in setu.** A doc opens rendered with Refine and Validate actions; setu never edits it.
  - Acceptance: opening a doc renders it; each action starts its step with the doc's path.
  - Delivery: delivered 2026-11-19 (#1085, #1088), PRD `docs/prds/ui/blubird-1-2.md` FR-7
  - Sources: `docs/prds/ui/blubird-1-2.md` FR-7
- **R-8 The docs gate is shown.** setu runs blubird's checker on change and shows pass, fail with its lines, or unavailable with the reason.
  - Acceptance: an undated Timeline bullet shows Gate fails with the checker's line.
  - Delivery: delivered 2026-11-19 (#1085, #1088), PRD `docs/prds/ui/blubird-1-2.md` FR-8
  - Sources: `docs/prds/ui/blubird-1-2.md` FR-8
- **R-9 A feature shows its business docs.** A feature's Business tab shows the doc at the same module and file name as its PRD, then docs whose `planned` bullets link the PRD.
  - Acceptance: both kinds of match show; none shows the empty state.
  - Delivery: delivered 2026-11-19 (#1085, #1088), PRD `docs/prds/ui/blubird-1-2.md` FR-9
  - Sources: `docs/prds/ui/blubird-1-2.md` FR-9
- **R-10 Business validation epics show under their module.** Open `epic` + `business-validation` issues show on the Docs page with their children and the usual actions, never as Feature rows.
  - Acceptance: a `Business validation: Auth` epic shows under `auth` with its children.
  - Delivery: delivered 2026-11-19 (#1085, #1088), PRD `docs/prds/ui/blubird-1-2.md` FR-10
  - Sources: `docs/prds/ui/blubird-1-2.md` FR-10
- **R-11 blubird 1.2.0 is required.** An older install shows a banner with Update; steps it lacks are disabled with the reason.
  - Acceptance: with 0.28.0 installed, the banner shows and `collect-docs` is disabled.
  - Delivery: delivered 2026-11-19 (#1083), PRD `docs/prds/ui/blubird-1-2.md` FR-11
  - Sources: `docs/prds/ui/blubird-1-2.md` FR-11
- **R-12 An unmapped repo can become a monorepo.** Before a docs-repo step on a repo with no map and no pointer, setu offers monorepo (writes the one-entry `.blubird/repos.json`, registers the product, then starts), agentic-onboard, or cancel.
  - Acceptance: choosing monorepo writes the map, the product appears and `create-prd` starts in that repo.
  - Delivery: delivered 2026-11-19 (#1087, #1090), PRD `docs/prds/ui/blubird-1-2.md` FR-12
  - Sources: `docs/prds/ui/blubird-1-2.md` FR-12
- **R-13 The monorepo map rides the next change.** setu never commits the map; the product shows "Map not committed" until it is tracked.
  - Acceptance: the note shows after R-12 and clears once the file is committed.
  - Delivery: delivered 2026-11-19 (#1087, #1090), PRD `docs/prds/ui/blubird-1-2.md` FR-13
  - Sources: `docs/prds/ui/blubird-1-2.md` FR-13
- **R-14 Unmapped repos offer the monorepo choice.** Process actions on an unmapped repo are shown and lead to the R-12 choice.
  - Acceptance: Refine on an unmapped repo shows the choice, then starts `refine-issues`.
  - Delivery: delivered 2026-11-19 (#1087, #1090), PRD `docs/prds/ui/blubird-1-2.md` FR-14
  - Sources: `docs/prds/ui/blubird-1-2.md` FR-14
- **R-15 Stale coordinator issues need you.** An `in-progress-stale` queue issue is highlighted with blubird's hint and adds one Inbox item with Implement and Open issue.
  - Acceptance: one stale line in a fixture queue gives one highlighted row and one Inbox item.
  - Delivery: delivered 2026-11-19 (#1086), PRD `docs/prds/ui/blubird-1-2.md` FR-15
  - Sources: `docs/prds/ui/blubird-1-2.md` FR-15

## Decisions

- 2026-11-18 Start setu's business docs with this feature, at the blubird 1.2 alignment PRD's approval — the repo had none to validate against. By: team, "Create a doc now". [PRD](../../prds/ui/blubird-1-2.md)

## Open questions

None.

## Critical checks

None.

## Timeline

- 2026-11-18 planned (team) R-1, R-2, R-3, R-4, R-5, R-6, R-7, R-8, R-9, R-10, R-11, R-12, R-13, R-14, R-15 align setu with blubird 1.2, PRD [blubird-1-2](../../prds/ui/blubird-1-2.md)
- 2026-11-19 delivered R-1, R-2, R-11 docs steps replace map-prds, docs stage and version gate [#1083](https://github.com/masnun-siam/ai-workflow/pull/1083)
- 2026-11-19 delivered R-3, R-4, R-5 approved PRDs are locked [#1084](https://github.com/masnun-siam/ai-workflow/pull/1084)
- 2026-11-19 delivered R-6, R-7, R-8, R-9, R-10 business docs reader, gate and API [#1085](https://github.com/masnun-siam/ai-workflow/pull/1085), Docs page and Business tab [#1088](https://github.com/masnun-siam/ai-workflow/pull/1088)
- 2026-11-19 delivered R-12, R-13, R-14 monorepo choice for unmapped repos, server [#1087](https://github.com/masnun-siam/ai-workflow/pull/1087) and web [#1090](https://github.com/masnun-siam/ai-workflow/pull/1090)
- 2026-11-19 delivered R-15 stale coordinator issues need you [#1086](https://github.com/masnun-siam/ai-workflow/pull/1086)

## Related

- PRD [docs/prds/ui/blubird-1-2.md](../../prds/ui/blubird-1-2.md)
