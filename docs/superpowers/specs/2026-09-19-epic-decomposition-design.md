# Epic decomposition and epic-aware dispatch

**Status:** approved design, not yet implemented
**Date:** 2026-09-19

## Problem

`/gh-issue` produces exactly one issue, and `/run-issue` runs exactly one issue. A BRD
for a whole feature has nowhere to go: filed as a single issue it becomes a PR nobody can
review, and split by hand it becomes N issues with no recorded ordering, so the person
running them has to remember which ones conflict.

This adds a layer above both: `/gh-issue` decomposes a BRD into a parent plus
bite-sized children with declared dependencies, and `/run-issue` on that parent drives
every child — in parallel where they are independent, in sequence where they are not.

## Constraints that shaped this

These are not preferences. Each one killed an otherwise reasonable design.

1. **Three human gates, exactly three.** `/run-issue`'s central promise. Eight children
   run naively is twenty-four interruptions, which would make the epic layer worse than
   running the children by hand.
2. **Subagents do not nest.** `/run-issue` is a session-level orchestration — it holds
   gates, dispatches station subagents, and owns the Docker stacks. Eight `/run-issue`s
   cannot run inside one session. `run-issue.md` already documents the neighbouring case:
   phase 10 must run in-session because `ScheduleWakeup`/`Monitor` die with a subagent.
3. **No daemon, no ledger service, no dashboard.** Stated in `run-issue.md`'s State rules.
   `~/.claude/pipeline/` is the predecessor this plugin replaced, and it has a daemon and
   a dashboard. A parallel epic runner is precisely the feature that tempts you back to
   one.
4. **Every issue is scored against `definition-of-ready` individually.** `run-researcher`
   blocks a run on a DoR gap. A child issue that defers context to its parent dies before
   its worktree exists.
5. **The Docker stack is capped for a reason.** Phase 2.5 caps the app service at 1.5 CPU
   because "three phases each independently bringing up their own stack with no caps and
   no teardown" pegged the host on a prior run. N children means N stacks.

## Decisions

| Decision | Choice | Rejected |
|---|---|---|
| Gate contract | three for the whole epic, any N | three per child; three per wave |
| Dependency source | declared in the sub-issue body at decomposition, confirmed at Gate 1 | inferred from plans' predicted file lists; declared + overlap veto |
| PR shape | one PR per child, **stacked on its dependency** | all onto master; one integration PR |
| Parallelism | flattened station relay in one session | sequential children; N separate sessions |

### Why the flattened relay

The epic session is **one** orchestrator holding N child ledgers. Rather than nesting
run-issues, it walks the roster across all ready children at once: N `run-planner`s in one
message, then N `run-sdet`s, then N `run-dev`s.

This is not a new primitive. `run-issue.md` phase 6 already mandates it for the specialist
panel — *"Spawn the specialist panel first, all in ONE message"* — and this applies the
same pattern across children instead of across lenses. No nesting, one owner of stacks and
gates, and `aiw` already keys ledgers per issue, so the state model needs nothing new.

### Why stacked PRs make sequencing fall out for free

A child stacked on its dependency cannot branch off a moving target, so it waits until its
dependency reaches **PR open** (phase 5), then branches off that branch. Independent
children run in parallel; dependent children cannot, by definition. The behaviour asked
for is a consequence of the DAG rather than a separately enforced rule.

The rebase cost is also nearly free. When child A's branch moves during review, child B's
base moved — and phase 8 *already* fetches and merges `origin/<base>`, runs the suite, and
routes conflicts to `run-sdet`/`run-dev`. Setting B's `base_branch` to A's branch instead
of `master` makes the existing phase handle it unchanged, and `aiw pr open --base` already
takes it.

## Decomposition (`/gh-issue` epic mode)

**Trigger.** `/gh-issue` detects an epic rather than being told: the input describes
multiple independently-shippable outcomes, or exceeds a size where one PR would be
reviewable. It proposes the split and asks before creating anything. Decomposition is a
judgment call and the user sees it proposed before N issues appear on the board.

**Every child is independently DoR-complete.** The parent holds the BRD; each child gets
its own full body — Problem, Scope, Acceptance Criteria, Affected Surface, Non-functional
Constraints, Dependencies — with the parent's context **inlined, never referenced**. This
follows from constraint 4: "see parent" fails DoR and the child dies before its worktree
is created.

**Vertical slices only.** A child is one thin end-to-end outcome ("payment refused on a
cancelled order, API through to UI"), never a layer ("all the models"). Horizontal slices
are the pathological case: they maximize file overlap so the DAG serializes everything,
and none of them has acceptance criteria verifiable on their own — phase 4.5 has nothing
to observe until the last one lands.

**Sizing.** One child is one PR a human reviews in one sitting: roughly ≤5 acceptance
criteria, one vertical slice. A split producing more than ~8 children is surfaced as a
decomposition problem at the gate, not silently launched as 20 pipelines.

**Dependencies** are a machine-readable `Depends on: #12, #13` line in each child's body,
written while the BRD is in context — the only moment anything can see the whole picture.
Edges may only point at siblings in the same epic. Cycles are rejected in code.

**Linkage** uses the native sub-issues API
(`POST repos/{owner}/{repo}/issues/{n}/sub_issues`), verified available on this repo. The
parent auto-closes when its children close. No label convention.

## State

No new state *kind*. Each child gets the run directory it would have had anyway,
`<runs_dir>/<owner>-<repo>-issue-<n>/`. The epic adds one sibling:

```
<runs_dir>/<owner>-<repo>-epic-<parent>/epic.json    # DAG, per-child status, stack budget
```

New deterministic surface in `run-engine/epic.py`, following the `register(sub, add)`
shape every module in `run-engine/` uses:

```
aiw epic split  <parent> --children <n>,<n>,…   # link sub-issues, build + validate the DAG
aiw epic init   <parent>                        # create every child run dir
aiw epic next   <parent>                        # -> JSON: which children may advance now
aiw epic status <parent>                        # -> per-child station, PR, blocked_on
```

`aiw epic next` is where sequencing lives, and it is pure: a child is ready when every
dependency has reached PR open, its own ledger says `running`, and a stack slot is free.
The orchestrator asks; it never eyeballs the DAG — the same rule `aiw route` already
enforces for station routing.

## The relay

A pipeline, not a set of barriers. Each turn:

1. `aiw epic next <parent>` → the children that may advance, and what each needs.
2. Dispatch **all of them in one message**, N tool uses.
3. Write each returned envelope to its own child run dir; route each with `aiw route`,
   which applies every existing guard and post-check per child, unchanged.

Children desynchronize immediately, and that is correct: child 3 can be in review while
child 5 is still writing tests. Nothing waits for a wave.

**Stack budget.** A child needs its stack from phase 2.5 through phase 8.5 — most of its
life. `epic.max_stacks` (default **2**) gates acquisition: a child that needs a stack and
cannot get a slot stays parked at phase 2.5 rather than starting. A child's stack tears
down the moment it clears the CI gate, freeing the slot. On a repo with no compose file
(`stack=none`) there is no budget to spend and every child runs at once.

Default 2 rather than a formula on core count: an epic that pegs the host is worse than
one that takes longer, and the value is raisable per repo in `.run-issue.json` once the
shape of that repo's stack is known.

## The three gates

**Gate 1 — the decomposition and every plan, once.** Prints the DAG as a readable order,
which children are parallel, per-child DoR gaps and assumptions, then all N plans in full.
Options: *Approve all* · *Revise child N* (re-plans that child only, re-gates) · *Drop
child N* (refused if anything depends on it, unless the dependents are dropped too) ·
*Abort*.

**Gate 2a — blockers, collected.** A blocker **parks that child**; the epic keeps going.
Gate 2a fires once, when the epic can make no further progress without a human — either
everything else has finished, or a parked child is blocking the DAG. Every blocker is then
seen together, which is also the only view in which they are comparable.

**Gate 2 — one epic report.** Per child: PR, CI verdict, open threads,
runtime-verification status, anything carried forward. Plus parked children and why. And
**the merge order, explicitly**: merging is manual, and a stacked PR merged out of order
has to be unpicked by hand.

## Failure

Each child takes the **Degraded finish** path that already exists: `blocked_on` recorded,
a draft PR if the branch can be pushed, carried to the report. The epic does not stop —
one child hitting a wall is not a reason to abandon seven working ones.

Two cases the single-issue design has no answer for:

- **A failed child with dependents.** Its dependents can never start; their base branch
  will never exist. They are reported at Gate 2 as *"never started, blocked by #N"*,
  explicitly. A child silently absent from a list of twelve is how a third of an epic
  turns out never to have been built.
- **A dropped or dead base.** A child dropped at Gate 1, or dead before opening its PR,
  leaves anything stacked on it with no base. Those children re-target `master` and are
  **flagged as re-targeted**, because the plan assumed a dependency that no longer exists
  and that assumption may have been load-bearing.

**A child run directly.** `/run-issue <child>` stays legal and behaves as an ordinary
single-issue run — a child is a complete, DoR-satisfying issue, which is the whole point of
the decomposition contract. The one difference: its `Depends on:` line names a base branch
that may not exist yet. Phase 0 checks, and if the dependency has no branch it says so and
asks whether to base on `master` instead. It never guesses a substitute base, which is the
same rule phase 8 already applies when `origin/<base>` has gone missing.

**Resume is free.** `aiw epic status` reads every child ledger, and each already carries
the `done` / `escalated` / `running` semantics phase 0 branches on. Epic resume is
per-child resume: no new recovery machinery, and nothing has to stay alive between
sessions.

## Out of scope

- **The epic does not grind.** Phase 10's `pr-grind` must run in-session and holds
  `ScheduleWakeup` plus a persistent `Monitor`; there cannot be eight. The epic stops at
  Gate 2 and hands back N PRs with their merge order. Grinding is per-PR, invoked as
  `/pr-grind <url>`. A multi-PR grind would be a second long-lived loop beside the one
  that works, which is how two budgets end up disagreeing about the same rerun.
- Cross-repo epics.
- Anything that merges.
- Re-decomposing mid-flight. That is abort, re-split, re-run.
- Inferring dependencies from predicted file lists. A plan's file list is a prediction —
  `check_dev_post` exists precisely because `run-dev` touches files the plan did not name.

## Surface

| File | Change |
|---|---|
| `run-engine/epic.py` | new: DAG build, cycle rejection, `next` readiness, stack budget — pure logic |
| `run-engine/route.py` | one entry in the module tuple in `main()` |
| `commands/gh-issue.md` | epic-mode branch: detect, propose, write N DoR-complete children, link |
| `commands/run-issue.md` | epic-mode branch at phase 0: parent detected → the relay |
| `run-engine/test_scripts.py` | DAG ordering, cycle rejection, readiness under a stack budget, drop-with-dependents |

Everything else is reuse: child ledgers, `aiw route` and its post-checks, `aiw stack`,
`aiw worktree`, `aiw pr open --base`, and phase 8 doing the rebase work unchanged.

## Dependency

Builds on the `aiw` subcommand pattern and the `run-engine/` module layout from
PR #3. Should not be implemented before that lands.
