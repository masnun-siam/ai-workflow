#!/usr/bin/env python3
"""Self-check for run-engine/ui_notify.py. `python3 test_ui_notify.py` — exit 0 = green.

Assert-based, no framework. Fresh CLAUDE_PLUGIN_DATA per case, AIW_NTFY_* popped,
fake ntfy server on 127.0.0.1:0.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ui_notify  # noqa: E402
import ui_runner  # noqa: E402
import ui_sessions  # noqa: E402

passed = 0
SECRET = "tk_SECRET"


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


class Fake:
    def __init__(self, status=200, delay=0.0, echo_auth=False):
        self.reqs, self.status, self.delay, self.echo = [], status, delay, echo_auth
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.reqs.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                                   "body": body})
                if outer.delay:
                    time.sleep(outer.delay)
                out = (self.headers.get("Authorization") or "").encode() if outer.echo else b"ok"
                try:
                    self.send_response(outer.status)
                    self.send_header("Content-Length", str(len(out)))
                    self.end_headers()
                    self.wfile.write(out)
                except OSError:
                    pass

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def fresh(cfg=None, mode=0o600, raw=None):
    for k in [k for k in os.environ if k.startswith("AIW_NTFY_")]:
        del os.environ[k]
    d = tempfile.mkdtemp()
    os.environ["CLAUDE_PLUGIN_DATA"] = d
    if cfg is not None or raw is not None:
        p = os.path.join(d, "ui.json")
        with open(p, "w") as f:
            f.write(raw if raw is not None else json.dumps(cfg))
        os.chmod(p, mode)
    return d


def conf(fake, **extra):
    c = {"ntfy": {"server": fake.url, "topic": "aiw-test", "token": SECRET}, "public_url": "https://box.ts.net"}
    c.update(extra)
    return c


def captured(fn):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        res = fn()
    return res, err.getvalue()


REC = {"id": "sid1", "command": "/run-issue 5", "repo": "o/r", "link": {"owner": "o", "repo": "r", "issue": 5},
       "pending_question": None}


def rec(**kw):
    return {**REC, **kw}


def meta(d, sid):
    with open(os.path.join(d, "sessions", sid, "meta.json")) as f:
        return json.load(f)


def new_session(command="/run-issue 5", link=None):
    return ui_sessions.create(command, "o/r", link)["id"]


# 1 normal waiting
f = Fake(); fresh(conf(f))
_, err = captured(lambda: ui_notify.notify("waiting", rec()))
assert len(f.reqs) == 1, f.reqs
r = f.reqs[0]
assert r["path"] == "/aiw-test"
r["headers"]["title"].encode("ascii")
assert r["headers"]["priority"] and r["headers"]["click"] == "https://box.ts.net/#/answer/sid1"
assert r["headers"]["authorization"] == f"Bearer {SECRET}"
assert b"/run-issue 5" in r["body"] and b"o/r" in r["body"]
assert SECRET not in err
f.close(); ok("waiting push")

# 2 done/failed click and priority
f = Fake(); fresh(conf(f))
for ev in ("done", "failed", "waiting"):
    ui_notify.notify(ev, rec())
done, failed, waiting = f.reqs
assert done["headers"]["click"] == failed["headers"]["click"] == "https://box.ts.net/#/run/o/r/5"
assert waiting["headers"]["priority"] == failed["headers"]["priority"] != done["headers"]["priority"]
assert waiting["headers"]["priority"] in ("high", "urgent", "4", "5")
f.close(); ok("done/failed click + priority")

# 3 store e2e
f = Fake(); d = fresh(conf(f))
sid = new_session()
ui_sessions.update(sid, status="running")
assert not f.reqs
ui_sessions.update(sid, status="done")
assert len(f.reqs) == 1 and "done" in meta(d, sid)["notified"]
f.close(); ok("update hook done once; running silent")

# 4 runner e2e
f = Fake(); d = fresh(conf(f))
empty = tempfile.mkdtemp(); old = os.environ["PATH"]; os.environ["PATH"] = empty
try:
    try:
        ui_runner.start("/run-issue 1", tempfile.mkdtemp())
        raise AssertionError("expected RunnerError")
    except ui_runner.RunnerError:
        pass
finally:
    os.environ["PATH"] = old
assert len(f.reqs) == 1 and "fail" in f.reqs[0]["headers"]["title"].lower(), f.reqs
f.close(); ok("runner preflight failure pushes")

# 5 env overrides
f = Fake(); g = Fake(); fresh(conf(f))
os.environ.update(AIW_NTFY_SERVER=g.url, AIW_NTFY_TOPIC="envtopic", AIW_NTFY_TOKEN="tk_ENV")
ui_notify.notify("done", rec())
assert not f.reqs and g.reqs[0]["path"] == "/envtopic" and g.reqs[0]["headers"]["authorization"] == "Bearer tk_ENV"
fresh()
os.environ.update(AIW_NTFY_SERVER=g.url, AIW_NTFY_TOPIC="only")
ui_notify.notify("done", rec())
assert g.reqs[-1]["path"] == "/only"
assert "authorization" not in g.reqs[-1]["headers"]  # 6 no token
f.close(); g.close(); ok("env overrides, env-only, no token")

# 7 empty configs
f = Fake()
for kind in ("missing", "zero", "{}", '{"ntfy":{}}', "notopic"):
    if kind == "missing":
        fresh()
    elif kind == "notopic":
        fresh({"ntfy": {"server": f.url, "topic": ""}})
    else:
        fresh(raw=kind if kind != "zero" else "")
    _, err = captured(lambda: ui_notify.notify("done", rec()))
    assert not f.reqs and err == "", (kind, err)
f.close(); ok("empty configs silent")

# 8 public_url variants
f = Fake(); c = conf(f); del c["public_url"]; fresh(c)
ui_notify.notify("done", rec())
assert len(f.reqs) == 1 and "click" not in f.reqs[0]["headers"]
fresh(conf(f, public_url="https://box.ts.net/"))
ui_notify.notify("waiting", rec())
assert f.reqs[-1]["headers"]["click"] == "https://box.ts.net/#/answer/sid1"
f.close(); ok("public_url missing / trailing slash")

# 9 link fallback
f = Fake(); fresh(conf(f))
for link in (None, {"owner": "o"}):
    ui_notify.notify("done", rec(link=link))
    assert f.reqs[-1]["headers"]["click"] == "https://box.ts.net/#/sessions", link
f.close(); ok("link fallback")

# 10 modes
f = Fake()
for m in (0o644, 0o640, 0o604):
    d = fresh(conf(f), mode=m)
    _, err = captured(lambda: ui_notify.notify("done", rec()))
    assert not f.reqs and "ui.json" in err and oct(m)[2:] in err and "0600" in err, (oct(m), err)
for m in (0o600, 0o400):
    fresh(conf(f), mode=m)
    n = len(f.reqs); ui_notify.notify("done", rec())
    assert len(f.reqs) == n + 1, oct(m)
f.close(); ok("file modes")

# 11 non-ASCII
f = Fake(); fresh(conf(f))
ui_notify.notify("done", rec(command="/run-issue 修正"))
f.reqs[0]["headers"]["title"].encode("ascii")
assert "修正".encode() in f.reqs[0]["body"]
f.close(); ok("non-ASCII command")

# 12 quoting
f = Fake(); fresh(conf(f))
ui_notify.notify("done", rec(link={"owner": "a b", "repo": "c/d", "issue": 5}))
c = f.reqs[-1]["headers"]["click"]
assert "a%20b" in c and "c%2Fd" in c, c
ui_notify.notify("waiting", rec(id="x y/z"))
c = f.reqs[-1]["headers"]["click"]
assert "x%20y" in c and "x y" not in c, c
f.close(); ok("url quoting")

# 13 malformed
f = Fake()
for raw in ("{not json", "[1,2]"):
    fresh(raw=raw)
    _, err = captured(lambda: ui_notify.notify("done", rec()))
    assert not f.reqs and err.strip(), raw
f.close(); ok("malformed json")

# 14 bad scheme
f = Fake(); fresh({"ntfy": {"server": "file:///etc/passwd", "topic": "t"}})
_, err = captured(lambda: ui_notify.notify("done", rec()))
assert err.strip() and not f.reqs
f.close(); ok("non-http server")

# 15 dedupe
f = Fake(); d = fresh(conf(f)); sid = new_session()
ui_sessions.update(sid, status="done"); ui_sessions.update(sid, status="done")
assert len(f.reqs) == 1
sid = new_session()
ts = [threading.Thread(target=ui_sessions.update, args=(sid,), kwargs={"status": "failed"}) for _ in range(2)]
[t.start() for t in ts]; [t.join() for t in ts]
assert len(f.reqs) == 2 and meta(d, sid)["notified"].count("failed") == 1
f.close(); ok("dedupe done / concurrent failed")

# 16 waiting rounds
f = Fake(); d = fresh(conf(f)); sid = new_session()
for q in ("r1", "r1", "r2"):
    ui_sessions.update(sid, status="waiting", pending_question={"id": q})
assert len(f.reqs) == 2
f.close(); ok("waiting per round")

# 17 error paths + 18 token redaction
def closed_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return f"http://127.0.0.1:{p}"


old_t = ui_notify.TIMEOUT_SECONDS
cases = [("401", Fake(401, echo_auth=True)), ("403", Fake(403)), ("500", Fake(500)),
         ("closed", None), ("slow", Fake(200, delay=2.0))]
for name, fk in cases:
    c = {"ntfy": {"server": fk.url if fk else closed_port(), "topic": "t", "token": SECRET}}
    d = fresh(c)
    ui_notify.TIMEOUT_SECONDS = 0.3
    sid = new_session()
    t0 = time.time()
    r, err = captured(lambda: ui_sessions.update(sid, status="done"))
    ui_notify.TIMEOUT_SECONDS = old_t
    assert time.time() - t0 < 1.5, name
    assert err.strip(), name
    assert r["status"] == "done" and meta(d, sid)["status"] == "done"
    blob = err + json.dumps(r) + json.dumps(meta(d, sid)) + json.dumps(ui_sessions.list_sessions())
    assert SECRET not in blob, name
    if fk:
        fk.close()
ok("errors logged, never raised, token redacted")

print(f"\n{passed} passed")
