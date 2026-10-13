Decision: the plugin's planning skills are forks of wasensi's `create-prd`, `create-tasks` and `refine-issues`, made generic and kept under wasensi's names. `/prd` becomes `/create-prd` with no alias, PRDs move from `docs/prd/` to `docs/prds/`, and `/gh-issue` and `/jira-to-gh` file exactly one issue. This supersedes the task-list half of ADR 0003: `/gh-issue` no longer saves or files a task list, and the epic is now filed by `/create-prd approve`, not `/gh-issue`. The rest of ADR 0003 stands (epics with sub-issues, `Depends on: #n` as the one source of dependencies, `aiw epic split`, both run paths).

## Context

The wasensi repo (`blubird-interactiveltd/wasensi`) grew its own planning chain in `.claude/skills/`: `create-prd` writes a PRD with a technical design and its epics, `create-tasks` splits an approved PRD into parallel, one-PR tasks, and `refine-issues` files them as sub-issues of the epics. Its PRD and task-list structure (status, epics, areas, waves, shared files, never renumbering) is better than ours. Ours had `/prd` (no technical design, no epics, no approval), `/create-tasks` (a flat list built from `/gh-issue`'s rules) and a task-list path inside `/gh-issue` and `/jira-to-gh` (step 0's saved-list skip, 3.6 / 4.6, 4-FLAT / 5-FLAT). The two chains overlap, so the user chose to fork wasensi's once and drop the overlap, instead of maintaining both.

The wasensi skills are tied to that project (its stack, its staging branch, its test tools, its tenant model), so a straight copy would not run on another repo. The fork removes those ties and keeps our own features: the Flow, peer review, the Obsidian mirror and the `→ next:` contract.

## Decision

1. Fork wasensi `create-prd`, `create-tasks` and `refine-issues` into the plugin once, made generic, under wasensi's names. Skip `implement-issue`, `verifier-locally`, wasensi's `pr-review` and `gitnexus-*`.
2. Rename `/prd` to `/create-prd` outright, with no alias. PRDs move from `docs/prd/` to `docs/prds/`.
3. `/create-prd` keeps our features:
   - the `→ next:` line and Flow auto mode
   - `--review`, the Obsidian mirror and the wiki
   - intake and `/dump` seed input
   - `--update`, which now also adds a `## Change log` line once the PRD is Approved
4. Status goes `Draft` → `In review` → `Approved`. `/create-prd approve <prd>` sets `Approved` and creates one epic per `## Epics` entry, labelled `epic` + `prd-<slug>`, and writes the numbers back. In `/flow`, "Continue" past the PRD checkpoint counts as approval. In the UI Flow, starting the Tasks step counts as approval.
5. `/create-tasks` takes wasensi's structure: Area, Parallel, Waves, Shared files, `Changed`/`Dropped`. It keeps **our** size rubric: 3 or fewer production files, 1–4 acceptance criteria, one verify command, no new dependency. It accepts an Approved PRD only, and its next line is `→ next: /refine-issues docs/tasks/<slug>.md`.
6. `/refine-issues` (new) files a task list:
   - Each task becomes a sub-issue of its epic, with native blocked-by links **and** `Depends on: #n` in the body.
   - Bodies use our section list, including `Test root:`, `Base branch:` and Proposed Fix.
   - After creating the issues it runs `aiw epic split` on each epic. Its next line is `→ next: /fix-blockers <epic>`.
7. `/gh-issue` and `/jira-to-gh` lose the task-list path: step 0's saved-list skip, 3.6 / 4.6, 4-FLAT / 5-FLAT, and "Saved task list and the epic". Step 3.5's decompose stays. With 2 or more tasks the command now **stops and routes to `/create-prd`**.
8. `/dump` routes bugs to `/gh-issue <Bugs.md>` instead of `/create-tasks`.
9. An "Improve this skill" footer goes on the three new skills only. It **always files an issue on the plugin repo** with the proposed diff, and never edits the skill.
10. Of the three forked skills, only `/create-prd` has `--review`. Its peer-review kind is renamed `prd` → `create-prd` (the UI passes the command family as the kind). The PRD rubric now allows contracts (data shape, endpoints, fields, sync/queued) and still bans code (file paths, class/method names, step-by-step logic).
11. The rest is detected rather than configured: base branch and repo from `gh`/git, Areas from the repo's top-level layout, and the tenant-isolation check only when CLAUDE.md or the code shows the repo is multi-tenant.
12. Ship as one branch and one PR, with a CHANGELOG entry and an ADR.

## Consequences

- There is no `/prd` alias. Anyone who types `/prd` must switch to `/create-prd`, and a link to `docs/prd/<slug>.md` must change to `docs/prds/<slug>.md`.
- `/gh-issue` and `/jira-to-gh` are one-issue only. Work that splits into 2 or more tasks goes through `/create-prd` → `/create-tasks` → `/refine-issues`, and `/run-issue` Preflight stops with the same `/create-prd` hand-off instead of filing several issues.
- The peer-review kind was renamed `prd` → `create-prd`, so `aiw peer-review new prd` no longer works; anything that passes the old kind must change.
- Old `/prd` sessions in `aiw ui` still map to the Flow's PRD step, and an old `docs/prd/` path still names its flow.
- The fork is one-off, not tracked. The ported sources are pinned at wasensi `staging` commit `051e5b8304605c5e9147394d66fbf2dd3818b90a`; a later improvement in wasensi is ported by hand, diffing from that sha.

## Later change, 2026-10-14

The Guided Flow's Blockers step was removed. `/refine-issues` already sets the native blocked-by links when it creates the issues (`gh issue create --blocked-by`), so the step did almost nothing. Decision 6's next line is now `→ next: herdr-dispatch <epic>`; when this `gh` lacks `--blocked-by`, the report says to run `/fix-blockers <epic>` first. `/flow` and the UI Flow run Dump → PRD → Tasks → Issues → Dispatch, and `/fix-blockers` stays a standalone command. The decisions above are otherwise unchanged.
