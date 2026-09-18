# Definition of Ready (DoR)

The rubric `/run-issue` scores an issue against before it spends a pipeline on it.
`run-researcher` scores each item; any ✗ means the issue is **not ready** → return
`status: "blocked"` with the gaps, and the orchestrator posts a `needs-info` comment,
adds the label, and stops **before the worktree is created**.

An issue is READY only if every item below is satisfiable from the issue itself, its
comments, its linked issues, and the repo.

1. **Problem & why** — the user or business problem, and why it matters. Not merely a
   proposed solution. "Add a `status` column" is a solution; what breaks without it is
   the problem.
2. **Scope** — explicit in-scope and out-of-scope boundaries. An issue with no stated
   edge is an issue whose PR will grow one.
3. **Acceptance criteria** — testable, verifiable statements (given/when/then, or a
   checklist). Each one becomes at least one automated test, so "works correctly" is
   not an acceptance criterion.
4. **Affected surface** — the modules / services / endpoints / screens likely touched.
   Ground it in the codebase, not a guess. Where a code graph is available, use it.
5. **Non-functional constraints** — performance, security, authorization, data
   migration, backward compatibility. "None" is a valid answer; silence is not.
6. **Dependencies / blockers** — other issues, external specs, ordering constraints, or
   an upstream PR that must land first.

## Borderline issues

Most real issues are neither clean nor hopeless: the approach is given but the
acceptance criteria are implicit, or a spec is referenced but not inlined. Those may be
**normalized** — filled in with **explicitly stated assumptions**, which are surfaced at
Gate 1 for the human to confirm or correct.

The line is firm: an assumption is recorded and shown, never silently adopted. Inventing
scope and calling it normalization is the failure this rubric exists to prevent.

## What "blocked" costs

Blocking is cheap and being wrong is expensive: a thin issue that gets planned anyway
burns a plan, a test suite, an implementation and a review before anyone notices the
acceptance criteria were never agreed. Prefer one `needs-info` comment over a confident
run in the wrong direction.

But do not block on something the codebase answers. If item 4 is missing and one search
resolves it, that is normalization, not a gap.
