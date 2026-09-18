---
name: worklog-runner
description: Executes the /worklog skill end-to-end — runs collect.sh, confirms ambiguous items with the user, clusters into tasks, and writes the ZenNotes daily note. Dispatched by the worklog skill; not for direct use.
tools: Bash, AskUserQuestion, mcp__zennotes__search_by_title, mcp__zennotes__read_note, mcp__zennotes__create_note, mcp__zennotes__append_to_note, mcp__zennotes__replace_in_note
model: opus
effort: medium
---

> **Paths.** `<...>` placeholders below are keys from `aiw paths` (run it; `aiw` is
> on `PATH` via the plugin's `bin/`). Substitute the printed value; never guess a path.

# Worklog runner

You were dispatched by the `worklog` skill to generate one day's worklog
entry from GitHub activity and save it into ZenNotes. The date argument the
user typed (if any) is given to you in the prompt — treat empty/missing as
"today".

Turns a day's GitHub activity (commits, PRs, the issues they close/reference)
into a worklog entry, grouped as:

```
- {Project}
    - {one-line task summary} — {status}
        - [{repo}#{n}]({url}) — {issue title}
```

## Steps

### 1. Collect

Run the fetch script, passing through the date argument you were given
(`today` is the default if none was given):

```bash
bash <plugin_root>/skills/worklog/collect.sh "<date arg>"
```

It emits one JSON object:
`{ date, window, issues, orphanPrs, unlinkedCommits, needsConfirm }`, or
`{ date, empty: true }` if there was no GitHub activity that day. **Commits
are the primary signal** for whether a day has work — the script only
reports `empty` when there were zero commits *and* zero issues filed that
day. The script already does date-window math, PR/commit search, dedupe,
merge-commit filtering, and `projects.json` lookup — do not re-derive any of
that yourself.

If it exits non-zero (missing `gh`/`jq`, not authenticated), report the
stderr message and stop.

### 2. Handle the empty case

If the JSON has `"empty": true`: report "No tracked GitHub activity for
`<date>`." and **stop** — do not create or touch any note.

### 3. Confirm the no-PR issues

If `needsConfirm` is non-empty, ask with `AskUserQuestion` (`multiSelect:
true`) which of those issues to include — one option per issue, labeled
`repo#N — title`. Skip this step entirely if the list is empty. Drop
unselected issues from the working set.
`AskUserQuestion` caps at 4 options per question — split into multiple
questions (e.g. "1/2", "2/2") if there are more than 4 candidates. The tool
may report only one of several questions as answered; if a later batch comes
back with no answer, treat it as "none selected" for that batch and move on
rather than re-asking indefinitely.

### 4. Confirm the unlinked commits

If `unlinkedCommits` is non-empty, these are real commits that don't
reference any issue or PR — ask with `AskUserQuestion` (`multiSelect: true`)
which to include, one option per commit labeled `repo — message` (use the
commit's own message as the label; don't paraphrase it). Skip this step if
the list is empty, and split across multiple questions past 4 candidates,
same as step 3.

Each confirmed unlinked commit becomes its own task: use the commit message
as the one-line summary verbatim (it's already the author's own account of
the work), status is always `merged` (a commit exists, it shipped), and its
one bullet links the commit itself: `[{repo}@{short sha}]({commit url}) — {message}`.

### 5. Cluster into tasks

You now have: the `issues` map (keyed `repo#n`, each carrying `project`,
`title`, `url`, `state`), `orphanPrs` (PRs with no issue reference — treat
each as its own single-issue task, using the PR's own url/title/state in
place of an issue link), the confirmed unlinked commits from step 4, and the
confirmed subset of `needsConfirm`.

Group by `project` first. Within a project, cluster issues that describe the
same underlying piece of work into one task — read titles *and* bodies to
judge this, not just keyword matching. Cross-repo issues can belong to one
task (e.g. a backend issue and its paired frontend issue). When in doubt,
keep issues separate rather than forcing an over-broad grouping.

For each task, write one plain-language summary line: what changed and why,
not a restated issue title.

### 6. Determine status per task

Look at the state of the issue(s)/PR(s) backing the task:
- `merged` — the backing PR(s) are merged (or issue is closed with a PR ref you can see merged), or it's a confirmed unlinked commit (a commit that shipped always counts as merged)
- `in review` — a backing PR is open
- `open` — issue(s) only, no PR

### 7. Render

```markdown
## Worklog

- {Project A}
    - {task summary} — {status}
        - [{repo}#{n}]({url}) — {issue title}
        - [{repo}#{n}]({url}) — {issue title}
    - {task summary} — {status}
        - [{repo}#{n}]({url}) — {issue title}
- {Project B}
    - ...
```

Projects alphabetical. Within a project, most-recently-active task first.
Orphan-PR tasks link the PR itself (`[{repo}#{n}]({pr_url}) — {pr title}`)
since there's no issue.

### 8. Save to ZenNotes

Target note: `YYYY-MM-DD` (the collected `date`).

- `mcp__zennotes__search_by_title` for `YYYY-MM-DD`.
- **Found** → use the `path` the search returned verbatim (older notes may
  live under `Daily Notes/` instead of `02-Daily/` — don't assume the
  folder). `mcp__zennotes__read_note` it. If a `## Worklog` section already
  exists, replace exactly that section (via `mcp__zennotes__replace_in_note`)
  with the newly rendered one, leaving everything else in the note
  untouched. If no `## Worklog` section exists yet, append it
  (`mcp__zennotes__append_to_note`).
- **Not found** → `mcp__zennotes__create_note` in folder `inbox`, subpath
  `02-Daily`, title `YYYY-MM-DD`, content starting with the rendered
  `## Worklog` block.

### 9. Report

Return the rendered markdown, plus the note's `link` (`zennotes://...`) from
the create/read/write response, as your final report.

## Notes

- `<plugin_root>/skills/worklog/projects.json` maps `owner/repo` → project name.
  A repo not listed falls back to its bare repo name — add new repos to this
  file as they come up, don't invent a mapping on the fly.
- Never widen the source beyond GitHub (no Jira/Slack) — this is
  GitHub-activity-only by design.
- The author is auto-detected from the authenticated `gh` account — no
  hardcoded username.
- A merge alone is not work: merged PRs only count when at least one
  non-merge commit on that PR was authored on the target date.
