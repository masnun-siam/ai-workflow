# Contributing

## Which docs to update

- **User-facing change** (a command, flag, `aiw` subcommand, config key, or behaviour a user
  sees): update `docs/REFERENCE.md`, and `docs/HOW-IT-WORKS.md` if a mechanism changed.
  Add an entry under `## Unreleased` in `CHANGELOG.md`.
- **Install or setup change:** update `docs/INSTALL.md`.
- **New domain term:** define it in `CONTEXT.md`.
- **Hard-to-reverse design decision:** add an ADR under `docs/adr/`.
- **`CLAUDE.md`:** a stable baseline. Change it only when the user explicitly asks. The
  pre-commit hook below is a reminder, not a gate.
- **`AGENTS.md`:** a symlink to `CLAUDE.md`, so edit `CLAUDE.md`. On Windows with
  `core.symlinks=false`, AGENTS.md checks out as a plain file containing the text `CLAUDE.md`.
- **`README.md`:** a link hub only. New content goes in the docs it links.
- **GitNexus:** run `gitnexus analyze --skip-agents-md` so it does not write its block into
  `CLAUDE.md`. `aiw gitnexus` already passes the flag.

Tests in `run-engine/test_scripts.py` pin some doc text (README, INSTALL and REFERENCE
together, `HOW-IT-WORKS.md`, `CONTEXT.md`, `CHANGELOG.md`). Run them after editing docs.

## Pre-commit reminder

```bash
pip install pre-commit   # once per machine
pre-commit install       # once per clone
```

When `CLAUDE.md` is staged, the hook prints a warning and lets the commit through.

## Process

- `definition-of-ready.md`: the rubric `/run-issue` scores an issue against before a run
- `definition-of-done.md`: the quality bar `/run-issue` holds a change to
- `tasks/lessons.md`: patterns learned from past issues and reviews
- `CHANGELOG.md`: release notes; new entries go under `## Unreleased`
