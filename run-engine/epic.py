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
        # A stack that failed to come up will never reach "up" either, and stack.py
        # continues that run with test_cmd unavailable rather than retrying forever —
        # so a failed stack must not hold a budget slot, or it starves its siblings.
        "needs_stack": ctx.get("stack") not in ("none", "failed"),
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
        body, proc = gh_json(["issue", "view", str(child), "--repo", args.slug,
                              "--json", "body", "--jq", ".body"])
        if proc.returncode != 0:
            die(1, f"could not read #{child}'s body to parse its dependencies: "
                   f"{(proc.stderr or '').strip()[:160]}")
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
