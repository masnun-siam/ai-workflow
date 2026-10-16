# aiw CLI

Covers: `bin/aiw`, `run-engine/route.py`, `run-engine/shared.py`, `run-engine/stack.py`, `run-engine/worktree.py`, `run-engine/maintree.py`, `run-engine/threads.py`, `run-engine/pr.py`, `run-engine/ci.py`, `run-engine/gitnexus.py`, `run-engine/project.py`, `run-engine/epic.py`, `run-engine/review.py`, `run-engine/ask.py`, `run-engine/refined.py`, `run-engine/peer_review.py`, `run-engine/dispatch.py`

`aiw` is the deterministic CLI behind every command, skill and agent in this plugin. How the engine decides is in [engine.md](engine.md). The UI server it starts is in [ui.md](ui.md).

## How it resolves

- `bin/aiw` is a `sh` shim: `exec python3 <plugin_root>/run-engine/route.py "$@"`. The plugin's `bin/` is on `PATH`, so markdown never spells an absolute path.
- It is not called `route` because `/sbin/route` (the network command) shadows it on macOS and exits 0 on bad input. Callers check that `aiw paths` prints JSON whose first key is `plugin_root`.
- `route.main` builds one argparse tree. It defines the ledger subcommands itself, then calls `module.register(sub, add)` for `stack, worktree, maintree, threads, pr, ci, gitnexus, project, epic, review, ui_server, ask, refined, peer_review`. Adding a subcommand is a module with `register` plus one entry in that tuple.
- `add(name, help)` creates a subparser with a positional `run_dir` and `--repo`. Modules with sub-operations (`stack up`, `epic split`) declare their own args instead.
- `--repo` default everywhere: ledger `context.repo`, else the current directory.

## Exit codes

| Scope | Codes |
|---|---|
| `aiw route` | 0 ok, 2 usage, 3 unreadable artifact, 4 not a JSON object, 5 contract violation, 6 test-ownership violation, 7 post-check refuted. Details: [engine.md](engine.md#aiw-route-step-by-step) |
| Mechanical subcommands | 0 ok, 1 the operation failed, 2 usage |
| Best-effort (`stack down`, `gitnexus`, `project-status`) | always 0 |
| Any `ValueError` escaping a command | 5 |

## Run ledger (`route.py`)

| Command | Args and flags | Does |
|---|---|---|
| `aiw init` | `<run_dir> --issue N [--no-review] [--repo PATH]` | Create `run.json` with the roster of `default_mode`. `--no-review` drops `reviewer` and `fixer`. Exits 2 if `run.json` exists |
| `aiw route` | `<run_dir> <artifact> [--repo PATH]` | Validate a station envelope (filename inside `run_dir`), run guards and post-checks, decide and print the next action |
| `aiw precheck` | `<run_dir> <station> [--repo PATH]` | Run the pre-guard for `sdet`, `reviewer` or `fixer`. Exit 1 means do not dispatch; other stations print `no pre-guard` |
| `aiw classify` | `<run_dir> [--loc N] [--labels a,b] [--depth N] [--repo PATH]` | Score the changed paths read from stdin; writes `45-classification.json` and the ledger. Omit `--depth` when unknown |
| `aiw resolve-review` | `<run_dir> [--repo PATH]` | Print the specialist lenses to spawn, one per line (needs `classify` first) |
| `aiw skip-review` | `<run_dir> [--repo PATH]` | Drop `reviewer` and `fixer` from a live run before the reviewer is current. Exit 1 once review started |
| `aiw set` | `<run_dir> key=value [...] [--repo PATH]` | Write string values into `context`; prints the whole context |
| `aiw paths` | none | Print resolved paths as JSON and create `runs_dir` and `pr_grind_dir` |

`set`, `route` and `skip-review` run under the ledger lock.

## Workspace and test stack

| Command | Args and flags | Does |
|---|---|---|
| `aiw worktree create` | `<run_dir> [--title T] [--base B] [--repo MAIN] [--main-tree]` | Fetch the base, add `../wt-issue-<n>` on branch `issue-<n>-<slug>`, copy gitignored secret files, install deps, exclude `.docker-agent.yml`. `--main-tree` branches inside the main checkout instead and records `carried` |
| `aiw maintree acquire` | `<owner/repo> <issue> [--grind] [--wait SECONDS]` | Take the main tree or join its queue. Prints `granted` or `waiting for #n (...) — position k`; exit 0 either way, 130 on Ctrl-C |
| `aiw maintree status` | `<owner/repo>` | Holder (with computed phase) and queue as JSON |
| `aiw maintree release` | `<owner/repo> [--issue N]` | Free the main tree |
| `aiw stack up` | `<run_dir> [--repo PATH] [--lock-timeout SECONDS]` | Detect a test compose file, start it with resource caps and ephemeral ports, record `test_cmd` and URLs. Degrades to `stack=none` or `stack=failed` with exit 0 |
| `aiw stack down` | `<run_dir> [--repo PATH]` | Tear down and release the stack lock. Always exit 0 |
| `aiw stack rebuild` | `<run_dir> [--repo PATH]` | Rebuild the app service when the source is not mounted; no-op otherwise |
| `aiw stack status` | `<run_dir> [--repo PATH]` | `healthy: …` or `unhealthy: …` (exit 1) for the app service |
| `aiw gitnexus` | `sync\|index\|clean <repo> [--run-dir DIR]` | Refresh, rebuild or clean the GitNexus index; `--run-dir` records `gitnexus=<key\|none>`. `clean` skips a main checkout |

## GitHub

| Command | Args and flags | Does |
|---|---|---|
| `aiw pr open` | `<run_dir> --body-file F [--title T] [--base B] [--draft] [--repo PATH]` | Link the branch to the issue, push, `gh pr create` (`--fill` without `--title`), verify both links, fall back to an issue comment. Records `pr`, `pr_number`, `link`. Exit 1 on a failed push with the hook output |
| `aiw ci status` | `<pr> [--watch] [--timeout SECONDS]` | Print `green`/`red`/`pending`, head sha and failing jobs with log excerpts. `--watch` polls every 30 s up to `--timeout` (default 1200) |
| `aiw threads list` | `<pr> [--open-only] [--for-comment ID]` | Every review thread as JSON (`node_id`, `is_resolved`, `is_outdated`, `comment_id`, `url`, `path`, `line`) |
| `aiw threads resolve` | `<node_id> [...]` | Resolve threads; warns per failure, exit 1 only if all fail |
| `aiw review pick` | `--reviews F --comments F [--window SECONDS]` | From `gh api …/reviews` and `…/comments` JSON, pick the review that carries the round's verdict (pr-grind). Flow: [features/review.md](features/review.md) |
| `aiw project-status` | `<owner/repo> <issue> "<status>"` | Move the issue's Projects v2 Status, matching option names by significant words. Best-effort |

`<pr>` accepts a PR URL, `owner/repo#N`, `owner/repo N` or a bare number (resolved from the checkout's remote).

## Issues and epics

| Command | Args and flags | Does |
|---|---|---|
| `aiw refined` | `<run_dir> --body-file F [--labels a,b] [--repo PATH]` | If the issue is `refined` and the body parses, write `00-readiness.json` (skip) and `10-plan.json`. Exit 1 `not refined: <reason>` otherwise |
| `aiw epic split` | `<epic_dir> --parent N --slug owner/repo --children a,b,c [--max-stacks N]` | Link children as sub-issues, build the DAG from their `Depends on:` lines, write the parent's `## Tasks` checklist and `epic.json`. `--max-stacks` default 3 |
| `aiw epic blockers` | `<epic_dir> [--dry-run]` | Add GitHub blocked-by edges missing from the `Depends on:` lines; report extra edges, never delete |
| `aiw epic init` | `<epic_dir> --runs-dir DIR --repo MAIN` | `aiw init` one run dir per child (idempotent), recording `epic` and `depends_on` |
| `aiw epic next` | `<epic_dir> --runs-dir DIR` | JSON: children that may advance now, plus every child's state |
| `aiw epic status` | `<epic_dir> --runs-dir DIR` | One line per child: status, station, PR, `blocked_on`, `blocker_ask` |

Epic flow: [features/run-issue.md](features/run-issue.md) and [features/planning.md](features/planning.md).

## Peer review, UI and headless

| Command | Args and flags | Does |
|---|---|---|
| `aiw peer-review new` | `<kind> [--slug S \| --id ID]` | Create and print a fresh review dir; never reuses one |
| `aiw peer-review next` | `<review_dir> --artifact F [--kind K] [--lenses a,b] [--prior F] [--max-rounds N] [--more]` | Open the next round or decide the open one; JSON on stdout |
| `aiw peer-review verdict` | `<review_dir> --lens L --file F\|-` | Validate and record one lens's verdict |
| `aiw peer-review diff` | `--since <sha\|@{u}\|HEAD> [--repo PATH] [--max-lines N]` | The change since a commit, minus secrets, binaries and lockfiles, capped |
| `aiw ui` | `[--port 8420] [--allow-host HOST]... [--no-tailscale] [--tailscale-port 443\|8443\|10000]` | Start the control UI server. Details: [ui.md](ui.md) |
| `aiw ask` | `[--json JSON]` (else stdin) | Record a gate question for a headless UI session (`AIW_UI_SESSION`); the model then ends its turn. Exit 2 outside a UI session |

Peer review flow and file layout: [features/peer-review.md](features/peer-review.md).

## `aiw paths`

Prints JSON, in this key order, and creates `runs_dir` and `pr_grind_dir`:

| Key | Value |
|---|---|
| `plugin_root` | parent of `run-engine/` |
| `data_dir` | `$CLAUDE_PLUGIN_DATA`, else `~/.claude/plugins/data/ai-workflow` |
| `runs_dir` | `<data_dir>/runs` |
| `pr_grind_dir` | `<data_dir>/pr-grind` |
| `channels` | `<data_dir>/channels.json` |
| `checkouts` | `<data_dir>/checkouts.json` |
| `config` | `<plugin_root>/run-engine/config.json` |
| `dod` | `<plugin_root>/definition-of-done.md` |
| `dor` | `<plugin_root>/definition-of-ready.md` |
| `agents_dir` | `<plugin_root>/agents` |

`commands/run-issue.md` substitutes `<runs_dir>`, `<channels>`, `<dod>` and the rest literally from this output.

## State on disk

The data dir sits outside the plugin install so it survives plugin upgrades.

| Path | Written by | Holds |
|---|---|---|
| `<data_dir>/runs/<owner>-<repo>-issue-<n>/` | `aiw init`, stations, `aiw classify` | `run.json`, `.run.lock`, station envelopes (`00-readiness.json` … `60-fix.json`), `45-classification.json`, `48-<lens>-verdict.json` |
| `<data_dir>/runs/<owner>-<repo>-epic-<n>/epic.json` | `aiw epic split` (dir chosen by the caller; this is the `/run-issue` convention) | `parent`, `slug`, `children`, `dag` (`order`, `deps`), `max_stacks` |
| `<data_dir>/pr-grind/<owner>-<repo>-<pr>.md` | `/pr-grind` | Grind state file, also read by `maintree` and the UI |
| `<data_dir>/channels.json` | the user | Slack review loop config (`channels`, `owner_uid`, `known_bots`, templates). See [features/setup.md](features/setup.md) |
| `<data_dir>/checkouts.json` | `dispatch.register_checkout` (UI) | `owner/repo` to local checkout path |
| `<data_dir>/locks/<compose project>.lock` | `aiw stack up` | Stack lock holder (`run_dir`, `issue`, `repo`, `acquired_at`) |
| `<data_dir>/maintree/<owner>-<repo>.json` (+ `.lock`) | `aiw maintree` | `holder` and `queue`; a queued waiter that has not polled for 15 min drops out |
| `<data_dir>/peer-review/<kind>/<name>/` | `aiw peer-review` | `round-<n>/request.json`, `<lens>.json`, `decision.json` |
| `<data_dir>/sessions/`, `pipelines/`, `flows/`, `ui.json`, `ui_settings.json`, `afk.json`, `gh-status.json`, `titles.json`, `grind_requests.json`, `grind_notified.json` | `aiw ui` | UI state. See [ui.md](ui.md) |

Outside the data dir:

| Path | Holds |
|---|---|
| `<main checkout>/../wt-issue-<n>/` | The run's worktree (not created with `--main-tree`) |
| `<worktree>/.docker-agent.yml` | Generated Compose override (limits, ephemeral ports); listed in `info/exclude`, never committed |
| `<repo>/.run-issue.json` | Per-repo config overlay. Keys: [engine.md](engine.md#config) |

Environment variables (names only): `CLAUDE_PLUGIN_DATA` (data dir), `AIW_UI_SESSION` (set by the UI runner, read by `aiw ask`), `AIW_HEADLESS` (set by the UI runner on a pr-grind re-entry; see [ui.md](ui.md)).
