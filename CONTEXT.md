# ai-workflow

A Claude Code plugin that drives GitHub issues through an automated pipeline (`/run-issue`) to a reviewed PR, and provides supporting tooling (worklog, PR review, etc.) around that pipeline.

## Language

**Run**:
A single execution of `/run-issue` against one Issue, tracked by a Ledger. An Issue may have multiple Runs (e.g. retries); only the latest Run is considered current.
_Avoid_: Task, job, execution

**Ledger**:
The persisted state of a Run, stored as `run.json` under the plugin data directory. Records the Station roster, current Station index, bounce counts, overall Status, trace log, and free-form context (repo path, branch, PR link, CI result, etc.).
_Avoid_: State file, run data

**Station**:
One stage in the `/run-issue` pipeline (researcher, planner, sdet, dev, verifier, reviewer, fixer, done). A Ledger advances through its Station roster in order; default-mode Runs skip the sdet and verifier Stations (run-dev does both jobs), and only "full" mode Runs include them.
_Avoid_: Stage, step, phase

**Status** (Ledger):
The Ledger's overall state: `running`, `done`, or `escalated`. Distinct from a Station's per-turn outcome.
_Avoid_: State

**Escalated**:
A Ledger Status meaning a Station bounced in a way that needs a human, rather than the automated pipeline continuing.
_Avoid_: Blocked, stuck

**Bounce**:
A Station rejecting its input and sending the Run back to an earlier Station, tracked in the Ledger's bounce counts and trace log.

**Classification**:
A one-time assessment of an Issue recorded on its Ledger — ticket type, risk score, risk band, and blast radius — set early in a Run and not updated afterward.

**Project**:
The human-friendly name for a GitHub `owner/repo`, looked up from `skills/worklog/projects.json`. Falls back to the raw `owner/repo` slug when unmapped.
_Avoid_: Repo (when referring to the display name — "repo" is fine for the raw owner/repo slug itself)

**Board** (kanban):
The generated visual page showing every Issue's current progress. Composed of Columns (one per Station, plus done) and Cards (one per Issue, sourced from its latest Run's Ledger).
_Avoid_: Dashboard

**Session**:
A headless Claude invocation started and tracked by the UI (`aiw ui`), recorded under `<data_dir>/sessions/<id>/`. A Session may or may not link to a Run.
_Avoid_: Run (a Run is the pipeline for one Issue; a Session is a single UI-started invocation)

**Card** (kanban):
One Issue's current-progress tile on the Board: Project, Issue number, and title. Represents the Issue via its latest Run only, not every Run.

**Dump**:
A capture filed into the Obsidian vault by `/dump` (new feature, change request, bug, task or meeting notes). A feature, change request or bug is written as a Problem statement; for a new feature it also seeds a `PRD.md` with `status: seed` next to `Dump.md`.
_Avoid_: Note, intake (intake normalises a source into a brief; it files nothing)

**Problem statement**:
What `/dump` writes for a feature, change request or bug: Problem, Who, Evidence, Expected and Open questions, taken only from the input, followed by the raw input verbatim. `/prd` builds a PRD from it; a bug goes from its problem statement to `/gh-issue`.
_Avoid_: Raw dump, brief (a brief is what `/intake` returns)

**Task list**:
The saved, ordered decomposition of one piece of work into small tasks, at `docs/tasks/<slug>.md`, one `## Task <n>` block each with its outcome, files, acceptance criteria, verify command, `Depends on:` and `Issue:` slot. Written by `/create-tasks` or `/gh-issue` step 3.6; `/gh-issue docs/tasks/<slug>.md` files issues from it.
_Avoid_: Plan (the planner's output), backlog

**PRD**:
The product requirements for one feature (the what and why, never the how), written by `/prd` after an interview. The canonical copy is the repo's `docs/prd/<slug>.md`; the vault `PRD.md` mirrors it. A `status: seed` PRD is a placeholder from `/dump` that `/prd` fills. `/prd --update` appends decisions made later.
_Avoid_: Spec, design doc

**Refined**:
The label `/gh-issue` puts on an issue that meets the definition of ready: independently readable, with acceptance criteria, a How and a verify command, and its order declared by `Depends on: #n`.
_Avoid_: Groomed, ready (ready is the Gate 2 verdict on a PR)

**Dispatch**:
Launching `/run-issue` over a batch of Issues in dependency order with a concurrency cap, via `herdr-dispatch` in the terminal or the `#/dispatch` page in the UI.
_Avoid_: Batch run, fan-out
