# Self-improve protocol

A skill whose SKILL.md ends with a `## Self-improve` pointer follows this file, so it gets
better through real use, and only with the user's approval. Runs that nobody is watching
never stop to ask: they log what they find for later.

## 1. During the task: collect, don't interrupt

Keep a private list of improvement candidates. A candidate is something that would have
made this run better if the skill had said it up front:
- a step that was wrong, outdated or failed as written (wrong path, flag, command)
- a step that was missing, so you had to work it out
- an ambiguity you had to resolve by guessing or asking
- a correction or preference the user gave you
- a manual action you repeated that the skill could have scripted

These are not candidates: one-off facts about this particular task, style nitpicks, and
anything you can't point to evidence for in this run.

Never stop the task to discuss candidates. Finish the user's work first.

## 2. After the task: ask or log

If the list is empty, say nothing and stop.

**Unattended:** the run is headless (your system prompt contains `Headless run: ask via aiw
ask`), runs inside `/run-issue`, `/pr-grind` or `/flow`, or was dispatched by herdr. Do not
ask: this would add a gate, and those flows stop for a human only at their fixed gates.
Append the candidates to `~/.claude/skills/_shared/pending-improvements.md`, one block per
run under a heading `## <skill> · <YYYY-MM-DD>`, using the label and description format
below. Then stop.

**Subagent:** you cannot ask the user. End your final report with a `## Skill improvement
candidates` section in the format below. The main session then applies step 2 to them,
asking if it is attended and logging if it is not.

**Attended:** call AskUserQuestion once:
- header: `Skill update`
- multiSelect: true
- one option per candidate, at most 4 (merge candidates or drop the weakest beyond that)
- label: the change in 5 words or fewer
- description: what went wrong in this run, plus the exact line(s) you would add or change

If the user picks none, drop the candidates and stop. Don't ask again.

## 3. Apply the approved changes

1. Resolve the real source file. An edit made anywhere else gets wiped:
   - an ai-workflow skill: edit it under `~/Documents/Projects/Personal/ai-workflow/skills/`,
     never under `~/.claude/plugins/cache/`
   - a `~/.claude/skills/<name>` that is a symlink: edit the `readlink` target
   - a third-party plugin or skill (gstack, superpowers, mattpocock, ponytail, engram, …):
     don't edit it. Tell the user the change would be overwritten on the next upgrade.
2. If the file is not in a git repo, back it up first:
   `cp <file> ~/.claude/skills/_shared/backups/<name>-$(date +%Y%m%d-%H%M%S).md`
3. Edit with the Edit tool, following these rules:
   - add or tighten. Never delete or rewrite an existing instruction unless the user
     explicitly approved that removal.
   - put each change in the section it belongs to, not in a changelog at the bottom
   - keep each change to a few lines, in the skill's own voice and formatting
   - never touch the frontmatter `name`. Edit `description` only if the user approved it.
4. Show the diff in one short block (`git diff <file>`, or `diff <backup> <file>`).
5. For an ai-workflow edit: don't commit. Tell the user the change is uncommitted, and that
   the installed copy picks it up only after the plugin is updated.
