# Skills: how they are written and how they improve

A skill is a short procedure an AI agent loads for one kind of task. The skills of this plugin live in `skills/<name>/SKILL.md` and are invoked as `/ai-workflow:<name>`. Shared guides live in `guides/` and templates in `templates/`, both at the plugin root.

| Skill | Use it to |
|---|---|
| `/create-prd` | Turn a feature idea into a PRD with its technical design and no open questions, and create its epic on approval |
| `/create-tasks` | Split an approved PRD into small parallel tasks and create them as child issues of the epic, with blocked-by links |
| `/refine-issues` | Write WHAT, WHY and HOW into each issue so it can be implemented without asking anything |
| `/implement-issue` | Implement a refined issue (or the next Ready one of an epic) in its own worktree through to a ready PR into the base branch, then close it and clean up after the merge |
| `/verifier-locally` | Prove a change passes every relevant check before it is pushed |
| `/pr-review` | Review a pull request or a local branch against its issue and the project rules; with `--fix`, fix the review feedback on a pull request through to green CI, replies and ready |
| `/skill-feedback` | Turn feedback on a skill, guide or the process into approved edits; `reconcile` mines the learning logs of closed PRs and their issues for improvements |
| `/docs-updater` | Bring the repo's `docs/` in line with the code |
| `/sync-from-wasensi` | Maintain this plugin: port Wasensi's latest skill, guide and template changes in repo-agnostic form |

## What belongs in a skill

- When to use it, the steps in order, where to stop and ask, and what to report at the end.
- Pointers to the real thing: a guide, a template, a file in the codebase that sets the pattern.
- The commands the procedure runs.

What does not belong: code samples, framework tutorials, conventions copied from a guide, or anything specific to one repository. Repo knowledge lives in that repo's `CLAUDE.md`, `AGENTS.md`, `docs/` and code, where everyone reads the same copy; a skill that restates it goes stale. If a skill passes roughly 100 lines, move the detail into a guide and link it.

A skill never overrides the repo's `CLAUDE.md` or `AGENTS.md`. If they disagree, the repo file wins and the skill is the thing to fix. Within this plugin, a skill wins over a guide or template that disagrees with it, and the guide or template is fixed to match.

## The improvement loop

Skills that end with an "Improve this skill" section run a closed loop: each use of the skill is also a test of it, and what the test finds goes back into the skill, with a human approving every change.

**1. Notice, while working.** Keep a private note whenever the procedure causes friction:

- a step that was wrong, outdated, missing or in the wrong order
- a command, path, label or tool that no longer exists or behaves differently
- something the user had to explain or correct that the skill could have said
- a question the skill made you ask that the repository could have answered
- a step that added nothing and could be removed
- a check that would have caught a mistake earlier

**2. Filter, when the task is done.** Keep only findings that are backed by something that happened in this session, that would recur for the next person, and that hold for any repository. Drop one-off circumstances, personal preferences and anything about one codebase rather than the procedure (that goes to the repo's `tasks/lessons.md` or docs, see [`engineering-workflow.md`](engineering-workflow.md#lessons)).

**3. Propose, in the same session.** If anything is left, tell the user what happened and show the exact edit: the lines to add, change or remove. Ask with `AskUserQuestion`, recommended option first. If nothing is left, say nothing; do not invent improvements.

**4. Apply, on approval.** Edit the skill in the plugin's source repository, `~/Documents/Projects/Personal/ai-workflow`, never in the installed plugin cache and never in the project being worked on. If that folder does not exist on this machine, ask the user where the source is. Keep the skill short and free of code samples. Commit the change on its own there as `chore: update /<name> skill - <what changed>`.

**5. Never.** Do not edit a skill without approval. Do not use a skill edit to weaken a gate, widen scope or contradict a repo's `CLAUDE.md` or `AGENTS.md`. Do not edit a repo's `CLAUDE.md` or `AGENTS.md` through this loop; changes there need an explicit human request.

If the user declines a proposal, drop it for the session. If the same finding comes up again in a later session, it is fair to raise it again with the new evidence.
