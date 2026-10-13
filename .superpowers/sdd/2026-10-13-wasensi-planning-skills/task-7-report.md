# Task 7 report

## Implemented
- commands/run-issue.md Preflight 2: "No issue URL" bullet drops the 4-FLAT clause; the "ordered list" branch is replaced by "No issue, and its last line is `-> next: /create-prd ...`" (print the line, say a PRD is needed first, end with no ledger/worktree/aiw init).
- 3.5: "Its children get linked by `/refine-issues` on its task list, or by `aiw epic split` ...".
- Epic mode step 0 (wording only), 3 edits: "only `/gh-issue` writes it -- on the machine that filed the epic" -> "only `/refine-issues` writes it (via `aiw epic split`) -- on the machine that refined the epic"; "an epic `/gh-issue` created" -> "an epic `/refine-issues` split"; "as `/gh-issue` does" -> "as `/refine-issues` does".
- commands/gh-issue.md: close paragraph prints `-> next: herdr-dispatch <n>` only on a standalone run; under /run-issue it prints no such line and hands back to Preflight 3. 3.5 bullet now says the /create-prd line is "printed under `/run-issue` too, which branches on it".

## Tests (run-engine/test_scripts.py)
- #85: NOURL rewritten; LIST1-4/LIST3E removed; LISTPRD added (whole-bullet pin, plus no 4-FLAT/herdr-dispatch/ordered list/Epic mode in step 2); ONE, HARD kept; branch-order pin updated; 3.5 pins for /refine-issues and absence of "re-running `/gh-issue`".
- #184 close pin: standalone-only herdr-dispatch + no-line-under-run-issue; new pin that the 3.5 /create-prd line is printed under /run-issue.
- S35_SHA and EPIC_SHA re-pinned, computed with the test's normalisation (whitespace-joined slice; Epic mode up to "\n## ").
- Result: `bash run-engine/run_tests.sh` -> all test files passed.

## TDD evidence
- RED: first run failed on NOURL pin (`st2.count(sent)==1`) against unedited run-issue.md; later with original gh-issue.md restored, the #184 close pin fails (line ~4491).
- GREEN after edits and re-pins.

## Deviations
- EPIC_SHA re-pinned (per ruling); brief said leave alone.
- Added NOURL pin and gh-issue pins beyond the brief (per ruling).
- LISTPRD text adds "no worktree and no `aiw init`" (kept from the old clean-stop wording).

## Concerns
- run-issue.md 3.5 still says `epic`+`prd-<slug>` is "how `/gh-issue` labels its parents"; that is now probably /create-prd approve. Left alone (S35 pin; outside ruling). Task 9 or a follow-up should check.
- No CHANGELOG/docs touched.
