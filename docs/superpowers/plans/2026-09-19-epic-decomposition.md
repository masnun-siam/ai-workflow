# Epic Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `/gh-issue` split a BRD into a parent plus bite-sized sub-issues with declared dependencies, and let `/run-issue <parent>` drive them all — parallel where independent, sequential where dependent — behind one set of three human gates.

**Architecture:** One session holds N child ledgers and walks the roster across all ready children at once (the pattern phase 6 already uses for the specialist panel), rather than nesting `/run-issue`s, which is impossible because subagents do not nest. Sequencing falls out of stacked PRs: a dependent child waits for its dependency to reach PR open, then branches off that branch, and phase 8's existing fetch-merge-test handles the rebase unchanged. All ordering logic is pure code in `run-engine/epic.py`; the orchestrator asks and never eyeballs the DAG.

**Tech Stack:** Python 3 stdlib only (no deps — matches the rest of `run-engine/`), `gh` CLI, GitHub GraphQL for Projects v2 and the sub-issues REST API.

**Spec:** `docs/superpowers/specs/2026-09-19-epic-decomposition-design.md`

## Global Constraints

- **Three human gates for the whole epic, any N.** Gate 1 (decomposition + all plans), Gate 2a (blockers, collected — fires once when no further progress is possible), Gate 2 (one report). No task may add a fourth.
- **No daemon, no ledger service, no dashboard.** State is files written by a script that exits.
- **`epic.max_stacks` default `2`**, overridable in `<repo>/.run-issue.json`.
- **Every child issue must independently satisfy `definition-of-ready`** — parent context is inlined, never referenced.
- **Dependency edges may only point at siblings in the same epic.** Cycles rejected in code.
- **The board filters on `label:epic-<n>`.** Never `parent-issue:` — the Projects API accepts any filter string without validation, so it cannot be verified.
- **Best-effort operations exit 0, always:** anything touching GitHub Projects. One warning line, never a stop.
- **Python modules follow the existing shape:** pure logic separate from I/O, `register(sub, add)` for CLI wiring, imports from `shared.py`.
- **Tests are assert-based with no framework**, appended to `run-engine/test_scripts.py`, using its existing `ok(label)` helper and `passed` counter.
- **Depends on PR #3** (`feat/route-subcommands-and-post-checks`). Do not start before it lands on `master`.

---

### Task 1: Dependency parsing and the DAG

**Files:**
- Create: `run-engine/epic.py`
- Test: `run-engine/test_scripts.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: `parse_depends(body: str) -> list[int]`, `build_dag(deps: dict[int, list[int]]) -> dict` returning `{"order": list[int], "deps": dict[str, list[int]]}` and raising `ValueError` on a foreign edge, a self-edge, or a cycle.

- [ ] **Step 1: Write the failing tests**

Append to `run-engine/test_scripts.py`, above the final `print`:

```python
# --------------------------------------------------------------------------- epic DAG

assert epic.parse_depends("Some body\n\nDepends on: #12, #13\n") == [12, 13]
assert epic.parse_depends("depends on: #7") == [7], "the header is case-insensitive"
assert epic.parse_depends("No dependency line here") == []
assert epic.parse_depends("Depends on: none") == []
assert epic.parse_depends("Depends on: #9, #9") == [9], "duplicates collapse"
assert epic.parse_depends(None) == []
ok("Depends on: parses to sorted unique issue numbers, absent means []")

dag = epic.build_dag({10: [], 11: [10], 12: [10], 13: [11, 12]})
assert dag["order"] == [10, 11, 12, 13], dag["order"]
assert dag["deps"]["13"] == [11, 12]
ok("build_dag topologically orders a diamond deterministically")

for bad, needle in [
    ({10: [99]}, "not in this epic"),
    ({10: [10]}, "itself"),
    ({10: [11], 11: [10]}, "cycle"),
    ({10: [11], 11: [12], 12: [10]}, "cycle"),
]:
    try:
        epic.build_dag(bad)
        raise AssertionError(f"expected ValueError for {bad}")
    except ValueError as exc:
        assert needle in str(exc), f"{bad}: {exc}"
ok("build_dag rejects foreign edges, self-edges and cycles of any length")
```

Add the import beside the others near the top of the file:

```python
import epic  # noqa: E402
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 run-engine/test_scripts.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'epic'`

- [ ] **Step 3: Write the implementation**

Create `run-engine/epic.py`:

```python
"""Epic decomposition: the DAG, readiness, and the stack budget.

Pure logic only — the orchestrator asks this module which children may advance
and never eyeballs the DAG itself, the same rule `aiw route` already enforces for
station routing. I/O lives in the cmd_* functions at the bottom.
"""

from __future__ import annotations

import re

DEPENDS_RE = re.compile(r"^\s*Depends on:\s*(.+)$", re.M | re.I)


def parse_depends(body: str | None) -> list[int]:
    """Issue numbers from a child's `Depends on: #12, #13` line.

    Absent line, or a line naming no issues ("none"), means no dependencies —
    both are normal and neither is an error.
    """
    match = DEPENDS_RE.search(body or "")
    if not match:
        return []
    return sorted({int(n) for n in re.findall(r"#(\d+)", match.group(1))})


def build_dag(deps: dict[int, list[int]]) -> dict:
    """Topologically order the epic's children.

    Raises ValueError rather than returning a partial order: an epic whose edges
    do not form a DAG cannot be sequenced at all, and guessing an order would run
    children against base branches that do not exist yet.
    """
    known = set(deps)
    for child, declared in deps.items():
        for dep in declared:
            if dep == child:
                raise ValueError(f"#{child} depends on itself")
            if dep not in known:
                raise ValueError(
                    f"#{child} depends on #{dep}, which is not in this epic — "
                    "edges may only point at siblings"
                )

    indegree = {child: len(declared) for child, declared in deps.items()}
    queue = [child for child, n in indegree.items() if n == 0]
    order: list[int] = []
    while queue:
        queue.sort()  # deterministic: the same epic always prints the same order
        node = queue.pop(0)
        order.append(node)
        for child, declared in deps.items():
            if node in declared:
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)

    if len(order) != len(deps):
        stuck = sorted(set(deps) - set(order))
        raise ValueError("dependency cycle among: " + ", ".join(f"#{c}" for c in stuck))
    return {"order": order, "deps": {str(k): v for k, v in deps.items()}}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 run-engine/test_scripts.py`
Expected: PASS, three new `ok` lines, total count increased by 3.

- [ ] **Step 5: Commit**

```bash
git add run-engine/epic.py run-engine/test_scripts.py
git commit -m "feat: parse Depends-on edges and build the epic DAG"
```

---

### Task 2: Readiness under dependencies and the stack budget

**Files:**
- Modify: `run-engine/epic.py`
- Test: `run-engine/test_scripts.py` (append)

**Interfaces:**
- Consumes: `build_dag` from Task 1.
- Produces: `ready(dag: dict, states: dict[int, dict], max_stacks: int) -> list[int]`. Each entry of `states` is `{"status": str, "pr": bool, "stack_up": bool, "needs_stack": bool}`.

- [ ] **Step 1: Write the failing tests**

Append to `run-engine/test_scripts.py`:

```python
# --------------------------------------------------------------------------- epic readiness

DAG = epic.build_dag({10: [], 11: [10], 12: []})


def state(status="running", pr=False, stack_up=False, needs_stack=False):
    return {"status": status, "pr": pr, "stack_up": stack_up, "needs_stack": needs_stack}


s = {10: state(), 11: state(), 12: state()}
assert epic.ready(DAG, s, max_stacks=2) == [10, 12], "11 waits: #10 has no PR yet"
ok("a child waits until every dependency has reached PR open")

s[10] = state(pr=True)
assert epic.ready(DAG, s, max_stacks=2) == [10, 11, 12]
ok("a dependency reaching PR open releases its dependents")

s = {10: state(status="done", pr=True), 11: state(), 12: state(status="escalated")}
assert epic.ready(DAG, s, max_stacks=2) == [11], "done and escalated children are not ready"
ok("only children whose own run is still running are ready")

# Stack budget, ISOLATED from the dependency rule. #10 must carry pr=True in every case
# below, or #11 is excluded because its dependency has no PR yet and the assertion passes
# for a reason that has nothing to do with the budget it is named for.
s = {10: state(pr=True, stack_up=True), 11: state(needs_stack=True), 12: state(stack_up=True)}
assert epic.ready(DAG, s, max_stacks=2) == [10, 12], "11 needs a stack, both slots taken"
ok("a child needing a stack parks when the budget is spent")

s = {10: state(pr=True, stack_up=True), 11: state(needs_stack=True), 12: state()}
assert epic.ready(DAG, s, max_stacks=2) == [10, 11, 12], "one slot free, 11 takes it"
ok("a freed stack slot releases exactly one parked child")

s = {10: state(pr=True, needs_stack=True), 11: state(needs_stack=True), 12: state(needs_stack=True)}
assert epic.ready(DAG, s, max_stacks=0) == [], "no budget at all"
assert epic.ready(DAG, s, max_stacks=1) == [10], "the budget is a hard cap, not a hint"
assert epic.ready(DAG, s, max_stacks=2) == [10, 11], "#12 is third in line for two slots"
ok("the stack budget is a hard cap counted across the whole epic")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 run-engine/test_scripts.py`
Expected: FAIL with `AttributeError: module 'epic' has no attribute 'ready'`

- [ ] **Step 3: Write the implementation**

Append to `run-engine/epic.py`:

```python
def ready(dag: dict, states: dict, max_stacks: int) -> list[int]:
    """The children that may advance right now.

    A child is ready when its own run is still going, every dependency has reached
    PR open (the point at which a stacked child has a base branch to branch from),
    and — if it still needs a Docker stack — a slot is free.

    The budget is counted across the whole epic and decremented as this function
    hands out slots, so one call can never promise the same slot twice.
    """
    deps = {int(k): v for k, v in dag["deps"].items()}
    in_use = sum(1 for s in states.values() if (s or {}).get("stack_up"))
    out: list[int] = []
    for child in dag["order"]:
        current = states.get(child) or {}
        if current.get("status") != "running":
            continue
        if not all((states.get(d) or {}).get("pr") for d in deps.get(child, [])):
            continue
        if current.get("needs_stack") and not current.get("stack_up"):
            if in_use >= max_stacks:
                continue
            in_use += 1
        out.append(child)
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 run-engine/test_scripts.py`
Expected: PASS, six new `ok` lines total across Tasks 1-2.

- [ ] **Step 5: Commit**

```bash
git add run-engine/epic.py run-engine/test_scripts.py
git commit -m "feat: epic readiness under dependency and stack-budget constraints"
```

---

### Task 3: The `aiw epic` CLI

**Files:**
- Modify: `run-engine/epic.py`
- Modify: `run-engine/route.py` (the module tuple in `main()`)
- Test: `run-engine/test_scripts.py` (append)

**Interfaces:**
- Consumes: `parse_depends`, `build_dag`, `ready`; `shared.read_json`, `write_json`, `gh_json`, `run`, `warn`, `die`; `route.py`'s `cmd_paths` for `runs_dir`.
- Produces: `aiw epic split|init|next|status`, and the file `<runs_dir>/<owner>-<repo>-epic-<parent>/epic.json` with shape `{"parent": int, "slug": str, "children": [int], "dag": {...}, "max_stacks": int}`.

- [ ] **Step 1: Write the failing test**

Append to `run-engine/test_scripts.py`:

```python
# --------------------------------------------------------------------------- epic CLI

with tempfile.TemporaryDirectory() as tmp:
    epic_dir = os.path.join(tmp, "epic")
    os.makedirs(epic_dir)
    with open(os.path.join(epic_dir, "epic.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "parent": 42, "slug": "o/r", "children": [10, 11],
            "dag": {"order": [10, 11], "deps": {"10": [], "11": [10]}},
            "max_stacks": 2,
        }, fh)

    runs = os.path.join(tmp, "runs")
    for issue, ctx in ((10, {"pr": "https://x/1"}), (11, {})):
        d = os.path.join(runs, f"o-r-issue-{issue}")
        os.makedirs(d)
        with open(os.path.join(d, "run.json"), "w", encoding="utf-8") as fh:
            json.dump({"issue": issue, "stations": ["dev"], "currentIndex": 0,
                       "bounceCounts": {}, "status": "running", "trace": [],
                       "context": ctx, "classification": None, "specialists": []}, fh)

    proc = subprocess.run(
        [sys.executable, ROUTE, "epic", "next", epic_dir, "--runs-dir", runs],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout)
    assert got["ready"] == [10, 11], got
ok("aiw epic next reads every child ledger and prints who may advance")

with tempfile.TemporaryDirectory() as tmp:
    epic_dir, runs, repo = os.path.join(tmp, "e"), os.path.join(tmp, "runs"), os.path.join(tmp, "repo")
    os.makedirs(epic_dir); os.makedirs(repo)
    with open(os.path.join(epic_dir, "epic.json"), "w", encoding="utf-8") as fh:
        json.dump({"parent": 42, "slug": "o/r", "children": [10, 11],
                   "dag": {"order": [10, 11], "deps": {"10": [], "11": [10]}},
                   "max_stacks": 2}, fh)

    proc = subprocess.run(
        [sys.executable, ROUTE, "epic", "init", epic_dir, "--runs-dir", runs, "--repo", repo],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    for issue in (10, 11):
        led = json.load(open(os.path.join(runs, f"o-r-issue-{issue}", "run.json")))
        assert led["issue"] == issue and led["status"] == "running", led
    # 11 depends on 10, so its base is 10's branch and must NOT default to the repo base
    led11 = json.load(open(os.path.join(runs, "o-r-issue-11", "run.json")))
    assert led11["context"]["depends_on"] == "10", led11["context"]

    # re-running must not clobber a ledger that already exists
    again = subprocess.run(
        [sys.executable, ROUTE, "epic", "init", epic_dir, "--runs-dir", runs, "--repo", repo],
        capture_output=True, text=True,
    )
    assert again.returncode == 0, again.stderr
    assert "already" in again.stdout.lower(), again.stdout
ok("aiw epic init creates one ledger per child, records edges, and is idempotent")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 run-engine/test_scripts.py`
Expected: FAIL with `invalid choice: 'epic'` on stderr and a nonzero return code.

- [ ] **Step 3: Write the implementation**

Append to `run-engine/epic.py`:

```python
import json  # noqa: E402  (kept beside the I/O half, the top of this file is pure)
import os  # noqa: E402

from shared import (  # noqa: E402
    die, gh_json, load_ledger, read_json, save_ledger, warn, write_json,
)


def epic_path(epic_dir: str) -> str:
    return os.path.join(epic_dir, "epic.json")


def child_state(runs_dir: str, slug: str, issue: int) -> dict:
    """Read one child's ledger into the shape `ready()` wants.

    A child with no run directory yet has not been initialised; it reports as
    running with nothing done, which is exactly how it should be treated.
    """
    owner, _, repo = slug.partition("/")
    path = os.path.join(runs_dir, f"{owner}-{repo}-issue-{issue}", "run.json")
    if not os.path.isfile(path):
        return {"status": "running", "pr": False, "stack_up": False, "needs_stack": True}
    led = read_json(path)
    ctx = led.get("context") or {}
    return {
        "status": led.get("status", "running"),
        "pr": bool(ctx.get("pr")),
        "stack_up": ctx.get("stack") == "up",
        "needs_stack": ctx.get("stack") not in ("none",),
        "station": (led.get("stations") or [None])[led.get("currentIndex", 0)],
        "blocked_on": ctx.get("blocked_on"),
    }


def load_epic(epic_dir: str) -> dict:
    return read_json(epic_path(epic_dir))


def cmd_split(args) -> None:
    """Link children as sub-issues of the parent, then build and validate the DAG.

    The DAG is built from what is actually on GitHub, not from what the caller
    passed, so a child whose `Depends on:` line was edited after filing is picked
    up rather than silently ignored.
    """
    children = [int(c) for c in args.children.split(",") if c.strip()]
    for child in children:
        _, proc = gh_json(
            ["api", f"repos/{args.slug}/issues/{args.parent}/sub_issues",
             "-f", f"sub_issue_id={child}"],
        )
        if proc.returncode != 0:
            warn(f"could not link #{child} as a sub-issue: {(proc.stderr or '').strip()[:160]}")

    deps = {}
    for child in children:
        body, _ = gh_json(["issue", "view", str(child), "--repo", args.slug,
                           "--json", "body", "--jq", ".body"])
        deps[child] = [d for d in parse_depends(body if isinstance(body, str) else "")
                       if d in children]

    try:
        dag = build_dag(deps)
    except ValueError as exc:
        die(1, f"invalid epic: {exc}")

    write_json(epic_path(args.epic_dir), {
        "parent": args.parent, "slug": args.slug, "children": children,
        "dag": dag, "max_stacks": args.max_stacks,
    })
    print(json.dumps(dag, indent=2))


def cmd_init(args) -> None:
    """One run directory per child, created by the same code path `aiw init` uses.

    Idempotent on purpose: an epic is resumed far more often than it is started, and
    re-initialising over a live ledger would reset a child mid-flight.
    """
    import route  # local import: route imports this module, so this cannot be top-level

    epic = load_epic(args.epic_dir)
    owner, _, repo_name = epic["slug"].partition("/")
    runs_dir = args.runs_dir or die(2, "--runs-dir is required")
    deps = {int(k): v for k, v in epic["dag"]["deps"].items()}

    for child in epic["dag"]["order"]:
        run_dir = os.path.join(runs_dir, f"{owner}-{repo_name}-issue-{child}")
        if os.path.isfile(os.path.join(run_dir, "run.json")):
            print(f"#{child}: already initialised")
            continue
        route.main(["init", run_dir, "--issue", str(child), "--repo", args.repo]
                   + (["--mode", args.mode] if args.mode else []))
        ledger = load_ledger(run_dir)
        # The edge is recorded on the child so phase 5 knows what to base its branch on.
        # A child with no dependency keeps the repo's own base branch.
        if deps.get(child):
            ledger.context["depends_on"] = ",".join(str(d) for d in deps[child])
        ledger.context["epic"] = str(epic["parent"])
        save_ledger(run_dir, ledger)
        print(f"#{child}: initialised")


def cmd_next(args) -> None:
    epic = load_epic(args.epic_dir)
    runs_dir = args.runs_dir or die(2, "--runs-dir is required")
    states = {c: child_state(runs_dir, epic["slug"], c) for c in epic["children"]}
    print(json.dumps({
        "ready": ready(epic["dag"], states, epic.get("max_stacks", 2)),
        "states": {str(k): v for k, v in states.items()},
    }, indent=2))


def cmd_status(args) -> None:
    epic = load_epic(args.epic_dir)
    runs_dir = args.runs_dir or die(2, "--runs-dir is required")
    for child in epic["dag"]["order"]:
        st = child_state(runs_dir, epic["slug"], child)
        blocked = f"  blocked_on={st['blocked_on']}" if st.get("blocked_on") else ""
        print(f"#{child}  {st['status']:<10} station={st.get('station')}  "
              f"pr={'yes' if st['pr'] else 'no'}{blocked}")


def register(sub, add) -> None:
    p = sub.add_parser("epic", help="decompose and drive a parent issue's children")
    ops = p.add_subparsers(dest="op", required=True)

    q = ops.add_parser("split", help="link sub-issues and build the DAG")
    q.add_argument("epic_dir")
    q.add_argument("--parent", type=int, required=True)
    q.add_argument("--slug", required=True, help="owner/repo")
    q.add_argument("--children", required=True, help="comma-separated issue numbers")
    q.add_argument("--max-stacks", type=int, default=2)
    q.set_defaults(func=cmd_split)

    q = ops.add_parser("init", help="create one run directory per child")
    q.add_argument("epic_dir")
    q.add_argument("--runs-dir", required=True)
    q.add_argument("--repo", required=True, help="the main checkout")
    q.add_argument("--mode", help="full | lean; applied to every child")
    q.set_defaults(func=cmd_init)

    for name, fn, helptext in (
        ("next", cmd_next, "print which children may advance now"),
        ("status", cmd_status, "print every child's station, PR and blocked_on"),
    ):
        q = ops.add_parser(name, help=helptext)
        q.add_argument("epic_dir")
        q.add_argument("--runs-dir", help="where child run dirs live (default: aiw paths runs_dir)")
        q.set_defaults(func=fn)
```

In `run-engine/route.py`, add `epic` to the imports beside the others and to the module tuple in `main()`:

```python
    for module in (stack, worktree, threads, pr, ci, gitnexus, project, epic):
        module.register(sub, add)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 run-engine/test_scripts.py`
Expected: PASS. Also confirm the CLI is wired: `python3 run-engine/route.py epic --help` lists `split`, `next`, `status`.

- [ ] **Step 5: Commit**

```bash
git add run-engine/epic.py run-engine/route.py run-engine/test_scripts.py
git commit -m "feat: aiw epic split/next/status"
```

---

### Task 4: The epic board

**Files:**
- Modify: `run-engine/project.py`
- Test: `run-engine/test_scripts.py` (append)

**Interfaces:**
- Consumes: `shared.gh_json`, `shared.warn`.
- Produces: `find_view(views: list[dict], name: str) -> dict | None` and `aiw project board <slug> <parent> --title <t> --children <n>,<n>`.

- [ ] **Step 1: Write the failing test**

Append to `run-engine/test_scripts.py`:

```python
# --------------------------------------------------------------------------- epic board

VIEWS = [{"id": "V1", "name": "Board"}, {"id": "V2", "name": "Epic #42 — Billing"}]
assert project.find_view(VIEWS, "Epic #42 — Billing")["id"] == "V2"
assert project.find_view(VIEWS, "Epic #43 — Other") is None
assert project.find_view([], "Epic #42 — Billing") is None
ok("an existing epic board is found by name, so a resume never creates a second")

assert project.board_name(42, "Billing overhaul") == "Epic #42 — Billing overhaul"
assert project.board_name(42, "x" * 200).startswith("Epic #42 — ")
assert len(project.board_name(42, "x" * 200)) <= 80, "view names must stay readable"
ok("board names are derived from the parent and bounded in length")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 run-engine/test_scripts.py`
Expected: FAIL with `AttributeError: module 'project' has no attribute 'find_view'`

- [ ] **Step 3: Write the implementation**

Append to `run-engine/project.py`:

```python
VIEWS_QUERY = """
query($p:ID!){ node(id:$p){ ... on ProjectV2{ views(first:50){ nodes{ id name } } } } }
"""

CREATE_VIEW = """
mutation($p:ID!,$n:String!){
  createProjectV2View(input:{projectId:$p,name:$n,layout:BOARD_LAYOUT}){ projectV2View{ id } } }
"""

SET_FILTER = """
mutation($v:ID!,$f:String!){
  updateProjectV2View(input:{viewId:$v,filter:$f}){ projectV2View{ id filter } } }
"""

DELETE_VIEW = """
mutation($v:ID!){ deleteProjectV2View(input:{viewId:$v}){ projectV2View{ id } } }
"""


def board_name(parent: int, title: str) -> str:
    """Stable, human-readable, and bounded — this string is the idempotency key."""
    prefix = f"Epic #{parent} — "
    return prefix + (title or "")[: 80 - len(prefix)]


def find_view(views: list, name: str):
    for view in views or []:
        if view.get("name") == name:
            return view
    return None


def cmd_board(args) -> None:
    """Create (or find) the epic's board view. Best-effort: never exits nonzero.

    The board filters on `label:epic-<n>`, never `parent-issue:` — the Projects API
    accepts ANY filter string without validating it (a deliberately bogus qualifier
    round-trips unchanged), so an unverifiable filter would fail as a silently empty
    board, which is indistinguishable from an epic where nothing has started.
    """
    data, _ = gh_json(["api", "graphql", "-f", f"query={ITEMS_QUERY}",
                       "-f", f"o={args.slug.split('/')[0]}",
                       "-f", f"r={args.slug.split('/')[1]}", "-F", f"n={args.parent}"])
    items = ((((data or {}).get("data") or {}).get("repository") or {})
             .get("issue") or {}).get("projectItems") or {}
    nodes = items.get("nodes") or []
    if not nodes:
        print("parent is not on any project — no board")
        return
    project_id = ((nodes[0].get("project") or {}).get("id"))

    name = board_name(args.parent, args.title)
    views, _ = gh_json(["api", "graphql", "-f", f"query={VIEWS_QUERY}", "-f", f"p={project_id}"])
    existing = find_view(
        ((((views or {}).get("data") or {}).get("node") or {}).get("views") or {}).get("nodes"),
        name,
    )
    if existing:
        print(f"board already exists: {name}")
        return

    created, proc = gh_json(["api", "graphql", "-f", f"query={CREATE_VIEW}",
                             "-f", f"p={project_id}", "-f", f"n={name}"])
    view = (((created or {}).get("data") or {}).get("createProjectV2View") or {}).get("projectV2View")
    if not view:
        # A closed project reports UNPROCESSABLE here. That is a normal state, not a bug.
        warn(f"could not create the epic board: {(proc.stderr or '').strip()[:200]}")
        return

    _, fproc = gh_json(["api", "graphql", "-f", f"query={SET_FILTER}",
                        "-f", f"v={view['id']}", "-f", f"f=label:epic-{args.parent}"])
    if fproc.returncode != 0:
        # An unfiltered view shows the ENTIRE project under an epic's name, which is
        # worse than no board. Remove it rather than leave it misleading.
        gh_json(["api", "graphql", "-f", f"query={DELETE_VIEW}", "-f", f"v={view['id']}"])
        warn("could not set the board filter; removed the unfiltered view")
        return
    print(f"created board: {name}")
```

Extend `register` in `project.py` — the existing `project-status` parser stays exactly as it is, and a second parser is added:

```python
    b = sub.add_parser("project-board", help="create the per-epic board view (best-effort)")
    b.add_argument("slug", help="owner/repo")
    b.add_argument("parent", type=int)
    b.add_argument("--title", default="", help="parent issue title, for the view name")
    b.set_defaults(func=cmd_board)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 run-engine/test_scripts.py`
Expected: PASS. Then confirm best-effort behaviour holds:

```bash
PATH=/nonexistent python3 run-engine/route.py project-board o/r 42 --title x; echo "exit=$?"
```
Expected: `exit=0` with a warning on stderr.

- [ ] **Step 5: Commit**

```bash
git add run-engine/project.py run-engine/test_scripts.py
git commit -m "feat: create the per-epic board view, filtered by label"
```

---

### Task 5: `/gh-issue` epic mode

**Files:**
- Modify: `commands/gh-issue.md`

This task is prose, so it has no unit test. Its check is the manual dry-run in Step 3 — run it and read the output rather than assuming.

- [ ] **Step 1: Add the epic-detection branch**

Insert a new step between the existing steps 3 and 4 of `commands/gh-issue.md`:

```markdown
3.5. **Epic check.** If the description covers more than one independently-shippable
   outcome, or is large enough that one PR would not be reviewable in a sitting, this
   is an epic. Do not split silently — propose the split with `AskUserQuestion`, listing
   each proposed child as one line (title + the one outcome it delivers) plus the
   dependency edges you intend to declare. On approval, go to step 4-EPIC instead of
   step 4. On rejection, file one issue as normal.

   More than ~8 children is a decomposition problem, not a bigger epic: say so and
   propose a coarser split rather than launching 20 pipelines.
```

- [ ] **Step 2: Add the epic creation step**

Insert after the existing step 4:

```markdown
### 4-EPIC. Create the parent and its children

1. Create the **parent** with the BRD as its body, labelled `epic`. It is a container:
   it needs no acceptance criteria of its own.
2. For each child, write a **complete, independently DoR-satisfying** issue body — the
   same section list as step 4, with the parent's context **inlined, never referenced**.
   `run-researcher` scores each child on its own and blocks the run on a gap, so a child
   whose Context section says "see parent" dies before its worktree is created.

   Each child is one **vertical slice** — one thin end-to-end outcome, never a layer.
   Horizontal slices ("all the models") maximize file overlap, which serializes the DAG,
   and none of them has acceptance criteria that can be verified on their own.

   Where a child depends on a sibling, add a line on its own:

   ```
   Depends on: #<n>, #<n>
   ```

   Edges may only point at siblings in this epic.
3. Label every child `epic-<parent>` in addition to its normal labels. This is what the
   epic board filters on, and what makes the children findable with
   `gh issue list --label epic-<parent>` when there is no project.
4. Link and validate:

   ```bash
   aiw epic split "<runs_dir>/<owner>-<repo>-epic-<parent>" \
     --parent <parent> --slug <owner>/<repo> --children <n>,<n>,<n>
   ```

   Exit 1 means the edges do not form a DAG — a cycle, a self-edge, or an edge pointing
   outside the epic. Fix the offending child's `Depends on:` line with `gh issue edit`
   and re-run. Do not proceed with an invalid DAG: the ordering is what keeps a stacked
   child from branching off a base that does not exist yet.
5. Add every child to the same project as the parent (step 6's calls, once per child),
   then create the board:

   ```bash
   aiw project-board <owner>/<repo> <parent> --title "<parent title>"
   ```

   Best-effort — it always exits 0. A parent on no project, a closed project, or a
   missing `project` scope means no board and one warning line.
6. Return the parent URL, the child URLs in dependency order, and the board name.
```

- [ ] **Step 3: Verify the DAG validation actually rejects a bad epic**

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, "run-engine")
import epic
for bad in ({1: [2], 2: [1]}, {1: [99]}, {1: [1]}):
    try:
        epic.build_dag(bad); print("NOT REJECTED:", bad)
    except ValueError as e:
        print("rejected:", e)
PY
```
Expected: three `rejected:` lines, no `NOT REJECTED`.

- [ ] **Step 4: Commit**

```bash
git add commands/gh-issue.md
git commit -m "feat: epic mode in /gh-issue — parent, DoR-complete children, declared edges"
```

---

### Task 6: `/run-issue` epic mode

**Files:**
- Modify: `commands/run-issue.md`

Prose again; its check is the Step 3 dry-run.

- [ ] **Step 1: Add epic detection to phase 0**

Insert into `commands/run-issue.md` phase 0, after the issue is resolved:

```markdown
5.5. **Epic check.** `gh api repos/{owner}/{repo}/issues/<n>/sub_issues`. A non-empty
   array means this is an epic parent — go to **Epic mode** below instead of the
   single-issue phases. An empty array is the ordinary path.

   Running `/run-issue` on a **child** stays legal and behaves as a normal single-issue
   run. Its `Depends on:` line names a base branch that may not exist yet, so check with
   `git ls-remote --heads origin <dep-branch>`; if it is absent, say so and ask whether to
   base on the default branch instead. Never guess a substitute base — the same rule
   phase 8 applies when `origin/<base>` has gone missing.
```

- [ ] **Step 2: Add the Epic mode section**

Insert as a new top-level section before `## Rules`:

```markdown
## Epic mode

One session, N child ledgers, three gates total. Children are not nested `/run-issue`s —
subagents do not nest — so this session walks the roster across all ready children at
once, exactly as phase 6 spawns the specialist panel in one message.

1. **Init.** `aiw epic init "<runs_dir>/<owner>-<repo>-epic-<n>" --runs-dir "<runs_dir>"
   --repo <main-checkout> [--mode lean]` creates a run directory per child. Each is an ordinary ledger; every existing guard and post-check applies to
   it unchanged.
2. **Plan every child.** Dispatch one `run-planner` per child, **all in one message**.
   Write each envelope to its own child run dir and route it with `aiw route`.
3. **GATE 1 — the decomposition and every plan, once.** Print, in order: the DAG as a
   readable order with the parallel groups marked; each child's DoR gaps and assumptions;
   then every plan in full. Then `AskUserQuestion`: **Approve all** · **Revise child N**
   (re-plan that child only, re-print, re-gate) · **Drop child N** (refused if anything
   depends on it unless its dependents are dropped too) · **Abort**.
4. **The relay.** Until every child is done or parked, loop:

   ```bash
   aiw epic next "<runs_dir>/<owner>-<repo>-epic-<n>" --runs-dir "<runs_dir>"
   ```

   Dispatch every ready child's next station **in one message**, route each envelope, and
   repeat. Children desynchronize immediately and that is correct — child 3 can be in
   review while child 5 writes tests. Nothing waits for a wave.

   A dependent child's `base_branch` is its dependency's branch, not the default branch.
   Phase 8's existing fetch-merge-test handles the rebase when that branch moves;
   `aiw pr open --base` takes it directly.

   **Never raise a stack yourself.** `aiw epic next` withholds a child that needs one
   when the budget is spent; a child's stack comes down via `aiw stack down` as soon as
   it clears the CI gate, which is what frees the slot.
5. **A blocker parks its child, it does not stop the epic.** Record it and keep going with
   everything else.
6. **GATE 2a — blockers, collected.** Fires **once**, when no further progress is possible
   without a human: everything else has finished, or a parked child is blocking the DAG.
   Print every blocker together with its child and thread URL, then gate as phase 7 does.
7. **GATE 2 — one epic report.** Per child: PR, CI verdict, open threads, runtime
   verification, anything carried forward. Then:
   - **Parked children**, and what they are waiting on.
   - **Children that never started**, named explicitly with the failed dependency that
     blocked them. A child silently absent from a list of twelve is how a third of an epic
     turns out never to have been built.
   - **Children re-targeted to the default branch** because their base was dropped or died
     — the plan assumed a dependency that no longer exists, and that assumption may have
     been load-bearing.
   - **The merge order**, explicitly. Merging is manual and these PRs are stacked; merged
     out of order they have to be unpicked by hand.
   - The board name, if one was created.
8. **The epic does not grind.** Phase 10 is skipped: `pr-grind` holds a session-local
   `Monitor` and `ScheduleWakeup` and there cannot be eight. Tell the user to run
   `/pr-grind <url>` per PR.
```

- [ ] **Step 3: Verify epic detection distinguishes a parent from a plain issue**

```bash
gh api repos/masnun-siam/ai-workflow/issues/2/sub_issues --jq 'length'
```
Expected: `0` — issue #2 is not an epic parent, so the ordinary path is taken. A parent created by Task 5 returns its child count.

- [ ] **Step 4: Commit**

```bash
git add commands/run-issue.md
git commit -m "feat: epic mode in /run-issue — relay, collected blockers, one report"
```

---

## Notes for the executor

- **Do not start before PR #3 lands.** Every task imports from `shared.py` and follows the
  `register(sub, add)` shape that PR introduces.
- **`route.main()` is imported locally inside `cmd_init`**, not at module top level —
  `route.py` imports `epic`, so a top-level import would be circular.
- **The only end-to-end test is a real epic.** These tests cover the pure logic — DAG,
  readiness, budget, name derivation. Ordering against real GitHub state is proven by
  running one small epic with two children, one dependent, and checking that the second
  child's branch is based on the first's.
