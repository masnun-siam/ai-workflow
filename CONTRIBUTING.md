# Contributing

## Which docs to update

- **User-facing change** (a command, flag, `aiw` subcommand, config key, or behaviour a user
  sees): update `docs/REFERENCE.md`, and `docs/HOW-IT-WORKS.md` if a mechanism changed.
  Add an entry under `## Unreleased` in `CHANGELOG.md`.
- **Install or setup change:** update `docs/INSTALL.md`.
- **New domain term:** define it in `CONTEXT.md`.
- **Hard-to-reverse design decision:** record it in the feature's PRD (`docs/prds/`).
- **`CLAUDE.md`:** a stable baseline. Change it only when the user explicitly asks. Its
  pre-commit hook is a reminder, not a gate.
- **`AGENTS.md`:** a symlink to `CLAUDE.md`, so edit `CLAUDE.md`. On Windows with
  `core.symlinks=false`, AGENTS.md checks out as a plain file containing the text `CLAUDE.md`.
- **`README.md`:** a link hub only. New content goes in the docs it links.
- **Skills, guides, templates:** the dev-workflow ones are imported as they are. Change
  them through the skill's own "Improve this skill" loop or `/sync-from-wasensi`, not by hand-fixing
  one repo's quirk. `guides/skills.md` explains the layout.
- **GitNexus:** run `gitnexus analyze --skip-agents-md` so it does not write its block into
  `CLAUDE.md`.

Some tests pin doc text. Run `bash run-engine/run_tests.sh` after editing docs.

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
- `shellcheck` (excluding SC2016, which flags the GraphQL `$vars` in imported scripts)
- `bash run-engine/run_tests.sh` (the whole suite) when a `run-engine/*.py` file is staged

All of these block the commit. The one exception is the `CLAUDE.md` hook, which prints a
warning and lets the commit through. Run `pre-commit run --all-files` to check the whole
repo. An agent's commit can be aborted by a fixer hook (whitespace, final newline,
ruff-format) or a failing test. Re-stage the fixed files and commit again, or fix the failure first.

On `git push`, `run-engine/run_tests.sh` runs every `run-engine/test_*.py` (about 2 minutes)
and blocks the push if any file fails. The `Tests` GitHub Actions job runs the same script on
every pull request and on pushes to `master`. Run it by hand with `bash run-engine/run_tests.sh`. A clone set up before
the pre-push hook existed must run `pre-commit install` again to get it.

## Process

- `guides/engineering-workflow.md`: the process the skills follow; `guides/code-review.md`: the review standard
- `templates/`: the PRD, epic and issue shapes
- `CHANGELOG.md`: release notes; new entries go under `## Unreleased`
