---
name: repo-bootstrap
description: Make an existing repository ready for AI agents and this plugin's workflow, in reviewable phases - a read-only audit for the team to discuss, the decisions it raises, a short protected CLAUDE.md, guides and a tested README quickstart, the gates, and agent-written docs - on one branch and one pull request, one phase per run. Its docs phase runs only inside a bootstrap; a standalone docs refresh is /docs-updater. Use when asked to bootstrap, onboard or set up a repo for agents or for ai-workflow, to write or rewrite a repo's CLAUDE.md or AGENTS.md from scratch, to audit a repo's agent setup, or to "do what we did for Wasensi" on another project.
argument-hint: "[audit | decide | constitution | guides | gates | docs] [issue number]"
---

# Repo bootstrap

Takes a repository from scattered or generic agent instructions to the shape the other skills expect: one short, protected `CLAUDE.md` that is an index, guides and docs verified against the code, gates that catch what agents get wrong, and the plugin's skills and templates used as they are. The plugin's workflow skills are not copied into the repo; a repo copy is only for a repo-specific deviation.

Paths below starting `../../` are relative to this skill's folder, at the plugin root. Read first: `../../guides/engineering-workflow.md` ("Repository settings" for the base branch and which guides, templates and skills win, and "Branches, commits and pull requests") and `../../guides/skills.md`.

## Rules for every phase

- **Verified only.** Every path, command, convention and claim you write must exist in the code at the commit you work on; take commands from the Makefile, package manifests, compose files and CI, not from old docs. Say what you could not run.
- **Write from the code, not from the old docs.** When recreating `CLAUDE.md`, a guide, the README or `docs/`, do not start from the existing text, keep its structure or carry its claims over. Old docs, instruction files and wikis are leads at most: a claim from them goes in only after you have found it in the code yourself, and silence in the old docs says nothing about what the code does.
- **Delete generic, don't trim it.** Instruction or skill files copied from an org template, framework tutorials and code dumps are removed, not relocated, when the code does not follow them. Git history keeps them.
- **One fact, one home.** `CLAUDE.md` holds rules and an index; `docs/guides/` how the team works; `docs/` what the code is; skills the steps. Nothing is said twice.
- **Never edit an existing `CLAUDE.md` or `AGENTS.md`** without the user saying so in this session, and show the full new text first.
- **Findings are not drive-by fixes.** A broken gate, a stale script or a bug found along the way gets its own issue (follow "A finding from other work" in create-tasks, see "Repo skills win"), not a fix in a bootstrap PR.
- A bootstrap is one branch, `bootstrap/<issue>` (`<issue>` is the audit issue), and one pull request into the base branch that references the bootstrap issue. The constitution phase (the first that commits) opens it as a draft and docs marks it ready; guides, gates and docs each add their own commit(s) and push to it. Reuse the branch and the PR already open for it when they exist. Audit and decide commit nothing and open no branch.
- The PR body carries one checklist line per committing phase: `- [ ] constitution`, `- [ ] guides`, `- [ ] gates`, `- [ ] docs`. Constitution writes them unticked; each phase ticks only its own line when it pushes (read the body first, then `gh pr edit --body`).
- Let every hook run; never `--no-verify`.

## Phases

Every run does exactly one phase and ends. With no argument the run is `audit`; `<phase> <issue>` runs only that phase and needs the issue number. Check the earlier phases are on `bootstrap/<issue>` or the issue (nothing merges until docs is done); if they are not, stop with an error and no `BOOTSTRAP:` line.

**Ending a run.** A finished phase ends its final message, after the report, with the next command and then the last line, with nothing after it:

```
Next: /repo-bootstrap <next phase> <issue>
BOOTSTRAP: <phase> done #<issue>
```

`<phase>` is one of `audit`, `decide`, `constitution`, `guides`, `gates`, `docs`. After `docs` there is no `Next:` line, only the `BOOTSTRAP:` line. A phase that did not finish prints no `BOOTSTRAP:` line.

1. **Audit (`audit`, read-only).** Change nothing. Read the README, every agent instruction file (`CLAUDE.md`, `AGENTS.md`, nested copies, `.cursorrules`, `.github/copilot-instructions.md`, `.claude/`, tool configs that regenerate them), skills, `.gitignore`, the hooks and CI for each component, how the project is run, and when each doc last changed. Write the report in the shape of `../../templates/repo-audit.md`. Show it, then create it as one GitHub issue only on the user's yes; the issue number is `<issue>` in the closing lines. On the user's no, end without a `BOOTSTRAP:` line. Needs no branch. Stop: the team discusses it before anything changes.

2. **Decisions (`decide`).** Settle every "To discuss" question with `AskUserQuestion`, recommended option first with the reason. At least: which agent tools the team uses (which instruction files to keep), the base and production branches, the package manager per component, where PRDs live, who owns `CLAUDE.md` (CODEOWNERS), the issue tracker and board statuses, which paths count as doc-only (default: any `*.md` plus `docs/`), and whether a code-graph tool (GitNexus or similar) is really used. Record the answers in a comment on the bootstrap issue; it commits nothing.

3. **Constitution (`constitution`).** Create `bootstrap/<issue>` from `origin/<base>` (reuse it if it exists), commit there, push, and open the draft PR with the checklist. Write the root `CLAUDE.md` in the shape of `../../templates/claude-md.md`, at most about 60 lines, naming the base branch so skills read it from there. Make `AGENTS.md` a symlink to it. Delete nested and duplicate instruction files; move any detail worth keeping, verified, into `docs/guides/`. Remove `docs/` from `.gitignore` if it is ignored. Add the guards from `scripts/`: `guard-claude-md.sh` as a `PreToolUse` hook on `Edit|Write|MultiEdit|NotebookEdit` in `.claude/settings.json` (it asks the human before an agent edits `CLAUDE.md` or `AGENTS.md`), and `claude-md-guard.sh` as two pre-commit hooks (`nested` blocks, `warn` on root changes). Add a CODEOWNERS entry for `CLAUDE.md`, or a commented placeholder if no owner was decided. Gitignore `CLAUDE.local.md`. Tools that regenerate instruction files (Laravel Boost, GitNexus without `--skip-agents-md` or `--index-only`) are noted in the PR.

4. **Guides and README (`guides`).**
   - One `docs/guides/<area>-conventions.md` per component, written from the code: each rule names the real file that sets the pattern, and names the exceptions.
   - Copy the plugin's guides and templates into `docs/guides/` and `docs/templates/` only where the repo deviates (branches, labels, board statuses, review rules), and edit the copy; otherwise the plugin's apply.
   - Cut the README to a quickstart a new developer or agent can follow without asking: services, prerequisites, start, ports, the checks CI runs, a docs index. Move runbooks to `docs/runbooks/`. Run the quickstart on a clean worktree and report each step's result.
   - Delete generic skill files, duplicate copies and symlinks that point outside the repo.
   - Add the guides to `CLAUDE.md` References only when the user asks.
   - Commit to the bootstrap branch, push, and tick `guides` in the PR body.

5. **Gates and local stack (`gates`).** Show the gaps as a table, then build what is missing on the bootstrap branch:
   - A root `Makefile` as the one entry point: `up` boots the whole system, `down` removes its containers, volumes and network, and `test`, `lint` and the other checks call the repo's own scripts.
   - A Docker stack that needs nothing on the host but Docker and make, isolated per worktree: compose project name, ports, volumes and network derived from the issue number, the main checkout keeping its defaults, so an issue's stack never touches another's or the main one.
   - For each component, lint, static analysis and tests in pre-commit (or pre-push) and in CI, failing closed; the protected-branch block, the secret scan and a block on lint-suppression comments.
   - Doc-only changes (the paths decided in phase 2) skip the code hooks and code CI jobs: a first CI job detects the changed paths, code jobs skip when only docs changed, and one always-running summary job is the required check.
   - The check that fails a pull request whose body references no issue runs in its own workflow on `opened`, `edited` and `synchronize`; code CI runs only on `opened`, `synchronize` and `reopened`, so renaming a pull request or editing its body re-runs only that check.
   - Run `make up`, `make down` and every check on a clean worktree and report each result. Bugs found along the way are still filed as issues. Commit, push, and tick `gates` in the PR body.

6. **Docs (`docs`).** Do the work of docs-updater with `full` (see "Repo skills win") on `bootstrap/<issue>` and commit there, without opening docs-updater's own branch or PR (docs-updater itself is unchanged). It owns `docs/` except `docs/guides/`, `docs/templates/`, `docs/prds/` and `docs/runbooks/`; never delete those. Tick `docs` in the PR body, mark the PR ready (`gh pr ready`), then show the user the `CLAUDE.md` References rows to change. The phase 7 hand-off stays as the closing message of the docs run.

7. **First feature.** Tell the user the repo is ready, and that the first real feature should go through the whole chain, starting with create-prd (see "Repo skills win"). Expect most skill fixes to come from that run; they go through each skill's "Improve this skill" loop.

## Report

After each phase: the bootstrap PR link, what was added, changed and removed, what was verified and how, what was not verified, and the issues filed. After the last: the checklist from `../../templates/repo-audit.md` "Done when" with each line ticked or explained. The report comes before the `Next:` and `BOOTSTRAP:` lines.

## Improve this skill

Follow the loop in `../../guides/skills.md`. Commit approved edits in the plugin source as `chore: update /repo-bootstrap skill - <what changed>`.
