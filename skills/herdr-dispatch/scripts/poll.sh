#!/usr/bin/env bash
# poll.sh <owner/repo> <issue>...   env PREV="5928=working,5929=blocked"
# Loops every 120s; exits printing "<n> <state>" for the first issue whose state differs from PREV.
# states: working | blocked (tab waits on a human) | ready | not-ready | red (Gate 2 verdicts)
set -uo pipefail
repo=$1; shift
state() {
  n=$1
  body=$(gh issue view "$n" -R "$repo" --json comments -q '[.comments[].body|select(startswith("🤖 /run-issue report"))]|last // ""')
  if [[ -n $body ]]; then
    [[ $body == *"Not ready"* ]] && { echo not-ready; return; }
    pr=$(grep -oE 'pull/[0-9]+' <<<"$body" | head -1 | cut -d/ -f2)
    chk=$(gh pr checks "$pr" -R "$repo" 2>/dev/null)
    grep -q pending <<<"$chk" && { echo working; return; }
    grep -qE '\sfail\s' <<<"$chk" && { echo red; return; }
    echo ready; return
  fi
  herdr tab list | jq -r --arg l "issue-$n" '.result.tabs[]|select(.label|endswith($l))|.agent_status' | grep -q blocked && echo blocked || echo working
}
while :; do
  for n in "$@"; do
    s=$(state "$n")
    prev=$(tr ',' '\n' <<<"${PREV:-}" | sed -n "s/^$n=//p")
    [[ ${prev:-working} != "$s" ]] && { echo "$n $s"; exit 0; }
  done
  sleep 120
done
