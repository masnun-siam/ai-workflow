#!/usr/bin/env bash
# resolve.sh <owner/repo> <input...>  ->  "repo<TAB>n<TAB>title<TAB>deps" sorted by repo, then issue number.
# input: GitHub issues search URL | label name | issue numbers | one epic parent number.
# An epic's sub-issues can live in other repos: each row carries the repo the issue is in.
# deps = "Depends on #N" / "Blocked by #N" refs that are also in the resolved set (same repo).
set -euo pipefail
repo=$1; shift
rows=()
if [[ ${1:-} == http* ]]; then
  q=$(python3 -c 'import sys,urllib.parse as u;print(" ".join(t for t in u.parse_qs(u.urlparse(sys.argv[1]).query).get("q",[""])[0].split() if not t.startswith(("is:issue","sort:"))))' "$1")
  mapfile -t rows < <(gh issue list -R "$repo" --search "$q" --state open --limit 100 --json number -q ".[]|\"$repo \(.number)\"")
elif [[ $# -eq 1 && ! $1 =~ ^[0-9]+$ ]]; then
  mapfile -t rows < <(gh issue list -R "$repo" --label "$1" --state open --limit 100 --json number -q ".[]|\"$repo \(.number)\"")
else
  for n in "$@"; do rows+=("$repo $n"); done
  if [[ $# -eq 1 ]]; then
    mapfile -t kids < <(gh api "repos/$repo/issues/$1/sub_issues" -q '.[]|"\(.repository_url|split("/")|.[-2:]|join("/")) \(.number)"')
    [[ ${#kids[@]} -gt 0 ]] && rows=("${kids[@]}")
  fi
fi
set=" $(printf '%s\n' "${rows[@]}" | tr ' ' '#' | paste -sd' ' -) "
printf '%s\n' "${rows[@]}" | sort -k1,1 -k2,2n | while read -r r n; do
  read -r title < <(gh issue view "$n" -R "$r" --json title -q .title)
  deps=$(gh issue view "$n" -R "$r" --json body -q .body | grep -ioE '(depends on|blocked by)[^.]*' | grep -oE '#[0-9]+' | tr -d '#' | sort -un | while read -r d; do [[ $set == *" $r#$d "* && $d != "$n" ]] && echo "$d"; done | paste -sd, - || true)
  printf '%s\t%s\t%s\t%s\n' "$r" "$n" "$title" "$deps"
done
