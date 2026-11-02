#!/usr/bin/env python3
"""Self-check for run-engine/ui_dispatch.py and the dispatch API. `python3 test_ui_dispatch.py` — exit 0 = green."""

from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
data = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = data
import dispatch_run as dr  # noqa: E402
import ui_dispatch  # noqa: E402
import ui_gh  # noqa: E402
import ui_notify  # noqa: E402
import ui_sessions  # noqa: E402
import ui_settings  # noqa: E402

pushed = []
ui_notify.notify = lambda event, rec: pushed.append((event, rec))
ui_gh.status = lambda *a, **k: {"ok": True, "login": "someone-else", "error": None}
macs = []
ui_notify.send_mac = lambda title, text, *a, **k: macs.append((title, text))
R = "o/r"


def issue(n, labels=("refined",), blockers=(), prs=()):
    return {
        "n": n,
        "title": f"i{n}",
        "state": "OPEN",
        "labels": list(labels),
        "priority": None,
        "parent": 1,
        "sub_issues": [],
        "blocked_by": [{"n": b, "state": s} for b, s in blockers],
        "prs": list(prs),
    }


def pr(n, **kv):
    return {
        "n": n,
        "url": f"https://github.com/o/r/pull/{n}",
        "draft": False,
        "state": "OPEN",
        "merged_at": None,
        "head": f"issue-{n}",
        "ci": "success",
        "review": "none",
        "conflict": False,
        "sha": "c" * 40,
        **kv,
    }


def snap(issues=(), merged=(), open_prs=(), stale=False, truncated=False):
    return {
        "stale": stale,
        "fetched_at": 1.0,
        "data": {
            "issues": list(issues),
            "merged": list(merged),
            "open_prs": list(open_prs),
            "closed_epics": [],
            "issues_truncated": truncated,
        },
    }


no_channel = lambda repo: None  # noqa: E731

# --- a truncated open-issue list lacking the lane's issue: the lane waits; a complete one: the issue is closed
t_lane = {"repo": R, "n": 777, "handle": {"t": 1}}
assert ui_dispatch.lane_facts(t_lane, snap(truncated=True), channel=no_channel) is None
assert ui_dispatch.lane_facts(t_lane, snap(), channel=no_channel)["issue_open"] is False

# --- lane_facts: stale -> None; open issue, blockers, PR approval via reviewer, grind header, agent
lane = {"repo": R, "n": 5, "handle": {"t": 1}}
assert ui_dispatch.lane_facts(lane, snap(stale=True)) is None
assert ui_dispatch.lane_facts(lane, None) is None
s = snap(
    [issue(5, blockers=[(4, "OPEN"), (3, "CLOSED")], prs=[pr(50)])],
    open_prs=[{**pr(50), "reviewer": "bot", "approved": True, "changes_requested": False, "checks": 3}],
)
grind_files = [("x", {"owner": "O", "repo": "R", "number": "50", "dispatch-due": "2026-10-23T00:00:00Z"})]
f = ui_dispatch.lane_facts(lane, s, status=lambda h: ("blocked", None), grind_files=grind_files, channel=lambda r: "C1")
assert f["issue_open"] and f["refined"] and f["blockers_open"] == ["o/r#4"]
assert (
    f["pr"]["n"] == 50
    and f["pr"]["approved"] is True
    and f["pr"]["changes_requested"] is False
    and (f["slack"], f["channel"]) == (True, "C1")
)
assert f["grind"] == {"state": "idle", "reason": "", "due": "2026-10-23T00:00:00Z"} and f["agent"] == "blocked"
f = ui_dispatch.lane_facts(
    lane,
    s,
    grind_files=[("x", {"owner": "o", "repo": "r", "number": "50", "done": "t — approved"})],
    channel=no_channel,
)
assert f["grind"]["state"] == "done" and f["slack"] is False and "agent" not in f
# closed issue: the merged list names its PR
f = ui_dispatch.lane_facts(
    lane,
    snap(merged=[{"n": 50, "title": "", "url": "u", "merged_at": "t", "head": "h", "closes": [5], "epic": 1}]),
    grind_files=[],
    channel=no_channel,
)
assert f["issue_open"] is False and f["pr"]["state"] == "MERGED"
# a runner that cannot be reached reads as no news
f = ui_dispatch.lane_facts(lane, s, status=lambda h: 1 / 0, grind_files=[], channel=no_channel)
assert f["agent"] == "unknown" and f["limited_until"] is None
# a merged PR from before the lane started is an earlier run of a reissued issue
old = pr(40, state="MERGED", merged_at="2026-11-01T00:00:00Z")
started = 1793000000.0  # 2026-10-28 < merged_at
for started_at, has_pr in ((started + 10**7, False), (started, True), (None, True)):
    ln = {"repo": R, "n": 5, **({"started_at": started_at} if started_at else {})}
    f = ui_dispatch.lane_facts(ln, snap([issue(5, prs=[old])]), grind_files=[], channel=no_channel)
    assert ("pr" in f) is has_pr and (not has_pr or f["pr"]["state"] == "MERGED"), started_at
# closed issue: the merged list is filtered the same way
m = {"n": 50, "title": "", "url": "u", "merged_at": "2026-11-01T00:00:00Z", "head": "h", "closes": [5], "epic": 1}
ln = {"repo": R, "n": 5, "started_at": started + 10**7}
assert "pr" not in ui_dispatch.lane_facts(ln, snap(merged=[m]), grind_files=[], channel=no_channel)
print("  ok  lane_facts")


# --- tick_one: launches on fresh facts, syncs the epic, notifies, skips stale repos
class FakeRunner:
    def __init__(self):
        self.started, self.sent = [], []

    def start(self, x, prompt, d):
        self.started.append((x["n"], prompt))
        return {"session": f"s{x['n']}"}

    def send(self, h, text):
        self.sent.append((h, text))

    def status(self, h):
        return "working", None

    def close(self, h):
        pass

    def read(self, h):
        return "pane text"


runner = FakeRunner()
d = dr.create(
    "o/r#1",
    "headless",
    {"max": 2, "grind": "off"},
    [{"repo": R, "n": 5, "refined": True}, {"repo": R, "n": 6, "refined": True, "deps": ["o/r#5"]}],
)
children = [
    {"repo": R, "n": 5, "refined": True},
    {"repo": R, "n": 6, "refined": True, "deps": ["o/r#5"]},
    {"repo": R, "n": 7, "refined": False},
]
snaps = {R: snap([issue(5), issue(6, blockers=[(5, "OPEN")]), issue(7, labels=())])}
ui_dispatch.tick_one(
    d["id"],
    lambda r: snaps.get(r),
    runner_for=lambda d: runner,
    resolve=lambda e: {"children": children},
    now=1000,
    grind_files=[],
)
d = dr.load(d["id"])
assert [n for n, _ in runner.started] == [5] and d["lanes"]["o/r#7"]["skip_reason"] == "needs refine"
assert d["synced_at"] == 1000
# stale snapshot: nothing moves
snaps[R] = snap(stale=True)
ui_dispatch.tick_one(
    d["id"], lambda r: snaps.get(r), runner_for=lambda d: runner, resolve=lambda e: 1 / 0, now=1001, grind_files=[]
)
assert dr.load(d["id"])["lanes"]["o/r#5"]["stage"] == "implementing"
# PR ready, grind off, auto-merge off -> awaiting_merge: Inbox row, macOS notice, ntfy push
snaps[R] = snap(
    [issue(5, prs=[pr(50, review="approved")]), issue(6, blockers=[(5, "OPEN")])],
    open_prs=[{**pr(50, review="approved"), "approved": True, "changes_requested": False}],
)
for t in (1002, 1003):
    ui_dispatch.tick_one(d["id"], lambda r: snaps.get(r), runner_for=lambda d: runner, now=t, grind_files=[])
d = dr.load(d["id"])
assert d["lanes"]["o/r#5"]["stage"] == "awaiting_merge"
assert (
    pushed[-1][0] == "dispatch" and "ready to merge" in pushed[-1][1]["note"] and not macs
)  # the fan-out owns the banner
# ignore + red CI merges, and the warning goes out on the dispatch channel
dw = dr.create(
    "o/r#95", "headless", {"grind": "off", "auto_merge": True, "ci": "ignore"}, [{"repo": R, "n": 96, "refined": True}]
)
dw["lanes"]["o/r#96"].update(stage="merge_gate", handle={"n": 96}, pr=196)
facts = {"o/r#96": ui_dispatch.lane_facts(dw["lanes"]["o/r#96"], snap([issue(96, prs=[pr(196, ci="failure")])]))}
facts["o/r#96"]["solo"] = True
dr.tick(dw, facts, runner, merge=lambda repo, n, sha: (True, ""), now=1004, notify=ui_dispatch.notify)
assert pushed[-1][0] == "dispatch" and "merged with red CI" in pushed[-1][1]["note"]
items = ui_dispatch.inbox_items([d])
row = next(i for i in items if i["lane"] == "o/r#5")
assert row["group"] == "decide" and row["type"] == "dispatch_lane" and row["pr"] == 50
print("  ok  tick_one")

# --- issue-list dispatch: re-read of the listed issues only, no epic anywhere
dl = dr.create(None, "headless", {"grind": "off"}, [{"repo": R, "n": 31, "refined": False}], issues=["o/r#31"])
rl = FakeRunner()
kids = [{"repo": R, "n": 31, "refined": True}, {"repo": R, "n": 99, "refined": True}]
ui_dispatch.tick_one(
    dl["id"],
    lambda r: snap(stale=True),
    runner_for=lambda d: rl,
    resolve=lambda e: 1 / 0,
    resolve_issues=lambda refs: {"children": kids[:1]},
    now=5000,
    grind_files=[],
)
x = dr.load(dl["id"])
assert list(x["lanes"]) == ["o/r#31"] and x["lanes"]["o/r#31"]["stage"] == "queued"
warns = []
ui_dispatch.warn = warns.append
ui_dispatch.tick_one(
    dl["id"],
    lambda r: snap(stale=True),
    runner_for=lambda d: rl,
    resolve=lambda e: 1 / 0,
    resolve_issues=lambda refs: 1 / 0,
    now=9000,
    grind_files=[],
)
assert warns and "epic" not in warns[0] and dr.load(dl["id"])["synced_at"] == 9000
n0 = len(pushed)
ui_dispatch.notify(dl, "o/r#31", "lane", "joined")
ui_dispatch.notify(dl, None, "x", "paused")
assert [p[1]["note"] for p in pushed[n0:]] == ["aiw: o/r#31 joined", f"aiw: {dl['title']} paused"]
assert pushed[-1][1]["repo"] == R and pushed[-1][1]["link"]["issue"] is None
dl["lanes"]["o/r#31"]["needs_you"] = "waiting on you"
assert ui_dispatch.inbox_items([dl])[0]["repo"] == R
dl["state"] = "done"
row = ui_dispatch.inbox_items([dl])[-1]
assert (row["repo"], row["epic"], row["title"], row["feature_branch"]) == (R, None, dl["title"], None)
dl["state"] = "running"
dl["lanes"]["o/r#31"]["stage"] = "queued"
assert R in ui_dispatch.repos()
print("  ok  issue-list dispatch")

# --- not busy: cancelled dispatches are left alone
for x in d["lanes"].values():
    x["handle"] = None  # no session to close
dr.save(d)
dr.set_state(d["id"], "cancelled")
assert ui_dispatch.tick_one(d["id"], lambda r: snaps.get(r), runner_for=lambda d: 1 / 0) == []
print("  ok  cancelled is idle")

# --- cancelled with queued closes: the tick runs them, then it is idle again
dc = dr.create("o/r#9", "headless", {}, [{"repo": "o/r", "n": 9, "refined": True}])
dc["lanes"]["o/r#9"].update(stage="implementing", handle={"session": "s9"})
dr.save(dc)
dr.set_state(dc["id"], "cancelled")
assert ui_dispatch._busy(dr.load(dc["id"]))
rc = FakeRunner()
rc.closed = []
rc.close = rc.closed.append
ui_dispatch.tick_one(dc["id"], lambda r: snaps.get(r), runner_for=lambda d: rc, resolve=lambda e: 1 / 0, grind_files=[])
assert rc.closed == [{"session": "s9"}] and rc.started == []
assert dr.load(dc["id"])["lanes"]["o/r#9"]["handle"] is None
assert not ui_dispatch._busy(dr.load(dc["id"]))
print("  ok  cancel closes sessions")

# --- usage and public
rec = ui_sessions.create("/ai-workflow:implement-issue 5", R)
ui_sessions.update(rec["id"], cost=1.25, tokens={"input": 100, "cached": 0, "output": 20})
x = {"handles": [{"session": rec["id"]}, {"tab": "t"}], "started_at": 10, "ended_at": 70}
assert ui_dispatch._usage(x) == {"cost": 1.25, "tokens": 120, "seconds": 60}
p = ui_dispatch.public(dr.load(d["id"]), full=True)
assert p["lanes"][0]["key"] == "o/r#5" and "events" in p and "handle" not in p["lanes"][0]
assert p["issues"] is None
il = dr.create(None, "headless", {"grind": "off"}, [{"repo": "o/r", "n": 5, "refined": True}], issues=["o/r#5"])
assert ui_dispatch.public(il)["issues"] == ["o/r#5"]
_load = ui_settings.load
ui_settings.load = lambda: {"commands": [{"label": "work", "cmd": "claude"}]}
try:
    assert ui_dispatch._settings({"settings": {"account": "work"}}, "epic")["account"] == "work"
    for call in (
        lambda: ui_dispatch._settings({"settings": {"account": "nope"}}, "epic"),
        lambda: ui_dispatch.set_settings(d["id"], {"account": "nope"}),
    ):
        try:
            call()
            raise AssertionError("unsaved account accepted")
        except ValueError as e:
            assert "saved in Settings" in str(e)
    assert ui_dispatch.set_settings(d["id"], {"account": "work"})["settings"]["account"] == "work"
finally:
    ui_settings.load = _load
print("  ok  usage, public")

# --- the Inbox shows a dispatch's issue once: as its lane
dd = {"state": "running", "lanes": {"o/r#5": {"repo": "O/R", "n": 5, "stage": "merge_gate", "pr": 50}}}
rows = [
    {"type": "pr_ready", "repo": "o/r", "pr": 50, "issue": 5},
    {"type": "session_failed", "repo": "o/r", "link": {"owner": "o", "repo": "r", "issue": 5}},
    {"type": "pr_ready", "repo": "o/r", "pr": 60, "issue": 6},
    {"type": "question", "repo": "o/r", "link": {"issue": 5}},
]
kept = ui_dispatch.drop_owned(rows, [dd])
assert [(r["type"], r.get("pr")) for r in kept] == [("pr_ready", 60), ("question", None)], kept
assert ui_dispatch.drop_owned(rows, [{**dd, "state": "done"}]) == rows
print("  ok  inbox dedupe")

# --- active_lane: grind autostart and pr-grind re-entry leave a lane's PR alone
d2 = dr.create("o/r#2", "headless", {}, [{"repo": R, "n": 9, "refined": True}])
d2["lanes"]["o/r#9"].update(stage="grinding", pr=90)
dr.save(d2)
assert dr.active_lane("O/R", pr=90)[0] == d2["id"] and dr.active_lane(R, n=9)
assert dr.active_lane(R, pr=91) is None
print("  ok  active_lane")

# --- pr-grind re-entry: a due round of a lane's PR is handed to the dispatch, no headless session starts
import ui_runner  # noqa: E402

os.makedirs(os.path.join(data, "pr-grind"), exist_ok=True)
gpath = os.path.join(data, "pr-grind", "o-r-90.md")
with open(gpath, "w") as fh:
    fh.write(
        "owner: o\nrepo: r\nnumber: 90\nthread: https://x.slack.com/archives/C1/p1\n"
        "next-poll: 2000-01-01T00:00:00Z\n\n## Round 1\n"
    )
ui_runner.shared.gh_json = lambda argv: ({"state": "OPEN"}, None)
ui_runner._new_review = lambda h, now: None
ui_runner.ci.snapshot = lambda *a: {"head_sha": "abc", "state": "success"}
started = []
ui_runner.start = lambda *a, **k: started.append(a)
assert ui_runner.prgrind_tick(gpath) == "dispatch" and not started
h = ui_runner._header(gpath)
assert h.get("dispatch-due") and h["next-poll"] > "2000"
assert ui_dispatch._grind(R, 90)["due"] == h["dispatch-due"]
print("  ok  pr-grind hand-off")

# --- API through the server
import ui_gh  # noqa: E402
import ui_server  # noqa: E402

ui_gh.status = lambda *a, **k: {"ok": True, "login": "me", "error": None}
srv = ui_server._Server(("127.0.0.1", 0), ui_server._Handler, ())
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]


def call(path, body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    raw = json.dumps(body).encode() if body is not None else None
    c.request(
        "POST" if body is not None else "GET",
        path,
        body=raw,
        headers={"Host": f"127.0.0.1:{port}", **({"Content-Type": "application/json"} if raw else {})},
    )
    r = c.getresponse()
    out = (r.status, json.loads(r.read() or b"null"))
    c.close()
    return out


st, body = call("/api/dispatches")
assert st == 200 and {x["id"] for x in body["dispatches"]} >= {d["id"], d2["id"]}
st, body = call(f"/api/dispatches/{d2['id']}")
assert st == 200 and body["events"]
assert call("/api/dispatches/000000000000")[0] == 404
st, body = call(f"/api/dispatches/{d2['id']}/settings", {"max": 4, "auto_merge": True})
assert st == 200 and body["settings"]["max"] == 4 and body["settings"]["auto_merge"] is True
assert call(f"/api/dispatches/{d2['id']}/settings", {"bogus": 1})[0] == 400
st, body = call(f"/api/dispatches/{d2['id']}/settings", {"ci": "ignore"})
assert st == 200 and body["settings"]["ci"] == "ignore"
st, body = call(f"/api/dispatches/{d2['id']}/settings", {"ci": "nope"})
assert st == 400 and body["error"] == "ci must be one of ('wait', 'defer', 'ignore')"
seen = []
real_start = ui_dispatch.dispatch_cli.start
ui_dispatch.dispatch_cli.start = lambda epic, runner, s, ws=None: seen.append(s) or d2  # no gh in a self-check
ui_dispatch.start({"epic": "o/r#1", "settings": {"ci": "defer"}})
assert seen[0]["ci"] == "defer"
try:
    ui_dispatch.start({"epic": "o/r#1", "settings": {"ci": "x"}})
    raise AssertionError("accepted ci=x")
except ValueError:
    pass
assert call(f"/api/dispatches/{d2['id']}/lane", {"lane": "o/r#9", "action": "hold"})[1]["lanes"][0]["hold_merge"]
assert call(f"/api/dispatches/{d2['id']}/lane", {"lane": "o/r#9", "action": "explode"})[0] == 400
assert call(f"/api/dispatches/{d2['id']}/state", {"state": "paused"})[1]["state"] == "paused"
stage_ = dr.load(d2["id"])["lanes"]["o/r#9"]["stage"]
dn_ = dr.load(d2["id"])
dn_["lanes"]["o/r#9"]["stage"] = "implementing"
dr.save(dn_)
assert (
    call(f"/api/dispatches/{d2['id']}/state", {"state": "paused", "now": True})[1]["lanes"][0]["paused_by"]
    == "dispatch"
)
dn_ = dr.set_state(d2["id"], "running")
dn_["lanes"]["o/r#9"].update(stage=stage_, restart=None, outbox=None)
dr.save(dn_)
assert call(f"/api/dispatches/{d2['id']}/state", {"state": "paused", "now": "yes"})[1]["lanes"][0]["paused_by"] is None
assert call(f"/api/dispatches/{d2['id']}/end", {"action": "open-pr"})[0] == 400  # no feature branch
assert call(f"/api/dispatches/{d2['id']}/lane?key=o/r%239")[0] == 400  # no session yet
d2 = dr.load(d2["id"])
d2["lanes"]["o/r#9"]["held"] = "CI is red"
dr.save(d2)
st, body = call("/api/inbox")
row = next(i for i in body["items"] if i["type"] == "dispatch_lane")
assert st == 200 and row["group"] == "fix" and row["reason"] == "CI is red"
# issue-list dispatches: plan, start, 400s and the 409 ownership check
ui_dispatch.dispatch_cli.start = real_start


seen_bodies = []


def fake_resolve(refs, gh=None, bodies=False):
    seen_bodies.append(bodies)
    repo, nums = ui_dispatch.dispatch_cli.parse_issues(refs)
    kids = [
        {"repo": repo, "n": n, "title": f"t{n}", "refined": True, "deps": [f"{repo}#412"] if n == 415 else []}
        for n in nums
    ]
    keys = [f"{repo}#{n}" for n in nums]
    return {"epic": None, "issues": keys, "title": dr.issues_title(keys), "children": kids, "outside": {}, "closed": []}


ui_dispatch.dispatch_cli.resolve_issues = fake_resolve
real_branch_sha = ui_dispatch.dispatch_cli.branch_sha
ui_dispatch.dispatch_cli.branch_sha = lambda repo, branch, gh=None: "sha"  # every base exists; no gh in a self-check
st, body = call("/api/dispatches/plan", {"issues": ["o/r#415", "o/r#412"]})
assert st == 200 and body["epic"] is None and body["issues"] == ["o/r#415", "o/r#412"] and body["title"]
assert body["waves"] == [["o/r#412"], ["o/r#415"]], body["waves"]
assert seen_bodies[-1] is True and all("readiness" in ln and ln["readiness"] is None for ln in body["lanes"])
st, body = call("/api/dispatches", {"issues": ["o/r#105", "o/r#105"]})
assert st == 201 and body["epic"] is None and body["issues"] == ["o/r#105"], body
owner = body["id"]
assert call("/api/dispatches/plan", {"issues": ["o/r#106"], "settings": {"base_branch": "hotfix"}})[0] == 200
st, b2 = call("/api/dispatches", {"issues": ["o/r#106"], "settings": {"base_branch": "hotfix"}})
assert st == 201 and b2["settings"]["base_branch"] == "hotfix", b2
st, body = call(f"/api/dispatches/{b2['id']}/settings", {"base_branch": "x"})
assert st == 400 and body["error"] == "base_branch is fixed at start", body
ui_dispatch.dispatch_cli.branch_sha = lambda repo, branch, gh=None: None
nb = {"issues": ["o/r#109"], "settings": {"base_branch": "staging"}}
st, body = call("/api/dispatches/plan", nb)
assert st == 200 and "o/r: base branch staging does not exist" in body["warnings"], body
st, body = call("/api/dispatches", nb)
assert st == 400 and body["error"] == "o/r: base branch staging does not exist", body
ui_dispatch.dispatch_cli.branch_sha = real_branch_sha
for bad in (
    {"epic": "o/r#1", "issues": ["o/r#106"]},
    {},
    {"issues": ["nope"]},
    {"issues": ["a/b#1", "c/d#2"]},
    {"issues": []},
    {"issues": [f"o/r#{i}" for i in range(1, 32)]},
    {"issues": "o/r#106"},
    {"issues": [6]},
    {"issues": ["o/r#106"], "settings": {"feature_branch": "feat"}},
):
    for path in ("/api/dispatches/plan", "/api/dispatches"):
        assert call(path, bad)[0] == 400, (path, bad)
real_resolve = ui_dispatch.dispatch_cli.resolve_issues
ui_dispatch.dispatch_cli.resolve_issues = lambda refs, gh=None, bodies=False: {**fake_resolve(refs), "children": []}
st, body = call("/api/dispatches", {"issues": ["o/r#107"]})
assert st == 400 and body["error"] == "none of the picked issues is open"
ui_dispatch.dispatch_cli.resolve_issues = real_resolve
st, body = call("/api/dispatches", {"issues": ["o/r#105", "o/r#106"]})
assert st == 409 and body["id"] == owner and "o/r#105" in body["error"] and owner in body["error"], body
od = dr.load(owner)
od["state"] = "paused"
dr.save(od)
assert call("/api/dispatches", {"issues": ["o/r#105"]})[0] == 409  # paused still owns its lanes
od["state"] = "cancelled"
dr.save(od)
assert call("/api/dispatches", {"issues": ["o/r#105"]})[0] == 201
results = []
ts = [
    threading.Thread(target=lambda: results.append(call("/api/dispatches", {"issues": ["o/r#108"]})[0]))
    for _ in range(2)
]
[t.start() for t in ts]
[t.join() for t in ts]
assert sorted(results) == [201, 409], results
srv.shutdown()
print("  ok  api")

# the dispatch timer survives a raising tick_all
import time  # noqa: E402

ticks = []


def flaky_tick_all(snapshot, *a, **k):
    ticks.append(1)
    if len(ticks) == 1:
        raise RuntimeError("boom")
    return []


real_tick_all, ui_dispatch.tick_all = ui_dispatch.tick_all, flaky_tick_all
th = ui_dispatch.start_timer(lambda repo: None, 0.01)
deadline = time.time() + 10
while len(ticks) < 2 and time.time() < deadline:
    time.sleep(0.01)
ui_dispatch.tick_all = real_tick_all
assert len(ticks) >= 2 and th.is_alive(), ticks
print("  ok  timer survives a raising tick")
print("ui_dispatch: all green")
