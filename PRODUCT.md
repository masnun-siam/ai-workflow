# setu: product

## What it is

A single-user control room for Claude Code work. The human sets direction and answers questions; sessions do the work.
setu's job is to make "what needs me now" obvious and one keypress to act on.

## Principles

- **Waiting on me comes first.** The Inbox and River rank by urgency; a question to answer is never more than one key away.
- **Keyboard first, mouse works.** Every action has a letter shown next to it. Nothing needs a mouse.
- **The server decides, the UI renders.** Items carry their own actions; the UI has no per-type logic.
- **GitHub is the truth.** setu derives views from GitHub and `docs/prds/`, and keeps only its own session and loop state.
- **Calm by default.** Notify only on events the human chose (waiting, failed, PR ready, release); one sender, deduped.
- **Local and small.** One binary, std lib first, loopback plus optional tailnet, low idle cost.
- **Away is safe.** In Away mode only a read-only answerer replies, and only when confident.

## Screens

River (pipeline), Inbox, Runs, Releases, Ops, Me, Settings.
