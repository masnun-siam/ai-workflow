#!/usr/bin/env bash
# Check for #235: task-list rubric covers FR coverage, deploy/ops, user-visible, unique titles, Design link.
# Run from the repo root: bash commands/rubric-235.test.sh
set -u
cd "$(dirname "$0")/.." || exit 1
fail=0
need() { # file, fixed string, label
  grep -qF -- "$2" "$1" || { echo "FAIL: $1 lacks $3"; fail=1; }
}
for f in commands/gh-issue.md commands/jira-to-gh.md; do
  need $f 'Covers: FR-n' 'Covers: FR-n line (AC1)'
  need $f 'covered by no task' 'uncovered-FR rebuild rule (AC1)'
  need $f '`deploy/ops` task, labelled `infra`' 'deploy/ops task labelled infra (AC2)'
  need $f 'User-visible: yes|no' 'User-visible line (AC3)'
  need $f 'first user-visible task' 'first user-visible task in header (AC3)'
  need $f 'Two tasks with the same title fail the rubric' 'duplicate title rule (AC4)'
  need $f 'Design: <url>' 'Design: <url> (AC5)'
done
[ $fail -eq 0 ] && echo "PASS" || { echo "FAILED"; exit 1; }
