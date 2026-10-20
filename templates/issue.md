# <Feature>: <short summary>

Writer note (delete before saving): `/refine-issues` writes this body and is the source of truth for it. The body stands alone: an agent can implement it and open a pull request without asking anyone. Open every file you cite, so every path and symbol is real or marked `(new)`. Keep anything a person already wrote that is still true. Leave the parent, blocked-by links and labels as they are, and add the `refined` label.

## WHAT
The outcome in one or two sentences.

Acceptance criteria:
- [ ] Each one a testable statement.

Out of scope:
- What this issue deliberately leaves out.

## WHY
The problem it solves for the user.

The PRD requirements it covers, quoted with their `FR-n`. PRD: `docs/prds/<feature-slug>.md`.

## HOW
- Files and symbols to change or create.
- Precedent to follow: the existing code that does something similar, with its path.
- From the PRD, quoted: the data, API contract and behaviour it must match.
- Edge cases, and data isolation where the project is multi-tenant or holds per-user data.
- Tests to write: the test file and the cases it must cover.
- Verify locally: the commands, and for a user-facing change, what to check in the running app.
- From its blockers: what #<n> delivers that this builds on.

Related: #<n>.
