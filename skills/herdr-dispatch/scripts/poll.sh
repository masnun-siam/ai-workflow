#!/usr/bin/env bash
# poll.sh <owner/repo> <issue>...   env PREV="5928=working,5929=blocked"
# Loops every 120s; exits printing "<n> <state>" for the first issue whose state differs from PREV.
# An issue may be given as other/repo#n (an epic's sub-issue in another repo); a bare n uses <owner/repo>.
# env READY=pr (a --cmd that posts no run-issue report): ready = non-draft PR on branch issue-<n>-* with green checks;
#   merged = that PR is merged but the issue is still open. env BASE=<branch> limits the PR lookup to that base.
# states: working | blocked (tab waits on a human) | idle (tab stopped, no verdict) | ready | merged | done (issue closed) | not-ready | red
set -uo pipefail
default_repo=$1; shift
state() {
  n=$1
  [[ $(gh issue view "$n" -R "$repo" --json state -q .state) == CLOSED ]] && { echo "done"; return; }
  body=$(gh issue view "$n" -R "$repo" --json comments -q '[.comments[].body|select(startswith("🤖 /run-issue report"))]|last // ""')
  if [[ -n $body ]]; then
    [[ $body == *"Not ready"* ]] && { echo not-ready; return; }
    pr=$(grep -oE 'pull/[0-9]+' <<<"$body" | head -1 | cut -d/ -f2)
    chk=$(gh pr checks "$pr" -R "$repo" 2>/dev/null)
    grep -q pending <<<"$chk" && { echo working; return; }
    grep -qE '\sfail\s' <<<"$chk" && { echo red; return; }
    echo ready; return
  fi
  if [[ ${READY:-} == pr ]]; then
    [[ -n $(gh pr list -R "$repo" --state merged ${BASE:+--base "$BASE"} --json headRefName -q "[.[]|select(.headRefName|startswith(\"issue-$n-\"))][0].headRefName // empty") ]] && { echo merged; return; }
    pr=$(gh pr list -R "$repo" --state open ${BASE:+--base "$BASE"} --json number,headRefName,isDraft -q "[.[]|select((.headRefName|startswith(\"issue-$n-\")) and (.isDraft|not))][0].number // empty")
    if [[ -n $pr ]]; then
      chk=$(gh pr checks "$pr" -R "$repo" 2>/dev/null)
      grep -q pending <<<"$chk" && { echo working; return; }
      grep -qE '\sfail\s' <<<"$chk" && { echo red; return; }
      echo ready; return
    fi
  fi
  tab=$(herdr tab list | jq -r --arg l "issue-$n" '.result.tabs[]|select(.label|endswith($l))|"\(.tab_id) \(.agent_status)"')
  case ${tab#* } in
    blocked) echo blocked ;;
    idle|done)
      # a tab waiting on its own background monitors/shells wakes itself: still working
      pane=$(herdr pane list | jq -r --arg t "${tab% *}" '.result.panes[]|select(.tab_id==$t)|.pane_id' | head -1)
      herdr pane read "$pane" 2>/dev/null | tail -3 | grep -qE '[0-9]+ (monitor|shell)' && echo working || echo idle ;;
    *) echo working ;;
  esac
}
while :; do
  for x in "$@"; do
    n=${x##*#}; repo=$default_repo; [[ $x == *#* ]] && repo=${x%#*}
    s=$(state "$n")
    prev=$(tr ',' '\n' <<<"${PREV:-}" | sed -n "s/^$n=//p")
    [[ ${prev:-working} != "$s" ]] && { echo "$n $s"; exit 0; }
  done
  sleep 120
done
