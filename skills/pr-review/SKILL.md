---
name: pr-review
description: Review a pull request, or a local branch before it is pushed, against its issue, the repo's CLAUDE.md or AGENTS.md rules and the code review guide, and report evidence-backed findings with a verdict. With --fix, fix the review feedback already on a pull request instead, from people or AI reviewers, through to green CI, replies and ready. Use when asked to review a PR, a branch, a commit range or a diff, or to fix or address the review comments on a PR.
argument-hint: <PR number | branch | commit range> [--fix]
---

# PR review

A strict review that a maintainer can act on without redoing it. The reviewer reads and runs checks; it does not change the branch under review, except in fix mode below.

Paths below starting `../../` are relative to this skill's folder, at the plugin root. Read first: `../../guides/engineering-workflow.md` ("Repository settings" to resolve the base branch and which guide and skills win) and the code review guide (the repo's own if it has one, else `../../guides/code-review.md`). The guide holds the checklist, the severity levels and the report format. Follow it; this file is the order of work.

## Input

One of: a PR number, a branch name, or a commit range. A PR number followed by `--fix` (or `-fix`) runs fix mode instead of a review. For a local branch the default range is `origin/<base>..HEAD`. Review committed work only. For a local branch with uncommitted changes, say so and ask whether to wait; for a PR number, local leftovers do not matter.

## Steps

1. **Gather.** The diff and commit list, the PR title and body, the linked issue with its acceptance criteria, existing review comments, and the state of CI on the head commit. No linked issue is already a finding; a PR into a base branch that is not the default branch gets no GitHub closing-issue link, so look for `Closes #N` in the body, not `closingIssuesReferences`. For a PR number, if CI on the head commit is failing or still running, stop with verdict `Blocked`: red CI is not finished work, so review it after it is green. A local branch before its push (`/implement-issue` step 12) has no CI yet: the `/verifier-locally` results stand in for it.

2. **Read the context, not just the hunks.** Open each changed file in full, the tests, and the callers of every changed symbol (GitNexus helps when its index is available). Open the repo's docs for each area touched, and the rules in its `CLAUDE.md` or `AGENTS.md`.

3. **Walk the checklist** in the code review guide, every section, in order. For acceptance criteria, find the code and the test for each one; "not covered" is a finding.

4. **Verify claims by running things.** Where the PR says something works, check it: run the relevant tests and checks from `/verifier-locally` (see "Repo skills win") on the PR's head, in a separate git worktree so the user's checkout is untouched. When CI is green on that same head commit, its job log (`gh run view <run> --job <job> --log`) can stand in for a slow local run, but confirm the new tests appear as passed, not skipped. When the repo-wide lint or static-analysis target also fails on files the PR did not touch, run those checks on the changed files only, and do not report the untouched failures as findings. When the PR depends on another open PR, check the commands, targets or symbols it relies on against that PR's head, in a separate worktree. When build files or tooling scripts change, run their tests and a linter on the changed scripts, then break each changed script line once (for example, make a reported miss stop counting) and confirm a test fails, since a green suite alone does not show the new test checks anything (a mutation that survives because the line is redundant is equivalent: say so, not a test gap; first confirm the break actually applied, for example by searching for the changed text, since a no-op edit also stays green), and check that any hook or CI job that runs them covers every new script. To check that a test fails without the line it guards, change the line in a scratch copy of the code (dependencies symlinked) and run that one test file, never in the PR's worktree. With symlinked dependencies, run the tools directly from their bin folder (for example `./node_modules/.bin/`), not through a package runner, which can run an install into the shared folder and break the other worktree. After browser checks, delete only the browser-tool output your session created (for example `.playwright-mcp/` files) in the main checkout; a parallel session may be using that folder. When a check starts background processes, record their PIDs (`$!`, `pgrep -P`) and kill only PIDs you confirmed are your own by checking each one's command; never kill a computed PID list unchecked, never PID 0, never `pkill` by name. For a pull request that changes only skills or guides, verify by reading: check every command, path, symbol and step reference it names against the base, and compare it with the other skills and guides that cover the same step; no worktree or process is needed. A claim you could not verify goes under open questions, not under findings.

5. **Challenge your own findings.** Before reporting anything Critical or Major, try to disprove it by rereading the surrounding code or running a test. Drop or downgrade what does not hold. Do not pad the list with nits.

6. **Report** in the format from the guide: verdict, numbered findings with severity, `path:line`, evidence and resolution, acceptance-criteria coverage, open questions, what is solid, and the checks you ran with their results.

7. **Posting is opt-in.** Give the review to the user in the session. Post it to GitHub only when the user asks, and then as review comments. Check earlier comments first so the same finding is not posted twice. Never approve, merge or close a PR on GitHub.

8. **On a re-review**, start from the previous findings: confirm each is resolved by looking at the new code, then review what changed since. When the branch merged in its base since the last review, review the PR's own commits by range (previous head to the commit before the merge, then the merge to the new head), not `merge^1..head`, which includes the base's commits, and confirm the merge left the PR's per-file changes intact.

## Fix mode (`--fix`)

For a session that addresses the feedback already on a pull request: every unresolved review comment, thread and conversation comment, from people and AI reviewers. Fix by default; do not ask per comment. Follow `/implement-issue` for everything below that it covers.

1. **Gather.** The PR, its linked issue and every unresolved comment: `gh pr view <pr> --json body,comments,reviews,isDraft,headRefName` for conversation comments and review bodies, and `gh api graphql` on the pull request's `reviewThreads` for inline threads, whose `isResolved` tells which are still open (the REST comments endpoint does not). A conversation comment or review body is handled once a later reply answers it. Note the start time.
2. **Work on the PR's branch.** If `git worktree list` shows a worktree on that branch, work there, unless another session may still be using it: then ask. Otherwise check the branch out in a new worktree under `.worktrees/` and prepare it as `/implement-issue` step 3 says.
3. **Validate each concern before changing code.** Reproduce it (a failing test, a run, or a regenerated output such as a generated API spec), or prove it from the code. A concern that does not hold gets a reply with the evidence instead of a change. One that needs a product decision goes to the user with `AskUserQuestion`; one outside the PR's scope becomes a follow-up issue (`/implement-issue` step 8).
4. **Fix** what holds, following `/implement-issue` steps 4 to 11: impact analysis, the fix, tests that fail without it, docs, `/verifier-locally` (see "Repo skills win"), the running app where a user can see it, small commits.
5. **Review again, push, get CI green.** `/implement-issue` steps 12 to 14: a re-review of the new commits on the local branch with this skill (review mode) and fixes for its Critical and Major findings, then the latest `origin/<base>` merged in, one push, and green CI with the new tests seen passing.
6. **Reply to every comment** only after the fix is pushed and CI is green: what changed and in which commit, or why not with the evidence.
7. **Mark it ready** if it is a draft (`gh pr ready <pr>`) and move the issue to In review, as `/implement-issue` step 14 says. Never merge it.
8. **Log learnings and report** as `/implement-issue` steps 15 and 16 say, including the 50-minute rule, plus each comment and what was done with it.

## Stop and ask when

- The PR targets the production branch, or mixes several unrelated issues.
- The diff is too large to review properly in one pass. Propose how to split the review.
- Reviewing would require credentials, production access or real customer data.

## Improve this skill

Each use of this skill is also a test of it. Full rules: `../../guides/skills.md`.

- **While working**, note privately any step here that was wrong, outdated, missing, unclear or unnecessary, any checklist item that missed a real defect or kept producing noise, and anything the user had to explain or correct that this file could have said.
- **Before you finish**, keep only findings backed by what happened in this session that would recur for the next person in any repository. Facts about one codebase go to its `tasks/lessons.md` or docs, not here. A missing checklist item belongs in `../../guides/code-review.md`; propose that edit the same way.
- **If anything is left**, tell the user what happened and propose the exact edit with `AskUserQuestion`, recommended option first; when running as a subagent, put the proposed edits at the end of the report instead. If nothing is left, say nothing.
- **On approval**, apply the edit in the plugin's source repository as `../../guides/skills.md` describes, keep the file short and free of code samples, and commit it on its own as `chore: update /pr-review skill - <what changed>`.
- **Never** edit this file without approval, and never use an edit to weaken a gate or contradict a repo's `CLAUDE.md` or `AGENTS.md`.
