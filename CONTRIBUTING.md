# Contributing

## Which docs to update

- **User-facing change** (a screen, key, `setu` verb or flag, setting, data file): update `docs/setu/REFERENCE.md`
  and `README.md` if setup or first run changed. Add an entry under `## Unreleased` in `CHANGELOG.md`.
- **API change** (endpoint, type, package interface): update `docs/setu/API.md`.
- **Architecture or hard-to-reverse decision:** `docs/setu/ARCHITECTURE.md` or `docs/setu/DECISIONS.md`.
- **Touching `web/`:** run `make web` and commit `internal/web/dist/` in the same change (users never run Node).
  UI look and tokens: `DESIGN.md`; principles: `PRODUCT.md`.
- **Built-in prompt change:** edit under `prompts/`; keep `internal/prompts` tests green (they ban old `aiw` verbs and local paths).
- **New domain term:** `CONTEXT.md`.
- **`CLAUDE.md`:** a stable baseline. Change it only when the user explicitly asks. `AGENTS.md` is a symlink to it.
- **`docs/prds/`:** history of the old plugin; do not edit.

## Checks

`make test` must pass (Go tests, web typecheck and tests). Pre-commit runs gofmt, go vet, gitleaks and file hygiene
(`pre-commit install`); pre-push runs `make test`. CI runs `make test` with Go 1.27 and Node 24.
