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
