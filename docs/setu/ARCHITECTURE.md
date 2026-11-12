# setu (সেতু) — architecture

setu is a local frontend for Claude Code. It starts headless `claude -p` sessions that run the
**blubird** plugin's skills (and four built-in prompts), watches GitHub, and shows what needs the
user. It replaces the `ai-workflow` plugin and its Python `aiw` engine. It is not a plugin.

Parity specs for the engine being replaced: `docs/setu/engine/{sessions,github,workflows}.md`.
Behaviour there is the contract unless this file overrides it.

## Decisions (settled with the user)

| Topic | Decision |
|---|---|
| Backend | Go, one static binary `setu`, UI embedded. Std lib first; a dependency only when the std lib truly lacks it (web push crypto may need one). |
| Frontend | Preact + @preact/signals + Vite + TypeScript, in `web/`. Built to `internal/web/dist/` and **committed**, so `go build` needs no Node. |
| State | `~/.setu/` (override `SETU_HOME`). First start copies `~/.claude/plugins/data/ai-workflow/` into it once (marker `~/.setu/.migrated`). Never deletes the old dir. |
| Workflow skills | blubird plugin (`/blubird:<skill>`), found via `~/.claude/plugins/installed_plugins.json` (respect `CLAUDE_CONFIG_DIR`). Missing → banner, blubird actions disabled. Settings can install/update it: `claude plugin marketplace add blubird-interactiveltd/agentic-workflow`, `claude plugin install blubird@agentic-workflow`, `claude plugin marketplace update agentic-workflow` (+ `claude plugin update blubird@agentic-workflow` when available). |
| Built-in prompts | `release-pr`, `pr-grind` (merged version), `release-note`, `peer-review`. Live in `prompts/<name>/SKILL.md` (+ `scripts/`), embedded with `embed.FS`, extracted on start to `~/.setu/prompts/<binary-version>/<name>/`. A session's prompt = `Base directory for this skill: <dir>\n\n<SKILL.md body without frontmatter>\n\nARGUMENTS: <args>`. Any `aiw <verb>` in them becomes `setu <verb>`. |
| Runner | Headless `claude -p` stream-json sessions, as today. |
| Parallel | Both: setu Dispatch (own lanes, `blubird:implement-issue` per issue) and blubird `project-coordinator` (setu starts it and reads `~/.claude/project-coordinator/{claims,runs}/`). |
| Kept features | Sessions core, accounts + usage, GitHub poller + board, inbox, dispatch + coordinator, away mode + away answerer, notifications (macOS + phone push PWA over tailnet), peer review panel, grind state, Jev + Vault, merge cleanup, small changes, cost + transcripts. |
| Dropped | PRD shares/public pages, Codex harness, herdr, install-skills, the ai-workflow-personal plugin (dump/worklog/sync-from-wasensi), `site/`, `kanban.html`, plugin manifest, imported guides/templates/skills/agents. |
| Product model | blubird's: a Product = one Documentation Repo (`docs/prds/<module>/<feature>.md`, epics, `.blubird/repos.json`) + its code repos (`.blubird/docs-repo` pointer). Monorepo = one repo with a `"."` entry. Board statuses Backlog, Ready, In progress, In review, Done — read from the GitHub Projects v2 Status field when the issue is on a project, else derived. Base branch `staging`. Agents never merge. |
| Hook state | Show blubird hook events (secret masking, idle guard, CLAUDE.md guard) found in a session's stream in the session view. |
| Audience | One user (the owner). Release-note defaults are global settings (channel `#dc-supports`/`C06RSFFRUFM`, CC Ashique `UAY0MVDHT`, Najmul `U01012AA4FL`, Abir `U067P3ADDDM`, suffix `vai`). |
| UI | Screens: River (pipeline home), Inbox, Runs, Releases, Ops, Me, Settings. Settings › Appearance: Look (Classic \| Console \| River), Mode (System \| Dark \| Light), Layout (Rail + drawer \| Tabs + split). Default Classic + drawer + System. Keyboard first, mouse works. Reference prototype: `docs/setu/prototype/` (setu.html, setu.css, setu.js). |

## Layout

```
cmd/setu/            main.go — CLI entry (subcommands below)
internal/
  home/              data dir, migration, atomic JSON store, file locks
  settings/          settings schema, defaults, validation
  claude/            launching `claude`, stream-json parsing, accounts, usage
  sessions/          session records, lifecycle, transcripts, questions/answers, restart recovery
  prompts/           embedded built-in prompts, extraction, registry (step → blubird|setu skill, runs_in)
  blubird/           detect, version, install/update
  gh/                thin wrapper over the `gh` CLI (graphql, api, pr, issue), rate limits
  poller/            per-product polling, snapshots
  products/          docs repo + code repos model, PRDs, epics, board status
  inbox/             items, urgency, dismissals
  dispatch/          lanes, coordinator reading
  away/              away mode + away answerer
  notify/            macOS notifications, web push, tailscale address
  review/            peer review panel (lenses)
  grind/             grind mode + reviewers resolution
  jev/ vault/        integrations
  release/           release flow state (cut → grind → merge → notify)
  server/            net/http API + SSE stream + static UI
  web/               embed of web build (dist/)
prompts/             release-pr, pr-grind, release-note, peer-review (+ scripts)
web/                 Preact app source
docs/setu/           this file, API.md, engine specs, prototype
```

## CLI

`setu serve` (alias `setu ui`) · `setu paths` · `setu ask` · `setu ci status <pr> [--watch]` ·
`setu threads list|resolve` · `setu grind-mode [--pr]` · `setu grind-reviewers --pr` ·
`setu dispatch …` · `setu jev ci-hint|finding-hint --file` · `setu blubird status|install|update` ·
`setu version`. Output shapes and exit codes match the `aiw` verbs they replace (see engine specs),
because the built-in prompts call them.

## Server

- Binds `127.0.0.1:<port>` (default from settings, same default port as aiw so the phone PWA and
  bookmarks keep working) plus the tailnet address when enabled, as aiw did.
- JSON API under `/api/` (contract: `docs/setu/API.md`). Live updates over one SSE stream
  `GET /api/events` (topics: sessions, inbox, products, dispatch, usage, toast) — the UI
  refetches the topic's resource on an event. No polling from the UI except as SSE fallback.
- Serves the embedded UI at `/` with SPA fallback; PWA manifest + service worker for push.

## Resource budget

Idle RSS under 40 MB; no busy loops; GitHub polling adaptive (as aiw) and paused when nothing is
watched; one goroutine per live session; transcripts streamed to disk, never held whole in memory.

## Install on this machine

`make install` → builds the web app, `go build -o ~/.local/bin/setu ./cmd/setu`, writes
`~/Library/LaunchAgents/dev.setu.plist` (RunAtLoad, KeepAlive, `setu serve`), unloads the old
`dev.aiw.ui` agent if loaded, loads the new one. `make restart` rebuilds and kickstarts.

## Testing

Go: `go test ./...`, table tests, fakes for `claude` and `gh` (a fake binary on PATH driven by
fixture files), no network. Web: `vitest` for logic + a smoke render of each screen; `tsc --noEmit`.
End-to-end: start `setu serve` against a temp `SETU_HOME` with fake binaries, drive the API.
