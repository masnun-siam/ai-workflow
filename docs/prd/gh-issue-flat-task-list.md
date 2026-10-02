# PRD — gh-issue: PRD to flat task list

**Status:** Draft · **Date:** 2026-10-02 · **Repo:** masnun-siam/ai-workflow

## Overview
`/gh-issue` (and its mirror `/jira-to-gh`) will stop creating epic parents with sub-issues. When an input breaks down into 2 or more tasks, the command first writes a detailed, ordered list of small tasks to a saved doc. It then creates one flat, refined GitHub issue per task. Each issue is small enough for `/run-issue <n>` in full mode to reach the reviewed-PR handback (before pr-grind) within 30 minutes.

Codebase context:
- `commands/gh-issue.md` step 3.5 already decomposes after grilling, but the list is never saved and is capped at "~8 tasks". It is approved through three choices: Create as shown / Let me edit the list / File as one issue instead.
- `commands/gh-issue.md` `### 4-EPIC` creates a parent (the BRD as its body, labels `epic` and `refined`) and children (`epic-<parent>`). It links them with `aiw epic split` (`run-engine/epic.py`, sub_issues API plus a dependency-graph check) and builds a board with `aiw project-board`.
- The HARD RULE in `commands/gh-issue.md` allows only the temp body file, `gh` calls and the `/dump` write. A task-list file is not allowed today.
- `commands/jira-to-gh.md` Step 4.5 and 5-EPIC copy the gh-issue epic flow word for word. `run-engine/test_scripts.py` (around lines 1555–1723) checks the two stay in step and slices the markdown by literal headings (`"### 4-EPIC"`, `"### 5-EPIC"`, …).
- `/run-issue` has no time or size budget. The closest thing is the `lean` heuristic. `/prd` (`skills/prd/SKILL.md`) and `/dump` already set the save conventions for local, Obsidian and wiki.

## Problem
A PRD filed through `/gh-issue` becomes one epic parent and up to ~8 children. Those children are vertical slices, but they are often too large for `/run-issue` to finish in one short run. The decomposition only ever exists in chat, so nobody can review it, keep it or resume from it. The parent/child hierarchy adds machinery (sub_issues linking, epic mode, boards) that the user no longer wants.

## Users
Developers who use ai-workflow to turn a PRD, BRD, Obsidian note, Jira ticket or free text into issues that `/run-issue` then drives to a PR.

## Goals
- Every input that decomposes into 2 or more tasks produces a saved, ordered, very detailed task list before any issue is created.
- The list together with the issues covers the whole input. A reader could rebuild the source PRD from the list alone. This is a quality bar for the decomposer and not a separate section in the doc.
- Each task becomes one flat refined issue that full-mode `/run-issue` completes, up to the reviewed-PR handback, within 30 minutes.
- No parent issues and no hierarchy.

## Non-goals
- Removing `/run-issue` epic mode, `aiw epic split` or `aiw project-board`. Epics that are already open keep working.
- Applying the `lean` label to generated issues. All of them run in full mode.
- Adding a time budget or timer to `/run-issue` itself.
- Changing the single-issue path (decomposition gives 1 task).
- Creating a GitHub wiki for this repo.

## Requirements
- **FR-1 Trigger.** After grilling, step 3.5 decomposes as it does today. 1 task leads to the unchanged single-issue path. 2 or more tasks lead to the task-list flow.
  - Acceptance: a free-text bug that decomposes to 1 task creates exactly one issue and no task-list file.
- **FR-2 Size rubric.** Every task is one deliverable at a single layer, touches 3 or fewer production files (tests not counted), has 1–4 acceptance criteria that can be checked at that layer, has one verify command, and adds no new dependency. A task that fails any of these is split until it passes. There is no cap on the number of tasks; the old "~8" guard is removed.
  - Layer units: DB migration (one file) · service / business logic · API endpoint (route, controller, request validation and resource/response together) · one UI unit (a single page or component).
  - Each additional capability repeats the layers it needs. Example: "add authentication" gives migration → auth service → API endpoint → UI. A "Google login" requirement then adds its own service-logic task, its own endpoint task (controller, request, resource) and its own frontend task.
  - Acceptance: no task in a generated list spans two layers or names more than 3 production files. The sample PRD "authentication + Google login" yields the four layer tasks plus three Google tasks, in that order.
- **FR-3 Task detail.** Each task records, in order:
  - a sequence number
  - a title
  - the outcome
  - the files and symbols it touches (from the GitNexus lookup)
  - acceptance criteria
  - the verify command
  - `Depends on: task <k>`
  - a slot for the issue number

  The list is sequential: list order is creation order and a valid dependency order.
  - Acceptance: every task has every field filled. No `[placeholders]` are left in the saved doc.
- **FR-4 Approval.** The list is shown in one AskUserQuestion with two choices: **"Create as shown"** and **"Let me edit the list"**. The second loops through revise and re-present with no round limit. "File as one issue instead" is removed.
  - Acceptance: the approval question offers exactly those two choices.
- **FR-5 Save.** After approval and before any issue is created, the list is written to `docs/tasks/<slug>.md`. At the same gate the user can add Obsidian and/or the GitHub wiki, using the same conventions as `/prd` Step 7:
  - Obsidian: `05-Work/<Project>/<Feature>/Tasks.md`, written through the `obsidian vault=notes` CLI
  - wiki: `Tasks-<Title>.md`, pushed only after explicit confirmation

  The HARD RULE gains an explicit exception for these writes only.
  - Acceptance: `docs/tasks/<slug>.md` exists before the first `gh issue create`.
- **FR-6 Flat issue creation.** Issues are created one at a time in list order with no further prompts. Each issue:
  - has the full refined body (What, Why, Out of Scope, Context / Affected Code, Acceptance Criteria, How, Non-functional Constraints, Assumptions, Dependencies / Blockers, Notes), with context inlined
  - carries the labels `refined`, `prd-<slug>`, its type label and its scope labels, and never `lean`
  - links back to the task-list doc in Notes
  - has `Depends on: #n` lines resolved from earlier tasks

  The skill makes no parent, no sub_issues call, no `aiw epic split` call and no board.
  - Acceptance: `gh issue list --label prd-<slug>` returns every created issue, and none of them has a parent.
- **FR-7 Write-back.** As each issue is created, its `#n` is written into its task's slot in the local list. Other destinations are updated where practical.
  - Acceptance: after a complete run, every task in `docs/tasks/<slug>.md` has an issue number.
- **FR-8 Per-issue checks, batch prompts.** The factchecker runs once per issue. Assignee and project fields are asked once and applied to every issue.
- **FR-9 Resume.** If `docs/tasks/<slug>.md` already exists, the skill reads it, shows which tasks have no issue number yet, and creates only those, in order. It reuses the issue numbers that already exist for `Depends on:` lines.
  - Acceptance: re-running after a failure at task k creates only tasks k..N and duplicates nothing.
- **FR-10 Partial failure.** A failed create stops the loop. The skill reports which tasks were created and which are missing, and offers **"Retry the missing ones"** or **"Stop here"**. It never deletes issues that were already created.
- **FR-11 jira-to-gh parity.** `/jira-to-gh` replaces its 5-EPIC branch with the same flat task-list flow. The mirror tests in `run-engine/test_scripts.py` are updated for the new headings and keep passing.
- **FR-12 Remove 4-EPIC.** The `### 4-EPIC` branch is deleted from `commands/gh-issue.md`.
- **FR-13 /run-issue handoff.** When `/run-issue` invokes gh-issue and the result is 2 or more issues, gh-issue returns their numbers in order and `/run-issue` stops after listing them. It does not run any of them automatically.
  - Acceptance: `/run-issue "<PRD path>"` ends with an ordered list of issue URLs and no Ledger beyond preflight.

## Edge cases
- An input that yields exactly 1 task follows the single-issue path, with no list and no `prd-<slug>` label.
- The slug collides with an unrelated existing `docs/tasks/<slug>.md`. The resume preview shows the existing tasks, and the user can stop and rename.
- A task cannot meet the rubric without touching more than 3 files, for example a cross-cutting rename. The decomposer must split it further within its layer. If it truly can't, it flags the task in the list for the user to decide at approval.
- A dependency edge points forward in the list. This is invalid, and the list must be reordered before it is shown.
- Obsidian is unreachable or the wiki is missing. The local save still happens, and the skill reports which destinations failed.
- The `prd-<slug>` label does not exist. Ensure-create it before the first create, the same way `refined` is handled.
- `/run-issue` invokes gh-issue and gets N flat issues back. It stops and lists them (FR-13).

## Success metrics
- Pick a real PRD and run `/run-issue` on each of its generated issues. At least 80% reach the reviewed-PR handback (before pr-grind) within 30 minutes, measured from the timestamps in each Ledger's trace.
- Coverage: every requirement in the source PRD maps to at least one task in the saved list (reviewer spot-check).

## Decisions
- No parent and no hierarchy: flat issues only — the user wants small issues with nothing else around them.
- Issues are linked by a `prd-<slug>` label, `Depends on: #n` lines and a link to the list — keeps order and grouping without the sub_issues API.
- Every issue runs in full mode and is never `lean` — smallness has to come from the task itself, not from a lighter roster.
- Tasks are sliced by layer (migration, service, API endpoint, UI), not as vertical end-to-end slices — this reverses the old epic rule, because a layer unit is the smallest thing that fits a 30-minute full-mode run. Order follows the dependency chain: migration → service → endpoint → UI.
- The size rubric is one layer-scoped deliverable, ≤3 production files, 1–4 acceptance criteria, one verify command and no new dependency — a concrete check that stands in for the 30-minute target.
- The count cap is removed — size is set by the rubric, not by a count.
- The list holds detailed, sequential tasks only, with no PRD header section — rebuilding the PRD is a quality bar for the decomposer, not part of the doc.
- The list is approved once and the issues are then created automatically — one prompt is enough for N issues.
- The list is always saved locally to `docs/tasks/<slug>.md`, and Obsidian or the wiki can be added at the gate — matches `/prd`.
- "File as one issue instead" is removed — two or more tasks always produce a list.
- An existing list is resumed — makes partial runs recoverable.
- jira-to-gh changes too — the two commands keep mirroring each other.
- Epic machinery is removed from gh-issue only — open epics still run.
- When gh-issue returns N issues to `/run-issue`, `/run-issue` stops and lists them — the human picks what to run next.

## Open questions
- The Obsidian feature folder for `Tasks.md`: reuse the source note's feature folder when the input came from Obsidian, or always resolve it the way `/dump` does? (Implementation detail for the spec.)
- How should the slug be derived for free-text inputs that have no title?

## Related
- `commands/gh-issue.md`
- `commands/jira-to-gh.md`
- `commands/run-issue.md`
- `skills/prd/SKILL.md`
- `skills/dump/SKILL.md`
- `docs/superpowers/specs/2026-09-19-epic-decomposition-design.md`
