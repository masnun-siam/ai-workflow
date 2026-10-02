# Tasks — gh-issue: PRD to flat task list

**Source PRD:** `docs/prd/gh-issue-flat-task-list.md` · **Repo:** masnun-siam/ai-workflow · **Label:** `prd-gh-issue-flat-task-list` · **Date:** 2026-10-02

Order is creation order and a valid dependency order. Verify command for every task: `python3 run-engine/test_scripts.py` (exit 0, currently 247 checks).

## Task 1 — gh-issue step 3.5: rubric, two-choice approval, flat routing
- **Outcome:** Step 3.5 sizes tasks by the layer rubric (one layer-scoped deliverable, ≤3 production files, 1–4 acceptance criteria, one verify command, no new dependency), drops the "~8 tasks" guard, offers exactly two choices, and routes 2+ tasks to the flat flow.
- **Files:** `commands/gh-issue.md` (step 3.5, lines 45–65); `run-engine/test_scripts.py` (assertions near 2360–2368 on the choice labels).
- **Acceptance:**
  - The approval question offers exactly "Create as shown" and "Let me edit the list"; "File as one issue instead" is gone.
  - No "~8" guard text remains in step 3.5.
  - 1 task still routes to step 4 unchanged; 2+ tasks route to the flat flow.
  - The rubric text states the layer units: migration, service, API endpoint, one UI unit.
- **Depends on:** none
- **Issue:** #78

## Task 2 — gh-issue: save the task list and add the HARD RULE exception
- **Outcome:** A new step after approval writes `docs/tasks/<slug>.md` before any issue is created, offers Obsidian/wiki at the same gate, and the HARD RULE allows exactly those writes.
- **Files:** `commands/gh-issue.md` (HARD RULE lines 24–36; new step after 3.5).
- **Acceptance:**
  - The HARD RULE lists the task-list writes as the only new exception.
  - The step writes the local file before the first `gh issue create`.
  - Obsidian and wiki follow `skills/prd/SKILL.md` Step 7 conventions; wiki push needs its own confirmation.
- **Depends on:** Task 1
- **Issue:** #79

## Task 3 — gh-issue: flat creation loop replaces 4-EPIC
- **Outcome:** `### 4-EPIC` is replaced by a flat loop creating one refined issue per task in list order with labels `refined` and `prd-<slug>` (ensure-created), never `lean`, `Depends on: #n` resolved from earlier tasks, a link to the task-list doc in Notes, and each `#n` written back into the list. No parent, no `aiw epic split`, no board.
- **Files:** `commands/gh-issue.md` (108–212); `run-engine/test_scripts.py` (tests slicing `### 4-EPIC` near 1712–1737 and 2370–2387).
- **Acceptance:**
  - No `epic` or `epic-<parent>` label and no `aiw epic split` in the flat flow.
  - `prd-<slug>` is ensure-created once before the first create and applied at creation time.
  - The test suite passes with the updated slicing.
- **Depends on:** Task 2
- **Issue:** #80

## Task 4 — gh-issue: resume and partial failure
- **Outcome:** An existing `docs/tasks/<slug>.md` is read and only tasks without an issue number are created; a failed create stops the loop and offers "Retry the missing ones" / "Stop here", never deleting created issues.
- **Files:** `commands/gh-issue.md` (flat loop); `run-engine/test_scripts.py` (assert both choice labels in the flat section).
- **Acceptance:**
  - Re-running after a failure at task k creates only tasks k..N.
  - Existing issue numbers are reused for `Depends on:` lines.
  - The report names created and missing tasks.
- **Depends on:** Task 3
- **Issue:** #81

## Task 5 — gh-issue: per-issue factcheck, batch assignee/project, return list
- **Outcome:** The factchecker runs once per created issue; assignees and project fields are asked once and applied to every issue; the command returns the ordered issue URLs, and when `/run-issue` invoked it the hand-back is that list.
- **Files:** `commands/gh-issue.md` (194–208, 245–247).
- **Acceptance:**
  - Assignee confirmation is asked once for the whole batch.
  - The closing paragraph returns the ordered issue list for 2+ issues.
- **Depends on:** Task 3
- **Issue:** #82

## Task 6 — jira-to-gh Step 4.5: mirror the new decompose and save steps
- **Outcome:** `commands/jira-to-gh.md` Step 4.5 matches gh-issue's rubric, two-choice approval, flat routing and save step.
- **Files:** `commands/jira-to-gh.md` (83–111).
- **Acceptance:**
  - Same rubric and two choices as gh-issue.
  - Jira's own "epic" wording (lines 23, 28) is untouched.
- **Depends on:** Task 2
- **Issue:** #83

## Task 7 — jira-to-gh: flat flow replaces 5-EPIC
- **Outcome:** `### 5-EPIC` is replaced by the same flat flow, and the issue #42 mirror tests are updated.
- **Files:** `commands/jira-to-gh.md` (140–234); `run-engine/test_scripts.py` (1626–1670, 1712–1737).
- **Acceptance:**
  - Body section list equals gh-issue's.
  - Every "Step N" reference resolves.
  - The test suite passes.
- **Depends on:** Task 3, Task 6
- **Issue:** #84

## Task 8 — run-issue Preflight: stop and list flat issues
- **Outcome:** When `/gh-issue` returns 2+ issues, `/run-issue` Preflight step 2 prints them in order and stops. Epic mode is untouched.
- **Files:** `commands/run-issue.md` (223–238).
- **Acceptance:**
  - `/run-issue "<PRD path>"` ends with an ordered list of issue URLs and no Ledger beyond preflight.
  - Epic mode (1076+) is not edited.
- **Depends on:** Task 5
- **Issue:** #85

## Task 9 — docs: README, HOW-IT-WORKS, CHANGELOG
- **Outcome:** The docs describe the flat task-list flow and a new CHANGELOG entry records it.
- **Files:** `README.md` (line 213); `docs/HOW-IT-WORKS.md` (323–352, 386); `CHANGELOG.md`.
- **Acceptance:**
  - README no longer says gh-issue files "a parent plus children".
  - CHANGELOG has a new entry; old entries are unchanged.
- **Depends on:** Tasks 1–8
- **Issue:** #86
