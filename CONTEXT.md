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
One stage in the `/run-issue` pipeline (researcher, planner, sdet, dev, verifier, reviewer, fixer, done). A Ledger advances through its Station roster in order; "lean" mode Runs skip the sdet and verifier Stations.
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

**Card** (kanban):
One Issue's current-progress tile on the Board: Project, Issue number, and title. Represents the Issue via its latest Run only, not every Run.
