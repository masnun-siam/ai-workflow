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

print(f"{passed} checks passed")
