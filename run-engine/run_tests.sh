#!/usr/bin/env bash
# Run every run-engine/test_*.py; exit nonzero if any fails. Used by the pre-push hook and CI.
# ponytail: serial (~2 min); run the files in parallel if this starts getting skipped.
set -u
# Called from git hooks: keep the tests' temp repos from writing into this repo's index.
unset GIT_INDEX_FILE GIT_DIR GIT_WORK_TREE
cd "$(dirname "$0")" || exit 1
# Tests must not read the user's real plugin data (config.json, state): use a throwaway dir unless one is given.
if [ -z "${CLAUDE_PLUGIN_DATA:-}" ]; then
  CLAUDE_PLUGIN_DATA=$(mktemp -d)
  export CLAUDE_PLUGIN_DATA
  trap 'rm -rf "$CLAUDE_PLUGIN_DATA"' EXIT
fi
failed=()
for t in test_*.py; do
  if ! out=$(python3 "$t" 2>&1); then
    failed+=("$t")
    printf 'FAIL %s\n%s\n' "$t" "$out"
  fi
done
if ((${#failed[@]})); then
  echo "${#failed[@]} test file(s) failed: ${failed[*]}"
  exit 1
fi
echo "all test files passed"
