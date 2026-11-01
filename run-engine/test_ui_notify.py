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
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ui_feed  # noqa: E402
import ui_notify  # noqa: E402
import ui_runner  # noqa: E402
import ui_sessions  # noqa: E402

# notify returns before the push lands: the cases below assert on received requests, so they wait for it.
_async_notify = ui_notify.notify


def _notify_and_drain(event, rec):
    _async_notify(event, rec)
    ui_notify.drain()


ui_notify.notify = _notify_and_drain

# Stub the Mac and feed channels so no test shows a real banner; later sections read these recorders.
REAL_SEND_MAC, REAL_FEED_ADD = ui_notify.send_mac, ui_feed.add
macs, feed = [], []
ui_notify.send_mac = lambda title, body, link=None, **k: macs.append((title, body, link))
ui_feed.add = lambda *a: feed.append(a)

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
                outer.reqs.append(
                    {"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body}
                )
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


REC = {
    "id": "sid1",
    "command": "/implement-issue 5",
    "repo": "o/r",
    "link": {"owner": "o", "repo": "r", "issue": 5},
    "pending_question": None,
}


def rec(**kw):
    return {**REC, **kw}


def meta(d, sid):
    with open(os.path.join(d, "sessions", sid, "meta.json")) as f:
        return json.load(f)


def new_session(command="/implement-issue 5", link=None):
    return ui_sessions.create(command, "o/r", link)["id"]


# 1 normal waiting
f = Fake()
fresh(conf(f))
_, err = captured(lambda: ui_notify.notify("waiting", rec()))
assert len(f.reqs) == 1, f.reqs
r = f.reqs[0]
assert r["path"] == "/aiw-test"
r["headers"]["title"].encode("ascii")
assert r["headers"]["priority"] and r["headers"]["click"] == "https://box.ts.net/#/sessions/sid1"
assert r["headers"]["authorization"] == f"Bearer {SECRET}"
assert b"/implement-issue 5" in r["body"] and b"o/r" in r["body"]
assert SECRET not in err
f.close()
ok("waiting push")

# 2 done/failed click and priority
f = Fake()
fresh(conf(f))
for ev in ("done", "failed", "waiting"):
    ui_notify.notify(ev, rec())
done, failed, waiting = f.reqs
assert done["headers"]["click"] == failed["headers"]["click"] == f"https://box.ts.net/#/sessions/{rec()['id']}"
assert waiting["headers"]["priority"] == failed["headers"]["priority"] != done["headers"]["priority"]
assert waiting["headers"]["priority"] in ("high", "urgent", "4", "5")
f.close()
ok("done/failed click + priority")

# answerer sessions never notify
f = Fake()
fresh(conf(f))
for ev in ("done", "failed", "waiting"):
    ui_notify.notify(ev, rec(role="away-answerer"))
assert not f.reqs, f.reqs
f.close()
ok("answerer: no notification")

# 3 store e2e
f = Fake()
d = fresh(conf(f))
sid = new_session()
ui_sessions.update(sid, status="running")
assert not f.reqs
ui_sessions.update(sid, status="done")
assert len(f.reqs) == 1 and "done" in meta(d, sid)["notified"]
f.close()
ok("update hook done once; running silent")

# 4 runner e2e
f = Fake()
d = fresh(conf(f))
empty = tempfile.mkdtemp()
old = os.environ["PATH"]
os.environ["PATH"] = empty
try:
    try:
        ui_runner.start("/implement-issue 1", tempfile.mkdtemp())
        raise AssertionError("expected RunnerError")
    except ui_runner.RunnerError:
        pass
finally:
    os.environ["PATH"] = old
assert len(f.reqs) == 1 and "fail" in f.reqs[0]["headers"]["title"].lower(), f.reqs
f.close()
ok("runner preflight failure pushes")

# 5 env overrides
f = Fake()
g = Fake()
fresh(conf(f))
os.environ.update(AIW_NTFY_SERVER=g.url, AIW_NTFY_TOPIC="envtopic", AIW_NTFY_TOKEN="tk_ENV")
ui_notify.notify("done", rec())
assert not f.reqs and g.reqs[0]["path"] == "/envtopic" and g.reqs[0]["headers"]["authorization"] == "Bearer tk_ENV"
fresh()
os.environ.update(AIW_NTFY_SERVER=g.url, AIW_NTFY_TOPIC="only")
ui_notify.notify("done", rec())
assert g.reqs[-1]["path"] == "/only"
assert "authorization" not in g.reqs[-1]["headers"]  # 6 no token
f.close()
g.close()
ok("env overrides, env-only, no token")

# 6b basic auth: user+password -> Basic, token wins, password never logged on failure
import base64  # noqa: E402

f = Fake()
fresh({"ntfy": {"server": f.url, "topic": "t", "user": "alice", "password": "s3cret"}})
ui_notify.notify("done", rec())
assert f.reqs[-1]["headers"]["authorization"] == "Basic " + base64.b64encode(b"alice:s3cret").decode()
fresh({"ntfy": {"server": f.url, "topic": "t", "user": "alice", "password": "s3cret", "token": "tk_X"}})
ui_notify.notify("done", rec())
assert f.reqs[-1]["headers"]["authorization"] == "Bearer tk_X"
fresh({"ntfy": {"server": f.url, "topic": "t", "user": "alice"}})
ui_notify.notify("done", rec())
assert "authorization" not in f.reqs[-1]["headers"]  # a user without a password sends nothing
assert f.reqs[-1]["headers"]["user-agent"].startswith("aiw-ui")  # not urllib's default, which Cloudflare blocks
f.close()
ok("basic auth from user+password; token wins; incomplete pair sends no auth; own User-Agent")

# 6c presentation: icon + context tags, issue in title, question/error first, action button
q = {
    "id": "r1",
    "questions": [
        {"header": "Plan", "question": "Approve the plan?\nSecond line", "recommended": "Approve (Recommended)"}
    ],
}
h, body = ui_notify.compose("waiting", rec(pending_question=q), "https://box.ts.net")
assert h["Title"] == "aiw: #5 waiting on you" and h["Tags"] == "speech_balloon,implement-issue,r,#5", h
assert h["Actions"] == "view, Answer, https://box.ts.net/#/sessions/sid1" and h["Click"].endswith("/#/sessions/sid1")
assert body.splitlines() == ["Approve the plan?", "Suggested: Approve (Recommended)", "o/r · /implement-issue 5"], body
h, body = ui_notify.compose("failed", rec(error="claude exited 1\ntraceback..."), "https://box.ts.net")
assert h["Title"] == "aiw: #5 failed" and h["Tags"].startswith("x,") and h["Priority"] == "high"
assert body.splitlines() == ["claude exited 1", "o/r · /implement-issue 5"] and h["Actions"].startswith(
    "view, Open run,"
)
h, body = ui_notify.compose("done", rec(), None)
assert (
    h["Tags"].startswith("white_check_mark,") and h["Priority"] == "default" and "Actions" not in h and "Click" not in h
)
h, _ = ui_notify.compose("done", rec(link=None, command="/create-prd x"), None)
assert h["Title"] == "aiw: run done" and h["Tags"] == "white_check_mark,create-prd,r", h
h, _ = ui_notify.compose("done", rec(link=None, command="/ai-workflow:create-prd x"), None)
assert h["Tags"] == "white_check_mark,create-prd,r", h  # #437: plugin spelling, same tag
h, _ = ui_notify.compose("done", rec(link=None, command="fix the bug"), None)
assert h["Tags"] == "white_check_mark,r", h  # free text: no family tag
h, _ = ui_notify.compose("pipeline", {"id": "p-1", "repo": "o/r", "command": "pipeline x"}, "https://box.ts.net")
assert (
    h["Tags"].startswith("checkered_flag") and h["Actions"] == "view, Open pipeline, https://box.ts.net/#/sessions/p-1"
)
h, body = ui_notify.compose("done", rec(repo="o/r\r\nX-Evil: 1", command="/implement-issue 5\r\nX-Evil: 1"), None)
assert all("\n" not in v and "\r" not in v for v in h.values()) and "X-Evil: 1" not in h["Tags"].replace(
    "X-Evil1", ""
), h
h["Title"].encode("ascii")
h["Tags"].encode("ascii")
ok("compose: icon tags, titles, question/error body, action button, header-safe")

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
f.close()
ok("empty configs silent")

# 8 public_url variants
f = Fake()
c = conf(f)
del c["public_url"]
fresh(c)
ui_notify.notify("done", rec())
assert len(f.reqs) == 1 and "click" not in f.reqs[0]["headers"]
fresh(conf(f, public_url="https://box.ts.net/"))
ui_notify.notify("waiting", rec())
assert f.reqs[-1]["headers"]["click"] == "https://box.ts.net/#/sessions/sid1"
f.close()
ok("public_url missing / trailing slash")

# 9 link fallback
f = Fake()
fresh(conf(f))
for link in (None, {"owner": "o"}):  # a session links to itself, with or without an issue
    ui_notify.notify("done", rec(link=link))
    assert f.reqs[-1]["headers"]["click"] == "https://box.ts.net/#/sessions/sid1", link
ui_notify.notify("done", rec(id=None))  # nothing to point at: Activity
assert f.reqs[-1]["headers"]["click"] == "https://box.ts.net/#/activity"
f.close()
ok("link fallback")

# 10 modes
f = Fake()
for m in (0o644, 0o640, 0o604):
    d = fresh(conf(f), mode=m)
    _, err = captured(lambda: ui_notify.notify("done", rec()))
    assert not f.reqs and "ui.json" in err and oct(m)[2:] in err and "0600" in err, (oct(m), err)
for m in (0o600, 0o400):
    fresh(conf(f), mode=m)
    n = len(f.reqs)
    ui_notify.notify("done", rec())
    assert len(f.reqs) == n + 1, oct(m)
f.close()
ok("file modes")

# 11 non-ASCII
f = Fake()
fresh(conf(f))
ui_notify.notify("done", rec(command="/implement-issue 修正"))
f.reqs[0]["headers"]["title"].encode("ascii")
assert "修正".encode() in f.reqs[0]["body"]
f.close()
ok("non-ASCII command")

# 12 quoting
f = Fake()
fresh(conf(f))
ui_notify.notify("done", rec(id="a b/c"))
c = f.reqs[-1]["headers"]["click"]
assert c.endswith("#/sessions/a%20b%2Fc"), c
ui_notify.notify("waiting", rec(id="x y/z"))
c = f.reqs[-1]["headers"]["click"]
assert "x%20y" in c and "x y" not in c, c
f.close()
ok("url quoting")

# 13 malformed
f = Fake()
for raw in ("{not json", "[1,2]"):
    fresh(raw=raw)
    _, err = captured(lambda: ui_notify.notify("done", rec()))
    assert not f.reqs and err.strip(), raw
f.close()
ok("malformed json")

# 14 bad scheme
f = Fake()
fresh({"ntfy": {"server": "file:///etc/passwd", "topic": "t"}})
_, err = captured(lambda: ui_notify.notify("done", rec()))
assert err.strip() and not f.reqs
f.close()
ok("non-http server")

# 15 dedupe
f = Fake()
d = fresh(conf(f))
sid = new_session()
ui_sessions.update(sid, status="done")
ui_sessions.update(sid, status="done")
assert len(f.reqs) == 1
sid = new_session()
ts = [threading.Thread(target=ui_sessions.update, args=(sid,), kwargs={"status": "failed"}) for _ in range(2)]
[t.start() for t in ts]
[t.join() for t in ts]
assert len(f.reqs) == 2 and meta(d, sid)["notified"].count("failed") == 1
f.close()
ok("dedupe done / concurrent failed")

# 16 waiting rounds
f = Fake()
d = fresh(conf(f))
sid = new_session()
for q in ("r1", "r1", "r2"):
    ui_sessions.update(sid, status="waiting", pending_question={"id": q})
assert len(f.reqs) == 2
f.close()
ok("waiting per round")


# 17 error paths + 18 token redaction
def closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{p}"


old_t = ui_notify.TIMEOUT_SECONDS
cases = [
    ("401", Fake(401, echo_auth=True)),
    ("403", Fake(403)),
    ("500", Fake(500)),
    ("closed", None),
    ("slow", Fake(200, delay=2.0)),
]
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

for ev, word in (("pr-ready", "ready"), ("needs-cleanup", "cleanup"), ("panel-cap", "cap")):
    h, body = ui_notify.compose(
        ev, {"repo": "o/r", "link": {"owner": "o", "repo": "r", "issue": 7}, "note": "the note"}, "https://x.ts.net"
    )
    assert word in h["Title"] and "the note" in body and h["Click"] == "https://x.ts.net/#/inbox", (ev, h)
ok("pr-ready, needs-cleanup and panel-cap compose")

# --- prd-comment
assert [e[0] for e in ui_notify.EVENTS][3:5] == ["panel-cap", "prd-comment"] and len(ui_notify.EVENTS) == 12
assert ui_notify.matrix({})["prd-comment"] == {"browser": True, "ntfy": False, "mac": False}
assert len(ui_notify.matrix({})) * len(ui_notify.CHANNELS) == 36
assert all(
    ui_notify.default_cell(e, c) == (True if c == "ntfy" else g != "Finished" and e != "grind-done")
    for e, _, g in ui_notify.EVENTS
    if e != "prd-comment"
    for c in ui_notify.CHANNELS
), "other defaults unchanged"
assert ui_notify.matrix({"channels": {"prd-comment": {"ntfy": True}}})["prd-comment"]["ntfy"] is True
h, body = ui_notify.compose("prd-comment", {"note": "2 new comments on My PRD"}, "https://x.ts.net")
assert body == "2 new comments on My PRD" and h["Click"] == "https://x.ts.net/#/inbox", (h, body)
assert ui_notify.click_path("prd-comment", {"note": "n"}) == "#/inbox"
ok("prd-comment: matrix defaults and compose")

from unittest import mock  # noqa: E402

feed.clear(), macs.clear()
with mock.patch.object(ui_notify, "send_ntfy", side_effect=AssertionError("ntfy is off")):
    assert ui_notify.prd_comment("a", "1 new comment on T", now=100.0) is True
    assert ui_notify.prd_comment("a", "2 new comments on T", now=130.0) is False
    assert ui_notify.prd_comment("b", "1 new comment on T", now=130.0) is True
    assert ui_notify.prd_comment("a", "2 new comments on T", now=161.0) is True
assert not macs and len(feed) == 3
assert feed[0][2] == "1 new comment on T" and feed[0][-1] == "#/inbox", feed[0]
ok("prd_comment: once per share per minute, browser only")

# --- fan-out
import itertools  # noqa: E402
from unittest import mock  # noqa: E402

ui_notify.send_mac = lambda title, body, link=None, **k: macs.append((title, body, link))


def fan(cfg, event="failed", record=None, fake_cfg=True):
    """Run notify against a fake ntfy; return (ntfy requests, mac calls, feed entries)."""
    macs.clear(), feed.clear()
    f = Fake()
    try:
        fresh(conf(f, **cfg) if fake_cfg else cfg)
        captured(lambda: ui_notify.notify(event, record or rec(error="boom")))
        return list(f.reqs), list(macs), list(feed)
    finally:
        f.close()


for b, n, m in itertools.product((False, True), repeat=3):
    reqs, ms, fd = fan({"channels": {"failed": {"browser": b, "ntfy": n, "mac": m}}})
    assert (len(fd), len(reqs), len(ms)) == (b, n, m), (b, n, m)
ok("8 cell combinations route to exactly the enabled channels")

reqs, ms, fd = fan({"channels": {"failed": {"browser": False, "mac": False}}})
assert len(reqs) == 1 and not ms and not fd
ok("failed with browser and mac off: ntfy only")

reqs, ms, fd = fan({"channels": {"failed": {"browser": True, "ntfy": False, "mac": True}}})
assert len(fd) == 1 and len(ms) == 1 and not reqs
assert fd[0][1] == ms[0][0] == "aiw: #5 failed" and fd[0][2] == ms[0][1] == "boom\no/r · /implement-issue 5"
assert fd[0][3] == "#/sessions/sid1" and ms[0][2] == "https://box.ts.net/#/sessions/sid1"
reqs, ms, fd = fan({"public_url": None, "channels": {"failed": {"browser": True, "ntfy": False, "mac": True}}})
assert fd[0][3] == "#/sessions/sid1" and ms[0][2] is None
ok("feed and Mac get the ntfy title/body; path always, link only with a public URL")

reqs, ms, fd = fan({"channels": {"failed": {"browser": True, "mac": True}}})
assert reqs[0]["headers"]["title"] == fd[0][1] and reqs[0]["body"].decode() == fd[0][2]
ok("ntfy request carries the same title and body")

# quiet rules apply to every channel
for c in ("/pr-grind 5", "/ai-workflow:pr-grind https://x.slack.com/archives/C1/p5", "Start the review grind for PR 5"):
    reqs, ms, fd = fan({}, "done", rec(command=c))
    assert not (reqs or ms or fd), c
reqs, ms, fd = fan({}, "done", rec(command="/ai-workflow:implement-issue 5"))
assert reqs or ms or fd, "only grind rounds are quiet"
import ui_afk  # noqa: E402

with mock.patch.object(ui_afk, "active", return_value=True):
    reqs, ms, fd = fan({}, "waiting")
    assert not (reqs or ms or fd)
ok("grind-round done and away-mode holds reach no channel")

# a channel failing never stops the others or reaches the caller
macs.clear(), feed.clear()
for status in (500, 200):
    f = Fake(status=status, delay=0 if status == 500 else 0.2)
    ui_notify.TIMEOUT_SECONDS = 0.05 if status == 200 else 5
    try:
        fresh(conf(f, channels={"failed": {"browser": True, "ntfy": True, "mac": True}}))
        captured(lambda: ui_notify.notify("failed", rec(error="x")))
    finally:
        f.close()
        ui_notify.TIMEOUT_SECONDS = 5
    assert len(macs) == 1 and len(feed) == 1, status
    macs.clear(), feed.clear()


def boom(*a, **k):
    raise RuntimeError("nope")


f = Fake()
fresh(conf(f, channels={"failed": {"browser": True, "ntfy": True, "mac": True}}))
with mock.patch.object(ui_notify, "send_mac", boom):
    captured(lambda: ui_notify.notify("failed", rec(error="x")))
    assert len(f.reqs) == 1 and len(feed) == 1
feed.clear()
with mock.patch.object(ui_feed, "add", boom):
    captured(lambda: ui_notify.notify("failed", rec(error="x")))
    assert len(f.reqs) == 2 and len(macs) == 1
f.close()
ok("ntfy HTTP error or timeout, a raising Mac sender or feed never stop the rest")

# ntfy not set up: other channels still route
macs.clear(), feed.clear()
fresh({"channels": {"failed": {"browser": True, "ntfy": True, "mac": True}}})
captured(lambda: ui_notify.notify("failed", rec(error="x")))
assert len(macs) == 1 and len(feed) == 1
assert ui_notify.send_ntfy({"ntfy": {}}, {}, "t", "failed", {}) == "ntfy is not set up"
ok("ntfy cells on but not set up still routes the others")

# click_url output is unchanged
assert ui_notify.click_url("failed", rec(), "https://h/") == "https://h/#/sessions/sid1"
assert ui_notify.click_url("pr-ready", {}, "https://h") == "https://h/#/inbox"
assert ui_notify.click_url("done", {}, "https://h") == "https://h/#/activity"
assert ui_notify.click_url("done", rec(), None) is None
ok("click_url unchanged")

# --- send_mac
ui_notify.send_mac = REAL_SEND_MAC
import types  # noqa: E402
from unittest import mock  # noqa: E402

calls = []
fake_run = lambda argv, **k: calls.append((argv, k)) or types.SimpleNamespace(returncode=0)  # noqa: E731
with mock.patch.dict(os.environ):
    os.environ.pop("AIW_NO_MAC_BANNER", None)
    with mock.patch.object(sys, "platform", "linux"):
        assert ui_notify.send_mac("t", "b", run=fake_run) == "Only on macOS" and not calls
    with mock.patch.object(sys, "platform", "darwin"):
        with mock.patch("shutil.which", return_value="/x/terminal-notifier"):
            ui_notify._notifier.cache_clear()
            assert ui_notify.send_mac("t", "b", "https://h/#/x", run=fake_run) is None
            assert calls[-1][0] == ["/x/terminal-notifier", "-title", "t", "-message", "b", "-open", "https://h/#/x"]
            assert calls[-1][1]["timeout"] == 10
            ui_notify.send_mac("t", "", run=fake_run)
            assert calls[-1][0] == ["/x/terminal-notifier", "-title", "t", "-message", "t"]
        with mock.patch("shutil.which", return_value=None):
            ui_notify._notifier.cache_clear()
            evil = 'x" & do shell script "rm'
            ui_notify.send_mac("t", evil, run=fake_run)
            assert (
                calls[-1][0][0] == "osascript"
                and calls[-1][0][-2:] == [evil, "t"]
                and "rm" not in " ".join(calls[-1][0][:-2])
            )

            def boom(argv, **k):
                raise subprocess.TimeoutExpired(argv, 10)

            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                assert ui_notify.send_mac("t", "b", run=boom) == "TimeoutExpired"
            assert buf.getvalue().count("macOS notification failed") == 1
            assert ui_notify.send_mac("t", "b", run=lambda a, **k: types.SimpleNamespace(returncode=1)) == "exit 1"
with mock.patch.dict(os.environ, {"AIW_NO_MAC_BANNER": "1"}), mock.patch.object(sys, "platform", "darwin"):
    calls.clear()
    assert ui_notify.send_mac("t", "b", run=fake_run) == "Turned off by AIW_NO_MAC_BANNER" and not calls
with mock.patch.dict(os.environ, {"AIW_NO_MAC_BANNER": "1"}), mock.patch.object(sys, "platform", "linux"):
    assert ui_notify.send_mac("t", "b", run=fake_run) == "Only on macOS"
ui_notify._notifier.cache_clear()
ok("send_mac: terminal-notifier, osascript argv, non-Mac, errors, AIW_NO_MAC_BANNER off-switch")

# send_test: one sample on one channel, ignoring the matrix and Away mode
import ui_afk  # noqa: E402

f = Fake()
fresh(conf(f, channels={e: {"browser": False, "ntfy": False, "mac": False} for e in ui_notify.matrix({"ntfy": {}})}))
with mock.patch.object(ui_afk, "active", return_value=True):
    res = ui_notify.send_test("ntfy")
assert res == {"ok": True}, res
assert len(f.reqs) == 1 and f.reqs[0]["headers"]["title"] == "aiw: test notification"
assert f.reqs[0]["headers"]["authorization"] == f"Bearer {SECRET}"
assert f.reqs[0]["headers"]["click"] == "https://box.ts.net/#/settings/notifications"
f.close()
f = Fake(status=401)
fresh(conf(f))
res, err = captured(lambda: ui_notify.send_test("ntfy"))
assert res == {"ok": False, "error": "HTTP 401"} and SECRET not in json.dumps(res) + err and "aiw-test" not in err
f.close()
fresh(conf(Fake(), ntfy={"server": closed_port(), "topic": "aiw-test"}))
res, err = captured(lambda: ui_notify.send_test("ntfy"))
assert res["ok"] is False and "aiw-test" not in json.dumps(res) + err, res
f = Fake()
fresh({})
assert ui_notify.send_test("ntfy") == {"ok": False, "error": "ntfy is not set up"} and not f.reqs
f.close()
for bad in ("browser", "x", None):
    try:
        ui_notify.send_test(bad)
        raise AssertionError(bad)
    except ValueError:
        pass
sent = []
fresh({})
with mock.patch.object(ui_notify, "send_mac", lambda *a: sent.append(a)):
    assert ui_notify.send_test("mac") == {"ok": True}
assert sent == [("aiw: test notification", "This is a test from aiw ui.", None)], sent
with mock.patch.object(ui_notify, "send_mac", lambda *a: "Only on macOS"):
    assert ui_notify.send_test("mac") == {"ok": False, "error": "Only on macOS"}
ok("send_test: ntfy ok/401/unreachable/not set up, mac, bad channel, ignores matrix and Away")

print(f"\n{passed} passed")


# notify never blocks on a slow channel, and the push still arrives
fresh({})
slow = Fake(200, delay=2.0)
os.environ.update(AIW_NTFY_SERVER=slow.url, AIW_NTFY_TOPIC="slow")
t0 = time.time()
_async_notify("done", rec())
assert time.time() - t0 < 0.5, "notify blocked on a slow channel"
ui_notify.drain()
assert len(slow.reqs) == 1, slow.reqs
slow.close()
