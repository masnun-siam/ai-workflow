# setu

> Stable baseline: edit only when the user explicitly asks. Volatile detail goes in the docs below.

setu (সেতু) is a Go single binary plus a Preact UI. It is a frontend for Claude Code: it starts headless
`claude -p` sessions that run the blubird plugin's skills and four built-in prompts, polls GitHub, and shows what
needs the user. It replaced the `ai-workflow` plugin and its Python `aiw` engine.

## Architecture

`PRD → tasks → refined issue → implement-issue → pr-review → grind → merge → release`

- **Backend:** `cmd/setu` is wiring only. `internal/` holds one package per concern (sessions, claude, gh, poller, products,
  inbox, views, grind, dispatch, away, release, review, notify, settings, blubird, prompts, server). Packages import only from lower layers.
- **Built-in prompts:** `prompts/` (`release-pr`, `pr-grind`, `release-note`, `peer-review`, `agents/`), embedded and extracted to `~/.setu/prompts/<version>/`.
- **UI:** `web/` (Preact, signals, Vite, TypeScript), built into `internal/web/dist/`, which is committed.
- **State:** GitHub and the repo's `docs/prds/` are the truth. `~/.setu` (override `SETU_HOME`) holds only setu's own state.

## Rules

- Go 1.27, standard library first. A dependency only when the std lib truly lacks it (see `docs/setu/API.md` §1).
- The UI is Preact + TypeScript, no other framework. Rebuild with `make web` and commit `internal/web/dist/` with the change.
- Tests: `make test` (Go `go test ./...`, web typecheck and vitest). No network; fake `claude`, `gh`, `slackcli` binaries via `internal/testutil/fakebin`.
- Errors are JSON `{error}`; use `internal/errs` kinds. Writes to `~/.setu` are atomic, with file locks.
- Use the vocabulary in `CONTEXT.md`.

## Where to look

- Overview and install → `README.md`
- Architecture and decisions → `docs/setu/ARCHITECTURE.md`, `docs/setu/DECISIONS.md`
- API and package contract → `docs/setu/API.md`
- CLI, data files, settings → `docs/setu/REFERENCE.md`
- Glossary → `CONTEXT.md`. Which docs to update → `CONTRIBUTING.md`
- UI principles and tokens → `PRODUCT.md`, `DESIGN.md`
- PR history of the old plugin → `docs/prds/`. Release notes → `CHANGELOG.md`
