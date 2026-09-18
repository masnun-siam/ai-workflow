---
description: Fix issues raised in a GitHub PR's review comments, confirming each action
argument-hint: <PR url or owner/repo#123>
allowed-tools: Bash(gh:*), Bash(git:*), Read, Edit, Grep, Glob, AskUserQuestion
---

Given the PR reference `$ARGUMENTS`, work through every review comment and
resolve it — but never fix or reply to anything without explicit user
confirmation first.

## 1. Parse the PR
Accept a full GitHub URL or `owner/repo#123`. Derive `owner`, `repo`, `number`.
If `$ARGUMENTS` is empty, ask for a PR link before doing anything else.

## 2. Fetch every comment
Run both, paginated:
- `gh api repos/{owner}/{repo}/pulls/{number}/comments --paginate` (inline review comments)
- `gh api repos/{owner}/{repo}/issues/{number}/comments --paginate` (top-level PR comments)

For each, keep `id`, `body`, `path`, `line`, `user.login`, `in_reply_to_id`.
Skip comments that are already replies in a thread you're about to reply to
(don't reply to a reply).

## 3. Group into issues
Cluster comments into distinct, actionable issues or categories (e.g. all
"missing null check" comments across files can be one category). Trivial or
non-actionable comments (a "LGTM", a question already answered) get noted but
not treated as fixable issues.

## 4. Present the full list first
Show the user every issue/category found, each with: source comment(s),
file/line, and your proposed action — "Fix: ..." or "No change needed
because: ...". Do this before touching any code.

## 5. Confirm before every action
For each issue or category, use `AskUserQuestion` with options like:
- Fix as proposed
- Skip (no fix, no reply)
- Reply only (explain why, no code change)
- Let me describe a different fix

Never batch-apply without asking. Never skip the ask because an issue "looks
obvious" or "the same as the last one."

## 6. Apply, commit, reply, resolve — per confirmed issue
If fixing:
1. Make the minimal edit for the root cause (no unrelated refactors).
2. Run the project's tests/lint if available; don't proceed if they fail.
3. Commit the fix and capture its SHA (one commit per issue, so each thread's
   reply points at its own fix):
   `git commit -m "..."` then `SHA=$(git rev-parse --short HEAD)`.
   Never use `--no-verify`.
4. Reply on the thread, including the commit SHA:
   - Inline comment: `gh api repos/{owner}/{repo}/pulls/{number}/comments/{comment_id}/replies -f body="Fixed in {SHA}: ..."`
   - Top-level comment: `gh pr comment {number} --body "Fixed in {SHA}: ..."`

If reply-only (no fix): reply with the reason (not applicable, already
handled elsewhere, disagree because X, etc.) — no SHA, never a bare "skipped."

## 7. Auto-resolve the thread
After replying to an inline review comment — regardless of whether it was
fixed, or replied-only with a reason for not fixing — resolve its review
thread (top-level PR comments have no thread to resolve, skip those). This
requires the thread's GraphQL node ID, not the REST comment id:

1. Get the thread ID:
   `gh api graphql -f query='query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$number){reviewThreads(first:100){nodes{id isResolved comments(first:1){nodes{databaseId}}}}}}}' -f owner={owner} -f repo={repo} -F number={number}`
   Match on `comments.nodes[0].databaseId` == the comment id you just replied to.
2. Resolve it:
   `gh api graphql -f query='mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}' -f id={threadId}`

Do this automatically as part of step 6 for every issue that got a reply — no
separate confirmation needed, since resolving follows directly from an action
already approved. Skip resolving only for the "Skip (no fix, no reply)"
choice, since nothing was posted there.

## 8. Push
After every confirmed issue has been handled (all commits made, replies
posted, threads resolved), push the branch once: `git push`. Commit SHAs
referenced in replies stay valid across the push, so this must happen last,
not per-issue.

## Rules
- Never use `--no-verify` or bypass hooks/checks.
- No raw SQL, no hardcoded secrets, no disabled security headers — same rules
  as any other change.
- If a fix would take >3 iterations to get right, stop and flag it to the
  user instead of continuing to guess.

## Wrap-up
After all issues are handled, summarize: what was fixed, what was skipped
(and why), what got a reply-only.
