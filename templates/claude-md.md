# <Project> — Agent Constitution

Writer note (delete before saving): this is the root `CLAUDE.md`, written by `repo-bootstrap` phase 3. At most about 60 lines. It is an index with rules, not a manual: anything longer goes to `docs/` and gets a row under References. Every command and path must exist.

This file is the constitution for every AI agent working in this repository.

- **Protected.** Never edit, rewrite, shorten or remove any part of this file unless a human explicitly asks for that change, and confirm with them before writing.
- **Wins conflicts.** If a doc, skill or prompt contradicts this file, this file wins.
- **Single source.** This is the only `CLAUDE.md` in the repo; never add another. `AGENTS.md` is a symlink to it.
- **Stays short.** Detail belongs in the references below, not here. Keep this file under about 60 lines.

## Project

Two or three sentences: what it is, who uses it, the external services it depends on.

## Architecture

| Component | Path | Tech | Role |
|---|---|---|---|
| <component> | `<path>/` | <language, framework, version> | <one line> |
| <data store> | — | <engine, version> | <what lives there> |

## Principles

1. **Branching.** Never commit or push to `<production>` or `<base>`. Work on a branch and open a PR into `<base>`.
2. **Gates.** Never bypass checks: no `--no-verify`, no lint or type suppressions, no weakening of pre-commit or CI.
3. **Data isolation.** <The repo's scoping rule, for example tenant or account scoping; drop if none.>
4. **Secrets.** Never commit or log credentials, tokens, `.env` values or customer data.
5. **Scope.** Change only what the task asks. No drive-by refactors, dependency upgrades or new patterns without a human agreeing.
6. **Production.** Never deploy or run commands against production services or data.
7. **Docs.** Do not commit plans, specs or generated docs unless a human asks.
8. **Read first.** Before working in an area, open its reference below. Do not invent conventions that are not written down; follow the surrounding code.
9. **Impact.** <Only if a code-graph tool is configured: run its impact analysis before editing a symbol, and how to build the index.>

## Commands

| Task | Command |
|---|---|
| Start dev stack | `<command>` |
| Lint / test per component | `<command>` |
| Everything | `<command>` |

## References

Open these on demand; only list files that exist.

| Need | Where |
|---|---|
| Docs index | `docs/README.md` |
| Workflow, gates, code review | `docs/guides/` or the ai-workflow plugin's `guides/` |
| Conventions per component | `docs/guides/<area>-conventions.md` |
| Lint, format and test targets | `<Makefile or package manifest>` |
| Commit gates | `.pre-commit-config.yaml` |
