---
name: herdr-dispatch
description: Run an epic's child issues as parallel herdr tabs, end to end — each tab runs `/ai-workflow:implement-issue <n>`, then grinds the PR (off/simple/full), is merged (optional auto-merge), does implement-issue's after-merge followups, closes, and the next unblocked issue opens. Dependency order and a concurrency cap; this session previews, starts and relays. Use whenever the user wants to run, dispatch or fan out an epic's issues in herdr tabs, "implement this epic in parallel", "dispatch epic 123", or work several issues at once in herdr, even if they don't name this skill.
argument-hint: <epic: owner/repo#N or N> [--max N] [--grind off|simple|full] [--ci wait|defer|ignore] [--auto-merge] [--feature-branch <name>] [--model M] [--effort E]
---

# herdr-dispatch

You are the **controller**. The `aiw dispatch` engine, ticked by the `aiw ui` server, does the work:
it opens one herdr tab per issue, sends each tab its next command, merges, and closes tabs. You preview,
start, watch and pass on what needs the user. The UI shows and steers the same dispatch.

You never answer a tab's question, merge, or post to GitHub yourself. The engine merges only when the
user turned auto-merge on.

## Inputs

`<epic>` is `owner/repo#N`, or `N` for the repo of the current checkout. Flags, all passed straight to
`aiw dispatch`:

| Flag | Meaning | Default |
|---|---|---|
| `--max N` | tabs running at once | 2 |
| `--grind off\|simple\|full` | grind each ready PR: `simple` ends on any approval, `full` on zero blocker/should-fix | full |
| `--ci wait\|defer\|ignore` | `wait`: CI gates each lane as today; `defer`: CI blocks only the merge (red CI at the gate sends the CI-fix prompt once per push); `ignore`: CI never blocks, red or pending CI can merge with a warning event | wait |
| `--auto-merge` | merge (merge commit) once CI is green, an approving review is in and the grind is done | off: the tab waits for the user's merge |
| `--feature-branch <name>` | every PR targets this branch, cut from the default branch if missing | each issue's own base |
| `--model`, `--effort` | for every tab | Claude's defaults |

## Flow

1. **Workspace.** `herdr pane current` → its `workspace_id`.
2. **Preview.** `aiw dispatch plan <epic> <flags>`. Show the user the waves (issues that run together),
   the settings, and every warning: unrefined issues are skipped ("needs refine": suggest
   `/ai-workflow:refine-issues`), a repo with no registered checkout cannot open a tab, a repo with no
   Slack channel skips grinding, an open blocker outside the epic holds its issue. Then ask with
   `AskUserQuestion`: start, change settings, or stop. On a change, preview again.
3. **Start.** `aiw dispatch start <epic> <flags> --runner herdr --workspace <workspace_id>` prints
   `{"id", "since", "ui"}`. It starts the `aiw ui` server when it is not running. Tell the user the id and
   the UI link.
4. **Watch.** Run `aiw dispatch watch <id> --since <since>` with `run_in_background`. It exits when an
   event needs the user (or after ~50 minutes), printing the new events and a last line
   `state=<state> since=<ts>`. Tell the user, in a line per lane, what happened and what each needs:
   - `needs_you` — the tab waits on a question or permission, or stopped. Name the tab (`issue-<n>`);
     the user answers in the tab or the UI.
   - `held` — CI is red, the grind paused or ended, or a merge failed. Its dependents wait.
   - `awaiting_merge` — the PR passed the gate and auto-merge is off: the user merges it; the engine
     sees the merge and sends the tab its followups.
   - `finished` — every lane is closed or skipped: go to step 6.
   Then start the watch again with the new `since`. Stay quiet about plain progress unless asked.
5. **Steer** on the user's word only:
   - `aiw dispatch set <id> max=3 grind=simple auto_merge=on model=<m>` (applies at the next step)
   - `aiw dispatch pause|resume|cancel <id>` (pause stops new tabs; running ones go on)
   - `aiw dispatch lane <id> <n> pause|resume|retry|skip|merge|hold|unhold`, or
     `aiw dispatch lane <id> <n> send "<text>"` to type into that tab
   - `aiw dispatch show <id>` for every lane's stage
6. **End.** When `finished`, report each issue: its PR, merged or not, skipped and why. Offer, with
   `AskUserQuestion` (multi-select), the end actions; none runs by itself:
   - **Open PR to the default branch** (`aiw dispatch end <id> open-pr`; only with a feature branch)
   - **Run QA** (`aiw dispatch end <id> qa`): a tab that runs `/ai-workflow:verifier-locally` and tests
     the whole feature end to end in the browser, filing each bug as a new child of the epic. New
     children join this dispatch as lanes by themselves, so keep watching. A finished dispatch that gains children pauses; resume it after they are refined.
   - **Grind the final PR** (`aiw dispatch end <id> grind-pr`; only after open-pr)

## Rules

- Never answer a tab's gate, merge, or comment on GitHub from here. Never type into a tab except through
  `aiw dispatch lane … send` on the user's word.
- The dispatch record and GitHub are the state. After a compaction or a new session, `aiw dispatch ls`
  and `show` say where things stand; resume at step 4.
- A tab that stalls at start (an MCP-servers dialog, a dropped prompt) shows as `needs_you`. The user
  fixes the tab, then `aiw dispatch lane <id> <n> retry`.

## Self-improve

After the task, follow `../../self-improve.md` (relative to this skill's directory).
