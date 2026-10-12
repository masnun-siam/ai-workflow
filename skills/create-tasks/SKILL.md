---
name: create-tasks
description: "Break a problem statement and its PRD into a saved, ordered list of small tasks (docs/tasks/<slug>.md), each one an independently implementable unit, before any GitHub issue exists. Use whenever the user says /create-tasks, 'break this into tasks', 'make a task list from this PRD', or hands over a /dump problem statement or a PRD and wants it decomposed. Creates no issues: /gh-issue files them from the saved list."
allowed-tools:
  - Bash
  - Read
  - Write
  - Grep
  - Glob
  - AskUserQuestion
  - mcp__gitnexus__query
  - mcp__gitnexus__context
---

# /create-tasks — problem statement + PRD → saved task list

> **Paths.** This skill runs in the user's repo, not the plugin's. Run `aiw paths` and use its
> `plugin_root` value for `<plugin_root>` below; never guess a path. If `aiw paths` does not print
> JSON whose first key is `plugin_root`, stop and report that the plugin is not installed.

The decomposition rules live in one place: `<plugin_root>/commands/gh-issue.md` steps
`3.5. **Decompose.**` and `3.6. **Save the task list.**`. Read both and apply them as written, with
the changes below. Do not copy them here; a rule changed there applies here too.

## Arguments

`/create-tasks <problem-statement> [<prd>]`

- `<problem-statement>`: what `/dump` filed (a vault `Dump.md`, or a bug in `Bugs.md`), or free text.
- `<prd>`: the PRD, a repo `docs/prd/<slug>.md` or a vault `PRD.md`. If it is a vault note with a
  `canonical` property (`obsidian vault=notes property:read path="<prd>" name=canonical`) naming
  this repo, read that repo copy instead: it is the canonical one. A bug usually has no PRD.

Read vault notes with `obsidian vault=notes read path="..."` and repo files with Read.

### Asking the user

Headless (your system prompt contains `Headless run: ask via aiw ask`): ask every question below
with one `aiw ask` call per round, passing the JSON through a quoted heredoc
(`aiw ask <<'EOF'` … `EOF`), recommended option first with `(Recommended)` on its label, then end
your turn; the answer arrives as your next message. Otherwise use AskUserQuestion.

## Step 1: Gather

1. Read the inputs. The PRD's Requirements, Decisions and Open questions stand in for the grilling
   that gh-issue's step 3 would have done.
2. If anything is still open (the PRD's `## Open questions`, the problem statement's **Open
   questions**, or a bug with no PRD whose expected behaviour is unclear), ask it now, in one round.
   Never decompose on a gap.
3. Find the code the work touches, as gh-issue's step 1 does: GitNexus (`gitnexus_query`,
   `gitnexus_context`) when the repo is indexed, Grep and Glob otherwise. Each task's
   Files/symbols come from this lookup.

## Step 2: Decompose and save

Apply gh-issue's 3.5 and then 3.6 to what Step 1 gathered, with these changes:

- **Approval means save, not file.** Offer the two choices as **"Save as shown"** and **"Let me
  edit the list"**. "Save as shown" runs 3.6's save and then Step 3. This skill creates nothing on
  GitHub: 3.5's routing to step 4 and `4-FLAT` does not apply here.
- **Always save,** even a single task, so the next step has a file to read.
- **Order follows the stack.** Dependency order comes from this repo's own layers. A Laravel-style
  stack might run migration → model → service → controller with its request and resource; that is
  an example, not a rule.

- **Two more header lines.** Below 3.6's header (title, source, date, owner/repo), add
  `Problem statement: <path>` and `PRD: <path>` (`PRD: none` when there is none), naming the
  inputs as given, so the issue-filing step can find them.

3.6's slug, destination, collision and failure rules apply unchanged.

## Step 3: Report

One line per destination written. End with this line, as the last line of your output:

`→ next: /gh-issue docs/tasks/<slug>.md`
