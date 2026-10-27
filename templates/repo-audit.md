# [REVIEW NEEDED] Repo setup for AI agents - audit

Writer note (delete before saving): `repo-bootstrap` phase 1 writes this as one GitHub issue. Read only, nothing executed: say so. Every finding names the file and, where it helps, the line count or date. Drop a section that has no findings; add one for anything else the repo needs.

> **This is a report for discussion, not a work item.** The team goes through it; what is agreed becomes the bootstrap phases and separate issues.

Reviewed at `<sha>` (`<branch>`, <date>) by reading the docs, agent config, hooks, CI and compose files. Nothing was executed.

## Summary

| Area | Status | Main problem |
|---|---|---|
| README | Good / Needs work / Stale | |
| Agent instructions | | |
| Skills | | |
| Pre-commit and CI | | |
| Running the project | | |
| Docs freshness | | |

## 1. README
| Finding | Detail |
|---|---|

**Suggest:**

## 2. Agent instructions
Every instruction file, its length, whether it is project-specific or a generic template, what it says that the code contradicts, duplication, and tool configs that regenerate it. Whether `docs/` is gitignored.

| Finding | Detail |
|---|---|

**Suggest:**

## 3. Skills
Layout (`<name>/SKILL.md` with front matter or not), share of code samples, generic vs. this codebase, contradictions, duplicates, broken symlinks.

| Finding | Detail |
|---|---|

**Suggest:**

## 4. Pre-commit and CI

| Check | <component> | <component> |
|---|---|---|
| Lint / format | | |
| Static analysis | | |
| Tests | | |
| Dependency audit | | |
| Doc-only skip | | |
| PR edit/rename triggers | | |

| Other finding | Detail |
|---|---|

Already good:

## 5. Running the project
Is there one start command and a quickstart someone can follow without asking? Is there one `make up` that boots everything in Docker, isolated per worktree, and a `make down` that removes it?

## 6. Stale docs

| File | Last changed |
|---|---|

## To discuss
- [ ] Which agent tools does the team use? That decides which instruction files to keep.
- [ ] Base and production branches.
- [ ] Package manager per component.
- [ ] Where PRDs live: `docs/prds/` or elsewhere.
- [ ] Who owns `CLAUDE.md` (CODEOWNERS)?
- [ ] Issue tracker, project board and its statuses.
- [ ] Which paths count as doc-only (default: any `*.md` plus `docs/`)?
- [ ] Is a code-graph tool really used? If yes, configure it; if not, drop the rule.

## Proposed order
1. Constitution: short `CLAUDE.md`, `AGENTS.md` symlink, guards
2. Guides, conventions and a tested README quickstart; remove generic files
3. Gates and local stack: Makefile, isolated Docker stack, pre-commit and CI
4. Docs generated for agents
5. First feature through the full workflow

## Done when
- [ ] Root `CLAUDE.md` under about 60 lines, every path and command in it exists, `AGENTS.md` links to it, no nested copies
- [ ] Guard hook, pre-commit guards and a CODEOWNERS entry for `CLAUDE.md`
- [ ] `docs/` tracked; conventions guide per component with a real file per rule
- [ ] README quickstart run end to end on a clean worktree
- [ ] No generic skill files, duplicates or broken symlinks
- [ ] `make up` and `make down` boot and remove an isolated per-worktree Docker stack
- [ ] Pre-commit and CI gate every component, skip code checks on doc-only changes, and a PR rename runs only the PR-meta check
- [ ] `docs/` generated, with `Covers:` lines and a sync marker
