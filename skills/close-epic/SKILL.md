---
name: close-epic
description: Verify that an epic is really finished, then set its PRD to Done and close the epic. Stops and lists the gaps when a child issue is still open or a PRD requirement is not shipped, runs the local checks on the base branch, and never closes children for you. Use when asked to close, finish or wrap up an epic, or to mark a PRD done.
argument-hint: <epic: owner/repo#N or N> [--dry-run]
---

# Close an epic

Input: an epic number (`N` or `owner/repo#N`). Output: the PRD at `Status: Done` and the epic closed as completed, or a list of what is missing. It verifies and never forces: it does not close, edit or reopen child issues.

Paths below starting `../../` are relative to this skill's folder, at the plugin root. Read first: `../../guides/engineering-workflow.md` ("Repository settings" to resolve the base branch and which skills win, "PRDs" and "GitHub: project, epics and dependencies").

With `--dry-run`, change nothing: run every check, and for each step that would write (the Status commit, the epic close) print what it would do instead.

## Steps

1. **Resolve the epic and its PRD.** `gh issue view <epic> --json number,title,state,labels,body,subIssues`. Stop if it is not labelled `epic` or is already closed. The PRD path is the `Source PRD:` line of the epic body. If there is none, or the file is missing on the base branch, there is no PRD: skip steps 3 and 5's Status edit, and say so.

2. **Check the children.** List `subIssues`. Any still open is a gap; list each with its number and title.

3. **Check the requirements.** Read the PRD from the base branch and list its `FR-n`. Each `FR-n` must be cited (in the body, normally WHY) by at least one closed child, and that child must be closed by a merged PR: `gh pr list --state merged --search "<child> in:body" --json number,baseRefName,body` and keep the PR whose body has `Closes #<child>`. A PR into a base branch that is not the default branch does not auto-close its issue, and a child may be closed by a different PR than its own: accept any merged PR that closes it. An `FR-n` with no such child is a gap. A requirement the epic does not cover (the PRD says another epic has it) is not a gap.

4. **Stop on gaps.** Print every gap from steps 2 and 3, grouped, and end. Do not go on to the checks.

5. **Verify.** Fetch, make sure the checkout is `origin/<base>` (use a throwaway worktree if the main checkout is elsewhere) and run `/verifier-locally` (see "Repo skills win") there. If it reports any failure, print the failures and stop.

6. **Mark done and close.** Set the PRD's `**Status:**` to `Done` and commit it to the base branch in the epic's repo as `docs(prd): mark <slug> done`, then `gh issue close <epic> --reason completed --comment "All requirements shipped and verified on <base>."`. This is the one write to the base branch this plugin allows an agent, and only for that line. If the base branch rejects the push (protected), open a one-line PR instead and say the epic stays open until it merges. Move the epic to Done on its board with `../implement-issue/set-status.sh <epic> "Done"`; on failure carry on and say so.

7. **Report** each check and its result, the gaps or failures, and what was written (or, with `--dry-run`, would have been).
