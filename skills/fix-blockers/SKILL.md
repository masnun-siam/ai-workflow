---
name: fix-blockers
description: "Set GitHub's native 'blocked by' relations between an epic's child issues, derived from their 'Depends on: #n' lines, so a task whose dependency is not merged yet shows as blocked on GitHub. Previews the edges, asks once, then writes only the missing ones. Use whenever the user says /fix-blockers, 'set the blockers', 'link the dependencies', or has just filed an epic's sub-issues with /refine-issues and wants its dependency order visible on GitHub."
allowed-tools:
  - Bash
  - AskUserQuestion
---

# /fix-blockers — Depends on lines → GitHub blocked-by

> **Paths.** Run `aiw paths` and use its `runs_dir` value for `<runs_dir>` below; never guess a
> path. If `aiw paths` does not print JSON whose first key is `plugin_root`, stop and report that
> the plugin is not installed.

`/fix-blockers <parent>`: the epic parent's number or URL.

The children's `Depends on:` lines are the only source of these relations (ADR 0003). This skill
never adds an edge they don't name. An edge GitHub has that no line names is reported and never
deleted: someone may have added it on purpose. To change an edge, edit the `Depends on:` line and
run this again.

### Asking the user

Headless (your system prompt contains `Headless run: ask via aiw ask`): ask the Step 3 question
with `aiw ask`, passing the JSON through a quoted heredoc (`aiw ask <<'EOF'` … `EOF`), recommended
option first with `(Recommended)` on its label, then end your turn; the answer arrives as your next
message. Otherwise use AskUserQuestion.

### Flow auto mode

When the system prompt contains `Flow auto mode`, this run is the Blockers step of the aiw ui
guided Flow. Starting that step was the user's confirmation, so Step 3 asks nothing and applies
the edges. Print the `→ next:` line as text only.

## Step 1: Find the epic

Resolve `<owner>/<repo>` with `gh repo view --json nameWithOwner -q .nameWithOwner`. The epic
directory is `<runs_dir>/<owner>-<repo>-epic-<parent>`. If it has no `epic.json` (the parent was
filed on another machine, or the run directory was cleaned), build it the way `/run-issue` Epic
mode step 0 does:

```bash
gh api repos/<owner>/<repo>/issues/<parent>/sub_issues --jq '[.[].number]'
aiw epic split "<runs_dir>/<owner>-<repo>-epic-<parent>" \
  --parent <parent> --slug <owner>/<repo> --children <n>,<n>,…
```

An empty sub-issue list means `<parent>` is not an epic: stop and say so. A split that exits 1
names the bad `Depends on:` line: report it and stop.

This split writes to GitHub before Step 3's question, because Step 2's preview needs the
`epic.json` it builds. Its write is the one `/refine-issues` already made when it ran `aiw epic split`:
already-linked children are skipped, and the parent's `## Tasks` checklist is rewritten from the
children's current titles and order. Say so in the report; a hand-edited `## Tasks` section on
that parent is replaced.

## Step 2: Preview

```bash
aiw epic blockers "<runs_dir>/<owner>-<repo>-epic-<parent>" --dry-run
```

It validates the dependency graph and prints each edge it would add, plus any edge on GitHub that
no `Depends on:` line names. Exit 1 means a cycle or an unreadable issue: report it and stop. With
nothing to add, report that and go to Step 4.

## Step 3: Confirm once

Show the preview and ask one question with the choices **"Add these"** and **"Stop"**. "Stop"
writes nothing. Then, on "Add these":

```bash
aiw epic blockers "<runs_dir>/<owner>-<repo>-epic-<parent>"
```

It writes only the missing edges, so running it again is safe. On exit 1, report the edge it names
and the edges already added, and stop.

## Step 4: Report

One line per edge added, and the reported extras. Then say the children can run: one tab each with
herdr-dispatch, or one session with `/run-issue <parent>` (Epic mode). End with this line, as the
last line of your output:

`→ next: herdr-dispatch <parent>`
