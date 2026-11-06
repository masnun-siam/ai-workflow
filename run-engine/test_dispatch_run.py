#!/usr/bin/env python3
"""Self-check for run-engine/dispatch_run.py and dispatch_runners.py. `python3 test_dispatch_run.py` — exit 0 = green."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()
import dispatch  # noqa: E402
import dispatch_run as dr  # noqa: E402
import dispatch_runners  # noqa: E402

real_create = dr.create


def _create_reusing_keys(*a, **kw):
    """Most checks reuse lane keys: park the earlier dispatches as done so ownership does not refuse them."""
    for old in dr.list_all():
        if old["state"] not in ("done", "cancelled"):
            old["state"] = "done"
            dr.save(old)
    return real_create(*a, **kw)


dr.create = _create_reusing_keys

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
        "changes_requested": False,
        "sha": "a" * 40,
        **kv,
    }


merges = []
merge_shas = []


def merge(repo, n, sha):
    merges.append(n)
    merge_shas.append(sha)
    return True, ""


# --- plan: waves, unrefined, cycles
p = dr.plan([child(1), child(2, [1]), child(3), child(4, [2, 3]), child(5, refined=False)])
assert p["waves"] == [[K(1), K(3)], [K(2)], [K(4)]], p
assert p["warnings"] == [f"{K(5)}: needs refine"]
assert "cycle" in dr.plan([child(1, [2]), child(2, [1])])["warnings"][0]
print("  ok  plan")

# --- settings validation
for bad in ({"ci": "x"}, {"grind": "deep"}, {"max": 0}, {"max": True}, {"feature_branch": "a b"}):
    try:
        dr.create("o/r#1", "headless", bad, [])
        raise AssertionError(f"accepted {bad}")
    except ValueError as e:
        if "ci" in bad:
            assert str(e) == "ci must be one of ('wait', 'defer', 'ignore')", e
assert dr.create("o/r#1", "headless", {}, [])["settings"]["ci"] == "wait"
assert dr.create("o/r#1", "headless", {}, [])["settings"]["base_branch"] is None
for ok in ("staging", "release/1.4"):
    assert dr.create("o/r#1", "headless", {"base_branch": ok}, [])["settings"]["base_branch"] == ok
for bad in ("bad name", "", "x;rm", "a" * 101, 5, {"base_branch": "feat/x", "feature_branch": "feat/x"}):
    try:
        dr.create("o/r#1", "headless", bad if isinstance(bad, dict) else {"base_branch": bad}, [])
        raise AssertionError(f"accepted base_branch {bad!r}")
    except ValueError:
        pass
# fixed at start: refused live, even with the stored value
bb = dr.create("o/r#1", "headless", {"base_branch": "staging"}, [])
for v in ("other", "staging"):
    try:
        dr.set_settings(bb["id"], base_branch=v)
        raise AssertionError("live base_branch accepted")
    except ValueError as e:
        assert str(e) == "base_branch is fixed at start", e
# a record saved before the setting loads as empty
old = dr.load(bb["id"])
del old["settings"]["base_branch"]
dr.save(old)
assert dr.load(bb["id"])["settings"]["base_branch"] is None
print("  ok  settings")

# --- issue-list dispatch
il = dr.create(None, "headless", {"grind": "off"}, [child(7), child(2)], issues=["o/r#7", "o/r#2"])
assert il["epic"] is None and il["issues"] == ["o/r#2", "o/r#7"] and il["title"] == "Small changes: #2, #7"
assert "issues" not in dr.create("o/r#1", "headless", {}, [])
assert dr.issues_title([f"o/r#{n}" for n in (9, 5, 1, 3, 4)]) == "Small changes: #1, #3, #4 +2 more"
for fn in (
    lambda: dr.create(None, "headless", {"feature_branch": "f/x"}, [], issues=["o/r#1"]),
    lambda: dr.set_settings(il["id"], feature_branch="f/x"),
):
    try:
        fn()
        raise AssertionError("feature_branch accepted")
    except ValueError:
        pass
assert (
    dr.create(None, "headless", {"base_branch": "hotfix"}, [child(8)], issues=["o/r#8"])["settings"]["base_branch"]
    == "hotfix"
)
# end actions are refused for an issue list, and nothing is recorded
for act in dr.END_ACTIONS:
    try:
        dr.request_end(il["id"], act)
        raise AssertionError(f"{act} accepted")
    except ValueError:
        pass
assert not dr.load(il["id"]).get("end_requests")
assert dr.dispatch_repo(il) == "o/r" and dr.dispatch_repo({"epic": "a/b#1", "issues": None}) == "a/b"
# a two-lane list dispatch walks to done under the cap, merging both
dl = dr.create(
    None,
    "headless",
    {"max": 1, "grind": "off", "auto_merge": True},
    [child(21), child(22)],
    issues=["o/r#21", "o/r#22"],
)
rl, lm = FakeRunner(), []
merge_l = lambda repo, n, sha: (lm.append(n), (True, ""))[1]  # noqa: E731
for t, n in ((1, 21), (2, 22)):
    dr.tick(dl, fq(21, 22), rl, merge_l, now=t)
    assert (
        len(rl.started) == (1 if n == 21 else 2)
        and sum(x["stage"] == "implementing" for x in dl["lanes"].values()) == 1
    )
    dl["lanes"][K(n)].update(stage="merge_gate", pr=n * 10)
    dr.tick(dl, {K(n): {"issue_open": True, "agent": "idle", "solo": True, "pr": pr(n * 10)}}, rl, merge_l, now=t + 0.5)
    gone = {"issue_open": False, "agent": "idle", "pr": pr(n * 10, state="MERGED")}
    for dt in (0.7, 0.8):
        dr.tick(dl, {K(n): gone}, rl, merge_l, now=t + dt)
assert lm == [210, 220], lm
dr.tick(dl, {}, rl, merge_l, now=10)
assert dl["state"] == "done", {k: x["stage"] for k, x in dl["lanes"].items()}
print("  ok  issue list")

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
assert run.started[0][1] == "/blubird:implement-issue 1"
dr.tick(d, fq(1, 2, 3), run, merge, now=1001)
assert len(run.started) == 2  # cap holds, #2 waits on #1
print("  ok  launch order, cap, deps")


_d, _run = d, run  # the sections below reuse these names


# --- lanes stranded behind a skipped blocker or in a cycle get needs_you once
def strand_d(*kids):
    return dr.create("o/r#9", "herdr", {"max": 2, "grind": "full", "auto_merge": True}, list(kids))


d = strand_d(child(1, refined=False), child(2, [1]), child(3, [2]))
run = FakeRunner()
ev1 = dr.tick(d, fq(2, 3), run, merge, now=1000)
assert d["lanes"][K(2)]["needs_you"] == "blocked by skipped #1", d["lanes"][K(2)]
assert d["lanes"][K(3)]["needs_you"] == "blocked by skipped #1"  # the skipped root, not the middle lane
assert [e["kind"] for e in ev1].count("needs_you") == 2 and not run.started
assert not [e for e in dr.tick(d, fq(2, 3), run, merge, now=1001) if e["kind"] == "needs_you"]  # once per reason
dr.apply_lane_action(d, K(1), "retry")  # blocker back to queued: stale reasons clear at the next tick
dr.tick(d, fq(1, 2, 3), run, merge, now=1002)
assert d["lanes"][K(2)].get("needs_you") is None and d["lanes"][K(3)].get("needs_you") is None
assert [s[0] for s in run.started] == [1]

d = strand_d(child(1), child(2, [1]))
dr.apply_lane_action(d, K(1), "skip")
dr.tick(d, fq(2), FakeRunner(), merge, now=1000)
assert d["lanes"][K(2)]["needs_you"] == "blocked by skipped #1"
dr.apply_lane_action(d, K(2), "skip")
dr.tick(d, fq(), FakeRunner(), merge, now=1001)
assert d["state"] == "done"

d = strand_d(child(1, [2]), child(2, [1]))
dr.tick(d, fq(1, 2), FakeRunner(), merge, now=1000)
assert d["lanes"][K(1)]["needs_you"] == d["lanes"][K(2)]["needs_you"] == "dependency cycle"

# merely waiting: no needs_you
d = strand_d(child(1), child(2, [1]))
dr.tick(d, fq(1, 2), FakeRunner(), merge, now=1000)  # #1 active, #2 waits
assert d["lanes"][K(2)].get("needs_you") is None
d = strand_d(child(1, [5]))  # blocker outside the dispatch
dr.tick(d, {K(1): {"blockers_open": [dr.key(R, 5)]}}, FakeRunner(), merge, now=1000)
assert d["lanes"][K(1)].get("needs_you") is None
d = strand_d(child(1, refined=False), child(2, [1]))
d["lanes"][K(2)]["paused"] = True
dr.tick(d, fq(2), FakeRunner(), merge, now=1000)
assert d["lanes"][K(2)].get("needs_you") is None
d, run = _d, _run
print("  ok  stranded lanes")

# --- diagnose (#741)
d = strand_d(child(1), child(2, [1]))
assert dr.diagnose(d, {R: {"stale": False, "error": None}}) == []  # healthy
dr.apply_lane_action(d, K(1), "skip")
assert dr.diagnose(d, {}) == [{"lane": K(2), "problem": "blocked by skipped #1"}]
dr.tick(d, fq(2), FakeRunner(), merge, now=1000)  # needs_you now holds the same reason: listed once
assert dr.diagnose(d, {}) == [{"lane": K(2), "problem": "blocked by skipped #1"}]
d = strand_d(child(1, [2]), child(2, [1]))
assert {p["problem"] for p in dr.diagnose(d, {})} == {"dependency cycle"}
d = strand_d(child(1))
got = dr.diagnose(d, {R: {"stale": True, "error": "rate limited"}})
assert got == [{"lane": None, "problem": f"stale poll snapshot for {R}: rate limited"}], got
assert dr.diagnose(d, {"other/repo": {"stale": True}}) == []  # not this dispatch's repo
d["lanes"][K(1)].update(stage="grinding", held="CI is red")
assert dr.diagnose(d, {}) == [{"lane": K(1), "problem": "held: CI is red"}]
d["state"] = "cancelled"
assert dr.diagnose(d, {R: {"stale": True}}) == []
d, run = _d, _run
print("  ok  diagnose")


# --- a handle is on disk as soon as its session starts: a crash later in the tick cannot lose it
class Boom(BaseException):
    pass


class BoomRunner(FakeRunner):
    def __init__(self, boom_on):
        super().__init__()
        self.boom_on = boom_on

    def start(self, lane, prompt, d):
        if len(self.started) == self.boom_on:
            raise Boom()
        return super().start(lane, prompt, d)


hd = dr.create("o/r#13", "herdr", {"max": 2}, [child(1), child(2)])
try:
    dr.tick(hd, fq(1, 2), BoomRunner(1), merge, now=1000)
except Boom:
    pass
x = dr.load(hd["id"])["lanes"][K(1)]
assert x["stage"] == "implementing" and x["handle"] == {"n": 1} and x["handles"] == [{"n": 1}], x
# restart start: lane 1 restarts (saved), then lane 2's launch crashes
hd = dr.create("o/r#14", "herdr", {"max": 2}, [child(1), child(2)])
dr.tick(hd, fq(1), FakeRunner(), merge, now=1000)
hd["lanes"][K(1)].update(restart=True, handle=None, handles=[])
try:
    dr.tick(hd, {**fq(2), K(1): {}}, BoomRunner(1), merge, now=1001)
except Boom:
    pass
x = dr.load(hd["id"])["lanes"][K(1)]
assert x["handle"] == {"n": 1} and x["handles"] == [{"n": 1}], x
print("  ok  handle saved at start")

# --- implementing: blocked / idle need you once
f1 = {"issue_open": True, "slack": True, "agent": "blocked"}
ev = dr.tick(d, {K(1): f1}, run, merge, now=1002)
assert d["lanes"][K(1)]["needs_you"] == "waiting on you" and any(e["kind"] == "needs_you" for e in ev)
assert not [e for e in dr.tick(d, {K(1): f1}, run, merge, now=1003) if e["kind"] == "needs_you"]  # said once
dr.tick(d, {K(1): {**f1, "agent": "working"}}, run, merge, now=1004)
assert d["lanes"][K(1)].get("needs_you") is None
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
# a PR is tracked once open; ready with red CI and a stopped session is "CI is red", not "no ready PR"
x = {"n": 1, "stage": "implementing", "needs_you": "stopped without a ready PR"}
p4, _ = dr.step(x, {"agent": "working", "pr": pr(140, draft=True, ci="pending")}, {}, 6000)
assert p4["pr"] == 140 and "held" not in p4
p5, a5 = dr.step(x, {"agent": "idle", "pr": pr(140, ci="failure")}, {}, 6000)
assert p5 == {"pr": 140, "held": "CI is red", "needs_you": None, "idle_since": None}, p5
assert a5 == [("notify", "held", "CI is red on PR #140")]
x.update(p5)
assert dr.step(x, {"agent": "idle", "pr": pr(140, ci="failure")}, {}, 6001) == ({}, [])  # said once
p6, _ = dr.step(x, {"agent": "working", "pr": pr(140, ci="failure")}, {}, 6002)
assert p6 == {"held": None}  # back on it
print("  ok  needs you, red CI while implementing")

# --- ci defer / ignore: no waiting for CI before the gate
for mode in ("defer", "ignore"):
    for ci_state in ("failure", "pending", "success", "none"):
        ln = {"n": 9, "stage": "implementing"}
        pa, aa = dr.step(ln, {"agent": "idle", "slack": True, "pr": pr(9, ci=ci_state)}, {"ci": mode}, 7000)
        assert pa["stage"] == "grinding" and pa.get("held") is None, (mode, ci_state, pa)
        assert [a[0] for a in aa] == ["send"] and aa[0][1].endswith(dr.SKIP_CI_REPLY), aa
        pa, aa = dr.step(ln, {"agent": "idle", "pr": pr(9, ci=ci_state)}, {"ci": mode, "grind": "off"}, 7000)
        assert pa["stage"] == "merge_gate" and pa["held"] is None and not aa, (mode, ci_state, pa, aa)
pw, _ = dr.step({"n": 9, "stage": "implementing"}, {"agent": "idle", "pr": pr(9, ci="failure")}, {"ci": "wait"}, 7000)
assert pw["held"] == "CI is red"
rel, _ = dr.step(
    {"n": 9, "stage": "implementing", "held": "CI is red"},
    {"agent": "idle", "slack": True, "pr": pr(9, ci="failure")},
    {"ci": "defer"},
    7001,
)
assert rel["held"] is None and rel["stage"] == "grinding"
# the merge action carries the head sha; an unknown head is never merged unpinned
mg = {"n": 9, "stage": "merge_gate"}
pm, am = dr.step(mg, {"agent": "idle", "solo": True, "pr": pr(9)}, {"auto_merge": True}, 7100)
assert am == [("merge", 9, "a" * 40)], am
pm, am = dr.step(mg, {"agent": "idle", "solo": True, "pr": pr(9, sha=None)}, {"auto_merge": True}, 7100)
assert pm["gate"] == "head commit unknown" and not am, (pm, am)
cf = {"n": 9, "stage": "conflict_fix"}
cfacts = {"agent": "idle", "pr": pr(9, ci="pending", conflict=False)}
assert dr.step(cf, cfacts, {"ci": "defer"}, 7002)[0]["stage"] == "merge_gate"
assert dr.step(cf, cfacts, {"ci": "wait"}, 7002)[0] == {}
assert "CI mode defer: mark the PR ready after local checks and review pass; do not wait for CI" in dr.implement_prompt(
    5, "master", ci="defer"
)
assert dr.implement_prompt(5, "master", ci="wait") == dr.implement_prompt(5, "master")
assert "CI mode" not in dr.stage_prompt({"n": 5, "stage": "implementing"}, {})
assert dr.grind_prompt("u", ci="wait") == "/ai-workflow:pr-grind u" + dr.LANE_GRIND
assert dr.grind_prompt("u", lane=False, ci="defer") == "/ai-workflow:pr-grind u"
assert dr.stage_prompt({"n": 5, "stage": "grinding"}, {"ci": "ignore"}, "u").endswith(dr.SKIP_CI_REPLY)
print("  ok  ci defer / ignore skip CI before the gate")

# --- PR ready -> grinding (slack) ; no slack -> merge_gate
f1 = {"issue_open": True, "slack": True, "agent": "idle", "pr": pr(101)}
dr.tick(d, {K(1): f1}, run, merge, now=1005)
assert d["lanes"][K(1)]["stage"] == "grinding" and run.sent[-1] == (
    1,
    "/ai-workflow:pr-grind https://github.com/o/r/pull/101" + dr.LANE_GRIND,
)
_, a = dr.step({"n": 1, "stage": "implementing"}, {**f1, "channel": "C1", "reviewer": "bob"}, {}, 1005)
assert a == [("send", "/ai-workflow:pr-grind https://github.com/o/r/pull/101 --channel C1" + dr.LANE_GRIND)], a
f3 = {"issue_open": True, "slack": False, "agent": "idle", "pr": pr(103, approved=True)}
dr.tick(d, {K(3): f3}, run, merge, now=1006)
assert d["lanes"][K(3)]["stage"] == "merge_gate"
dr.tick(d, {K(3): f3}, run, merge, now=1007)
assert merge_shas == ["a" * 40]  # pinned to the facts' head
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
assert dr._gate(d["lanes"][K(1)], {**fg, "solo": True}, d["settings"], 1015) is None  # your own repo needs no approval
cr = {**fg, "pr": pr(101, approved=True, changes_requested=True)}
assert dr._gate(d["lanes"][K(1)], cr, d["settings"], 1015) == "changes requested"
assert dr._gate(d["lanes"][K(1)], {**cr, "solo": True}, d["settings"], 1015) == "changes requested"
assert (
    dr._gate(d["lanes"][K(1)], {**fg, "pr": pr(101, draft=True, approved=True)}, d["settings"], 1015) == "PR is a draft"
)
assert (
    dr._gate(d["lanes"][K(1)], {**fg, "pr": pr(101, conflict=True, approved=True)}, d["settings"], 1015)
    == "PR has a merge conflict"
)
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
# GitHub refuses the merge for a conflict the board has not seen yet: straight to the lane's conflict fix
dc = dr.create("o/r#90", "headless", {"grind": "off", "auto_merge": True}, [child(91)])
rc = FakeRunner()
dc["lanes"][K(91)].update(stage="merge_gate", handle={"n": 91}, pr=191)
dr.tick(
    dc,
    {K(91): {"issue_open": True, "agent": "idle", "solo": True, "pr": pr(191)}},
    rc,
    lambda r, n, sha: (False, "GraphQL: Pull Request has merge conflicts (mergePullRequest)"),
    now=1,
)
assert dc["lanes"][K(91)]["stage"] == "conflict_fix" and not dc["lanes"][K(91)].get("held")
assert "conflicts" in rc.sent[-1][1]
# GitHub refuses the merge because the head is behind its base: the base is merged in, no hold
BEHIND = "X Pull request o/r#191 is not mergeable: the head branch is not up to date with the base branch."
for rc_upd, want in ((0, "merge_gate"), (1, "conflict_fix")):
    db_ = dr.create("o/r#94", "headless", {"grind": "off", "auto_merge": True}, [child(95)])
    rb, ub = FakeRunner(), []
    db_["lanes"][K(95)].update(stage="merge_gate", handle={"n": 95}, pr=195)
    dr.tick(
        db_,
        {K(95): {"issue_open": True, "agent": "idle", "solo": True, "pr": pr(195)}},
        rb,
        lambda r, n, sha: (False, BEHIND),
        now=1,
        gh=lambda argv: (ub.append(argv), subprocess.CompletedProcess(argv, rc_upd, "", ""))[1],
    )
    lb = db_["lanes"][K(95)]
    assert ub == [["pr", "update-branch", "195", "-R", "o/r"]], ub
    assert lb["stage"] == want and not lb.get("held") and not lb.get("merge_fails"), lb
# merged after the lane's session was closed: followups start a fresh session, not a send to None
dm = dr.create("o/r#92", "headless", {"grind": "off", "auto_merge": True}, [child(93)])
rm = FakeRunner()
dm["lanes"][K(93)].update(stage="merge_gate", handle=None, pr=193)
dr.tick(dm, {K(93): {"issue_open": True, "agent": None, "solo": True, "pr": pr(193, state="MERGED")}}, rm, merge, now=1)
assert dm["lanes"][K(93)]["stage"] == "followups" and not dm["lanes"][K(93)].get("needs_you")
assert rm.started and rm.started[-1][0] == 93 and dm["lanes"][K(93)]["handle"] == {"n": 93}
# a failed merge keeps its error, counts, asks for you after 3, and clears on success / retry / red CI


def boom(r, n, sha):
    return (False, "boom")


dq = dr.create("o/r#94", "headless", {"grind": "off", "auto_merge": True}, [child(95)])
rq = FakeRunner()
dq["lanes"][K(95)].update(stage="merge_gate", handle={"n": 95}, pr=195)
fq95 = {K(95): {"issue_open": True, "agent": "idle", "solo": True, "pr": pr(195)}}


def kinds():
    return [e["kind"] for e in dq["events"]]


dr.tick(dq, fq95, rq, boom, now=1)
L = dq["lanes"][K(95)]
assert L["held"] == "merge failed: boom" and L["merge_error"] == "boom" and L["merge_fails"] == 1
dr.tick(dq, fq95, rq, boom, now=10)  # inside the retry window: the error stays
assert L["held"] == "merge failed: boom" and L["merge_fails"] == 1
dr.tick(dq, fq95, rq, boom, now=400)
assert L["merge_fails"] == 2 and kinds().count("held") == 1 and not L.get("needs_you")
dr.tick(dq, fq95, rq, boom, now=800)
assert L["needs_you"] == "merge failed 3 times: boom" and kinds().count("needs_you") == 1
dr.tick(dq, fq95, rq, lambda r, n, sha: (False, "other"), now=1200)
assert L["merge_error"] == "other" and kinds().count("held") == 2
dr.tick(dq, {K(95): {**fq95[K(95)], "pr": pr(195, ci="failure")}}, rq, boom, now=1201)  # red CI: stale error dropped
assert L["held"] == "CI is red" and not L.get("merge_error") and not L["merge_fails"] and not L.get("needs_you")
dr.tick(dq, fq95, rq, boom, now=2000)
assert L["merge_fails"] == 1
dr.apply_lane_action(dq, K(95), "retry")
assert not (L.get("merge_error") or L.get("merge_fails") or L.get("held") or L.get("needs_you"))
for t in range(3000, 5000, 400):  # the first tick restarts the session
    dr.tick(dq, fq95, rq, boom, now=t)
assert L.get("needs_you")
dr.tick(dq, fq95, rq, merge, now=9000)  # a merge that works clears the lot
assert not (L.get("merge_error") or L.get("merge_fails") or L.get("held") or L.get("needs_you"))
print("  ok  merge gate, red CI, conflict")


# --- merge gate follows the ci mode
def gate_facts(ci, sha="a"):
    return {"agent": "idle", "solo": True, "pr": pr(9, ci=ci, sha=sha)}


for mode, ci_state, want in [
    ("wait", "failure", "CI is not green"), ("wait", "pending", "CI is not green"), ("wait", "none", "CI not registered yet"),
    ("wait", "success", None), ("defer", "failure", "waiting for green CI (defer)"),
    ("defer", "pending", "waiting for green CI (defer)"), ("defer", "none", "CI not registered yet"), ("defer", "success", None),
    ("ignore", "failure", None), ("ignore", "pending", None), ("ignore", "success", None),
]:  # fmt: skip
    assert dr._gate({}, gate_facts(ci_state), {"ci": mode, "grind": "off"}, 0) == want, (mode, ci_state)
assert dr._gate({}, gate_facts("failure"), {"grind": "off"}, 0) == "CI is not green"  # no ci setting: wait
# unresolved review threads block in every ci mode, solo or not
for mode in ("wait", "defer", "ignore"):
    tf = {**gate_facts("success"), "pr": pr(9, ci="success", approved=True, threads_open=2)}
    assert dr._gate({}, tf, {"ci": mode, "grind": "off"}, 0) == "unresolved review threads", mode
# CI `none`: blocked for NONE_GRACE_SECONDS from the first sighting of this sha, then it passes (wait and defer)
for mode in ("wait", "defer"):
    st = {"ci": mode, "grind": "off"}
    ln = {"none_since": 100, "none_sha": "a"}
    g_ = dr.NONE_GRACE_SECONDS
    assert dr._gate(ln, gate_facts("none"), st, 100 + g_ - 1) == "CI not registered yet", mode
    assert dr._gate(ln, gate_facts("none"), st, 100 + g_) is None, mode
    assert dr._gate(ln, gate_facts("none", sha="b"), st, 100 + g_) == "CI not registered yet", "new sha restarts"
nl = {"n": 9, "stage": "merge_gate"}
pn, _ = dr.step(nl, gate_facts("none"), {"ci": "wait", "grind": "off"}, 500)
assert pn["none_since"] == 500 and pn["none_sha"] == "a" and pn["gate"] == "CI not registered yet", pn
nl.update(pn)
pn2, _ = dr.step(nl, gate_facts("none"), {"ci": "wait", "grind": "off"}, 500 + dr.NONE_GRACE_SECONDS)
assert pn2["gate"] is None and "none_since" not in pn2, pn2
pn3, _ = dr.step(nl, gate_facts("success"), {"ci": "wait", "grind": "off"}, 600)
assert pn3["none_since"] is None and pn3["none_sha"] is None  # cleared once CI registers
dset = {"ci": "defer", "grind": "off", "auto_merge": True}
lane = {"n": 9, "stage": "merge_gate"}
p1, a1 = dr.step(lane, gate_facts("failure"), dset, 8000)
assert p1["gate"] == "waiting for green CI (defer)" and not p1.get("held")
assert a1 == [("send", dr.ci_fix_prompt(9))] and p1["ci_fixed"] == "a"
lane.update(p1)
p2, a2 = dr.step(lane, gate_facts("failure"), dset, 8001)
assert not a2 and not any(x[0] == "merge" for x in a2)  # same head commit: no second prompt
p3, a3 = dr.step(lane, gate_facts("failure", sha="b"), dset, 8002)
assert a3 == [("send", dr.ci_fix_prompt(9))]  # a new red push prompts again
p4, a4 = dr.step({**lane, "stage": "awaiting_merge"}, gate_facts("pending"), dset, 8003)
assert p4["stage"] == "merge_gate" and not a4
for ci_state in ("success", "none"):
    lane_ci = {**lane, "none_since": 100, "none_sha": "a"}  # `none` for longer than the grace
    pm, am = dr.step(lane_ci, gate_facts(ci_state), dset, 8004)
    assert am == [("merge", 9, "a")] and pm["gate"] is None, ci_state
    pm, am = dr.step(lane_ci, gate_facts(ci_state), {**dset, "auto_merge": False}, 8004)
    assert pm["stage"] == "awaiting_merge" and ("merge", 9, "a") not in am, ci_state
pw, aw = dr.step({**lane, "ci_fixed": "a"}, gate_facts("failure"), {**dset, "ci": "wait"}, 8005)
assert pw["held"] == "CI is red"  # defer -> wait at the gate: held as today
for ci_state in ("failure", "pending"):
    pi, ai = dr.step(lane, gate_facts(ci_state), {**dset, "ci": "ignore"}, 8006)
    assert ai == [("merge", 9, "a")] and not pi.get("held"), ci_state
    pi, ai = dr.step(lane, gate_facts(ci_state), {"ci": "ignore", "grind": "off"}, 8006)
    assert pi["stage"] == "awaiting_merge" and ("merge", 9, "a") not in ai, ci_state
# ignore merging with CI not green leaves a warning event; green leaves none
for ci_state, warn in [("failure", "merged with red CI"), ("pending", "merged with CI pending"), ("success", None)]:
    di = dr.create("o/r#95", "headless", {"grind": "off", "auto_merge": True, "ci": "ignore"}, [child(96)])
    di["lanes"][K(96)].update(stage="merge_gate", handle={"n": 96}, pr=196)
    evs = dr.tick(di, {K(96): {"issue_open": True, "agent": "idle", "solo": True, "pr": pr(196, ci=ci_state)}},
                  FakeRunner(), merge, now=1)  # fmt: skip
    assert [e["text"] for e in evs if e["kind"] == "warning"] == ([warn] if warn else []), (ci_state, evs)
print("  ok  merge gate follows the ci mode")

# --- skip_approval: no approving review needed on a team repo; every other gate still applies
sa = {"ci": "wait", "grind": "off", "auto_merge": True, "skip_approval": True}
team = lambda **kv: {"agent": "idle", "solo": False, "slack": True, "pr": pr(9, **kv)}  # noqa: E731
assert dr._gate({}, team(), sa, 0) is None
assert dr._gate({}, team(), {**sa, "skip_approval": False}, 0) == "no approving review"
assert dr._gate({}, team(), {k: v for k, v in sa.items() if k != "skip_approval"}, 0) == "no approving review"
assert dr._gate({}, team(changes_requested=True), sa, 0) == "changes requested"
assert dr._gate({}, team(threads_open=1), sa, 0) == "unresolved review threads"
assert dr._gate({}, team(draft=True), sa, 0) == "PR is a draft"
assert dr._gate({}, team(conflict=True), sa, 0) == "PR has a merge conflict"
assert dr._gate({}, team(ci="pending"), sa, 0) == "CI is not green"
assert dr._gate({}, team(ci="pending"), {**sa, "ci": "defer"}, 0) == "waiting for green CI (defer)"
assert dr._gate({}, team(ci="none"), sa, 0) == "CI not registered yet"
gr = {**team(), "grind": {"state": "running", "reason": ""}}
assert dr._gate({}, gr, {**sa, "grind": "simple"}, 0) == "grind is not done"
gd = {**team(), "grind": {"state": "done", "reason": "approved (simple)"}}
assert dr._gate({}, gd, {**sa, "grind": "simple"}, 0) is None
ps, as_ = dr.step({"n": 9, "stage": "merge_gate"}, team(), sa, 0)
assert as_ == [("merge", 9, "a" * 40)] and ps["gate"] is None, (ps, as_)
ps, as_ = dr.step({"n": 9, "stage": "merge_gate", "hold_merge": True}, team(), sa, 0)
assert not any(a[0] == "merge" for a in as_), as_
ps, as_ = dr.step({"n": 9, "stage": "merge_gate"}, team(), {**sa, "auto_merge": False}, 0)
assert ps["stage"] == "awaiting_merge" and not any(a[0] == "merge" for a in as_), (ps, as_)
assert dr.check_settings({**dr.DEFAULTS, "skip_approval": 1})["skip_approval"] is True
assert dr.check_settings({**dr.DEFAULTS})["skip_approval"] is False
print("  ok  skip_approval drops only the approval")

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
assert run2.started[0][1].startswith("/blubird:implement-issue 7 (base branch feature/x")
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
assert run2.sent[-1][1] == dr.followups_prompt(7, 107, "feature/x") and "Close #" not in run2.sent[-1][1]
dr.tick(d2, {K(7): {**f7, "issue_open": False}}, run2, merge, now=6)
assert d2["state"] == "done"
print("  ok  awaiting merge, merge now, done")

# --- QA adds a child: done dispatch pauses
dr.sync_lanes(d2, [child(7), child(8)])
assert d2["state"] == "paused" and d2["lanes"][K(8)]["stage"] == "queued"
assert [e["kind"] for e in d2["events"]].count("paused") == 1
dr.sync_lanes(d2, [child(8, [7]), child(7)])
dr.sync_lanes(d2, [child(8), child(7)])  # #7 closed: the epic no longer lists it as a blocker
assert d2["lanes"][K(8)]["deps"] == [K(7)]
print("  ok  new children pause, deps kept")

# --- unrefined child joins a done dispatch: paused, tick keeps it; refine, resume, lane starts
d4 = dr.create("o/r#30", "headless", {"grind": "off"}, [child(30)])
d4.update(state="done", ended_at=1)
d4["lanes"][K(30)]["stage"] = "closed"
dr.sync_lanes(d4, [child(30), {**child(31), "refined": False}])
assert d4["state"] == "paused" and d4["ended_at"] is None and d4["lanes"][K(31)]["stage"] == "skipped"
run4 = FakeRunner()
dr.tick(d4, {}, run4, merge, now=1)
assert d4["state"] == "paused" and not run4.started
dr.sync_lanes(d4, [child(30), child(31)])
assert d4["lanes"][K(31)]["stage"] == "queued" and d4["state"] == "paused"
d4["state"] = "running"
dr.tick(d4, fq(31), run4, merge, now=2)
assert d4["lanes"][K(31)]["stage"] == "implementing" and run4.started[-1][0] == 31
# a done dispatch stuck with a refined-later lane pauses; a cancelled one stays cancelled
d5 = dr.create("o/r#40", "headless", {}, [{**child(40), "refined": False}])
d5["state"] = "done"
dr.sync_lanes(d5, [child(40)])
assert d5["state"] == "paused" and d5["lanes"][K(40)]["stage"] == "queued"
d6 = dr.create("o/r#50", "headless", {}, [child(50)])
d6["state"] = "cancelled"
dr.sync_lanes(d6, [child(50), child(51)])
assert d6["state"] == "cancelled"
print("  ok  paused on new issues, resume starts lane")

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
# a retry while implementing with a PR open continues that PR instead of re-running implement-issue
d3["lanes"][K(20)].update(stage="implementing", needs_you="stopped without a ready PR")
dr.save(d3)
dr.lane_action(d3["id"], K(20), "retry")
d3 = dr.load(d3["id"])
assert d3["lanes"][K(20)]["stage"] == "implementing"
dr.tick(d3, {K(20): {"agent": "idle", "pr": pr(120, draft=True)}}, run3, merge, now=302)
assert run3.started[-1] == (
    20,
    "/blubird:implement-issue 20 (PR #120 is already open for it: continue that PR on its branch, don't start over)",
)
# a retry of red CI sends the fix to the lane's session, and the stale idle facts don't re-flag it that tick
d3["lanes"][K(20)].update(held="CI is red")
dr.save(d3)
dr.lane_action(d3["id"], K(20), "retry")
d3 = dr.load(d3["id"])
dr.tick(d3, {K(20): {"agent": "idle", "pr": pr(120, ci="failure")}}, run3, merge, now=303)
assert run3.sent[-1][1] == dr.ci_fix_prompt(120) and d3["lanes"][K(20)]["held"] is None
d3["lanes"][K(20)].update(stage="grinding")
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
assert dr.grind_prompt("u", None, lane=False, reviewer="bob") == "/ai-workflow:pr-grind u --reviewer bob"
assert dr.grind_prompt("u", "C1", lane=False, reviewer="bob") == "/ai-workflow:pr-grind u --channel C1"
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
dr.set_settings(d3["id"], ci="defer")
assert dr.load(d3["id"])["settings"]["ci"] == "defer"
old = dr.load(d3["id"])
del old["settings"]["ci"], old["settings"]["skip_approval"]
with open(dr._path(d3["id"]), "w") as f:  # a record saved before ci and skip_approval existed
    json.dump(old, f)
assert dr.load(d3["id"])["settings"]["ci"] == "wait"
assert dr.load(d3["id"])["settings"]["skip_approval"] is False
dr.set_settings(d3["id"], skip_approval=True)
assert dr.load(d3["id"])["settings"]["skip_approval"] is True
dr.set_settings(d3["id"], skip_approval=False)
dr.set_settings(d3["id"], max=3)
dr.set_settings(d3["id"], account="work")
assert dr.load(d3["id"])["settings"]["account"] == "work"
for ok in (None, "work"):
    assert dr.check_settings({**dr.DEFAULTS, "account": ok})["account"] == ok
for bad in ("", 5, "x" * 41):
    try:
        dr.check_settings({**dr.DEFAULTS, "account": bad})
        raise AssertionError(f"accepted account {bad!r}")
    except ValueError:
        pass
for ok in ("gpt-5-codex", "o3:high", "openai/gpt-5.1", "a" * 80, "opus", "opus[1m]", "claude-sonnet-4-5"):
    assert dr.check_settings({**dr.DEFAULTS, "model": ok})["model"] == ok
for bad in ("", "a" * 81, "gpt 5", "-x", ";rm"):
    try:
        dr.check_settings({**dr.DEFAULTS, "model": bad})
        raise AssertionError(f"accepted model {bad!r}")
    except ValueError as e:
        assert str(e) == "model is not a model name"
for ok in (None, 5, 0.5, 10000):
    assert dr.check_settings({**dr.DEFAULTS, "max_cost": ok})["max_cost"] == ok
for bad in (0, -1, "5", True, 10001, float("nan")):
    try:
        dr.check_settings({**dr.DEFAULTS, "max_cost": bad})
        raise AssertionError(f"accepted max_cost {bad!r}")
    except ValueError:
        pass
dp = dr.set_state(d3["id"], "paused")
assert dr.startable(dp, {}) == []
assert dr.list_all()[0]["id"] == d5["id"] and d3["id"] in [x["id"] for x in dr.list_all()]
try:
    dr.load("../etc")
    raise AssertionError("bad id loaded")
except ValueError:
    pass
print("  ok  live edit, pause, store")

# --- Cancel closes every active lane's session, paused ones too, and starts nothing
dx = dr.create("o/r#9", "headless", {}, [child(80), child(81), child(82), child(83)])
L = dx["lanes"]
L[K(80)].update(stage="implementing", handle={"n": 80})
L[K(81)].update(stage="grinding", handle={"n": 81}, paused=True)
L[K(82)].update(stage="closed", handle={"n": 82})
dr.save(dx)
dx = dr.set_state(dx["id"], "cancelled")
dx = dr.set_state(dx["id"], "cancelled")  # twice: still one close
L = dx["lanes"]
assert L[K(80)]["outbox"] == [["close", None]] and L[K(81)]["outbox"] == [["close", None]]
assert "outbox" not in L[K(82)] and "outbox" not in L[K(83)] and L[K(81)]["stage"] == "grinding"
assert dx["events"][-1]["text"] == "dispatch cancelled"
fr = FakeRunner()
dr.tick(dx, {K(83): {"blockers_open": []}}, fr, merge, now=1000)
assert sorted(fr.closed) == [80, 81] and fr.started == [] and L[K(80)]["handle"] is None
print("  ok  cancel closes sessions")

# --- Pause > Now stops the running lanes; Resume gives them a fresh session
dn = dr.create("o/r#9", "headless", {}, [child(70), child(71), child(72), child(73), child(74)])
L = dn["lanes"]
L[K(70)].update(stage="implementing", handle={"n": 70}, needs_you="waiting on you", limited_until=9e9)
L[K(71)].update(stage="followups", pr=9)  # no session: nothing to close
L[K(72)].update(stage="grinding", handle={"n": 72}, paused=True)  # the user's own pause
L[K(74)].update(stage="closed", handle={"n": 74})
dr.save(dn)
plain = dr.set_state(dn["id"], "paused")  # the plain pause touches no lane
assert all(not x.get("paused_by") and not x.get("outbox") for x in plain["lanes"].values())
assert plain["events"][-1]["text"] == "dispatch paused"
dr.set_state(dn["id"], "running")
dn = dr.set_state(dn["id"], "paused", now=True)
L = dn["lanes"]
assert dn["state"] == "paused" and dn["events"][-1]["text"] == "dispatch paused now: 2 issues stopped"
assert L[K(70)]["paused"] and L[K(70)]["paused_by"] == "dispatch" and L[K(70)]["outbox"] == [["close", None]]
assert not L[K(70)]["needs_you"] and not L[K(70)]["limited_until"]  # those were about the session it just lost
assert L[K(71)]["paused_by"] == "dispatch" and "outbox" not in L[K(71)]
for n in (72, 73, 74):
    assert not L[K(n)].get("paused_by") and "outbox" not in L[K(n)], n
fr = FakeRunner()
dr.tick(dn, {K(70): {"pr": None}, K(73): {"blockers_open": []}}, fr, merge, now=1000)
assert fr.closed == [70] and fr.started == [] and L[K(70)]["handle"] is None  # not driven, nothing starts
dr.save(dn)
dn = dr.set_state(dn["id"], "running")
L = dn["lanes"]
assert dn["events"][-1]["text"] == "dispatch running: 2 issues restarted"
assert L[K(70)]["restart"] and not L[K(70)]["paused"] and L[K(70)]["paused_by"] is None
assert L[K(72)]["paused"] and "restart" not in L[K(72)]  # still the user's
fr = FakeRunner()
dr.tick(dn, {}, fr, merge, now=1001)
assert [n for n, _ in fr.started] == [70, 71] and L[K(70)]["handle"] == {"n": 70}

# a lane action on a stopped lane leaves no stale paused_by for the dispatch's Resume to act on
for action, restart in (("resume", True), ("skip", None)):
    dx = dr.create(f"o/r#{10 + bool(restart)}", "headless", {}, [child(80)])
    dx["lanes"][K(80)].update(stage="implementing", handle={"n": 80})
    dr.save(dx)
    dr.set_state(dx["id"], "paused", now=True)
    x = dr.lane_action(dx["id"], K(80), action)["lanes"][K(80)]
    assert not x.get("paused_by") and x.get("restart") is restart, (action, x)
    assert "restart" not in dr.set_state(dx["id"], "running")["lanes"][K(80)] or restart
print("  ok  pause now, resume restarts")

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
assert h == {"tab": "t1", "pane": "p1", "agent": "aiw-abc-issue-5", "cwd": co}
assert calls[0] == ["tab", "create", "--workspace", "w1", "--cwd", co, "--label", "issue-5", "--no-focus"]
assert calls[1][-4:] == ["--", "--dangerously-skip-permissions", "--model", "opus"]
assert calls[2] == ["agent", "prompt", "aiw-abc-issue-5", "/ai-workflow:implement-issue 5"]
# repo skills win: every send is resolved against the lane's checkout
os.makedirs(os.path.join(co, ".claude", "skills", "verifier-locally"))
open(os.path.join(co, ".claude", "skills", "verifier-locally", "SKILL.md"), "w").close()
hd.send(h, dr.qa_prompt("o/r#1", None))  # a /blubird: command is never shadowed by a repo copy
assert "run /blubird:verifier-locally " in calls[-1][3] and "/blubird:create-tasks" in calls[-1][3]
os.makedirs(os.path.join(co, ".claude", "skills", "pr-grind"))
open(os.path.join(co, ".claude", "skills", "pr-grind", "SKILL.md"), "w").close()
hd.send(h, dr.grind_prompt("u", lane=False))  # an ai-workflow one is
assert calls[-1][3] == "/pr-grind u"
hd.send(h, "/ai-workflow:implement-issue 5")
assert calls[-1][3] == "/ai-workflow:implement-issue 5"  # no copy of that one
hd.send({**h, "cwd": None}, dr.grind_prompt("u", lane=False))  # a handle from before `cwd` was kept
assert calls[-1][3] == "/ai-workflow:pr-grind u"
shutil.rmtree(os.path.join(co, ".claude"))
hd.send(h, dr.grind_prompt("u", lane=False))
assert calls[-1][3] == "/ai-workflow:pr-grind u"
hd.send(h, "x" * 470 + " /verifier-locally")  # resolved before the 480-character cut
assert calls[-1][3] == ("x" * 470 + " /ai-workflow:verifier-locally")[:480]
assert hd.status(h) == ("working", None)  # idle but waiting on its own monitors
assert hd.status({"tab": "gone"}) == ("gone", None)
hd.close(h)
assert calls[-1] == ["tab", "close", "t1"]
# a tab that is already gone closes quietly; one that fails to close while it exists raises
tabs_now = []


def cli_close(argv, timeout=60):
    out = json.dumps({"result": {"tabs": [{"tab_id": t} for t in tabs_now]}}) if argv[:2] == ["tab", "list"] else ""
    return subprocess.CompletedProcess(argv, 1 if argv[:2] == ["tab", "close"] else 0, out, "no such tab")


hc = dispatch_runners.Herdr("w1", cli_close)
hc.close({"tab": "t9"})
tabs_now.append("t9")
try:
    hc.close({"tab": "t9"})
    raise AssertionError("close of a live tab that failed")
except RuntimeError:
    pass


# herdr-app: hc run makes the tab with the first prompt as claude's argument; status/close by terminal
happ, app_calls, live = [], [], {"t7": {"state": "live", "status": "blocked"}}


def hc_cli(argv, timeout=60):
    happ.append(argv)
    out, code = "", 0
    if argv[0] == "run":
        out = json.dumps({"address": "t7", "state": "live"})
    elif argv[0] == "get":
        t = live.get(argv[-1])
        out, code = (json.dumps(t), 0) if t else ("", 1)
    elif argv[0] == "read":
        out = "all done"
    elif argv[0] == "kill":
        code = 1 if argv[-1] in live else 0
    return subprocess.CompletedProcess(argv, code, out, "")


ha = dispatch_runners.HerdrApp("sp1", hc_cli, lambda argv, timeout=30: app_calls.append(argv))
h = ha.start({"repo": R, "n": 5}, "/ai-workflow:implement-issue 5", {"id": "abc", "settings": {"model": "opus"}})
assert h["terminal"] == "t7" and h["cwd"] == co and h["tab"].startswith("tb")
assert happ[0][:6] == ["run", "--bg", "--json", "--no-parent", "--keep", "--cwd"]
assert "herdr.space=sp1" in happ[0] and f"herdr.tab={h['tab']}" in happ[0]
assert happ[0][-5:] == ["claude", "--dangerously-skip-permissions", "--model", "opus", "/ai-workflow:implement-issue 5"]
assert app_calls == [["do", "tab.rename", "--id", h["tab"], "--name", "issue-5"]]
ha.send(h, "go on")
assert happ[-1] == ["send", "--json", "t7", "go on"]
assert ha.status(h) == ("blocked", None)
live["t7"]["status"] = "idle"
assert ha.status(h) == ("idle", None)
assert ha.status({"terminal": "t9"}) == ("gone", None)
try:
    ha.close(h)  # kill failed while it is still live
    raise AssertionError("close of a live terminal that failed")
except RuntimeError:
    pass
del live["t7"]
ha.close(h)  # already gone: quiet
assert dispatch_runners.for_dispatch({"runner": "herdr-app", "workspace": "sp1"}).space == "sp1"
print("  ok  herdr-app runner")


class FakeSessions:
    recs = {
        "s1": {"status": "waiting"},
        "s2": {"status": "failed"},
        "s3": {"status": "done", "hold": True},
        "s4": {"status": "stopped", "hold": True},
        "s5": {"status": "done"},
    }

    def load(self, sid):
        return self.recs.get(sid)

    def update(self, sid, **kw):
        self.recs[sid].update(kw)


hl = dispatch_runners.Headless(runner=object(), sessions=FakeSessions())
assert hl.status({"session": "s1"}) == ("blocked", None) and hl.status({"session": "s2"})[0] == "gone"
assert hl.status({"session": "nope"})[0] == "gone"


class SendRunner:
    sent = []

    def send_prompt(self, sid, text):
        self.sent.append((sid, text))


hs = dispatch_runners.Headless(runner=SendRunner(), sessions=FakeSessions())
assert hs.status({"session": "s3"}) == ("working", None)  # held: no needs_you, the lane stays
hs.send({"session": "s3"}, "first")
hs.send({"session": "s3"}, "newer")
assert FakeSessions.recs["s3"]["queued_prompt"] == "newer" and SendRunner.sent == []
assert hs.status({"session": "s4"}) == ("idle", None)  # stopped stays final, held or not
hs.send({"session": "s4"}, "go")
assert "queued_prompt" not in FakeSessions.recs["s4"] and SendRunner.sent == [("s4", "go")]
assert hs.status({"session": "s5"}) == ("idle", None)
hs.send({"session": "s5"}, "go")
assert SendRunner.sent[-1] == ("s5", "go")


class StopRunner:
    stopped = []

    def stop(self, sid):
        self.stopped.append(sid)
        if sid == "nope":
            raise FileNotFoundError(sid)


hc = dispatch_runners.Headless(runner=StopRunner(), sessions=FakeSessions())
hc.close({"session": "s1"})
hc.close({"session": "nope"})  # a record that is gone is not a failed close
assert StopRunner.stopped == ["s1", "nope"]


class KwRunner:
    def start(self, *a, **kw):
        self.kw = kw
        return {"id": "s9"}


class FakeSettings:
    @staticmethod
    def load():
        return {"commands": [{"label": "work", "cmd": "cc-profile work"}]}


for acc, want in (("work", "cc-profile work"), ("gone", None), (None, None)):
    kr = KwRunner()
    dispatch_runners.Headless(runner=kr, sessions=FakeSessions(), settings=FakeSettings).start(
        {"repo": "o/r"}, "p", {"settings": {"account": acc}}
    )
    assert kr.kw["claude_cmd"] == want, (acc, kr.kw)
# headless on a Codex account: its command, model and effort go to the runner, no Claude flag added
kr = KwRunner()
FakeSettings.load = staticmethod(lambda: {"commands": [{"label": "cx", "cmd": "codex"}]})
dispatch_runners.Headless(runner=kr, sessions=FakeSessions(), settings=FakeSettings).start(
    {"repo": "o/r"}, "p", {"settings": {"account": "cx", "model": "gpt-5-codex", "effort": "high"}}
)
assert kr.kw == {
    "direct_effort": "high",
    "model": "gpt-5-codex",
    "claude_cmd": "codex",
    "gate_questions": True,
}, kr.kw
print("  ok  runners")

# --- herdr on a Codex account (FR-13): --kind codex, the command's words, Codex flags, a short skill pointer
import ui_settings  # noqa: E402


class CodexSettings:
    HARNESSES = ui_settings.HARNESSES
    ACC = [
        {"label": "claude", "cmd": "claude", "harness": "claude"},
        {"label": "work", "cmd": "cc-profile work", "harness": "claude"},
        {"label": "cx", "cmd": "codex", "harness": "codex", "models": ["gpt-5-codex"]},
        {"label": "cxp", "cmd": "codex --profile x", "harness": "codex", "models": []},
        {"label": "cc", "cmd": "cc-codex x", "harness": "codex", "models": []},
    ]
    default = "claude"

    @classmethod
    def load(cls):
        return {"commands": cls.ACC, "default": cls.default}

    @classmethod
    def default_cmd(cls):
        return next(c["cmd"] for c in cls.ACC if c["label"] == cls.default)

    @classmethod
    def harness_of(cls, cmd):
        return next((c["harness"] for c in cls.ACC if c["cmd"] == cmd), "claude")

    @classmethod
    def models_of(cls, cmd):
        return next((c.get("models") or [] for c in cls.ACC if c["cmd"] == cmd and c["harness"] == "codex"), [])

    missing = set()  # commands whose first word is "not on PATH"

    @classmethod
    def argv(cls, cmd):
        if cmd in cls.missing:
            raise ValueError(f"{cmd.split()[0]!r} not found on PATH")
        return shlex.split(cmd)


def herdr_start(account, model=None, effort=None, prompt="/ai-workflow:implement-issue 5"):
    del calls[:]
    hx = dispatch_runners.Herdr("w1", cli, settings=CodexSettings)
    d = {"id": "abc", "settings": {"account": account, "model": model, "effort": effort}}
    return hx, hx.start({"repo": R, "n": 5}, prompt, d)


CODEX_HEAD = ["agent", "start", "aiw-abc-issue-5", "--kind", "codex", "--pane", "p1", "--timeout", "120000", "--"]
hx, h = herdr_start("cx", "gpt-5-codex", "high")
assert h == {"tab": "t1", "pane": "p1", "agent": "aiw-abc-issue-5", "cwd": co, "kind": "codex"}
assert calls[1] == [
    *CODEX_HEAD,
    "--dangerously-bypass-approvals-and-sandbox",
    "--model=gpt-5-codex",
    "-c",
    "model_reasoning_effort=high",
], calls[1]
first = calls[2][3]
assert len(calls) == 3 and len(first) <= 480 and first.startswith("Read the skill file "), first
assert os.path.join("skills", "implement-issue", "SKILL.md") in first and first.endswith("ARGUMENTS: 5")
hx.send(h, dr.conflict_prompt(7, "master"))
assert calls[-1][3] == dr.conflict_prompt(7, "master")  # not a skill command: sent as today
for model, effort in (("opus", "max"), ("default", None), (None, "default"), ("gpt-x", "low")):
    _, _ = herdr_start("cx", model, effort)
    want = ["-c", "model_reasoning_effort=low"] if effort == "low" else []
    assert calls[1] == [*CODEX_HEAD, "--dangerously-bypass-approvals-and-sandbox", *want], (model, effort, calls[1])
_, h = herdr_start("cxp", "gpt-5-codex", "medium")  # a model saved on another account is left out
assert calls[1] == [
    *CODEX_HEAD,
    "--profile",
    "x",
    "--dangerously-bypass-approvals-and-sandbox",
    "-c",
    "model_reasoning_effort=medium",
], calls[1]
# the repo copy wins in the pointer
os.makedirs(os.path.join(co, ".claude", "skills", "implement-issue"))
open(os.path.join(co, ".claude", "skills", "implement-issue", "SKILL.md"), "w").close()
hx.send(h, "/ai-workflow:implement-issue 5")
assert calls[-1][3].startswith(f"Read the skill file {co}/.claude/skills/implement-issue/SKILL.md "), calls[-1][3]
shutil.rmtree(os.path.join(co, ".claude"))
# the longest lane prompts fit herdr's send with a 120-character plugin path
real_dir = dispatch_runners.repo_skills._SKILLS_DIR
root = tempfile.mkdtemp()
dispatch_runners.repo_skills._SKILLS_DIR = os.path.join(root + "/" + "p" * (119 - len(root)), "skills")
assert len(os.path.dirname(dispatch_runners.repo_skills._SKILLS_DIR)) == 120
for nm in ("implement-issue", "pr-grind"):
    os.makedirs(os.path.join(dispatch_runners.repo_skills._SKILLS_DIR, nm))
    open(os.path.join(dispatch_runners.repo_skills._SKILLS_DIR, nm, "SKILL.md"), "w").close()
pr_url = "https://github.com/masnun-siam/ai-workflow/pull/12345"
out = dispatch_runners.repo_skills.codex_pointer(dr.grind_prompt(pr_url, "C0123456789AB", ci="defer"), None)
assert out.startswith("Read the skill file ") and len(out) < 480, (len(out), out)
# a /blubird: command passes through unchanged (inlining it for Codex is #969), still under the cut
text = dr.implement_prompt(12345, "staging", pr=67890, ci="defer")
assert dispatch_runners.repo_skills.codex_pointer(text, None) == text and len(text) < 480, text
dispatch_runners.repo_skills._SKILLS_DIR = real_dir
# a Codex command herdr cannot start is refused before any herdr call
for acc in ("cc",):
    del calls[:]
    try:
        herdr_start(acc)
        raise AssertionError("started cc-codex on herdr")
    except ValueError as e:
        assert str(e) == dispatch_runners.HERDR_CODEX_REFUSAL and calls == [], (e, calls)
for bad in ("cc-codex x", "npx codex", "/usr/bin/codex", "codex 'x", ""):
    try:
        dispatch_runners.herdr_codex_words(bad)
        raise AssertionError(bad)
    except ValueError as e:
        assert str(e) == dispatch_runners.HERDR_CODEX_REFUSAL
assert dispatch_runners.herdr_codex_words("codex --profile 'my work'") == ["--profile", "my work"]
# Claude accounts, default or not, start today's argv and handle whatever the account
for acc in (None, "claude", "work", "gone"):
    _, h = herdr_start(acc, "opus", None)
    assert h == {"tab": "t1", "pane": "p1", "agent": "aiw-abc-issue-5", "cwd": co}, h
    assert calls[1][3:5] == ["--kind", "claude"] and calls[1][-4:] == [
        "--",
        "--dangerously-skip-permissions",
        "--model",
        "opus",
    ]
    assert calls[2] == ["agent", "prompt", "aiw-abc-issue-5", "/ai-workflow:implement-issue 5"]
# a Settings default of Codex makes an unset account a Codex lane
CodexSettings.default = "cx"
_, h = herdr_start(None)
assert h.get("kind") == "codex" and calls[1][3:5] == ["--kind", "codex"]
CodexSettings.default = "claude"
# a limited herdr Codex lane shows as stalled, never limited; a Claude lane with the same pane is limited
lim_text = "x\n5-hour limit reached ∙ resets 3pm"


def cli_lim(argv, timeout=60):
    if argv[:2] == ["pane", "read"]:
        return subprocess.CompletedProcess(argv, 0, lim_text, "")
    return cli(argv, timeout)


hl = dispatch_runners.Herdr("w1", cli_lim, settings=CodexSettings)
assert hl.status({"tab": "t1", "pane": "p1", "kind": "codex"}) == ("idle", None)
assert hl.status({"tab": "t1", "pane": "p1"})[1] is not None
print("  ok  herdr codex lanes")


# herdr-app on a Codex account: the account's own command, the Codex flags, the inlined skill prompt
def app_start(account, model=None, effort=None, prompt="/ai-workflow:implement-issue 5"):
    del happ[:]
    live["t7"] = {"state": "live", "status": "idle"}
    ha = dispatch_runners.HerdrApp("sp1", hc_cli, lambda argv, timeout=30: None, settings=CodexSettings)
    d = {"id": "abc", "settings": {"account": account, "model": model, "effort": effort}}
    return ha, ha.start({"repo": R, "n": 5}, prompt, d)


def after_dashes(argv):
    return argv[argv.index("--") + 1 :]


ha, h = app_start("cx", "gpt-5-codex", "high")
assert h["kind"] == "codex" and h["terminal"] == "t7" and h["cwd"] == co
tail = after_dashes(happ[0])
assert tail[:-1] == [
    "codex",
    "--dangerously-bypass-approvals-and-sandbox",
    "--model=gpt-5-codex",
    "-c",
    "model_reasoning_effort=high",
], tail
assert tail[-1].startswith("Base directory for this skill: ") and tail[-1].endswith("ARGUMENTS: 5"), tail[-1][:80]
ha.send(h, "/ai-workflow:implement-issue 5")
assert happ[-1][:3] == ["send", "--json", "t7"] and happ[-1][3].startswith("Base directory for this skill: ")
ha.send(h, dr.conflict_prompt(7, "master"))
assert happ[-1] == ["send", "--json", "t7", dr.conflict_prompt(7, "master")]  # not a skill command: as today
_, h = app_start("cc", "gpt-5-codex", "max")  # cc-codex starts on herdr-app; unsaved model and max left out
assert h["kind"] == "codex" and after_dashes(happ[0])[:-1] == [
    "cc-codex",
    "x",
    "--dangerously-bypass-approvals-and-sandbox",
], happ[0]
_, h = app_start("cxp", None, "default")
assert after_dashes(happ[0])[:-1] == ["codex", "--profile", "x", "--dangerously-bypass-approvals-and-sandbox"]
CodexSettings.missing = {"codex"}
try:
    app_start("cx")
    raise AssertionError("started a codex not on PATH")
except ValueError as e:
    assert "not found on PATH" in str(e) and happ == [], (e, happ)
CodexSettings.missing = set()
# Claude accounts, default or not: today's argv and handle exactly
for acc in (None, "claude", "work", "gone"):
    _, h = app_start(acc, "opus", "high")
    assert "kind" not in h and set(h) == {"terminal", "tab", "cwd"}, h
    assert after_dashes(happ[0]) == [
        "claude",
        "--dangerously-skip-permissions",
        "--model",
        "opus",
        "--effort",
        "high",
        "/ai-workflow:implement-issue 5",
    ], happ[0]
# a limited herdr-app Codex lane shows as stalled; a Claude handle with the same text is limited
_real_read, dispatch_runners.HerdrApp.read = dispatch_runners.HerdrApp.read, lambda self, h: lim_text
assert ha.status({"terminal": "t7", "kind": "codex"}) == ("idle", None)
assert ha.status({"terminal": "t7"})[1] is not None
dispatch_runners.HerdrApp.read = _real_read
print("  ok  herdr-app codex lanes")

# base_branch: lane_base order, lane prompts, followups tail, Open PR target
assert dr.lane_base({"base": "L"}, {"feature_branch": "F", "base_branch": "B"}) == "F"
assert dr.lane_base({"base": "L"}, {"base_branch": "B"}) == "B"
assert dr.lane_base({"base": "L"}, {}) == "L" and dr.lane_base({}, {}) is None
db = dr.create("o/r#60", "headless", {"grind": "off", "base_branch": "release/1.4"}, [child(61)])
runb = FakeRunner()
dr.tick(db, fq(61), runb, merge, now=1)
assert "base branch release/1.4: branch from it, open the PR into it" in runb.started[0][1]
assert "Merge origin/release/1.4" in dr.stage_prompt({"n": 61, "stage": "conflict_fix", "pr": 5}, db["settings"])
assert dr.stage_prompt({"n": 61, "stage": "followups", "pr": 5}, db["settings"]) == dr.followups_prompt(61, 5, "x")
# followups: the after-merge command plus the pinned section sentence, no Close tail
assert dr.followups_prompt(5, 9, "staging") == (
    "/blubird:implement-issue 5 (PR #9 for issue #5 is merged: "
    "run the 'After the pull request is merged' section, not the implement steps)"
)
# the registry drives the prompts: implement-issue and after-merge change independently
import skill_registry  # noqa: E402

_reg_real = skill_registry.REGISTRY_PATH
with open(_reg_real) as f:
    _reg = json.load(f)
_tmpreg = os.path.join(tempfile.mkdtemp(), "reg.json")


def _with_reg(steps):
    with open(_tmpreg, "w") as f:
        json.dump({"steps": steps}, f)
    skill_registry.REGISTRY_PATH = _tmpreg


try:
    _with_reg({**_reg["steps"], "implement-issue": {**_reg["steps"]["implement-issue"], "plugin": "ai-workflow"}})
    assert dr.implement_prompt(5, None) == "/ai-workflow:implement-issue 5"
    assert dr.followups_prompt(5, 9, None).startswith("/blubird:implement-issue 5 (")
    _with_reg({**_reg["steps"], "after-merge": {**_reg["steps"]["after-merge"], "plugin": "ai-workflow"}})
    assert dr.implement_prompt(5, None) == "/blubird:implement-issue 5"
    assert dr.followups_prompt(5, 9, None).startswith("/ai-workflow:implement-issue 5 (")
    _with_reg({k: v for k, v in _reg["steps"].items() if k != "after-merge"})
    try:
        dr.followups_prompt(5, 9, None)
        raise AssertionError("a registry without after-merge must not build a prompt")
    except ValueError:
        pass
finally:
    skill_registry.REGISTRY_PATH = _reg_real
assert len(dr.followups_prompt(99999, 99999, "x")) < 480
db2 = dr.create(
    "o/r#62", "headless", {"grind": "off", "feature_branch": "feat/x", "base_branch": "staging"}, [child(63)]
)
runb2 = FakeRunner()
dr.tick(db2, fq(63), runb2, merge, now=1)
assert "feat/x" in runb2.started[0][1] and "staging" not in runb2.started[0][1]
dn = dr.create("o/r#64", "headless", {"grind": "off"}, [child(65)])
runn = FakeRunner()
dr.tick(dn, fq(65), runn, merge, now=1)
assert "base branch" not in runn.started[0][1]
assert "Close #" not in dr.followups_prompt(65, 5, None)
d6 = dr.create("o/r#70", "headless", {"feature_branch": "feature/x", "base_branch": "staging"}, [child(71)])
dr.request_end(d6["id"], "open-pr")
d6 = dr.load(d6["id"])
del gh_calls[:]
dr.tick(d6, {}, FakeRunner(), merge, now=1, gh=fake_gh)
assert gh_calls[0][:8] == ["pr", "create", "-R", "o/r", "--base", "staging", "--head", "feature/x"]
assert not any(c[:2] == ["repo", "view"] for c in gh_calls)
# a retry after a failure on the second repo creates only that PR and reports both
d7 = dr.create("o/r#80", "headless", {"feature_branch": "feature/x"}, [child(81), child(82)])
dr.request_end(d7["id"], "open-pr")
d7 = dr.load(d7["id"])
d7["lanes"][K(82)]["repo"] = "o/s"
fail_once = [True]


def gh_fail_s(argv):
    if argv[:2] == ["pr", "create"] and argv[3] == "o/s" and fail_once:
        fail_once.pop()
        return subprocess.CompletedProcess(argv, 1, "", "boom")
    return fake_gh(argv)


del gh_calls[:]
dr.tick(d7, {}, FakeRunner(), merge, now=1, gh=gh_fail_s)
assert list(d7["final_prs"]) == ["o/r"] and d7["lanes"][K(82)]["repo"] == "o/s"
d7.setdefault("end_requests", []).append("open-pr")
del gh_calls[:]
dr.tick(d7, {}, FakeRunner(), merge, now=2, gh=gh_fail_s)
creates = [c[3] for c in gh_calls if c[:2] == ["pr", "create"]]
assert creates == ["o/s"] and sorted(d7["final_prs"]) == ["o/r", "o/s"]
# an unreachable runner is no news: a followups lane is not closed
fl = {"n": 9, "repo": "o/r", "stage": "followups", "pr": 5}
fp, fa = dr.step(fl, {"issue_open": False, "agent": "unknown", "pr": pr(5, state="MERGED")}, {"grind": "off"}, 1)
assert fp.get("stage", "followups") == "followups" and ("close",) not in fa
print("  ok  base_branch lanes and open-pr")

# --- epic dispatches honour lane ownership (#714)
shutil.rmtree(dr._dir())
e1 = real_create("o/r#900", "headless", {}, [child(901), child(902)])
n_before = len(dr.list_all())
try:
    real_create("o/r#900", "headless", {}, [child(902), child(903)])
    raise AssertionError("second epic dispatch over an owned child should conflict")
except dr.Conflict as exc:
    assert exc.id == e1["id"] and K(902) in str(exc), exc
assert len(dr.list_all()) == n_before
try:
    real_create(None, "headless", {}, [child(901)], issues=[K(901)])
    raise AssertionError("issue-list dispatch over an epic lane should conflict")
except dr.Conflict as exc:
    assert exc.id == e1["id"]
e1["state"] = "cancelled"
dr.save(e1)
e2 = real_create("o/r#900", "headless", {}, [child(901), child(902)])
assert e2["id"] != e1["id"]
try:
    real_create("o/r#910", "headless", {}, [child(901)])
    raise AssertionError("epic dispatch over an issue-list/epic lane should conflict")
except dr.Conflict:
    pass
print("  ok  epic ownership")
# --- archive_old: finished and old moves; recent, running and malformed stay
import time  # noqa: E402

for old in dr.list_all():  # start clean: park earlier dispatches out of the way
    old["state"], old["ended_at"] = "done", time.time()
    dr.save(old)
now = time.time()
mk = lambda n, st, ago: dict(  # noqa: E731
    real_create(None, "headless", {}, [child(n)], issues=[K(n)]), state=st, ended_at=now - ago * 86400
)
old_done, recent, running = mk(951, "done", 31), mk(952, "done", 29), mk(953, "running", 40)
for d in (old_done, recent, running):
    dr.save(d)
    open(dr._path(d["id"])[:-5] + ".lock", "w").close()
bad = os.path.join(dr._dir(), "0" * 12 + ".json")
with open(bad, "w") as f:
    f.write("{not json")
before = {d["id"] for d in dr.list_all()}
moved = dr.archive_old(now=now)
assert old_done["id"] in moved and recent["id"] not in moved and running["id"] not in moved and "0" * 12 not in moved, (
    moved
)
assert os.path.exists(os.path.join(dr._dir(), "archive", old_done["id"] + ".json"))
assert os.path.exists(dr._path(old_done["id"])[:-5] + ".lock") and os.path.exists(bad)
assert old_done["id"] not in {d["id"] for d in dr.list_all()}
assert {recent["id"], running["id"]} <= {d["id"] for d in dr.list_all()}
assert dr.archive_old(now=now) == [] and before - set(moved) == {d["id"] for d in dr.list_all()}
assert recent["id"] in dr.archive_old(now=now, days=28)
print("  ok  archive_old")

# --- retry_failed: start-failed, needs_you and held lanes retry; user-skipped, closed and healthy stay
d = strand_d(*[child(n) for n in range(1, 8)])
L = d["lanes"]
L[K(1)].update(stage="skipped", skip_reason="start failed: boom")
L[K(2)].update(stage="implementing", needs_you="the lane session is gone", handle="h")
L[K(3)].update(stage="grinding", pr=3, held="CI is red")
L[K(4)].update(stage="skipped", skip_reason="skipped by you")
L[K(5)].update(stage="skipped", skip_reason="needs refine")
L[K(6)].update(stage="closed")
dr.save(d)
n_events = len(d["events"])
assert sorted(dr.retry_failed(d["id"])) == sorted([K(1), K(2), K(3)])
d = dr.load(d["id"])
L = d["lanes"]
assert L[K(1)]["stage"] == "queued" and L[K(2)]["needs_you"] is None and L[K(3)]["held"] is None
assert [L[K(n)]["stage"] for n in (4, 5, 6, 7)] == ["skipped", "skipped", "closed", "queued"]
assert L[K(4)]["skip_reason"] == "skipped by you"
assert [e["lane"] for e in d["events"][n_events:] if e["kind"] == "lane" and e["text"] == "retry"] == [K(1), K(2), K(3)]
assert dr.retry_failed(d["id"]) == []
print("  ok  retry_failed")
print("dispatch_run: all green")
