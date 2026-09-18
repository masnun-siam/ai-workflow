"""CI status: `route ci status`.

Phase 8.5 and pr-grind's rail 2 described the same `gh pr checks` handling twice.
This is the polling half only.

Flake-vs-real classification deliberately stays OUT. That is run-ci's entire job and
the judgment call the pipeline most needs a model for — a script that guessed it
would be the thing that reruns a genuine break until it ships.
"""

from __future__ import annotations

import json
import time

from shared import gh_json, parse_pr_ref, run

POLL_SECONDS = 30


def state_of(rows: list[dict]) -> str:
    """Pending beats failing: a check still running is not a verdict, and acting on a
    half-landed round is what rail 2 exists to avoid."""
    buckets = {(r.get("bucket") or "").lower() for r in rows}
    if "pending" in buckets:
        return "pending"
    return "red" if "fail" in buckets else "green"


def run_id_of(link: str) -> str:
    return link.split("/runs/", 1)[1].split("/")[0] if "/runs/" in (link or "") else ""


def snapshot(owner: str, repo: str, number: int) -> dict:
    slug = f"{owner}/{repo}"
    head, _ = gh_json(["pr", "view", str(number), "--repo", slug, "--json", "headRefOid",
                       "--jq", ".headRefOid"])
    rows, proc = gh_json(["pr", "checks", str(number), "--repo", slug, "--json",
                          "name,state,bucket,link"])
    if rows is None:
        # `gh pr checks` exits nonzero when checks are red AND when none exist.
        # "no checks configured" is green for our purposes; anything else is an error.
        if "no checks" in ((proc.stderr or "") + (proc.stdout or "")).lower():
            return {"state": "green", "head_sha": head, "failing": [], "note": "no checks configured"}
        rows = []
    failing = [r for r in rows if (r.get("bucket") or "").lower() == "fail"]
    return {"state": state_of(rows), "head_sha": head, "failing": failing}


def failing_detail(slug: str, failing: list[dict]) -> list[dict]:
    """Hand over the failing job's log. Reading it is the caller's job."""
    out = []
    for check in failing:
        link = check.get("link") or ""
        run_id = run_id_of(link)
        excerpt = ""
        if run_id:
            proc = run(["gh", "run", "view", run_id, "--repo", slug, "--log-failed"], timeout=300)
            excerpt = (proc.stdout or proc.stderr or "").strip()[-4000:]
        out.append({"name": check.get("name"), "run_id": run_id, "link": link,
                    "log_excerpt": excerpt})
    return out


def cmd_status(args) -> None:
    owner, repo, number = parse_pr_ref(args.pr)
    slug = f"{owner}/{repo}"
    deadline = time.monotonic() + args.timeout
    result = snapshot(owner, repo, number)
    while args.watch and result["state"] == "pending" and time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
        result = snapshot(owner, repo, number)
    if result["state"] == "pending" and args.watch:
        result["note"] = f"wall-clock cap of {args.timeout}s expired with checks still pending"
    result["failing"] = failing_detail(slug, result.get("failing") or [])
    print(json.dumps(result, indent=2))


def register(sub, add) -> None:
    p = sub.add_parser("ci", help="report a PR's check status")
    ops = p.add_subparsers(dest="op", required=True)
    q = ops.add_parser("status", help="green|red|pending plus the failing jobs' logs")
    q.add_argument("pr", help="PR url, owner/repo#N, or N")
    q.add_argument("--watch", action="store_true", help="poll until nothing is pending")
    q.add_argument("--timeout", type=int, default=1200, help="wall-clock cap for --watch")
    q.set_defaults(func=cmd_status)
