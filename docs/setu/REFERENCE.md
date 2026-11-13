# setu reference

CLI verbs, data files and settings. The HTTP contract is [API.md](API.md) (endpoints §5, SSE §6, CLI §8); this file summarizes
what the code does. Where the two differ, the code wins.

## CLI

`setu <verb>`. Usage errors exit 64. Verbs run inside a session find the data dir through `SETU_HOME`.

| Verb | Purpose |
|---|---|
| `serve` (alias `ui`) | Run the app and API on 127.0.0.1. Flags: `--port N` (default 8420), `--allow-host H` (repeatable), `--no-tailscale`, `--tailscale-port 443\|8443\|10000`. Migrates the old data dir on first start. |
| `version` | Print `setu <version> (<commit>)`. |
| `paths` | JSON of the data, prompts, checkouts and channels paths, for the built-in prompts. |
| `ask [--json STR]` | Used by a session to ask the human; records a round in `meta.json` and ends the turn. Needs `SETU_SESSION`. |
| `hook idle` | The idle guard's Claude Code `Stop` hook: reads the hook input JSON on stdin, prints `{"decision":"block","reason":...}` to block an idle stop (at most 2 in a row, counted in `meta.json` `idle_blocks`), else nothing; the 3rd stop is allowed and sets `stalled`. Always exits 0; no `SETU_SESSION` or any error allows. |
| `ci status <pr> [--watch] [--timeout S]` | CI snapshot of a PR. |
| `threads list <pr>` / `threads resolve <node_id>...` | List or resolve review threads. |
| `grind start\|wait\|ci\|threads\|retrigger\|record\|pause\|done\|status\|mode\|reviewers` | Grind mechanics; exit codes in API.md §8. `grind-mode` and `grind-reviewers` are aliases. |
| `dispatch plan\|start\|ls\|show\|set\|pause\|resume\|cancel\|lane\|watch\|retry-failed\|end\|archive\|doctor` | Run an epic's issues as lanes. |
| `jev ci-hint\|finding-hint --file F` | Jev hints for the grind prompts. |
| `blubird status\|install\|update` | Detect, install or update the plugin; prints JSON. |
| `review lenses` | Peer-review lens config for the peer-review prompt. |

`<pr>` is a URL, `owner/repo#N`, `owner/repo N`, or a bare `N` (cwd's repo).

## Environment

| Variable | Use |
|---|---|
| `SETU_HOME` | Data dir override (default `~/.setu`). |
| `CLAUDE_CONFIG_DIR` | Where blubird and `claude` state live (default `~/.claude`). |
| `SETU_SESSION`, `SETU_HEADLESS` | Set by setu in child sessions (`AIW_UI_SESSION`, `AIW_HEADLESS` mirror them). `CLAUDE_PLUGIN_DATA` is never set. |
| `BLUBIRD_IDLE_GUARD=off` | Set in every session so blubird's idle guard does not block headless turn ends. |

## Data (`~/.setu`)

| Path | Holds |
|---|---|
| `sessions/<id>/` | `meta.json`, `stream.jsonl`, `stderr.log` per session |
| `ui_settings.json` | settings (below) |
| `ui.json` (0600) | ntfy, `public_url`, notification matrix |
| `push.json` (0600) | VAPID keys and push subscriptions |
| `checkouts.json`, `products.json` | repo slug to checkout path; Documentation Repo paths |
| `issue_grind.json` | per-issue grind switches |
| `channels.json` | Slack channels for grind (read only) |
| `pr-grind/` | one markdown state file per PR (plus `.lock`, `.last.json`); `grind_notified.json` |
| `dispatches/` | one JSON per dispatch (`archive/` for ended ones) |
| `afk.json` | Away mode |
| `peer-review/`, `config.json` | review panels and lens overrides |
| `releases/<id>.json`, `releases/<id>/note.md` | release flow state and the drafted note |
| `release-pr/` | dry-run output |
| `jev_cache.json` | Jev cache |
| `prompts/<version>/` | extracted built-in prompts; old versions are pruned after 5 |
| `.migrated` | marker for the one-time copy of `~/.claude/plugins/data/ai-workflow/` |
| `setu.log` | launchd stdout/stderr |

External, read only: `~/.claude/plugins/installed_plugins.json` (blubird), `~/.claude/project-coordinator/` (coordinator runs and claims),
`~/.claude*/projects/` (transcripts, copied on account rebind).

## Settings (`ui_settings.json`, edited in Settings)

`claude_label`, `commands` (accounts) and `default`; `repos` (per-repo options); `slack_channels`, `reviewers` and `active_reviewers`;
`vault_dir`; `grind_mode` (`deep`/`simple`) and `grind_limits` (`max_rounds`, `poll_interval`, `max_wait`, `max_idle_waits`, `stuck_seen`, `ci_timeout`, `ci_poll`);
`use_jev`; `idle_guard` (default on; an absent key reads as on); `run_model`, `run_effort`; `release_note` (channel, cc, suffix); `server` (`port`, `tailscale`, `tailscale_https_port`, `allow_hosts`).

Notification events: waiting, failed, dispatch, panel-cap, pr-ready, needs-cleanup, grind-paused, grind-done, done, afk, release.
Channels per event: browser, ntfy, mac, push.

Appearance (look, mode, layout) is not a server setting; it is kept in the browser (`setu.prefs.v1`).

## Built-in prompts

`release-pr`, `pr-grind`, `release-note`, `peer-review`, plus agent bodies `peer-reviewer` and `away-answerer`, in `prompts/`. Step registry: API.md §9.

## Build

| Command | Does |
|---|---|
| `make web` | Vite build into `internal/web/dist/` (committed) |
| `make test` | `go test ./...` plus web typecheck and tests |
| `make install` | build, install `~/.local/bin/setu`, sign it, load the launchd agent |
| `make codesign-setup` | once per machine: create the `setu-dev` self-signed code-signing identity (override `SETU_SIGN_ID`) |

`make install` and `make restart` sign the binary with that identity and identifier `dev.setu`, so a Full Disk Access
grant (System Settings → Privacy & Security → Full Disk Access → add `~/.local/bin/setu`) survives rebuilds. Without
the identity the binary is signed ad-hoc and macOS drops the grant on every rebuild.
