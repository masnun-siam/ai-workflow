#!/usr/bin/env python3
"""Self-check for run-engine/ui_start.py. `python3 test_ui_start.py` — exit 0 = green."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
data = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = data
import dispatch  # noqa: E402
import dispatch_run  # noqa: E402
import ui_start  # noqa: E402

checkout = tempfile.mkdtemp()
dispatch.register_checkout("o/r", checkout)


def issue(n, labels=("refined",), parent=1, blockers=(), prs=(), prio=None):
    return {
        "n": n,
        "title": f"i{n}",
        "state": "OPEN",
        "labels": list(labels),
        "priority": prio,
        "parent": parent,
        "sub_issues": [],
        "blocked_by": [{"n": b, "state": s} for b, s in blockers],
        "prs": list(prs),
    }


def snap(issues, stale=False):
    return {"stale": stale, "fetched_at": 1.0, "data": {"issues": issues, "merged": [], "open_prs": []}}


def sess(n, status="running"):
    return {"id": f"S{n}", "status": status, "command": f"/implement-issue {n}", "repo": "o/r"}


class Launcher:
    def __init__(self):
        self.bodies = []

    def __call__(self, body):
        self.bodies.append(body)
        return 201, {"id": f"S{len(self.bodies)}"}

    @property
    def issues(self):
        return [int(b["text"].split()[1]) for b in self.bodies]


def fresh():
    ui_start._recent.clear()
    return Launcher()


EPIC = issue(1, labels=("epic",), parent=None)
pr = {"n": 9, "url": "u", "draft": True, "state": "OPEN", "merged_at": None, "head": "h", "ci": "none"}

# start(): guards
L = fresh()
s = snap([EPIC, issue(2, blockers=[(8, "OPEN")]), issue(3, prs=[pr]), issue(4)])


def refuses(skill, arg, exc, **kw):
    try:
        ui_start.start("o/r", skill, arg, launch=kw.pop("launch", L), snapshot=s, **kw)
    except exc:
        return
    raise AssertionError((skill, arg))


refuses("implement-issue", "2", ui_start.Conflict)  # blocked
refuses("implement-issue", "3", ui_start.Conflict)  # open PR
refuses("implement-issue", "4", ui_start.Conflict, sessions=[sess(4, "waiting")])  # live session
refuses("implement-issue", "x", ValueError)
refuses("bogus", "4", ValueError)
refuses("peer-review", "docs/prds/a.md", ValueError, lenses=None)  # no lenses (400), never reaches the panel
assert not L.bodies
assert ui_start.start("o/r", "implement-issue", "#4", snapshot=s, launch=L) == {"session": "S1"}
refuses("implement-issue", "4", ui_start.Conflict)  # just started
assert ui_start.start("o/r", "create-tasks", "docs/prds/a.md", launch=L)["session"] == "S2"
assert L.bodies[1] == {"repo": "o/r", "text": "/create-tasks docs/prds/a.md"}
conflict = lambda b: (409, {"error": "pr-grind already running"})  # noqa: E731
refuses("pr-grind", "12", ui_start.Conflict, launch=conflict)
assert ui_start.start("o/r", "pr-grind", "13", launch=L, channel="C1")["session"] == "S3"
assert L.bodies[2]["text"] == "/pr-grind 13 --channel C1"
assert ui_start.start("o/r", "refine-issues", "#7, 9  11", launch=L)["session"] == "S4"
assert L.bodies[3]["text"] == "/refine-issues 7 9 11", "several issue numbers, normalised"
refuses("refine-issues", "7 and 9", ValueError)
assert ui_start.start("o/r", "refine-issues", "7", launch=L, model="opus", effort="medium")["session"] == "S5"
assert L.bodies[4]["model"] == "opus" and L.bodies[4]["effort"] == "medium"
assert "model" not in L.bodies[3] and "effort" not in L.bodies[3], "unset: not sent"
assert "issue" not in L.bodies[3], "several issues: unlinked"
assert L.bodies[4]["issue"] == 7, "one refined issue links its session"
assert ui_start.start("o/r", "create-tasks", "docs/prds/b.md", launch=L, issue=3)["session"] == "S6"
assert L.bodies[5]["issue"] == 3, "an explicit issue is forwarded"
live_refine = {"id": "R1", "status": "running", "command": "/refine-issues 7 8", "repo": "o/r"}
try:
    ui_start.start("o/r", "refine-issues", "8 12", launch=L, sessions=[live_refine])
    raise AssertionError("overlapping live refine")
except ui_start.Conflict as e:
    assert e.id == "R1"
assert ui_start.start("o/r", "refine-issues", "99", launch=L, sessions=[live_refine])["session"] == "S7"
for cmd in ("/ai-workflow:refine-issues 5 6", "/refine-issues 5 6"):  # #437: both spellings guard
    live = {"id": "R2", "status": "running", "command": cmd, "repo": "o/r"}
    try:
        ui_start.start("o/r", "refine-issues", "6", launch=L, sessions=[live])
        raise AssertionError(f"live {cmd} must refuse")
    except ui_start.Conflict as e:
        assert e.id == "R2", cmd
refuses("refine-issues", "7", ValueError, model="gpt")
refuses("refine-issues", "7", ValueError, effort="default")
print("  ok  start guards and launch")

# a lane of a running dispatch owns its issue
d = dispatch_run.create("o/r#1", "headless", {}, [{"repo": "o/r", "n": 6, "refined": True}])
d["lanes"]["o/r#6"]["stage"] = "implementing"
dispatch_run.save(d)
L = fresh()
refuses("implement-issue", "6", ui_start.Conflict)
assert not L.bodies
print("  ok  dispatch owns its issues")
print("ui_start: all checks passed")
