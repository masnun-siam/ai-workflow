---
name: docs-updater
description: Bring the repo documentation in docs/ in line with the current codebase, written for AI agents - concise, scannable, with diagrams, tables and bullet points. The first run documents everything; later runs read only what changed in the code since the last docs update, then add, fix and remove what that change affects. Use when asked to update, refresh, sync or (re)generate the documentation, or on the team's periodic docs run.
argument-hint: "[full] [issue number to reference]"
---

# Docs updater

Keeps `docs/` true to the code on the base branch. The reader is an AI agent about to start work: it must learn quickly where things are, how they flow, which conventions the code follows and how to run and check its work. The code is the only source; never copy from old docs, issues or memory without checking it in the code.

Paths below starting `../../` are relative to this skill's folder, at the plugin root. Read first: `../../guides/engineering-workflow.md` ("Repository settings" to resolve the base branch and which skills win, and "Branches, commits and pull requests").

`docs/prds/` belongs to `/create-prd`; never touch it. Leave `docs/guides/` and `docs/templates/` alone too: they are written by people.

## Layout

| File | Holds |
|---|---|
| `docs/README.md` | Index: every doc with one line on when to read it, and the sync marker `Synced to: <commit sha> (<date>)` |
| `docs/architecture.md` | Components, how they talk, data stores, main request and event flows |
| `docs/development.md` | Local setup, commands, tests, hooks and CI gates |
| `docs/<component>.md` | One per component or package the repo actually has (for example `backend.md`, `frontend.md`, `worker.md`): structure, layers, conventions and patterns |
| `docs/features/<feature>.md` | One per business feature: what it does, its flow end to end, data, endpoints, jobs, events, UI |

Let the code decide the component and feature lists. In a single-component repo, fold `docs/<component>.md` into `docs/architecture.md`. Every doc starts with a `Covers:` line listing the paths it describes, so later runs can map a changed file to its docs. Every path under the documented areas belongs to at least one doc.

## Writing rules

- **Concise and scannable.** Tables for lists of things (endpoints, jobs, tables, commands, env keys by name only), bullet points for rules and facts, short sentences. No introductions or filler. One idea per bullet.
- **Diagrams** in Mermaid wherever a flow, a sequence or relations between parts would otherwise take a paragraph: architecture, request and event flows, data models, state changes.
- **Agent-useful.** Say where things live (real paths and symbol names), how a flow runs, the conventions the code follows consistently, how to test, and the gotchas that would trip someone. Skip what is obvious from reading a file.
- **Only verified facts.** Every path, symbol, command and claim must exist in the code at the commit you sync to. Describe a convention only when the code follows it consistently; where the code is inconsistent, say so.
- **No duplication.** Each fact lives in one doc; others link to it. Do not repeat the repo's `CLAUDE.md` or `AGENTS.md`.
- **Short files.** When a doc grows past what can be scanned in a minute or two, split it.
- **Never** include secrets, `.env` values, credentials or customer data.

## Steps

1. **Set up.** Fetch, then create a branch and worktree from the latest `origin/<base>` (for example `git worktree add -b docs-update-<date> .worktrees/docs-update-<date> origin/<base>`). Note the `origin/<base>` commit sha; this run syncs the docs to it.

2. **Choose the mode.** Read the sync marker in `docs/README.md`. Run a **full** update when there is no marker, the marked commit is not an ancestor of `origin/<base>`, or the user passed `full`. Otherwise run an **incremental** update from the marked commit.

3. **Full update.** Map the codebase, with GitNexus (clusters, processes, `query`, `context`) when its index is available, and by reading the code: components, features, flows, data, endpoints, jobs, events, UI, tooling, gates. Split the work by area; when subagents are available, document areas in parallel, each following the writing rules. Then write `docs/architecture.md` and `docs/README.md` last, from the finished area docs. Remove any existing generated doc that no longer matches the layout or the code; ask before removing anything you are not sure was generated.

4. **Incremental update.** List what changed: `git diff --name-status <marked sha> origin/<base>` and `git log --oneline <marked sha>..origin/<base>`. For each changed, added, renamed or deleted path, find the docs whose `Covers:` include it, and any new area no doc covers yet. In each affected doc, check every statement that touches the change against the code: fix what is wrong, remove what is stale, add what is new. Create a new doc for a new feature or area, and delete or merge a doc whose code is gone. Leave unaffected docs alone.

5. **Verify.** Every path and symbol named in `docs/` exists at the sync commit (check them all, not a sample). Every Mermaid diagram is valid syntax. Every link between docs resolves. Every doc has a `Covers:` line and appears in the `docs/README.md` index. Nothing is said twice.

6. **Update the marker** in `docs/README.md` to the `origin/<base>` sha and date from step 1.

7. **Check `CLAUDE.md` and `AGENTS.md`.** If their references point at docs that no longer exist or miss the docs index, tell the user the exact lines to change. Edit them only if the user explicitly asks.

8. **Commit and open a pull request** into the base branch. Let every hook run; never use `--no-verify`. Reference an issue in the pull request body: use the issue number the user gave, or ask the user for one. List the docs added, changed and removed, and the commit range covered.

9. **Report** the pull request link, the mode (full or incremental), the commit range, the docs added, changed and removed, and anything in the code you could not document confidently and why. After merge, remove the worktree and branch.
