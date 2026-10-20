#!/usr/bin/env python3
"""Self-check for run-engine/ui_delivery.py. `python3 test_ui_delivery.py` — exit 0 = green."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()
import ui_delivery  # noqa: E402


def pr(n, state="OPEN", draft=False, ci="success"):
    return {"n": n, "url": f"u{n}", "draft": draft, "state": state, "merged_at": None, "head": f"b{n}", "ci": ci}


def issue(n, labels=("refined",), parent=None, blockers=(), prs=(), prio=None):
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


def snap(issues, merged=()):
    return {"stale": False, "fetched_at": 1.0, "data": {"issues": issues, "merged": list(merged), "open_prs": []}}


def cards(res, epic=None):
    return {c["n"]: c for lane in res["lanes"] if lane["epic"] == epic for c in lane["cards"]}


def build(s, sessions=(), grind=None, settings=None, flags=None):
    return ui_delivery.build("o/r", s, list(sessions), grind or {"pr": {}}, settings or {}, flags or {})


# no epics: only the No epic lane; non-refined without PR/session absent
r = build(snap([issue(1), issue(2, labels=[])]))
assert [lane["epic"] for lane in r["lanes"]] == [None] and set(cards(r)) == {1}
assert r["cap"] == 2 and r["running"] == 0 and r["lanes"][0]["title"] == "No epic"
assert r["auto_grind"] is False and build(snap([]), settings={"auto_grind": True})["auto_grind"] is True

# blocked by open issue -> Ready with blocked_by; closed blocker dropped
epic = issue(10, labels=["epic"])
epic["title"] = "Epic: Boards"
s = snap([epic, issue(11, parent=10, blockers=[(12, "OPEN"), (9, "CLOSED")], prio="high"), issue(12, parent=10)])
c = cards(build(s, settings={"autopilot": [10], "autopilot_cap": 3}), 10)
assert c[11]["column"] == "ready" and c[11]["blocked_by"] == [12] and c[11]["priority"] == "high"
r = build(s, settings={"autopilot": {"10": True}, "autopilot_cap": 3})
lane = next(x for x in r["lanes"] if x["epic"] == 10)
assert lane["autopilot"] and lane["title"] == "Boards" and r["cap"] == 3
s = snap([epic, issue(11, parent=10, blockers=[(12, "CLOSED")]), issue(12, parent=10)])
assert cards(build(s), 10)[11]["blocked_by"] == []

# grind / draft / review / closed-unmerged / session
s = snap(
    [
        issue(1, prs=[pr(31, draft=True)]),
        issue(2, prs=[pr(32)]),
        issue(3, prs=[pr(33)]),
        issue(4, prs=[pr(34, state="CLOSED")]),
        issue(5, labels=[]),
    ]
)
sess = [
    {"id": "S1", "status": "running", "command": "/implement-issue 5", "repo": "o/r"},
    {"id": "S2", "status": "done", "command": "/implement-issue 4", "repo": "o/r"},
    {"id": "S3", "status": "running", "command": "/implement-issue 9", "repo": "x/y"},
]
r = build(s, sess, {"pr": {("o", "r", 33): {"state": "running", "round": 2}}})
c = cards(r)
assert c[1]["column"] == "draft_pr" and c[1]["pr"] == {"n": 31, "draft": True, "ci": "success", "url": "u31"}
assert c[2]["column"] == "in_review" and c[3]["column"] == "grinding" and c[3]["grind_round"] == 2
assert c[4]["column"] == "ready" and c[4]["pr"] is None
assert c[5]["column"] == "in_progress" and c[5]["session"] == {"id": "S1", "status": "running"}
assert r["running"] == 1 and r["lanes"][0]["running"] == 1
r = build(s, grind={"pr": {("o", "r", 33): {"state": "done", "round": 2}}})
assert cards(r)[3]["column"] == "in_review"

# merged cards with cleanup flags, placed in their epic lane
m = [{"n": 40, "title": "t", "url": "u40", "merged_at": "x", "head": "h", "closes": [7], "epic": 10}]
flag = {"uncommitted": ["f"], "unpushed": []}
r = build(snap([epic], m), flags={7: flag})
assert cards(r, 10)[7]["column"] == "merged" and cards(r, 10)[7]["needs_cleanup"] == flag
print("ok")
