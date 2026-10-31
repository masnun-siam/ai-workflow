# ai-workflow

A Claude Code plugin that carries the team's dev process (PRD → tasks → refined issues → implement → review) plus the tools around it (dump, worklog, release PR, grind, peer review) and a web UI that runs them.

## Language

**PRD**:
The product requirements for one feature (the what and why, with a technical design of contracts but never code), written by `/create-prd` after an interview. The canonical copy is the repo's `docs/prds/<slug>.md`. Its status is Draft, In review or Approved; only an Approved PRD can be split into tasks. An author can set `Done` by hand in the header for a feature built without an epic; the UI then shows it as Shipped. `/create-prd --update` records later decisions.
_Avoid_: Spec, design doc

**Epic**:
A parent issue whose sub-issues are the tasks of one `## Epics` entry of a PRD, filed when the PRD is approved and labelled `epic` + `prd-<slug>`.
_Avoid_: Parent ticket, umbrella issue

**Task list**:
The saved, ordered decomposition of one PRD into small one-PR tasks, at `docs/tasks/<slug>.md`: outcome, Area, files, acceptance criteria, verify command, `Depends on:` and Parallel per task, plus Waves. Written by `/create-tasks`; tasks are never renumbered, only marked Changed or Dropped.
_Avoid_: Plan, backlog

**Refined issue**:
A task filed as a child issue of its epic, with a WHAT, WHY and HOW written from the PRD and the code, native blocked-by links, and the `refined` label. `/refine-issues` writes it. Only a refined issue is ready to implement.
_Avoid_: Groomed, ready

**implement-issue**:
The skill that takes one refined issue to a Ready PR in a single session: stop if blocked, work in its own worktree, run every check locally, verify in the running app, open a draft PR, and mark it ready only when CI is green and every review comment is handled.

**verifier-locally**:
The skill that proves a change works before it is pushed: it finds the repo's checks from CI, hooks and build files, runs the ones matching the changed paths, and reports each result with evidence. `implement-issue` and grind both call it.

**pr-review**:
The skill that reviews a PR or local branch against its issue, the repo's rules and `guides/code-review.md`, and reports evidence-backed findings with a verdict.

**Grind**:
`/pr-grind`: the loop on a ready PR that posts the Slack reviewer-bot trigger, waits for a round, fixes the findings inline in its own session, runs `/verifier-locally`, pushes, re-triggers, and repeats until approved or a rail stops it. Each round re-enters as a fresh headless session that reads the PR's grind state file.
_Avoid_: Review loop

**Lens**:
One review angle (critical, CEO, CTO, security, QA, UX, performance). The `peer-reviewer` agent is a lens: read-only, on Opus, one lens per instance.

**Peer review panel**:
The lenses picked for one artifact (a draft PRD, or a change: Ask, Answer and Diff), run by `/peer-review` until every picked lens approves or the round cap is reached. The UI starts one lens session per lens, relays verdicts to the root session and caps the loop at 5 rounds; the user decides after that.
_Avoid_: Review (on its own, that means a PR review)

**Dump**:
A capture filed into the Obsidian vault by `/dump` (new feature, change request, bug, task or meeting notes). A feature, change request or bug is written as a Problem statement; for a new feature it also seeds a `PRD.md` with `status: seed` next to `Dump.md`.
_Avoid_: Note

**Problem statement**:
What `/dump` writes for a feature, change request or bug: Problem, Who, Evidence, Expected and Open questions, taken only from the input, followed by the raw input verbatim. `/create-prd` builds a PRD from it.

**Share**:
A public, token-link view of one PRD in Draft or In review with its comment threads, served by a separate read-only listener behind a tailscale funnel. It ends when the PRD leaves those statuses, on Stop, or when the file is gone.
_Avoid_: Review link, public PRD

**Reviewer**:
Anyone holding a Share link: a typed display name, no account and no verified identity. Their Approve is a signal, never the PRD's Approved status.
_Avoid_: Guest, user

**Thread**:
One anchored quote in a shared PRD with its comments, from reviewers and the author. Open threads go to a session only through the author's Send.
_Avoid_: Discussion

**Session**:
A headless Claude invocation started and tracked by the UI (`aiw ui`), recorded under `<data_dir>/sessions/<id>/`. It exits after each turn and comes back via `--resume` with an answer or after a rate limit.
_Avoid_: Run, job

**Held session**:
A Session the user paused with "After this run" (`hold` on its record): the current run finishes, and nothing continues the session on its own until the user resumes it. It can still be answered by hand. Not a held lane, which is a dispatch lane stopped for red CI or a grind.

**Bootstrap run**:
One "Bootstrap repo" started from the UI: a record under `<data_dir>/bootstraps/` that chains one headless Session per phase (audit, decide, constitution, guides, gates, docs) and stops at the first phase that does not report `BOOTSTRAP: <phase> done #<issue>`. A repo has at most one that is running, waiting or stopped. It is not a Session.
_Avoid_: Bootstrap session

**Inbox**:
The UI's list of everything that needs the user across repos (questions, PRs ready to merge, paused grinds, failed sessions, reviews at their cap), built on the server by `GET /api/inbox`. Items clear themselves when their condition does.
_Avoid_: Notifications, queue

**Away mode**:
A timed run by the UI server that answers every `aiw ask` question (recommended options at once, an Opus answerer for the rest, risky or unanswerable rounds held), skips CI on paused grinds and retries failed sessions while the user is away. Formerly "AFK".
_Avoid_: AFK, autopilot

**Answerer**:
A read-only Opus session (`agents/away-answerer.md`) that Away mode starts for one question round without a recommended option. It picks labels with a reason, or holds the round; it never appears in session lists.
_Avoid_: Bot, auto-answerer

**Project**:
The human-friendly name for a GitHub `owner/repo`, looked up from `skills/worklog/projects.json`. Falls back to the raw `owner/repo` slug when unmapped.
_Avoid_: Repo (when referring to the display name; "repo" is fine for the raw slug)

**Dispatch**:
One run of an epic's child issues, or of a list of picked issues (from the UI only), as parallel Lanes, in dependency order under a cap, recorded under `<data_dir>/dispatches/` and ticked by the `aiw ui` server. Started by the `herdr-dispatch` skill (lanes are herdr tabs) or from the UI (lanes are headless Sessions); both see and steer every dispatch. Replaces Auto-build and epic autopilot.
_Avoid_: Batch run, fan-out, autopilot, auto-build

**Small change**:
A bug or change that needs no PRD: filed and refined by one `/create-tasks` then `/refine-issues` session started from the Features page's Small changes tab, and built with a Dispatch of picked issues.
_Avoid_: Ticket, quick fix

**Lane**:
One issue of a Dispatch, walked by the engine: implement (`/implement-issue`), grind (`/pr-grind`, off/simple/full), the merge gate (CI green, an approving review, the grind done), merge (automatic only with auto-merge on), followups (implement-issue's after-merge steps), closed; then the next unblocked lane starts. A lane that needs the user is held, and its dependents wait.
_Avoid_: Job, tab (a herdr tab is only where a lane may run)
