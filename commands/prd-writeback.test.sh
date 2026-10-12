#!/usr/bin/env bash
# RED/GREEN check for #234: resolved Open questions are written back into the PRD.
# Run from the repo root: bash commands/prd-writeback.test.sh
set -u
cd "$(dirname "$0")/.." || exit 1
fail=0
need() { # file, fixed string, label
  grep -qF -- "$2" "$1" || { echo "FAIL: $1 lacks $3"; fail=1; }
}
g=commands/gh-issue.md
j=commands/jira-to-gh.md
need $g '3.7. **Write resolved decisions back into the PRD.**' 'step 3.7'
need $g '`<decision> — <why>`' 'the decision shape'
need $g 'stays exactly where it is' 'unresolved items left untouched'
need $g 'failed — <reason>' 'the failed — <reason> report line'
grep -q 'never stops issue creation' $g || { echo "FAIL: $g lacks never-stops-creation rule"; fail=1; }
need $g 'step 3.7 PRD write-back is a second' 'the amended HARD RULE exception'
need $g '**Step 3.7 (PRD write-back):**' 'the Flow auto mode decision'
need $g 'Before the return, report step 3.7' 'per-destination report before the next line'
need $j '## Step 4.7 — Write resolved decisions back into the PRD' 'Step 4.7'
need $j 'failed — <reason>' 'the failed — <reason> report line'
[ $fail -eq 0 ] && echo "PASS" || { echo "FAILED"; exit 1; }
