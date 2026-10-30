#!/usr/bin/env python3
"""Self-check for run-engine/ui_bootstrap.py + the repo-bootstrap start hook. `python3 test_ui_bootstrap.py` - exit 0 = green.

Sessions are fakes: ui_runner.start creates a real session record; the test ends a session by writing its stream and status.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import http.client
import tempfile
import threading
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()
os.environ["AIW_NO_MAC_BANNER"] = "1"

import dispatch  # noqa: E402
import ui_bootstrap as B  # noqa: E402
import ui_repos  # noqa: E402
import ui_runner  # noqa: E402
import ui_server  # noqa: E402
import ui_sessions  # noqa: E402

REPO = "acme/shop"
checkout = tempfile.mkdtemp()
subprocess.run(["git", "init", "-q", checkout], check=True)
dispatch.register_checkout(REPO, checkout)
dispatch.register_checkout("local/x", checkout)
starts = []
fail_start = []


def fake_start(cmd, cwd, link=None, **kw):
    if fail_start:
        raise ui_runner.RunnerError("boom")
    sid = ui_sessions.create(cmd, cwd, link, claude_cmd=kw.get("claude_cmd"))["id"]
    ui_sessions.update(sid, status="running", run_model=kw.get("run_model"), run_effort=kw.get("effort"))
    starts.append((sid, cmd, link, kw))
    return ui_sessions.load(sid)


srv = ui_server._Server(("127.0.0.1", 0), ui_server._Handler, ())
threading.Thread(target=srv.serve_forever, daemon=True).start()


def call(method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    c.request(method, path, json.dumps(body) if body is not None else None, {"Content-Type": "application/json"})
    r = c.getresponse()
    out = json.loads(r.read() or b"{}")
    c.close()
    return r.status, out


def set_state(run, state, **kw):
    r = B.load(run["id"])
    r["state"] = state
    r.update(kw)
    B.save(r)


def finish(sid, text="", status="done", **extra):
    if text:
        with open(os.path.join(ui_sessions.session_dir(sid), "stream.jsonl"), "a") as fh:
            fh.write(json.dumps({"type": "result", "is_error": False, "result": text}) + "\n")
    ui_sessions.update(sid, status=status, **extra)


def new_run(phase="audit", issue=None, repo=REPO):
    run = B.create(repo, phase, issue)
    B.attach(run["id"], fake_start(f"/repo-bootstrap {phase}", repo)["id"])
    return B.load(run["id"])


def sid_of(run, name):
    return next(p["session_id"] for p in B.load(run["id"])["phases"] if p["name"] == name)


def states(run):
    return [p["state"] for p in B.load(run["id"])["phases"]]


def line(phase, n=7):
    return f"work done\nBOOTSTRAP: {phase} done #{n}\n"


def end_run(run):  # drop a run out of the open states so the next test can use the repo
    r = B.load(run["id"])
    r["state"] = "ended"
    B.save(r)


with mock.patch.object(ui_runner, "start", fake_start):
    # ---- parse_input
    assert B.parse_input("") == B.parse_input("audit") == B.parse_input("  ") == ("audit", None)
    assert B.parse_input("decide 12") == ("decide", 12) and B.parse_input("docs #3") == ("docs", 3)
    for bad in ("12", "audit 123", "decide", "docs", "nope 4", "decide x", "decide 1 2", "#4"):
        try:
            B.parse_input(bad)
            raise AssertionError(bad)
        except ValueError as e:
            assert "decide, constitution" in str(e)
    print("  ok  parse_input")

    # ---- audit match -> waiting, issue/branch set, nothing started
    run = new_run()
    assert states(run) == ["running"] + ["pending"] * 5 and B.load(run["id"])["state"] == "running"
    assert ui_sessions.load(sid_of(run, "audit"))["bootstrap"] == run["id"]
    n = len(starts)
    B.tick_one(run["id"])
    assert B.load(run["id"])["state"] == "running" and len(starts) == n, "live session: no change"
    finish(sid_of(run, "audit"), line("audit"))
    B.tick_one(run["id"])
    r = B.load(run["id"])
    assert r["state"] == "waiting" and r["issue"] == 7 and r["branch"] == "bootstrap/7" and len(starts) == n
    assert states(run) == ["done"] + ["pending"] * 5
    print("  ok  audit match -> waiting")

    # ---- chain from decide through docs: same account/model/effort, bootstrap set, last -> done
    end_run(run)
    ui_sessions.update(sid_of(run, "audit"), claude_cmd="claude-work", run_model="opus", run_effort="high")
    run = new_run("decide", 7)
    assert states(run)[:2] == ["done", "running"] and B.load(run["id"])["branch"] == "bootstrap/7"
    ui_sessions.update(sid_of(run, "decide"), claude_cmd="claude-work", run_model="opus", run_effort="high")
    for i, ph in enumerate(B.PHASES[1:-1], 1):
        n = len(starts)
        finish(sid_of(run, ph), line(ph))
        B.tick_one(run["id"])
        B.tick_one(run["id"])  # a double end event
        nxt = B.PHASES[i + 1]
        assert len(starts) == n + 1, "one next session"
        _, cmd, link, kw = starts[-1]
        assert cmd == f"/repo-bootstrap {nxt} 7" and link == {"owner": "acme", "repo": "shop", "issue": 7}
        assert kw["gate_questions"] is True and kw["claude_cmd"] == "claude-work"
        assert kw["run_model"] == "opus" and kw["effort"] == "high"
        assert B.load(run["id"])["state"] == "running" and sid_of(run, nxt) == starts[-1][0]
        assert ui_sessions.load(sid_of(run, nxt))["bootstrap"] == run["id"]
        ui_sessions.update(sid_of(run, nxt), claude_cmd="claude-work", run_model="opus", run_effort="high")
    finish(sid_of(run, "docs"), line("docs"))
    B.tick_one(run["id"])
    assert B.load(run["id"])["state"] == "done" and states(run) == ["done"] * 6
    print("  ok  chain decide..docs, same account/model/effort, docs -> done")

    # ---- stops: failed, stopped, no line, wrong phase, wrong issue, malformed
    cases = [
        ("failed", "", "failed", {"error": "crashed"}, "crashed"),
        ("failed", "", "failed", {}, "phase ended without reporting done"),
        ("stopped", "", "stopped", {}, "phase session was stopped"),
        ("done", "no line here", "done", {}, "phase ended without reporting done"),
        ("done", line("guides"), "done", {}, "phase ended without reporting done"),
        ("done", line("decide", 8), "done", {}, "phase ended without reporting done"),
        ("done", "BOOTSTRAP: decide done 7", "done", {}, "phase ended without reporting done"),
        ("done", "BOOTSTRAP: decide done #7\nthanks", "done", {}, "phase ended without reporting done"),
    ]
    for _, text, status, extra, err in cases:
        run = new_run("decide", 7)
        n = len(starts)
        finish(sid_of(run, "decide"), text, status, **extra)
        B.tick_one(run["id"])
        r = B.load(run["id"])
        assert r["state"] == "stopped" and r["error"] == err and len(starts) == n, (text, r)
        assert states(run)[1] == "failed", states(run)
        end_run(run)
    print("  ok  failed / stopped / bad last line -> stopped at the phase")

    # ---- two threads, one start
    run = new_run("decide", 7)
    finish(sid_of(run, "decide"), line("decide"))
    n = len(starts)
    ts = [threading.Thread(target=B.tick_one, args=(run["id"],)) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(starts) == n + 1
    live = [p for p in B.load(run["id"])["phases"] if p["state"] == "running"]
    assert len(live) == 1, "one live phase"
    print("  ok  double end event starts one session")

    # ---- missing session record; restart re-check
    r = B.load(run["id"])
    cur = next(p for p in r["phases"] if p["state"] == "running")
    cur["session_id"] = "20200101T000000000000Z-deadbeef"
    B.save(r)
    B.tick()
    r = B.load(run["id"])
    assert r["state"] == "stopped" and r["error"] == "phase session is gone"
    end_run(run)
    run = new_run("decide", 7)
    finish(sid_of(run, "decide"), line("decide"))  # ended while the UI was down
    n = len(starts)
    B.tick()
    assert len(starts) == n + 1 and states(run)[2] == "running"
    end_run(run)
    # a start that never attached stops after the grace period, not before
    run = B.create(REPO, "decide", 7)
    B.tick_one(run["id"])
    assert B.load(run["id"])["state"] == "running"
    with mock.patch.object(B, "ATTACH_GRACE_SECONDS", -1):
        B.tick_one(run["id"])
    assert B.load(run["id"])["state"] == "stopped"
    end_run(run)
    # a next phase that cannot start stops the run
    run = new_run("decide", 7)
    finish(sid_of(run, "decide"), line("decide"))
    fail_start.append(1)
    B.tick_one(run["id"])
    fail_start.clear()
    r = B.load(run["id"])
    assert r["state"] == "stopped" and "could not start constitution" in r["error"] and states(run)[2] == "failed"
    end_run(run)
    print("  ok  gone session, restart re-check, lost start, failed next start")

    # ---- one open run per repo
    for state in ("running", "waiting", "stopped"):
        run = new_run()
        r = B.load(run["id"])
        r["state"] = state
        B.save(r)
        try:
            B.create(REPO.upper(), "audit", None)
            raise AssertionError(state)
        except B.Conflict as e:
            assert e.id == run["id"] and run["id"] in str(e) and state in str(e) and e.session
        B.create("acme/other", "audit", None)
        end_run(B.load(B.list_all()[0]["id"]))
        end_run(run)
        assert B.create(REPO, "audit", None)  # allowed once ended
        end_run(B.list_all()[0])
    print("  ok  one run per repo (case-insensitive), free after ended")

    # ---- through ui_repos.start_session
    for r in B.list_all():
        end_run(r)
    s, res = ui_repos.start_session({"repo": REPO, "command": "repo-bootstrap", "args": ""})
    assert s == 201, (s, res)
    runs = [r for r in B.list_all() if r["state"] == "running"]
    assert len(runs) == 1 and runs[0]["phases"][0]["session_id"] == res["id"] and res["command"] == "/repo-bootstrap"
    assert ui_sessions.load(res["id"])["bootstrap"] == runs[0]["id"]
    n, total = len(starts), len(B.list_all())
    s, res2 = ui_repos.start_session({"repo": REPO, "text": "/repo-bootstrap"})
    assert s == 409 and res2["bootstrap"] == runs[0]["id"] and res2["id"] == res["id"], (s, res2)
    assert res2["href"] == f"/api/sessions/{res['id']}" and "audit" in res2["error"]
    assert len(starts) == n and len(B.list_all()) == total, "nothing spawned or written"
    end_run(runs[0])
    for bad in ("12", "audit 123", "docs"):
        s, res3 = ui_repos.start_session({"repo": REPO, "command": "repo-bootstrap", "args": bad})
        assert s == 400 and "accepted" in res3["error"], (bad, s, res3)
    s, res3 = ui_repos.start_session({"repo": "local/x", "command": "repo-bootstrap", "args": ""})
    assert s == 400 and "GitHub" in res3["error"], (s, res3)
    total = len(B.list_all())
    fail_start.append(1)
    s, _ = ui_repos.start_session({"repo": REPO, "command": "repo-bootstrap", "args": "decide #5"})
    fail_start.clear()
    assert s == 502 and len(B.list_all()) == total, "a failed start leaves no run"
    s, _ = ui_repos.start_session({"repo": REPO, "command": "repo-bootstrap", "args": "decide #5"})
    assert s == 201 and B.list_all()[0]["issue"] == 5
    print("  ok  start endpoint: run created and linked, 409 body, 400s, discard on failure")

    # ---- continue / retry / stop
    for r in B.list_all():
        end_run(r)
    run = new_run()
    finish(sid_of(run, "audit"), line("audit"))
    B.tick_one(run["id"])
    ui_sessions.update(sid_of(run, "audit"), claude_cmd="claude-work", run_model="opus", run_effort="high")
    n = len(starts)
    try:
        B.retry(run["id"])
        raise AssertionError("retry from waiting")
    except B.Conflict as e:
        assert "waiting" in str(e)
    fail_start.append(1)
    try:
        B.continue_run(run["id"])
        raise AssertionError("failed start")
    except ui_runner.RunnerError:
        pass
    fail_start.clear()
    r = B.load(run["id"])
    assert r["state"] == "waiting" and states(run)[1] == "pending" and len(starts) == n, "failed start: unchanged"
    r = B.continue_run(run["id"])
    assert r["state"] == "running" and r["phases"][1]["state"] == "running" and r["phases"][1]["session_id"]
    _, cmd, _, kw = starts[-1]
    assert cmd == "/repo-bootstrap decide 7" and kw["claude_cmd"] == "claude-work" and kw["effort"] == "high"
    assert ui_sessions.load(r["phases"][1]["session_id"])["bootstrap"] == run["id"]
    try:
        B.continue_run(run["id"])
        raise AssertionError("continue from running")
    except B.Conflict as e:
        assert "running" in str(e)
    for bad in ("0" * 12, "nope"):
        for fn in (B.continue_run, B.retry, B.stop):
            try:
                fn(bad)
                raise AssertionError(bad)
            except ValueError as e:
                assert "bootstrap" in str(e)

    # retry from stopped: same phase, error cleared; a failing start leaves it stopped
    finish(sid_of(run, "decide"), "", "failed", error="crashed")
    B.tick_one(run["id"])
    r = B.load(run["id"])
    assert r["state"] == "stopped" and r["error"] == "crashed" and states(run)[1] == "failed"
    old = sid_of(run, "decide")
    fail_start.append(1)
    try:
        B.retry(run["id"])
        raise AssertionError("failed start")
    except ui_runner.RunnerError:
        pass
    fail_start.clear()
    r = B.load(run["id"])
    assert r["state"] == "stopped" and r["error"] == "crashed" and states(run)[1] == "failed"
    n = len(starts)
    r = B.retry(run["id"])
    assert r["state"] == "running" and r["error"] is None and states(run)[1] == "running" and len(starts) == n + 1
    assert starts[-1][1] == "/repo-bootstrap decide 7" and sid_of(run, "decide") != old
    try:
        B.retry(run["id"])
        raise AssertionError("retry from running")
    except B.Conflict:
        pass

    # stop from running: ended first, live session stopped, tick leaves it ended
    stopped = []
    with mock.patch.object(ui_runner, "stop", lambda sid: stopped.append((sid, B.load(run["id"])["state"]))):
        live = sid_of(run, "decide")
        assert B.stop(run["id"])["state"] == "ended"
        assert stopped == [(live, "ended")], "stopped after the run was ended"
    finish(live, "", "stopped")
    B.tick_one(run["id"])
    assert B.load(run["id"])["state"] == "ended"
    for fn in (B.stop, B.retry, B.continue_run):
        try:
            fn(run["id"])
            raise AssertionError("from ended")
        except B.Conflict as e:
            assert "ended" in str(e)
    # stop from waiting and stopped: nothing started, nothing stopped
    for state in ("waiting", "stopped"):
        run = new_run()
        set_state(run, state)
        n = len(starts)
        with mock.patch.object(ui_runner, "stop", lambda sid: stopped.append(sid)):
            assert B.stop(run["id"])["state"] == "ended" and len(starts) == n
        assert stopped[-1] != run["phases"][0]["session_id"]
    run = new_run()
    set_state(run, "done")
    try:
        B.stop(run["id"])
        raise AssertionError("from done")
    except B.Conflict as e:
        assert "done" in str(e)
    end_run(run)
    print("  ok  continue / retry / stop")

    # ---- HTTP
    for r in B.list_all():
        end_run(r)
    run = new_run()
    finish(sid_of(run, "audit"), line("audit"))
    B.tick_one(run["id"])
    other = B.create("acme/other", "audit", None)
    s, b = call("GET", "/api/bootstraps")
    assert (
        s == 200 and b["runs"][0]["created_at"] >= b["runs"][-1]["created_at"] and len(b["runs"]) == len(B.list_all())
    )
    s, b = call("GET", "/api/bootstraps?repo=ACME/shop")
    assert s == 200 and {r["repo"] for r in b["runs"]} == {REPO} and any(r["id"] == run["id"] for r in b["runs"])
    s, b = call("GET", "/api/bootstraps?repo=nobody/nothing")
    assert s == 400, (s, b)
    s, b = call("POST", f"/api/bootstraps/{run['id']}/retry", {})
    assert s == 409 and "waiting" in b["error"] and b["id"] == run["id"], (s, b)
    s, b = call("POST", "/api/bootstraps/" + "0" * 12 + "/stop", {})
    assert s == 404, (s, b)
    s, b = call("POST", "/api/bootstraps/zz/continue", {})
    assert s == 404, (s, b)
    fail_start.append(1)
    s, b = call("POST", f"/api/bootstraps/{run['id']}/continue", {})
    fail_start.clear()
    assert s == 502 and B.load(run["id"])["state"] == "waiting", (s, b)
    s, b = call("POST", f"/api/bootstraps/{run['id']}/continue", {})
    assert s == 200 and b["state"] == "running" and b["phases"][1]["state"] == "running", (s, b)
    s, b = call("POST", f"/api/bootstraps/{run['id']}/stop", {})
    assert s == 200 and b["state"] == "ended"
    s, b = call("POST", f"/api/bootstraps/{run['id']}/stop", {})
    assert s == 409 and "ended" in b["error"]
    # the session API carries the run, or null
    mine = ui_server._public(ui_sessions.load(sid_of(run, "audit")))
    assert mine["bootstrap"]["id"] == run["id"]
    assert ui_server._public({"id": "x"})["bootstrap"] is None
    assert ui_server._public({"id": "x", "bootstrap": "0" * 12})["bootstrap"] is None, "run file gone"
    end_run(other)
    print("  ok  HTTP: list, filter, 400/404/409/502, session bootstrap field")

print("all ok")
