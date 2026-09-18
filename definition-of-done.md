# Definition of Done (DoD)

The quality bar `/run-issue` holds a change to. **`run-dev` self-certifies** every item
into `handoff.dod_self_check`; **`run-reviewer` independently re-verifies** — a
self-check is a claim, and the reviewer's job is to disbelieve it until the diff agrees.

This file is stack-neutral. A repo may add its own hard-won traps in
`<repo>/tasks/definition-of-done.md`, which is **appended** to this list when present.
Missing file → skip silently; it is not an error.

- **Tests** — every acceptance criterion has at least one automated test, plus the edge
  and negative/authorization cases the plan named. In full mode those tests were written
  RED first, by a station that did not write the implementation. The suite is green.
  A test changed to fit the code is a defect, not a fix.
- **Root cause, not symptom** — a bug fix addresses why it broke. Before changing a
  shared function, check its other callers: one guard where they all route through is a
  smaller diff *and* the correct one; patching only the path the issue names leaves every
  sibling caller broken.
- **DRY against the repo, not the diff** — search for an existing helper, service, type,
  or pattern before writing a new one. Re-implementing what already lives a few files
  over is the most common failure here, and a diff-only review never catches it.
- **YAGNI** — nothing beyond the issue. No speculative parameter, config flag, interface
  with one implementation, or abstraction "for later".
- **Errors are handled, never swallowed** — no bare catch that discards. Log at the
  right level through the project's existing logger. Never log secrets, tokens, or
  personal data.
- **Security** — input validated at the trust boundary; authorization enforced the way
  this codebase already enforces it; no new mass-assignment or injection surface; no
  hardcoded credentials; no secret added to a committed file.
- **No debug residue** — no `console.log`, `dd()`, `var_dump`, `print()`, commented-out
  code, stray TODO, or unused import introduced by this change.
- **Style and static analysis** — the repo's linter and type-checker pass on every
  changed file, at the project's configured strictness. Fix the cause; do not add a
  blanket ignore, a baseline entry, or a suppression comment to go green.
- **Migrations are additive and reversible** — a schema change is its own new migration
  and applies forward onto an already-migrated database. Never edit a migration that has
  already been committed; the database it ran against is real.
- **Public contracts** — a change to a published API, response shape, or event payload is
  additive, or it ships behind a version with the generated docs/schema in the repo
  regenerated to match.
- **Traceability** — commits follow the repo's convention, the PR body carries
  `Closes #<issue>`, and the branch is off the approved base.
- **CI green** — the opened PR's checks pass. A local suite pass is necessary and **not**
  sufficient: CI runs checks the local run does not, and an issue is not done until its
  PR is green.

The reviewer's lenses map onto these: correctness → tests / root cause · security →
security / errors · performance → the repo overlay's hot-path traps · conventions →
DRY / YAGNI / style / migrations / contracts.
