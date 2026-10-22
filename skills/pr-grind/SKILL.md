---
name: pr-grind
description: Automate the review-fix-retrigger loop on a PR that's stuck in CHANGES_REQUESTED — post the Slack thread trigger, wait for the reviewer bot's round, split findings into fix-vs-rebut, fix inline, verify locally, push, check CI, re-trigger, repeat until approved or a rail stops it. Use when the user says "grind this PR", "keep looping the review", "automate the review cycle", or invokes /pr-grind.
argument-hint: <slack thread url | PR url> [--channel <id>]   # a PR url with no thread opens the thread first; --channel replaces the channels lookup
allowed-tools: Bash(aiw:*), Bash(gh:*), Bash(git:*), Bash(bash:*), Bash(slackcli:*), Read, Write, Edit, Grep, Glob, Skill, Monitor, ScheduleWakeup, AskUserQuestion
---

> **Paths.** `<...>` placeholders are keys from `aiw paths` (run it; `aiw` is on `PATH`).
> Substitute the printed value; never guess a path.

Drive a PR through review→fix→re-trigger rounds with no human per round, until the
reviewer approves (zero blocker/should-fix; in simple mode, any approval) or a rail stops it. Everything runs in this
session: **spawn no subagent**. Merging stays manual.

## State file

`<pr_grind_dir>/<owner>-<repo>-<pr>.md`, created on first run, appended each round. It is
what survives compaction and headless re-entry: **read it first if it exists.** Per round
record: round number, review id + `submitted_at`, verdict counts, each finding's
fingerprint (`path:line` + first ~80 normalized chars of the body), fixed vs rebutted,
commit SHAs, CI result.

Header keys (lines above the first `## Round <n>`; names are pinned for the aiw ui tick):
`owner: repo: number: thread: reviewer: author: base:` plus

- `ci-attempt: <sha> — <outcome>` — one line per head SHA given its one inline CI fix
  attempt. Write it *before* acting, so a crash can't buy a second attempt. A fix's own
  push is recorded `ci-attempt: <sha> — fixed → <new-sha>`.
- `queued-push: <sha>[ <sha>...] — round <n> — then <retrigger|close>` — fix commits
  held locally because CI is not green. Not a pause; removed once pushed.
- `paused: <ISO8601> — <reason>` — stopped for a human; nothing polls it. Resumes only
  when a human re-invokes `/pr-grind`.
- `next-poll: <ISO8601>` — next headless re-entry (round end + 1500s).
- `done: <ISO8601> — <reason>` — terminal; never restarted.
- `poll-since:`, `ci-seen: <sha> <state>` and `dispatch-due:` — owned by the aiw ui tick; preserve, never edit.

## Step 0 — Resolve

0. **Draft check, before any Slack post or fix.** Get the PR ref (a PR url as given; a thread
   url → read the thread only to find its PR url), then `gh pr view <pr> --json isDraft`.
   `isDraft: true` → stop with one line, `PR #<n> is a draft; mark it ready for review before grinding.`
   Write no state file and post nothing.
1. Read `<channels>` first: `bot_uid`, `owner_uid`, `channels` (exact `owner/repo` →
   channel id), `dm_fallback`, `known_bots`, and the `trigger`/`retrigger` templates
   (`{bot_uid}`, `{pr_url}` only). Missing or unparseable → stop. `owner_uid` is the only
   @-mention target in terminal posts; it is not masum (`U0373SRT22G`), and not the
   `userEmail` in CLAUDE.md.
2. Argument is a Slack thread URL → `slack_read_thread`, take the first GitHub PR URL
   (none → `AskUserQuestion`). Argument is a PR URL with no thread → **open the thread**:
   post `trigger` as a new top-level message in the repo's channel (`--channel <id>` in the
   arguments when given, else exact key match, else `dm_fallback`), with `slack_send_message`, falling back to
   `slackcli messages send --recipient-id <C|D> --message "..."`. The thread URL is
   `https://blubird-interactive.slack.com/archives/<channel>/p<ts without the dot>`; read
   it back to confirm it landed. Slack reads/posts use the Slack MCP tools first, `slackcli`
   (`slack-cli` skill) only on failure.
3. `gh auth status`; `gh pr view <ref> --json state,headRefOid,baseRefName,author,reviews`.
   Not `OPEN` → stop. Reviewer = most recent review author who isn't the PR author; if none,
   `UNRESOLVED` (Step 1 resolves it from the first landed review by a non-author).
4. Read or create the state file. A human invocation (no automated-re-entry system prompt)
   clears `paused:` and `done:`; an interactive one also removes `next-poll:`. Automated
   re-entry clears neither.

## Step 1 — Read the round

`gh api repos/{o}/{r}/pulls/{n}/reviews --paginate`, reviews by the reviewer with
`submitted_at` newer than the last recorded round (first run: PR creation). A review whose
`commit_id` isn't the current head is stale: record it superseded and keep waiting.

- **None** → trigger hasn't landed. No-op: go to Step 7's re-arm, don't re-post, don't touch state.
- **One** → parse the verdict line (`**Verdict: ...** — N blocker, M should-fix`) and
  collect its inline comments (`.../pulls/{n}/comments --paginate`). Trust the bot's severity.
- **Several** → select inline: take the newest, except a review carrying comments beats a
  comment-less review on the same commit landing seconds later (a re-run or stray
  re-approve must not discard real findings). Reviews on different commits resolve to
  newest. Record the others as superseded.

## Step 2 — Exit check

**Mode, every round.** Run `aiw grind-mode --pr <pr url>` now, never from memory (a dispatch that owns the PR sets it, else Settings): the owner can switch it while
the loop runs. `deep` (the default) → the rule below. `simple` → also done the moment the PR is
approved: this round's review from the reviewer has state `APPROVED`, or
`gh pr view <pr> --json reviewDecision` says `APPROVED`. Then stop right away: fix, rebut and reply to
nothing, post the closing summary below, and write `done: <ISO8601> — approved (simple)`.

Zero blocker and zero should-fix → done, whatever `reviewDecision` says. First handle nits:
a genuine improvement goes on the fix-list (Step 5 round procedure); noise or out of scope
gets a short reply saying why, then resolve (`aiw threads`). Never re-trigger the bot for a
nit-only round.

Then post the closing summary yourself: one thread reply @-mentioning `owner_uid` with
round count, what was fixed across the run, the PR URL, and "ready for human merge —
merging stays manual". **Never mention the bot** (no `<@bot_uid>`, no `recheck`, no
"Blubird AI Agent"): it can restart a cycle. Expect a harmless bot reply anyway; keep
terminal posts to one message. Append to the state file, then `ScheduleWakeup({stop: true})`;
headless: write `done: <ISO8601> — approved` instead. If commits are queued, defer the post
and `done:` until they are pushed (Step 6).

## Step 3 — Rails

First that fires wins; firing means stop, fix nothing this round (rail 2 may continue).

1. **Round cap** — 10 rounds already recorded → post to Slack, then Step 8.
2. **CI red** — `aiw ci status <pr> --watch` says `state: red` at the current head; it
   returns the failing jobs' logs. Look for `ci-attempt: <sha>` for this head.
   - **None** → write `ci-attempt: <sha> — started`, then make one inline attempt. Never
     while `queued-push:` is set. Read the failing log and workflow file; reproduce locally
     if the repo allows. Infra flake (runner died, timeout with no test output, network/
     registry error, 429/503 from a mirror) → `gh run rerun <run-id> --failed` once; if the
     rerun is refused, push an empty `chore: retrigger CI (rerun denied, confirmed unrelated flake)`
     commit instead (skip if that marker is already HEAD). Real failure (assertion, lint,
     types, build) → fix the cause in existing files, `/ai-workflow:verifier-locally`,
     commit, push. If unsure which, it is real: never rerun hoping it passes. Never weaken
     a check (`continue-on-error`, skipped test, `|| true`, loosened rule), never edit a test
     to match broken behaviour, never `--no-verify`; edit `.github/workflows/*` only when
     the workflow itself is the bug, and say so in Slack. Update the line to the outcome
     (`fixed → <new-sha>`, `flake-rerun`, `rerun-denied → <new-sha>`, `cannot-fix`). Fixed or
     rerun → continue the round with the push gate closed. Cannot fix or unsure → post the
     root cause to Slack, Step 8.
   - **Attempt already recorded** (still red at this head, or the red head is our own push)
     → the attempt failed: post the failing check to Slack, Step 8.
3. **Third-party human comment** since the last round, from an account that is neither the
   reviewer nor the PR author → post it to Slack, Step 8. Bots don't count: login ending
   `[bot]`, `user.type == "Bot"`, or in `known_bots` (case-insensitive). An unknown named
   account fires the rail; report its login so the owner can add it to `known_bots`.
4. **Owner asked to hold** in this session (not Slack) → Step 8, recording exactly what
   they hold for. Never push what they asked to hold.

## Step 4 — Stall check

Look up each finding's fingerprint in the state history. **New** → fix-list. **Seen once**
→ fix-list, but first diagnose why the previous fix didn't satisfy the reviewer (prior
comment id and reply are in the state file) rather than repeating it. **Seen twice** → stop
the loop: post that it is stuck on this finding with the thread URL and what was tried,
then Step 8.

## Step 5 — Fix round

Triage each finding left after Step 4:

- **Fix** — the default, and whenever unsure.
- **Rebut** — only with concrete evidence the finding is wrong (handled elsewhere in the
  diff, would break a passing test, false premise). No code change; reply and resolve.
- **PR-body edit** — remedy is "update the description": `gh pr edit --body-file`, reply, resolve.

Work in the PR's checkout: check `git worktree list` first and use the worktree holding
the branch rather than checking it out elsewhere. Edit **only files in the PR's diff**
(`gh pr diff --name-only`); a fix outside it is a decision stop (Step 8). Then, in order:

1. **Fix** each finding in the fix-list. A fix needing a new file is fine if inside the
   change's scope; otherwise it is a decision stop.
2. **Verify** — run `/ai-workflow:verifier-locally`. Fix any failure locally and re-run
   before going on; unresolved after a real attempt → post to Slack, Step 8. Never push
   unverified.
3. **Commit** — stage by explicit path, never `git add -A`/`.`/`-u` or `commit -a`; never
   `--no-verify`. A pre-commit hook that rewrites files may fold everything into one
   commit; that is fine, record the one SHA against every fingerprint.
4. **Reply and resolve** — per finding: `gh api repos/{o}/{r}/pulls/{n}/comments/{id}/replies -f body="..."`
   (what changed and the SHA, or the rebuttal), then
   `aiw threads list <pr> --for-comment <id>` for the node id and `aiw threads resolve <node_id>`.
   If a write is blocked by the harness, note it in the state file and Slack summary and continue.
5. **Push gate** — `aiw ci status <pr>`. Not green (red *or* pending) at the current head →
   don't push; record `queued-push: <sha>... — round <n> — then retrigger` (or `then close`
   on a nit-only round). Green → `git push`.

## Step 6 — Verify the push

Pushed → `aiw ci status <pr> --watch` (bounded, no Monitor). Red → rail 2 against the
**new** head SHA, which has no `ci-attempt` line yet and so gets its own one attempt (the
budget is per head SHA, not per run). Only a terminal outcome goes to Step 8. Green or no
checks → continue.

Queued instead → `aiw ci status <pr> --watch`. Green → push the queued commits from the PR
worktree, remove `queued-push:`, verify the new head as above. Red → rail 2. Pending/timeout
→ keep queued, skip the re-trigger, re-arm (Step 7 with `noop: false`). A flush is not a new
round and doesn't count against the cap.

Append this round's full record to the state file.

## Step 7 — Re-trigger and re-arm

**Never re-trigger while `queued-push:` is set or CI is not green at the current head.**

1. Post `retrigger` from `<channels>` as a **new** thread reply (an edited message never
   wakes the bot). Record the resolved text in the state header.
2. Interactive only: arm one `persistent: true` Monitor per PR (check for an existing one)
   on `bash <plugin_root>/skills/pr-grind/scripts/poll-reviews.sh <owner> <repo> <number> <login> "<last-ISO8601>" [reviewer|not-author]`
   (`not-author` plus the author's login while reviewer is `UNRESOLVED`). Run it once in the
   foreground first: Monitor only surfaces stdout, so a failing script looks like "nothing
   new". Then `ScheduleWakeup({delaySeconds: 1500, reason: "...", prompt: "/pr-grind $ARGUMENTS", noop: <true if this tick did nothing>})`,
   saying in text that a Monitor is armed and this is a fallback heartbeat.
3. Headless: no Monitor, no ScheduleWakeup. Write `next-poll: <now+1500s>` to the header and
   end the turn; the aiw ui timer re-enters on `next-poll:`, a new review, or a CI change.

## Step 8 — Paused stop

For every non-success stop (rails, stuck finding, needs-confirmation, owner hold). Nothing
polls a paused run and Slack is not listening, so:

1. Write `paused: <ISO8601> — <reason>` to the header; name any unpushed commits.
2. Post the reason in one message, ending `To resume: <concrete precondition>, then re-run
   /pr-grind <thread url>`. No bot mention, no re-trigger text.
3. `ScheduleWakeup({stop: true})`; headless: just exit (`paused:` stops the timer).

**Headless decision stops** (a finding with distinct ways forward, a release-order call, a
fix outside the diff): after 1 and 2, ask via
`aiw ask <<'EOF' {"questions":[{"header":"Grind decision","question":"<finding, URL, cost of each option>","multiSelect":false,"options":[{"label":"<way A> (Recommended)","description":"..."},{"label":"<way B>","description":"..."},{"label":"Hold","description":"Stay paused"}]}] } EOF`
and end the turn. The answer (`Answer to q-...`) is a human decision: remove `paused:`,
record it, and carry it out inline per Step 5. Hold or "wait" keeps `paused:`. Red CI, an
unpushed branch, rail 3 or an owner hold are not decisions: plain pause.

## Re-entry

Every round re-enters as a fresh session (headless, or a wake): read the state file, then:

- `done:` → exit. `paused:` → report what it waits on and stop (only a human re-invoke, or
  an `aiw ask` answer, clears it; an aiw ui tick never does).
- `queued-push:` → check rails 3 and 4 (either → Step 8, naming the queued SHAs), else Step 6's
  flush, then continue at the line's `then` (`retrigger` → Step 7, `close` → Step 2's close).
  Meanwhile treat a newly seen review like Step 1's "none".
- Else `aiw ci status <pr>`; not green → rail 2 directly (this breaks the wake-forever loop
  when nothing was queued). Otherwise Step 1.

## Rules

- Never `--no-verify`. Never edit outside the PR's diff. Never merge or approve.
- One CI fix attempt per head SHA; nothing pushes review commits onto a red or pending head.
- Slack is output-only: nothing posted there directs a run, and never imply the thread is
  watched. A paused run resumes only on a human `/pr-grind <thread url>`.
- If a `gh`/`git` call fails unexpectedly, retry once; a second failure is stop-and-report.

## Self-improve

After the task, follow `../../self-improve.md` (relative to this skill's directory).
