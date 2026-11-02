---
name: release-pr
description: Open (or refresh) a release PR from staging to master with an accurate release summary, deploy checklist and env/migration notes, then post the reviewer-bot trigger in Slack as a release announcement and hand off to /pr-grind. Also builds a partial release (a cherry-picked release branch) when part of staging must be held back. Use whenever the user says "create a release PR", "release staging to master", "cut a release", "open the staging → master PR", "release PR and grind it", "release everything except X", "skip <feature> from this release", or invokes /release-pr — even if they only say "release this" on a repo with a staging branch. Supports --dry-run to build the PR body and Slack message without creating or posting anything.
argument-hint: "[--dry-run] [head=staging] [base=master]"
allowed-tools: Bash(aiw:*), Bash(gh:*), Bash(git:*), Bash(bash:*), Bash(slackcli:*), Read, Write, Skill, AskUserQuestion
---

> **Paths.** `<...>` placeholders below are keys from `aiw paths` (run it; `aiw` is
> on `PATH` via the plugin's `bin/`). Substitute the printed value; never guess a path.

Create the release PR `<head>` → `<base>` (default `staging` → `master`) for the current
repo, then start the review loop on it. Arguments: `$ARGUMENTS`. `--dry-run` anywhere in
them means **build everything, write nothing to GitHub or Slack** (see Dry run below).

This skill writes a PR and one Slack message. It never merges, never edits code, and
never pushes.

Paths below starting `../../` are relative to this skill's folder, at the plugin root. Read first: `../../guides/engineering-workflow.md` ("Repository settings": the base branch and which guides, templates and skills win).

## Why this needs care

A release PR's commit list can't be trusted. When earlier releases were squash-merged, their
commits never reach `<base>`, so `<head>` keeps showing hundreds of commits "ahead" whose
content `<base>` already has. A summary built from that list over-reports. One built from
the batch you just merged under-reports: it misses older single PRs still waiting on
`<head>`. The data script fixes both. It starts from the last merged release PR, keeps the
PRs merged since then that are actually on `<head>`, and drops any PR whose changes
`<base>` already has. Trust its lists over your memory of the session.

## Step 1: Collect the facts

```bash
bash <plugin_root>/skills/release-pr/scripts/release-data.sh <head> <base>
```

It is read-only and takes about a minute, because it inspects each candidate PR. Its sections:

- **Branches:** ahead/behind counts, the content diff (files, +/−), the head SHA, any open
  release PR, and the previous release (the cutoff).
- **PRs in this release:** the included PRs. Children of a batch branch show the batch
  branch as their base. A PR tagged `[UMBRELLA]` is the batch PR itself; mention it once
  and list its children, so nothing is counted twice.
- **Excluded since the cutoff:** hotfixes that went straight to `<base>`, PRs whose changes
  `<base>` already has, and syncs from `<base>` into `<head>`. Don't list these as release
  content.
- **New env vars, .env.example additions, migrations, scheduler and queue changes:** the
  inputs for the deploy checklist.

Stop and tell the user when:
- **behind > 0:** `<base>` has commits `<head>` lacks, so the PR will conflict, or will
  silently revert hotfixes when merged. `<base>` needs syncing into `<head>` first. Offer
  to do that through a sync PR; don't do it yourself.
- **The PR list is empty:** nothing to release.

## Partial release: holding a theme back

Use this when the user wants only part of what's on `<head>` released ("skip the HubSpot
work", "release everything except X"). You can't leave PRs out of a `<head>` → `<base>`
PR, because `<head>` already contains their code. Build a separate release branch instead:

1. **Pick the PRs.** Run Step 1 on the normal `<head>` and group its PRs into themes. Show
   the user which PRs each theme covers and which ones are held back. Then check that the
   kept PRs don't depend on held-back ones. Compare their file lists
   (`gh pr view <n> --json files`); a shared file is fine (lang files, `.env.example`), but a
   kept PR calling code a held-back PR adds is not. If one does, ask the user before going on.
2. **If a release PR is open for `<head>`,** close it with a comment saying the release was
   re-scoped and naming what's held back. If a `/pr-grind` loop is running on it, write
   `done: <ISO8601> — superseded` into its state file and stop its monitor.
3. **Build the branch** `release/<YYYY-MM-DD>` from `origin/<base>`, in a separate worktree,
   so the user's checkout isn't touched. Cherry-pick each kept PR's merge commit, in the
   order they were merged, with `-x`, so every commit records its origin. Use `-m 1` when
   the commit is a merge commit (more than one parent); a squash-merged PR's commit is a
   plain commit and takes no `-m`. The commit hooks need `vendor/`, so symlink it from the
   main checkout into the worktree. On a conflict, stop and show the user the files; don't
   resolve it by guessing which side a held-back feature needs.
4. **Verify before pushing:**
   - grep the branch diff (`git diff origin/<base> HEAD`) for the held-back theme's
     distinctive names (classes, config keys, commands). Any hit means it leaked in.
   - `php -l` every changed PHP file.
   - Report the branch's diff stat. CI on the PR runs the full suite, so say that the
     tests haven't run locally rather than claiming they passed.
5. **Push** the branch. Then continue at Step 2 with `<head>` = the release branch, and with
   the kept PR numbers passed to the script:
   `RELEASE_PRS="<n> <n> …" bash <plugin_root>/skills/release-pr/scripts/release-data.sh release/<date> <base>`.
   Git history can't find cherry-picked PRs, so the script needs the list.

In the PR body, add a **Held back** section after "What's in it". It names each held-back
theme with its PR range, and says the code stays on `<head>` for a later release. In
**Merge method**, add that once this merges, `<base>` has to be merged back into `<head>`.
The cherry-picked copies then match what's already on `<head>`, so that merge is clean.

## Step 2: Check for blockers

```bash
gh issue list --state open --label bug --search "created:><cutoff>" --json number,title,url
```

Also count anything the user said in this session (e.g. "SMS isn't working on staging").
If something looks like a blocker, show it to the user and ask: keep it as a blocker in the
PR body, or leave it out. Don't decide on your own that a bug blocks the release, and don't
drop one silently.

## Step 3: Write the PR body

Group the included PRs into **themes** by what they deliver to users, not by branch. A
PRD label, a shared issue range (#5928–#5932), or a common prefix in the titles are good
signals. Put single fixes under **Other**. Each line is `#<pr>: <plain-language
outcome>`. Rewrite slug-style titles ("issue 5951 restrict unfinished signups …") into a
real sentence.

Use this structure:

```markdown
Release `<head>` → `<base>`.

> ⚠️ **Blocker:** <only if the user kept one in Step 2>

## What's in it

<When ahead is much larger than the included PRs' commits, say so in one sentence: the
real change is <N files (+a / −d)>, and the extra commits are squash history <base>
already has. Otherwise omit this paragraph.>

### <Theme> (<issue range or PRD>)
- #<pr>: <outcome>

### Other
- #<pr>: <outcome>

## Deployment checklist (<base> environment)

**Migrations:** <list, landlord vs tenant; "none" if none>

**New env vars:**

| Var | Value for <base> / default if unset |
|---|---|

**After deploy:**
- [ ] <migrate, if there are migrations>
- [ ] `php artisan config:cache`, if env or config changed
- [ ] `php artisan horizon:terminate`, if jobs, queues or config changed. Workers keep
      their old code and config until restarted.
- [ ] <one line per new scheduled command, external scope or IP whitelist this release needs>
- [ ] <one smoke test per theme that touches an external service>

## Merge method

Merge commit, not squash. Squashing is what makes `<head>` show commits "ahead" that
`<base>` already has, and it causes conflicts on the next `<base>` → `<head>` sync.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Rules:
- **Never put secret values in the body.** That covers API keys, tokens and passwords,
  even in a private repo, even if the user shared them earlier in the session. The PR
  outlives the session and gets read by more people. Write where to get the value (the
  ops issue, the vault entry) instead.
- **Env var defaults:** describe each one: what happens if it's unset, and any value
  that breaks things (e.g. "must differ from `SMS_PROVIDER`").
- **Checklist items:** derive each one from the data. A checklist item with no matching
  change in this release is noise.

**Title:** `Release: <head> → <base> — <theme>, <theme>, <theme>`. Name up to four
themes, in the order they appear in the body.

## Step 4: Create or update the PR

Write the body to a temp file and use `--body-file`, never `--body`: release bodies have
backticks and pipes that break shell quoting.

- **No open release PR:** `gh pr create --base <base> --head <head> --title "…" --body-file <file>`
- **One is already open** (Step 1 reports it): don't open a second one. Update it with
  `gh pr edit <n> --title "…" --body-file <file>`. Tell the user what changed from the old
  body, e.g. "added #5876 and #5877, which the old body missed".

## Step 5: Post the Slack trigger

Read `<channels>` and find the repo's channel under `channels["<owner>/<repo>"]`. Start
with the `trigger` template, so the bot sees its normal command, then add the release
announcement. The bot ignores edited messages, so always post a new message:

```
<trigger template with {bot_uid} and {pr_url} filled in>

**This is a release PR: `<head>` → `<base>`.**

Release summary:
• **<Theme>** (<issue range>): <one line>
• **<Theme>** (<issue range>): <one line>

<If the ahead-count note applied in the body:> Note: the real change is <N> files; most of the
<ahead> commits shown are squash history already on <base>. Merge with a merge commit, not squash.
```

Keep it to one message, and leave out the deploy checklist. The thread is for review, and
the PR holds the details. Post it with the Slack MCP `slack_send_message`. If that fails,
fall back to the `slack-cli` skill. Keep the returned permalink: that's the thread URL.

No channel for the repo, or `<channels>` missing → stop after Step 4. Give the user the PR
URL and say the grind needs a channel mapping.

## Step 6: Hand off to the grind

Invoke `ai-workflow:pr-grind` (see "Repo skills win") with the thread URL from Step 5. From here it owns the
loop, the state file and the terminal message. Don't create its state file or arm its
monitor yourself.

End by telling the user:
- the PR URL, and whether it was created or updated
- the thread URL
- any blocker that's still open
- that the merge stays theirs, as a merge commit

## Dry run

With `--dry-run`, run Steps 1 to 3 normally (they only read), then write:

- `<data_dir>/release-pr/<owner>-<repo>-<YYYY-MM-DD>/pr-body.md`
- `…/pr-title.txt`
- `…/slack-message.md` (with the PR link shown as `<PR URL>` if no PR exists yet)
- `…/release-data.md` (the script's raw output, so the summary can be checked against it)

Print the title, the body and the Slack message, and say which action Steps 4 to 6
*would* take (create vs update #n, which channel). Then stop: no `gh pr create`/`edit`, no
Slack post, no grind.

## Self-improve

After the task, follow `../../self-improve.md` (relative to this skill's directory).
