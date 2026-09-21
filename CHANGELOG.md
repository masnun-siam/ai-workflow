# Changelog

## 1.2.1 — 2026-09-21

### Changed

- **Worklog now writes through Obsidian, not ZenNotes.** `worklog-runner` was the only
  agent in this plugin that saved notes through the ZenNotes MCP server
  (`mcp__zennotes__*`) — every other vault-touching agent (`dump`, `run-researcher`,
  `run-issue` phase 9.1, `gh-issue` step 7) goes through the `obsidian` CLI against the
  same vault. Two note backends for one vault meant the worklog path could break
  independently of everything else and carried a dependency (the ZenNotes MCP server)
  nothing else in the plugin needed. `worklog-runner` now resolves the daily note via
  `obsidian vault=notes daily:path`, and reads/writes it with the same
  `read`/`create ... overwrite`/`daily:append` sequence `dump` already uses, including
  its "check the output text, not the exit code, for `not found`" gotcha. The
  `mcp__zennotes__*` tool grants are gone from `worklog-runner`'s frontmatter.

## 1.2.0 — 2026-09-21

### Added

- **Stack-aware runtime QA.** Phase 4.5's verifier no longer delegates to gstack's
  `qa-only` and is no longer browser-only. It routes on `backend`/`frontend` glob
  signals (deterministic, in `classification.signals`, overridable per repo) computed
  from the diff:
  - **Backend** is verified over real HTTP against `api_url` — one call per response
    state (200/401/403/404/422/500), intersected with the diff-touched routes and the
    plan's acceptance criteria. `tinker`/SQL seed preconditions and assert side effects
    only; auth is always minted via the real login endpoint, never in-process.
  - **Frontend** is verified with real Playwright specs against `web_url`, using
    `page.route()` to force every state (loading/empty/error/permission-denied/success)
    instead of hoping an exploratory pass reaches them, plus one unmocked smoke run.
    Reuses a repo's own Playwright/`npx` setup before installing anything.
  - A PR touching both runs backend first; its captured responses become the
    frontend's mocks, so the two halves can't quietly disagree. A failing backend
    still lets the frontend run, flagged provisional.
  - `stack.py` now records `api_url`/`web_url` alongside `app_url` when a compose file
    exposes two distinct buildable app services. The envelope's rollup verdict is the
    worst of the dispatched modes, and `checks.py` validates each mode independently.

## 1.1.0 — 2026-09-19

### Added

- **Epic decomposition.** `/gh-issue` can split a large brief into a parent issue plus
  bite-sized children, each independently satisfying the Definition of Ready and declaring
  its order with a `Depends on: #n` line. `/run-issue <parent>` then drives them all —
  parallel where independent, sequential where dependent — behind **one** set of three
  human gates, not three per child. Dependent children stack their branch on the branch
  they depend on, so sequencing falls out of the DAG rather than being enforced separately.
  A blocker parks its child; the epic keeps going.
- **Station post-checks.** A `passed` envelope is now a claim the engine tries to refute
  from something with no incentive to agree — an exit code, a git object, a GitHub
  response, a file on disk. Five stations are checked; three gained a cheap pre-guard
  (`aiw precheck`). The motivating case: `run-fixer` could report success with review
  threads still open and nothing pushed. A refuted claim self-bounces on a budget that can
  never spend a real one; an exhausted budget advances and reports at the final gate.
- **The mechanical phases are code.** What used to be ~250 lines of procedure written in
  English is now `aiw stack|worktree|threads|pr|ci|gitnexus|project-status|project-board`.
  Each writes the ledger keys it produces itself, so there is no follow-up step to forget.
- **`docs/HOW-IT-WORKS.md`** — the system explained in layers, each usable on its own.
- **`CHANGELOG.md`** — this file.

### Changed

- **The CLI is now `aiw`, not `route`.** `route` is also the macOS, BSD and net-tools
  *network* command, and `/sbin` precedes plugin bin directories on a default macOS `PATH`
  — so `route paths` ran `/sbin/route`, printed a usage error to stderr, and **exited 0**
  while every path the orchestrator needed silently resolved to nothing. Preflight now
  verifies identity (`aiw paths` must print JSON whose first key is `plugin_root`) instead
  of testing for absence, which was never the failure mode.
- **New exit code 7** from `aiw route`: a post-check refuted the envelope and the bounce is
  already routed. Exit 6 (test-root ownership) is unchanged.
- **The README is a setup protocol**, executable by an AI agent handed the repo link, with
  a human copy-paste install at the top.
- `epic.max_stacks` defaults to **1**. `-p runissue-<n>` namespaces container names, not
  published host ports, so two children sharing a compose file with any published port
  collide and both fail.

### Fixed

- **The plugin was uninstallable.** Both `userConfig` entries carried a `title` and no
  `description`, which the manifest schema rejects — `claude plugin install` failed
  outright. Nothing in `installed_plugins.json`, for the whole of 1.0.0.
- Four agents (`run-ci`, `run-grinder`, `run-researcher`, `run-specialist`) were told to run
  the CLI while their `tools:` line granted no permission for it.
- `aiw epic split` linked sub-issues by issue *number* where the API wants the database
  *id*, and only warned on failure — so it exited 0 having linked nothing, and a parent with
  no sub-issues then ran as one ordinary issue, turning the whole brief into a single PR.
- Several places conflated a failed `gh` call with a legitimately empty result: `epic split`
  silently dropping a child's dependencies (producing a DAG that validates and orders
  wrongly), and `project-board` creating a **second** board on a resumed epic.
- `definition-of-ready.md` told `run-researcher` to return `status: "blocked"`. The engine
  accepts `passed`/`bounce`/`escalate` only, so that envelope fails validation — and
  `run-issue.md` has long said readiness is advisory and surfaces at Gate 1.
- README commands were unpasteable: `<repo>` inside a bash fence is a shell input redirect,
  so `claude plugin marketplace add <repo>` ran with no argument at all.

### Notes

52 checks across `test_engine.py` (17) and `test_scripts.py` (35). No network, no Docker, no
install step.

**Epic mode has not been exercised against a live epic.** Its pure logic is covered and its
`gh` paths are stubbed, but the prose halves — the relay, the gate collapse, the
`base_branch` handoff — have no executable surface and are verified by reading only.

## 1.0.0

Initial packaging of the `/run-issue` pipeline as a Claude Code plugin.
