# <Feature name> — task list

- Source PRD: `docs/prds/<feature-slug>.md` (status `Approved`; every decision lives there, none here)
- Epic: #<n>
- Date: YYYY-MM-DD
- Repo: <owner/repo>

## Shared files

- `<path>` — owned by task <n>. Existing files more than one part of the work must edit; each belongs to one task, or the tasks that need it are ordered by a dependency.

## Waves

- Wave 1 (can start now): backend task 1
- Wave 2 (after wave 1 is merged): frontend task 2

## Task 1 — <Short title>
Outcome: one sentence, observable, deliverable in one pull request.
Area: backend
Files/symbols: real paths and symbols this task touches, with line numbers where helpful; mark files and symbols that do not exist yet `(new)` and name the precedent to copy.
Acceptance criteria:
- Testable statements, including edge cases (and data isolation when the repo is multi-tenant). Together with the other tasks they cover every FR of the PRD.
Verify command: the exact command that proves it: the repo's own test command scoped to this task's tests.
Depends on: none
Parallel: yes
Issue: —

## Task 2 — <Short title>
Outcome: ...
Area: frontend
Files/symbols: ...
Acceptance criteria:
- ...
Verify command: ...
Depends on: task 1
Parallel: no
Issue: —

Notes for the writer, delete before saving (this block and every `<placeholder>` and example text above):
- `Area` comes from the repo's top-level layout (for example `backend` or `frontend`), one per task. A task that needs two areas is two tasks.
- A task is within the size limits in this skill's step 5.
- `Depends on` is `none` or a list such as `task 1, task 3`. List tasks dependencies-first, so a task only depends on tasks above it.
- `Parallel` is `yes` when no task outside its own dependency chain shares a file with it, otherwise `no`. "Waves": a task is in the first wave in which all its dependencies are in earlier waves.
- When the PRD has more than one epic, replace the `Epic:` line at the top with one per epic and add `Epic: #<n>` to each task, above its `Issue:` line.
- When an approved PRD changes, tasks are never renumbered. A changed task that already has an issue gets a `Changed: YYYY-MM-DD <what changed>` line; a removed one is marked `Dropped` with the reason.
- `Issue` stays `—` until `/refine-issues` writes the issue number back, for example `#123`.
