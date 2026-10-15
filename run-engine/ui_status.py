"""GitHub status for Cards: issue state/labels plus PR state, approval and CI (read-only, cached).

A live server polls /board.json every few seconds; `gh` is only run when an entry is older
than its TTL, on a pool, so a request never waits on it. A failed fetch keeps the last good value
and marks it stale. An entry is frozen (never refetched) once its PR is merged, its issue is
closed with no open PR, or the issue is gone from GitHub. The cache lives on disk too, so a
restart does not refetch every card at once.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

from shared import atomic_write_text, data_dir, gh_json

TTL = 45  # a PR whose CI is still running
IDLE_TTL = 300  # any other card not yet frozen: two GraphQL calls per card add up across a full board
RATE_LIMIT_PAUSE = 600  # GitHub said the rate limit is spent: no fetches, last values shown stale
_FAILING = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR"}

_cache: dict = {}
_loaded = False
_paused_until = 0.0
_GONE = ("could not resolve to an issue", "was deleted")
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
        out["pr"] = {
            "url": pr.get("url"),
            "number": pr.get("number"),
            "state": pr.get("state"),
            "approval": pr.get("reviewDecision") or None,
            "ci": ci,
            "failing": failing,
        }
    return out


def _frozen(value):
    pr, issue = value.get("pr"), value.get("issue")
    if issue and issue.get("state") == "DELETED" or pr and pr.get("state") == "MERGED":
        return True  # a merge into a non-default branch leaves the issue open for good
    return bool(issue and issue.get("state") == "CLOSED" and (pr is None or pr.get("state") == "CLOSED"))


def _path() -> str:
    return os.path.join(data_dir(), "gh-status.json")


def _load() -> None:
    """Fill the cache from disk once per process. Caller holds _lock."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        with open(_path(), encoding="utf-8") as f:
            rows = json.load(f)
    except (OSError, ValueError):
        return
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and isinstance(row.get("value"), dict):
            key = (row.get("owner"), row.get("repo"), row.get("issue"))
            _cache.setdefault(key, {"value": row["value"], "at": row.get("at") or 0, "stale": False})


def _save() -> None:
    """Caller holds _lock."""
    rows = [
        {"owner": k[0], "repo": k[1], "issue": k[2], "value": e["value"], "at": e["at"]}
        for k, e in _cache.items()
        if e.get("value")
    ]
    try:
        atomic_write_text(_path(), json.dumps(rows))
    except OSError as exc:
        print(f"ui_status: could not save the status cache: {exc}", file=sys.stderr)


def _ttl(value):
    pr = (value or {}).get("pr")
    return TTL if pr and pr.get("state") == "OPEN" and pr.get("ci") == "pending" else IDLE_TTL


class RateLimited(RuntimeError):
    pass


def _rate_limited(proc) -> None:
    if "rate limit" in (proc.stderr or "").lower():
        raise RateLimited((proc.stderr or "").strip()[:200])


def _fetch(owner, repo, issue, pr_url, branch):
    slug = f"{owner}/{repo}"
    iss, proc = gh_json(["issue", "view", str(issue), "-R", slug, "--json", "state,labels"], timeout=30)
    _rate_limited(proc)
    if iss is None and any(g in (proc.stderr or "").lower() for g in _GONE):
        return {"issue": {"state": "DELETED", "labels": []}, "pr": None}
    target = pr_url or branch
    pr = None
    if target:
        pr, proc = gh_json(
            ["pr", "view", target, "-R", slug, "--json", "url,number,state,reviewDecision,statusCheckRollup"],
            timeout=30,
        )
        _rate_limited(proc)
        if pr is None and "no pull requests found" in (proc.stderr or ""):
            target = None  # a branch with no PR yet is a normal state, not a failed fetch
    if not isinstance(iss, dict) or (target and not isinstance(pr, dict)):
        raise RuntimeError(f"gh status fetch failed for {slug}#{issue}")
    return summarize(iss, pr)


def _fill(key, pr_url, branch):
    global _paused_until
    try:
        value = _fetch(*key, pr_url, branch)
    except RateLimited as exc:
        print(f"ui_status: GitHub rate limit, pausing status fetches {RATE_LIMIT_PAUSE}s: {exc}", file=sys.stderr)
        _paused_until = time.time() + RATE_LIMIT_PAUSE
        value = None
    except Exception as exc:  # logged, last good value stays
        print(f"ui_status: {exc}", file=sys.stderr)
        value = None
    with _lock:
        old = _cache.get(key)
        if value is not None:
            _cache[key] = {"value": value, "at": time.time(), "stale": False}
            _save()
        elif old:
            old["stale"], old["at"] = True, time.time()
        else:
            _cache[key] = {"value": None, "at": time.time(), "stale": True}
        _pending.discard(key)


def get(owner, repo, issue, pr_url, branch, pool):
    """Cached status dict for a Card, or None until first fetched. Refreshes in the background."""
    key = (owner, repo, int(issue))
    with _lock:
        _load()
        entry = _cache.get(key)
        fresh = entry and (
            time.time() - entry["at"] < _ttl(entry["value"]) or (entry["value"] and _frozen(entry["value"]))
        )
        start = not fresh and key not in _pending and time.time() >= _paused_until
        if start:
            _pending.add(key)
    if start:
        pool.submit(_fill, key, pr_url, branch)
    with _lock:
        entry = _cache.get(key)
    if not entry or not entry["value"]:
        return None
    return {**entry["value"], "stale": entry["stale"]}


def mark_merged(pr_url) -> None:
    """A PR just merged from the UI: every cached card with that PR shows it merged now (GitHub said
    so) and refetches on its next read, instead of showing "open" until the TTL runs out."""
    with _lock:
        for entry in _cache.values():
            pr = (entry.get("value") or {}).get("pr")
            if pr and str(pr.get("url") or "").lower() == str(pr_url).lower():
                pr["state"] = "MERGED"
                entry["at"] = 0


def cached(owner, repo, issue):
    """The last fetched status for a Card, or None; never starts a fetch."""
    with _lock:
        _load()
        entry = _cache.get((owner, repo, int(issue)))
    return entry["value"] if entry else None
