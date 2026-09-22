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
