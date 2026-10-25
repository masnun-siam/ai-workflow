"""Is `gh` signed in? (And `solo`: does the signed-in user own a repo.)

`gh` sign-in: one `gh api user` call, cached for a minute (the header and the Inbox poll for it).

`status()` returns {ok, login, error}. A cold cache waits for the call (5 s at most); a stale one is served
as it is while a background thread refreshes it, so a request never waits on gh twice.
"""

from __future__ import annotations

import re
import threading
import time

from shared import run

TTL = 60.0
TIMEOUT = 5
_lock = threading.Lock()
_cache: dict = {"at": None, "value": None, "busy": False}


def check(runner=run) -> dict:
    p = runner(["gh", "api", "user", "--jq", ".login"], timeout=TIMEOUT)
    login = (p.stdout or "").strip()
    if p.returncode == 0 and login:
        return {"ok": True, "login": login, "error": None}
    err = (p.stderr or p.stdout or "").strip().splitlines()
    return {"ok": False, "login": None, "error": (err[0] if err else "gh did not answer")[:200]}


def _refresh(runner) -> None:
    value = check(runner)
    with _lock:
        _cache.update(at=time.time(), value=value, busy=False)


def status(runner=run, now=None) -> dict:
    now = now or time.time()
    with _lock:
        value, at, busy = _cache["value"], _cache["at"], _cache["busy"]
        if value is not None and now - at < TTL:
            return value
        if value is not None and not busy:  # stale: refresh behind this request
            _cache["busy"] = True
            threading.Thread(target=_refresh, args=(runner,), daemon=True).start()
            return value
        if value is not None:
            return value
    # ponytail: cold concurrent callers each run the check; it is one cheap call, a lock would only queue them
    _refresh(runner)
    return _cache["value"]


def solo(repo: str, runner=run) -> bool:
    """Is the repo owned by the signed-in user (owner == gh login)? Then a PR needs no approval to merge."""
    login = status(runner).get("login")
    return bool(login) and repo.partition("/")[0].lower() == str(login).lower()


_REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
BRANCHES_TIMEOUT = 60  # thousands of branches take several pages


def _gh_error(p) -> str:
    lines = (p.stderr or "").strip().splitlines() or (p.stdout or "").strip().splitlines()
    return (lines[-1] if lines else "gh did not answer")[:200]


def branches(repo, runner=run) -> tuple:
    """(status, body): every branch of owner/name, the default first and the rest sorted. Never cached."""
    if not isinstance(repo, str) or not _REPO_RE.fullmatch(repo) or {".", ".."} & set(repo.split("/")):
        return 400, {"error": "repo must be owner/name"}
    d = runner(["gh", "repo", "view", repo, "--json", "defaultBranchRef", "-q", ".defaultBranchRef.name"], timeout=30)
    default = (d.stdout or "").strip()
    if d.returncode != 0 or not default:
        return 502, {"error": _gh_error(d)}
    b = runner(["gh", "api", f"repos/{repo}/branches", "--paginate", "--jq", ".[].name"], timeout=BRANCHES_TIMEOUT)
    if b.returncode != 0:
        return 502, {"error": _gh_error(b)}
    names = set((b.stdout or "").split()) - {default}
    return 200, {"branches": [default] + sorted(names), "default": default}
