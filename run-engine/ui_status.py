"""GitHub status for Cards: issue state/labels plus PR state, approval and CI (read-only, cached).

A live server polls /board.json every few seconds; `gh` is only run when an entry is older
than TTL, on a pool, so a request never waits on it. A failed fetch keeps the last good value
and marks it stale. Once the PR is merged/closed and the issue closed the entry is frozen.
"""

from __future__ import annotations

import sys
import threading
import time

from shared import gh_json

TTL = 45
_FAILING = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR"}

_cache: dict = {}
_pending: set = set()
_lock = threading.Lock()


def _check(item):
    """(name, link, bucket) for a CheckRun or StatusContext rollup entry."""
    if item.get("__typename") == "StatusContext":
        name, link, result = item.get("context"), item.get("targetUrl"), item.get("state")
        done = result not in ("PENDING", "EXPECTED")
    else:
        name, link, result = item.get("name"), item.get("detailsUrl"), item.get("conclusion")
        done = item.get("status") == "COMPLETED"
    bucket = "pending" if not done else "red" if result in _FAILING else "green"
    return name, link, bucket


def summarize(issue, pr):
    """Pure: raw `gh` JSON (or None) -> the dict the UI renders."""
    out = {"issue": None, "pr": None}
    if issue:
        out["issue"] = {"state": issue.get("state"), "labels": [x.get("name") for x in issue.get("labels") or []]}
    if pr:
        checks = [_check(c) for c in pr.get("statusCheckRollup") or []]
        failing = [{"name": n, "link": link} for n, link, b in checks if b == "red"]
        ci = "red" if failing else "pending" if any(b == "pending" for *_, b in checks) else "green" if checks else None
        out["pr"] = {"url": pr.get("url"), "number": pr.get("number"), "state": pr.get("state"),
                     "approval": pr.get("reviewDecision") or None, "ci": ci, "failing": failing}
    return out


def _frozen(value):
    pr, issue = value["pr"], value["issue"]
    return bool(issue and issue["state"] == "CLOSED" and (pr is None or pr["state"] in ("MERGED", "CLOSED")))


def _fetch(owner, repo, issue, pr_url, branch):
    slug = f"{owner}/{repo}"
    iss, _ = gh_json(["issue", "view", str(issue), "-R", slug, "--json", "state,labels"], timeout=30)
    target = pr_url or branch
    pr = None
    if target:
        pr, _ = gh_json(["pr", "view", target, "-R", slug, "--json",
                         "url,number,state,reviewDecision,statusCheckRollup"], timeout=30)
    if not isinstance(iss, dict) or (target and not isinstance(pr, dict)):
        # a PR that doesn't exist yet (branch not pushed) is not an error worth keeping stale for
        raise RuntimeError(f"gh status fetch failed for {slug}#{issue}")
    return summarize(iss, pr)


def _fill(key, pr_url, branch):
    try:
        value, stale = _fetch(*key, pr_url, branch), False
    except Exception as exc:  # logged, last good value stays
        print(f"ui_status: {exc}", file=sys.stderr)
        value, stale = None, True
    with _lock:
        old = _cache.get(key)
        if value is not None:
            _cache[key] = {"value": value, "at": time.time(), "stale": False}
        elif old:
            old["stale"], old["at"] = True, time.time()
        else:
            _cache[key] = {"value": None, "at": time.time(), "stale": True}
        _pending.discard(key)


def get(owner, repo, issue, pr_url, branch, pool):
    """Cached status dict for a Card, or None until first fetched. Refreshes in the background."""
    key = (owner, repo, int(issue))
    with _lock:
        entry = _cache.get(key)
        fresh = entry and (time.time() - entry["at"] < TTL or (entry["value"] and _frozen(entry["value"])))
        start = not fresh and key not in _pending
        if start:
            _pending.add(key)
    if start:
        pool.submit(_fill, key, pr_url, branch)
    with _lock:
        entry = _cache.get(key)
    if not entry or not entry["value"]:
        return None
    return {**entry["value"], "stale": entry["stale"]}
