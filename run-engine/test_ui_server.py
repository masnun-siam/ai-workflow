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
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ui_gh  # noqa: E402
import ui_grind  # noqa: E402
import ui_server  # noqa: E402
import ui_sessions  # noqa: E402
import ui_start  # noqa: E402
import ui_watch  # noqa: E402

passed = 0
# no test touches the network: `gh api user` is stubbed for the whole file
ui_gh.status = lambda *a, **k: {"ok": True, "login": "me", "error": None}


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


def start(extras=()):
    srv = ui_server._Server(("127.0.0.1", 0), ui_server._Handler, extras)
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

    # removed engine-era endpoints answer 404; cleanup moved under /api/sessions
    me = f"127.0.0.1:{port}"
    for p in (
        "/board.json",
        "/api/runs/o/r/1",
        "/api/pipelines",
        "/api/flows",
        "/api/notes",
        "/api/cleanup",
        "/api/pulls/o/r/1/merge",
    ):
        assert req(port, p, host=me)[0] == 404, p
    for p in (
        "/api/dispatch/preview",
        "/api/autopilot",
        "/api/grind/start",
        "/api/maintree/release",
        "/api/runs/o/r/1/options",
    ):
        assert req(port, p, method="POST", host=me)[0] == 404, p
    s, _, body, _ = req(port, "/api/sessions/cleanup", host=me)
    assert s == 200 and json.loads(body) == {"items": []}
    ok("removed endpoints 404; GET /api/sessions/cleanup lists")

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
        s, r, body, _ = req(port, "/api/health", method=m, host=good)
        assert s == 405 and r.getheader("Allow") == "GET", (m, s)
        if m == "HEAD":
            assert body == b"" and r.getheader("Content-Length") == "0"
    ok("all non-GET verbs -> 405 Allow: GET (HEAD empty body)")
    for m in ("OPTIONS", "TRACE"):
        s, _, _, h = req(port, "/api/health", method=m, host="evil.example")
        assert s == 403 and no_cors(h), m
    ok("OPTIONS/TRACE bad host -> 403 (guard first)")
    assert ui_server._Server.allow_reuse_address is True
    ok("allow_reuse_address is True")
    assert req(port, "/api/health", method="POST", host="evil.example")[0] == 403
    ok("POST bad host -> 403")

    # concurrency
    with ThreadPoolExecutor(2) as ex:
        res = list(ex.map(lambda _: req(port, host=good)[0], range(2)))
    assert res == [200, 200]
    ok("concurrent health")
finally:
    srv.shutdown()
    tail.shutdown()
    srv.server_close()
    tail.server_close()
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
        ui_server.cmd_serve(argparse.Namespace(port=p, allow_host=None, no_tailscale=True, tailscale_port=8443))
    except SystemExit as e:
        return e
    raise AssertionError("expected SystemExit")


os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()  # cmd_serve clears old data on entry: never the real dir
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
out = subprocess.run([sys.executable, os.path.join(HERE, "route.py"), "ui", "--help"], capture_output=True, text=True)
assert out.returncode == 0 and "--port" in out.stdout and "--allow-host" in out.stdout
ok("route.py ui --help")
parser = argparse.ArgumentParser()
sub = parser.add_subparsers(dest="cmd", required=True)
ui_server.register(sub, lambda name, h: sub.add_parser(name, help=h))
a = parser.parse_args(["ui", "--allow-host", "a", "--allow-host", "b"])
assert a.allow_host == ["a", "b"] and a.port == 8420
ok("register: --allow-host append, --port default 8420")
# A cold page load opens many connections at once; none may be reset by a tiny listen backlog.
assert ui_server._Server.request_queue_size >= 64, ui_server._Server.request_queue_size
sv, pt = start()
good = f"127.0.0.1:{pt}"
failures = []


def burst():
    try:
        assert req(pt, host=good)[0] == 200
    except Exception as exc:  # collected so the main thread can fail with the cause
        failures.append(exc)


threads = [threading.Thread(target=burst) for _ in range(60)]
for t in threads:
    t.start()
for t in threads:
    t.join()
sv.shutdown()
assert not failures, failures[:2]
ok("burst of 60 simultaneous connections all served (listen backlog)")

# ---- /: the built app from ui_dist/ (not built yet -> 404 with a short text body); /next/ is gone
ns, port = start()
me = f"127.0.0.1:{port}"
real_dist = ui_server.DIST_DIR
dist = tempfile.mkdtemp()
ui_server.DIST_DIR = os.path.join(dist, "missing")
s_, r_, body, h_ = req(port, "/", host=me)
assert s_ == 404 and r_.getheader("Content-Type").startswith("text/plain") and 0 < len(body) < 100, (s_, body)
ui_server.DIST_DIR = os.path.join(dist, "ui_dist")
os.makedirs(os.path.join(dist, "ui_dist", "assets"))
for rel, text in (("index.html", "<html>new</html>"), ("assets/app-1a2b.js", "x()"), ("sw.js", "i")):
    with open(os.path.join(dist, "ui_dist", rel), "w") as f:
        f.write(text)
with open(os.path.join(dist, "secret.txt"), "w") as f:
    f.write("secret")
s_, r_, body, h_ = req(port, "/", host=me)
assert s_ == 200 and body == b"<html>new</html>" and r_.getheader("Cache-Control") == "no-cache", (s_, h_)
assert r_.getheader("Content-Type").startswith("text/html")
s_, r_, body, h_ = req(port, "/assets/app-1a2b.js", host=me)
assert s_ == 200 and r_.getheader("Content-Type").startswith("text/javascript") and body == b"x()"
assert "immutable" in r_.getheader("Cache-Control"), "hashed assets may be cached"
assert req(port, "/sw.js", host=me)[1].getheader("Cache-Control") == "no-cache"
for p in (
    "/next/",
    "/next",
    "/assets/nope.js",
    "/assets",
    "/assets/%2e%2e/secret.txt",
    "/assets/..%2fsecret.txt",
    "/assets/%252e%252e/secret.txt",
):
    s_, r_, body, h_ = req(port, p, host=me)
    assert s_ == 404 and b"secret" not in body, (p, s_)
assert req(port, "/", host="evil.example")[0] == 403, "same Host guard"
ui_server.DIST_DIR = real_dist
ns.shutdown()
ok("/ serves ui_dist: index no-cache, hashed assets cached, 404 when unbuilt, no escapes; /next/ is gone")

# ---- boards: /api/planning, /api/delivery, /api/start, /api/cleanup and the post-poll hooks
import subprocess as sp  # noqa: E402

import dispatch  # noqa: E402
import ui_notify  # noqa: E402
import ui_poller  # noqa: E402
import ui_repos  # noqa: E402
import ui_settings  # noqa: E402

bd = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = bd
repo_dir = tempfile.mkdtemp()


def git(*a):
    return sp.run(
        ["git", "-C", repo_dir, "-c", "user.email=t@t", "-c", "user.name=t", *a], capture_output=True, check=True
    )


git("init", "-q")
git("commit", "-q", "--allow-empty", "-m", "init")
git("worktree", "add", "-q", os.path.join(repo_dir, ".worktrees", "3-x"), "-b", "issue-3-x")
with open(os.path.join(repo_dir, ".worktrees", "3-x", "dirty.txt"), "w") as f:
    f.write("x")
os.makedirs(os.path.join(repo_dir, "docs", "prds"))
with open(os.path.join(repo_dir, "docs", "prds", "x.md"), "w") as f:
    f.write("# PRD x\n\n**Status:** Draft · **Slug:** `x`\n")
dispatch.register_checkout("o/r", repo_dir)

_notes, _started = [], []
ui_notify.notify = lambda event, rec: _notes.append((event, rec))
ui_repos.start_session = lambda body: _started.append(body) or (201, {"id": f"S{len(_started)}"})


def _pr(n, draft=False, state="OPEN", merged=None):
    return {
        "number": n,
        "url": f"https://github.com/o/r/pull/{n}",
        "isDraft": draft,
        "state": state,
        "mergedAt": merged,
        "headRefName": f"issue-{n}",
        "statusCheckRollup": None,
    }


def _issue(n, labels, parent=None, blockers=(), prs=()):
    return {
        "number": n,
        "title": f"i{n}",
        "state": "OPEN",
        "labels": {"nodes": [{"name": x} for x in labels]},
        "parent": {"number": parent} if parent else None,
        "subIssues": {"nodes": []},
        "blockedBy": {"nodes": [{"number": b, "state": st} for b, st in blockers]},
        "closedByPullRequestsReferences": {"nodes": list(prs)},
    }


_resp = {}


def _gh(argv):
    return sp.CompletedProcess(argv, 0, json.dumps({"data": {"repository": _resp["r"]}}), "")


def _gql(issues, merged=(), open_prs=()):
    _resp["r"] = {
        "issues": {"nodes": issues},
        "mergedPrs": {"nodes": list(merged)},
        "openPrs": {"nodes": [dict(p, title="t") for p in open_prs]},
    }


ui_server.POLLER = ui_poller.Poller(runner=_gh, on_fresh=ui_server._on_fresh)
ui_server._watched.add("o/r")
bs, bport = start()
bme = f"127.0.0.1:{bport}"


def call(method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.1", bport, timeout=5)
    raw = json.dumps(body).encode() if body is not None else b""
    c.request(method, path, body=raw or None, headers={"Host": bme, "Content-Length": str(len(raw))})
    r = c.getresponse()
    out = r.read()
    c.close()
    return r.status, json.loads(out)


try:
    # unknown repo -> 400 everywhere; nothing is fetched for it
    for m, p, b in (
        ("GET", "/api/planning?repo=x/y", None),
        ("GET", "/api/delivery", None),
        ("POST", "/api/start", {"repo": "x/y", "skill": "implement-issue", "arg": "2"}),
        ("POST", "/api/cleanup", {"repo": "x/y", "issue": 3, "confirm": True}),
    ):
        assert call(m, p, b)[0] == 400, p
    ok("boards: unknown repo is 400")

    assert call("GET", "/api/notifications") == (200, {"latest": 0, "events": []})
    assert call("GET", "/api/notifications?after=0") == (200, {"latest": 0, "events": []})
    for bad in ("abc", "1.5", "", "-1"):
        st, body = call("GET", "/api/notifications?after=" + bad)
        assert st == 400 and "error" in body, bad
    ok("notifications: empty feed 200, bad after 400")
    st, _ = call("POST", "/api/settings/notify/channel", {"event": "done", "channel": "sms", "on": True})
    assert st == 400
    st, body = call("POST", "/api/settings/notify/channel", {"event": "done", "channel": "ntfy", "on": False})
    assert st == 200 and body["matrix"]["done"]["ntfy"] is False
    ok("settings: notify channel route")
    for bad in ({"channel": "browser"}, {"channel": "x"}, {}):
        st, body = call("POST", "/api/settings/notify/test", bad)
        assert st == 400 and "error" in body, bad
    ok("settings: notify test route rejects browser, unknown, missing")

    # before the first poll: stale, empty. Planning shows the PRD file.
    st, body = call("GET", "/api/planning?repo=o/r")
    assert st == 200 and body["stale"] and [c["slug"] for c in body["prds"]] == ["x"]
    st, body = call("GET", "/api/delivery?repo=o/r")
    assert st == 200 and body["stale"] and body["running"] == 0
    # a stale poll runs no hook
    ui_server.POLLER.runner = lambda argv: sp.CompletedProcess(argv, 1, "", "boom")
    ui_server.POLLER.poll("o/r")
    assert not _started and not _notes
    ui_server.POLLER.runner = _gh
    ok("boards: reads from memory, stale poll runs no hook")

    # poll 1: epic 1; 2 refined but blocked by 3; 3 has a draft PR 30. Nothing starts by itself any more.
    _gql(
        [
            _issue(1, ["epic"]),
            _issue(2, ["refined"], 1, [(3, "OPEN")]),
            _issue(3, ["refined"], 1, prs=[_pr(30, draft=True)]),
            _issue(4, ["refined"], 1),
        ],
        open_prs=[_pr(30, draft=True)],
    )
    ui_server.POLLER.poll("o/r")
    assert _started == [], _started
    st, body = call("GET", "/api/delivery?repo=o/r")
    assert not body["stale"] and any(lane["epic"] == 1 for lane in body["lanes"])
    ok("boards: a fresh poll starts no issue (dispatches do that)")

    # poll 2: PR 30 ready and merged-by-poll-3 later; first ready -> pr-ready notification + grind autostart
    ui_settings.save({"repos": {"o/r": {"auto_grind": True, "slack_channel": "C9"}}})
    _gql(
        [
            _issue(1, ["epic"]),
            _issue(2, ["refined"], 1, [(3, "OPEN")]),
            _issue(3, ["refined"], 1, prs=[_pr(30)]),
            _issue(4, ["refined"], 1, prs=[_pr(40, draft=True)]),
        ],
        open_prs=[_pr(30)],
    )
    _started.clear()
    ui_server.POLLER.poll("o/r")
    assert [e for e, _ in _notes] == ["pr-ready"], _notes
    assert [b["text"] for b in _started] == ["/pr-grind https://github.com/o/r/pull/30 --channel C9"], _started
    ok("boards: PR turned ready notifies once and autostarts grind")

    # poll 3: PR 30 merged -> 3 closed; 3's dirty worktree is flagged + notified
    _notes.clear()
    _started.clear()
    _gql(
        [
            _issue(1, ["epic"]),
            _issue(2, ["refined"], 1, [(3, "CLOSED")]),
            _issue(4, ["refined"], 1, prs=[_pr(40, draft=True)]),
        ],
        merged=[
            {
                "number": 30,
                "title": "m",
                "url": "u30",
                "mergedAt": "2999-01-01T00:00:00Z",
                "headRefName": "issue-3-x",
                "closingIssuesReferences": {"nodes": [{"number": 3, "parent": {"number": 1}}]},
            }
        ],
    )
    ui_server.POLLER.poll("o/r")
    assert _started == [], _started
    assert [e for e, _ in _notes] == ["needs-cleanup"], _notes
    ui_server.POLLER.poll("o/r")  # same merge again: not new, no second notification
    assert [e for e, _ in _notes] == ["needs-cleanup"]
    st, body = call("GET", "/api/delivery?repo=o/r")
    flagged = [c for lane in body["lanes"] for c in lane["cards"] if c["needs_cleanup"]]
    assert [c["n"] for c in flagged] == [3] and flagged[0]["needs_cleanup"]["uncommitted"] == ["dirty.txt"]
    ok("boards: merge flags needs-cleanup with one notification")

    # cleanup: 409 for an unmerged issue, 400 without confirm, removes the flagged worktree
    assert call("POST", "/api/cleanup", {"repo": "o/r", "issue": 4, "confirm": True})[0] == 409
    assert call("POST", "/api/cleanup", {"repo": "o/r", "issue": 3})[0] == 400
    st, body = call("POST", "/api/cleanup", {"repo": "o/r", "issue": 3, "confirm": True})
    assert st == 200 and body["removed"] and not os.path.exists(os.path.join(repo_dir, ".worktrees", "3-x"))
    body = call("GET", "/api/delivery?repo=o/r")[1]
    assert not [c for lane in body["lanes"] for c in lane["cards"] if c["needs_cleanup"]]
    ok("boards: cleanup 409/400/200 and the flag clears")

    # /api/start: headless, conflicts (open PR, blocked, live session), peer-review needs lenses
    ui_start._recent.clear()
    _started.clear()
    st, body = call(
        "POST", "/api/start", {"repo": "o/r", "skill": "create-tasks", "arg": "docs/prds/x.md", "via": "headless"}
    )
    assert st == 200 and body == {"session": "S1"} and _started[0]["text"] == "/create-tasks docs/prds/x.md"
    r4 = call("POST", "/api/start", {"repo": "o/r", "skill": "implement-issue", "arg": "4"})
    assert r4[0] == 409, r4  # open PR 40
    _gql([_issue(1, ["epic"]), _issue(5, ["refined"], 1, [(6, "OPEN")])])
    ui_server.POLLER.poll("o/r")
    assert call("POST", "/api/start", {"repo": "o/r", "skill": "implement-issue", "arg": "5"})[0] == 409  # blocked
    assert (
        call("POST", "/api/start", {"repo": "o/r", "skill": "pr-grind", "arg": "https://github.com/o/r/pull/9"})[0]
        == 200
    )
    assert call("POST", "/api/start", {"repo": "o/r", "skill": "peer-review", "arg": "docs/prds/x.md"})[0] == 400
    assert call("POST", "/api/start", {"repo": "o/r", "skill": "nope", "arg": "1"})[0] == 400
    ui_repos.start_session = lambda body: (409, {"error": "live"})
    assert call("POST", "/api/start", {"repo": "o/r", "skill": "refine-issues", "arg": "1"})[0] == 409
    ok("boards: /api/start shapes and 409s")

    # herdr starts from a card are gone: a dispatch runs issues in herdr tabs
    ui_start._recent.clear()
    st, body = call("POST", "/api/start", {"repo": "o/r", "skill": "refine-issues", "arg": "1", "via": "herdr"})
    assert st == 400 and "dispatch" in body["error"], body
    ok("boards: a herdr start is refused")

    # /api/prd: sha of the file as read; base_sha guards the save
    st, body = call("GET", "/api/prd?repo=o/r&path=docs/prds/x.md")
    prd_file = os.path.join(repo_dir, "docs", "prds", "x.md")
    assert st == 200 and body["sha"] == git("hash-object", prd_file).stdout.decode().strip(), body
    st, out = call(
        "POST", "/api/prd", {"repo": "o/r", "path": "docs/prds/x.md", "text": "# new\n", "base_sha": "0" * 40}
    )
    assert (st, out) == (409, {"error": "changed on disk"}), (st, out)
    assert (
        call("POST", "/api/prd", {"repo": "o/r", "path": "docs/prds/x.md", "text": "# new\n", "base_sha": 5})[0] == 400
    )
    with open(prd_file) as f:
        assert f.read().startswith("# PRD x"), "a refused save writes nothing"
    ok("prd: GET carries sha, POST base_sha mismatch -> 409 changed on disk")

    # /api/grind/skip-ci and /stop
    sent_prompts = []
    ui_server.ui_runner.send_prompt = lambda sid, text: sent_prompts.append((sid, text)) or "sent"
    for action in ("skip-ci", "stop"):
        p = f"/api/grind/{action}"
        assert call("POST", p, {"repo": "x/y", "pr": 9})[0] == 400
        assert call("POST", p, {"repo": "o/r", "pr": "9"})[0] == 400
        assert call("POST", p, {"repo": "o/r", "pr": True})[0] == 400
        assert call("POST", p, {"repo": "o/r", "pr": 9})[0] == 409, "no loop"
    os.makedirs(os.path.join(bd, "pr-grind"), exist_ok=True)
    thread = "https://x.slack.com/archives/C1/p9"
    state = os.path.join(bd, "pr-grind", "o-r-9.md")
    with open(state, "w") as f:
        f.write(
            f"owner: o\nrepo: r\nnumber: 9\nthread: {thread}\npaused: 2026-10-08T00:00:00Z — CI red\n\n## Round 1\n"
        )
    assert call("POST", "/api/grind/skip-ci", {"repo": "o/r", "pr": 9})[0] == 409, "paused but no session to reply to"
    gs = ui_sessions.create(f"/pr-grind {thread}", repo_dir)
    ui_sessions.update(gs["id"], status="done", session_id="c-1")
    assert call("POST", "/api/grind/skip-ci", {"repo": "o/r", "pr": 9}) == (200, {"state": "running"})
    assert sent_prompts and sent_prompts[0][0] == gs["id"] and "Skip CI" in sent_prompts[0][1]
    assert call("POST", "/api/grind/skip-ci", {"repo": "o/r", "pr": 9})[0] == 409, "not paused any more"
    assert call("POST", "/api/grind/stop", {"repo": "o/r", "pr": 9}) == (200, {"ok": True, "state": "done"})
    assert "stopped from the UI" in open(state).read() and ui_grind.index()["pr"][("o", "r", 9)]["state"] == "done"
    ok("grind: skip-ci and stop validate, 409 without a loop / when not paused, stop marks it done")

    # a merge re-polls before answering, so the board the UI refetches already shows it merged
    import ui_actions

    _gql([_issue(5, ["refined"], prs=[_pr(55)])])
    ui_server.POLLER.poll("o/r")
    real_merge = ui_actions.merge

    def fake_merge(*a):
        _gql([_issue(5, ["refined"], prs=[_pr(55, state="MERGED", merged="2026-10-21T00:00:00Z")])])
        return {"ok": True}

    ui_actions.merge = fake_merge
    try:
        assert call("POST", "/api/pulls/o/r/55/merge", {}) == (200, {"ok": True})
    finally:
        ui_actions.merge = real_merge
    pr55 = ui_server.POLLER.snapshot("o/r")["data"]["issues"][0]["prs"][0]
    assert pr55["state"] == "MERGED", pr55
    ok("merge: re-polls the repo before answering")

    # watch set: opened in the last 7 days (any ?repo= request) or live session; GitHub remotes only
    other = tempfile.mkdtemp()
    local = tempfile.mkdtemp()
    dispatch.register_checkout("o/q", other)
    dispatch.register_checkout("local/idea", local)
    assert "o/q" not in ui_server._watched_copy()
    ui_sessions.update(
        ui_sessions.create("/implement-issue 3", other, {"owner": "o", "repo": "q", "issue": 3})["id"], status="running"
    )
    assert "o/q" in ui_server._watched_copy(), "a live session puts its repo in the set"
    for s_ in ui_sessions.list_sessions():
        ui_sessions.update(s_["id"], status="done")
    assert "o/q" not in ui_server._watched_copy()
    call("GET", "/api/delivery?repo=o/q")
    assert "o/q" in ui_watch.recent() and "o/q" in ui_server._watched_copy(), "opened now"
    dispatch.register_checkout("o/z", tempfile.mkdtemp())
    for p_ in ("/api/repos?repo=o/z", "/api/sessions?repo=o/z", "/api/settings?repo=o/z"):
        call("GET", p_)
    assert "o/z" not in ui_watch.recent(), "only planning, delivery and inbox?repo= count as looking at a repo"
    ui_watch.touch("local/idea")
    assert "local/idea" not in ui_server._watched_copy(), "no GitHub remote: not watched"
    with open(os.path.join(bd, "ui_opened.json")) as f:
        opened = json.load(f)
    old = time.time() - 8 * 86400
    opened["o/q"] = old
    with open(os.path.join(bd, "ui_opened.json"), "w") as f:
        json.dump(opened, f)
    assert "o/q" not in ui_server._watched_copy(), "opened 8 days ago: out"
    ok("watch set: opened in 7 days or live, GitHub repos only, persisted in the data dir")

    # hot: viewed in the last VIEW_SECONDS (every watched repo while the global Inbox is open) or live
    ui_server._seen.clear()
    assert ui_server._hot() == set(), "nobody looking: every repo is cold"
    call("GET", "/api/delivery?repo=o/r")
    assert ui_server._hot() == {"o/r"}
    ui_server._seen["o/r"] = time.time() - ui_server.VIEW_SECONDS
    assert ui_server._hot() == set()
    ui_server._seen["*"] = time.time()
    assert ui_server._hot() == set(ui_server._watched_copy()) and "o/r" in ui_server._hot()
    ui_server._seen.clear()
    ok("hot: viewed repos and live sessions poll on the normal cadence")

    # /api/inbox and gh on /api/sessions
    ui_gh.status = lambda *a, **k: {"ok": True, "login": "me", "error": None}
    ready = dict(_pr(60), statusCheckRollup={"state": "SUCCESS"}, reviewDecision="APPROVED")
    _gql([_issue(1, ["epic"])], open_prs=[ready])
    ui_server.POLLER.poll("o/r")
    st, body = call("GET", "/api/inbox?repo=o/r")
    assert st == 200 and set(body) == {"items", "afk", "gh", "stale"} and body["gh"]["login"] == "me", body
    assert not [i for i in body["items"] if i["type"] == "pr_ready"], "o/r grinds: no Merge before the grind is done"
    ui_settings.save({"repos": {"o/r": {"auto_grind": False, "slack_channel": "C9"}}})
    st, body = call("GET", "/api/inbox?repo=o/r")
    assert [i["key"] for i in body["items"] if i["type"] == "pr_ready"] == ["pr_ready:o/r#60"] and body["stale"] == []
    assert body["afk"]["active"] is False
    ui_server.POLLER._state.pop("o/q", None)  # the first look at o/q polled it (the fake gh answers o/r's data)
    live_q = ui_sessions.create("/implement-issue 3", other, {"owner": "o", "repo": "q", "issue": 3})
    ui_sessions.update(live_q["id"], status="running")  # o/q is watched through its session, not yet polled
    st, body = call("GET", "/api/inbox")
    assert st == 200 and any(i["type"] == "pr_ready" for i in body["items"]) and "o/q" in body["stale"], body
    assert call("GET", "/api/inbox?repo=x/y")[0] == 400
    ui_gh.status = lambda *a, **k: {"ok": False, "login": None, "error": "not logged in"}
    assert call("GET", "/api/inbox")[1]["items"][0]["type"] == "gh_auth"
    assert call("GET", "/api/sessions")[1]["gh"] == {"ok": False, "login": None, "error": "not logged in"}
    ok("inbox: items, afk, gh, stale; ?repo= filter and 400; gh on /api/sessions")
    assert call("POST", "/api/sessions/nope/start-now")[0] == 404
    st, body = call("POST", f"/api/sessions/{live_q['id']}/start-now")
    assert st == 409 and body == {"error": "session is not queued"}, (st, body)
    ok("start-now: 404 unknown, 409 when the session is not queued")
finally:
    bs.shutdown()
    os.environ["CLAUDE_PLUGIN_DATA"] = data_dir

print(f"{passed} checks passed")
