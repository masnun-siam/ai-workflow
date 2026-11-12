#!/usr/bin/env bash
# Collect the facts for a <head> -> <base> release PR, as markdown on stdout.
# Read-only: fetches, reads git and gh, never writes to GitHub.
#
# usage: release-data.sh [head=staging] [base=master]
#
# RELEASE_PRS="5876 5934 ..." skips PR discovery and reports exactly those PRs.
# Use it for a partial release branch built by cherry-picking: cherry-picked
# commits are new commits, so git ancestry can no longer find their PRs.
set -uo pipefail

HEAD_BR=${1:-staging}
BASE_BR=${2:-master}
H=origin/$HEAD_BR
B=origin/$BASE_BR

git fetch -q origin "$HEAD_BR" "$BASE_BR" || { echo "fetch failed" >&2; exit 1; }
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner) || exit 1
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "# Release data: $REPO $HEAD_BR -> $BASE_BR"
echo
echo "## Branches"
echo "- ahead (commits on $HEAD_BR not on $BASE_BR): $(git rev-list --count "$B..$H")"
echo "- behind (commits on $BASE_BR not on $HEAD_BR): $(git rev-list --count "$H..$B")"
echo "- content diff: $(git diff --shortstat "$B" "$H")"
echo "- head sha: $(git rev-parse --short "$H")"

OPEN=$(gh pr list --base "$BASE_BR" --head "$HEAD_BR" --state open --json number,url --jq '.[] | "#\(.number) \(.url)"')
echo "- open release PR: ${OPEN:-none}"

LAST=$(gh pr list --base "$BASE_BR" --head "$HEAD_BR" --state merged --limit 1 \
  --json number,mergedAt,title --jq '.[0] // empty | "\(.number)\t\(.mergedAt)\t\(.title)"')
if [ -n "$LAST" ]; then
  IFS=$'\t' read -r LAST_N CUTOFF LAST_T <<<"$LAST"
  echo "- previous release: #$LAST_N merged $CUTOFF ($LAST_T)"
else
  CUTOFF=$(git log -1 --format=%cI "$(git merge-base "$B" "$H")")
  echo "- previous release: none found; cutoff = merge-base date $CUTOFF"
fi

# Files that actually differ between the branches. A PR only counts as release
# content if it touches one of these: commit ranges over-report when earlier
# releases were squash-merged, because squashing never carries the commits over.
git diff --name-only "$B" "$H" | sort >"$TMP/files"

: >"$TMP/included"
: >"$TMP/excluded"
if [ -n "${RELEASE_PRS:-}" ]; then
  for n in $RELEASE_PRS; do
    gh pr view "$n" --json number,baseRefName,headRefName,title \
      --jq '[.number, .baseRefName, .headRefName, .title] | @tsv' >>"$TMP/included"
  done
  echo "n/a: discovery skipped, PR list given via RELEASE_PRS" >>"$TMP/excluded"
  : >"$TMP/candidates"
else
  gh pr list --state merged --search "merged:>$CUTOFF" --limit 500 \
    --json number,title,baseRefName,headRefName,mergeCommit \
    --jq '.[] | [.number, .baseRefName, .headRefName, .mergeCommit.oid, .title] | @tsv' >"$TMP/candidates"
fi

while IFS=$'\t' read -r n base head sha title; do
  if [ "$base" = "$BASE_BR" ]; then
    echo "#$n — merged straight into $BASE_BR (hotfix)" >>"$TMP/excluded"; continue
  fi
  if ! git merge-base --is-ancestor "$sha" "$H" 2>/dev/null; then
    continue   # not on the head branch (another release line, or still in a stack)
  fi
  overlap=$(gh pr view "$n" --json files --jq '.files[].path' | sort | comm -12 - "$TMP/files" | wc -l | tr -d ' ')
  if [ "$overlap" = 0 ]; then
    echo "#$n — no file differs from $BASE_BR (content already there): $title" >>"$TMP/excluded"; continue
  fi
  total=0; on_base=0
  for c in $(gh pr view "$n" --json commits --jq '.commits[].oid'); do
    total=$((total + 1))
    git merge-base --is-ancestor "$c" "$B" 2>/dev/null && on_base=$((on_base + 1))
  done
  if [ "$total" -gt 0 ] && [ $((on_base * 100 / total)) -ge 90 ]; then
    echo "#$n — sync of $BASE_BR into $HEAD_BR ($on_base/$total commits already on $BASE_BR): $title" >>"$TMP/excluded"; continue
  fi
  printf '%s\t%s\t%s\t%s\n' "$n" "$base" "$head" "$title" >>"$TMP/included"
done <"$TMP/candidates"

# A PR whose head branch is the base of other included PRs is a batch/umbrella:
# list it separately so its children are not counted twice.
cut -f2 "$TMP/included" | sort -u >"$TMP/bases"
echo
echo "## PRs in this release (number, base, title)"
sort -n "$TMP/included" | while IFS=$'\t' read -r n base head title; do
  tag=""
  grep -qxF "$head" "$TMP/bases" && tag=" [UMBRELLA: batch branch $head]"
  echo "- #$n [$base] $title$tag"
done
echo
echo "## Excluded since the cutoff"
if [ -s "$TMP/excluded" ]; then sort -t'#' -k2 -n "$TMP/excluded" | sed 's/^/- /'; else echo "- none"; fi

echo
echo "## New env vars (read in config/, added by this release)"
git diff "$B" "$H" -- config | grep -oE "^\+.*env\('[A-Z0-9_]+'[^)]*\)" | sed -E 's/^\+[[:space:]]*//' | sort -u | sed 's/^/- /' || true
echo
echo "## .env.example additions"
git diff "$B" "$H" -- .env.example | grep -E '^\+[A-Z0-9_]+=' | sed 's/^+/- /' || echo "- none"

echo
echo "## Migrations added"
git diff --name-only --diff-filter=A "$B" "$H" -- database/migrations | sed 's/^/- /' || true
echo "(paths under database/migrations/tenant/ are tenant migrations; others are landlord)"

echo
echo "## Scheduler changes (app/Console/Kernel.php)"
git diff "$B" "$H" -- app/Console/Kernel.php | grep -E '^[+-][^+-]' | sed 's/^/    /' || echo "- none"

echo
echo "## Queue config changes (config/horizon.php, config/queue.php)"
git diff --stat "$B" "$H" -- config/horizon.php config/queue.php | tail -1 || echo "- none"
