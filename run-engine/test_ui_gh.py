#!/usr/bin/env python3
"""Self-check for run-engine/ui_gh.py. `python3 test_ui_gh.py` — exit 0 = green."""

from __future__ import annotations

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui_gh  # noqa: E402

calls = []
answer = [0, "me\n", ""]


def runner(argv, **kw):
    calls.append(argv)
    return subprocess.CompletedProcess(argv, answer[0], answer[1], answer[2])


# check(): signed in, signed out (first stderr line), gh missing
assert ui_gh.check(runner) == {"ok": True, "login": "me", "error": None}
answer[:] = [1, "", "You are not logged into any GitHub hosts.\nTo log in, run: gh auth login\n"]
assert ui_gh.check(runner) == {"ok": False, "login": None, "error": "You are not logged into any GitHub hosts."}
answer[:] = [127, "", "gh: not found"]
assert ui_gh.check(runner)["error"] == "gh: not found"
answer[:] = [0, "", ""]
assert ui_gh.check(runner)["ok"] is False, "no login printed is not signed in"
print("  ok  check")

# status(): the first call waits for gh; calls inside a minute are cached; a stale value is served while it refreshes
answer[:] = [1, "", "signed out"]
calls.clear()
t0 = 1000.0
assert ui_gh.status(runner, now=t0)["error"] == "signed out" and len(calls) == 1
assert ui_gh.status(runner, now=t0 + 59)["error"] == "signed out" and len(calls) == 1
answer[:] = [0, "me\n", ""]
stale = ui_gh.status(runner, now=time.time() + 61)
assert stale["ok"] is False, "the stale answer is returned at once"
for _ in range(100):
    if len(calls) == 2 and not ui_gh._cache["busy"]:
        break
    time.sleep(0.02)
assert len(calls) == 2 and ui_gh.status(runner)["login"] == "me", "refreshed behind the request"
print("  ok  status: cached for a minute, stale-while-refresh")

# a refresh that times out keeps the last answer; a real sign-out still replaces it
answer[:] = [124, "", "timed out after 60s"]
ui_gh._refresh(runner)
assert ui_gh._cache["value"]["login"] == "me", "a timeout is not a sign-out"
answer[:] = [1, "", "You are not logged into any GitHub hosts."]
ui_gh._refresh(runner)
assert ui_gh._cache["value"]["ok"] is False
print("  ok  status: timeout keeps the last answer")

# solo: the signed-in login owns the repo (case-insensitive); signed out is never solo
ui_gh._cache.update(at=time.time(), value={"ok": True, "login": "Me", "error": None}, busy=False)
assert ui_gh.solo("me/r", runner) and ui_gh.solo("ME/r", runner) and not ui_gh.solo("org/r", runner)
ui_gh._cache.update(at=time.time(), value={"ok": False, "login": None, "error": "x"}, busy=False)
assert not ui_gh.solo("me/r", runner)
print("  ok  solo: repo owner is the signed-in user")


# branches(): default first, rest sorted; paginated; bad repo -> 400 with no gh call; gh failure -> 502; uncached
def br_runner(argv, **kw):
    calls.append(argv)
    if argv[:3] == ["gh", "repo", "view"]:
        return subprocess.CompletedProcess(argv, 0, "master\n", "")
    return subprocess.CompletedProcess(argv, 0, "staging\nmaster\ndev\n", "")


calls.clear()
assert ui_gh.branches("o/r", br_runner) == (200, {"branches": ["master", "dev", "staging"], "default": "master"})
assert any("--paginate" in c for c in calls)
ui_gh.branches("o/r", br_runner)
assert len(calls) == 4, "nothing is cached"
calls.clear()
for bad in ("", "o", "o/r/x", "o/r;ls", "../x", "./x", "o/..", None):
    assert ui_gh.branches(bad, br_runner) == (400, {"error": "repo must be owner/name"}), bad
assert not calls, "a bad repo never reaches gh"


def only(argv, **kw):
    return subprocess.CompletedProcess(argv, 0, "master\n", "")


assert ui_gh.branches("o/r", only) == (200, {"branches": ["master"], "default": "master"})


def fail(argv, **kw):
    return subprocess.CompletedProcess(argv, 1, "", "boom\nHTTP 404: Not Found\n\n")


assert ui_gh.branches("o/r", fail) == (502, {"error": "HTTP 404: Not Found"})


def fail_pages(argv, **kw):
    if argv[:3] == ["gh", "repo", "view"]:
        return subprocess.CompletedProcess(argv, 0, "master\n", "")
    return subprocess.CompletedProcess(argv, 1, "", "rate limited\n")


assert ui_gh.branches("o/r", fail_pages) == (502, {"error": "rate limited"})
print("  ok  branches")
print("ui_gh: all checks passed")
