---
name: flow
description: "Guide one feature from raw input to dispatched /run-issue runs: /dump (Obsidian) → /prd → /gh-issue (flat refined issues) → herdr-dispatch, stopping for the user's go-ahead at every stage boundary. Picks the entry stage from the input, so half-done work (a PRD, existing issues) resumes where it is. Use whenever the user says /flow, 'take this idea to PRs', 'guided flow', or wants an idea carried through capture, PRD, issues and dispatch in one go."
allowed-tools:
  - Skill
  - AskUserQuestion
  - Bash
  - Read
---

# /flow — Idea → PRD → issues → dispatch

`/flow` holds the user's place in the Guided Flow. It owns no stage logic: each stage is the existing skill, invoked through the Skill tool in this same session. Its whole job is picking the entry stage, routing, carrying each stage's output into the next, and asking before every boundary.

Every stage ends its output with one line, `→ next: <command> <argument>`. That line is the handoff contract: take the next stage's argument from that line, never from your own reading of the stage's output. A stage that ends without the line ends the flow.

## Arguments

`/flow <raw text | feature folder | Dump.md path | PRD path | issue numbers>`

| Input | Entry stage |
|---|---|
| Raw text (anything that is not one of the shapes below) | dump |
| A vault feature folder `05-Work/<Project>/<Feature>`, or its `Dump.md` path (use the folder) | prd |
| A PRD path (a vault `…/PRD.md` or a local PRD file), or the `Bugs.md` / `Tasks.md` note a `→ next: /gh-issue` line named | gh-issue |
| Issue numbers: bare integers or GitHub issue URLs, one or more | dispatch |

A vault path starts with `05-Work/`. When an input fits no row cleanly, ask which stage to start at (AskUserQuestion) rather than guessing.

## Stages

### dump

Invoke the `ai-workflow:dump` skill with the raw text. Its own Step 3 confirmation still applies. When it finishes, read its classification and its final `→ next:` line, then go to **Routing after dump**.

### prd

Invoke the `ai-workflow:prd` skill with the feature folder (`/prd <feature-folder>`). It fills the folder's seeded `PRD.md`, or, on a PRD that is already finished (a change request), asks and updates it. Its final line is `→ next: /gh-issue <prd-path>`.

### gh-issue

Invoke the `ai-workflow:gh-issue` skill with the PRD path or note path. It splits the work into flat `refined` issues with `Depends on: #n` lines, under its own confirmations. Its final line is `→ next: herdr-dispatch <n> <n> …`.

### dispatch

See **Dispatch** below.

## Routing after dump

| Dump classification | Path |
|---|---|
| New feature request | prd → gh-issue → dispatch |
| Change request | prd (update path) → gh-issue → dispatch |
| Bug report, feature-scoped task | gh-issue → dispatch |
| Standalone task, weekly meeting notes, unclassifiable | stop after filing; there is no next stage |

## Checkpoints

At every boundary between stages, ask one AskUserQuestion: "Continue to <next stage> (Recommended)" / "Stop here", naming the argument the `→ next:` line gave. On "Stop here", print that `→ next:` line and tell the user they can resume later with `/flow <that argument>`. Never advance past a boundary without the user's "Continue".

## Dispatch

1. Invoke the `ai-workflow:herdr-dispatch` skill with `<numbers> --max 2 --dry-run` and show the user its order and launch plan.
2. Ask one AskUserQuestion: "Launch" / "Stop here".
3. On "Launch", invoke `ai-workflow:herdr-dispatch` with `<numbers> --max 2`. On "Stop here", print `→ next: herdr-dispatch <numbers>` and stop.

## Guardrails

- No stage logic copied here: classification, PRD writing, issue splitting and dispatch belong to their own skills.
- No state file. The artifacts (vault note, PRD, issues) are the state, which is why `/flow <argument>` can resume.
- One feature per run. No epics or parent tracking issues.
- Never launch a dispatch without an explicit "Launch", and never create issues without the user's "Continue" into the gh-issue stage.
