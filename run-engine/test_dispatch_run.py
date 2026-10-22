#!/usr/bin/env python3
"""Self-check for run-engine/dispatch_run.py and dispatch_runners.py. `python3 test_dispatch_run.py` — exit 0 = green."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()
import dispatch  # noqa: E402
import dispatch_run as dr  # noqa: E402
import dispatch_runners  # noqa: E402

R = "o/r"
K = lambda n: dr.key(R, n)  # noqa: E731


class FakeRunner:
    def __init__(self):
        self.started, self.sent, self.closed = [], [], []

    def start(self, lane, prompt, d):
        self.started.append((lane["n"], prompt))
        return {"n": lane["n"]}

    def send(self, h, text):
        self.sent.append((h["n"], text))

    def close(self, h):
        self.closed.append(h["n"])


def fq(*ns):
    """Fresh facts for queued lanes: a lane only launches once its repo was polled."""
    return {K(n): {"blockers_open": []} for n in ns}


def child(n, deps=(), refined=True, base=None):
    return {"repo": R, "n": n, "title": f"i{n}", "refined": refined, "deps": [K(d) for d in deps], "base": base}


def pr(n=100, **kv):
    return {
        "n": n,
        "url": f"https://github.com/o/r/pull/{n}",
        "draft": False,
        "state": "OPEN",
        "ci": "success",
        "conflict": False,
        "approved": False,
        **kv,
    }


merges = []


def merge(repo, n):
    merges.append(n)
    return True, ""


# --- plan: waves, unrefined, cycles
p = dr.plan([child(1), child(2, [1]), child(3), child(4, [2, 3]), child(5, refined=False)])
assert p["waves"] == [[K(1), K(3)], [K(2)], [K(4)]], p
assert p["warnings"] == [f"{K(5)}: needs refine"]
assert "cycle" in dr.plan([child(1, [2]), child(2, [1])])["warnings"][0]
print("  ok  plan")

# --- settings validation
for bad in ({"grind": "deep"}, {"max": 0}, {"max": True}, {"feature_branch": "a b"}):
    try:
        dr.create("o/r#1", "headless", bad, [])
        raise AssertionError(f"accepted {bad}")
    except ValueError:
        pass
print("  ok  settings")

# --- launch order, cap, deps, needs refine
run = FakeRunner()
d = dr.create(
    "o/r#9",
    "herdr",
    {"max": 2, "grind": "full", "auto_merge": True},
    [child(3), child(1), child(2, [1]), child(4, refined=False)],
)
assert d["lanes"][K(4)]["stage"] == "skipped" and d["lanes"][K(4)]["skip_reason"] == "needs refine"
dr.tick(d, fq(1, 2, 3), run, merge, now=1000)
assert [s[0] for s in run.started] == [1, 3], run.started
assert run.started[0][1] == "/ai-workflow:implement-issue 1"
dr.tick(d, fq(1, 2, 3), run, merge, now=1001)
assert len(run.started) == 2  # cap holds, #2 waits on #1
print("  ok  launch order, cap, deps")

# --- implementing: blocked / idle need you once
f1 = {"issue_open": True, "slack": True, "agent": "blocked"}
ev = dr.tick(d, {K(1): f1}, run, merge, now=1002)
assert d["lanes"][K(1)]["needs_you"] == "waiting on you" and any(e["kind"] == "needs_you" for e in ev)
assert not [e for e in dr.tick(d, {K(1): f1}, run, merge, now=1003) if e["kind"] == "needs_you"]  # said once
dr.tick(d, {K(1): {**f1, "agent": "working"}}, run, merge, now=1004)
assert d["lanes"][K(1)]["needs_you"] is None
# an idle session is flagged only after the grace: the board may not have seen its PR yet
x = {"n": 1, "stage": "implementing"}
p1, _ = dr.step(x, {"agent": "idle"}, {}, 5000)
assert p1 == {"idle_since": 5000} and "needs_you" not in p1
x.update(p1)
p2, a2 = dr.step(x, {"agent": "idle"}, {}, 5000 + dr.IDLE_GRACE_SECONDS)
assert p2["needs_you"] == "stopped without a ready PR" and a2[0][0] == "notify"
x.update(p2)
p3, _ = dr.step(x, {"agent": "working"}, {}, 5300)
assert p3 == {"idle_since": None, "needs_you": None}
print("  ok  needs you")

# --- PR ready -> grinding (slack) ; no slack -> merge_gate
f1 = {"issue_open": True, "slack": True, "agent": "idle", "pr": pr(101)}
dr.tick(d, {K(1): f1}, run, merge, now=1005)
assert d["lanes"][K(1)]["stage"] == "grinding" and run.sent[-1] == (
    1,
    "/ai-workflow:pr-grind https://github.com/o/r/pull/101" + dr.LANE_GRIND,
)
f3 = {"issue_open": True, "slack": False, "agent": "idle", "pr": pr(103, approved=True)}
dr.tick(d, {K(3): f3}, run, merge, now=1006)
assert d["lanes"][K(3)]["stage"] == "merge_gate"
dr.tick(d, {K(3): f3}, run, merge, now=1007)
assert merges == [103]  # no grind for a repo without a channel: straight to the gate and merge
dr.tick(d, {K(3): f3}, run, merge, now=1008)
assert merges == [103]  # not merged twice before the board catches up
print("  ok  grind start, slack skip, single merge")

# --- grind: nudge once per due token, paused holds, done approved -> gate
g = lambda **kv: {**f1, "grind": {"state": "idle", "reason": "", "due": None, **kv}}  # noqa: E731
n0 = len(run.sent)
dr.tick(d, {K(1): g(due="r2")}, run, merge, now=1010)
dr.tick(d, {K(1): g(due="r2")}, run, merge, now=1011)
assert len(run.sent) == n0 + 1, (run.sent[n0:], d["lanes"][K(1)])
dr.tick(d, {K(1): g(state="paused", reason="rail: 5 rounds")}, run, merge, now=1012)
assert d["lanes"][K(1)]["held"] == "grind paused: rail: 5 rounds"
dr.tick(d, {K(1): g(state="running")}, run, merge, now=1013)
assert d["lanes"][K(1)]["held"] is None
dr.tick(d, {K(1): g(state="done", reason="approved")}, run, merge, now=1014)
assert d["lanes"][K(1)]["stage"] == "merge_gate"
print("  ok  grind nudge, pause, done")

# --- gate: no approval waits; red CI holds; conflict -> fix -> gate; merge
fg = {**f1, "grind": {"state": "done", "reason": "approved (simple)"}}
dr.tick(d, {K(1): fg}, run, merge, now=1015)
assert d["lanes"][K(1)]["gate"] == "no approving review" and 101 not in merges
assert dr._gate(d["lanes"][K(1)], {**fg, "solo": True}, d["settings"]) is None  # your own repo needs no approval
dr.tick(d, {K(1): {**fg, "pr": pr(101, approved=True, ci="failure")}}, run, merge, now=1016)
assert d["lanes"][K(1)]["held"] == "CI is red"
dr.tick(d, {K(1): {**fg, "pr": pr(101, approved=True, conflict=True)}}, run, merge, now=1017)
assert d["lanes"][K(1)]["stage"] == "conflict_fix" and "conflicts" in run.sent[-1][1]
dr.tick(d, {K(1): {**fg, "agent": "working", "pr": pr(101, approved=True, ci="pending")}}, run, merge, now=1018)
assert d["lanes"][K(1)]["stage"] == "conflict_fix"
dr.tick(d, {K(1): {**fg, "pr": pr(101, approved=True)}}, run, merge, now=1019)
assert d["lanes"][K(1)]["stage"] == "merge_gate"
dr.tick(d, {K(1): {**fg, "pr": pr(101, approved=True)}}, run, merge, now=1020)
assert merges[-1] == 101
print("  ok  merge gate, red CI, conflict")

# --- merged -> followups -> closed, tab closed, dependent #2 starts
fm = {**fg, "pr": pr(101, state="MERGED", approved=True)}
dr.tick(d, {K(1): fm}, run, merge, now=1021)
assert d["lanes"][K(1)]["stage"] == "followups" and "is merged" in run.sent[-1][1]
dr.tick(d, {K(1): {**fm, "agent": "working"}}, run, merge, now=1022)
assert d["lanes"][K(1)]["stage"] == "followups"
dr.tick(
    d, {K(1): {**fm, "issue_open": False}, K(3): {**f3, "pr": pr(103, state="MERGED")}, **fq(2)}, run, merge, now=1023
)
assert d["lanes"][K(1)]["stage"] == "closed" and 1 in run.closed
assert run.started[-1][0] == 2  # unblocked, slot free
print("  ok  followups, close, next lane")

# --- auto-merge off -> awaiting_merge; human merge picked up; hold/force
d2 = dr.create("o/r#8", "headless", {"grind": "off"}, [child(7, base="feature/x")])
run2 = FakeRunner()
dr.tick(d2, fq(7), run2, merge, now=1)
assert run2.started[0][1].startswith("/ai-workflow:implement-issue 7 (base branch feature/x")
f7 = {"issue_open": True, "slack": True, "agent": "idle", "pr": pr(107, approved=True)}
dr.tick(d2, {K(7): f7}, run2, merge, now=2)
ev = dr.tick(d2, {K(7): f7}, run2, merge, now=3)
assert d2["lanes"][K(7)]["stage"] == "awaiting_merge" and 107 not in merges
assert any(e["kind"] == "awaiting_merge" for e in ev)
dr.lane_action(d2["id"], K(7), "merge")
d2 = dr.load(d2["id"])
dr.tick(d2, {K(7): f7}, run2, merge, now=4)
assert merges[-1] == 107 and not d2["lanes"][K(7)]["force_merge"]
dr.tick(d2, {K(7): {**f7, "pr": pr(107, state="MERGED")}}, run2, merge, now=5)
assert "close #7 with `gh issue close`" in run2.sent[-1][1]  # non-default base: issue closes by hand
dr.tick(d2, {K(7): {**f7, "issue_open": False}}, run2, merge, now=6)
assert d2["state"] == "done"
print("  ok  awaiting merge, merge now, done")

# --- QA adds a child: done dispatch runs again
dr.sync_lanes(d2, [child(7), child(8)])
assert d2["state"] == "running" and d2["lanes"][K(8)]["stage"] == "queued"
print("  ok  new children reopen")

# --- usage limit: hold launches, continue after reset
d3 = dr.create("o/r#7", "herdr", {"max": 3}, [child(20), child(21, [20]), child(22)])
run3 = FakeRunner()
d3["settings"]["max"] = 1
dr.tick(d3, fq(20, 22), run3, merge, now=10)
dr.tick(d3, {K(20): {"agent": "idle", "limited_until": 9e9}}, run3, merge, now=11)
assert d3["lanes"][K(20)]["limited_until"] == 9e9
d3["settings"]["max"] = 3
dr.tick(d3, {K(20): {"agent": "idle", "limited_until": 9e9}}, run3, merge, now=12)
assert len(run3.started) == 1  # no launches while limited
d3["lanes"][K(20)]["limited_until"] = 100
dr.tick(d3, {K(20): {"agent": "idle"}}, run3, merge, now=200)
assert run3.sent[-1][1] == dr.CONTINUE and d3["lanes"][K(20)]["limited_until"] is None
print("  ok  usage limit")

# --- gone session, retry restarts in stage; paused lane does nothing; skip
d3["lanes"][K(20)].update(stage="grinding", pr=120)
dr.tick(d3, {K(20): {"agent": "gone", "slack": True}}, run3, merge, now=300)
assert d3["lanes"][K(20)]["needs_you"] == "the lane session is gone"
dr.save(d3)
dr.lane_action(d3["id"], K(20), "retry")
d3 = dr.load(d3["id"])
dr.tick(d3, {K(20): {"agent": "working", "slack": True, "pr": pr(120)}}, run3, merge, now=301)
assert run3.started[-1] == (20, "/ai-workflow:pr-grind https://github.com/o/r/pull/120" + dr.LANE_GRIND)
dr.lane_action(d3["id"], K(20), "pause")
d3 = dr.load(d3["id"])
assert dr.step(d3["lanes"][K(20)], {"pr": pr(120, state="MERGED")}, d3["settings"], 400) == ({}, [])
dr.lane_action(d3["id"], K(22), "skip")
assert dr.load(d3["id"])["lanes"][K(22)]["skip_reason"] == "skipped by you"
print("  ok  gone, retry, pause, skip")

# --- send and skip go through the outbox; channel rides on the grind prompt
dr.lane_action(d3["id"], K(20), "resume")
dr.lane_action(d3["id"], K(20), "send", "please rebase")
try:
    dr.lane_action(d3["id"], K(21), "send", "x")  # queued, no session
    raise AssertionError("send to a lane without a session")
except ValueError:
    pass
d3 = dr.load(d3["id"])
dr.tick(d3, {}, run3, merge, now=500)
assert run3.sent[-1] == (20, "please rebase") and "outbox" not in d3["lanes"][K(20)]
assert dr.grind_prompt("u", "C1", lane=False) == "/ai-workflow:pr-grind u --channel C1"
assert dr.grind_prompt("u", "", lane=False) == "/ai-workflow:pr-grind u" == dr.grind_prompt("u", "a b", lane=False)
assert len(dr.grind_prompt("https://github.com/owner-name/repo-name/pull/12345", "C0123456789")) < 480
assert len(dr.grind_prompt("https://github.com/owner-name/repo-name/pull/12345", "C0123456789")) < 480
print("  ok  outbox, channel")

# --- end actions: open-pr needs a feature branch; qa and grind-pr start sessions
gh_calls = []


def fake_gh(argv):
    gh_calls.append(argv)
    out = "master\n" if argv[:2] == ["repo", "view"] else "https://github.com/o/r/pull/900\n"
    return subprocess.CompletedProcess(argv, 0, out, "")


try:
    dr.request_end(d3["id"], "open-pr")
    raise AssertionError("open-pr without a feature branch")
except ValueError:
    pass
d5 = dr.create("o/r#50", "headless", {"feature_branch": "feature/x"}, [child(51)])
try:
    dr.request_end(d5["id"], "grind-pr")
    raise AssertionError("grind-pr before open-pr")
except ValueError:
    pass
dr.request_end(d5["id"], "open-pr")
dr.request_end(d5["id"], "qa")
d5 = dr.load(d5["id"])
run5 = FakeRunner()
dr.tick(d5, {}, run5, merge, now=1, gh=fake_gh)
assert d5["final_prs"] == {"o/r": "https://github.com/o/r/pull/900"}
assert gh_calls[1][:8] == ["pr", "create", "-R", "o/r", "--base", "master", "--head", "feature/x"]
assert (
    run5.started[0][0] == 50
    and "verifier-locally" in run5.started[0][1]
    and "on branch feature/x" in run5.started[0][1]
)
dr.save(d5)
dr.request_end(d5["id"], "grind-pr")
d5 = dr.load(d5["id"])
dr.tick(d5, {}, run5, merge, now=2, gh=fake_gh)
assert run5.started[-1] == (900, "/ai-workflow:pr-grind https://github.com/o/r/pull/900")
print("  ok  end actions")

# --- live settings edit, dispatch pause stops launches
dr.set_settings(d3["id"], grind="simple", auto_merge=True)
assert dr.load(d3["id"])["settings"]["grind"] == "simple"
dp = dr.set_state(d3["id"], "paused")
assert dr.startable(dp, {}) == []
assert dr.list_all()[0]["id"] == d5["id"] and d3["id"] in [x["id"] for x in dr.list_all()]
try:
    dr.load("../etc")
    raise AssertionError("bad id loaded")
except ValueError:
    pass
print("  ok  live edit, pause, store")

# --- outside blocker still open holds a lane
d4 = dr.create("o/r#6", "headless", {}, [child(30)])
assert dr.startable(d4, {K(30): {"blockers_open": ["x/y#1"]}}) == []
assert dr.startable(d4, {K(30): {"blockers_open": []}}) == [K(30)]
print("  ok  outside blockers")

# --- runners: limit text, herdr commands, headless status
now = datetime(2026, 10, 23, 14, 0)
assert (
    datetime.fromtimestamp(dispatch_runners.limit_reset("x\n5-hour limit reached ∙ resets 3pm (Asia/Dhaka)", now)).hour
    == 15
)
assert datetime.fromtimestamp(dispatch_runners.limit_reset("You've hit your limit · resets 9:30am", now)).day == 24
assert dispatch_runners.limit_reset("all good", now) is None
co = tempfile.mkdtemp()
dispatch.register_checkout(R, co)
calls = []


def cli(argv, timeout=60):
    calls.append(argv)
    out = ""
    if argv[:2] == ["tab", "create"]:
        out = json.dumps({"result": {"tab": {"tab_id": "t1"}, "pane": {"pane_id": "p1"}}})
    elif argv[:2] == ["tab", "list"]:
        out = json.dumps({"result": {"tabs": [{"tab_id": "t1", "agent_status": "idle"}]}})
    elif argv[:2] == ["pane", "read"]:
        out = "done\n  2 monitors running"
    return subprocess.CompletedProcess(argv, 0, out, "")


hd = dispatch_runners.Herdr("w1", cli)
h = hd.start(
    {"repo": R, "n": 5}, "/ai-workflow:implement-issue 5", {"id": "abc", "settings": {"model": "opus", "effort": None}}
)
assert h == {"tab": "t1", "pane": "p1", "agent": "aiw-abc-issue-5"}
assert calls[0] == ["tab", "create", "--workspace", "w1", "--cwd", co, "--label", "issue-5", "--no-focus"]
assert calls[1][-4:] == ["--", "--dangerously-skip-permissions", "--model", "opus"]
assert calls[2] == ["agent", "prompt", "aiw-abc-issue-5", "/ai-workflow:implement-issue 5"]
assert hd.status(h) == ("working", None)  # idle but waiting on its own monitors
assert hd.status({"tab": "gone"}) == ("gone", None)
hd.close(h)
assert calls[-1] == ["tab", "close", "t1"]


class FakeSessions:
    recs = {"s1": {"status": "waiting"}, "s2": {"status": "failed"}}

    def load(self, sid):
        return self.recs.get(sid)


hl = dispatch_runners.Headless(runner=object(), sessions=FakeSessions())
assert hl.status({"session": "s1"}) == ("blocked", None) and hl.status({"session": "s2"})[0] == "gone"
assert hl.status({"session": "nope"})[0] == "gone"
print("  ok  runners")
print("dispatch_run: all green")
