---
name: peer-review
description: "Run a panel of single-lens reviewers (critical, CEO, CTO, security, QA, UX, performance) on one artifact until every lens approves, on Opus. Normally the workflow UI runs the panel and this skill is the root's side: revise the artifact in place after each relayed round, stop at round 5. Also runnable by hand: /peer-review reviews the session's change, or the artifact you name, with one subagent per lens. Use whenever the user says /peer-review, 'peer review this', 'get the panel to review it', or asks for critical/CEO/CTO/security/QA/UX/performance reviewers on the work just done."
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Grep
  - Glob
  - Agent
  - AskUserQuestion
---

# /peer-review: a reviewer panel on one artifact

A panel of single-lens reviewers checks one artifact (a PRD, a task list, or a change) in
rounds. **Every lens blocks:** the artifact is done when all lenses approve on the same round.
You are the artifact's author (the root). The lenses are read-only: they report only through
their final message, which ends with exactly one line, `Verdict: approve` or `Verdict: changes`,
with findings above it. You never write a verdict for a lens and never approve on a lens's behalf.

Paths below starting `../../` are relative to this skill's folder, at the plugin root. Read first: `../../guides/engineering-workflow.md` ("Repository settings": the base branch and which guides, templates and skills win).

## Arguments

`/peer-review [--lenses <lens,lens>] [<artifact>]`, or from the UI: `/ai-workflow:peer-review --root <panel_id> <artifact>`.

- `--root <panel_id> <artifact>`: the workflow UI runs the panel and you are its root (below).
- Otherwise you run the panel by hand (below). Text that is not a flag or an existing file is a
  task: do that work first, then review it.

## As the root of a UI-run panel

The UI starts one headless, read-only lens session per lens, each on Opus as
`ai-workflow:peer-reviewer`. It copies each lens's final message into the panel folder, counts
the rounds, and relays to you. Lenses never message each other or you; the UI is the only relay.

- **Started with `--root <panel_id> <artifact>`** (no authoring session existed): read the
  artifact at that path; it is what the panel reviews. Then end your turn so the first round
  runs. Do not review it yourself.
- **Resumed with a round** (all lens verdicts of the round, each ending in its `Verdict:` line):
  1. Read every lens's findings. Fix each blocker and major finding by editing the artifact
     **in place**. For a doc, change the wording and never add implementation. For a change,
     change the code, then update the artifact's Answer and Diff to match.
  2. Answer each finding in a short list in your reply: `fixed`, or `dismissed` with a one-line
     reason. A finding only the user can settle (evidence, priority, a product choice) is not
     yours to decide: leave the artifact as is and list it for the user.
  3. Address minor findings when cheap; the same list answers them.
  4. End your turn. The UI then asks the same lenses to re-review the revised artifact. You do
     not ask them, and you do not start another round yourself.
- **Every lens says `Verdict: approve`:** say the panel approved, list any minor findings and what you
  did with them, and end. If you changed the artifact after that, say the change was not reviewed.
- **Cap reached** (the UI says the cap of 5 rounds was reached): stop. Do not revise further and
  do not loop. List the open findings, per lens with its latest verdict, for the human. Say
  plainly that the panel did not approve. Never approve anything yourself.

## Running it by hand (outside the UI)

1. **Artifact.** Use the file named in the arguments. With none, build `peer-review-artifact.md`
   in the scratchpad or a temp dir: `## Ask` (the user's request, verbatim), `## Answer`
   (your final answer and anything you did not do), `## Diff` (`git diff` of the change; confirm
   the start point with the user, never guess it, and leave out secret files and lockfiles).
   When the argument is a task that ends in a change, first write the plan as a doc artifact and
   run the panel on it before implementing; then run the panel on the change. When the Answer
   cites a test run, run the suite with `CLAUDE_PLUGIN_DATA=$(mktemp -d)` so the user's data dir
   cannot fail it.
2. **Lenses.** `--lenses` if given, otherwise `critical`. The pool is critical, ceo, cto,
   security, qa, ux, performance. For a doc a PRD offers all seven; pick the ones that fit. The
   lens descriptions are `peer_review.lenses` in `run-engine/config.json`; paste each lens's
   `prompt` into its subagent's prompt.
3. **Round.** In one message, spawn one `ai-workflow:peer-reviewer` subagent per lens, in
   parallel, each with `model: "opus"`. Each prompt names: the artifact path, the lens and its
   description, the round number, and from round 2 on that the artifact was revised. Tell it to
   end with `Verdict: approve` or `Verdict: changes`. From round 2, resume each lens's subagent
   (SendMessage) with the revision note instead of spawning a new one, so it re-checks its own
   findings.
4. **Read.** Take each subagent's final message; its last line is the verdict. A message with no
   `Verdict:` line is not a verdict: re-spawn that lens once, and if it is still missing, stop and
   say which lens.
5. **Revise.** If any lens says `changes`, revise the artifact in place as in the root procedure
   above, answer every finding, and go to 3 with the next round number. Before revising, ask the
   user every finding only they can settle in one AskUserQuestion, then revise with the answers.
6. **Stop** when every lens approves in the same round, or after round 5. At the cap, list the
   open findings for the user and do not approve anything. A finding only the user can settle
   goes to the user, never into the artifact as a guess.

**Finish** with one line, `peer review: <approved | stopped> after <n> round(s)`, then each lens's
last verdict, each minor finding and its disposition, and any open findings.

## Self-improve

After the task, follow `../../self-improve.md` (relative to this skill's directory).
