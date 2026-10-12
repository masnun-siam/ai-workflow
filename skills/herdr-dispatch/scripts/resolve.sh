#!/usr/bin/env bash
# resolve.sh <owner/repo> <input...>  ->  "n<TAB>title<TAB>deps" sorted by issue number.
# input: GitHub issues search URL | label name | issue numbers | one epic parent number.
# deps = native blocked-by links plus "Depends on #N" refs, kept only if also in the resolved set.
set -euo pipefail
repo=$1; shift
nums=()
if [[ ${1:-} == http* ]]; then
  q=$(python3 -c 'import sys,urllib.parse as u;print(" ".join(t for t in u.parse_qs(u.urlparse(sys.argv[1]).query).get("q",[""])[0].split() if not t.startswith(("is:issue","sort:"))))' "$1")
  mapfile -t nums < <(gh issue list -R "$repo" --search "$q" --state open --limit 100 --json number -q '.[].number')
elif [[ $# -eq 1 && ! $1 =~ ^[0-9]+$ ]]; then
  mapfile -t nums < <(gh issue list -R "$repo" --label "$1" --state open --limit 100 --json number -q '.[].number')
else
  nums=("$@")
  if [[ ${#nums[@]} -eq 1 ]]; then
    mapfile -t kids < <(gh api "repos/$repo/issues/${nums[0]}/sub_issues" -q '.[].number')
    [[ ${#kids[@]} -gt 0 ]] && nums=("${kids[@]}")
  fi
fi
set=" ${nums[*]} "
for n in $(printf '%s\n' "${nums[@]}" | sort -n); do
  read -r title < <(gh issue view "$n" -R "$repo" --json title -q .title)
  # blocked-by is best-effort: a failed call falls back to the text line alone
  deps=$({ gh issue view "$n" -R "$repo" --json body -q .body | grep -ioE 'depends on[^.]*' | grep -oE '#[0-9]+' | tr -d '#' || true
           gh api "repos/$repo/issues/$n/dependencies/blocked_by" -q '.[].number' 2>/dev/null || true; } | sort -un | while read -r d; do [[ $set == *" $d "* && $d != "$n" ]] && echo "$d"; done | paste -sd, - || true)
  printf '%s\t%s\t%s\n' "$n" "$title" "$deps"
done
