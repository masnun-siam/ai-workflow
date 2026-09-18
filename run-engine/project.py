"""GitHub Projects (v2) status: `route project-status`.

Three GraphQL queries written out in the orchestrator prose, for a step that is
best-effort in every case: if the issue isn't on a board, or the field or option
names don't match, the run continues. So this NEVER exits nonzero — the
orchestrator's standing reflex is "nonzero means stop the run", and a board that
calls its column "On Review" must not be able to trigger it.
"""

from __future__ import annotations

import re

from shared import gh_json, warn

ITEMS_QUERY = """
query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){
  issue(number:$n){ projectItems(first:10){ nodes{ id project{ id title }
    fieldValueByName(name:"Status"){ ... on ProjectV2ItemFieldSingleSelectValue{ name } } } } } } }
"""

FIELD_QUERY = """
query($p:ID!){ node(id:$p){ ... on ProjectV2{
  field(name:"Status"){ ... on ProjectV2SingleSelectField{ id options{ id name } } } } } }
"""

SET_MUTATION = """
mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){
  updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,
    value:{singleSelectOptionId:$o}}){ projectV2Item{ id } } }
"""


# Words that carry no meaning in a column name, so "In Review" and "On Review"
# compare as the same thing — which is the exact mismatch the prose called out.
FILLER = {"in", "on", "at", "to", "the", "is", "be", "for"}


def _words(name: str) -> set:
    return {w for w in re.split(r"[^a-z0-9]+", (name or "").lower()) if w and w not in FILLER}


def match_option(options: list[dict], target: str) -> dict | None:
    """Exact name first, then the best significant-word overlap.

    A board that calls the column "On Review" still gets updated when this pipeline
    asks for "In Review". A plain substring test does not cover that pair — neither
    string contains the other — which is why the comparison is on words.
    """
    for opt in options:
        if opt.get("name") == target:
            return opt
    wanted = _words(target)
    if not wanted:
        return None
    best, best_score = None, 0
    for opt in options:
        score = len(wanted & _words(opt.get("name")))
        if score > best_score:
            best, best_score = opt, score
    return best


def cmd_set(args) -> None:
    owner, _, repo = args.slug.partition("/")
    data, proc = gh_json(["api", "graphql", "-f", f"query={ITEMS_QUERY}", "-f", f"o={owner}",
                          "-f", f"r={repo}", "-F", f"n={args.issue}"])
    items = ((((data or {}).get("data") or {}).get("repository") or {})
             .get("issue") or {}).get("projectItems") or {}
    nodes = items.get("nodes") or []
    if not nodes:
        print("issue is not on any project — nothing to update")
        return

    for item in nodes:
        project = item.get("project") or {}
        pid = project.get("id")
        field, _ = gh_json(["api", "graphql", "-f", f"query={FIELD_QUERY}", "-f", f"p={pid}"])
        spec = (((field or {}).get("data") or {}).get("node") or {}).get("field") or {}
        option = match_option(spec.get("options") or [], args.status)
        if not spec.get("id") or not option:
            warn(f"no Status option matching {args.status!r} on {project.get('title')!r}")
            continue
        _, mproc = gh_json(["api", "graphql", "-f", f"query={SET_MUTATION}", "-f", f"p={pid}",
                            "-f", f"i={item['id']}", "-f", f"f={spec['id']}",
                            "-f", f"o={option['id']}"])
        if mproc.returncode != 0:
            warn(f"could not set status on {project.get('title')!r}: {(mproc.stderr or '').strip()[:160]}")
        else:
            print(f"{project.get('title')}: Status -> {option['name']}")


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


def register(sub, add) -> None:
    p = sub.add_parser("project-status", help="move an issue's Projects v2 Status (best-effort)")
    p.add_argument("slug", help="owner/repo")
    p.add_argument("issue", type=int)
    p.add_argument("status", help='target status name, e.g. "In Progress"')
    p.set_defaults(func=cmd_set)

    b = sub.add_parser("project-board", help="create the per-epic board view (best-effort)")
    b.add_argument("slug", help="owner/repo")
    b.add_argument("parent", type=int)
    b.add_argument("--title", default="", help="parent issue title, for the view name")
    b.set_defaults(func=cmd_board)
