"""Read-only pull request overview for the UI popup: description, conversation, files with patches, commits, checks.

Same approach as ui_issue: GitHub renders the markdown (`application/vnd.github.html+json`), the UI only
displays it. Patches are capped so one huge PR cannot turn the popup into a multi-megabyte payload.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from shared import gh_json
from ui_issue import _HTML, _links_out, _user, valid  # noqa: F401  (valid is re-exported for the server route)
from ui_status import _check

PAGE = 100  # one page of files / commits / comments; a longer list says so and points at GitHub
MAX_PATCH = 60_000  # per file, chars
MAX_PATCH_TOTAL = 500_000  # across files, chars


def _state(pr: dict) -> str:
    if pr.get("merged") or pr.get("merged_at"):
        return "merged"
    return "draft" if pr.get("draft") and pr.get("state") == "open" else pr.get("state") or "open"


def _files(raw: list) -> list:
    budget, out = MAX_PATCH_TOTAL, []
    for f in raw:
        patch = f.get("patch")
        if patch is not None and (len(patch) > MAX_PATCH or len(patch) > budget):
            patch = None
            truncated = True
        else:
            truncated = False
            budget -= len(patch or "")
        out.append({"name": f.get("filename"), "from": f.get("previous_filename"), "status": f.get("status"),
                    "additions": f.get("additions", 0), "deletions": f.get("deletions", 0),
                    "patch": patch, "patch_cut": truncated})
    return out


def _conversation(comments: list, reviews: list) -> list:
    """Comments and review verdicts interleaved by time; an empty 'commented' review is just inline noise."""
    items = [{"kind": "comment", "author": _user(c.get("user")), "at": c.get("created_at"), "body_html": _links_out(c.get("body_html"))}
             for c in comments]
    items += [{"kind": "review", "verdict": r.get("state"), "author": _user(r.get("user")), "at": r.get("submitted_at"),
               "body_html": _links_out(r.get("body_html"))}
              for r in reviews if r.get("state") != "PENDING" and (r.get("body_html") or r.get("state") != "COMMENTED")]
    return sorted(items, key=lambda i: i["at"] or "")


def _checks(rollup) -> list | None:
    if not isinstance(rollup, dict):
        return None
    out = []
    for item in rollup.get("statusCheckRollup") or []:
        name, link, bucket = _check(item)
        out.append({"name": name, "link": link, "bucket": bucket})
    return out


def shape(pr: dict, files: list, commits: list, comments: list, reviews: list, rollup) -> dict:
    """Pure: the REST payloads -> the dict the popup renders."""
    ms = pr.get("milestone") or {}
    return {
        "number": pr.get("number"), "title": pr.get("title"), "url": pr.get("html_url"), "state": _state(pr),
        "author": _user(pr.get("user")), "created_at": pr.get("created_at"),
        "head": (pr.get("head") or {}).get("ref"), "base": (pr.get("base") or {}).get("ref"),
        "labels": [{"name": x.get("name"), "color": x.get("color")} for x in pr.get("labels") or [] if isinstance(x, dict)],
        "assignees": [_user(a) for a in pr.get("assignees") or []],
        "milestone": ms.get("title"),
        "body_html": _links_out(pr.get("body_html")),
        "additions": pr.get("additions", 0), "deletions": pr.get("deletions", 0),
        "file_count": pr.get("changed_files", len(files)), "files": _files(files),
        "commit_count": pr.get("commits", len(commits)),
        "commits": [{"sha": (c.get("sha") or "")[:7], "subject": ((c.get("commit") or {}).get("message") or "").split("\n", 1)[0],
                     "author": _user(c.get("author")) if c.get("author") else ((c.get("commit") or {}).get("author") or {}).get("name") or "ghost",
                     "at": ((c.get("commit") or {}).get("author") or {}).get("date")} for c in commits],
        "conversation": _conversation(comments, reviews),
        "checks": _checks(rollup),
    }


def fetch(owner: str, repo: str, n: str):
    """(status, body). 404 for a missing PR, 502 when `gh` cannot answer."""
    base, slug = f"repos/{owner}/{repo}/pulls/{n}", f"{owner}/{repo}"
    calls = {
        "pr": ["api", "-H", _HTML, base],
        "files": ["api", f"{base}/files?per_page={PAGE}"],
        "commits": ["api", f"{base}/commits?per_page={PAGE}"],
        "comments": ["api", "-H", _HTML, f"repos/{owner}/{repo}/issues/{n}/comments?per_page={PAGE}"],
        "reviews": ["api", "-H", _HTML, f"{base}/reviews?per_page={PAGE}"],
        "checks": ["pr", "view", n, "-R", slug, "--json", "statusCheckRollup"],
    }
    with ThreadPoolExecutor(len(calls)) as pool:
        got = dict(zip(calls, pool.map(lambda a: gh_json(a, timeout=40), calls.values())))
    pr, proc = got["pr"]
    if not isinstance(pr, dict):
        err = (proc.stderr or proc.stdout or "").strip()
        if "Not Found" in err or "HTTP 404" in err:
            return 404, {"error": "Pull request not found, or this gh login cannot see the repo."}
        return 502, {"error": (err.splitlines() or ["gh could not read the pull request"])[-1]}
    lists = {}
    for key in ("files", "commits", "comments", "reviews"):
        value, p = got[key]
        if not isinstance(value, list):
            return 502, {"error": ((p.stderr or "").strip().splitlines() or [f"gh could not read the {key}"])[-1]}
        lists[key] = value
    return 200, shape(pr, lists["files"], lists["commits"], lists["comments"], lists["reviews"], got["checks"][0])
