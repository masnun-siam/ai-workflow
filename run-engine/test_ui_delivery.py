#!/usr/bin/env python3
"""Self-check for run-engine/ui_delivery.py. `python3 test_ui_delivery.py` — exit 0 = green."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()
import ui_delivery  # noqa: E402


def pr(n, state="OPEN", draft=False, ci="success", review="none"):
    return {
        "n": n,
        "url": f"u{n}",
        "draft": draft,
        "state": state,
        "merged_at": None,
        "head": f"b{n}",
        "ci": ci,
        "review": review,
    }


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


# no epics: only the No epic lane; a non-refined issue without PR/session is unrefined
r = build(snap([issue(1), issue(2, labels=[])]))
assert [lane["epic"] for lane in r["lanes"]] == [None] and set(cards(r)) == {1, 2}
assert cards(r)[2]["column"] == "unrefined"
assert "cap" not in r and r["running"] == 0 and r["lanes"][0]["title"] == "No epic"
assert r["auto_grind"] is False and build(snap([]), settings={"auto_grind": True})["auto_grind"] is True

# blocked by open issue -> Ready with blocked_by; closed blocker dropped
epic = issue(10, labels=["epic"])
epic["title"] = "Epic: Boards"
s = snap([epic, issue(11, parent=10, blockers=[(12, "OPEN"), (9, "CLOSED")], prio="high"), issue(12, parent=10)])
c = cards(build(s), 10)
assert c[11]["column"] == "ready" and c[11]["blocked_by"] == [12] and c[11]["priority"] == "high"
lane = next(x for x in build(s)["lanes"] if x["epic"] == 10)
assert lane["title"] == "Boards" and "autopilot" not in lane
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
assert c[1]["column"] == "draft_pr" and c[1]["pr"] == {
    "n": 31,
    "draft": True,
    "ci": "success",
    "url": "u31",
    "review": "none",
    "conflict": False,
}
assert c[2]["column"] == "in_review" and c[3]["column"] == "grinding" and c[3]["grind"]["round"] == 2
assert c[4]["column"] == "ready" and c[4]["pr"] is None
assert c[5]["column"] == "in_progress" and c[5]["session"] == {"id": "S1", "status": "running"}
assert r["running"] == 1 and r["lanes"][0]["running"] == 1
sess[0]["command"] = "/ai-workflow:implement-issue 5"  # #437: plugin spelling counts the same
r = build(s, sess, {"pr": {("o", "r", 33): {"state": "running", "round": 2}}})
assert cards(r)[5]["session"] == {"id": "S1", "status": "running"} and r["running"] == 1
r = build(s, grind={"pr": {("o", "r", 33): {"state": "done", "round": 2}}})
assert cards(r)[3]["column"] == "in_review"

# card.grind: running | idle | paused (with its reason), None for no loop or a done one
g = {
    "pr": {
        ("o", "r", 31): {"state": "idle", "round": 1},
        ("o", "r", 32): {"state": "paused", "round": 3, "reason": "CI red"},
        ("o", "r", 33): {"state": "done", "round": 2},
    }
}
c = cards(build(s, grind=g))
assert c[1]["grind"] == {"state": "idle", "round": 1, "reason": None, "thread": None}
assert c[2]["grind"] == {"state": "paused", "round": 3, "reason": "CI red", "thread": None}
g2 = {"pr": {("o", "r", 31): {"state": "running", "round": 1, "thread": "https://x.slack.com/archives/C1/p1"}}}
assert cards(build(s, grind=g2))[1]["grind"]["thread"] == "https://x.slack.com/archives/C1/p1"
assert c[3]["grind"] is None and c[4]["grind"] is None
# card.pr.review comes from the snapshot's PR
s2 = snap([issue(1, prs=[pr(31, review="approved")]), issue(2, prs=[pr(32, review="changes_requested")])])
c = cards(build(s2))
assert c[1]["pr"]["review"] == "approved" and c[2]["pr"]["review"] == "changes_requested"

# grind_on (the issue's switch, else auto_grind) and mergeable (ui_inbox.merge_ready)
s3 = snap([issue(1, prs=[pr(41, review="approved")]), issue(2, prs=[pr(42)])])
c = cards(build(s3))
assert not c[1]["grind_on"] and c[1]["mergeable"] and not c[2]["mergeable"], "off: approval needed"
assert cards(ui_delivery.build("o/r", s3, [], {"pr": {}}, {}, {}, solo=True))[2]["mergeable"], "owner: no approval"
c = cards(build(s3, settings={"auto_grind": True, "issue_grind": {2: False}}))
assert c[1]["grind_on"] and not c[1]["mergeable"] and not c[2]["grind_on"]
c = cards(build(s3, grind={"pr": {("o", "r", 41): {"state": "done", "round": 1}}}, settings={"issue_grind": {1: True}}))
assert c[1]["grind_on"] and c[1]["mergeable"]
g42 = {"pr": {("o", "r", 42): {"state": "done", "round": 1}}}
assert not cards(build(s3, grind=g42, settings={"auto_grind": True}))[2]["mergeable"], "grind done but not approved"

# a PR that conflicts with its base is never mergeable
s4 = snap([issue(1, prs=[dict(pr(43, review="approved"), conflict=True)])])
c = cards(build(s4))
assert c[1]["pr"]["conflict"] is True and not c[1]["mergeable"]

# merged cards with cleanup flags, placed in their epic lane
m = [{"n": 40, "title": "t", "url": "u40", "merged_at": "x", "head": "h", "closes": [7], "epic": 10}]
flag = {"uncommitted": ["f"], "unpushed": []}
r = build(snap([epic], m), flags={7: flag})
assert cards(r, 10)[7]["column"] == "merged" and cards(r, 10)[7]["needs_cleanup"] == flag
# merged into staging: the issue stays open but its card is only in Merged, never back in Ready
mp = {"n": 41, "url": "u41", "draft": False, "state": "MERGED", "merged_at": "x", "head": "h", "ci": "success"}
m = [{"n": 41, "title": "t", "url": "u41", "merged_at": "x", "head": "h", "closes": [8], "epic": 10}]
r = build(snap([epic, issue(8, parent=10, prs=[mp])], m))
assert [c["column"] for c in cards(r, 10).values() if c["n"] == 8] == ["merged"], cards(r, 10)
# an epic's unrefined child is in Needs refinement; a loose unrefined issue is in the No epic lane
r = build(snap([epic, issue(12, labels=(), parent=10), issue(13, labels=())]))
assert cards(r, 10)[12]["column"] == "unrefined" and cards(r, None)[13]["column"] == "unrefined"
# a loose unrefined issue with an open blocker stays unrefined and lists the blocker
r = build(snap([issue(17, labels=(), blockers=[(18, "OPEN")])]))
assert cards(r, None)[17]["column"] == "unrefined" and cards(r, None)[17]["blocked_by"] == [18]
# lane membership matches ui_planning's children: sub_issues and the prd-<slug> label count too
ep = {**issue(10, labels=("epic", "prd-x")), "sub_issues": [14]}
r = build(snap([ep, issue(14, labels=()), issue(15, labels=("prd-x",)), issue(16, labels=("prd-y",))]))
assert set(cards(r, 10)) == {14, 15} and cards(r, None)[16]["column"] == "unrefined", r
# a grind reason's leading "<ISO> — " stamp is not part of the reason
g = {
    "pr": {("o", "r", 31): {"state": "paused", "round": 3, "reason": "2026-10-06T15:54:44Z — owner decision needed: x"}}
}
assert cards(build(snap([issue(1, prs=[pr(31)])]), grind=g))[1]["grind"]["reason"] == "owner decision needed: x"
print("ok")
