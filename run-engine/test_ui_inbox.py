#!/usr/bin/env python3
"""Self-check for run-engine/ui_inbox.py. `python3 test_ui_inbox.py` — exit 0 = green."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()
import ui_inbox  # noqa: E402

REPOS = [{"slug": "o/r", "path": "/p/r"}, {"slug": "o/s", "path": "/p/s"}, {"slug": "local/idea", "path": "/p/i"}]
PANEL = "p-20261020T100000Z-abcdef"


def rec(sid, status, command="/implement-issue 4", at="2026-10-20T10:00:00+00:00", **kw):
    return {"id": sid, "status": status, "command": command, "repo": "o/r", "started_at": at, **kw}


def pq():
    return {"id": "q-1", "status": "pending", "questions": [{"question": "A or B?", "options": []}]}


def snap(open_prs=(), issues=(), stale=False, fetched=1.0):
    return {
        "stale": stale,
        "fetched_at": fetched,
        "data": {"issues": list(issues), "merged": [], "open_prs": list(open_prs)},
    }


def pr(n, draft=False, ci="success", review="approved"):
    return {
        "n": n,
        "title": f"t{n}",
        "url": f"u{n}",
        "draft": draft,
        "ci": ci,
        "review": review,
        "reviewer": "bob",
        "checks": 3,
    }


def panel(state, prd="Draft", pid=PANEL, artifact="/p/r/docs/prds/x.md"):
    return {
        "id": pid,
        "repo": "o/r",
        "artifact": artifact,
        "state": state,
        "round": 5,
        "max_rounds": 5,
        "approved": 2,
        "total": 3,
        "prd_status": prd,
    }


def build(**kw):
    args = dict(
        sessions=[], panels=[], grind_index={"pr": {}}, flags={}, repos=REPOS, snapshots={"o/r": snap()},
        gh={"ok": True, "login": "me", "error": None}, alive=set(), account_labels={"claude": "main"},
    )  # fmt: skip
    return ui_inbox.build(**{**args, **kw})


def types(res):
    return sorted(i["type"] for i in res["items"])


def one(res, typ):
    (item,) = [i for i in res["items"] if i["type"] == typ]
    return item


# nothing to do: only the unpublished local repo (setup) shows
res = build()
assert types(res) == ["repo_unpublished"] and res["stale"] == []
u = one(res, "repo_unpublished")
assert (
    u["group"] == "setup" and u["key"] == "unpublished:local/idea" and u["slug"] == "local/idea" and u["path"] == "/p/i"
)
print("  ok  repo_unpublished: a local/ slug in the registry")

# gh_auth: blocking, no repo; gone when gh answers
res = build(gh={"ok": False, "login": None, "error": "not logged in"})
g = one(res, "gh_auth")
assert (g["group"], g["key"], g["repo"], g["error"]) == ("block", "gh_auth", None, "not logged in")
assert res["items"][0] is g, "blocking sorts first"
assert "gh_auth" not in types(build(gh={"ok": True, "login": "me", "error": None}))
print("  ok  gh_auth")

# question: only a waiting session with a pending round; process_alive from `alive`
s = rec("S1", "waiting", pending_question=pq(), link={"owner": "o", "repo": "r", "issue": 4})
q = one(build(sessions=[s], alive={"S1"}), "question")
assert (q["group"], q["key"], q["repo"], q["session_id"], q["round_id"]) == (
    "answer",
    "question:S1",
    "o/r",
    "S1",
    "q-1",
)
assert q["process_alive"] is True and q["questions"][0]["question"] == "A or B?" and q["link"]["issue"] == 4
assert q["command"] == "/implement-issue 4" and q["at"] == "2026-10-20T10:00:00+00:00"
assert one(build(sessions=[s]), "question")["process_alive"] is False
assert "question" not in types(build(sessions=[{**s, "status": "running", "pending_question": None}]))
assert "question" not in types(build(sessions=[{**s, "pending_question": {**pq(), "status": "answered"}}]))
print("  ok  question")

# review_cap / review_approved: PRD panels only, newest panel per artifact, gone once the PRD is Approved
c = one(build(panels=[panel("cap reached")]), "review_cap")
assert (c["group"], c["key"], c["repo"], c["prd_path"], c["panel"]) == (
    "decide",
    f"review_cap:{PANEL}",
    "o/r",
    "docs/prds/x.md",
    PANEL,
)
assert (c["round"], c["max_rounds"], c["at"]) == (5, 5, "2026-10-20T10:00:00+00:00") and "2 of 3" in c["note"]
a = one(build(panels=[panel("approved")]), "review_approved")
assert (a["group"], a["key"], a["prd_path"], a["panel"]) == (
    "decide",
    f"review_approved:{PANEL}",
    "docs/prds/x.md",
    PANEL,
)
for gone in (panel("running"), panel("cap reached", prd="Approved"), panel("approved", prd="Approved"),
             panel("approved", artifact="/p/r/asks/x.md")):  # fmt: skip
    assert not [t for t in types(build(panels=[gone])) if t.startswith("review")], gone
newer = panel("running", pid="p-20261020T110000Z-abcdef")
assert not [t for t in types(build(panels=[panel("cap reached"), newer])) if t.startswith("review")], "superseded"
print("  ok  review_cap, review_approved")

# pr_ready: open, not draft, CI success, approved
prs = [
    pr(1),
    pr(2, draft=True),
    pr(3, ci="pending"),
    pr(4, review="review_required"),
    pr(5, ci="failure"),
    pr(6, review="none"),
]
issues = [{"n": 9, "prs": [{"n": 1}]}]
res = build(snapshots={"o/r": snap(prs, issues)})
r = one(res, "pr_ready")
assert (r["group"], r["key"], r["repo"], r["pr"], r["issue"]) == ("decide", "pr_ready:o/r#1", "o/r", 1, 9)
assert (r["title"], r["reviewer"], r["checks"], r["url"]) == ("t1", "bob", 3, "u1")
assert "pr_ready" not in types(build(snapshots={"o/r": snap(prs[1:], issues)}))


# the user owns the repo: no approval needed
def ready_prs(res):
    return [i["pr"] for i in res["items"] if i["type"] == "pr_ready"]


assert ready_prs(build(snapshots={"o/r": snap(prs, issues)}, solo={"O/R": True})) == [1, 4, 6]
# grinding on (repo default, or the issue's switch): also the grind is done (stopped counts); approval still needed
on = {"o/r": {"auto_grind": True}}
done = {"pr": {("o", "r", 1): {"state": "done", "round": 2}, ("o", "r", 6): {"state": "done", "round": 1}}}
assert "pr_ready" not in types(build(snapshots={"o/r": snap(prs, issues)}, settings=on))
assert ready_prs(build(snapshots={"o/r": snap(prs, issues)}, settings=on, grind_index=done)) == [1]
assert ready_prs(build(snapshots={"o/r": snap(prs, issues)}, settings=on, grind_index=done, solo={"o/r": True})) == [
    1,
    6,
]
off9 = {"o/r": {"auto_grind": True, "issue_grind": {9: False}}}
assert ready_prs(build(snapshots={"o/r": snap(prs, issues)}, settings=off9)) == [1], "#9 is off"
on9 = {"o/r": {"auto_grind": False, "issue_grind": {9: True}}}
assert "pr_ready" not in types(build(snapshots={"o/r": snap(prs[:1], issues)}, settings=on9))
assert not ui_inbox.merge_ready({"draft": False, "ci": "pending"}, {"state": "done"}, True, True)
assert ui_inbox.grind_on({"auto_grind": True}, None) and not ui_inbox.grind_on({}, 3)
# a conflicting PR is a Fix item, never ready to merge
conflicting = dict(pr(1), conflict=True)
res = build(snapshots={"o/r": snap([conflicting], issues)})
assert "pr_ready" not in types(res)
c = one(res, "pr_conflict")
assert (c["group"], c["key"], c["pr"], c["issue"], c["url"]) == ("fix", "pr_conflict:o/r#1", 1, 9, "u1")
print("  ok  pr_ready (grind on/off, solo), pr_conflict")

# grind_paused: only paused loops; gone when the PR is no longer open (fresh snapshot)
idx = {
    "pr": {
        ("o", "r", 1): {"state": "paused", "round": 3, "reason": "CI red"},
        ("o", "r", 2): {"state": "idle", "round": 1},
    }
}
res = build(grind_index=idx, snapshots={"o/r": snap([pr(1, review="none")], issues)})
g = one(res, "grind_paused")
assert (g["group"], g["key"], g["repo"], g["pr"], g["issue"], g["round"], g["reason"]) == (
    "fix", "grind:o/r#1", "o/r", 1, 9, 3, "CI red")  # fmt: skip
assert "grind_paused" not in types(build(grind_index=idx, snapshots={"o/r": snap([])})), "PR closed"
assert one(build(grind_index=idx, snapshots={"o/r": snap(stale=True)}), "grind_paused")["issue"] is None
stamped = {
    "pr": {
        ("o", "r", 1): {"state": "paused", "round": 3, "reason": "2026-10-06T15:54:44Z — owner decision needed: x — y"}
    }
}
g = one(build(grind_index=stamped, snapshots={"o/r": snap([pr(1, review="none")], issues)}), "grind_paused")
assert (g["at"], g["reason"]) == ("2026-10-06T15:54:44Z", "owner decision needed: x — y"), g
assert one(res, "grind_paused")["at"] is None  # no stamp, no time
print("  ok  grind_paused")

# session_failed: gone when a newer session of the same command exists; lens sessions never
f = rec("F1", "failed", error="boom", ended_at="2026-10-20T10:05:00+00:00", link=None)
x = one(build(sessions=[f]), "session_failed")
assert (x["group"], x["key"], x["repo"], x["error"], x["at"]) == (
    "fix",
    "failed:F1",
    "o/r",
    "boom",
    "2026-10-20T10:05:00+00:00",
)
again = rec("N1", "running", at="2026-10-20T11:00:00+00:00")
assert "session_failed" not in types(build(sessions=[f, again]))
assert "session_failed" in types(
    build(sessions=[f, rec("N2", "done", command="/other", at="2026-10-20T11:00:00+00:00")])
)
assert "session_failed" not in types(build(sessions=[{**f, "panel_role": "lens"}]))
for st_, kw in (
    ("waiting", {"pending_question": pq()}),
    ("failed", {"error": "boom"}),
    ("limited", {"auto_resume": True}),
    ("queued", {"batch": "b1"}),
):
    plain = rec("A1", st_, **kw)
    assert types(build(sessions=[plain])) != types(build()), st_
    assert types(build(sessions=[{**plain, "role": "away-answerer"}])) == types(build()), st_
print("  ok  session_failed")

# needs_cleanup: from the flags, until cleaned
res = build(flags={"o/r": {7: {"uncommitted": ["a.py"], "unpushed": ["abc"]}}})
n = one(res, "needs_cleanup")
assert (n["group"], n["key"], n["repo"], n["issue"], n["uncommitted"], n["unpushed"]) == (
    "fix", "cleanup:o/r#7", "o/r", 7, ["a.py"], ["abc"])  # fmt: skip
assert "needs_cleanup" not in types(build(flags={"o/r": {}}))
print("  ok  needs_cleanup")

# limited / queued: waiting, nothing to do
lim = rec("L1", "limited", claude_cmd="claude", limit_resets_at="2026-10-20T15:00:00Z", auto_resume=True)
qd = rec("Q1", "queued", note="queued: 3 of this batch run at once")
res = build(sessions=[lim, qd])
x, y = one(res, "limited"), one(res, "queued")
assert (x["group"], x["key"], x["account"], x["resets_at"], x["auto_resume"]) == (
    "wait", "limited:L1", "main", "2026-10-20T15:00:00Z", True)  # fmt: skip
assert (y["group"], y["key"], y["reason"]) == ("wait", "queued:Q1", "queued: 3 of this batch run at once")
assert one(build(sessions=[{**lim, "claude_cmd": "cc x", "auto_resume": None}]), "limited")["account"] == "cc x"
print("  ok  limited, queued")

# stale snapshots: no poller-derived items, listed in `stale`; the others are unaffected
prs = [pr(1)]
res = build(snapshots={"o/r": snap(prs), "o/s": snap(prs, stale=True), "o/t": {"stale": True, "fetched_at": None, "data": {}}},
            sessions=[s], watched=["o/r", "o/s", "o/t"])  # fmt: skip
assert [i["repo"] for i in res["items"] if i["type"] == "pr_ready"] == ["o/r"]
assert res["stale"] == ["o/s", "o/t"] and "question" in types(res)
assert build(snapshots={}, watched=["o/r"])["stale"] == ["o/r"]
print("  ok  stale repos")

# repo filter keeps that repo's items and the repo-less ones
mixed = build(
    gh={"ok": False, "login": None, "error": "x"},
    sessions=[s, {**rec("S2", "waiting", pending_question=pq()), "repo": "o/s"}],
    snapshots={"o/r": snap([pr(1)]), "o/s": snap([pr(1)])},
)
assert sorted((i["type"], i["repo"]) for i in mixed["items"] if i["type"] != "repo_unpublished") == [
    ("gh_auth", None), ("pr_ready", "o/r"), ("pr_ready", "o/s"), ("question", "o/r"), ("question", "o/s")]  # fmt: skip
only = build(repo="o/s", gh={"ok": False, "login": None, "error": "x"}, sessions=[s, {**rec("S2", "waiting", pending_question=pq()), "repo": "o/s"}],
             snapshots={"o/s": snap([pr(1)])})  # fmt: skip
assert sorted((i["type"], i["repo"]) for i in only["items"]) == [
    ("gh_auth", None),
    ("pr_ready", "o/s"),
    ("question", "o/s"),
]
assert only["stale"] == []
print("  ok  repo filter")

# order: by group, newest first inside it; keys are the same from poll to poll
sess = [
    rec("A", "waiting", pending_question=pq(), at="2026-10-20T09:00:00+00:00"),
    rec("B", "waiting", pending_question=pq(), at="2026-10-20T10:00:00+00:00"),
]
res = build(sessions=sess, gh={"ok": False, "login": None, "error": "x"})
assert [i["key"] for i in res["items"]][:3] == ["gh_auth", "question:B", "question:A"]
assert [i["key"] for i in build(sessions=sess)["items"]] == [i["key"] for i in build(sessions=sess)["items"]]
assert set(ui_inbox.GROUPS) == {"block", "answer", "decide", "fix", "setup", "wait"}
print("  ok  order and stable keys")


# rank: urgency inside a group, then newest first
def qi(k, at, group="answer", typ="question"):
    return {"key": k, "group": group, "type": typ, "repo": "o/r", "at": at}


old, new = qi("old", "2026-10-20T10:00:00+00:00"), qi("new", "2026-10-21T10:00:00+00:00")
r = ui_inbox.rank([new, old], lambda i: {"old": 5, "new": 1}[i["key"]])
assert [(i["key"], i["urgency"]) for i in r] == [("old", 5), ("new", 1)]
r = ui_inbox.rank([new, old], lambda i: 3 if i["key"] == "old" else None)  # scored old before unscored new
assert [i["key"] for i in r] == ["old", "new"] and r[1]["urgency"] is None
r = ui_inbox.rank([old, new], lambda i: 2)  # equal: newest first
assert [i["key"] for i in r] == ["new", "old"]
r = ui_inbox.rank([old, new], lambda i: None)  # no scores: time order
assert [i["key"] for i in r] == ["new", "old"] and all("urgency" in i for i in r)
lane = qi("lane", None, typ="dispatch_lane")
r = ui_inbox.rank([lane, old], lambda i: 1 if i["key"] == "old" else None)
assert [i["key"] for i in r] == ["old", "lane"]
fix = qi("fix", "2026-10-22T10:00:00+00:00", group="fix", typ="session_failed")
r = ui_inbox.rank([fix, old], lambda i: 5 if i["key"] == "fix" else 1)  # a high score never leaves its group
assert [i["key"] for i in r] == ["old", "fix"]
print("  ok  rank")

# urgency_text per type
q = {
    "type": "question",
    "questions": [{"question": "Merge?", "options": [{"label": "Yes", "description": "force"}, {"label": "No"}]}],
}
assert ui_inbox.urgency_text(q) == "Merge?\nYes\nforce\nNo"
assert ui_inbox.urgency_text({"type": "grind_paused", "reason": "CI red"}) == "CI red"
assert ui_inbox.urgency_text({"type": "session_failed", "error": "boom"}) == "boom"
assert "merge conflict" in ui_inbox.urgency_text({"type": "pr_conflict"})
assert ui_inbox.urgency_text({"type": "pr_ready"}) is None
assert ui_inbox.urgency_text({"type": "session_failed", "error": "  "}) is None
assert ui_inbox.urgency_text({"type": "question", "questions": []}) is None
print("  ok  urgency_text")

# prd_comment: one item per share with unseen reviewer activity
SH = {
    "id": "sh1",
    "repo": "O/R",
    "path": "docs/prds/x.md",
    "title": "My PRD",
    "comments": 1,
    "approvals": 0,
    "at": "2026-10-29T10:00:00+00:00",
}
S = ui_inbox.share_summary
assert S(1, 0, "T") == "1 new comment on T" and S(3, 0, "T") == "3 new comments on T"
assert S(1, 1, "T") == "1 new comment, 1 approval on T" and S(3, 2, "T") == "3 new comments, 2 approvals on T"
assert S(0, 1, "T") == "1 approval on T" and S(0, 4, "T") == "4 approvals on T"
res = build(shares=[SH])
it = one(res, "prd_comment")
assert (it["key"], it["group"], it["repo"], it["summary"]) == (
    "prd_comment:sh1",
    "decide",
    "o/r",
    "1 new comment on My PRD",
)
assert (it["share"], it["prd_path"], it["prd_title"], it["comments"], it["approvals"]) == (
    "sh1",
    "docs/prds/x.md",
    "My PRD",
    1,
    0,
)
assert it["at"] == SH["at"]
it2 = one(build(shares=[{**SH, "comments": 3, "approvals": 2}]), "prd_comment")
assert it2["key"] == it["key"] and it2["summary"] == "3 new comments, 2 approvals on My PRD"
assert one(build(shares=[{**SH, "comments": 0, "approvals": 2}]), "prd_comment")["summary"] == "2 approvals on My PRD"
assert "prd_comment" not in types(build(shares=[])) and "prd_comment" not in types(build())
assert "prd_comment" in types(build(repo="o/r", shares=[SH])) and "prd_comment" not in types(
    build(repo="o/s", shares=[SH])
)
assert [i["type"] for i in ui_inbox.rank([it], lambda i: 5)] == ["prd_comment"] and ui_inbox.urgency_text(it) is None
print("  ok  prd_comment items")

# ui_server._share_rows over the store
import dispatch  # noqa: E402
import ui_server  # noqa: E402
import ui_shares  # noqa: E402

co = tempfile.mkdtemp()
os.makedirs(os.path.join(co, "docs", "prds"))
with open(os.path.join(co, "docs", "prds", "x.md"), "w") as f:
    f.write("# Pretty title\n\nStatus: Draft\n")
dispatch.read_checkouts = lambda: {"o/r": co}
clock = [1000.0]
ui_shares.clock = lambda: clock[0]
rec, _ = ui_shares.create("o/r", "docs/prds/x.md", co)
assert ui_server._share_rows() == []
clock[0] += 5
t = ui_shares.add_thread(rec["id"], "Ana", "hello", {"exact": "x"})
ui_shares.add_approval(rec["id"], "Bo")
(row,) = ui_server._share_rows()
assert (row["id"], row["repo"], row["title"], row["comments"], row["approvals"]) == (
    rec["id"],
    "o/r",
    "Pretty title",
    1,
    1,
)
assert "Ana" not in str(row) and "hello" not in str(row)
ui_shares.add_owner_comment(rec["id"], t["id"], "me", "reply")  # an author reply never counts
assert ui_server._share_rows()[0]["comments"] == 1
clock[0] += 5
ui_shares.mark_seen(rec["id"])
assert ui_server._share_rows() == []
clock[0] += 5
ui_shares.add_comment(rec["id"], t["id"], "Ana", "again")
ui_shares.end(rec["id"], "stopped")  # an ended share keeps its unseen activity
(row,) = ui_server._share_rows()
assert row["comments"] == 1
os.remove(os.path.join(co, "docs", "prds", "x.md"))
assert ui_server._share_rows()[0]["title"] == "x"  # the file is gone: the stem
print("  ok  _share_rows")

# the registered listener raises one throttled prd-comment with only count and title
import ui_notify  # noqa: E402

raised = []
ui_notify.notify = lambda ev, r: raised.append((ev, r))
ui_notify._prd_last.clear()
with open(os.path.join(co, "docs", "prds", "y.md"), "w") as f:
    f.write("# Why title\n\nStatus: Draft\n")
ui_shares.listeners.append(ui_server._on_share_activity)
r3, _ = ui_shares.create("o/r", "docs/prds/y.md", co)
clock[0] += 5
ui_shares.add_thread(r3["id"], "Ana", "secret words", {"exact": "x"})
ui_shares.add_approval(r3["id"], "Bo")  # within the minute: throttled
assert raised == [("prd-comment", {"note": "1 new comment on Why title"})], raised
print("  ok  listener")
print("ui_inbox: all checks passed")
