#!/usr/bin/env python3
"""Self-check for run-engine/ui_autopilot.py. `python3 test_ui_autopilot.py` — exit 0 = green."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
data = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = data
import dispatch  # noqa: E402
import ui_autopilot  # noqa: E402

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
    ui_autopilot._recent.clear()
    return Launcher()


EPIC = issue(1, labels=("epic",), parent=None)
on = {"autopilot": [1], "autopilot_cap": 2}

# cap 2, five eligible: priority (high > medium > low > none) then number; non-refined never
L = fresh()
s = snap(
    [
        EPIC,
        issue(5),
        issue(3, prio="low"),
        issue(4, prio="high"),
        issue(2, prio="high"),
        issue(6, prio="medium"),
        issue(7, labels=()),
    ]
)
assert ui_autopilot.tick("o/r", s, [], on, launch=L) == [2, 4] and L.issues == [2, 4]
assert L.bodies[0] == {"repo": "o/r", "text": "/implement-issue 2"}
print("  ok  cap and priority order")

# racing ticks on one snapshot: each issue at most once, and the cap holds
L = fresh()
s = snap([EPIC] + [issue(n) for n in range(2, 8)])
ts = [threading.Thread(target=ui_autopilot.tick, args=("o/r", s, [], on), kwargs={"launch": L}) for _ in range(4)]
[t.start() for t in ts]
[t.join() for t in ts]
assert sorted(L.issues) == [2, 3], L.issues
print("  ok  racing ticks")

# running ones count (waiting too), lowering the cap stops nothing, others wait
L = fresh()
s = snap([EPIC] + [issue(n) for n in range(2, 6)])
assert ui_autopilot.tick("o/r", s, [sess(2), sess(3, "waiting")], on, launch=L) == []
assert ui_autopilot.tick("o/r", s, [sess(2), sess(3, "waiting")], {**on, "autopilot_cap": 1}, launch=L) == []
other = {**sess(9), "repo": "x/y"}
assert ui_autopilot.tick("o/r", s, [sess(2), sess(3, "done"), other], {**on, "autopilot_cap": 3}, launch=L) == [3, 4]
assert L.issues == [3, 4]  # 2 live (counts), other repo's 9 does not, 3's session is done
print("  ok  running sessions count against the cap")

# real session records: `repo` is the checkout path and `link` names owner/repo (the regression that
# let autopilot start 2 more issues every poll while 2 were still running)
L = fresh()
real = [
    {**sess(2), "repo": checkout, "link": {"owner": "o", "repo": "r", "issue": 2}},
    {**sess(3, "waiting"), "repo": checkout + "/", "link": None},  # no link: the checkouts registry names it
]
assert ui_autopilot.tick("o/r", s, real, on, launch=L) == [] and L.bodies == []
assert ui_autopilot.tick("o/r", s, real, {**on, "autopilot_cap": 3}, launch=L) == [4]
print("  ok  live sessions with a checkout path and a link dict count against the cap")

# an issue whose PR merged into staging is still open: autopilot never starts it again
L = fresh()
merged_pr = {"n": 70, "state": "MERGED", "draft": False, "url": "u", "merged_at": "x", "head": "h", "ci": "success"}
assert ui_autopilot.tick("o/r", snap([EPIC, issue(2, prs=[merged_pr]), issue(3)]), [], on, launch=L) == [3]
print("  ok  an issue with a merged PR is not started again")

# stale, no epic on, blocked, open PR, epic off
L = fresh()
assert ui_autopilot.tick("o/r", snap([EPIC, issue(2)], stale=True), [], on, launch=L) == []
assert ui_autopilot.tick("o/r", snap([EPIC, issue(2)]), [], {"autopilot": []}, launch=L) == []
pr = {"n": 9, "url": "u", "draft": True, "state": "OPEN", "merged_at": None, "head": "h", "ci": "none"}
s = snap(
    [
        EPIC,
        issue(2, blockers=[(8, "OPEN")]),
        issue(3, blockers=[(8, "CLOSED")]),
        issue(4, prs=[pr]),
        issue(5, parent=None),
        issue(6, parent=99),
    ]
)
assert ui_autopilot.tick("o/r", s, [], on, launch=L) == [3]
print("  ok  stale, blocked, open PR, epic scope")

# start(): guards
L = fresh()
s = snap([EPIC, issue(2, blockers=[(8, "OPEN")]), issue(3, prs=[pr]), issue(4)])


def refuses(skill, arg, exc, **kw):
    try:
        ui_autopilot.start("o/r", skill, arg, kw.pop("via", "headless"), launch=kw.pop("launch", L), snapshot=s, **kw)
    except exc:
        return
    raise AssertionError((skill, arg))


refuses("implement-issue", "2", ui_autopilot.Conflict)  # blocked
refuses("implement-issue", "3", ui_autopilot.Conflict)  # open PR
refuses("implement-issue", "4", ui_autopilot.Conflict, sessions=[sess(4, "waiting")])  # live session
refuses("implement-issue", "x", ValueError)
refuses("bogus", "4", ValueError)
refuses("create-tasks", "docs/prds/a.md", ValueError, via="carrier")
refuses("peer-review", "docs/prds/a.md", ValueError, lenses=None)  # no lenses (400), never reaches the panel
assert not L.bodies
assert ui_autopilot.start("o/r", "implement-issue", "#4", snapshot=s, launch=L) == {"session": "S1"}
refuses("implement-issue", "4", ui_autopilot.Conflict)  # just started
assert ui_autopilot.start("o/r", "create-tasks", "docs/prds/a.md", launch=L)["session"] == "S2"
assert L.bodies[1] == {"repo": "o/r", "text": "/create-tasks docs/prds/a.md"}
conflict = lambda b: (409, {"error": "pr-grind already running"})  # noqa: E731
refuses("pr-grind", "12", ui_autopilot.Conflict, launch=conflict)
assert ui_autopilot.start("o/r", "pr-grind", "13", launch=L, channel="C1")["session"] == "S3"
assert L.bodies[2]["text"] == "/pr-grind 13 --channel C1"
print("  ok  start guards and launch")

# herdr: tab create -> agent start -> agent prompt, in the checkout
calls = []


def herdr(argv):
    calls.append(argv)
    return subprocess.CompletedProcess(argv, 0, "pane-7\n" if argv[:2] == ["tab", "create"] else "", "")


L = fresh()
r = ui_autopilot.start("o/r", "implement-issue", "4", "herdr", snapshot=s, launch=L, herdr=herdr)
assert r == {"session": "herdr:issue-4", "via": "herdr"} and not L.bodies
assert calls == [
    ["tab", "create", "--cwd", checkout, "--label", "issue-4"],
    ["agent", "start", "issue-4", "--kind", "claude", "--pane", "pane-7"],
    ["agent", "prompt", "issue-4", "/ai-workflow:implement-issue 4"],
], calls
refuses("implement-issue", "4", ui_autopilot.Conflict, via="herdr", herdr=herdr)
bad = lambda argv: subprocess.CompletedProcess(argv, 1, "", "no herdr")  # noqa: E731
try:
    ui_autopilot.start("o/r", "implement-issue", "5", "herdr", snapshot=s, herdr=bad)
    raise AssertionError("herdr failure must raise")
except RuntimeError:
    pass
print("  ok  herdr")
print("ui_autopilot: all checks passed")
