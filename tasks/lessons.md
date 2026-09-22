# Lessons

## Prompt & Skill Authoring
- **Pattern**: Issue #12 diagnosed one unbounded "terminal instruction" (a line telling a
  skill to return and stop, which then halts the whole `/run-issue` turn) and its Proposed
  Fix section patched exactly that one line. Three lines of the identical shape existed
  across the two skills; the literal diff would have fixed one and left the epic path — an
  explicitly-listed acceptance criterion — still halting.
  **Rule**: When a fix scopes or bounds a *pattern* (a HARD RULE block, a terminal
  "return and stop" line, any turn-halting instruction), grep the whole file set for every
  occurrence of that shape and fix all of them. A bug report names one symptom site; the
  root-cause fix is every site sharing the shape. The same rule applies to the scope you
  write into the bound: #12 said "steps 1–7", but `commands/gh-issue.md`'s step 0 (Source
  check) sits outside that numbered list and is the step intake input actually drives —
  bound to the real span, not the one the report quoted.
  **Evidence**: three matching terminal lines in the pre-fix tree —
  `commands/gh-issue.md:144` ("Return the issue URL when done.", the one #12 named),
  `commands/gh-issue.md:111` (the `4-EPIC` step 7 "Return the parent URL, the child URLs
  in dependency order, and the board name.", missed by the proposed diff), and
  `commands/intake.md:122` ("Return the result as the final message ... no other text
  after it", upstream of the reported failure). Review:
  https://github.com/masnun-siam/ai-workflow/pull/13#pullrequestreview-5273570158
  **Date**: 2026-09-22

## Run Engine — Fixer Handoff
- **Pattern**: A fixer pass declined an optional nit, replied on the thread explaining why,
  and moved on without resolving it. The engine's post-check refused the envelope (exit 7,
  "review thread(s) still open and not handed onward") and cost a full extra bounce round
  for zero code change.
  **Rule**: Every review thread must end a fixer pass either resolved
  (`aiw threads resolve <node_id>`) or declared in the handoff under
  `needs_confirmation` / `needs_test_root_fix` / `needs_new_file`. A reply alone is not a
  disposition. Declining a nit is a *resolve*, not a leave-open — only human-confirmation,
  test-root, and new-file findings are legitimately left open, and those must appear in the
  handoff.
  **Evidence**: `run-engine/checks.py:309-323` requires every open thread to appear in the
  handoff's declared set; `agents/run-fixer.md:45-47` tells the fixer to "note it, don't
  force a change" for a nit without saying to resolve the thread — that is the gap the
  bounce fell into. PR: https://github.com/masnun-siam/ai-workflow/pull/13
  **Date**: 2026-09-22

## Review — Acceptance Criteria
- **Pattern**: Issue #12 listed as an explicit AC that a `/gh-issue` failure or human
  cancellation mid-flow must make `/run-issue` stop with a clear message rather than
  resume against a nonexistent issue number. The implementation wrote the happy path only
  ("parse `<n>` from the returned URL, continue to step 3") with no stop clause, and the
  run's own in-context self-review passed it. An external reviewer re-reading the diff
  cold against the issue's AC list caught it one round later.
  **Rule**: Before declaring a review pass done, walk the issue's AC list one item at a
  time and point each one at the literal added/changed text that implements it, quoted
  from the file as it stands now — not from the plan or the commit message. "The general
  approach covers it" is not a trace. An AC that describes a failure/abort path is the
  usual miss, because the happy path reads as complete on its own.
  **Evidence**: review comment 4067994880 on
  https://github.com/masnun-siam/ai-workflow/pull/13 (round 1, review 5273636176 against
  commit 9a29ee2 — the state the PR was in *after* the pipeline's own review+fix cycle);
  fixed by the added clause at `commands/run-issue.md:222` in commit 948327f, which
  round 2 (review 5273653952) returned clean on.
  **Date**: 2026-09-22

## Concurrency & Mutual Exclusion
- **Pattern**: PR #17 added a cross-process file lock to `run-engine/stack.py` and three
  consecutive review rounds each found a *different* function in that same file with the
  same shape of race, because each round fixed one function and declared victory once
  that function's own new test passed. Round 1: `acquire_lock`'s cold-path create relied on
  a process-local `threading.Lock` — zero cross-process exclusion — and its test used 8
  threads in one interpreter, so it passed while the lock provided no exclusion at all
  (reviewer: 4–9 winners of 12 processes, 10/10 trials). Round 2: the O_EXCL fix was real
  for the cold path, but the stale-lock *reclaim* branch was still an unguarded
  read-check-write, and round 1's new test only ever raced for an *absent* lockfile so it
  never entered that branch (5–10 winners of 12, 10/10 trials, two staleness triggers).
  Round 3: `release_lock` is still a non-atomic `_read_holder` then `os.remove` with
  nothing between the two syscalls, so a contender can break the lock as stale, a third
  process can create a fresh lock in the gap, and the original release deletes the new
  holder's lock (1/40 trials — rare, but the *expected* interleaving here, since
  `lock_stale` goes true the moment a holder's ledger hits `done`/`escalated` and
  `aiw stack down` runs at that same transition). This round is unfixed; it spent the
  bounce budget and left the PR a draft.
  **Rule**: When a change introduces a mutual-exclusion mechanism (lock, semaphore, any
  "exactly one of N wins"), treat *every* function that touches that shared state —
  acquire, break/reclaim, AND release — as one unit of review, and fix and test them
  together. Fixing one and stopping when its test goes green systematically misses the
  siblings. And a **thread-based test for a cross-process primitive is worthless: it passes
  whether or not the primitive works.** The only check that caught anything here, all three
  times, was a real multi-process harness with a shared start barrier, many trials,
  counting how many processes believe they hold the lock — plus a control run against the
  pre-fix commit to prove the harness isn't vacuous. Write that harness once, then point it
  at every branch (no lockfile / stale lockfile / live lockfile / release racing a break),
  not just the branch you happened to change.
  **Evidence**: three rounds on https://github.com/masnun-siam/ai-workflow/pull/17 —
  reviews 5273915526 (round 1, fixed in 20dcdf6→77edbfd), 5273965331 (round 2, fixed in
  4cc5ad3 via an O_EXCL-created `stack.lock.break` sentinel gating the reclaim), 5274069166
  (round 3, `release_lock`, unfixed). The lock lives only on the PR branch, not yet on
  master; on that branch `run-engine/stack.py:197-204` is the still-unguarded
  read-check-then-remove, and `run-engine/test_scripts.py:679-680` records the
  thread-vs-process point in the test file's own comment.
  **Date**: 2026-09-22

## Run Mode Selection
- **Pattern**: Issue #14 was run in `--lean` (no sdet, no verifier, no specialist panel),
  and the lone reviewer had to find three separate concurrency bugs in the same file over
  three rounds. The failure mechanism is the exact one `--lean`'s own documented tradeoff
  names first: tests written by the implementer to fit the implementation still pass. Both
  the round-1 and round-2 fixes shipped with a new test that covered the branch just fixed
  and no other.
  **Rule**: A diff that introduces or alters a concurrency primitive (lock, semaphore,
  queue, anything with a "exactly one winner" or shared-mutable-file invariant) belongs in
  full mode, alongside the risk categories already listed. Its correctness is only
  observable through an adversarial test an independent station writes — which is precisely
  the guarantee lean drops.
  **Evidence**: `run-engine/config.json:54` — lean's `tradeoff` states "(1) tests are no
  longer authored RED-first by an independent station, so a test written to fit the
  implementation still passes" and lists the full-mode categories as "auth, migrations,
  payment, or public API contracts", with no shared-state/concurrency category. Run
  history: https://github.com/masnun-siam/ai-workflow/pull/17 (3 reviewer rounds, bounce
  budget of 2 exhausted, degraded finish).
  **Date**: 2026-09-22
