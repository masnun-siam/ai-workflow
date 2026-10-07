#!/usr/bin/env python3
"""Self-check for run-engine/ui_status.py. `python3 test_ui_status.py` — exit 0 = green."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ui_status
from ui_status import summarize

run = lambda name, status, conclusion=None: {"__typename": "CheckRun", "name": name, "status": status,
                                              "conclusion": conclusion, "detailsUrl": "https://x/" + name}
pr = lambda *checks, **kw: {"url": "https://github.com/o/r/pull/1", "number": 1, "state": "OPEN",
                            "reviewDecision": "APPROVED", "statusCheckRollup": list(checks), **kw}
iss = {"state": "OPEN", "labels": [{"name": "ready-for-agent"}]}

s = summarize(iss, pr(run("a", "COMPLETED", "SUCCESS")))
assert s["pr"]["ci"] == "green" and s["pr"]["approval"] == "APPROVED" and s["issue"]["labels"] == ["ready-for-agent"]
s = summarize(iss, pr(run("a", "COMPLETED", "SUCCESS"), run("b", "COMPLETED", "FAILURE"), run("c", "IN_PROGRESS")))
assert s["pr"]["ci"] == "red" and s["pr"]["failing"] == [{"name": "b", "link": "https://x/b"}]
assert summarize(iss, pr(run("c", "IN_PROGRESS")))["pr"]["ci"] == "pending"
assert summarize(iss, pr())["pr"]["ci"] is None
ctx = {"__typename": "StatusContext", "context": "ci/x", "state": "ERROR", "targetUrl": "https://y"}
assert summarize(iss, pr(ctx))["pr"]["failing"][0]["name"] == "ci/x"
assert summarize(iss, pr(reviewDecision=""))["pr"]["approval"] is None
assert summarize(iss, None)["pr"] is None
print("  ok  summarize: CI rollup, failing checks, approval, labels")

closed = summarize({"state": "CLOSED", "labels": []}, pr(state="MERGED"))
assert ui_status._frozen(closed) and not ui_status._frozen(summarize(iss, pr(state="MERGED")))
print("  ok  frozen only when PR merged/closed and issue closed")

# get(): stale-keeps-last-good-value and no refetch inside TTL
calls = []
class Inline:
    def submit(self, fn, *a): fn(*a)
ui_status._fetch = lambda *a: (calls.append(a), summarize(iss, None))[1]
assert ui_status.get("o", "r", 1, None, None, Inline())["issue"]["state"] == "OPEN"
ui_status.get("o", "r", 1, None, None, Inline())
assert len(calls) == 1
ui_status._cache[("o", "r", 1)]["at"] = 0
def boom(*a): raise RuntimeError("gh down")
ui_status._fetch = boom
got = ui_status.get("o", "r", 1, None, None, Inline())
assert got["stale"] is True and got["issue"]["state"] == "OPEN"
print("  ok  get: cached within TTL, last good value kept and flagged stale on failure")
