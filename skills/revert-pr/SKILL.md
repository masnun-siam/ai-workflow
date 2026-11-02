---
name: revert-pr
description: Revert a bad merge - open a revert PR into the original base branch, file the finding as an issue, and reopen the child issue the PR closed. Stops with one line if the PR is not merged or was already reverted, and leaves nothing pushed if the revert conflicts. Use when asked to revert, roll back or undo a merged PR, or after a merge broke something.
argument-hint: <pr url or number> [--dry-run]
---

# Revert a PR

Input: a merged PR (number or URL) and, from the user, the evidence of what broke. Output: a revert PR into the PR's base branch, a finding issue, and the child issue reopened. It opens the revert PR as ready and never merges it; it reverts only, and the fix goes through the normal flow from the finding.

Paths below starting `../../` are relative to this skill's folder, at the plugin root. Read first: `../../guides/engineering-workflow.md` ("Repository settings" for which skills win, "Branches, commits and pull requests").

With `--dry-run`, change nothing: run every read and check, and for each step that would write (branch, push, PR, issue, comment, reopen) print what it would do instead.

## Steps

1. **Resolve and check the PR.** `gh pr view <pr> --json number,title,url,state,mergedAt,mergeCommit,baseRefName,closingIssuesReferences`. Stop with one line if `mergedAt` is empty (not merged). Stop with one line if a PR titled `Revert "<title>"` already exists (`gh pr list --state all --search 'in:title Revert "<title>"' --json number,title,url`, exact title match). Note the merge commit's parent count (`git rev-list --parents -n1 <sha>`): two parents is a merge commit (`git revert -m 1`), one is a squash or rebase merge (plain `git revert`).

2. **Get the evidence.** Ask the user with `AskUserQuestion` what broke and how it shows (commands, output, link), unless the invocation already gave it. File nothing without it.

3. **Revert in a worktree.** Fetch, then `git worktree add -b revert-pr-<pr> .worktrees/revert-<pr> origin/<base>` (the PR's own base, which may not be the default branch). In it, run the revert from step 1. On a conflict, list the files (`git diff --name-only --diff-filter=U`), `git revert --abort`, remove the worktree and branch, report the files and stop: nothing has been pushed. A PR merged earlier than later work that touches the same lines is the usual cause; tell the user it needs a manual revert.

4. **Open the revert PR.** Push the branch, then `gh pr create --base <base> --title 'Revert "<title>"'` with a body that links the original PR, says why it is reverted (the evidence) and carries `Refs #<finding>` once step 5 has a number (edit the body after). Open it ready, not draft, and do not merge it.

5. **File the finding.** Run `/create-tasks` in single-issue mode ("A finding from other work"; see "Repo skills win") with the evidence, the link to the original PR and the revert PR. Comment its number on the original issue.

6. **Reopen the child issue.** For each issue in `closingIssuesReferences`: if it is still closed, `gh issue reopen <n> --comment "Reverted in #<revert pr>; finding in #<finding>."` and move it back with `../implement-issue/set-status.sh <n> "Backlog"` (on failure carry on and say so). If another PR closed the issue, or it is already open, say so and leave it.

7. **Report** the revert PR link, the finding, the reopened issues, and anything not done (or, with `--dry-run`, what would have been done).
