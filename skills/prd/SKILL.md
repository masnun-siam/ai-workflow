---
name: prd
description: "Turn a rough requirement into a reviewed PRD: scan the codebase first, interview the user with the grilling skill, then save the PRD to a local file, the Obsidian vault and/or the repo's GitHub wiki. Use whenever the user says /prd, 'write a PRD', 'PRD for X', 'product requirements for X', 'flesh out this feature before we build it', or hands over a feature idea, BRD file, Obsidian note or issue URL and wants it pinned down as a PRD. Not for raw capture/filing (use /dump), technical design (use spec), or normalising input only (use /intake)."
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
  - Agent
  - Skill
  - AskUserQuestion
---

# /prd — Requirement → grilled PRD → saved

Produces a PRD only: the *what* and *why*. Architecture, data models and API design belong to `spec` / `run-planner` later. The one place code shows up is a short "Codebase context" note inside Overview, so the PRD stays honest about what already exists.

Why this order matters: scanning before interviewing means the questions are informed ("the code already does X — do you want that kept?") instead of asking the user things the repo can answer. Showing the full draft before saving matters because two of the three destinations (vault, wiki) are shared and hard to retract.

## Arguments

`/prd <requirement> [--to local,obsidian,wiki]`

- `<requirement>`: free text, a BRD file, an Obsidian note, a Sentry link or a GitHub issue URL.
- `--to`: one or more destinations. Default `local`. If the user passes none, still use `local` as the preselected default, but ask once at the end (Step 6) whether to add the others.

## Step 1: Normalise the input

Free text → use as is. Anything else (file path, Obsidian note, URL) → run `/intake` on it and use its brief as the requirement. Don't re-implement parsing here.

Derive a short **title** and kebab-case **slug** from the requirement. Detect the repo with `gh repo view --json nameWithOwner,name` (fall back to the git remote).

## Step 2: Check for an existing PRD at every chosen destination — before any interviewing

Interviewing for ten minutes and then discovering a PRD already exists wastes the user's time, so check first.

| Destination | Existence check |
|---|---|
| local | `docs/prd/<slug>.md` in the repo root |
| obsidian | `obsidian vault=notes file path="05-Work/<Project>/<Feature>/PRD.md"` — prints `Error: ... not found` (exit code 0) when missing, so read the output text |
| wiki | after cloning (Step 7), look for `PRD-<Title-With-Dashes>.md`; for an early check use `git ls-remote` only to confirm the wiki exists, and defer the page check to the clone |

If a PRD already exists anywhere: **stop and ask the user** what to do (read it and update it, pick a new name, skip that destination). Never overwrite silently. If they choose to update, read the existing PRD before Step 4 so the interview builds on it and keeps earlier decisions.

For Obsidian, also resolve the project and feature folder here, the same way `dump` does:

1. `obsidian vault=notes read path="05-Work/Index.md"` and match the repo/project name against it (e.g. wasensi → `05-Work/Wasensi`). Read `05-Work/<Project>/Index.md` too.
2. Show the resolved target in the Step 6 confirmation. A **new** feature folder needs the user's explicit OK, same rule as `/dump`; never create a project folder or edit `05-Work/Index.md` on your own.

## Step 3: Scan the codebase (once, up front)

Launch one Explore agent with the requirement and ask for: the modules, models, routes/jobs and UI that relate to it; current behaviour the requirement touches or contradicts; existing constraints (limits, permissions, tenancy, billing, integrations); and similar features worth reusing. Ask for file paths and a short summary, not file dumps.

Follow the repo's own search rules if its CLAUDE.md names a preferred code-search tool (e.g. GitNexus) — put that in the agent prompt. Keep the summary as interview context. Only a few lines of it go into the PRD, under Overview.

## Step 4: Grill

Invoke the `grilling` skill via the Skill tool, passing the requirement, the scan summary and the starting design tree below. Let grilling run its own rounds and its own rule about facts vs decisions: when a question needs a fact from the code, look it up (sub-agent) instead of asking the user. The interview ends only when the user confirms shared understanding.

Starting tree. Each branch unlocks the ones below it, so ask the top ones first:

1. **Problem and users** — who has the problem, what happens today, why now.
2. **Goals and non-goals** — what done looks like; what is deliberately excluded.
3. **Requirements** — each behaviour as something testable, with acceptance criteria. Reconcile against what the scan found.
4. **Edge cases** — failure paths, permissions, tenancy, empty/limit states, migration of existing data.
5. **Success metrics** — how anyone will know it worked.
6. **Rollout and dependencies** — flags, phasing, other teams, external services.

Skip branches the requirement already settles. Do not drift into implementation choices; if one comes up, record it in Open questions for the later technical spec.

## Step 5: Draft

Fill this template with what was agreed. Keep the user's decisions and their one-line reasons in **Decisions**; anything still unresolved goes in **Open questions** (never invent an answer to fill a section — write "None" if empty).

```markdown
# PRD — <Title>

**Status:** Draft · **Date:** YYYY-MM-DD · **Repo:** <owner/repo>

## Overview
<2–4 sentences. Then "Codebase context:" with 2–5 bullets from the scan, with file paths.>

## Problem
## Users
## Goals
## Non-goals
## Requirements
- **FR-1** <behaviour>
  - Acceptance: <observable check>
## Edge cases
## Success metrics
## Decisions
- <decision> — <why>
## Open questions
## Related
```

The Obsidian copy additionally gets tag frontmatter and full-path wikilinks in `## Related` (Step 7). Local and wiki copies use plain links.

## Step 6: Review gate — always

Show the **full** draft, plus for each chosen destination the exact path it will be written to (and, for Obsidian, the resolved project/feature folder and whether it is new). Wait for an explicit OK. Apply any edits and show the changed draft again until the user approves. If `--to` was not given, ask here whether to also save to Obsidian and/or the wiki.

Nothing is written anywhere before this approval. The wiki push needs its own explicit confirmation in Step 7, because pushing to a wiki publishes it.

## Step 7: Save

**local** — write `docs/prd/<slug>.md` with the Write tool (create `docs/prd/` if needed). Do not `git add` or commit; the user decides.

**obsidian** — always through the `obsidian` CLI with `vault=notes`, never plain file writes, so the index stays in sync. Follow `skills/dump/SKILL.md` ("Tagging and linking" and "New feature") for the exact commands:

```
obsidian vault=notes create path="05-Work/<Project>/<Feature>/PRD.md" content="<PRD>"
obsidian vault=notes property:set path="05-Work/<Project>/<Feature>/PRD.md" name=tags value="work,<project-tag>,type/feature,<feature-slug>" type=list
obsidian vault=notes append path="05-Work/<Project>/<Feature>/PRD.md" content="\n## Related\n- [[05-Work/<Project>/Index|<Project> Project Index]]"
obsidian vault=notes append path="05-Work/<Project>/Index.md" content="- [[05-Work/<Project>/<Feature>/PRD|<Feature>]]"
```

Read a sibling's tags first to reuse the feature slug, and list existing siblings (Dump, Decisions, SRS…) in `## Related`. Add the PRD line to existing siblings' Related blocks as dump does. The project tag table lives in dump's SKILL.md.

**wiki** — only after a final "push to the wiki?" confirmation:

1. `git clone --depth 1 https://github.com/<owner>/<repo>.wiki.git` into the scratchpad directory (the wiki's default branch is usually `master`; check with `git branch --show-current`).
2. Write `PRD-<Title-With-Dashes>.md`. Stop and ask if it already exists.
3. Add a link to it on a `PRDs` index page (create `PRDs.md` if missing) and, if the wiki has `_Sidebar.md`, leave it alone unless the user asks.
4. Commit with a plain message (`docs: add PRD — <Title>`) and push. Never use `--no-verify`.

If any save step fails, report which destinations succeeded and which didn't. Don't retry silently.

## Step 8: Report and hand off

One line per destination with its final path or URL. Then offer, in one line, to run `/gh-issue` with the PRD as the body. Do nothing further unless the user says yes.

## Guardrails

- No customer PII, secrets or production data in the PRD. If the interview surfaces any, refer to it generically.
- The PRD is a deliverable for the user. Don't add session URLs, local absolute paths or "Claude-Session" lines to it.
- Don't commit or push the repo; the only push this skill ever performs is the confirmed wiki push.
