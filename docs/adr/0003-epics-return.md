Decision: `/gh-issue` again files a parent epic over its refined task issues, and GitHub's native blocked-by relations are written between those issues. This supersedes, in part, `docs/prds/gh-issue-flat-task-list.md`: its problem statement (line 16, the parent/child hierarchy "adds machinery … that the user no longer wants"), its goal "No parent issues and no hierarchy" (line 25), and its decision "No parent and no hierarchy: flat issues only" (line 94). The rest of that PRD stands: the saved, ordered task list, small layer-scoped tasks, and one refined issue per task.

## Context

The flat-only rule came in 1.9.0 (CHANGELOG). The user now wants a six-step chain: dump → prd → create-tasks → gh-issue → fix-blockers → run-issue. Step 4 files one refined issue per task under a parent epic. The parent's body holds the problem statement, the task list and links to every child. Step 5 sets blocked-by between the children, so an issue whose dependency is not merged yet is visibly blocked on GitHub.

The epic machinery was never removed (that PRD's non-goals kept it working for open epics): `aiw epic split` (`run-engine/epic.py`, sub_issues links plus the dependency-graph and cycle check), `/run-issue` Epic mode, and herdr-dispatch's expansion of a parent into its children.

## Rules

- **Reuse, don't rebuild.** Parent/child links go through `aiw epic split`. No second epic implementation.
- **An epic from birth.** `/gh-issue` links the children as sub-issues as soon as it creates the parent. `/run-issue` and herdr-dispatch detect an epic only by its sub-issues. A parent labelled `epic` that has no sub-issues must never run as an ordinary issue.
- **One source of dependencies.** The `Depends on: #n` lines in each child's body are the source of truth. Native blocked-by relations are derived from those lines and never edited on their own. A re-run writes only the missing relations. A relation on GitHub with no matching body line is reported, never deleted.
- **Both run paths stay.** An epic can run through herdr-dispatch of its children (one tab each, in dependency order) or through `/run-issue <parent>` Epic mode (one session).
- **Layer order is an example.** The migration → model → service → controller order in the task breakdown is an example for Laravel-style stacks, not a rule.

## Consequences

- The "no epics" statements in `skills/flow/SKILL.md` and `commands/run-issue.md` are removed by the change that brings the parent back.
- Writes to GitHub from the new steps (issues, sub-issue links, blocked-by) need a preview and a confirmation, and must be safe to re-run after a crash.
