---
name: flow
description: "Guide one feature from raw input to dispatched /run-issue runs: /dump (Obsidian) → /create-prd → /create-tasks → /refine-issues → /fix-blockers → herdr-dispatch, stopping for the user's go-ahead at every stage boundary. Picks the entry stage from the input, so half-done work (a PRD, existing issues) resumes where it is. Use whenever the user says /flow, 'take this idea to PRs', 'guided flow', or wants an idea carried through capture, PRD, tasks, issues and dispatch in one go."
allowed-tools:
  - Skill
  - AskUserQuestion
  - Bash
  - Read
---

# /flow — Idea → PRD → tasks → refined issues → blockers → dispatch

`/flow` holds the user's place in the Guided Flow. It owns no stage logic: each stage is the existing skill, invoked through the Skill tool in this same session. Its whole job is picking the entry stage, routing, carrying each stage's output into the next, and asking before every boundary.

Every stage ends its output with one line, `→ next: <command> <argument>`. That line is the handoff contract: take the next stage's argument from that line, never from your own reading of the stage's output. A stage that ends without the line ends the flow.

A stage's own "last line of your output" or "do nothing further" ends that stage, not `/flow`: once its `→ next:` line is printed, carry on to **Checkpoints**.

## Arguments

`/flow <raw text | feature folder | Dump.md path | PRD path | task list | epic parent | issue numbers>`

| Input | Entry stage |
|---|---|
| Raw text (anything that is not one of the shapes below) | dump |
| A vault feature folder `05-Work/<Project>/<Feature>`, or its `Dump.md` path (use the folder) | create-prd |
| A PRD path (a vault `…/PRD.md` or a repo `docs/prds/<slug>.md`) | create-tasks |
| A task list `docs/tasks/<slug>.md` | refine-issues |
| A `Bugs.md` or `Tasks.md` note a `→ next: /gh-issue` line named | gh-issue |
| An epic parent a `→ next: /fix-blockers` line named | fix-blockers |
| Issue numbers: bare integers or GitHub issue URLs, one or more | dispatch |

A vault path starts with `05-Work/`. When an input fits no row cleanly, ask which stage to start at (AskUserQuestion) rather than guessing.

## Stages

### dump

Invoke the `ai-workflow:dump` skill with the raw text. Its own Step 3 confirmation still applies. When it finishes, read its classification and its final `→ next:` line, then go to **Routing after dump**.

### create-prd

Invoke the `ai-workflow:create-prd` skill with the feature folder (`/create-prd <feature-folder>`). It fills the folder's seeded `PRD.md`, or, on a PRD that is already finished (a change request), asks and updates it. Its final line is `→ next: /create-tasks <prd-path>`. The same skill is the target when `gh-issue` stops with `→ next: /create-prd <input>`: the input needs a PRD, so run create-prd on that input.

### create-tasks

Invoke the `ai-workflow:create-tasks` skill with the PRD path. It works only from an Approved PRD and saves a small, ordered task list. Its final line is `→ next: /refine-issues docs/tasks/<slug>.md`.

### refine-issues

Invoke the `ai-workflow:refine-issues` skill with the task list path. It files one refined sub-issue per task under the PRD's epic, with `Depends on:` lines. Its final line is `→ next: /fix-blockers <epic>`.

### gh-issue

Invoke the `ai-workflow:gh-issue` skill with the note path. It files exactly one issue. Its final line is `→ next: herdr-dispatch <n>`, or `→ next: /create-prd <input>` when it stopped because the input splits into 2 or more tasks. That is not an error: go to the create-prd stage with that argument.

### fix-blockers

Invoke the `ai-workflow:fix-blockers` skill with the epic number. It sets GitHub's blocked-by relations from the `Depends on:` lines. Its final line is `→ next: herdr-dispatch <epic>`.

### dispatch

See **Dispatch** below.

## Routing after dump

| Dump classification | Path |
|---|---|
| New feature request | create-prd → create-tasks → refine-issues → fix-blockers → dispatch |
| Change request | create-prd (update path) → create-tasks → refine-issues → fix-blockers → dispatch |
| Bug report | gh-issue → dispatch |
| Feature-scoped task | gh-issue → dispatch |
| Standalone task, weekly meeting notes, unclassifiable | stop after filing; there is no next stage |

## Checkpoints

At every boundary between stages, ask one AskUserQuestion: "Continue to <next stage> (Recommended)" / "Stop here", naming the argument the `→ next:` line gave. On "Stop here", print that `→ next:` line and tell the user they can resume later with `/flow <that argument>`. Never advance past a boundary without the user's "Continue".

The boundary after `create-prd` asks "Approve the PRD, file its epics, and continue to create-tasks (Recommended)" / "Stop here", because Continue is the approval and files GitHub epics. When the user answers Continue at the boundary after `create-prd`, first invoke `ai-workflow:create-prd` with `approve <prd-path>` (the Continue is the approval; it creates the epics without asking again), then invoke `create-tasks`.

## Dispatch

1. Convert any issue URLs to their numbers (`herdr-dispatch` takes numbers, not URLs). Invoke the `ai-workflow:herdr-dispatch` skill with `<numbers> --max 2 --dry-run` and show the user its order and launch plan.
2. Ask one AskUserQuestion: "Launch" / "Stop here".
3. On "Launch", invoke `ai-workflow:herdr-dispatch` with `<numbers> --max 2`. If the user asked for the main tree (`/flow … --no-worktree`), use `<numbers> --sequential --no-worktree` instead of `--max 2`, in both the dry run and the launch. If the user passed `--no-review`, append `--no-review` to the herdr-dispatch arguments too, and likewise `--grind`. On "Stop here", print `→ next: herdr-dispatch <numbers>` and stop.

## Guardrails

- No stage logic copied here: classification, PRD writing, task splitting and dispatch belong to their own skills.
- No state file. The artifacts (vault note, PRD, issues) are the state, which is why `/flow <argument>` can resume.
- One feature per run. The epics `/create-prd approve` files are the only tracking issues; this skill never creates another.
- Never launch a dispatch without an explicit "Launch", and never create GitHub issues without the user's "Continue" into the create-tasks (it runs the approve that files epics), gh-issue or refine-issues stage.
