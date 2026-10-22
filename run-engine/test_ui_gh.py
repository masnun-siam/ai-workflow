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

# solo: the signed-in login owns the repo (case-insensitive); signed out is never solo
ui_gh._cache.update(at=time.time(), value={"ok": True, "login": "Me", "error": None}, busy=False)
assert ui_gh.solo("me/r", runner) and ui_gh.solo("ME/r", runner) and not ui_gh.solo("org/r", runner)
ui_gh._cache.update(at=time.time(), value={"ok": False, "login": None, "error": "x"}, busy=False)
assert not ui_gh.solo("me/r", runner)
print("  ok  solo: repo owner is the signed-in user")
print("ui_gh: all checks passed")
