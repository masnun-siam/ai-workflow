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

import ui_autopilot  # noqa: E402
import ui_server  # noqa: E402

passed = 0


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

# ---- boards: /api/planning, /api/delivery, /api/start, /api/autopilot, /api/cleanup and the post-poll hooks
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
ui_settings.set_autopilot("o/r", 1, True)

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
        ("POST", "/api/autopilot", {"repo": "x/y", "epic": 1, "on": True}),
        ("POST", "/api/cleanup", {"repo": "x/y", "issue": 3, "confirm": True}),
    ):
        assert call(m, p, b)[0] == 400, p
    ok("boards: unknown repo is 400")

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

    # poll 1: epic 1 on autopilot; 2 refined but blocked by 3; 3 has a draft PR 30
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
    assert [b["text"] for b in _started] == ["/implement-issue 4"], _started  # 3 has a PR, 2 is blocked
    st, body = call("GET", "/api/delivery?repo=o/r")
    assert not body["stale"] and any(lane["epic"] == 1 and lane["autopilot"] for lane in body["lanes"])
    ok("boards: autopilot tick after a fresh poll")

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

    # poll 3: PR 30 merged -> 3 closed, 2 unblocked: autopilot starts 2; 3's dirty worktree is flagged + notified
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
    assert [b["text"] for b in _started] == ["/implement-issue 2"], _started
    assert [e for e, _ in _notes] == ["needs-cleanup"], _notes
    ui_server.POLLER.poll("o/r")  # same merge again: not new, no second notification
    assert [e for e, _ in _notes] == ["needs-cleanup"]
    st, body = call("GET", "/api/delivery?repo=o/r")
    flagged = [c for lane in body["lanes"] for c in lane["cards"] if c["needs_cleanup"]]
    assert [c["n"] for c in flagged] == [3] and flagged[0]["needs_cleanup"]["uncommitted"] == ["dirty.txt"]
    ok("boards: merge unblocks and starts; needs-cleanup flag + one notification")

    # cleanup: 409 for an unmerged issue, 400 without confirm, removes the flagged worktree
    assert call("POST", "/api/cleanup", {"repo": "o/r", "issue": 4, "confirm": True})[0] == 409
    assert call("POST", "/api/cleanup", {"repo": "o/r", "issue": 3})[0] == 400
    st, body = call("POST", "/api/cleanup", {"repo": "o/r", "issue": 3, "confirm": True})
    assert st == 200 and body["removed"] and not os.path.exists(os.path.join(repo_dir, ".worktrees", "3-x"))
    body = call("GET", "/api/delivery?repo=o/r")[1]
    assert not [c for lane in body["lanes"] for c in lane["cards"] if c["needs_cleanup"]]
    ok("boards: cleanup 409/400/200 and the flag clears")

    # /api/autopilot
    assert call("POST", "/api/autopilot", {"repo": "o/r", "epic": 4, "on": True})[0] == 400  # not an epic
    assert call("POST", "/api/autopilot", {"repo": "o/r", "epic": 1, "on": "yes"})[0] == 400
    assert call("POST", "/api/autopilot", {"repo": "o/r", "epic": 1, "on": False}) == (
        200,
        {"repo": "o/r", "epic": 1, "on": False},
    )
    assert ui_settings.repo_settings("o/r")["autopilot"] == []
    assert call("POST", "/api/autopilot", {"repo": "o/r", "epic": 1, "on": True})[0] == 200
    ok("boards: autopilot toggle")

    # /api/start: headless, conflicts (open PR, blocked, live session), peer-review needs lenses
    ui_autopilot._recent.clear()
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
finally:
    bs.shutdown()
    os.environ["CLAUDE_PLUGIN_DATA"] = data_dir

print(f"{passed} checks passed")
