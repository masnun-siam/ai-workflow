# Docs index

Covers: `docs/`

Synced to: 561e5fde33ff21a84bbbd4e054b4389f9718461b (2026-10-16)

Written for an AI agent about to work on this repo. Terms are in [CONTEXT.md](../CONTEXT.md); the stable project baseline is `CLAUDE.md`.

| Doc | Read it when |
|---|---|
| [architecture.md](architecture.md) | First. Components, how they talk, data stores, main flows |
| [development.md](development.md) | Before changing anything: setup, tests, hooks, CI, docs rules, how to add a station, subcommand or skill |
| [engine.md](engine.md) | Changing `run-engine/` routing, the ledger, envelopes, post-checks, budgets or `config.json` |
| [cli.md](cli.md) | Calling or adding an `aiw` subcommand; finding where state lives on disk |
| [plugin.md](plugin.md) | Looking up a slash command, an agent and its tools, or plugin conventions |
| [ui.md](ui.md) | Changing the `aiw ui` server: flags, security, state files, sessions, timers |
| [ui-api.md](ui-api.md) | Adding or calling an `aiw ui` HTTP route |
| [ui-frontend.md](ui-frontend.md) | Changing `run-engine/ui_static/` |
| [features/setup.md](features/setup.md) | Installing and configuring the plugin (an agent can follow it as a protocol) |
| [features/run-issue.md](features/run-issue.md) | Working on `/run-issue`: preflight, roster, stations, gates, worktree and stack |
| [features/epic-mode.md](features/epic-mode.md) | Working on `/run-issue <parent>` |
| [features/review.md](features/review.md) | Working on review, fix, CI, `/pr-grind`, `/pr-fix-comments` or lessons |
| [features/planning.md](features/planning.md) | Working on idea → issues: intake, dump, gh-issue, jira-to-gh, create-prd, create-tasks, refine-issues, flow |
| [features/peer-review.md](features/peer-review.md) | Working on `/peer-review` or `--review` |
| [features/dispatch.md](features/dispatch.md) | Working on `herdr-dispatch` or `run-engine/dispatch.py` |
| [features/utilities.md](features/utilities.md) | Working on `/release-pr`, `/worklog` or the `ship` agent |

Not agent docs, kept as they are:

| Path | Holds |
|---|---|
| `docs/adr/` | Architecture decision records (design history) |
| `docs/prds/` | PRDs, owned by `/create-prd` |
| `docs/tasks/` | Task lists, owned by `/create-tasks` |
| `docs/overview.html` | Human overview page, deployed to GitHub Pages by `.github/workflows/pages.yml` |

Every doc's `Covers:` line lists the paths it describes; a docs update maps each changed file to the docs that cover it.
