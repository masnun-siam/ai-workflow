# Definition of Ready (DoR)

The rubric `/run-issue` scores an issue against before it spends a pipeline on it.
`run-researcher` scores each item and returns the failures in `handoff.gaps[]`, alongside
every normalization it made in `handoff.assumptions[]`.

**Readiness is advisory. It does not stop the run.** The gaps surface at **Gate 1**, printed
above the plan under a "⚠ This issue was thin" heading, where you decide with the plan in
front of you. There is no `blocked` status for the researcher to return — the engine's
vocabulary is `passed` / `bounce` / `escalate` and nothing else, which is what stops any
station inventing a fourth human gate.

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

## What a gap costs

Reporting a gap is cheap and missing one is expensive: a thin issue that gets planned anyway
burns a plan, a test suite, an implementation and a review before anyone notices the
acceptance criteria were never agreed. Naming it in `handoff.gaps[]` puts it in front of the
human at the one moment they are already reading the plan and deciding.

But do not report a gap the codebase answers. If item 4 is missing and one search resolves
it, that is normalization, not a gap — record it in `handoff.assumptions[]` instead, so the
human sees what was filled in on their behalf.
