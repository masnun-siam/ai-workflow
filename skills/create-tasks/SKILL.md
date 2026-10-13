---
name: create-tasks
description: "Turn an Approved PRD into an ordered task list (docs/tasks/<slug>.md) that covers every requirement, split so several engineers can work in parallel, with an area, files, acceptance criteria, a verify command and dependencies per task, grouped into waves. Use whenever the user says /create-tasks, 'break this PRD into tasks', 'make a task list from this PRD', 'plan the work for this PRD', or wants a task list written before issues are created. Creates no issues: /refine-issues files them from the saved list."
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

# /create-tasks — Approved PRD → saved task list

Produces `docs/tasks/<slug>.md`: tasks small enough to review and verify in one sitting, each
deliverable as one pull request into the repo's base branch, ordered so work can start at the top
and split so several engineers can work at once without editing the same files. The PRD already
decided what is built and how; this skill makes no design decisions.

> **Paths.** This skill runs in the user's repo, not the plugin's. Run `aiw paths` and use its
> `plugin_root` value for `<plugin_root>` below; never guess a path. If `aiw paths` does not print
> JSON whose first key is `plugin_root`, stop and report that the plugin is not installed.

`<skill_dir>` is `<plugin_root>/skills/create-tasks`. **Template:** use the repo's own
`docs/templates/task-list.md` when it exists; otherwise `<skill_dir>/templates/task-list.md`.
"The template" below means the resolved file.

Read the repo's `CLAUDE.md` and the template first. Detect the repo (`gh repo view --json
nameWithOwner`) and its base branch (`gh repo view --json defaultBranchRef`, else `git symbolic-ref
refs/remotes/origin/HEAD`); never assume either.

## Arguments

`/create-tasks <prd-path | slug>`: the PRD the previous step's `→ next:` line named. A slug means
`docs/prds/<slug>.md`. If it is a vault `PRD.md` with a `canonical` property
(`obsidian vault=notes property:read path="<prd>" name=canonical`) naming this repo, read that
repo copy instead: it is the canonical one.

### Asking the user

Headless (your system prompt contains `Headless run: ask via aiw ask`): ask every question below
with one `aiw ask` call per round, passing the JSON through a quoted heredoc
(`aiw ask <<'EOF'` … `EOF`), recommended option first with `(Recommended)` on its label, then end
your turn; the answer arrives as your next message. Otherwise use AskUserQuestion.

### Flow auto mode

When the system prompt contains `Flow auto mode`, this run is the Tasks step of the aiw ui guided
Flow and asks nothing. When the PRD's status is `Draft` and its `## Open questions` is empty, run
the `ai-workflow:create-prd` skill with `approve <prd>` first (starting this step was the user's
approval), then continue. Any other gap in step 2 still stops the run. The list is saved as shown,
under the proposed slug, to `docs/tasks/<slug>.md` only. An existing file with that slug is resumed
only when its `Source PRD:` header line matches this run's PRD; otherwise it is another list, so
save under `<slug>-2` (or the next free number) and say so. Never overwrite either.

## Steps

1. **Read the PRD** at `docs/prds/<slug>.md`. If you were not given a slug, ask which one;
   `docs/prds/` may not exist yet, so list it only if it does. A PRD that exists only on the wiki
   is copied to `docs/prds/<slug>.md` first, after asking; the slug is the file name. List its
   `FR-n` requirements, edge cases, technical design, epics and decisions.

2. **Check it is ready.** Stop and send the user back to `/create-prd` when the PRD is missing, a
   requirement has no acceptance line, `## Open questions` has an entry, or the technical design is
   missing. When its status is not `Approved`, or an epic in `## Epics` still reads `Issue: —`,
   send them to `/create-prd approve <prd>`. If `docs/tasks/<slug>.md` already exists, you are
   updating it: follow "Updating a task list" below.

3. **Ground every requirement in the code.** For each FR find the files and symbols it will touch
   and the closest existing feature to copy: GitNexus when indexed (`gitnexus_query`,
   `gitnexus_context`), otherwise Grep/Glob. Open every path you will cite; note whether another
   service writing the same data also needs changing. Mark every file and every symbol that does
   not exist yet `(new)`, including new methods and constants in existing files. The PRD names no
   files or classes, so this is where they are worked out: follow `CLAUDE.md` and the closest
   existing feature. List the existing files more than one part of the work must edit; these are
   the shared files.

4. **No design decisions here.** Where code goes and what it is called follows `CLAUDE.md` and the
   precedent, and is yours to settle. What the feature does, its data, its API contract and its
   behaviour are the PRD's. When the split shows the PRD is silent or wrong about one of those,
   stop. Ask the user, recommended option first and the reason in the description, record the
   answer with `/create-prd --update <prd> <decision lines>` and only then carry on. The task list
   never holds a decision the PRD does not.

5. **Split into tasks** from the template.
   - One task is one pull request: a layer or a slice a reviewer can hold in their head. Split by
     layer (model, service, endpoint, resource, hook, component) rather than by file.
   - Every task is one layer-scoped deliverable: a DB migration, service logic, an API
     endpoint (its request and resource count as one unit), or one UI unit. Each task
     touches 3 or fewer production files (tests not counted), has 1-4 acceptance
     criteria, has one verify command, and adds no new dependency. If an endpoint unit
     (controller, request, resource, routes) needs more than 3 production files, split it
     by file group (e.g. route+controller, then request+resource) rather than waiving the
     cap. Non-layered work (docs, config) uses the same limits, split by file or section. If any task fails the rubric,
     create nothing and don't ask yet: split the failing task and rebuild the list before
     presenting it.
   - When you cannot say in one sentence what a task delivers, it is two tasks. Do not split below
     the point where the task can be merged alone with the build green and proven by its own test.
   - Split for parallel work. The goal is the widest set of tasks that can be in progress at once
     without two pull requests editing the same file:
     - Put what everything else builds on (schema, shared types, the API contract's route and
       resource) in the smallest possible first tasks, so the rest can fan out behind them.
     - List the shared files under "Shared files" and give each to exactly one task, or order the
       tasks that need it with a dependency. Two tasks that could run at once must not edit the
       same file.
     - Prefer short dependency chains. A task depends only on the tasks it cannot be merged
       without, not on everything listed above it.
     - The PRD fixes the API contract, so a frontend task whose tests mock that contract can run
       at the same time as the backend task behind it.
   - Every FR and edge case lands in at least one task's acceptance criteria. Nothing is added that
     the PRD does not ask for.
   - Each task has an outcome, files and symbols, acceptance criteria, a verify command that proves
     that task alone (the repo's own test command scoped to this task's tests), `Area`,
     `Depends on`, `Parallel` and, when the PRD has more than one epic, its `Epic`.
   - `Area` values come from the repo's top-level layout (for example `backend`/`frontend`), one
     per task. A task that needs two areas is two tasks.
   - Only when the repo is multi-tenant (its `CLAUDE.md` or the code says so), keep data isolation
     in the acceptance criteria of anything that reads or writes that data.
   - Order dependencies-first. `Parallel: yes` marks a task that no task outside its own
     dependency chain shares a file with; otherwise `Parallel: no`. Then group the tasks into
     "Waves": a task is in the first wave in which all its dependencies are in earlier waves.

6. **Check it before showing it.**
   - Does every FR appear in some task? Is any task not traceable to an FR?
   - Is every cited path real, or marked `(new)`?
   - Could a test be written from each acceptance line alone?
   - Does any dependency point downward, or form a cycle?
   - Do two tasks in the same wave touch the same file? Is any dependency there only because of
     list order, not because the task needs it?
   - Is wave 1 wide enough for the team to start together? If one task blocks everything, try to
     make it smaller.
   - Does any task fail the rubric in step 5, or span more than one area?
   - Does anything contradict `CLAUDE.md`?

7. **Save it** as `docs/tasks/<slug>.md` with `Issue: —` on every task, filling the template's
   header with the PRD path, one `Epic: #<n>` line per epic, today's date and the detected repo.
   Local only: no vault or wiki copy. Show the user the path, the task count, the waves broken down
   by area (which tasks can start now, and how many engineers that keeps busy), and any file two
   tasks still share. Do not commit, push or publish it unless asked.

8. **Hand off.** Report the path and the next stage, `/refine-issues`, which creates each task as a
   sub-issue of its epic with its blocked-by links. Do not start it unless asked. End with this
   line, as the last line of your output:

   `→ next: /refine-issues docs/tasks/<slug>.md`

## Updating a task list

A task list is revised when its PRD has a "Change log" line newer than the list, or the user asks.

- Change only the tasks the PRD change affects. Never renumber: issues point at their task by
  number, so a new task takes the next free number and a removed one stays in place marked
  `Dropped` with the reason.
- A changed task that already has an issue keeps its `Issue:` number and gets
  `Changed: YYYY-MM-DD <what changed>`, so `/refine-issues` knows to update that issue.
- Recompute the waves, then show the user what was added, changed and dropped, and which issues
  are affected. Ask before changing a task whose issue is closed or has a pull request open.

## Stop and ask when

- The PRD and the code disagree about what exists today.
- A gap in the PRD changes scope rather than design.
- A requirement cannot be split below one pull request without breaking the build between tasks.

## Improve this skill

Each use of this skill is also a test of it.

- **While working**, note privately any step here that was wrong, outdated, missing, unclear or unnecessary, and anything the user had to explain or correct that this file could have said.
- **Before you finish**, keep only findings backed by what happened in this session that would recur for the next person. Facts about the user's repo go to its `tasks/lessons.md`, not here.
- **If anything is left**, tell the user what happened and ask (AskUserQuestion, headless: `aiw ask`) whether to file it, recommended option first. On yes, resolve `<plugin_repo>` from the `repository` (else `homepage`) field of `<plugin_root>/.claude-plugin/plugin.json`, falling back to `masnun-siam/ai-workflow`, and run `gh issue create --repo <plugin_repo> --title "skill(create-tasks): <what to change>" --body-file <file>` with what happened and the exact proposed edit as a diff.
- **Never edit this skill file**, even when the plugin root is a git checkout. Never propose an edit that weakens a gate.
