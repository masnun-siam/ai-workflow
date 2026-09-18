# Changelog

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
