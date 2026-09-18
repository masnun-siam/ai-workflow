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


def register(sub, add) -> None:
    p = sub.add_parser("project-status", help="move an issue's Projects v2 Status (best-effort)")
    p.add_argument("slug", help="owner/repo")
    p.add_argument("issue", type=int)
    p.add_argument("status", help='target status name, e.g. "In Progress"')
    p.set_defaults(func=cmd_set)
