"""Tests for ui_dispatch: plain asserts, run with `python3 test_ui_dispatch.py`."""
import os
import sys
import tempfile
import time

os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ui_dispatch as d  # noqa: E402
import ui_notify  # noqa: E402
import ui_repos  # noqa: E402

n_ok = 0


def ok(label):
    global n_ok
    n_ok += 1
    print(f"  ok  {label}")


def raises(fn, *a):
    try:
        fn(*a)
    except ValueError:
        return True
    return False


def pipe(items, mode="parallel", cap=2, status="active"):
    return {"id": "p-20260101000000-abcdef", "name": "t", "slug": "o/r", "repo_path": "/x", "mode": mode,
            "max": cap, "claude_cmd": None, "status": status, "created": 1.0, "notified": False,
            "items": [{"issue": n, "title": "", "deps": deps, "ext_deps": [], "state": "queued",
                       "session_id": None, "reason": None} for n, deps in items]}


# --- parse_input
assert d.parse_input("https://github.com/o/r/issues?q=is%3Aissue+is%3Aopen+label%3Abug+sort%3Acreated-asc") == ("o/r", "query", "label:bug")
ok("search URL drops is:/sort: tokens and keeps the repo")
assert d.parse_input('https://github.com/o/r/issues?q=label%3A%22good+first+issue%22')[2] == 'label:"good first issue"'
ok("quoted label survives")
assert d.parse_input("#12, 14 15 12") == (None, "issues", [12, 14, 15])
ok("number list: # prefixes, commas/whitespace, dedupe")
assert d.parse_input("https://github.com/o/r/issues/3\nhttps://github.com/o/r/issues/4") == ("o/r", "issues", [3, 4])
ok("issue URLs")
assert raises(d.parse_input, "") and raises(d.parse_input, "https://github.com/o/r/issues") \
    and raises(d.parse_input, "https://github.com/o/r/issues/1 https://github.com/o/x/issues/2") and raises(d.parse_input, "12 abc")
ok("empty / no-query / mixed repos / junk rejected")

# --- advance: cap, order, dependency gate
p = pipe([(1, []), (2, []), (3, [1]), (4, [])], cap=2)
launch, fin = d.advance(p, {})
assert launch == [1, 2] and not fin
ok("parallel launches up to the cap in dependency order")
for n in (1, 2):
    p["items"][n - 1].update(state="running", session_id=f"s{n}")
launch, _ = d.advance(p, {1: ("running", None), 2: ("running", None)})
assert launch == []
ok("full cap launches nothing")
launch, _ = d.advance(p, {1: ("done", "done"), 2: ("running", None)})
assert launch == [3] and p["items"][0]["state"] == "done"
ok("dependent starts only once its dependency is done; freed slot is reused")

p = pipe([(1, []), (2, []), (3, [])], mode="sequential", cap=5)
assert d.advance(p, {})[0] == [1]
ok("sequential caps at one regardless of max")

p = pipe([(1, []), (2, [1])])
p["items"][0].update(state="running", session_id="s1")
launch, _ = d.advance(p, {1: ("waiting", None)})
assert launch == [] and p["items"][0]["state"] == "waiting"
ok("a gate-waiting issue keeps its slot and blocks dependents")

# --- failure / skip closure / recovery / finish
p = pipe([(1, []), (2, [1]), (3, [2]), (4, [])])
p["items"][0].update(state="running", session_id="s1")
launch, _ = d.advance(p, {1: ("done", "escalated")})
st = {i["issue"]: i["state"] for i in p["items"]}
assert st == {1: "failed", 2: "skipped", 3: "skipped", 4: "queued"} and launch == [4]
ok("escalated ledger = failed; dependents skipped transitively; independents run")
p["items"][0].update(state="stopped")
p["items"][0]["state"] = "running"
d.advance(p, {1: ("running", None)})
assert [i["state"] for i in p["items"]][1:3] == ["queued", "queued"]
ok("blocked items re-queue when the blocker recovers")
p["items"][1].update(state="skipped", reason="manual")
d.advance(p, {1: ("running", None)})
assert p["items"][1]["state"] == "skipped"
ok("manual skip sticks")

p = pipe([(1, []), (2, [])])
for it in p["items"]:
    it.update(state="running", session_id="s")
_, fin = d.advance(p, {1: ("done", "done"), 2: ("failed", None)})
assert fin and p["status"] == "done"
_, fin = d.advance(p, {1: ("done", "done"), 2: ("failed", None)})
assert not fin
ok("pipeline finishes exactly once")
p["items"][1]["state"] = "queued"
d.advance(p, {})
assert p["status"] == "active" and p["notified"] is False
ok("a retried item reopens a finished pipeline")

p = pipe([(1, [])], status="paused")
assert d.advance(p, {})[0] == []
ok("paused pipeline launches nothing")
assert raises(d.order_of, pipe([(1, [2]), (2, [1])])["items"])
ok("dependency cycle rejected")

# --- store + launch + controls (gh and sessions stubbed)
calls = []
sessions = {}


def fake_start(body):
    calls.append(body)
    if body["issue"] == 9:
        return 409, {"error": "dup", "id": "live-9"}
    if body["issue"] == 8:
        return 400, {"error": "claude_cmd must be a label saved in Settings"}
    return 201, {"id": f"sess-{body['issue']}"}


d.ui_repos.start_session = fake_start
d.ui_repos.resolve_repo = lambda r: ("/tmp/x", "o/r")
d.ui_repos.is_unregistered_slug = lambda r: False
d._screen = lambda slug, nums: [{"issue": n, "title": f"T{n}", "deps": {2: [1]}.get(n, [])} for n in nums]
d.ui_sessions.load = lambda sid: sessions.get(sid)
ledgers = {}  # issue -> ledger status; absent = the run never created a ledger
d.ui_board.load_run = lambda o, r, n: ({"status": ledgers[int(n)]} if int(n) in ledgers else None)
ledgers.update({1: "done", 2: "done", 3: "done"})
d.ui_runner.stop = lambda sid: sessions[sid].update(status="stopped")
notes = []
ui_notify.notify = lambda ev, rec: notes.append((ev, rec))
d.ui_notify = ui_notify

created = d.create({"repo": "o/r", "issues": [1, 2, 3, 9, 8], "mode": "parallel", "max": 2})
by = {i["issue"]: i for i in created["items"]}
assert by[1]["session_id"] == "sess-1" and by[3]["session_id"] == "sess-3" and by[2]["state"] == "queued"
assert all(c["command"] == "run-issue" and c["args"] == str(c["issue"]) for c in calls)
ok("create persists and launches the first wave through start_session")
assert d.load(created["id"])["items"][0]["title"] == "T1"
ok("pipeline round-trips through disk")

for sid in ("sess-1", "sess-3"):
    sessions[sid] = {"status": "running"}
d.tick(created["id"])
sessions["sess-1"]["status"] = "done"
d.tick(created["id"])
by = {i["issue"]: i for i in d.load(created["id"])["items"]}
assert by[1]["state"] == "done"
ok("tick observes finished sessions")
ledgers.pop(1)  # a session that exited cleanly without a ledger (stopped at preflight) is a failure
d.tick(created["id"])
by = {i["issue"]: i for i in d.load(created["id"])["items"]}
assert by[1]["state"] == "failed" and by[1]["reason"] == "run did not start", by[1]
ledgers[1] = "done"
d.tick(created["id"])
assert d.load(created["id"])["items"][0]["state"] == "done"
ok("done session without a completed ledger is failed, recovers when the ledger completes")

sessions["sess-3"]["status"] = "done"
sessions["sess-2"] = {"status": "running"}
sessions["live-9"] = {"status": "running"}
d.tick(created["id"])
d.tick(created["id"])
by = {i["issue"]: i for i in d.load(created["id"])["items"]}
assert by[8]["state"] == "failed" and "could not start" in by[8]["reason"]
ok("a refused launch fails that item only")
assert by[9]["session_id"] == "live-9" and by[9]["reason"] == "adopted"
ok("409 adopts the live session")

out = d.act(created["id"], "pause")
assert out["status"] == "paused"
out = d.act(created["id"], "update", {"max": 4, "mode": "sequential"})
assert out["max"] == 4 and out["mode"] == "sequential"
ok("pause + live max/mode edit")
assert raises(d.act, created["id"], "update", {"max": 0})
ok("bad max rejected")

# --- review / auto_grind edits: stored on the pipeline, applied to live runs, per-item result
ep = pipe([(201, []), (202, [])])
ep["id"] = "p-20260101000009-aaaaaa"
ep["items"][0].update(state="running", session_id="s-1")
d.save(ep)
_calls = []
_real_apply = d.ui_options.apply
d.ui_options.apply = lambda o, r, i, b, session_id=None: _calls.append((i, b, session_id)) or {"review": "too_late"}
out = d.act(ep["id"], "update", {"review": False, "auto_grind": False})
assert out["review"] is False and out["auto_grind"] is False, out
assert _calls == [(201, {"review": False, "auto_grind": False}, "s-1")], _calls
assert out["applied"] == {201: {"review": "too_late"}}, out
_calls.clear()
out = d.act(ep["id"], "update", {"review": True})
assert out["review"] is True and not _calls, (out, _calls)  # turning review back on only reaches queued items
assert raises(d.act, ep["id"], "update", {"review": "no"})
assert raises(d.act, ep["id"], "update", {"auto_grind": 1})
d.ui_options.apply = _real_apply
os.unlink(d._path(ep["id"]))  # a live pipeline would leak into the checks below
notes.clear()
ok("update review/auto_grind: stored, applied to live runs with a per-item result, non-bool rejected")
_real = d._screen
d._screen = lambda slug, nums: [{"issue": n, "error": "Could not resolve to an Issue"} for n in nums]
assert raises(d.act, created["id"], "update", {"add": [404]}) and raises(d.create, {"repo": "o/r", "issues": [404]})
d._screen = lambda slug, nums: [{"issue": n, "closed": True, "title": "x"} for n in nums]
assert raises(d.act, created["id"], "update", {"add": [405]})
d._screen = _real
ok("unresolvable or closed issues are refused on create and add")
out = d.act(created["id"], "update", {"add": [7]})
assert [i["issue"] for i in out["items"]][-1] == 7
ok("add issues to a live pipeline")

try:
    d.delete(created["id"])
    assert False
except d.Conflict:
    pass
ok("cannot delete while sessions are live")
out = d.act(created["id"], "stop")
assert out["status"] == "stopped" and all(i["state"] != "running" for i in out["items"])
ok("stop pipeline stops every live session")
try:
    d.act(created["id"], "skip", issue=1)
    assert False
except d.Conflict:
    pass
out = d.act(created["id"], "skip", issue=7)
assert {i["issue"]: i for i in out["items"]}[7]["state"] == "skipped"
ok("skip: refused on a finished issue, works on a queued one")
d.delete(created["id"])
assert d.load(created["id"]) is None
ok("delete removes the pipeline file")

p2 = d.create({"repo": "o/r", "issues": [5]})
ledgers[5] = "done"
sessions["sess-5"] = {"status": "done"}
d.tick(p2["id"])
assert d.load(p2["id"])["status"] == "done" and [e for e, _ in notes] == ["pipeline"]
d.tick(p2["id"])
assert len(notes) == 1
ok("finish notifies once")
assert d.membership() == {} and d.summary(d.load(p2["id"]))["counts"] == {"done": 1}
ok("finished pipelines drop out of board membership; summary counts")

# unknown repo -> NeedsCheckout carrying the clones found on disk
d.ui_repos.is_unregistered_slug = lambda r: r == "acme/new"
d.ui_repos.find_clones = lambda roots, slug=None, **k: [{"slug": slug, "path": "/home/me/new"}]
for call in (lambda: d.preview("#1", "acme/new"), lambda: d.preview("https://github.com/acme/new/issues?q=label%3Aready", None),
             lambda: d.create({"repo": "acme/new", "issues": [1]})):
    try:
        call()
        raise AssertionError("expected NeedsCheckout")
    except d.NeedsCheckout as e:
        assert e.slug == "acme/new" and e.candidates == ["/home/me/new"] and "no local clone registered" in str(e)
ok("an unregistered repo asks for a clone (preview by number, preview by URL, create) with candidates")

print(f"\n{n_ok} passed")


# an issue transferred to another repo: the run's Ledger lives under the new number and links back
tp = d.create({"repo": "o/r", "issues": [77, 78]})
ledgers.pop(77, None)
moved_run = {"status": "done", "pr": "https://github.com/o/new/pull/9", "stations": [], "totals": {}, "branch": "b", "currentStation": None}
d.ui_board.transferred_run = lambda slug, n: ("o", "new", 12) if (slug, n) == ("o/r", 77) else None
real_load_run = d.ui_board.load_run
d.ui_board.load_run = lambda o, r, n: moved_run if (o, r, n) == ("o", "new", "12") else real_load_run(o, r, n)
sessions[d.load(tp["id"])["items"][0]["session_id"]] = {"status": "done"}
d.tick(tp["id"])
it0 = d.load(tp["id"])["items"][0]
assert it0["state"] == "done" and it0["moved_to"] == {"owner": "o", "repo": "new", "issue": 12}, it0
_pp = d.load(tp['id']); _pp['status'] = 'active'; d.save(_pp)  # membership only lists unfinished pipelines
assert d.membership().get("o/new#12") == tp["id"]
assert d.detail(tp["id"])["items"][0]["run"]["pr"].endswith("/o/new/pull/9")
d.ui_board.load_run = real_load_run
print("ok  transferred issue: item follows its run to the new repo and number")

# --- main tree: sequential only
assert raises(d.create, {"repo": "o/r", "issues": [90], "mode": "parallel", "worktree": False})
assert raises(d.create, {"repo": "o/r", "issues": [90], "mode": "sequential", "worktree": "no"})
mt = d.create({"repo": "o/r", "issues": [90, 91], "mode": "sequential", "worktree": False})
assert mt["worktree"] is False
assert calls[-1]["issue"] == 90 and calls[-1]["worktree"] is False
assert d.create({"repo": "o/r", "issues": [92]})["worktree"] is True
assert d.detail(mt["id"])["worktree"] is False
print("ok  main-tree pipeline must be sequential; the flag reaches each launched session")
assert raises(d.create, {"repo": "o/r", "issues": [93], "review": "no"})
nr = d.create({"repo": "o/r", "issues": [94], "review": False})
assert nr["review"] is False and calls[-1]["review"] is False
assert d.create({"repo": "o/r", "issues": [95]})["review"] is True
print("ok  review flag is stored on the pipeline and reaches each launched session")
assert raises(d.act, mt["id"], "update", {"mode": "parallel"})
assert d.load(mt["id"])["mode"] == "sequential"
print("ok  a main-tree pipeline cannot switch to parallel")
