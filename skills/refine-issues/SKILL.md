---
name: refine-issues
description: "Turn a saved task list (docs/tasks/<slug>.md) into refined GitHub issues, one per task, each written from the code with the What, Why and How an implementer needs, filed as sub-issues of the PRD's epic with native blocked-by links, `Depends on:` lines and the team's project and labels, after checking every cited path against the code and getting confirmation. Use whenever the user says /refine-issues, 'create the issues from this task list', 'file these tasks', 'refine issues from docs/tasks/<slug>.md', or follows the `→ next: /refine-issues` line from /create-tasks."
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Grep
  - Glob
  - Agent
  - AskUserQuestion
  - mcp__gitnexus__query
  - mcp__gitnexus__context
---

# /refine-issues — saved task list → refined sub-issues of the epic

Creates one issue per task, under the PRD's epic and linked to the issues it waits for, so an
engineer or agent can start any unblocked one without asking anything or researching the code
again. The task list says what each task is; this skill gathers the context and writes it into
the issue. Creating issues is visible to the whole team: nothing is written to GitHub until the
user has seen the full list and confirmed it.

> **Paths.** This skill runs in the user's repo, not the plugin's. Run `aiw paths` and use its
> `plugin_root` and `runs_dir` values for `<plugin_root>` and `<runs_dir>` below; never guess a
> path. If `aiw paths` does not print JSON whose first key is `plugin_root`, stop and report that
> the plugin is not installed.

`<skill_dir>` is `<plugin_root>/skills/refine-issues`. **Template:** use the repo's own
`docs/templates/issue.md` when it exists; otherwise `<skill_dir>/templates/issue.md`. "The
template" below means the resolved file.

Read the repo's `CLAUDE.md` and the template first. Detect the repo (`gh repo view --json
nameWithOwner`, giving `<owner>/<repo>`); never assume it.

## Arguments

`/refine-issues <task-list-path | slug>`: the list the previous step's `→ next:` line named. A
slug means `docs/tasks/<slug>.md`.

### Asking the user

Headless (your system prompt contains `Headless run: ask via aiw ask`): ask every question below
with one `aiw ask` call per round, passing the JSON through a quoted heredoc
(`aiw ask <<'EOF'` … `EOF`), recommended option first with `(Recommended)` on its label, then end
your turn; the answer arrives as your next message. Otherwise use AskUserQuestion.

### Flow auto mode

When the system prompt contains `Flow auto mode`, this run is the Issues step of the aiw ui
guided Flow and asks nothing. Starting this step was the user's yes, so step 6 asks nothing and
its confirmation list goes in the final report instead. Every other gate still stops the run.

- **Assignees:** none.
- **Project:** the project(s) linked to the repo
  (`gh repo view <owner>/<repo> --json projectsV2 --jq '.projectsV2.Nodes'`); if several,
  the most recently updated one. If none is linked, use the owner's project when
  `gh project list` shows exactly one; otherwise add to no project and say so.
- **Project fields:** a field named `Status` (or the single-select field that plays that role)
  gets its first option. Every other single-select field gets the option that best fits the
  issue's content and the PRD (for example Priority from the PRD's priority). Never invent option
  names. List every value set, per issue, in the report.
- **Hand-off line:** print the `→ next:` line as text only. Never invoke `/fix-blockers`; the
  UI's next steps do that.

## Steps

1. **Read** `docs/tasks/<slug>.md` and the PRD its `Source PRD:` header names. If you were not
   given a slug, ask which one; `docs/tasks/` may not exist yet, so list it only if it does.

2. **Check it is ready.** Stop and send the user back to `/create-tasks` when the task list is
   missing, or a task lacks an outcome, files and symbols, acceptance criteria, a verify command,
   `Depends on` or `Parallel`, or when any task depends on a task in another epic (`aiw epic
   split` rejects an edge to an issue outside the epic). Stop as well when the PRD's status is not `Approved`, an epic in its
   `## Epics` still reads `Issue: —`, or that epic issue is closed
   (`gh issue view <epic> --json state`); send the user back to `/create-prd approve <prd>`.
   Find the GitHub project (in Flow auto mode, as above). Never hard-code a project name or
   number; read it from where the team's issues already are:
   1. List the projects recent issues sit on: `gh issue list --state all --limit 50 --json number,projectItems`. Look at epics first (`--label epic`), then at all issues.
   2. One project in use: add the new issues to it.
   3. More than one in use: ask which, recommending the one the most recent issues of the same kind are on.
   4. None in use: check `gh project list --owner <owner>`. Propose a project if exactly one is open; otherwise skip the project step and say so in the report. Do not create a project.

3. **Gather the context for each task** against the base branch: `<base>` is
   `gh repo view --json defaultBranchRef -q .defaultBranchRef.name`; run `git fetch origin <base>`
   first and read `origin/<base>`. The implementer will have only the issue, so read what they
   would otherwise have to find:
   - every file and symbol the task cites, with what each does today and the line numbers
   - the precedent the task copies, and the tests that sit next to it
   - the callers of anything the task changes: GitNexus when indexed (`gitnexus_query`,
     `gitnexus_context`), otherwise Grep/Glob
   - the parts of the PRD the task needs: the `FR-n` text, the API contract, the data shape, the
     decisions and edge cases that apply
   - the repo's conventions for that layer (`CLAUDE.md`, its docs)

   Tasks are independent, so research them in parallel (Agent) when the list is long. A cited path
   or symbol that does not exist is a finding, unless it is marked `(new)`: a new file's parent
   folder must exist or be `(new)` too, and a file created by a task it depends on counts as
   present. Fix the task, or ask the user, before drafting.

4. **Draft one issue per task** from the template, keeping its sections and their order. These
   sections are `/run-issue`'s Definition of Ready, and `aiw refined` reads the body to skip the
   researcher and planner, so never ship a `[bracketed placeholder]` or an unfilled `<placeholder>`.
   - Title `<Feature>: <summary>`, short and specific (72 characters or fewer).
   - **What** is the observable change and the `FR-n` it delivers. **Why** is the problem in the
     PRD's words and where this task sits in the feature.
   - **Out of Scope** names the neighbouring tasks that cover what this one leaves.
   - **Context / Affected Code** opens with the feature in two or three sentences, quotes the parts
     of the PRD the task needs, then lists what you found in step 3.
   - **Acceptance Criteria** are the task's, as a `- [ ]` checklist.
   - **How** is numbered steps, each naming the file, the symbol and the pattern to copy with its
     path, then the test file and its cases, ending with the task's verify command. Then a
     `Test root: <dir>` line (the repo-relative directory this task's tests live in) and, only when
     the pull request should not target `<base>`, a `Base branch: <branch>` line. Both stay plain
     text, because `aiw refined` reads them. Write steps you could follow yourself without opening
     the PRD.
   - **Non-functional Constraints**, **Assumptions**: write `none` deliberately where it is true.
   - **Dependencies / Blockers** holds one `Depends on: #<n>` line (with the colon) per task it
     depends on, filled in at creation once the numbers exist, or `Depends on: none`.
   - **Proposed Fix** only for a bug with an obvious fix; otherwise delete the section.
   - **Notes** carries `Task <n> of docs/tasks/<slug>.md` and `Epic #<n>`.
   - Labels: `refined`, `prd-<slug>`, the area label for the task's `Area` and the PRD's
     `priority:` label. In `prd-<slug>`, `<slug>` is the PRD's `**Slug:**` header field, never the
     task-list file name (which may be `<slug>-2`); step 5's label search uses the same value. Use only labels that exist (`gh label list`); `refined` and `prd-<slug>`
     are proposed for creation in step 6 when missing.
   - Before moving on, read the draft as the implementer: is there anything they would have to
     look up or ask? If so, it is not finished.

5. **Match against what already exists.** For each task, look at its `Issue:` field first, then
   search open and closed issues (`gh issue list --state all`) for the label `prd-<slug>` and the
   same `Task <n>` note, then the epic's existing sub-issues, then for the same title. Titles are
   reworded when issues are written, so the note is the reliable match. Two matches for one task is
   a finding for the user.
   - No match: the issue is created.
   - A match and the task is unchanged: skip it, and add only the parent, blocked-by, project and
     label links it lacks.
   - A match and the task is marked `Changed:`, or the PRD changed under it: draft the update and
     show what differs. An issue that is closed or has a pull request open is never edited without
     the user saying so for that issue.
   - A match and the task is marked `Dropped`: propose closing the issue as not planned, with the
     reason.

6. **Confirm.** Show the full list: the epic, the project and the status new issues will get (or
   that no project was found), titles, labels, dependencies, the waves, the issues to update or
   close and what changes in each, the tasks skipped as existing, the code findings, and any label
   that does not exist yet (propose creating it, with colour and description like the existing
   ones). Offer to show any draft in full. Ask (AskUserQuestion, headless: `aiw ask`) whether to
   create them, "Create these issues (Recommended)" / "Stop". If the answer is anything other than
   an explicit yes, write nothing and stop. In Flow auto mode, skip the question (see above).

7. **Create** in dependency order. Before the first create, ensure each missing `refined` and
   `prd-<slug>` label the confirmed list uses (in Flow auto mode, without asking), the way
   `/gh-issue` does; `gh label create` without `--force` leaves an existing label as it is, and
   never `--force` it, which would recolour it:

   ```bash
   gh label create refined --color 1D76DB --description "properly specified: passes the issue template" 2>/dev/null || true
   gh label create prd-<slug> --color 5319E7 --description "tasks of docs/prds/<slug>.md" 2>/dev/null || true
   ```

   Area and priority labels are used only when they already exist; never create or invent them.
   Then write each body to a scratch file with the Write tool, replacing
   each `Depends on:` with the real numbers, then:

   ```bash
   gh issue create --title "<title>" --parent <epic> --blocked-by <n,m> \
     --label "refined,prd-<slug>,<area>,<priority>" --body-file <file>
   ```

   plus `--project "<title>"` when step 2 found one. In Flow auto mode, set its fields as above;
   otherwise set its status to the option the team's other refined, unstarted issues have
   (`gh project item-list`, `gh project field-list`, then `gh project item-edit`), asking once
   when the board does not make that clear. Leave assignees empty unless the user named them. Project
   commands need the `project` scope on the `gh` token (`gh auth refresh -s project`); if it is
   missing, say so and carry on without the project step.
   - If this `gh` lacks `--parent` or `--blocked-by` (exit 1 with "unknown flag"), create the issue
     without them. `aiw epic split` below links the sub-issues and `/fix-blockers` sets the
     blocked-by edges from `Depends on:`. Say so in the report, and skip the blocked-by part of
     the read-back below.
   - Apply the confirmed updates with `gh issue edit` and add a comment to each updated issue
     saying what changed and why.
   - Record each number as you go.

   Then run **one `aiw epic split` per epic**. Its `--children` are every issue of that epic's
   tasks, in task-list order: the ones created now and the ones matched or skipped in step 5,
   never a `Dropped` task's. The split rewrites `epic.json` from that list, so passing only the
   new issues drops earlier children and turns their `Depends on:` lines into edges outside the
   epic, which exits 1.

   ```bash
   aiw epic split "<runs_dir>/<owner>-<repo>-epic-<epic>" \
     --parent <epic> --slug <owner>/<repo> --children <n>,<n>,…
   ```

   Children in list order. It links them as sub-issues, checks that `Depends on:` forms a DAG,
   writes the parent's `## Tasks` checklist, and writes the `epic.json` that `/run-issue <parent>`
   Epic mode reads. It is idempotent, so a re-run is safe. Exit 1: report its message and stop.
   It links the children before it checks `Depends on:`, so on a cycle or a bad `Depends on:` the
   children may already be linked while no `epic.json` exists; `/run-issue <parent>` Epic mode
   then re-runs the split in its step 0 and stops on the same error until the lines are fixed.

   Read each epic back (`gh issue view <epic> --json subIssues`, and `blockedBy` on each child)
   and check its sub-issues and every blocked-by link match the task list. When `--blocked-by`
   was unavailable, check the sub-issues only: `/fix-blockers` sets the blocked-by links. Stop at the first
   failure, write back the numbers recorded so far (step 8), and report what exists and what does
   not; do not retry blindly.

8. **Write back.** Put each number in the `Issue:` field of its task in `docs/tasks/<slug>.md`
   (for example `#123`), and remove the `Changed:` line from each task whose issue was updated. Do
   not commit the file unless asked.

9. **Report** the epic, the created, updated, closed and skipped issues with links, and the waves:
   which issues can be picked up now by different engineers and which are blocked by what. Do not
   start implementing. When the list spans several epics, name every epic and put the first in the
   next line. End with this line, as the last line of your output:

   `→ next: /fix-blockers <epic>`

## Stop and ask when

- The PRD and the task list disagree.
- Existing issues for this slug look half-done or conflict with the list.
- Creation fails part-way.

## Improve this skill

Each use of this skill is also a test of it.

- **While working**, note privately any step here that was wrong, outdated, missing, unclear or unnecessary, and anything the user had to explain or correct that this file could have said.
- **Before you finish**, keep only findings backed by what happened in this session that would recur for the next person. Facts about the user's repo go to its `tasks/lessons.md`, not here.
- **If anything is left**, tell the user what happened and ask (AskUserQuestion, headless: `aiw ask`) whether to file it, recommended option first. On yes, resolve `<plugin_repo>` from the `repository` (else `homepage`) field of `<plugin_root>/.claude-plugin/plugin.json`, falling back to `masnun-siam/ai-workflow`, and run `gh issue create --repo <plugin_repo> --title "skill(refine-issues): <what to change>" --body-file <file>` with what happened and the exact proposed edit as a diff.
- **Never edit this skill file**, even when the plugin root is a git checkout. Never propose an edit that weakens a gate.
