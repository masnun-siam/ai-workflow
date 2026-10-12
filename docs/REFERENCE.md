# Reference

## Commands

| Command | Does |
|---|---|
| `/ai-workflow:run-issue <n> [--full] [--no-review] [--grind]` | the full pipeline: issue → reviewed PR (`--no-review` skips review and fix; `--grind` keeps working the PR's review rounds after the handback, off by default). Accepts an epic parent. |
| `/ai-workflow:intake <source>` | normalize a Sentry link, BRD file, or vault note into an issue brief — used internally by `/gh-issue` and `/run-issue` |
| `/ai-workflow:gh-issue` | file a well-formed issue; always decomposes first — one task files one issue; two or more save the task list to `docs/tasks/<slug>.md` and file one refined issue per task, ordered by `Depends on: #n` lines, under an `epic` parent; `/gh-issue docs/tasks/<slug>.md` files a saved list, one question round per task |
| `/ai-workflow:create-tasks <problem-statement> [<prd>]` | break a problem statement and its PRD into a saved, ordered task list (`docs/tasks/<slug>.md`) using `/gh-issue`'s decomposition rules; files no issues. `/gh-issue docs/tasks/<slug>.md` then files them |
| `/ai-workflow:jira-to-gh <KEY>` | decompose a Jira ticket and file flat issues the same way as `/gh-issue` (one issue for a single task; two or more saved to `docs/tasks/<slug>.md` and filed flat) |
| `/ai-workflow:pr-fix-comments <pr>` | work through a PR's review comments, confirming each |
| `/ai-workflow:issue-to-pr` | the interactive, non-unattended variant |
| `/ai-workflow:flow <idea \| folder \| PRD \| issue numbers>` | the guided flow (`/flow` for short): dump → PRD → flat issues → herdr-dispatch for one feature, starting at whichever stage the input implies and stopping for your go at each boundary |

The default roster is researcher → planner → dev → reviewer → fixer. `run-dev` writes the
RED tests first, implements, and runtime-verifies in one dispatch, and also applies the
review findings. `--full` (or a `full` label) runs the seven-station roster with an
independent `run-sdet` and `run-verifier`. Use it for auth, migrations, payments, or public
API contracts. `--lean` and the `lean` label are deprecated aliases of the default. A
`refined` issue whose body passes `aiw refined` also skips the researcher and planner.

## The `aiw` CLI

The orchestrator never eyeballs a decision it can compute. Everything mechanical is a
subcommand:

```
aiw paths                          resolve every path, create the state dirs
aiw init | route | set             the ledger and the router
aiw precheck <station>             a station's pre-guard, before dispatching it
aiw refined                        plan from a refined issue body (skips researcher + planner)
aiw classify | resolve-review      score a diff, pick the specialist panel
aiw stack up|down|rebuild|status   the per-issue Docker test stack
aiw worktree create                the per-issue worktree
aiw pr open                        link the branch to the issue, push, open the PR
aiw threads list|resolve           PR review threads
aiw ci status                      check state plus the failing job's log
aiw gitnexus sync|index|clean      the code graph (best-effort)
aiw project-status                 GitHub Projects (best-effort)
aiw epic split|init|next|status    epic decomposition and sequencing
aiw ui [--port N] [--allow-host HOST]  local web UI to start and track sessions
```

## aiw ui

`aiw ui` serves a local web UI for starting and tracking headless Claude sessions.

- It binds to loopback only. `--port` sets the port (default 8420).
- `--allow-host HOST` is repeatable and matches exactly: use `name:port`, or the bare name for the default 443 serve.
- To reach it over a tailnet: `tailscale serve --bg 8420`, then
  `aiw ui --allow-host <machine>.<tailnet>.ts.net`.

Optional push notifications and links live in `<data_dir>/ui.json` (the data dir is
`$CLAUDE_PLUGIN_DATA`, default `~/.claude/plugins/data/ai-workflow`):

```json
{"ntfy": {"server": "<ntfy-server-url>", "topic": "<topic>", "token": "<token>"},
 "public_url": "<https://your-ui-url>"}
```

The file must be mode 0600 (`chmod 600 <data_dir>/ui.json`) because it can hold a token;
a looser mode is ignored with a warning. `AIW_NTFY_SERVER`, `AIW_NTFY_TOPIC` and
`AIW_NTFY_TOKEN` override the file. `public_url` is the base for push click-through links.

**Security:** there is no app-level auth. Access relies on tailnet ACLs, so anyone who can
reach the URL can start sessions. Sessions run `claude --dangerously-skip-permissions` by
default, with no opt-out flag. Never use `tailscale funnel` (public exposure plus skip-permissions
is remote code execution), and on a shared machine any local user can reach the loopback port.

## Where state lives

Nothing stateful lives in this repo. `aiw paths` resolves it at run start, under
`$CLAUDE_PLUGIN_DATA` (default `~/.claude/plugins/data/ai-workflow`), which **survives
plugin upgrades** — in-flight runs are not lost when you update.

| Key | Contents |
|---|---|
| `runs_dir` | one directory per run; `run.json` is the only source of truth |
| `pr_grind_dir` | one markdown file per PR under review |
| `channels` | `channels.json` — Slack ids and trigger templates |

## Layout

```
commands/     run-issue (the orchestrator) + 5 intake commands
agents/       12 run-* pipeline agents + ship, worklog-runner, gh-issue-factchecker
skills/       pr-review, pr-grind, herdr-dispatch, worklog, dump, prd, create-tasks, flow, 7 Laravel reviewers
run-engine/   engine.py (pure) · route.py (CLI) · checks.py (station post-checks)
              stack/worktree/threads/pr/ci/gitnexus/project/epic (mechanical phases)
              config.json (policy) · test_engine.py + test_scripts.py
bin/aiw       PATH shim. NOT named `route` — see INSTALL.md Step 3.
docs/         HOW-IT-WORKS, INSTALL, REFERENCE, adr/, prd/, tasks/
```

## Tests

```bash
python3 run-engine/test_engine.py     # the pure engine: routing, caps, contracts
python3 run-engine/test_scripts.py    # the mechanical phases
bash run-engine/run_tests.sh          # every test_*.py (~2 min); also the pre-push hook and CI
```

No network, no Docker, no install step.
