---
name: refine-issues
description: Refine the child issues of an epic (or single issues) so each one carries all the context needed to implement it - a WHAT, WHY and HOW written into the issue body from the PRD, the code and the repo documentation. Takes an epic number or issue numbers as its argument. Use when asked to refine issues, prepare an epic for implementation, or write WHAT/WHY/HOW into issues.
argument-hint: <epic number | issue numbers>
---

# Refine issues

Input: an epic number, or one or more issue numbers. Output: every issue's body rewritten with a WHAT, WHY and HOW that holds all the context an AI agent needs to implement it and open a pull request, without asking anyone or searching for what was already known. `/create-tasks` creates the issues; this skill fills them.

The PRD is the source of truth. A refined issue explains and applies the PRD; it never decides something the PRD does not.

Paths below starting `../../` are relative to this skill's folder, at the plugin root. Read first: `../../guides/engineering-workflow.md` ("Repository settings" and "Refined issues") and the template `../../templates/issue.md`.

## Steps

1. **Load the work.** For an epic, list its child issues (`gh issue view <epic> --json subIssues`). For each issue read the body, comments, parent and blocked-by links (`gh issue view <n> --json body,comments,parent,blockedBy,blocking`). Find the PRD path in the epic or issue body and read the PRD. Skip closed issues and issues with an open pull request; say which.

2. **Gather the context for each issue.**
   - The PRD requirements and decisions this issue covers, and anything else in the PRD that affects it.
   - The code it touches, with GitNexus (`query`, `context`, `impact`) when its index is available, otherwise by reading the code and searching for callers: the files and symbols to change or add, their callers, the closest existing feature that does something similar, and the tests nearby.
   - Any repo documentation relevant to the area, and the rules in the repo's `CLAUDE.md` or `AGENTS.md` that apply (for example data isolation).
   - What its blockers will deliver that it builds on, and what the issues it blocks expect from it.
   - Open every file you will cite, so every path and symbol in the issue is real or clearly marked as new.

3. **Resolve gaps before writing.** If the PRD, the code or another issue leaves something undecided or contradictory, ask the user with `AskUserQuestion`: recommended option first, with the reason. Write the answer into the PRD file and use it in the issue. Never leave a question for the implementer.

4. **Write the issue body** from the template, so it stands alone:
   - **WHAT**: the outcome in one or two sentences, the acceptance criteria as testable statements, and what is out of scope for this issue.
   - **WHY**: the problem it solves for the user, and the PRD requirements it covers, quoted, with the PRD path.
   - **HOW**: the files and symbols to change or create; the existing code to follow as precedent; the data, API contract and behaviour from the PRD it must match, quoted; edge cases and data isolation where it applies; the tests to write; how to verify it locally, including the commands and, for user-facing changes, what to check in the running app; and what it depends on from its blockers.
   - Keep anything a person already wrote in the body that is still true. Link related issues by number.

5. **Check each draft.** Could an agent implement it from the body alone? Is every acceptance criterion testable? Is every cited path real or marked new? Does anything contradict the PRD, the repo's `CLAUDE.md` or `AGENTS.md`, or another issue in the epic? Is the issue still small enough for one pull request; if not, tell the user and propose a split.

6. **Show the user the drafts** and ask with `AskUserQuestion` whether to update the issues, adjust, or stop; recommended option first. Edit nothing on GitHub without a yes.

7. **Update the issues** with `gh issue edit <n> --body-file <file>`. Keep the parent, blocked-by links and labels as they are, and add the `refined` label. If refining showed a blocked-by link is missing or wrong, fix it and say so.

8. **Report and hand off.** List the refined issues, which can start now, and any change made to the PRD or links. The next step is `/implement-issue <issue number>`. Do not start it unless asked.
