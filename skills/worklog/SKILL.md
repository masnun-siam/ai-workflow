---
name: worklog
description: Generate today's (or a given day's) worklog entry from GitHub activity — PRs, commits, and their linked issues — grouped by project and task, and save it into the Obsidian daily note. Use when the user asks for a worklog, daily log, standup entry, or "what did I do today/yesterday".
---

# Worklog

Dispatch to the `worklog-runner` agent, which does the actual work (fetching,
confirming ambiguous items with the user, clustering, and saving to the
Obsidian vault) on Opus at medium effort — this task is bounded judgment over
data `collect.sh` already fetched, not something that needs a larger model.

Invoke the `Agent` tool with `subagent_type: worklog-runner`. The subagent
starts fresh with no memory of this conversation, so the prompt must be
self-contained: pass along the raw date argument exactly as the user typed
it (`$ARGUMENTS`), or state plainly that none was given (defaults to today).
When headless (your own system prompt contains `Headless run: ask via aiw ask`), the
subagent does not inherit it, so also put the line `Headless run: ask via aiw ask` in the
prompt. A subagent cannot end your turn: if its report is `RECORDED q-...` plus a resolved
date, end your turn immediately. When the answer arrives (`Answer to q-...: {...}`),
re-dispatch `worklog-runner` with that resolved date (not `today`), the answer verbatim and
the headless marker, telling it to apply the answer instead of asking again.

Nothing else needs to be included — `worklog-runner`'s own instructions
cover collection, confirmation, clustering, rendering, and saving.

**Otherwise:** not headless, so skip `aiw ask` and the marker; the subagent calls
AskUserQuestion exactly as written.

After the subagent returns, relay its report (the rendered markdown and the
Obsidian link) to the user.
