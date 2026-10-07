#!/usr/bin/env python3
"""Self-check for run-engine/ui_runner.py. `python3 test_ui_runner.py` — exit 0 = green.

Assert-based, no framework, matching test_ui_sessions.py. A fake `claude` shell script
is put first on PATH; env vars FAKE_CLAUDE_MODE / FAKE_CLAUDE_AUTH / FAKE_DIR drive it.
"""

from __future__ import annotations

import concurrent.futures
import http.client
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ui_runner  # noqa: E402
import ui_server  # noqa: E402
import ui_sessions  # noqa: E402

passed = 0
ORIG_PATH = os.environ.get("PATH", "")
INIT = '{"type":"system","subtype":"init","session_id":"sess-abc"}'
ASSIST = '{"type":"assistant","message":"hi"}'
RESULT = '{"type":"result","subtype":"success","is_error":false,"total_cost_usd":0.0421}'
RESULT_ERR = '{"type":"result","subtype":"error","is_error":true,"total_cost_usd":0.5}'

FAKE = r"""#!/bin/sh
if [ "$1" = "auth" ]; then
  case "$FAKE_CLAUDE_AUTH" in
    out) echo '{"loggedIn": false}'; exit 1;;
    garbage) echo 'not json at all'; exit 2;;
    *) echo '{"loggedIn": true}'; exit 0;;
  esac
fi
printf '%s\n' "$@" > "$FAKE_DIR/argv"
pwd > "$FAKE_DIR/pwd"
echo "$FAKE_CLAUDE_INIT_ENV" > /dev/null
INIT='{"type":"system","subtype":"init","session_id":"'"${FAKE_SID:-sess-abc}"'"}'
RESULT='{"type":"result","subtype":"success","is_error":false,"total_cost_usd":'"${FAKE_COST:-0.0421}"'}'
case "$FAKE_CLAUDE_MODE" in
  normal)
    printf '%s\n' "$INIT" '{"type":"assistant","message":"hi"}' "$RESULT"
    echo "some warning" >&2
    exit 0;;
  crash)
    echo "boom on stderr" >&2
    exit 3;;
  iserror)
    printf '%s\n' "$INIT" '{"type":"result","subtype":"error","is_error":true,"total_cost_usd":0.5}'
    exit 1;;
  junk)
    printf '%s\n' "$INIT" 'this is not json' '[1,2,3]'
    printf '%s' "$RESULT"
    exit 0;;
  ask)
    printf '%s\n' "$INIT"
    while [ ! -f "$FAKE_DIR/exit" ]; do sleep 0.1; done
    printf '%s\n' "$RESULT"
    exit 0;;
  askfail)
    printf '%s\n' "$INIT"
    while [ ! -f "$FAKE_DIR/exit" ]; do sleep 0.1; done
    exit 1;;
  sleep|stuck|spawn)
    [ "$FAKE_CLAUDE_MODE" = stuck ] && trap '' TERM
    if [ "$FAKE_CLAUDE_MODE" = spawn ]; then sleep 300 & echo $! > "$FAKE_DIR/gc"; fi
    printf '%s\n' "$INIT"
    while :; do
      if [ -f "$FAKE_DIR/go" ]; then echo '{"type":"assistant","message":"LATE"}'; rm -f "$FAKE_DIR/go"; fi
      sleep 0.2
    done;;
esac
"""


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


def fresh() -> str:
    d = tempfile.mkdtemp()
    os.environ["CLAUDE_PLUGIN_DATA"] = d
    return d


def setup(mode="normal", auth="in"):
    """Fresh data dir + fake claude on PATH. Returns (data_dir, fake_dir, work_dir)."""
    d = fresh()
    fake_dir = tempfile.mkdtemp()
    bindir = os.path.join(fake_dir, "bin")
    os.mkdir(bindir)
    exe = os.path.join(bindir, "claude")
    with open(exe, "w") as f:
        f.write(FAKE)
    os.chmod(exe, 0o755)
    os.environ["PATH"] = bindir + os.pathsep + ORIG_PATH
    os.environ["FAKE_DIR"] = fake_dir
    os.environ["FAKE_CLAUDE_MODE"] = mode
    os.environ["FAKE_CLAUDE_AUTH"] = auth
    for k in ("FAKE_SID", "FAKE_COST"):
        os.environ.pop(k, None)
    return d, fake_dir, tempfile.mkdtemp()


def sdir(sid):
    return ui_sessions.session_dir(sid)


def read(sid, name):
    with open(os.path.join(sdir(sid), name), "rb") as f:
        return f.read()


def wait_for(pred, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("timed out waiting for condition")


def wait_status(sid, statuses, timeout=20.0):
    return wait_for(lambda: (r := ui_sessions.load(sid)) and r["status"] in statuses and r, timeout)


def wait_finished(sid):
    wait_for(lambda: sid not in ui_runner._procs)


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def group_gone(pgid):
    try:
        os.killpg(pgid, 0)
        return False
    except ProcessLookupError:
        return True


def reap(*recs):
    for r in recs:
        pid = r and r.get("pid")
        if pid:
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


def real(p):
    return os.path.realpath(p.strip())


def lines(fake_dir, name):
    with open(os.path.join(fake_dir, name)) as f:
        return f.read()


def no_sessions(d):
    return not os.path.isdir(os.path.join(d, "sessions")) or not os.listdir(os.path.join(d, "sessions"))


def all_sessions():
    return ui_sessions.list_sessions()


# ---- answer API (issue #117) ------------------------------------------------
def answer_checks():
    def boom(*_a, **_k):
        raise AssertionError("fetch_title must not be called")

    srv = ui_server._Server(("127.0.0.1", 0), ui_server._Handler, (), boom)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    live = []

    def req(method, path, body=None, headers=None, ctype="application/json"):
        h = dict(headers or {})
        if method == "POST" and ctype and "Content-Type" not in h:
            h["Content-Type"] = ctype
        data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            return r.status, r.headers, json.loads(raw)
        except ValueError:
            return r.status, r.headers, raw

    def post(sid, rid, answers, **kw):
        return req("POST", f"/api/sessions/{sid}/answer", {"round_id": rid, "answers": answers}, **kw)

    def rnd(rid="q-1", free=None):
        q1 = {"header": "Branch", "question": "Which branch?", "multiSelect": True,
              "options": [{"label": "master", "description": "main"}, {"label": "staging", "description": "stage"}]}
        if free is not None:
            q1["allowFreeText"] = free
        return {"id": rid, "status": "pending", "questions": [
            {"header": "Gate 1", "question": "Proceed?", "multiSelect": False,
             "options": [{"label": "Approve and start (Recommended)", "description": "go"},
                         {"label": "Revise", "description": "rework"},
                         {"label": "Abort", "description": "stop"}]}, q1]}

    GOOD = {"0": {"labels": ["Revise"]}, "1": {"labels": ["master"]}}

    def mk(rid="q-1", free=None, mode="normal", pending=True):
        """Cheap waiting session: recorded INIT stream, session_id set, no live process."""
        d, fk, work = setup(mode)
        sid = ui_sessions.create("/run-issue 1", work)["id"]
        with open(os.path.join(sdir(sid), "stream.jsonl"), "ab") as f:
            f.write((INIT + "\n").encode())
        ui_sessions.update(sid, session_id="sess-abc", status="done")
        if pending:
            ui_sessions.set_pending(sid, rnd(rid, free))
        return sid, fk, work

    def spawned(fk):
        return os.path.exists(os.path.join(fk, "argv"))

    def text(rid, norm):
        return f"Answer to {rid}: " + json.dumps(norm, ensure_ascii=False, separators=(",", ":"))

    def argv_of(fk, t):
        return ui_runner.CLAUDE_ARGS + ["--resume", "sess-abc", t]

    def intact(sid, fk, rid="q-1"):
        r = ui_sessions.load(sid)
        assert r["status"] == "waiting" and r["pending_question"]["id"] == rid \
            and r["pending_question"]["status"] == "pending", r
        assert not spawned(fk)

    try:
        # -- set_pending stores the record; GET shows waiting
        sid, fk, work = mk()
        r = ui_sessions.load(sid)
        pq = r["pending_question"]
        assert r["status"] == "waiting" and pq["id"] == "q-1" and pq["status"] == "pending", r
        assert pq["allowFreeText"] is True
        q0, q1 = pq["questions"]
        assert q0["header"] == "Gate 1" and q0["question"] == "Proceed?" and q0["multiSelect"] is False
        assert q0["options"][1] == {"label": "Revise", "description": "rework"}
        assert q0["recommended"] == "Approve and start (Recommended)" and q1["recommended"] is None
        assert q1["multiSelect"] is True and q1["allowFreeText"] is True
        s, _, b = req("GET", f"/api/sessions/{sid}")
        assert s == 200 and b["waiting"] is True and b["outcome"] == "waiting" and b["pending_question"] == pq, b
        ok("set_pending stores round, derived recommended/allowFreeText, GET shows waiting")

        # -- waiting after a real finished run, no process alive
        d, fk, work = setup("normal")
        rec = ui_runner.start("/run-issue 1", work)
        live.append(rec)
        wait_status(rec["id"], {"done", "failed"})
        wait_finished(rec["id"])
        ui_sessions.set_pending(rec["id"], rnd())
        r = ui_sessions.load(rec["id"])
        assert r["status"] == "waiting" and not alive(r["pid"]) and r["session_id"] == "sess-abc", r
        ok("waiting session has no live process")

        # -- ask mode: set_pending mid-run survives clean exit
        d, fk, work = setup("ask")
        rec = ui_runner.start("/run-issue 1", work)
        live.append(rec)
        wait_for(lambda: b"init" in read(rec["id"], "stream.jsonl"))
        pend = ui_sessions.set_pending(rec["id"], rnd())["pending_question"]
        open(os.path.join(fk, "exit"), "w").close()
        wait_finished(rec["id"])
        r = ui_sessions.load(rec["id"])
        assert r["status"] == "waiting" and r["pending_question"] == pend, r
        ok("clean exit during waiting keeps status waiting and the round")

        # -- process still alive: 409, nothing spawned
        d, fk, work = setup("ask")
        rec = ui_runner.start("/run-issue 1", work)
        live.append(rec)
        wait_for(lambda: b"init" in read(rec["id"], "stream.jsonl"))
        ui_sessions.set_pending(rec["id"], rnd())
        assert rec["id"] in ui_runner._procs
        before = lines(fk, "argv")
        s, _, _ = post(rec["id"], "q-1", GOOD)
        assert s == 409 and lines(fk, "argv") == before and "--resume" not in before
        open(os.path.join(fk, "exit"), "w").close()
        wait_finished(rec["id"])
        ok("waiting but process alive: 409, no spawn")

        # -- happy path through HTTP
        sid, fk, work = mk()
        old_pid = ui_sessions.load(sid)["pid"]
        before = read(sid, "stream.jsonl")
        ans = {"0": {"labels": ["Revise"]}, "1": {"other": "drop task 3"}}
        s, _, b = post(sid, "q-1", ans)
        assert s == 200, (s, b)
        wait_status(sid, {"done", "failed"})
        wait_finished(sid)
        assert lines(fk, "argv").split("\n")[:-1] == argv_of(fk, text("q-1", ans)), lines(fk, "argv")
        assert lines(fk, "argv").split("\n")[:-1][-1] == \
            'Answer to q-1: {"0":{"labels":["Revise"]},"1":{"other":"drop task 3"}}'
        assert real(lines(fk, "pwd")) == real(work)
        after = read(sid, "stream.jsonl")
        assert after.startswith(before) and len(after) > len(before) and after.count(b'"init"') == 2
        r = ui_sessions.load(sid)
        assert r["status"] == "done" and r["pending_question"] is None and r["pid"] != old_pid, r
        ok("answer 200: exact resume argv, cwd, stream appended, done, round cleared")

        # -- re-POST after 200 -> 409, no second spawn
        os.remove(os.path.join(fk, "argv"))
        s, _, _ = post(sid, "q-1", ans)
        assert s == 409 and not spawned(fk)
        ok("re-answering a resumed round: 409, no spawn")

        # -- multiSelect order preserved
        sid, fk, work = mk()
        a = {"0": {"labels": ["Abort"]}, "1": {"labels": ["staging", "master"]}}
        assert post(sid, "q-1", a)[0] == 200
        wait_status(sid, {"done", "failed"})
        wait_finished(sid)
        assert lines(fk, "argv").split("\n")[:-1][-1] == text("q-1", a)
        assert '["staging","master"]' in text("q-1", a)
        ok("multiSelect labels keep sent order")

        # -- direct resume()
        sid, fk, work = mk(mode="ask")
        ui_sessions.update(sid, status="waiting", error="old", ended_at="2020-01-01T00:00:00Z")
        t = text("q-1", GOOD)
        out = ui_runner.resume(sid, t)
        r = ui_sessions.load(sid)
        assert r["status"] == "running" and r["ended_at"] is None and r["error"] is None, r
        wait_for(lambda: spawned(fk) and lines(fk, "argv").endswith(t + "\n"))
        assert lines(fk, "argv").split("\n")[:-1] == argv_of(fk, t)
        open(os.path.join(fk, "exit"), "w").close()
        wait_status(sid, {"done", "failed"})
        wait_finished(sid)
        assert ui_sessions.load(sid)["status"] == "done"
        ok("resume(): exact argv, running then done, ended_at/error cleared")

        # -- 400s leave the round intact (one session), then boundary 4000 ok
        sid, fk, work = mk()
        bad_answers = [
            None, {}, [], "x", {"0": {"labels": ["Revise"]}},
            {"1": {"labels": ["master"]}},
            {**GOOD, "2": {"labels": ["master"]}},
            {"0": {"labels": ["Revise"], "other": "x"}, "1": GOOD["1"]},
            {"0": "Revise", "1": GOOD["1"]},
            {"0": {}, "1": GOOD["1"]},
            {"0": {"labels": []}, "1": GOOD["1"]},
            {"0": GOOD["0"], "1": {"other": ""}},
            {"0": GOOD["0"], "1": {"other": "   \n"}},
            {"0": {"labels": ["Ship it"]}, "1": GOOD["1"]},
            {"0": {"labels": ["master"]}, "1": GOOD["1"]},
            {"0": {"labels": ["Revise", "Abort"]}, "1": GOOD["1"]},
            {"0": GOOD["0"], "1": {"labels": ["master", "master"]}},
            {"0": {"labels": ["Rev\x00ise"]}, "1": GOOD["1"]},
            {"0": GOOD["0"], "1": {"other": "a\x00b"}},
            {"0": GOOD["0"], "1": {"other": "a" * 4001}},
        ]
        for a in bad_answers:
            s, _, b = post(sid, "q-1", a)
            assert s == 400 and "error" in b, (a, s, b)
            intact(sid, fk)
        s, _, b = req("POST", f"/api/sessions/{sid}/answer", {"answers": GOOD})
        assert s == 400, s
        for raw in (b"not json{", b"[1,2]", b'"x"', b"123", b"null"):
            assert req("POST", f"/api/sessions/{sid}/answer", raw)[0] == 400, raw
        intact(sid, fk)
        s, _, b = post(sid, "q-1", {"0": GOOD["0"], "1": {"other": "a" * 4001}})
        assert "4000" in b["error"], b
        ok("invalid answers/bodies: 400, round intact, nothing spawned")

        # -- 4000 boundary accepted, after the 400s above
        assert post(sid, "q-1", {"0": GOOD["0"], "1": {"other": "a" * 4000}})[0] == 200
        wait_status(sid, {"done", "failed"})
        wait_finished(sid)
        ok("exactly 4000 chars accepted; round usable after earlier 400s")

        # -- free text rejected when allowFreeText false
        sid2, fk2, _ = mk(free=False)
        s, _, _ = post(sid2, "q-1", {"0": GOOD["0"], "1": {"other": "x"}})
        assert s == 400
        intact(sid2, fk2)
        ok("free text on allowFreeText=False question: 400")

        # -- lone surrogate in free text: 400, round intact, then valid answer 200
        sid, fk, work = mk()
        body = ('{"round_id":"q-1","answers":{"0":{"labels":["Revise"]},'
                '"1":{"other":"x\\ud800y"}}}').encode()
        s, _, b = req("POST", f"/api/sessions/{sid}/answer", body)
        assert s == 400 and "error" in b, (s, b)
        intact(sid, fk)
        assert post(sid, "q-1", GOOD)[0] == 200
        wait_status(sid, {"done", "failed"})
        wait_finished(sid)
        ok("lone surrogate free text: 400, round intact, valid answer still 200")

        # -- run that recorded a round then exits non-zero: failed, round cleared
        d, fk, work = setup("askfail")
        rec = ui_runner.start("/run-issue 1", work)
        live.append(rec)
        wait_for(lambda: b"init" in read(rec["id"], "stream.jsonl"))
        ui_sessions.set_pending(rec["id"], rnd())
        open(os.path.join(fk, "exit"), "w").close()
        wait_finished(rec["id"])
        r = ui_sessions.load(rec["id"])
        assert r["status"] == "failed" and r["pending_question"] is None, r
        ok("round recorded then non-zero exit: failed, pending_question None")

        # -- oversized body 413, not read
        sid, fk, work = mk()
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        c.putrequest("POST", f"/api/sessions/{sid}/answer")
        c.putheader("Content-Type", "application/json")
        c.putheader("Content-Length", str(64 * 1024 + 1))
        c.endheaders()
        assert c.getresponse().status == 413
        c.close()
        intact(sid, fk)
        ok("body over 64 KiB: 413, round intact")

        # -- 415
        s, _, _ = post(sid, "q-1", GOOD, ctype="application/x-www-form-urlencoded")
        assert s == 415
        intact(sid, fk)
        ok("wrong content type: 415")

        # -- not waiting
        for st in ("starting", "running", "done", "failed", "stopped"):
            for with_pq in (True, False):
                sid3, fk3, _ = mk(pending=False)
                ui_sessions.update(sid3, status=st, **({"pending_question": rnd()} if with_pq else {}))
                s, _, _ = post(sid3, "q-1", GOOD)
                assert s == 409 and not spawned(fk3), (st, with_pq, s)
        sid3, fk3, _ = mk(pending=False)
        ui_sessions.update(sid3, status="waiting", pending_question=None)
        assert post(sid3, "q-1", GOOD)[0] == 409 and not spawned(fk3)
        ok("not waiting / waiting without round: 409, no spawn")

        # -- stale round id
        sid, fk, work = mk("q-1")
        ui_sessions.set_pending(sid, rnd("q-2"))
        snap = ui_sessions.load(sid)
        assert post(sid, "q-1", GOOD)[0] == 409 and not spawned(fk)
        assert ui_sessions.load(sid) == snap
        assert post(sid, "q-2", GOOD)[0] == 200
        wait_status(sid, {"done", "failed"})
        wait_finished(sid)
        ok("stale round 409 unchanged; current round 200")

        # -- session_id missing
        sid, fk, work = mk()
        ui_sessions.update(sid, session_id=None)
        assert post(sid, "q-1", GOOD)[0] == 409
        intact(sid, fk)
        ok("waiting without session_id: 409 before claim")

        # -- spawn failure after claim
        sid, fk, work = mk()
        os.environ["PATH"] = tempfile.mkdtemp()
        try:
            s, _, b = post(sid, "q-1", GOOD)
        finally:
            os.environ["PATH"] = fk + "/bin" + os.pathsep + ORIG_PATH
        assert s == 500 and b["error"], (s, b)
        r = ui_sessions.load(sid)
        assert r["status"] == "failed" and r["error"] and r["ended_at"] and r["pending_question"] is None, r
        ok("resume spawn failure: 500, failed, round cleared")

        # -- 404s
        for bad in ("nope", "..", "%2e%2e"):
            s, _, _ = req("POST", f"/api/sessions/{bad}/answer", {"round_id": "q-1", "answers": GOOD})
            assert s == 404, (bad, s)
        ok("unknown/malformed session ids: 404")

        # -- 405 still holds
        for path in ("/api/sessions", "/board.json", f"/api/sessions/{sid}"):
            s, h, _ = req("POST", path, {})
            assert s == 405 and h["Allow"] == "GET", (path, s)
        ok("other POSTs still 405 with Allow: GET")

        # -- set_pending validation
        sid, fk, work = mk(pending=False)
        base = ui_sessions.load(sid)
        good = rnd()

        def mut(fn):
            r = json.loads(json.dumps(good))
            fn(r)
            return r

        bads = [None, [], "x", mut(lambda r: r.pop("id")), mut(lambda r: r.update(id="")),
                mut(lambda r: r.update(questions=[])), mut(lambda r: r.update(questions="x")),
                mut(lambda r: r["questions"][0].update(options=[])),
                mut(lambda r: r["questions"][0]["options"][0].pop("label")),
                mut(lambda r: r["questions"][0]["options"][0].update(label="")),
                mut(lambda r: r["questions"][0]["options"][0].update(label=5)),
                mut(lambda r: r["questions"][0]["options"][1].update(label="Abort")),
                mut(lambda r: r["questions"][0].update(multiSelect="no"))]
        for b_ in bads:
            try:
                ui_sessions.set_pending(sid, b_)
                raise AssertionError(f"expected ValueError for {b_!r}")
            except ValueError:
                pass
            assert ui_sessions.load(sid) == base
        try:
            ui_sessions.set_pending("20990101T000000000000Z-deadbeef", good)
            raise AssertionError("expected FileNotFoundError")
        except FileNotFoundError:
            pass
        try:
            ui_sessions.set_pending("../x", good)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
        ok("set_pending validation: ValueError, record unchanged; unknown/invalid sid")

        # -- shell metacharacters
        sid, fk, work = mk()
        meta = "x; touch PWNED $(id) `id`"
        a = {"0": GOOD["0"], "1": {"other": meta}}
        assert post(sid, "q-1", a)[0] == 200
        wait_status(sid, {"done", "failed"})
        wait_finished(sid)
        assert lines(fk, "argv").split("\n")[:-1] == argv_of(fk, text("q-1", a))
        assert not os.path.exists(os.path.join(work, "PWNED")) and not os.path.exists(os.path.join(fk, "PWNED"))
        ok("metacharacters stay in one argv element")

        # -- claim_answer branch matrix
        sid, fk, work = mk()
        won = ui_sessions.claim_answer(sid, "q-1")
        assert won and won["pending_question"] is None and won["status"] == "starting", won
        assert ui_sessions.claim_answer(sid, "q-1") is None
        sid, fk, work = mk()
        snap = ui_sessions.load(sid)
        assert ui_sessions.claim_answer(sid, "q-0") is None and ui_sessions.load(sid) == snap
        ui_sessions.update(sid, status="running")
        assert ui_sessions.claim_answer(sid, "q-1") is None
        ui_sessions.update(sid, status="waiting", pending_question=None)
        assert ui_sessions.claim_answer(sid, "q-1") is None
        try:
            ui_sessions.claim_answer("20990101T000000000000Z-deadbeef", "q-1")
            raise AssertionError("expected FileNotFoundError")
        except FileNotFoundError:
            pass
        try:
            ui_sessions.claim_answer("../x", "q-1")
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
        ok("claim_answer branch matrix")

        # -- claim_answer across real processes
        sid, fk, work = mk()
        child = (
            "import os,sys,time\nsys.path.insert(0,%r)\nimport ui_sessions\n"
            "sid,go=sys.argv[1],sys.argv[2]\n"
            "while not os.path.exists(go): time.sleep(0.001)\n"
            "print(1 if ui_sessions.claim_answer(sid,'q-1') else 0)\n" % HERE)
        go = os.path.join(tempfile.mkdtemp(), "go")
        procs = [subprocess.Popen([sys.executable, "-c", child, sid, go], stdout=subprocess.PIPE, text=True)
                 for _ in range(8)]
        open(go, "w").close()
        wins = [p.communicate(timeout=60)[0].strip() for p in procs]
        assert wins.count("1") == 1 and wins.count("0") == 7, wins
        r = ui_sessions.load(sid)
        assert r["pending_question"] is None and r["status"] == "starting", r
        assert not [n for n in os.listdir(sdir(sid)) if ".tmp" in n]
        ok("claim_answer: exactly one of 8 processes wins")

        # -- concurrent POSTs
        sid, fk, work = mk()
        with concurrent.futures.ThreadPoolExecutor(2) as ex:
            codes = sorted(f.result()[0] for f in [ex.submit(post, sid, "q-1", GOOD) for _ in range(2)])
        assert codes == [200, 409], codes
        wait_status(sid, {"done", "failed"})
        wait_finished(sid)
        assert read(sid, "stream.jsonl").count(b'"init"') == 2
        ok("two concurrent answers: [200, 409], one spawn")

        # -- permissions
        sid, fk, work = mk()
        for hdr in ({"Host": "evil.example"}, {"Origin": "http://evil.example"}):
            s, h, _ = post(sid, "q-1", GOOD, headers=hdr)
            assert s == 403 and not [k for k in h.keys() if k.lower().startswith("access-control")], (hdr, s)
        intact(sid, fk)
        ok("bad Host/Origin: 403, no CORS headers, round intact")
    finally:
        srv.shutdown()
        srv.server_close()
        reap(*live)


if "--answer" in sys.argv:
    answer_checks()
    print(f"\n{passed} checks passed")
    sys.exit(0)


# ---- normal: full run -------------------------------------------------------
d, fk, work = setup("normal")
rec = ui_runner.start("/run-issue 42", work)
sid = rec["id"]
try:
    assert rec["status"] == "running" and rec["pid"], rec
    ok("start returns running record with pid")
    final = wait_status(sid, {"done", "failed"})
    wait_finished(sid)
    final = ui_sessions.load(sid)
    assert read(sid, "stream.jsonl") == (INIT + "\n" + ASSIST + "\n" + RESULT + "\n").encode()
    assert final["session_id"] == "sess-abc" and final["cost"] == 0.0421, final
    assert final["status"] == "done" and final["pid"] and final["ended_at"], final
    ok("normal run: stream bytes, session_id, cost, done, ended_at")
    assert lines(fk, "argv").split("\n")[:-1] == [
        "--print", "--output-format", "stream-json", "--verbose",
        "--dangerously-skip-permissions", "/run-issue 42"], lines(fk, "argv")
    assert ui_runner.CLAUDE_ARGS == ["--print", "--output-format", "stream-json", "--verbose",
                                     "--dangerously-skip-permissions"]
    assert real(lines(fk, "pwd")) == real(work)
    ok("argv exact, cwd is checkout")
    assert b"some warning" in read(sid, "stderr.log")
    assert b"some warning" not in read(sid, "stream.jsonl")
    ok("stderr goes to stderr.log only")
finally:
    reap(rec)

# ---- slug via checkouts.json -----------------------------------------------
d, fk, work = setup("normal")
with open(os.path.join(d, "checkouts.json"), "w") as f:
    json.dump({"my-slug": work}, f)
rec = ui_runner.start("/run-issue 1", "my-slug")
try:
    wait_status(rec["id"], {"done", "failed"})
    assert real(lines(fk, "pwd")) == real(work)
    assert ui_sessions.load(rec["id"])["repo"] == "my-slug"
    ok("checkouts.json slug resolves to path; repo records slug")
finally:
    reap(rec)

# ---- detached ---------------------------------------------------------------
d, fk, work = setup("sleep")
helper = (
    "import sys; sys.path.insert(0, %r); import ui_runner; "
    "r = ui_runner.start('/run-issue 5', %r); print(r['id'], r['pid'])" % (HERE, work)
)
out = subprocess.run([sys.executable, "-c", helper], capture_output=True, text=True, timeout=60)
assert out.returncode == 0, out.stderr
sid, pid = out.stdout.split()
pid = int(pid)
try:
    assert alive(pid), "child died with its starter"
    assert os.getpgid(pid) == pid and os.getsid(pid) == pid
    assert pid != os.getpgrp() and os.getsid(pid) != os.getsid(0)
    open(os.path.join(fk, "go"), "w").close()
    wait_for(lambda: b"LATE" in read(sid, "stream.jsonl"))
    ok("detached: survives starter, own session/group, writes after starter exit land")
finally:
    reap({"pid": pid})

# ---- stop graceful ----------------------------------------------------------
d, fk, work = setup("sleep")
rec = ui_runner.start("/run-issue 6", work)
sid, pid = rec["id"], rec["pid"]
try:
    wait_for(lambda: b"init" in read(sid, "stream.jsonl"))
    t0 = time.time()
    ui_runner.stop(sid)
    assert time.time() - t0 < ui_runner.STOP_GRACE_SECONDS
    assert group_gone(pid)
    r = ui_sessions.load(sid)
    assert r["status"] == "stopped" and r["ended_at"], r
    wait_finished(sid)
    assert ui_sessions.load(sid)["status"] == "stopped"
    ok("stop graceful: group gone, status stopped and sticks")
    again = ui_runner.stop(sid)
    assert again["status"] == "stopped"
    ok("second stop on stopped is a no-op")
finally:
    reap(rec)

# ---- stop SIGKILL path ------------------------------------------------------
assert ui_runner.STOP_GRACE_SECONDS == 10
d, fk, work = setup("stuck")
rec = ui_runner.start("/run-issue 7", work)
sid, pid = rec["id"], rec["pid"]
try:
    wait_for(lambda: b"init" in read(sid, "stream.jsonl"))
    time.sleep(0.5)  # let the shell install its trap
    with mock.patch.object(ui_runner, "STOP_GRACE_SECONDS", 1):
        t0 = time.time()
        ui_runner.stop(sid)
        elapsed = time.time() - t0
    assert elapsed >= 1.0, elapsed
    assert group_gone(pid)
    assert ui_sessions.load(sid)["status"] == "stopped"
    ok("stop escalates to SIGKILL after grace; default grace is 10")
finally:
    reap(rec)

# ---- stop kills whole group -------------------------------------------------
d, fk, work = setup("spawn")
rec = ui_runner.start("/run-issue 8", work)
sid = rec["id"]
try:
    gc = int(wait_for(lambda: os.path.exists(os.path.join(fk, "gc")) and lines(fk, "gc").strip()))
    assert alive(gc)
    with mock.patch.object(ui_runner, "STOP_GRACE_SECONDS", 1):
        ui_runner.stop(sid)
    wait_for(lambda: not alive(gc), 5)
    ok("stop kills grandchild in the group")
finally:
    reap(rec)

# ---- stop idempotent on finished + errors ----------------------------------
d, fk, work = setup()
for st in ("done", "failed", "stopped"):
    r = ui_sessions.create("/x", work)
    r = ui_sessions.update(r["id"], status=st, pid=os.getpid())
    with mock.patch("os.killpg") as kp, mock.patch("os.kill") as k:
        out = ui_runner.stop(r["id"])
        assert not kp.called and not k.called
    assert out["status"] == st
ok("stop on done/failed/stopped sends no signal")
for bad in ("20990101T000000000000Z-deadbeef",):
    try:
        ui_runner.stop(bad)
        raise AssertionError("expected raise")
    except AssertionError:
        raise
    except Exception:
        pass
try:
    ui_runner.stop("../x")
    raise AssertionError("expected ValueError")
except ValueError:
    pass
ok("stop unknown sid raises; invalid sid raises ValueError")

# ---- missing binary ---------------------------------------------------------
d, fk, work = setup()
empty = tempfile.mkdtemp()
os.environ["PATH"] = empty
try:
    with mock.patch.object(subprocess, "Popen") as po:
        try:
            ui_runner.start("/run-issue 9", work)
            raise AssertionError("expected RunnerError")
        except ui_runner.RunnerError as e:
            assert "claude" in str(e) and "PATH" in str(e), e
        assert not po.called
finally:
    os.environ["PATH"] = ORIG_PATH
ss = all_sessions()
assert len(ss) == 1 and ss[0]["status"] == "failed" and ss[0]["error"] \
    and ss[0]["ended_at"] and ss[0]["pid"] is None, ss
ok("missing claude: RunnerError, failed record, no spawn")

# ---- logged out / garbage auth ---------------------------------------------
d, fk, work = setup(auth="out")
try:
    ui_runner.start("/run-issue 9", work)
    raise AssertionError("expected RunnerError")
except ui_runner.RunnerError as e:
    assert "claude auth login" in str(e), e
ss = all_sessions()
assert len(ss) == 1 and ss[0]["status"] == "failed" and ss[0]["error"], ss
assert not os.path.exists(os.path.join(fk, "argv"))
ok("logged out: RunnerError mentions claude auth login, command never ran")

d, fk, work = setup(auth="garbage")
try:
    ui_runner.start("/run-issue 9", work)
    raise AssertionError("expected RunnerError")
except ui_runner.RunnerError:
    pass
ss = all_sessions()
assert len(ss) == 1 and ss[0]["status"] == "failed" and ss[0]["error"], ss
assert not os.path.exists(os.path.join(fk, "argv"))
ok("garbage auth status is not treated as logged in")

# ---- crash / is_error -------------------------------------------------------
d, fk, work = setup("crash")
rec = ui_runner.start("/run-issue 10", work)
try:
    wait_status(rec["id"], {"done", "failed"})
    wait_finished(rec["id"])
    r = ui_sessions.load(rec["id"])
    assert r["status"] == "failed" and "3" in r["error"] and "stderr.log" in r["error"], r
    assert b"boom on stderr" in read(rec["id"], "stderr.log")
    ok("crash: failed, error names exit code 3 and stderr.log")
finally:
    reap(rec)

d, fk, work = setup("iserror")
rec = ui_runner.start("/run-issue 10", work)
try:
    wait_status(rec["id"], {"done", "failed"})
    wait_finished(rec["id"])
    r = ui_sessions.load(rec["id"])
    assert r["status"] == "failed" and r["cost"] == 0.5, r
    ok("result is_error: failed, cost still recorded")
finally:
    reap(rec)

# ---- Popen OSError, no fd leak ---------------------------------------------
d, fk, work = setup()
real_popen = subprocess.Popen


def picky(args, *a, **kw):
    if "--print" in args:
        raise OSError("exec format boom")
    return real_popen(args, *a, **kw)


before = len(os.listdir("/dev/fd"))
with mock.patch.object(subprocess, "Popen", side_effect=picky):
    try:
        ui_runner.start("/run-issue 11", work)
        raise AssertionError("expected RunnerError")
    except ui_runner.RunnerError as e:
        assert "exec format boom" in str(e), e
ss = all_sessions()
assert len(ss) == 1 and ss[0]["status"] == "failed" and "exec format boom" in ss[0]["error"], ss
assert len(os.listdir("/dev/fd")) <= before, "fd leak"
ok("Popen OSError: failed with OS error text, RunnerError, no fd leak")

# ---- bad stream lines -------------------------------------------------------
d, fk, work = setup("junk")
rec = ui_runner.start("/run-issue 12", work)
try:
    wait_status(rec["id"], {"done", "failed"})
    wait_finished(rec["id"])
    r = ui_sessions.load(rec["id"])
    raw = read(rec["id"], "stream.jsonl")
    assert b"this is not json\n[1,2,3]\n" in raw and raw.endswith(RESULT.encode()), raw
    assert r["cost"] == 0.0421 and r["session_id"] == "sess-abc" and r["status"] == "done", r
    ok("bad lines skipped, raw bytes kept, trailing partial result parsed")
finally:
    reap(rec)

# ---- input validation -------------------------------------------------------
d, fk, work = setup()
for bad in ("", "   \n", None, "-p evil", "--help"):
    try:
        ui_runner.start(bad, work)
        raise AssertionError(f"expected ValueError for {bad!r}")
    except ValueError:
        pass
assert no_sessions(d)
ok("empty/None/dash-leading command raises ValueError, no session")
for bad in (os.path.join(work, "nope"), "unknown-slug"):
    try:
        ui_runner.start("/run-issue 1", bad)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
assert no_sessions(d)
ok("bad cwd raises ValueError, no session")

# ---- shell metacharacters ---------------------------------------------------
d, fk, work = setup()
cmd = "/run-issue 1; touch PWNED"
rec = ui_runner.start(cmd, work)
try:
    wait_status(rec["id"], {"done", "failed"})
    assert lines(fk, "argv").split("\n")[-2] == cmd
    assert not os.path.exists(os.path.join(work, "PWNED"))
    assert not os.path.exists(os.path.join(fk, "PWNED"))
    ok("metacharacters are one argv element, no shell")
finally:
    reap(rec)

# ---- concurrency ------------------------------------------------------------
d, fk, work = setup("sleep")
recs = []
try:
    os.environ["FAKE_SID"], os.environ["FAKE_COST"] = "sess-A", "0.1"
    a = ui_runner.start("/run-issue 1", work)
    recs.append(a)
    os.environ["FAKE_SID"], os.environ["FAKE_COST"] = "sess-B", "0.2"
    b = ui_runner.start("/run-issue 2", tempfile.mkdtemp())
    recs.append(b)
    assert a["id"] != b["id"] and a["pid"] != b["pid"]
    assert os.getpgid(a["pid"]) != os.getpgid(b["pid"])
    wait_for(lambda: (ui_sessions.load(a["id"]) or {}).get("session_id") == "sess-A")
    wait_for(lambda: (ui_sessions.load(b["id"]) or {}).get("session_id") == "sess-B")
    assert b"sess-A" in read(a["id"], "stream.jsonl") and b"sess-B" not in read(a["id"], "stream.jsonl")
    assert b"sess-B" in read(b["id"], "stream.jsonl") and b"sess-A" not in read(b["id"], "stream.jsonl")
    ok("two concurrent sessions: distinct pids/pgids, no cross-talk")
finally:
    reap(*recs)

answer_checks()

print(f"\n{passed} checks passed")
