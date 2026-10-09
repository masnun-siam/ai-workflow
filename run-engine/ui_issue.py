"""Read-only issue overview for the UI popup: title, state, people, and GitHub-rendered body + comments.

GitHub renders the markdown itself (`application/vnd.github.html+json`), so the UI needs no markdown
library and gets sanitized HTML with task lists, mentions and code fences already handled.
"""

from __future__ import annotations

import re

from shared import gh_json

MAX_COMMENTS = 100  # one page; a longer thread says so and points at GitHub
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_HTML = "Accept: application/vnd.github.html+json"


def valid(owner: str, repo: str, n: str) -> bool:
    return bool(_NAME.fullmatch(owner) and _NAME.fullmatch(repo) and n.isdigit())


def _links_out(html: str | None) -> str:
    """GitHub's HTML is sanitized; links just need to leave the app in a new tab."""
    return re.sub(r"<a\s", '<a target="_blank" rel="noopener noreferrer" ', html or "")


def _user(u):
    return (u or {}).get("login") or "ghost"


def shape(issue: dict, comments: list) -> dict:
    """Pure: the two REST payloads -> the dict the popup renders."""
    ms = issue.get("milestone") or {}
    return {
        "number": issue.get("number"),
        "title": issue.get("title"),
        "url": issue.get("html_url"),
        "state": issue.get("state"),
        "state_reason": issue.get("state_reason"),
        "is_pr": "pull_request" in issue,
        "author": _user(issue.get("user")),
        "created_at": issue.get("created_at"),
        "labels": [{"name": x.get("name"), "color": x.get("color")} for x in issue.get("labels") or [] if isinstance(x, dict)],
        "assignees": [_user(a) for a in issue.get("assignees") or []],
        "milestone": ms.get("title"),
        "body_html": _links_out(issue.get("body_html")),
        "comment_count": issue.get("comments", len(comments)),
        "comments": [{"author": _user(c.get("user")), "created_at": c.get("created_at"), "body_html": _links_out(c.get("body_html"))}
                     for c in comments],
    }


def fetch(owner: str, repo: str, n: str):
    """(status, body). 404 for a missing issue, 502 when `gh` cannot answer."""
    base = f"repos/{owner}/{repo}/issues/{n}"
    issue, proc = gh_json(["api", "-H", _HTML, base], timeout=30)
    if not isinstance(issue, dict):
        err = (proc.stderr or proc.stdout or "").strip()
        if "Not Found" in err or "HTTP 404" in err:
            return 404, {"error": "Issue not found, or this gh login cannot see the repo."}
        return 502, {"error": (err.splitlines() or ["gh could not read the issue"])[-1]}
    comments, proc = gh_json(["api", "-H", _HTML, f"{base}/comments?per_page={MAX_COMMENTS}"], timeout=30)
    if not isinstance(comments, list):
        return 502, {"error": ((proc.stderr or "").strip().splitlines() or ["gh could not read the comments"])[-1]}
    return 200, shape(issue, comments)
