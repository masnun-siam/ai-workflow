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
import ui_notify  # noqa: E402
import ui_sessions  # noqa: E402

pushed = []
ui_notify.notify = lambda event, rec: pushed.append((event, rec))
macs = []
ui_dispatch.mac_notify = lambda title, text: macs.append((title, text))
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
        **kv,
    }


def snap(issues=(), merged=(), open_prs=(), stale=False):
    return {
        "stale": stale,
        "fetched_at": 1.0,
        "data": {"issues": list(issues), "merged": list(merged), "open_prs": list(open_prs), "closed_epics": []},
    }


no_channel = lambda repo: None  # noqa: E731

# --- lane_facts: stale -> None; open issue, blockers, PR approval via reviewer, grind header, agent
lane = {"repo": R, "n": 5, "handle": {"t": 1}}
assert ui_dispatch.lane_facts(lane, snap(stale=True)) is None
assert ui_dispatch.lane_facts(lane, None) is None
s = snap(
    [issue(5, blockers=[(4, "OPEN"), (3, "CLOSED")], prs=[pr(50)])],
    open_prs=[{**pr(50), "reviewer": "bot", "checks": 3}],
)
grind_files = [("x", {"owner": "O", "repo": "R", "number": "50", "dispatch-due": "2026-10-23T00:00:00Z"})]
f = ui_dispatch.lane_facts(lane, s, status=lambda h: ("blocked", None), grind_files=grind_files, channel=lambda r: "C1")
assert f["issue_open"] and f["refined"] and f["blockers_open"] == ["o/r#4"]
assert f["pr"]["n"] == 50 and f["pr"]["approved"] is True and (f["slack"], f["channel"]) == (True, "C1")
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
assert "agent" not in f
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
snaps[R] = snap([issue(5, prs=[pr(50, review="approved")]), issue(6, blockers=[(5, "OPEN")])])
for t in (1002, 1003):
    ui_dispatch.tick_one(d["id"], lambda r: snaps.get(r), runner_for=lambda d: runner, now=t, grind_files=[])
d = dr.load(d["id"])
assert d["lanes"]["o/r#5"]["stage"] == "awaiting_merge"
assert macs and "ready to merge" in macs[-1][1] and pushed[-1][0] == "dispatch"
items = ui_dispatch.inbox_items([d])
row = next(i for i in items if i["lane"] == "o/r#5")
assert row["group"] == "decide" and row["type"] == "dispatch_lane" and row["pr"] == 50
print("  ok  tick_one")

# --- not busy: cancelled dispatches are left alone
dr.set_state(d["id"], "cancelled")
assert ui_dispatch.tick_one(d["id"], lambda r: snaps.get(r), runner_for=lambda d: 1 / 0) == []
print("  ok  cancelled is idle")

# --- usage and public
rec = ui_sessions.create("/ai-workflow:implement-issue 5", R)
ui_sessions.update(rec["id"], cost=1.25, tokens={"input": 100, "cached": 0, "output": 20})
x = {"handles": [{"session": rec["id"]}, {"tab": "t"}], "started_at": 10, "ended_at": 70}
assert ui_dispatch._usage(x) == {"cost": 1.25, "tokens": 120, "seconds": 60}
p = ui_dispatch.public(dr.load(d["id"]), full=True)
assert p["lanes"][0]["key"] == "o/r#5" and "events" in p and "handle" not in p["lanes"][0]
print("  ok  usage, public")

# --- mac_notify passes the text as argv, never as script
real = ui_dispatch.__dict__.get("mac_notify")
import importlib  # noqa: E402

fresh = importlib.reload(ui_dispatch)
calls = []
fresh.mac_notify("t", 'x" & do shell script "rm', run=lambda argv, **k: calls.append(argv))
if sys.platform == "darwin":
    assert calls[0][-2] == 'x" & do shell script "rm' and "rm" not in " ".join(calls[0][:-2])
ui_dispatch = fresh
ui_dispatch.mac_notify = lambda title, text: macs.append((title, text))
print("  ok  mac notify")

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
assert call(f"/api/dispatches/{d2['id']}/lane", {"lane": "o/r#9", "action": "hold"})[1]["lanes"][0]["hold_merge"]
assert call(f"/api/dispatches/{d2['id']}/lane", {"lane": "o/r#9", "action": "explode"})[0] == 400
assert call(f"/api/dispatches/{d2['id']}/state", {"state": "paused"})[1]["state"] == "paused"
assert call(f"/api/dispatches/{d2['id']}/end", {"action": "open-pr"})[0] == 400  # no feature branch
assert call(f"/api/dispatches/{d2['id']}/lane?key=o/r%239")[0] == 400  # no session yet
d2 = dr.load(d2["id"])
d2["lanes"]["o/r#9"]["held"] = "CI is red"
dr.save(d2)
st, body = call("/api/inbox")
row = next(i for i in body["items"] if i["type"] == "dispatch_lane")
assert st == 200 and row["group"] == "fix" and row["reason"] == "CI is red"
srv.shutdown()
print("  ok  api")
print("ui_dispatch: all green")
