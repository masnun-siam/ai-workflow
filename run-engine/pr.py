"""Opening the PR: `route pr open`.

Phase 5 is the most order-sensitive procedure in the orchestrator, and two of its
facts are load-bearing and easy to lose in prose:

  * createLinkedBranch CREATES the ref from an issue, so it must run BEFORE the
    push. Called after, it silently no-ops (linkedBranch: null, no GraphQL error).
  * A null linkedBranch with no `errors` key is a FAILURE, not a success.

Pre-push hook triage stays with the orchestrator: deciding whether a failing test
belongs to the test root, to this PR's dev phase, or to neither is judgment, and
this module has none. It surfaces the hook output and exits 1.
"""

from __future__ import annotations

from shared import die, gh_json, load_ledger, print_written, record, repo_of, run, warn

LINK_MUTATION = """
mutation($i:ID!,$b:String!,$r:ID!,$o:GitObjectID!){
  createLinkedBranch(input:{issueId:$i, name:$b, repositoryId:$r, oid:$o}){ linkedBranch{ id } }
}
"""

VERIFY_QUERY = """
query($owner:String!,$repo:String!,$number:Int!){
  repository(owner:$owner,name:$repo){
    issue(number:$number){ linkedBranches(first:5){ nodes{ ref{ name } } } }
  }
}
"""


def link_branch(repo_dir: str, issue: int, branch: str) -> bool:
    issue_id, _ = gh_json(["issue", "view", str(issue), "--json", "id", "--jq", ".id"], cwd=repo_dir)
    repo_id, _ = gh_json(["repo", "view", "--json", "id", "--jq", ".id"], cwd=repo_dir)
    head = run(["git", "rev-parse", "HEAD"], cwd=repo_dir)
    if not issue_id or not repo_id or head.returncode != 0:
        warn("could not resolve issue/repo node ids or head oid; skipping branch link")
        return False
    data, proc = gh_json(
        ["api", "graphql", "-f", f"query={LINK_MUTATION}", "-f", f"i={issue_id}",
         "-f", f"b={branch}", "-f", f"r={repo_id}", "-f", f"o={head.stdout.strip()}"],
        cwd=repo_dir,
    )
    linked = (((data or {}).get("data") or {}).get("createLinkedBranch") or {}).get("linkedBranch")
    if not linked or not linked.get("id"):
        warn("createLinkedBranch returned no branch: " + (proc.stderr or "").strip()[:200])
        return False
    return True


def linked_ok(repo_dir: str, owner: str, name: str, issue: int) -> bool:
    data, _ = gh_json(
        ["api", "graphql", "-f", f"query={VERIFY_QUERY}", "-f", f"owner={owner}",
         "-f", f"repo={name}", "-F", f"number={issue}"], cwd=repo_dir)
    nodes = ((((data or {}).get("data") or {}).get("repository") or {})
             .get("issue") or {}).get("linkedBranches") or {}
    return bool(nodes.get("nodes"))


def closes_ok(repo_dir: str, number: int) -> bool:
    data, _ = gh_json(["pr", "view", str(number), "--json", "closingIssuesReferences"], cwd=repo_dir)
    return bool((data or {}).get("closingIssuesReferences"))


def cmd_open(args) -> None:
    ledger = load_ledger(args.run_dir)
    repo_dir = repo_of(ledger, args.repo)
    branch = ledger.context.get("branch")
    base = args.base or ledger.context.get("base_branch")
    issue = ledger.issue
    if not branch or not base:
        die(2, "need `branch` and `base_branch` in the ledger — run `route worktree create` first")

    linked = link_branch(repo_dir, issue, branch)

    proc = run(["git", "push", "-u", "origin", branch], cwd=repo_dir, timeout=600)
    if proc.returncode != 0:
        # Exits 1 with the hook's own words: the orchestrator triages whether the
        # failing test is in the test root, in this PR's diff, or neither.
        die(1, "push failed:\n" + (proc.stderr or proc.stdout or "").strip())

    create = ["pr", "create", "--base", base, "--body-file", args.body_file]
    if args.draft:
        create.append("--draft")
    if args.title:
        create += ["--title", args.title]
    else:
        create.append("--fill")
    created = run(["gh", *create], cwd=repo_dir, timeout=300)
    if created.returncode != 0:
        die(1, "gh pr create failed: " + (created.stderr or "").strip()[:400])
    url = (created.stdout or "").strip().splitlines()[-1]
    number, _ = gh_json(["pr", "view", url, "--json", "number", "--jq", ".number"], cwd=repo_dir)

    slug, _ = gh_json(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], cwd=repo_dir)
    owner, _, name = (slug or "/").partition("/")

    link = "ok"
    if not (linked and linked_ok(repo_dir, owner, name, issue)) or not closes_ok(repo_dir, int(number or 0)):
        # One retry, then a fallback trail. Never stop the run over a missing link.
        run(["gh", "pr", "edit", str(number), "--body-file", args.body_file], cwd=repo_dir)
        link_branch(repo_dir, issue, branch)
        if not linked_ok(repo_dir, owner, name, issue) or not closes_ok(repo_dir, int(number or 0)):
            warn("issue link could not be established; posting a fallback comment")
            run(["gh", "issue", "comment", str(issue), "--body", f"PR: {url}"], cwd=repo_dir)
            link = "FAILED"

    print_written(record(args.run_dir, ledger, pr=url, pr_number=str(number or ""), link=link))


def register(sub, add) -> None:
    p = sub.add_parser("pr", help="open the PR and link it to the issue")
    ops = p.add_subparsers(dest="op", required=True)
    q = ops.add_parser("open", help="link the branch, push, create the PR, verify both links")
    q.add_argument("run_dir")
    q.add_argument("--body-file", required=True, help="PR body; must contain `Closes #<n>`")
    q.add_argument("--title", help="PR title (default: --fill from the commits)")
    q.add_argument("--base", help="base branch (default: base_branch from the ledger)")
    q.add_argument("--draft", action="store_true", help="degraded finish: open it as a draft")
    q.add_argument("--repo", help="worktree root (default: ledger context, else cwd)")
    q.set_defaults(func=cmd_open)
