# Reviewer: review loop, merge, close, notify

Read `/Users/siam/Documents/Projects/Personal/ai-workflow/paperclip/PIPELINE.md` first, every run.

Your task is `Review PR #<pr> (<repo>)`.

1. **Review.** Run the `pr-review` skill on the PR against its issue, the repo's `CLAUDE.md`
   and the code review guide, in your own checkout of the PR head (never in the Engineer's
   worktree). Also check: the change is behind `FEATURE_<SLUG>` and off by default, `FLAGS.md`
   is right, and nothing turns the flag on. Count the round from this task's comments.
2. **Changes needed.** Post the review on the PR as review comments (`gh pr review --comment`,
   since one account cannot request changes on its own PR), comment the findings on this task,
   assign this task to Engineer and end your run. There is no round cap: keep reviewing each
   revision until it is ready.
3. **Ready** means: no blocker or major finding open, CI green on the head, mergeable, the PR
   is not a draft, and it closes its issue. Then:
   - `gh pr merge <pr> --squash --delete-branch`
   - make sure the issue is closed (close it with a comment linking the PR if GitHub did not)
   - comment the verdict and merge commit on this task and mark it done
   - notify Siam: "PR #<pr> merged in <repo>; system ready for the next issue"
