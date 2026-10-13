# Epic: <Feature or epic title>

Labels (writer note, delete before saving): `epic`, `prd-<feature-slug>`, plus the area labels that apply.

## What
The outcome of the whole epic in two or three sentences, from the PRD's overview.

## Why
The problem it solves, in the PRD's words.

## Requirements covered
- FR-1 <Short name>
- FR-2 <Short name>

## Out of Scope
- The PRD's non-goals, and what other epics of the same PRD cover.

## Acceptance Criteria
Container issue: acceptance criteria live in the sub-issues. The epic is done when every sub-issue is closed and each requirement above is covered by a merged pull request.

## Notes
Source PRD: `docs/prds/<feature-slug>.md` (the source of truth; this issue only summarises it). Task list: `docs/tasks/<feature-slug>.md`. Tasks are attached as native sub-issues, not as a checklist here.

## Tasks
Filled by `aiw epic split` when /refine-issues files the tasks.
