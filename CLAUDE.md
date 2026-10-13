# ai-workflow

> Stable baseline: edit only when the user explicitly asks. Volatile detail goes in the docs below.

A Claude Code plugin that takes a GitHub issue to a reviewed, ready-to-merge PR.
`/ai-workflow:run-issue` tests, implements, verifies, opens, reviews and fixes the PR. A human
is needed only at plan approval, at an escalated review finding, and at the final handback.

## Architecture

`orchestrator → engine → station → envelope → post-checks → ledger`

- **Orchestrator:** `commands/run-issue.md`. It runs what the engine prints and never picks the next step itself.
- **Stations:** `agents/run-*.md`. Each runs with fresh context and returns a fixed-shape envelope. The other agents serve standalone commands.
- **Engine:** `run-engine/engine.py` is pure and deterministic. `route.py` and the other modules do the I/O. Policy lives in `config.json`, and a repo can override it with `.run-issue.json`.
- **Ledger:** one `run.json` per run, kept in the plugin data dir and never in this repo. It is the only source of truth.
- **CLI/UI:** `bin/aiw` → `route.py`. `aiw ui` is a stdlib `http.server` serving vendored Preact/htm from `run-engine/ui_static/`.

## Rules

- Python 3.10+, stdlib only. No pip and no frontend build step.
- Tests are plain `assert` scripts (`run-engine/test_*.py`), with no framework, network or Docker.
- Post-checks verify every station result. Never trust a station's claim.
- Use the vocabulary in `CONTEXT.md`.

## Where to look

- How a run works → `docs/HOW-IT-WORKS.md`
- Commands, `aiw` CLI, state, tests → `docs/REFERENCE.md`
- Setup → `docs/INSTALL.md`
- Glossary → `CONTEXT.md`
- Which docs to update → `CONTRIBUTING.md`
- Slash commands → `commands/`. Agents → `agents/`. Skills → `skills/`.
- Design history → `docs/adr/`, `docs/prds/`, `docs/tasks/`, `CHANGELOG.md`
