# setu (সেতু)

A local frontend for Claude Code. setu starts headless `claude -p` sessions that run the
[blubird](https://github.com/blubird-interactiveltd/agentic-workflow) plugin's skills, watches GitHub, and shows
what needs you: a question to answer, a PR to review, a release to cut. It is one Go binary with the web app embedded.
It is not a Claude Code plugin.

The process it drives: `PRD → tasks → refined issue → implement-issue → pr-review → grind → merge → release`.

## Install

Requires Go 1.27, Node 24 (only to rebuild the UI), the `claude` and `gh` CLIs, and the blubird plugin.

```sh
make install     # builds the web app and the binary, installs ~/.local/bin/setu and the launchd agent
setu serve       # or run in the foreground (alias: setu ui)
```

Open http://127.0.0.1:8420. `--port N`, `--allow-host H` and `--no-tailscale` override the saved server settings.
`setu serve` also exposes the app over `tailscale serve` when Tailscale is running (HTTPS port 443, 8443 or 10000).

## First run

1. Settings > Blubird: setu looks for blubird in `~/.claude/plugins/installed_plugins.json`
   (`CLAUDE_CONFIG_DIR` is respected). If it is missing, a banner shows and blubird actions stay disabled;
   Settings can install or update it.
2. Settings > Products: register a Documentation Repo checkout. Its `.blubird/repos.json` makes it and its
   code repos one product.
3. Settings > Accounts: pick the `claude` account(s) sessions run under.
4. If `~/.claude/plugins/data/ai-workflow/` exists, the first start copies it into `~/.setu/` once. The old dir is never deleted.

## Screens

The rail follows the old aiw UI. A top bar holds the **repo switcher** (the current repo: new runs start there, and its
product drives River, Releases and Ops), search (`Cmd/Ctrl-K`), the needs-you count and **New** (`n`). List pages have
a repo filter (`?only=owner/name`, default All repos). With no repo registered, every page but Settings opens onboarding.

| Key | Screen | What it shows |
|---|---|---|
| 1 | Inbox | everything waiting on you across your repos, ranked by urgency |
| 2 | Features | every PRD with its stage, issues and next step; a feature page per PRD (issues, PRD edit, peer review, sessions) |
| 3 | Small changes | file a small change (the list returns in a later phase) |
| 4 | Dispatches | dispatches with All / Needs you / Live / Finished, and Run an epic |
| 5 | Activity | live sessions, run history with search and result filter, coordinators, grinds, peer review |
| 6 | River | the pipeline by stage, with the cards in each |
| 7 | Releases | the release flow: cut, grind, merge, notify |
| 8 | Ops | repo and product upkeep (onboard, docs, security sweep) |
| 9 | Me | reconcile and weekly review |
| 0 | Settings | accounts, products and repos, blubird, notifications, away, review, appearance |

**New** (`n`) opens the Create box: describe a change, then file it as a Feature (PRD interview) or a Small change.
The command palette (`:`) opens the Start dialog: any command, where it runs (repo, another folder, or the notes vault),
its input (open issues and PRs are listed), model, effort, lenses and account.

The rail foot has Away mode (30 min to 4 h, or until a time), plan usage per account, the theme and the key sheet.

## Keyboard

`1`-`9` and `0` pages, `g` then `i`/`f`/`c`/`d`/`a`/`v`/`s` go to a page, `g r` opens the repo switcher, `n` New,
`j`/`k` move, `h`/`l` stage (River), `Enter` open, `a`/`b`/`c` answer a question, `:` or `Cmd/Ctrl-K` command
palette, `?` help, `Esc` back. Each screen lists its action keys in the footer. `.` cycles mode, `s` cycles look, `L` cycles layout.

## Appearance

Settings > Appearance, stored per browser: Look (Classic, Console or River), Mode (System, Dark or Light), Layout (Rail + drawer or Tabs + split).
Default: Console, System, drawer.

## Data

Everything lives in `~/.setu` (override with `SETU_HOME`). GitHub and the repo's `docs/prds/` stay the source of truth for work.
Files and settings: [docs/setu/REFERENCE.md](docs/setu/REFERENCE.md).

## Develop

`make test` runs the Go and web tests. See [CLAUDE.md](CLAUDE.md), [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/setu/](docs/setu/).
