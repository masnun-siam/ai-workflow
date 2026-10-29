# ai-workflow

> Stable baseline: edit only when the user explicitly asks. Volatile detail goes in the docs below.

A Claude Code plugin that carries one team process, from an idea to a merged PR:
PRD → tasks → refined issues → `/implement-issue` → `/pr-review`. Skills do the work; the
`aiw ui` web app starts them as headless sessions and shows where everything stands.

## Architecture

`PRD → tasks → refined issue → implement-issue → pr-review → grind → merge`

- **Skills:** `skills/`. Each stage is one skill: `create-prd`, `create-tasks`, `refine-issues`, `implement-issue`, `verifier-locally`, `pr-review`, `docs-updater`, `sync-from-wasensi`. The tools around them: `dump`, `release-pr`, `worklog`, `peer-review`, `herdr-dispatch`, `pr-grind`.
- **Guides and templates:** `guides/` is the engineering process and review standard the skills read. `templates/` holds the PRD, epic and issue shapes.
- **Agents:** `agents/`. Only `peer-reviewer` (one read-only review lens), `away-answerer` (the read-only Away mode answerer) and `worklog-runner`.
- **CLI/UI:** `bin/aiw` → `run-engine/route.py`, verbs `ui`, `paths`, `ask`, `ci`, `threads`, `peer-review`. `aiw ui` is a stdlib `http.server` serving the built React app from `run-engine/ui_dist/` (source in `ui/`).
- **State:** GitHub (issues, PRs, labels) and the repo's `docs/prds/` are the truth. The plugin data dir holds only UI and grind state, never in this repo.

## Rules

- Python 3.10+, stdlib only; no pip. The UI is a React + TypeScript app in `ui/`, built with Vite into `run-engine/ui_dist/`, which is committed so users never need Node.
- Tests are plain `assert` scripts (`run-engine/test_*.py`), with no framework or network.
- The imported dev-workflow skills, guides and templates stay as imported. Deviations live in the kept tools and the UI.
- Use the vocabulary in `CONTEXT.md`.

## Where to look

- How the process works → `docs/HOW-IT-WORKS.md`
- Commands, `aiw` CLI, UI, state, tests → `docs/REFERENCE.md`
- Setup → `docs/INSTALL.md`
- Glossary → `CONTEXT.md`
- Which docs to update → `CONTRIBUTING.md`
- Process and review standards → `guides/`. Document shapes → `templates/`
- Skills → `skills/`. Agents → `agents/`. Slash commands → `commands/`
- Release notes → `CHANGELOG.md`
