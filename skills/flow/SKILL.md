---
name: flow
description: "Guide one feature from raw input to autopilot: /dump (optional) → /create-prd → approval → /create-tasks → /refine-issues → aiw autopilot, stopping for the user's go-ahead at every stage boundary. Picks the entry stage from the input, so half-done work (a PRD, existing issues) resumes where it is. Use whenever the user says /flow, 'take this idea to PRs', 'guided flow', or wants an idea carried through capture, PRD, tasks, refined issues and autopilot in one go."
allowed-tools:
  - Skill
  - AskUserQuestion
  - Bash
  - Read
---

# /flow — Idea → PRD → tasks → refined issues → autopilot

`/flow` holds the user's place in the Guided Flow. It owns no stage logic: each stage is the existing skill, invoked through the Skill tool in this same session. Its job is to pick the entry stage, carry each stage's output into the next, and ask before every boundary.

The artifacts are the state (the PRD file, its `Epics` section, the epic's child issues), so take each next argument from them, never from memory. A stage that fails or is declined ends the flow.

## Arguments

`/flow <raw idea | feature folder | Dump.md path | PRD path | epic number | issue URL>`

| Input | Entry stage |
|---|---|
| Raw text (anything that is not one of the shapes below) | dump, then create-prd |
| A vault feature folder `05-Work/<Project>/<Feature>`, or its `Dump.md` path | create-prd |
| A PRD path (vault `…/PRD.md` or repo `docs/prds/<slug>.md`), not yet `Approved` | approval, then create-tasks |
| An `Approved` PRD path | create-tasks |
| An epic number whose child issues are not all refined (`gh issue view`; a refined issue carries WHAT, WHY and HOW) | refine-issues |
| An epic number whose child issues are all refined | autopilot |

When an input fits no row cleanly, ask which stage to start at (AskUserQuestion) rather than guessing. Resolve `<owner/repo>` once with `gh repo view --json nameWithOwner -q .nameWithOwner`.

## Stages

1. **dump** (optional; skip it when the user already has a PRD, a folder or a clear idea they want spec'd). Invoke `ai-workflow:dump` with the raw text. Its own routing confirmation still applies. A bug report or standalone task ends the flow after filing.
2. **create-prd.** Invoke `ai-workflow:create-prd` with the feature folder or idea. It interviews the user and saves a `Draft` PRD. Then offer the peer-review panel: from the web UI, the PRD card's lens picker; by hand, `/ai-workflow:peer-review <prd-path>`. The panel is optional; do not run it without a yes.
3. **approval.** Only on the user's say that the PRD is reviewed: invoke `ai-workflow:create-prd` with `approve <prd-path>`. It files the epic and writes its number into the PRD's `Epics` section.
4. **create-tasks.** Invoke `ai-workflow:create-tasks` with the PRD path. It files the child issues under the epic.
5. **refine-issues.** Invoke `ai-workflow:refine-issues` with the epic number (from the PRD's `Epics` section).
6. **autopilot.** Run `aiw autopilot <owner/repo> <epic> on`. Autopilot then starts eligible refined issues up to the repo's cap; `aiw autopilot <owner/repo> <epic> off` stops it.

## Checkpoints

Before each stage after the entry stage, ask one AskUserQuestion: "Continue to <next stage> (Recommended)" / "Stop here", naming the argument it will get. On "Stop here", say `/flow <that argument>` resumes. The approval question is "Approve the PRD and file its epic (Recommended)" / "Stop here", because Continue is the approval and it creates a GitHub issue. Never advance past a boundary without an explicit "Continue".

## Guardrails

- No stage logic copied here: PRD writing, task splitting and refining belong to their own skills.
- No state file. One feature per run.
- Never create GitHub issues, or switch autopilot on, without the user's "Continue" into that stage.

## Self-improve

After the task, follow `../../self-improve.md` (relative to this skill's directory).
