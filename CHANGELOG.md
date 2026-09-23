# Changelog

## 1.5.0 — 2026-09-23

### Added

- **`/gh-issue` and `/jira-to-gh` auto-apply a `lean` label at intake (#15).** A
  smallness heuristic (one shippable outcome, ~1-2 files, no new dependency, no new
  public API, none of auth/authz, migrations, payment, or a public API contract)
  idempotently labels an issue `lean` so `/run-issue` can pick the lean 5-station
  roster without a human remembering `--lean`. `/run-issue` gains an explicit `--full`
  flag; precedence is both flags → full, `--full` alone → full, `--lean` alone → lean,
  neither → the issue's label if present else full. Epic parents are never labelled;
  each child is judged independently, and `epic init --lean-children <n>,<n>` lets
  individual children opt into lean without losing their DAG wiring.
- **`.run-issue.json` can now pin `test_cmd` per repo (#27).** A top-level `test_cmd`
  override in the overlay is used verbatim by `aiw stack up` in place of the derived
  command, and survives every degraded stack path (lock-held, up-failed, no-app-service)
  instead of being silently overwritten with `""`. `run_suite` now also treats
  `stack=failed` as unconditionally unrunnable regardless of a leftover `test_cmd`,
  closing a false-RED hole a preserved override would otherwise open.
- **Post-check suite timeout is configurable per repo (#25).** The hardcoded 900s
  timeout on the sdet/dev post-check's test run is now `checks.suite_timeout` in
  `.run-issue.json`, validated (positive int, bool excluded) and falling back to 900
  with a stderr warning on any invalid value.
- **`aiw pr open`'s push timeout is configurable per repo (#28).** A new `pr.push_timeout`
  key (default 600s) follows the same validate-and-fallback pattern as `suite_timeout`.
  A genuine timeout (return code 124) now reports a distinct message naming the
  effective timeout and noting the push may still be running, instead of a generic
  "push failed:" with no context.

### Fixed

- **`pr-grind` Step 1 discarded real review findings to a same-commit rubber-stamp
  review (#24).** A reviewer bot posting a substantive `COMMENTED` review followed
  seconds later by a zero-comment `APPROVED` rubber stamp on the identical commit made
  "take the newest only" silently reinstate the exact bug the round was meant to catch.
  A new `run-engine/review.py` (`aiw review pick`) prefers the comment-carrying review
  within a 60s same-commit window regardless of posting order; different-commit rounds
  and genuine multi-comment re-reviews still resolve to newest, unchanged.
- **Exit-6 (test-ownership violation) recovery could be blocked by a git safety hook
  (#26).** The documented `git checkout <sdet_sha> -- <paths>` recovery is now paired
  with a fallback — `git show <sdet_sha>:<path> > /tmp/<file>` plus a plain file write —
  for environments where a discard-pattern command is blocked even scoped to one file.
  Mirrored in the engine's own exit-6 stderr message, not just the docs.

## 1.4.1 — 2026-09-22

### Fixed

- **Parallel `/run-issue` runs could collide on Docker test stacks (#21).** `-p
  runissue-<issue>` namespaced container names only, never published host ports, and
  had no repo component — so the same issue number in two different repos shared one
  Compose project (a `down -v` from either tore down the other's containers/volumes),
  and two different issues in the same repo with any `ports:` mapping collided on the
  host port. `stack.py` now keys the Compose project (and its lock) on both repo and
  issue (`runissue-<repo-slug>-<digest>-<issue>`), force-publishes every declared port
  to an OS-chosen one, and reads the real port back via `docker compose port` after
  `up --wait`. The host-wide lock is now per-project: a live lock on an unrelated
  project never blocks a new run, while a second `up` on the *same* project still
  serializes as before. Also closes a lock/teardown leak in the "no app service
  identified" branch, and raises `epic.max_stacks`'s default (1 → 3) now that the
  port-collision blocker forcing it to 1 is gone.

## 1.4.0 — 2026-09-22

### Added

- **`aiw dispatch plan`: batch roster resolution and DoR pre-screen (#14).** Resolves a
  batch of issues to run from `--issues`, `--query`, `--project`+`--status`, or `--epic`,
  then mechanically pre-screens each for Definition-of-Ready gaps, skip reasons (already
  has an open PR, already closed), and lane mode — before any of them reach `/run-issue`.
  Adds an atomic `checkouts.json` registry, mirroring `epic.py`'s file shape, so concurrent
  dispatches share one source of truth for which repo checkout each issue runs against.
- **Per-host stack lock (#14).** `aiw stack up`/`down` now serialize against each other
  across separate OS processes, not just threads within one interpreter, using an atomic
  `O_CREAT|O_EXCL` lock file. Staleness reclaim is ledger-status-based (`done`/`escalated`
  reclaim immediately; a still-`running` holder is bounded by `LOCK_GRACE`), not a bare
  timer, so a lock abandoned by a finished run no longer outlives every contender's
  `--lock-timeout`. `stack up` gained a `--lock-timeout` flag (default 900s) and degrades
  to `stack=failed` + `tests_unverified` on timeout instead of racing another run's writes.

## 1.3.1 — 2026-09-22

### Fixed

- **`/gh-issue`'s and `/intake`'s HARD RULE blocks silently halted `/run-issue`.**
  Both rules were unbounded, so once read into context they were treated as binding
  for the rest of `/run-issue`'s turn — silently halting the pipeline right after an
  intake-routed issue was filed, instead of continuing on to Preflight step 3 and
  Gate 1 as designed. Both rules are now explicitly scoped to their own skill's
  steps, with an explicit handback stated both where the rule is defined and at
  `/run-issue`'s call site.

## 1.3.0 — 2026-09-21

### Added

- **Content-oriented intake.** `/run-issue` and `/gh-issue` now accept a Sentry issue
  link, a BRD file path, an Obsidian vault note, or free text — not only a GitHub issue
  number/URL. A new `/intake` command normalizes any of those into an issue brief
  (auto-detected, no flags); `/gh-issue` files it as a real issue exactly as it would a
  hand-written description, and `/run-issue` runs `/intake` then `/gh-issue` automatically
  when its argument isn't already an issue reference. The GitHub issue stays the single
  source of truth — nothing downstream of Preflight step 1 changed. A BRD describing more
  than one independently-shippable outcome prompts once to pick which one to run now; every
  other source never prompts.

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
