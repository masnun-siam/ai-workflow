"""PR review threads: `route threads list|resolve`.

The `reviewThreads` query and the `resolveReviewThread` mutation were written out
verbatim in four places — commands/pr-fix-comments.md, commands/run-issue.md (twice),
skills/pr-grind/SKILL.md — with agents/run-fixer.md telling its agent to fetch node
ids "alongside the comment". Four copies of a GraphQL query is four chances for one
of them to drift from the schema.

checks.py's check_fixer_post calls list_threads() directly; it must not become a
fifth copy.
"""

from __future__ import annotations

import json

from shared import die, gh_json, parse_pr_ref, warn

LIST_QUERY = """
query($owner:String!,$repo:String!,$number:Int!,$cursor:String){
  repository(owner:$owner,name:$repo){
    pullRequest(number:$number){
      reviewThreads(first:100, after:$cursor){
        pageInfo{ hasNextPage endCursor }
        nodes{
          id isResolved isOutdated path line
          comments(first:1){ nodes{ databaseId url body } }
        }
      }
    }
  }
}
"""

RESOLVE_MUTATION = """
mutation($id:ID!){ resolveReviewThread(input:{threadId:$id}){ thread{ id isResolved } } }
"""


def list_threads(owner: str, repo: str, number: int, cwd=None) -> list[dict]:
    """Every review thread on the PR, flattened to what callers actually match on.

    `comment_id` is the REST databaseId of the thread's FIRST comment — that is the
    id every call site matches against, because the REST comment endpoints hand back
    databaseIds and the resolve mutation needs the GraphQL node id.
    """
    out: list[dict] = []
    cursor = None
    while True:
        args = ["api", "graphql", "-f", f"query={LIST_QUERY}",
                "-f", f"owner={owner}", "-f", f"repo={repo}", "-F", f"number={number}"]
        if cursor:
            args += ["-f", f"cursor={cursor}"]
        data, proc = gh_json(args, cwd=cwd)
        if data is None:
            die(1, "could not read review threads: " + (proc.stderr or proc.stdout or "").strip()[:300])
        block = (((data.get("data") or {}).get("repository") or {})
                 .get("pullRequest") or {}).get("reviewThreads") or {}
        for node in block.get("nodes") or []:
            first = ((node.get("comments") or {}).get("nodes") or [{}])[0]
            out.append({
                "node_id": node.get("id"),
                "is_resolved": bool(node.get("isResolved")),
                "is_outdated": bool(node.get("isOutdated")),
                "comment_id": first.get("databaseId"),
                "url": first.get("url"),
                "path": node.get("path"),
                "line": node.get("line"),
            })
        page = block.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            return out
        cursor = page.get("endCursor")


def thread_for_comment(threads: list[dict], comment_id) -> dict | None:
    """The match every call site describes in prose: thread whose first comment is
    the one you just replied to."""
    try:
        wanted = int(comment_id)
    except (TypeError, ValueError):
        return None
    for t in threads:
        if t.get("comment_id") == wanted:
            return t
    return None


def resolve_thread(node_id: str, cwd=None) -> tuple[bool, str]:
    data, proc = gh_json(
        ["api", "graphql", "-f", f"query={RESOLVE_MUTATION}", "-f", f"id={node_id}"], cwd=cwd
    )
    if data is None or (data.get("errors")):
        return False, (proc.stderr or json.dumps(data or {}))[:200]
    thread = (((data.get("data") or {}).get("resolveReviewThread") or {}).get("thread") or {})
    return bool(thread.get("isResolved")), ""


def cmd_list(args) -> None:
    owner, repo, number = parse_pr_ref(args.pr)
    threads = list_threads(owner, repo, number)
    if args.open_only:
        threads = [t for t in threads if not t["is_resolved"]]
    if args.for_comment is not None:
        match = thread_for_comment(threads, args.for_comment)
        threads = [match] if match else []
    print(json.dumps(threads, indent=2))


def cmd_resolve(args) -> None:
    """Per-thread non-fatal: the prose everywhere says warn and continue if one
    fails, because an unresolvable thread is never worth stopping a run over."""
    failed = 0
    for node_id in args.node_ids:
        ok, err = resolve_thread(node_id)
        if ok:
            print(f"resolved {node_id}")
        else:
            failed += 1
            warn(f"could not resolve {node_id}: {err}")
    if failed and failed == len(args.node_ids):
        raise SystemExit(1)


def register(sub, add) -> None:
    p = sub.add_parser("threads", help="list or resolve a PR's review threads")
    ops = p.add_subparsers(dest="op", required=True)

    q = ops.add_parser("list", help="print every review thread as JSON")
    q.add_argument("pr", help="PR url, owner/repo#N, or N")
    q.add_argument("--open-only", action="store_true", help="only threads that are still open")
    q.add_argument("--for-comment", type=int, default=None,
                   help="only the thread whose first comment has this REST id")
    q.set_defaults(func=cmd_list)

    q = ops.add_parser("resolve", help="resolve one or more threads by node id")
    q.add_argument("node_ids", nargs="+")
    q.set_defaults(func=cmd_resolve)
