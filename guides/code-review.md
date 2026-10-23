# Code review guide

What a review checks, how findings are graded and how the result is reported. Used by people and by the `/pr-review` skill.

## Principles

- Review the diff and the repository, not the author's summary. A claim that cannot be confirmed from the code or by running something is an open question.
- Read each changed file in full, and the callers of each changed symbol. A hunk can be correct and still break what surrounds it.
- Every finding carries evidence (file and line, or command output) and says what would resolve it.
- Name what is good as well. A review that lists only problems hides which parts can be relied on.

## Checklist

### 1. Issue fidelity
- Every acceptance criterion in the linked issue maps to code and to a test that would fail without it.
- Nothing listed as out of scope was built.
- The PR references its issue and targets the base branch.

### 2. Scope
- Only what the issue asks for changed. No drive-by refactors, dependency upgrades or new patterns unless a human agreed.
- No plans, specs or generated docs committed unless a human asked.

### 3. Data isolation and authorization
Applies when the project is multi-tenant or holds per-user data.
- Every new query, endpoint, job, command and broadcast is scoped to the tenant or user.
- A tenant or user ID taken from a header, route or request body is checked against the authenticated user's access.
- Shared tables and stores are filtered by the owning ID explicitly; only stores isolated by design are safe without it.
- Counts, caches, cache keys and channel names cannot mix tenants or users.
- A test proves another tenant's or user's data is neither returned nor changed.

### 4. Security
- Input is validated at the boundary the project uses for it before it reaches business logic.
- Authentication and authorisation are present on every new route.
- No secrets, tokens, `.env` values or customer data in code, logs, fixtures or test output.
- No filesystem paths or internal identifiers leak into API responses or third-party calls.

### 5. Correctness
- Error paths, empty and null inputs, limits and boundaries.
- Concurrency: two requests at the same moment, retried jobs, duplicate webhooks. Writes that must be atomic are atomic.
- Money and billing: the project's money type or helper, ledger writes that are idempotent, no double charge on retry.
- Time: time zones and day boundaries are explicit.
- Host tooling (scripts, `Makefile`): port and listener probes cover IPv4 and IPv6 (`localhost`), and values put into a shell are validated before use.

### 6. Data
- Migrations are safe on existing data.
- New queries come with the indexes they need.
- A field written by more than one service is not overwritten or dropped by either side.

### 7. Tests
- Tests assert behaviour and values, not just a status code or "no exception".
- Tests run the production code path. A test that re-implements the query or guard under test proves nothing: ask whether it would fail if the guarded line were removed.
- At least one failure path per feature.
- External services (payment, messaging, mail, storage) are faked; no real network calls.
- Test data comes from factories or builders, not hardcoded IDs.

### 8. Gates
- No lint, type or static-analysis suppressions added.
- No change to hooks, CI or test configuration that makes a check weaker.
- CI is green on the head commit, and its log shows the new and changed tests as passed, not skipped. A PR whose CI is failing or still running is `Blocked`, not reviewed. A local branch reviewed before its push has no CI yet; its `/verifier-locally` results stand in.

### 9. Conventions
- The change follows the repo's docs for its area and the sibling files next to it, including the documented data flow between layers.
- Skills and guides: step numbers and cross-references still resolve, and no other skill, guide or `CLAUDE.md`/`AGENTS.md` now contradicts the change.
- A tracked file deleted or untracked: `git grep` its path and any `Covers:` lines in `docs/`, and the PR says whether checkouts with local edits to it must discard them before pulling.
- Frontend: a component that stays mounted while a prop changes does not apply a late async result, such as an error or a pending flag, from the previous value: it checks the id it captured against the current one.

## Severity

| Level | Meaning | Blocks merge |
|---|---|---|
| Critical | Data loss, cross-tenant or cross-user exposure, wrong billing, security hole, production outage | Yes |
| Major | A defect or a missing test for an acceptance criterion; a weakened gate | Yes |
| Minor | Convention break or maintainability problem with no user-visible effect | No, but fix before or soon after |
| Nit | Preference | No |

Before reporting a Critical or Major finding, try to disprove it: read the surrounding code again or run the test. Downgrade or drop it if it does not hold.

## Report format

1. **Verdict:** `Approve`, `Changes required` or `Blocked` (cannot be reviewed yet, with the reason).
2. **Findings:** numbered, most severe first. Each one: severity, `path:line`, what is wrong, the evidence, what would resolve it.
3. **Acceptance criteria coverage:** one line per criterion with the code and test that cover it, or "not covered".
4. **Open questions:** claims that could not be verified.
5. **What is solid:** the parts checked and found correct.
6. **Checks run:** each command and its result; say plainly what was not run.
