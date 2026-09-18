# ai-workflow

GitHub issue → reviewed PR, as a Claude Code plugin. One orchestrator command drives a
roster of specialised agents through a deterministic routing engine, stopping for a human
in **exactly three places**: plan approval, an escalated review finding, and the final
ready-to-merge handback.

## Install

```bash
git clone git@github.com:masnun-siam/ai-workflow.git ~/Documents/Projects/Personal/ai-workflow
```

Then in Claude Code:

```
/plugin marketplace add ~/Documents/Projects/Personal/ai-workflow
/plugin install ai-workflow@ai-workflow
```

You'll be prompted for `slack_owner_uid` (the @-mention target for review threads). Skip
it if you don't use the Slack review loop.

## Use

```
/ai-workflow:run-issue <issue-number-or-url> [--lean]
```

`--lean` runs a shorter roster (researcher → planner → dev → reviewer → fixer): no
independent RED tests, no runtime verification, no specialist panel. The CI gate still
applies. Use it for low-risk, well-specified work; use full mode for auth, migrations,
payments, or public API contracts.

Other commands: `/ai-workflow:gh-issue`, `/ai-workflow:issue-to-pr`,
`/ai-workflow:jira-to-gh`, `/ai-workflow:pr-fix-comments`.

## Dependencies

| What | Needed for | Without it |
|---|---|---|
| `gh` CLI, authenticated | everything | hard requirement |
| Python 3.10+ | the routing engine | hard requirement |
| [gstack](https://github.com/garrytan/gstack) at `~/.claude/skills/gstack` | phase 4.5 runtime verification (`qa-only`) | phase 4.5 returns `UNVERIFIABLE` (`gstack-not-installed`) and the run continues |
| `slackcli` | the Slack review-trigger loop (phase 10) | skip the grind; the PR still lands at Gate 2 |
| gitnexus MCP | code-graph lookups in several agents | agents fall back to grep/glob |

Everything else — the Laravel review panel, the notes-vault `dump` skill, `pr-review`,
`pr-grind`, `worklog` — ships in this plugin.

## Where state lives

Nothing stateful lives in this repo. `aiw paths` resolves everything at run start:

| Key | Contents |
|---|---|
| `runs_dir` | one directory per run; `run.json` is the only source of truth |
| `pr_grind_dir` | one markdown file per PR under review |
| `channels` | `channels.json` — `owner/repo` → Slack channel, `bot_uid`, `owner_uid`, trigger templates |

These sit under `$CLAUDE_PLUGIN_DATA` (default `~/.claude/plugins/data/ai-workflow`),
which **survives plugin upgrades** — in-flight runs are not lost when you update.

`channels.json` is not shipped. Create it before using the Slack loop:

```json
{
  "bot_uid": "U...",
  "owner_uid": "U...",
  "channels": { "owner/repo": "C..." },
  "trigger": "...",
  "retrigger": "..."
}
```

## Layout

```
commands/     run-issue (the orchestrator) + 4 intake commands
agents/       11 run-* pipeline agents + ship, worklog-runner, gh-issue-factchecker
skills/       pr-review, pr-grind, worklog, dump, 7 Laravel reviewers
run-engine/   engine.py (pure), route.py (CLI), checks.py + stack/worktree/
              threads/pr/ci/gitnexus/project (the mechanical phases),
              config.json (policy)
bin/aiw       PATH shim so no markdown spells an absolute path.
              NOT named `route`: that is the system network command, and
              /sbin shadows plugin bins on a default macOS PATH.
```

`run-engine/config.json` is the policy surface: station roster, bounce cap, mode
definitions, diff classification, and the specialist review panel. A repo can override any
of it with a `.run-issue.json` at its root (deep-merged).

## Tests

```bash
python3 run-engine/test_engine.py
```
