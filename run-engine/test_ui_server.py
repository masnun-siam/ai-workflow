#!/usr/bin/env python3
"""Self-check for run-engine/ui_server.py. `python3 test_ui_server.py` — exit 0 = green.

Assert-based, no framework, matching test_ui_board.py.
"""

from __future__ import annotations

import argparse
import http.client
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ui_board
import ui_server

passed = 0


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


def boom(*_a, **_k):
    raise AssertionError("fetch_title must not be called")


def start(extras=()):
    srv = ui_server._Server(("127.0.0.1", 0), ui_server._Handler, extras, boom)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def req(port, path="/api/health", method="GET", host="", origin=None, skip_host=False):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    if not skip_host:
        c.putheader("Host", host)
    if origin is not None:
        c.putheader("Origin", origin)
    c.endheaders()
    r = c.getresponse()
    body = r.read()
    headers = r.getheaders()
    c.close()
    return r.status, r, body, headers


def no_cors(headers):
    return not any(k.lower().startswith("access-control-") for k, _ in headers)


def runs_section():
    d = tempfile.mkdtemp()
    old = os.environ.get("CLAUDE_PLUGIN_DATA")
    os.environ["CLAUDE_PLUGIN_DATA"] = d
    rdir = os.path.join(d, "runs")
    os.makedirs(rdir)
    full = ["researcher", "planner", "sdet", "dev", "verifier", "reviewer", "fixer"]
    lean = ["researcher", "planner", "dev", "reviewer", "fixer"]

    def mk(n, led=None, plan=None, mkdir=True):
        p = os.path.join(rdir, f"acme-widgets-issue-{n}")
        if mkdir:
            os.makedirs(p)
        if led is not None:
            with open(os.path.join(p, "run.json"), "w") as f:
                f.write(led if isinstance(led, str) else json.dumps(led))
        if plan is not None:
            with open(os.path.join(p, "10-plan.json"), "w") as f:
                f.write(plan if isinstance(plan, str) else json.dumps(plan))

    def L(n, stations, idx, status="running", trace=()):
        return {"issue": n, "stations": stations, "currentIndex": idx, "status": status,
                "trace": list(trace), "context": {}, "bounceCounts": {}}

    PLAN = {"handoff": {"plan_md": "## Plan\nbody"}}
    adv = ["init: x", "advance->planner", "advance->sdet", "advance->dev"]
    mk(1, L(1, full, 3, trace=adv), PLAN)
    mk(2, L(2, full, 3, trace=adv + ["advance->verifier", "bounce->verifier->dev#1"]))
    mk(3, L(3, full, 1, "escalated", ["init: x", "advance->planner", "escalate: need info"]))
    mk(4, L(4, full, 6, "done", adv + ["done"]))
    mk(5, L(5, lean, 2))
    mk(6, L(6, full, 0))
    mk(7, L(7, full, 0), {"x": 1})
    mk(8, L(8, full, 0), {"handoff": {"plan_md": 5}})
    mk(9, {"issue": 9, "stations": lean, "currentIndex": 1, "status": "running"})
    mk(10, L(10, full, 0), "```json\n" + json.dumps(PLAN) + "\n```")
    mk(11, L(11, full, 0), "Here is the plan:\n" + json.dumps(PLAN))
    mk(12, L(12, full, 0))
    mk(13, L(13, full, 99))
    mk(14, L(14, full, -1))
    mk(16)
    mk(17, '{"issue": 7,', PLAN)
    mk(18, L(18, full, 0), "{not json")
    mk(19, "[]")
    mk(20, L(20, full, "x"))
    mk(21, '{"issue": 7, "context": {"a": 1}, "stations": [')
    mk(22, {**L(22, full, 0), "bounceCounts": ["x"]})

    def snap():
        out = {}
        for root, _, files in os.walk(rdir):
            for fn in files:
                p = os.path.join(root, fn)
                st = os.stat(p)
                with open(p, "rb") as f:
                    out[os.path.relpath(p, rdir)] = (f.read(), st.st_mtime_ns)
            out[os.path.relpath(root, rdir) + "/"] = None
        return out

    before = snap()
    sv, pt = start()
    good = f"127.0.0.1:{pt}"

    def get(n, o="acme", r="widgets"):
        s, rr, body, _ = req(pt, f"/api/runs/{o}/{r}/{n}", host=good)
        assert s == 200, (n, s, body[:80])
        assert rr.getheader("Content-Type", "").startswith("application/json")
        return json.loads(body)

    def sts(b):
        return {s["name"]: s["status"] for s in b["stations"]}

    try:
        b = get(1)
        assert isinstance(b["issue"], int) and b["issue"] == 1
        assert b["owner"] == "acme" and b["repo"] == "widgets"
        assert sts(b) == {"researcher": "done", "planner": "done", "sdet": "done", "dev": "running",
                          "verifier": "pending", "reviewer": "pending", "fixer": "pending"}, sts(b)
        assert b["status"] == "running" and b["currentStation"] == "dev"
        assert b["trace"] == adv and b["plan"] == "## Plan\nbody" and b["errors"] == {}
        assert b["totals"] == {"stations": 7, "done": 3, "bounces": 0}, b["totals"]
        ok("runs: mid-run")

        b = get(2)
        v = [s for s in b["stations"] if s["name"] == "verifier"][0]
        assert v["status"] == "bounced" and v["bounces"] == 1, v
        assert sts(b)["reviewer"] == sts(b)["fixer"] == "pending" and b["totals"]["bounces"] == 1
        ok("runs: bounce")

        b = get(3)
        assert sts(b)["planner"] == "escalated" and sts(b)["researcher"] == "done"
        assert all(sts(b)[n] == "pending" for n in full[2:])
        assert b["status"] == "escalated" and b["currentStation"] == "planner"
        ok("runs: escalated")

        b = get(4)
        assert all(s["status"] == "done" for s in b["stations"]) and b["currentStation"] is None
        assert b["totals"]["done"] == b["totals"]["stations"] == 7
        ok("runs: done")

        assert [s["name"] for s in get(5)["stations"]] == lean
        ok("runs: lean roster from ledger")

        b = get(6)
        assert b["plan"] is None and "plan" not in b["errors"]
        for n in (7, 8):
            b = get(n)
            assert b["plan"] is None and "plan" not in b["errors"], n
        ok("runs: missing plan / no handoff / non-string plan_md -> null")

        b = get(9)
        assert b["trace"] == [] and [s["name"] for s in b["stations"]] == lean
        ok("runs: legacy minimal run.json")

        assert get(10)["plan"] == "## Plan\nbody" and get(11)["plan"] == "## Plan\nbody"
        ok("runs: fenced / prose-prefixed plan recovered")

        b = get(12)
        assert sts(b)["researcher"] == "running" and b["totals"]["done"] == 0
        assert all(sts(b)[n] == "pending" for n in full[1:])
        ok("runs: currentIndex 0")

        assert get(13)["currentStation"] is None and get(14)["currentStation"] is None
        ok("runs: currentIndex out of range -> 200, null currentStation")

        for n in ("0", "007", "abc", "1234567890"):
            assert req(pt, f"/api/runs/acme/widgets/{n}", host=good)[0] == 400, n
        for path in ("/api/runs/acme/widgets", "/api/runs/acme/widgets/1/", "/api/runs/acme/widgets/1/x"):
            assert req(pt, path, host=good)[0] == 404, path
        ok("runs: bad issue number 400 / wrong segment count 404")

        assert req(pt, "/api/runs/acme/widgets/15", host=good)[0] == 404
        assert req(pt, "/api/runs/acme/widgets/16", host=good)[0] == 404
        assert ui_board.load_run("acme", "widgets", "15", runs_dir=rdir) is None
        assert ui_board.load_run("acme", "widgets", "16", runs_dir=rdir) is None
        ok("runs: unknown run / no run.json -> 404, load_run None")

        b = get(17)
        e = b["errors"]["ledger"]
        assert e and "run.json" in e and d not in e and "/" not in e, e
        assert b["status"] is None and b["currentStation"] is None
        assert b["stations"] == [] and b["trace"] == [] and b["plan"] == "## Plan\nbody"
        ok("runs: invalid run.json -> errors.ledger, plan kept")

        b = get(18)
        assert b["errors"].get("plan") and b["plan"] is None and "ledger" not in b["errors"]
        assert b["currentStation"] == "researcher" and len(b["stations"]) == 7
        ok("runs: invalid plan -> errors.plan, ledger intact")

        for n in (19, 20):
            assert get(n)["errors"].get("ledger"), n
        ok("runs: non-object / bad currentIndex -> errors.ledger")

        b = get(21)
        assert b["errors"].get("ledger") and b["status"] is None and b["currentStation"] is None
        assert b["stations"] == [], b
        ok("runs: truncated run.json with nested object -> errors.ledger")

        assert get(22)["errors"].get("ledger")
        ok("runs: non-dict bounceCounts -> errors.ledger, 200")

        for seg in ("..", ".hidden", "-x", "a%2Fb", "%2e%2e", "a%20b", "a;b"):
            assert req(pt, f"/api/runs/{seg}/widgets/1", host=good)[0] == 400, ("owner", seg)
            assert req(pt, f"/api/runs/acme/{seg}/1", host=good)[0] == 400, ("repo", seg)
            try:
                ui_board.load_run(seg, "widgets", "1", runs_dir=rdir)
            except ValueError:
                pass
            else:
                raise AssertionError(f"load_run accepted {seg!r}")
        ok("runs: unsafe segments -> 400 / ValueError")

        s, _, _, h = req(pt, "/api/runs/acme/widgets/1", host="evil.example")
        assert s == 403 and no_cors(h)
        s, r, _, _ = req(pt, "/api/runs/acme/widgets/1", method="POST", host=good)
        assert s == 405 and r.getheader("Allow") == "GET"
        ok("runs: bad host 403, POST 405")

        with ThreadPoolExecutor(2) as ex:
            res = list(ex.map(lambda _: req(pt, "/api/runs/acme/widgets/1", host=good), range(2)))
        assert [x[0] for x in res] == [200, 200] and res[0][2] == res[1][2]
        ok("runs: concurrent GETs identical")

        assert snap() == before
        ok("runs: read-only (runs dir unchanged)")
    finally:
        sv.shutdown()
        sv.server_close()
        shutil.rmtree(d, ignore_errors=True)
        if old is None:
            os.environ.pop("CLAUDE_PLUGIN_DATA", None)
        else:
            os.environ["CLAUDE_PLUGIN_DATA"] = old


if sys.argv[1:] == ["--runs"]:
    runs_section()
    print(f"{passed} checks passed")
    sys.exit(0)

data_dir = tempfile.mkdtemp()
old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
os.environ["CLAUDE_PLUGIN_DATA"] = data_dir
srv, port = start()
tail, tport = start(["box.tailnet.ts.net"])
try:
    # health
    s, r, body, h = req(port, host=f"127.0.0.1:{port}")
    assert s == 200 and r.getheader("Content-Type", "").startswith("application/json")
    assert json.loads(body) == {"ok": True}
    ok("health 127.0.0.1")
    assert req(port, host=f"localhost:{port}")[0] == 200
    ok("health localhost")
    assert req(port, host=f"LOCALHOST:{port}")[0] == 200
    ok("host case-insensitive")

    # board
    s, _, body, _ = req(port, "/board.json", host=f"127.0.0.1:{port}")
    assert s == 200
    assert [c["key"] for c in json.loads(body)["columns"]] == ui_board.STATIONS
    ok("board.json columns == STATIONS")

    # extra allowed host
    assert req(tport, host="box.tailnet.ts.net")[0] == 200
    ok("allow-host accepted")
    assert req(port, host="box.tailnet.ts.net")[0] == 403
    ok("allow-host rejected on server without it")

    # origin
    assert req(port, host=f"127.0.0.1:{port}", origin=f"http://127.0.0.1:{port}")[0] == 200
    assert req(tport, host="box.tailnet.ts.net", origin="https://box.tailnet.ts.net")[0] == 200
    assert req(port, host=f"127.0.0.1:{port}")[0] == 200
    ok("origin == host / no origin allowed")

    # 403s
    good = f"127.0.0.1:{port}"
    for label, kw in [
        ("evil host", dict(host="evil.example")),
        ("other port", dict(host=f"127.0.0.1:{port + 1}")),
        ("evil origin", dict(host=good, origin="http://evil.example")),
        ("origin localhost vs host 127.0.0.1", dict(host=good, origin=f"http://localhost:{port}")),
        ("origin null", dict(host=good, origin="null")),
        ("missing host", dict(skip_host=True)),
    ]:
        s, _, _, h = req(port, **kw)
        assert s == 403, (label, s)
        assert no_cors(h)
        ok(f"403 {label}")

    # CORS absent on 200/404
    assert no_cors(req(port, host=good)[3])
    s, _, _, h = req(port, "/nope", host=good)
    assert s == 404 and no_cors(h)
    ok("no Access-Control-* on 200/404")
    assert req(port, "/nope", host="evil.example")[0] == 403
    ok("bad host + unknown path -> 403")

    # methods
    for m in ("POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE", "CONNECT"):
        s, r, body, _ = req(port, "/board.json", method=m, host=good)
        assert s == 405 and r.getheader("Allow") == "GET", (m, s)
        if m == "HEAD":
            assert body == b"" and r.getheader("Content-Length") == "0"
    ok("all non-GET verbs -> 405 Allow: GET (HEAD empty body)")
    for m in ("OPTIONS", "TRACE"):
        s, _, _, h = req(port, "/board.json", method=m, host="evil.example")
        assert s == 403 and no_cors(h), m
    ok("OPTIONS/TRACE bad host -> 403 (guard first)")
    assert ui_server._Server.allow_reuse_address is False
    ok("allow_reuse_address is False")
    assert req(port, "/board.json", method="POST", host="evil.example")[0] == 403
    ok("POST bad host -> 403")

    # concurrency
    with ThreadPoolExecutor(2) as ex:
        res = list(ex.map(lambda _: req(port, host=good)[0], range(2)))
    assert res == [200, 200]
    ok("concurrent health")
finally:
    srv.shutdown(); tail.shutdown()
    srv.server_close(); tail.server_close()
    shutil.rmtree(data_dir, ignore_errors=True)
    if old_data is None:
        os.environ.pop("CLAUDE_PLUGIN_DATA", None)
    else:
        os.environ["CLAUDE_PLUGIN_DATA"] = old_data

# port in use
def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve_fail(p):
    try:
        ui_server.cmd_serve(argparse.Namespace(port=p, allow_host=None))
    except SystemExit as e:
        return e
    raise AssertionError("expected SystemExit")


p = free_port()
holder = socket.socket()
holder.bind(("127.0.0.1", p))
holder.listen(1)
try:
    buf = io.StringIO()
    with redirect_stderr(buf):
        e = serve_fail(p)
    msg = buf.getvalue() + (e.code if isinstance(e.code, str) else "")
    assert e.code not in (0, None) and str(p) in msg
    assert (str(os.getpid()) if shutil.which("lsof") else f"http://127.0.0.1:{p}/") in msg
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", p + 1)) != 0
    ok("port in use -> SystemExit naming port + holder")

    orig = ui_server._port_holder
    ui_server._port_holder = lambda _p: None
    try:
        buf = io.StringIO()
        with redirect_stderr(buf):
            e = serve_fail(p)
    finally:
        ui_server._port_holder = orig
    msg = buf.getvalue() + (e.code if isinstance(e.code, str) else "")
    assert e.code not in (0, None) and f"http://127.0.0.1:{p}/" in msg and "in use" in msg
    ok("lsof-missing fallback names URL")
finally:
    holder.close()

buf = io.StringIO()
with redirect_stderr(buf):
    e = serve_fail(70000)
assert e.code not in (0, None) and "70000" in buf.getvalue() + (e.code if isinstance(e.code, str) else "")
ok("out-of-range port -> SystemExit naming port")

# CLI wiring
out = subprocess.run([sys.executable, os.path.join(HERE, "route.py"), "ui", "--help"],
                     capture_output=True, text=True)
assert out.returncode == 0 and "--port" in out.stdout and "--allow-host" in out.stdout
ok("route.py ui --help")
parser = argparse.ArgumentParser()
sub = parser.add_subparsers(dest="cmd", required=True)
ui_server.register(sub, lambda name, h: sub.add_parser(name, help=h))
a = parser.parse_args(["ui", "--allow-host", "a", "--allow-host", "b"])
assert a.allow_host == ["a", "b"] and a.port == 8420
ok("register: --allow-host append, --port default 8420")

runs_section()

print(f"{passed} checks passed")
