---
description: Start issue-URL-to-PR workflow (context → interview → plan → todo → execute → commit → push → PR)
argument-hint: "<issue-url>"
---
You are running the issue-to-pr workflow.

Issue URL:
$ARGUMENTS

Process (strict order):
1) Fetch issue details from the URL (title, description, acceptance criteria, labels, linked tasks).
2) Gather context:
   - Fetch issue details and comments via `gh issue view <number> --comments --json title,body,labels,comments`.
   - Use GitNexus (`gitnexus_query`, `gitnexus_context`) to explore the codebase — find execution flows, affected symbols, and related files.
   - Read AGENTS.md / CLAUDE.md + project docs + tasks/lessons.md.
   - Check recent git history for related changes.
   - If the project has Jira/Confluence/Slack MCP, query linked context.
3) Interview me for missing constraints/acceptance criteria (focused questions).
4) Produce an implementation plan (numbered steps, risks, rollback).
5) Produce an executable todo checklist.
6) Before editing any file, run `gitnexus_impact` (downstream, depth=2) on affected symbols to check blast radius — verify no unexpected dependents will break.
7) Execute todos one-by-one with progress updates.
8) Run verification (lint/tests/typecheck as applicable).
9) STOP — manual E2E checkpoint. Tell me the issue scope is implemented and ready for my
   manual E2E test and local code review, then wait for my reply. Do not commit anything.
   - If I give feedback: resolve it, re-run verification, then STOP again and re-invite
     testing. Repeat until I reply "continue" with no feedback.
   - If I reply "continue" with no feedback: go to step 10.
10) Ask me whether to proceed with commit → push → PR. If I say no, stop and leave the
    changes uncommitted.
11) Commit with a clear message.
12) Push the branch.
13) Choose the PR base branch before creating the PR:
    - List remote branches with `git ls-remote --heads origin`.
    - Offer, via AskUserQuestion, only those of `master`, `staging`, and the current branch
      (`git branch --show-current`) that exist on the remote, plus a free-text option for
      anything else.
    - If the chosen base equals the PR's head branch, that PR is invalid — say so and ask
      again.
    Then create the PR with `gh pr create --base <chosen-branch> --body-file <file>`.
    The body MUST contain a closing keyword on its own line:
    `Closes #<issue-number>` (use `Closes owner/repo#<issue-number>` if the issue lives in
    a different repo). Do not use non-linking phrasing like "Related to" or a bare URL —
    those do not close the issue on merge.
    Write the body to a file and pass it with `gh pr create --body-file`, so the keyword
    survives verbatim (`--fill` would overwrite it with commit messages).
14) Verify the link: `gh pr view <pr> --json closingIssuesReferences`. If the array is
    empty, the issue is NOT linked — fix the PR body with `gh pr edit --body-file` and
    re-check. Do not report the PR as done until it is non-empty.

Rules:
- Do not skip interview/plan/todo.
- If ambiguity remains, stop and ask before coding.
- If tests fail, fix before commit.
- Never commit before I have confirmed the E2E checkpoint AND approved the PR step.
- A PR is not done until `closingIssuesReferences` on it is non-empty.
- Never create a PR without an explicitly chosen base branch — do not rely on the gh default.
