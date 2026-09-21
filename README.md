# ai-workflow

GitHub issue → reviewed PR, as a Claude Code plugin. One orchestrator command drives a
roster of specialised agents through a deterministic routing engine, stopping for a human
in **exactly three places**: plan approval, an escalated review finding, and the final
ready-to-merge handback.

**To understand how it works**, read [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md).
**To install it**, hand this repository to Claude Code and say "set this up" — the rest of
this file is the instruction it follows.

---

# Setup protocol — instructions for an AI agent

**You are reading this because someone asked you to install this plugin. Follow this file
top to bottom. It is a procedure, not a description.**

## Ground rules

1. **Ask before you install anything.** Show the user what is missing and what you propose
   to run, then wait. Package installs and auth flows are theirs to approve, once each.
2. **Never run an auth flow for them.** `gh auth login`, Slack tokens, API keys — print the
   command and let the human run it. Never ask them to paste a token to you.
3. **Never edit config you were not sent here to edit.** Their `~/.zshrc`, their global
   `settings.json`, their other plugins. If something needs a PATH change, say so; don't
   make it.
4. **Verify every step from something that has no incentive to pass.** An exit code, a
   parsed JSON key, a file that exists. "The command printed no error" is not verification
   — see step 3 for exactly how this bites here.
5. **Missing optional dependencies are fine.** Most of this degrades gracefully. Report what
   will be unavailable and continue; do not block a setup on a nice-to-have.
6. **Stop and report** if a step fails in a way this file does not describe. Do not
   improvise around a failure you cannot explain.

## Step 0 — Where is the repo?

If it is not already on disk, ask the user where they want it, then clone:

```bash
git clone https://github.com/masnun-siam/ai-workflow.git <chosen-path>
```

Default suggestion: `~/Documents/Projects/ai-workflow`. Use their answer, not the default.
From here, `<repo>` means that path.

## Step 1 — Check the hard requirements

Both of these are required. Without them, stop and report.

```bash
python3 --version          # need 3.10+
gh --version
gh auth status
```

- **Python 3.10+** — the routing engine. It is stdlib-only; there is nothing to `pip install`.
- **`gh`, authenticated** — every phase reads or writes GitHub through it.

If `gh auth status` fails, tell the user to run `gh auth login` themselves and come back.
Do not run it for them.

While you are here, check the scope that the Projects integration needs:

```bash
gh auth status 2>&1 | grep -i 'token scopes'
```

If `project` is absent, the board and status features will warn and skip. That is not a
blocker. Tell the user they can add it later with `gh auth refresh -s project`.

## Step 2 — Install the plugin

```bash
claude plugin marketplace add <repo>
claude plugin install ai-workflow@ai-workflow
```

**Expect this to succeed. If it fails with a manifest validation error, stop and report it**
— it means `.claude-plugin/plugin.json` is malformed, which is a bug in the repo, not in
their machine. (This exact failure shipped once: `userConfig` entries carried a `title` and
no `description`, and the plugin was silently uninstallable for weeks.)

Confirm it registered:

```bash
claude plugin list | grep -A3 ai-workflow
```

You want `Status: ✔ enabled`.

## Step 3 — Verify the CLI resolves to *this* plugin

**Do not skip this, and do not accept a zero exit code as proof.**

```bash
aiw paths
```

This must print JSON whose **first key is `plugin_root`**. Parse it and check that key.

Why the ceremony: this CLI used to be called `route`, which is also the macOS, BSD and
net-tools *network* command. On a default macOS `PATH`, `/sbin` sits ahead of the plugin bin
directories, so `route paths` ran `/sbin/route`, printed `route: bad keyword: paths` to
stderr, and **exited 0**. Every path the orchestrator needed then silently resolved to
nothing. A wrong binary exiting 0 is indistinguishable from a right one until something
downstream reads a value that was never substituted. Hence: check the key, not the code.

If `aiw` is not found at all, the plugin's `bin/` is not on `PATH`. Plugin bins are resolved
when a Claude Code session starts, so the usual cause is simply that this session began
before the install. Tell the user to restart their session and re-run `aiw paths`.

## Step 4 — Run the test suites

```bash
python3 <repo>/run-engine/test_engine.py
python3 <repo>/run-engine/test_scripts.py
```

Both must exit 0. Expect 17 and 35 checks respectively at time of writing; a higher number
is fine, a failure is not. These need no network and no Docker. If either fails, stop and
report the output — something is wrong with the checkout, not with their setup.

## Step 5 — Optional dependencies

Check each, report the result as a table, and let the user decide. **None of these blocks
installation.**

| Check | Enables | Without it |
|---|---|---|
| `docker info` | the per-issue test stack (phase 2.5) | `stack=none`; tests run on the host runner instead |
| `node --version` + `npx gitnexus --help` | code-graph lookups in several agents | agents fall back to grep/glob, slower but correct |
| `command -v slackcli` | the Slack review-trigger loop (phase 10) | no grind loop; the PR still lands at Gate 2 |
| `ls ~/.claude/skills/gstack` | runtime verification (phase 4.5) | phase 4.5 returns `UNVERIFIABLE` and the run continues |

Present it as findings, not as a shopping list. "Docker is not running, so runs on this
machine will use the host test runner" is more useful than "please install Docker".

## Step 6 — Configure

Two things are configurable. Both are optional; ask before writing either.

### 6a. Slack review loop

Only if the user wants the phase-10 grind loop. Resolve the data directory first:

```bash
aiw paths     # read the `channels` key from the JSON
```

Create that file with this shape:

```json
{
  "bot_uid": "U...",
  "owner_uid": "U...",
  "channels": { "owner/repo": "C..." },
  "trigger": "<@{bot_uid}> review {pr_url}",
  "retrigger": "<@{bot_uid}> recheck"
}
```

- `bot_uid` — the reviewer bot's Slack user id.
- `owner_uid` — the person @-mentioned when a PR is ready to merge. **Ask the user for
  theirs**; do not derive it from an email address or a name you found in a config file.
- `channels` — one entry per repo you will run against.

These are workspace identifiers, not secrets, but ask before writing the file and show them
its contents.

### 6b. Per-repo policy

Any repo can override the engine's policy with a `.run-issue.json` at its root, deep-merged
over `run-engine/config.json`. Do not create one during setup. Mention it exists and move on
— the defaults are stack-neutral and the override only earns its keep once they have run
something and found a rule they want changed.

## Step 7 — Report and hand back

Tell the user, in this order:

1. **Ready or not**, and if not, exactly what is missing.
2. **What will be degraded** and what that costs them concretely — "no Docker, so tests run
   on the host runner; on a repo whose tests need a database that will fail."
3. **The first command to try**, with a real issue number if they have one:

   ```
   /ai-workflow:run-issue <issue-number-or-url> [--lean]
   ```

4. **Point them at [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md)** before their first run —
   the three gates are the part worth understanding in advance, because everything else
   happens without them.

Do not run a pipeline yourself to "test the install". `/run-issue` opens pull requests and
comments on issues. That is the user's call on their repo, not a smoke test.

---

# Reference

## Commands

| Command | Does |
|---|---|
| `/ai-workflow:run-issue <n> [--lean]` | the full pipeline: issue → reviewed PR. Accepts an epic parent. |
| `/ai-workflow:intake <source>` | normalize a Sentry link, BRD file, or vault note into an issue brief — used internally by `/gh-issue` and `/run-issue` |
| `/ai-workflow:gh-issue` | file a well-formed issue; splits a large brief into an epic |
| `/ai-workflow:jira-to-gh <KEY>` | convert a Jira ticket into a GitHub issue |
| `/ai-workflow:pr-fix-comments <pr>` | work through a PR's review comments, confirming each |
| `/ai-workflow:issue-to-pr` | the interactive, non-unattended variant |

`--lean` runs a shorter roster — researcher → planner → dev → reviewer → fixer. No
independent RED tests, no runtime verification, no specialist panel. The CI gate still
applies. Use it for low-risk, well-specified work; use full mode for auth, migrations,
payments, or public API contracts.

## The `aiw` CLI

The orchestrator never eyeballs a decision it can compute. Everything mechanical is a
subcommand:

```
aiw paths                          resolve every path, create the state dirs
aiw init | route | set             the ledger and the router
aiw precheck <station>             a station's pre-guard, before dispatching it
aiw classify | resolve-review      score a diff, pick the specialist panel
aiw stack up|down|rebuild|status   the per-issue Docker test stack
aiw worktree create                the per-issue worktree
aiw pr open                        link the branch to the issue, push, open the PR
aiw threads list|resolve           PR review threads
aiw ci status                      check state plus the failing job's log
aiw gitnexus sync|index|clean      the code graph (best-effort)
aiw project-status | project-board GitHub Projects (best-effort)
aiw epic split|init|next|status    epic decomposition and sequencing
```

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
skills/       pr-review, pr-grind, worklog, dump, 7 Laravel reviewers
run-engine/   engine.py (pure) · route.py (CLI) · checks.py (station post-checks)
              stack/worktree/threads/pr/ci/gitnexus/project/epic (mechanical phases)
              config.json (policy) · test_engine.py + test_scripts.py
bin/aiw       PATH shim. NOT named `route` — see Step 3.
docs/         HOW-IT-WORKS.md, plus specs and plans under superpowers/
```

## Tests

```bash
python3 run-engine/test_engine.py     # the pure engine: routing, caps, contracts
python3 run-engine/test_scripts.py    # the mechanical phases
```

No network, no Docker, no install step.
