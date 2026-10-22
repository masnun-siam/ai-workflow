"""Is `gh` signed in? (And `solo`: does the signed-in user own a repo.)

`gh` sign-in: one `gh api user` call, cached for a minute (the header and the Inbox poll for it).

`status()` returns {ok, login, error}. A cold cache waits for the call (5 s at most); a stale one is served
as it is while a background thread refreshes it, so a request never waits on gh twice.
"""

from __future__ import annotations

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
