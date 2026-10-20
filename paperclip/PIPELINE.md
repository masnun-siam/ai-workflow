# Personal Projects pipeline (Paperclip)

Shared rules for every agent in the Paperclip company "Personal Projects". Your own `AGENTS.md`
says which stage you own. Read this file in full on every run.

## The owner

Siam is the board. Siam is available for only three things:

1. **Requirements**: Siam creates a task assigned to PM with a feature request or a project idea.
2. **Release confirmation**: Siam confirms what a release will enable before it happens.
3. **Emergencies**: only (a) a credential, secret, account or paid service is needed, or
   (b) the PRD panel cannot agree on a decision after 2 rounds.

Everything else is decided by the agents. Never wait on Siam for anything outside that list.

## Asking Siam

Run headless: there is no terminal and `AskUserQuestion` does not exist. When an emergency
above applies, create an `ask_user_questions` interaction on the Paperclip task with
`resolverPolicy: human_only` (each question: options with a recommended one first and the
reason), set the task to `blocked`, then end your run. Siam's answer wakes you.
For anything else an ai-workflow skill says to ask the user, decide yourself: take the
recommended option, the PRD's intent and the repo's own conventions, and write the decision and
its reason as a comment on the task.

## Using the ai-workflow skills

The ai-workflow skills (create-prd, create-tasks, refine-issues, implement-issue,
verifier-locally, pr-review, peer-review) are attached as Paperclip skills. They were written
for an interactive session, so apply these overrides; where a skill disagrees with this file,
this file wins.

- **Paths.** A skill's `../../guides/<x>` and `../../templates/<x>` are
  `/Users/siam/Documents/Projects/Personal/ai-workflow/guides/<x>` and `.../templates/<x>`.
  `agents/peer-reviewer.md` is in the same repo.
- **Branches.** The base branch and the production branch are both `main` (the GitHub default
  branch if a repo uses another name). There is no staging branch. PRs go into `main`.
- **Feature flags.** Every user-visible change ships behind an env-var flag named
  `FEATURE_<SLUG>` (upper snake case of the PRD slug), default **off**. Code reads it from the
  environment; when off, behaviour is exactly as before. The repo keeps a `FLAGS.md` table:
  flag, PRD, epic, default, status (`off`, `released <tag>`). Merging deploys the code dark;
  only a release turns a flag on.
- **Not used here:** Slack, herdr, `/pr-grind`, `/release-pr`, the run-engine UI, staging.
- **Confirmations.** Where a skill says "show the user and ask before creating/editing", do it
  without asking, and put what you did in a task comment.
- **Skill improvement.** Where a skill's "Improve this skill" step would propose an edit, post
  the exact proposed edit as a comment on the task, starting `Skill proposal:`, then carry on.
  Do not edit or commit the skill yourself.

## Repos and projects

- Repos live under `/Users/siam/Documents/Projects/Personal/<repo>`, on GitHub as
  `masnun-siam/<repo>`. A new project's repo is **private**.
- Each repo has one Paperclip project with the same name and its local path as the workspace.
- GitHub is the source of truth for epics, issues, blocked-by links and PRs. Paperclip tasks
  track which agent is on which stage and hold the PRD while it is being written.
- `gh` is logged in as `masnun-siam`. Never force-push to `main`, never rewrite published
  history, never delete a repo.

## Handoffs

Work moves by **assignment**, never by mentioning an agent. Hand off by assigning the task (or a
new subtask) to the next agent by name. One agent works at a time: when you start parallel
looking work (panel reviews), chain it with blocked-by links so it runs in sequence.

| Stage | Agent | Hands off to |
|---|---|---|
| PRD draft + panel | PM, with panel CTO, CEO, Critical, Security, QA, UX | Planner |
| Repo (if new), epic, tasks, refine | Planner | Engineer |
| Implement each issue in order | Engineer | Reviewer (per PR) |
| Review loop, merge, close, notify | Reviewer | Engineer (next issue) |
| Release (only when Siam invokes it) | Release | Siam (confirm), then done |

## Notifying Siam

When a stage finishes something Siam cares about (PRD approved, epic done, system ready for the
next requirement, release ready to confirm, an emergency), post a task comment and also run:

    osascript -e 'display notification "<one line>" with title "Paperclip"'

## Never

- Never put secrets in a repo, a comment or a PR.
- Never mark a PR approved or merged without the Reviewer's review.
- Never turn a feature flag on outside a confirmed release.
- Never stop on a failing check or a review loop: keep fixing until it passes (Siam's choice).
  A usage-limit stop is not a failure; the next run resumes the same task.
