# Contributing

## Which docs to update

- **User-facing change** (a command, flag, `aiw` subcommand, config key, or behaviour a user
  sees): update `docs/REFERENCE.md`, and `docs/HOW-IT-WORKS.md` if a mechanism changed.
  Add an entry under `## Unreleased` in `CHANGELOG.md`.
- **Install or setup change:** update `docs/INSTALL.md`.
- **New domain term:** define it in `CONTEXT.md`.
- **Hard-to-reverse design decision:** add an ADR under `docs/adr/`.
- **`CLAUDE.md`:** a stable baseline. Change it only when the user explicitly asks. Its
  pre-commit hook is a reminder, not a gate.
- **`AGENTS.md`:** a symlink to `CLAUDE.md`, so edit `CLAUDE.md`. On Windows with
  `core.symlinks=false`, AGENTS.md checks out as a plain file containing the text `CLAUDE.md`.
- **`README.md`:** a link hub only. New content goes in the docs it links.
- **GitNexus:** run `gitnexus analyze --skip-agents-md` so it does not write its block into
  `CLAUDE.md`. `aiw gitnexus` already passes the flag.

Tests in `run-engine/test_scripts.py` pin some doc text (README, INSTALL and REFERENCE
together, `HOW-IT-WORKS.md`, `CONTEXT.md`, `CHANGELOG.md`). Run them after editing docs.

## Pre-commit hooks

```bash
pip install pre-commit   # once per machine
pre-commit install       # once per clone; installs the pre-commit and pre-push hooks
git config blame.ignoreRevsFile .git-blame-ignore-revs   # optional: skip the reformat in blame
```

`.pre-commit-config.yaml` runs, on staged files:

- file hygiene: YAML/JSON syntax, merge-conflict markers, large files, broken symlinks,
  trailing whitespace, final newline
- `gitleaks` secret scan
- `ruff` lint and format, configured by `ruff.toml` (the repo's own config, so a
  machine-level ruff config never changes the result)
- `shellcheck`
- `run-engine/test_engine.py` when a `run-engine/*.py` file is staged

All of these block the commit. The one exception is the `CLAUDE.md` hook, which prints a
warning and lets the commit through. Run `pre-commit run --all-files` to check the whole
repo. When `/run-issue` runs on this repo with the hooks installed, an agent's commit
can be aborted by a fixer hook (whitespace, final newline, ruff-format) or a failing
`test_engine.py`. Re-stage the fixed files and commit again, or fix the failure first.

On `git push`, `run-engine/run_tests.sh` runs every `run-engine/test_*.py` (about 2 minutes)
and blocks the push if any file fails. The `Tests` GitHub Actions job runs the same script on
every pull request and on pushes to `master`. Run it by hand with `bash run-engine/run_tests.sh`.

## Process

- `definition-of-ready.md`: the rubric `/run-issue` scores an issue against before a run
- `definition-of-done.md`: the quality bar `/run-issue` holds a change to
- `tasks/lessons.md`: patterns learned from past issues and reviews
- `CHANGELOG.md`: release notes; new entries go under `## Unreleased`
