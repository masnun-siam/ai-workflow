# ai-workflow

A Claude Code plugin that carries the team's dev process (PRD → tasks → refined issues → implement → review) plus the tools around it (dump, worklog, release PR, grind, peer review) and a web UI that runs them.

## Language

**PRD**:
The product requirements for one feature (the what and why, with a technical design of contracts but never code), written by `/create-prd` after an interview. The canonical copy is the repo's `docs/prds/<slug>.md`. Its status is Draft, In review or Approved; only an Approved PRD can be split into tasks. `/create-prd --update` records later decisions.
_Avoid_: Spec, design doc

**Epic**:
A parent issue whose sub-issues are the tasks of one `## Epics` entry of a PRD, filed when the PRD is approved and labelled `epic` + `prd-<slug>`.
_Avoid_: Parent ticket, umbrella issue

**Task list**:
The saved, ordered decomposition of one PRD into small one-PR tasks, at `docs/tasks/<slug>.md`: outcome, Area, files, acceptance criteria, verify command, `Depends on:` and Parallel per task, plus Waves. Written by `/create-tasks`; tasks are never renumbered, only marked Changed or Dropped.
_Avoid_: Plan, backlog

**Refined issue**:
A task filed as a child issue of its epic, with a WHAT, WHY and HOW written from the PRD and the code, native blocked-by links, and the `refined` label. `/refine-issues` writes it. Only a refined issue is ready to implement.
_Avoid_: Groomed, ready

**implement-issue**:
The skill that takes one refined issue to a Ready PR in a single session: stop if blocked, work in its own worktree, run every check locally, verify in the running app, open a draft PR, and mark it ready only when CI is green and every review comment is handled.

**verifier-locally**:
The skill that proves a change works before it is pushed: it finds the repo's checks from CI, hooks and build files, runs the ones matching the changed paths, and reports each result with evidence. `implement-issue` and grind both call it.

**pr-review**:
The skill that reviews a PR or local branch against its issue, the repo's rules and `guides/code-review.md`, and reports evidence-backed findings with a verdict.

**Grind**:
`/pr-grind`: the loop on a ready PR that posts the Slack reviewer-bot trigger, waits for a round, fixes the findings inline in its own session, runs `/verifier-locally`, pushes, re-triggers, and repeats until approved or a rail stops it. Each round re-enters as a fresh headless session that reads the PR's grind state file.
_Avoid_: Review loop

**Lens**:
One review angle (critical, CEO, CTO, security, QA, UX, performance). The `peer-reviewer` agent is a lens: read-only, on Opus, one lens per instance.

**Peer review panel**:
The lenses picked for one artifact (a draft PRD, or a change: Ask, Answer and Diff), run by `/peer-review` until every picked lens approves or the round cap is reached. A **dispute** is a finding the author dismissed that its lens raises again; the user settles it.
_Avoid_: Review (on its own, that means a PR review)

**Dump**:
A capture filed into the Obsidian vault by `/dump` (new feature, change request, bug, task or meeting notes). A feature, change request or bug is written as a Problem statement; for a new feature it also seeds a `PRD.md` with `status: seed` next to `Dump.md`.
_Avoid_: Note

**Problem statement**:
What `/dump` writes for a feature, change request or bug: Problem, Who, Evidence, Expected and Open questions, taken only from the input, followed by the raw input verbatim. `/create-prd` builds a PRD from it.

**Session**:
A headless Claude invocation started and tracked by the UI (`aiw ui`), recorded under `<data_dir>/sessions/<id>/`. It exits after each turn and comes back via `--resume` with an answer or after a rate limit.
_Avoid_: Run, job

**Project**:
The human-friendly name for a GitHub `owner/repo`, looked up from `skills/worklog/projects.json`. Falls back to the raw `owner/repo` slug when unmapped.
_Avoid_: Repo (when referring to the display name; "repo" is fine for the raw slug)

**Dispatch**:
Opening several refined issues in separate herdr tabs, one `/implement-issue <n>` each, in dependency order with a concurrency cap, via `herdr-dispatch`.
_Avoid_: Batch run, fan-out
