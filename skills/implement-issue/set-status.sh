#!/usr/bin/env bash
# Set the Status field of an issue on every GitHub Project board it belongs to.
# Usage: set-status.sh <issue number> "<status name>"   (name matches case-insensitively)
# Exits non-zero when no board was updated, so the caller can warn and carry on.
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "usage: $0 <issue number> \"<status name>\"" >&2
  exit 2
fi
issue=$1
status=$2
repo=$(gh repo view --json nameWithOwner -q .nameWithOwner)

# One line per Status option on each board: item id, project id, field id, option name, option id, board title.
rows=$(gh api graphql -F owner="${repo%/*}" -F name="${repo#*/}" -F number="$issue" -f query='
  query($owner: String!, $name: String!, $number: Int!) {
    repository(owner: $owner, name: $name) {
      issue(number: $number) {
        projectItems(first: 20) {
          nodes {
            id
            project {
              id
              title
              field(name: "Status") {
                ... on ProjectV2SingleSelectField { id options { id name } }
              }
            }
          }
        }
      }
    }
  }' -q '.data.repository.issue.projectItems.nodes[]
    | .id as $item | .project as $p
    | ($p.field.options // [])[]
    | [$item, $p.id, $p.field.id, .name, .id, $p.title] | @tsv')

updated=0
want=$(printf '%s' "$status" | tr '[:upper:]' '[:lower:]')
while IFS=$'\t' read -r item project field name option title; do
  [ -z "$item" ] && continue
  [ "$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')" = "$want" ] || continue
  gh project item-edit --id "$item" --project-id "$project" --field-id "$field" --single-select-option-id "$option" >/dev/null
  echo "#$issue -> $name on $title"
  updated=$((updated + 1))
done <<<"$rows"

if [ "$updated" -eq 0 ]; then
  echo "#$issue is not on a project board with a \"$status\" status; board not updated" >&2
  exit 1
fi
