# Reference

## Commands

| Command | Does |
|---|---|
| `/ai-workflow:run-issue <n> [--full] [--no-review] [--grind]` | the full pipeline: issue → reviewed PR (`--no-review` skips review and fix; `--grind` keeps working the PR's review rounds after the handback, off by default). Accepts an epic parent. |
| `/ai-workflow:intake <source> [--review [<lens,lens>] [--herdr]]` | normalize a Sentry link, BRD file, or vault note into an issue brief — used internally by `/gh-issue` and `/run-issue` (which never pass `--review`) |
| `/ai-workflow:dump <text> [--review [<lens,lens>] [--herdr]]` | file free-form input into the Obsidian vault's Project → Feature structure, after one confirmation |
| `/ai-workflow:gh-issue [--review [<lens,lens>] [--herdr]]` | file exactly one well-formed issue. It decomposes first; when the input splits into 2 or more tasks it creates nothing and ends `→ next: /create-prd <input>`. A standalone run ends `→ next: herdr-dispatch <n>` |
| `/ai-workflow:create-prd <requirement \| feature-folder> [--to <local,obsidian,wiki>] [--review [<lens,lens>] [--herdr]]` | grill a requirement into a PRD with its technical design (contracts, never code) and its epics, saved to `docs/prds/<slug>.md` (status Draft, In review, then Approved) and mirrored to the vault; `--review` runs the picked reviewer lenses (default critical; also CEO, CTO, security, QA, UX, performance) until every one approves (`--herdr`: one herdr tab per reviewer, terminal only); `--update <prd> <decisions>` records later decisions (plus a `## Change log` line once Approved); `/create-prd approve <prd-path \| slug>` sets Approved, files one epic per `## Epics` entry labelled `epic` + `prd-<slug>`, and writes the numbers back |
| `/ai-workflow:peer-review [--lenses <lens,lens>] [--since <sha\|@{u}>] [--herdr]` | a reviewer panel on Opus (critical, CEO, CTO, security, QA, UX, performance; default critical) on the session's change: the diff plus your final answer, checked against what you asked, until every picked lens approves. `--review` on `/create-prd`, `/intake`, `/dump` and `/gh-issue` runs the same loop on their draft before anything is saved or filed |
| `/ai-workflow:create-tasks <prd>` | split an Approved PRD into a saved, ordered list of one-PR tasks (`docs/tasks/<slug>.md`): each with an Area, a Parallel flag and dependencies inside its own epic, plus Waves and Shared files; tasks are never renumbered, only marked Changed or Dropped. Files no issues; ends `→ next: /refine-issues docs/tasks/<slug>.md` |
| `/ai-workflow:refine-issues docs/tasks/<slug>.md` | file each task as a `refined` sub-issue of its epic, after one confirmation, with `Depends on: #n` in the body and native blocked-by links (on an older `gh`, `/fix-blockers` sets them); runs one `aiw epic split` per epic; ends `→ next: herdr-dispatch <epic>` (when `--blocked-by` fell back, the report says to run `/fix-blockers <epic>` first) |
| `/ai-workflow:fix-blockers <parent>` | set GitHub's native "blocked by" relations between an epic's children from their `Depends on:` lines: previews, asks once, writes only the missing edges, reports (never deletes) edges no line names. A standalone command, not a Flow step |
| `/ai-workflow:jira-to-gh <KEY>` | turn a Jira ticket into exactly one issue the same way as `/gh-issue`; 2 or more tasks create nothing and end `→ next: /create-prd <jira-key-or-url>` |
| `/ai-workflow:pr-fix-comments <pr>` | work through a PR's review comments, confirming each |
| `/ai-workflow:issue-to-pr` | the interactive, non-unattended variant |
| `/ai-workflow:flow <idea \| folder \| PRD \| task list \| parent \| issue numbers>` | the guided flow (`/flow` for short): dump → create-prd → (Continue approves the PRD and files its epics) → create-tasks → refine-issues → herdr-dispatch for one feature; a bug goes gh-issue → dispatch. It starts at whichever stage the input implies and stops for your go at each boundary |

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
aiw epic blockers <dir> [--dry-run]   GitHub blocked-by edges from the children's Depends on lines
aiw peer-review new|next|verdict|diff   peer review: a fresh dir per run, open/decide rounds, record a checked verdict, the change to review
aiw ui [--port N] [--allow-host HOST]  local web UI to start and track sessions
```

## aiw ui

`aiw ui` serves a local web UI for starting and tracking headless Claude sessions.

- It binds to loopback only. `--port` sets the port (default 8420).
- `--allow-host HOST` is repeatable and matches exactly: use `name:port`, or the bare name for the default 443 serve.
- To reach it over a tailnet: `tailscale serve --bg 8420`, then
  `aiw ui --allow-host <machine>.<tailnet>.ts.net`.

**Peer review.** New run (both forms) and the Flow's PRD step have a **Peer review** box. Ticking
it shows the reviewers the command offers (from `GET /api/peer-review`, read from `config.json`),
with critical ticked. A doc command gets `--review <lenses>`. A custom prompt gets a fresh review
dir holding the prompt as `ask.md`, plus one line asking the session to run `/peer-review` with
that dir, the lenses and the HEAD at start. That line is not a gate. The session page shows
**peer review: approved / cap reached / unfinished / not run**, read from the review's rounds.

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
skills/       pr-review, pr-grind, herdr-dispatch, worklog, dump, create-prd, create-tasks, refine-issues, fix-blockers, flow, peer-review, 7 Laravel reviewers
run-engine/   engine.py (pure) · route.py (CLI) · checks.py (station post-checks)
              stack/worktree/threads/pr/ci/gitnexus/project/epic (mechanical phases)
              config.json (policy) · test_engine.py + test_scripts.py
bin/aiw       PATH shim. NOT named `route` — see INSTALL.md Step 3.
docs/         HOW-IT-WORKS, INSTALL, REFERENCE, adr/, prds/, tasks/
```

## Tests

```bash
python3 run-engine/test_engine.py     # the pure engine: routing, caps, contracts
python3 run-engine/test_scripts.py    # the mechanical phases
bash run-engine/run_tests.sh          # every test_*.py (~2 min); also the pre-push hook and CI
```

No network, no Docker, no install step.
