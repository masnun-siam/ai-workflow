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

- **Python 3.10+** — the `aiw` CLI and UI. It is stdlib-only; there is nothing to `pip install`.
- **`gh`, authenticated** — the process reads and writes issues and PRs through it.

If `gh auth status` fails, tell the user to run `gh auth login` themselves and come back.
Do not run it for them.

While you are here, check the scope that the Projects integration needs:

```bash
gh auth status 2>&1 | grep -i 'token scopes'
```

If `project` is absent, features that touch GitHub Projects will warn and skip. That is not a
blocker. Tell the user they can add it later with `gh auth refresh -s project`.

## Step 2 — Install the plugin

```bash
claude plugin marketplace add <repo>
claude plugin install ai-workflow@ai-workflow
```

**Upgrading from an older version:** reinstall after upgrading (`claude plugin marketplace update`,
then `claude plugin install ai-workflow@ai-workflow` again), and remove the old `shahria-skills`
local marketplace so the separate `dev-workflow` plugin stops shadowing these skills:

```bash
claude plugin marketplace remove shahria-skills
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

## Step 4 — Run the test suite

```bash
bash <repo>/run-engine/run_tests.sh
```

It must exit 0. It needs no network. If it fails, stop and report the output: something is
wrong with the checkout, not with their setup.

**Working on the web UI (developers only).** Using `aiw ui` needs no Node: its React app is built
into the committed `run-engine/ui_dist/`. To change it you need Node 20 and the source in `ui/`:

```bash
cd <repo>/ui
npm ci                 # once
npm run dev            # Vite dev server; proxies /api to `aiw ui` on 127.0.0.1:8420, so run that too
npm run typecheck && npm test
npm run build          # writes run-engine/ui_dist/; commit it with the source change
```

## Step 5 — Optional dependencies

Check each, report the result as a table, and let the user decide. **None of these blocks
installation.**

| Check | Enables | Without it |
|---|---|---|
| `node --version` + `npx gitnexus --help` | code-graph lookups in `implement-issue` and `pr-review` | grep and glob, slower but correct |
| `command -v slackcli` | the Slack reviewer-bot loop (`/pr-grind`, `/release-pr`) | no grind loop |
| `command -v herdr` | `herdr-dispatch`: an epic's lanes in separate terminal tabs | dispatch from the UI (headless lanes) |
| `command -v jev` | quick judgment calls in `aiw ui` (create box Auto route, Away mode risk check, Inbox order, readiness and duplicate warnings) and grind hints; needs a TypeSafe AI key | you pick routes yourself; everything else works as before |
| `command -v tailscale` | reaching `aiw ui` from your phone, and sharing a PRD for review | the UI stays on loopback; Share is unavailable |

Sharing a PRD publishes it through a tailscale funnel, so the tailnet policy must give the node the `funnel` attribute (and HTTPS certificates must be enabled for the tailnet; funnel runs only on ports 443, 8443 and 10000):

```json
"nodeAttrs": [{"target": ["autogroup:member"], "attr": ["funnel"]}]
```

Without it Share is refused with tailscale's own message and everything else works.

Present it as findings, not as a shopping list. "slackcli is missing, so PRs land without the review loop" is more useful than "please install slackcli".

## Step 6 — Configure

One thing is configurable, and it is optional; ask before writing it.

### Slack review loop

Only if the user wants the grind loop (`/pr-grind`, `/release-pr`). Resolve the data directory first:

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

## Step 7 — Report and hand back

Tell the user, in this order:

1. **Ready or not**, and if not, exactly what is missing.
2. **What will be degraded** and what that costs them concretely — "no slackcli, so PRs
   land without the reviewer-bot loop."
3. **The first command to try**, on a repo of theirs:

   ```
   /ai-workflow:create-prd <requirement>
   ```

   or, for an issue that is already refined, `/ai-workflow:implement-issue <issue-number>`.

4. **Point them at [HOW-IT-WORKS.md](HOW-IT-WORKS.md)** before their first run.

Do not run a stage yourself to "test the install". `/implement-issue` opens pull requests and
comments on issues. That is the user's call on their repo, not a smoke test.
