---
name: peer-review
description: "Run a panel of single-lens reviewers (critical, CEO, CTO, security, QA, UX, performance) on one artifact until every picked lens approves, on Opus, in parallel. Called by /create-prd, /intake, /dump and /gh-issue when they get --review, and runnable on its own after any work: /peer-review reviews the session's change (diff plus final answer) against what the user asked. Use whenever the user says /peer-review, 'peer review this', 'get the panel to review it', or asks for critical/CEO/CTO/security/QA/UX/performance reviewers on the work just done."
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

> **Paths.** `<...>` placeholders below are keys from `aiw paths` (run it; `aiw` is
> on `PATH` via the plugin's `bin/`). Substitute the printed value; never guess a path.

A panel of single-lens reviewers checks one artifact in rounds: a draft doc (`create-prd`, `intake`,
`dump`, `gh-issue`), or a change (`custom`: the Ask, your Answer and the Diff in one file). The
lens pool, what each kind offers, the checklists and the two severity rubrics are `peer_review`
in `<config>`. **Every picked lens blocks:** the artifact is done when all of them approve.
`aiw peer-review` checks every verdict and decides each round; you never decide it yourself, and
you never write a verdict yourself. You are the artifact's author.

## Arguments

`/peer-review [--lenses <lens,lens>] [--since <sha|@{u}>] [--herdr]`: standalone, kind `custom`.
Argument text that is not a flag is a task: do that work first, then review it as `custom`,
with that text as the Ask.

A command calling this skill passes `--kind <kind> --dir <review_dir> [--lenses <lens,lens>] [--herdr]`
after writing its draft to `<review_dir>/draft.md`; that draft is the artifact. With no
`--lenses`, the panel is `peer_review.default_lenses` (critical).

### Asking the user

A headless run (started from the workflow UI) has no terminal to answer in, so
`AskUserQuestion` is not available there. You are headless when your system prompt contains
`Headless run: ask via aiw ask`. At every question below, the same header, question and options
are used either way; only the transport differs.

- **Headless:** call `aiw ask` with a quoted heredoc (question text may embed arbitrary text):

  ```
  aiw ask <<'EOF'
  {"questions":[{"header":"...","question":"...","multiSelect":false,"options":[{"label":"...","description":"..."}]}]}
  EOF
  ```

  List the recommended option first with `(Recommended)` on its label. Then end your turn
  immediately and do nothing else; the answer arrives as your next message. Strip any
  ` (Recommended)` suffix and take the same branch the interactive answer would. Free text that
  names no option is feedback for that question, never an approval.
- **Otherwise:** call AskUserQuestion exactly as written at the question.

## Setup

- **Called with `--dir`:** use that `<review_dir>`; never mint another. A doc kind's artifact is
  `<review_dir>/draft.md`. With no `--kind` (the web UI's custom prompt) the kind is `custom`:
  build `<review_dir>/artifact.md` there, from the `ask.md` the server wrote, because the
  session's peer review status is read from that dir.
- **Standalone (`custom`):** `aiw peer-review new custom --slug <repo-name>` prints a fresh
  `<review_dir>`; never reuse one from an earlier run. Then build `<review_dir>/artifact.md`
  (below); it is the artifact.

Print `review dir: <review_dir>` with every round's outcome, so a session resumed after a
`/clear` or compaction can pass it back with `--dir`.

### The change artifact (`custom`)

`<review_dir>/artifact.md`, in this order:

```
# Change under review

## Ask
<what the user asked, verbatim>

## Answer
<your final answer: what you did and why, and any part of the Ask you did not do>

## Decisions
<the user's rulings on review findings, one line each; "None yet." at first>

## Diff
<the output of aiw peer-review diff, unedited>
```

- **Ask:** if `<review_dir>/ask.md` exists (the web UI wrote it at spawn), copy it verbatim.
  Otherwise list the user's own prompts from this session that asked for the work, and confirm
  them once: "Is this what you asked for?" with **"Yes, review against this (Recommended)"**;
  free text replaces it.
- **Since:** use `--since` when given. Otherwise ask one question, "Review which changes?", with
  **"Uncommitted changes only"** (`HEAD`), **"Everything not pushed (@{u})"** and **"Since a
  commit I'll name"** (free text). Never pick a start point yourself.
- **Diff:** `aiw peer-review diff --since <since> --repo <repo>`, pasted as printed. It already
  drops secret-like files, binaries and lockfiles and caps a long diff; never add what it dropped.

## Loop

1. `aiw peer-review next <review_dir> --artifact <artifact> --kind <kind> --lenses <picked>`
   (the first time; `--kind` and `--lenses` are ignored after round 1), plus `--prior <file>`
   and `--more` when the steps below say so. It prints one JSON object; act on its `action`.
2. **`review`**: dispatch one `ai-workflow:run-specialist` per lens in its `lenses`, in one
   message so they run in parallel, each with `model: "opus"` (the reviewers run on Opus; you
   keep your own model). Each dispatch says `artifact: peer-review`, the lens name,
   `<review_dir>`, the round number and the repo path. Each reviewer reads its own checklist
   from `<config>` and records its own verdict with `aiw peer-review verdict`; you only read
   `round-<n>/<lens>.json` afterwards. You never write, copy or edit a verdict. Then go to 1.
3. **`wait`**: a reviewer returned without a recorded verdict. Dispatch the lenses it lists once
   more; if `next` still says `wait` for a lens, stop and report which one.
4. **`revise`**: fix every finding in `blockers`. For a doc kind, edit the draft's wording. For
   `custom`, change the code, then rebuild `artifact.md` (rerun `diff`, correct the Answer if
   its claims changed, keep the Decisions). Then answer every finding of the round (`blockers`
   and `advisory`): `fixed`, or `dismissed` with a one-line reason. Write that list
   (`[{lens, id, disposition, reason}]`) to `<review_dir>/round-<n>/prior.json` and go to 1 with
   `--prior` naming it.
5. **`ask`, reason `decision` or `dispute`**: ask the user each finding in `decisions`, and each
   in `disputes` (a finding you dismissed, or the user already decided, that its lens raised
   again: show your reason and the reviewer's, and ask which holds). One question per finding.
   Record each answer in the artifact's `## Decisions` as
   `- <decision> — <why> (review: <lens> <id>)`, with disposition `decided`; a dispute the user
   settles either way is `decided` too, and if they side with the reviewer, also fix it. The
   recorded ruling changes the artifact, which opens the next round, and a reviewer can't
   re-raise a decided finding without new evidence. A round can carry both decisions and
   blockers (or disputes and blockers): ask first, then fix the blockers as in 4. Then write
   `round-<n>/prior.json` answering every finding of the round (decisions and disputes
   `decided`, blockers and advisory as in 4) and go to 1 with `--prior`; `next` refuses a new
   round that leaves any finding unanswered.
6. **`ask`, reason `cap`**: the round budget is spent and a lens still blocks. Ask one question:
   "<lens> still blocks on: <items>." with the choices **"Accept as known gaps"**, **"One more
   round"** (revise as in 4, then go to 1 with `--prior` and `--more`) and **"Stop"**. In Flow
   auto mode, stop here and report: the run never accepts gaps on the user's behalf.
7. **`done`**: list `advisory` (minor findings). Answer each as in 4. If you changed the
   artifact, go to 1 with `--prior` so the change is reviewed too; past the budget, say that
   those changes were not reviewed.

**Finish.** End with one line, `peer review: <approved | known gaps accepted | stopped> after
<n> round(s); review dir: <review_dir>`, then the lenses, each lens's last verdict, each advisory
finding with its disposition, the decisions recorded and any known gaps. A caller reads this
line: on `stopped` it files nothing; on `known gaps accepted` it records the gaps where its own
instructions say (for `/create-prd`, under `## Open questions`). Standalone, the gaps go in your final
answer to the user.

## With `--herdr`

The reviewers run in herdr tabs instead of subagents; everything else above is the same,
including the verdict path (`aiw peer-review verdict --file -`) and every rule. Headless runs
(the web UI) ignore `--herdr` and use subagents. If `command -v herdr` fails, use subagents and
say so.

- Once, before round 1: `herdr pane current` for the workspace id, then for each lens
  `herdr tab create --workspace <ws> --cwd <repo> --label rv-<lens>` and
  `herdr agent start rv-<lens> --kind claude --pane <pane> -- --agent ai-workflow:run-specialist --model opus --disallowedTools "Write,Edit,NotebookEdit"`,
  so each tab runs as the reviewer agent on Opus with no file-editing tools. Its shell commands
  follow your normal permissions, so a shell can still write files (in bypass mode, without
  asking); that is not read-only. It searches code with `rg` through the shell.
- Each round, step 2 becomes: `herdr agent prompt rv-<lens> "<the same dispatch text>"` for
  every lens (no `--wait`, so they work in parallel), then for each lens
  `herdr agent wait rv-<lens> --until idle --until done --until blocked`. On `blocked`, tell the
  user which tab needs them (usually a permission prompt) and wait again; it does not count as
  a missing verdict. Right after the prompt the tab can still read `idle`, so `wait` may return
  before the reviewer starts: if `round-<n>/<lens>.json` is missing, wait again before
  re-dispatching.
- The tabs stay open across rounds, so a reviewer remembers its earlier rounds; `prior` stays
  the record of what was settled. The user can talk to any tab between rounds.

## Self-improve

After the task, follow `../../self-improve.md` (relative to this skill's directory).
