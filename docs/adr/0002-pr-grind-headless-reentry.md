Decision: Option A. A per-PR timer inside `aiw ui` re-enters pr-grind by starting a headless `claude -p "/pr-grind <thread url>"` round when something changed or a heartbeat elapsed, and the existing pr-grind state file carries all state between rounds. Option B, an external scheduler (launchd on macOS, cron or a systemd timer on Linux), is rejected: it needs two platform-specific install and uninstall paths, leaves units behind when the workflow is removed, would keep firing while the UI is down (a real advantage, see the Assumption below), and would have to re-implement the FR-15 duplicate-run check outside the UI.

## Context

The workflow-control UI (PRD `workflow-control-ui`, FR-15, FR-16) runs commands as headless `claude -p` sessions (ADR 0001). `skills/pr-grind/SKILL.md` is a long-running loop that depends on two session-local mechanisms:

- `ScheduleWakeup`: a 1500 second heartbeat armed every round, and the "On wake" re-entry (step 7 and the On-wake section).
- `Monitor`: a background `poll-reviews.sh` that streams new reviewer activity into the session (step 7).

Both live inside one session. A `claude -p` process ends when its turn ends, so nothing is alive to receive a wake or to hold a monitor. The PRD open question: how does pr-grind get re-entered when headless?

Facts the design must respect:

- The skill's argument is the Slack thread URL, not a PR number. The headless invocation is `/pr-grind <thread url>`.
- State already lives in a file, `<pr_grind_dir>/<owner>-<repo>-<pr>.md`, with header keys `paused:`, `queued-push:` and `ci-attempt:`. Step 0 reads it (at item 5, after the earlier checks), so a fresh process can pick up where a previous one stopped.
- The skill says a human re-invoking `/pr-grind` clears `paused:`, while an automated wake never clears it. A headless re-entry looks like a re-invocation unless it is marked.
- FR-16 (`docs/prd/workflow-control-ui.md`, line 65): "Server-independent sessions — sessions are detached and write their stream/state to the data dir. A UI restart picks them up again." Acceptance: "killing and restarting `aiw ui` mid-run loses no session, and live output resumes."

## Evidence

Run on macOS (Darwin) with Claude Code 2.1.289, in a throwaway directory, no real `/pr-grind` run (it would post to Slack and push).

**(a) Tool list under `-p`.** `claude -p --model haiku --output-format stream-json --verbose "reply ok"`: exit 0, `"terminal_reason":"completed"`. The `system`/`init` event listed 203 tools and, contrary to what the plan expected, this includes `ScheduleWakeup` and `Monitor` (and `CronCreate`). `AskUserQuestion` is absent, consistent with ADR 0001. The list comes from the local user configuration, so it may differ elsewhere. An attempt to call `ScheduleWakeup` once under `-p` was blocked by the permission classifier and not retried, so whether it actually schedules anything headlessly is not tested. The design does not depend on that answer: the `-p` process exits at the end of its turn, so a wake it scheduled would have no live session to land in unless the process stays up for the whole wait, which is the cost-and-lifetime problem the timer avoids. That reasoning is not an observed result.

**(b) Per-PR lock.** A stdlib Python harness (not committed): 8 processes released together by a `multiprocessing.Barrier`, each doing `fcntl.flock(fd, LOCK_EX | LOCK_NB)` on the same file.

```
winners 1 skipped 7
held: second acquire refused
after SIGKILL of holder: acquired
```

Exactly one winner, the other seven skip, and the kernel frees the lock the moment the holder is SIGKILLed, with no stale-lock cleanup. Only macOS was run. `flock` semantics are the same on Linux; that is not tested here.

## Consequences

- Chosen: Option A. Rejected: Option B, for the reasons in the Decision line. A second reason: B's tick would have to know the UI's session data dir and run the same checks the UI already runs. The UI is the one place that already owns sessions, the FR-15 guard and the per-PR display.
- Timer shape: a per-PR tick inside `aiw ui`. The tick is cheap stdlib Python with no model call: `gh api` for new reviews and CI state, plus `gh pr view --json state`. It starts a detached `claude -p "/pr-grind <thread url>"` only when a new review or comment landed, CI changed, or the 1500 second heartbeat elapsed.
- FR-16 UI restart: the timer holds no state of its own. On startup `aiw ui` rebuilds its timers from active sessions and the pr-grind state file headers, then runs one catch-up tick for any interval missed while it was down. Rounds already running are detached, so a UI restart does not lose them.
- State file reuse: no new store. `<pr_grind_dir>/<owner>-<repo>-<pr>.md` stays the source of truth.
  - `paused:` set: stop the timer, UI shows "waiting on you".
  - `queued-push:` set: keep ticking, UI shows waiting on CI.
  - `ci-attempt:` is read and written by the rounds as today.
  - Step 2 close: stop the timer. Open question for task 25: does a close need a terminal `done:` header key so a restarted UI does not rebuild a timer for a finished PR? No such key exists today.
- PR merged or closed between wakes: the tick checks `gh pr view --json state` before anything else and stops the timer on merged or closed. Step 0.3 (the OPEN check) stays as the backstop if a round starts anyway.
- Two re-entries racing for one PR, or a wake while the previous round is still running: one per-PR lockfile in the data dir, taken with `flock(LOCK_EX | LOCK_NB)` as in (b). The tick opens the lockfile, takes the lock, and spawns the detached `claude -p` with `pass_fds=[fd]` (the default `Popen` `close_fds=True` would not pass it on), then closes the parent's copy. The lock then lives exactly as long as the round and the kernel frees it on exit or crash. The harness in (b) did not test this parent-to-child handoff; task 25 must verify it. This avoids the stale-lock reclaim branches that PR 17 and `tasks/lessons.md` warn about. If the lock is held, the tick skips and does not queue: the next tick re-checks the same inputs, so nothing is lost. The FR-15 refusal (409) is a second layer. An interactive pr-grind is blocked only where it is detectable, since a human session holds no lock.
- Automated-re-entry marker: the tick starts the round with `AIW_HEADLESS=1` in the environment (for `aiw` and the engine) and `--append-system-prompt` telling the model this is an automated re-entry (the model-facing switch), the same pair as ADR 0001. The model then takes the On-wake branch and never clears `paused:`. Only tick starts carry the marker. Resume from the UI or terminal is a human re-invocation without the marker, so it clears `paused:` and the timer restarts; a paused PR resumes only that way, never from a tick. Without the marker a headless tick is indistinguishable from a human re-invoking.
- UI between rounds: "waiting for reviewer" with the next tick time while the timer runs and nothing is set; waiting on CI while `queued-push:` is set; "waiting on you" while `paused:` is set.
- Assumption, stated and accepted: the timer only advances while `aiw ui` runs. When the UI is not running no ticks fire and PR review activity waits until the UI is back, when the catch-up tick runs. Cost: a late response to a reviewer while the UI is down, never a lost one, since state is on disk. Acceptable because pr-grind is a supervised workflow; Option B would close this gap, which is its one advantage, at the price above.
- Platforms: macOS and Linux only. `fcntl.flock` is POSIX and Windows is out of scope.
- Interactive pr-grind is unchanged: `ScheduleWakeup`, `Monitor` and the human re-invocation branch keep working exactly as today. The headless path is additive.
- Task 25 (pr-grind headless re-entry) builds this ADR:
  - the tick and per-PR lock in `run-engine/ui_runner.py`;
  - a one-shot mode for `poll-reviews.sh`, which today loops forever and cannot serve a tick;
  - headless rounds stop after Step 7.1: Steps 7.2-7.4 (arming `Monitor` and the 1500 second `ScheduleWakeup`) are skipped, because (a) shows both tools are offered under `-p` and arming them would keep the process, and so the lock, alive;
  - the On-wake marker prose in `skills/pr-grind/SKILL.md`;
  - the open `done:` header question above.
- Not built here: this ADR is the spike result only. `skills/pr-grind/SKILL.md` and `run-engine/` are untouched.
