#!/usr/bin/env python3
"""Self-check for run-engine/ui_repos.py + GET /api/repos + POST /api/sessions (issue #116).

`python3 test_ui_repos.py` — exit 0 = green. Assert-based, no framework.
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

data_dir = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = data_dir
ORIG_PATH = os.environ.get("PATH", "")

import ui_board
import ui_repos
import ui_runner
import ui_server
import ui_sessions

passed = 0


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


def boom(*_a, **_k):
    raise AssertionError("fetch_title must not be called")


def git_repo(parent=None):
    d = os.path.realpath(tempfile.mkdtemp(dir=parent))
    subprocess.run(["git", "init", "-q", d], check=True)
    return d


def write(path, text):
    with open(path, "w") as f:
        f.write(text)


tmp = os.path.realpath(tempfile.mkdtemp())
REPO_A = git_repo()
REPO_B = git_repo()
PLAIN = os.path.realpath(tempfile.mkdtemp())
CHECKOUTS = os.path.join(data_dir, "checkouts.json")
PROJECTS = os.path.join(tmp, "projects.json")
ui_board.PROJECTS_PATH = PROJECTS


def set_registry(checkouts, projects=None):
    write(CHECKOUTS, checkouts if isinstance(checkouts, str) else json.dumps(checkouts))
    if projects is not None:
        write(PROJECTS, projects if isinstance(projects, str) else json.dumps(projects))


def reset_sessions():
    shutil.rmtree(ui_sessions.sessions_dir(), ignore_errors=True)


set_registry({"o/r": REPO_A, "z/last": REPO_B, "a/first": REPO_A},
             {"o/r": "Orange Repo", "z/last": "Zed", "only/proj": "Only In Projects"})

srv = ui_server._Server(("127.0.0.1", 0), ui_server._Handler, [], boom)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
HOST = f"127.0.0.1:{port}"


def req(path, method="GET", body=None, host=HOST, origin=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    c.putheader("Host", host)
    if origin is not None:
        c.putheader("Origin", origin)
    for k, v in (headers or {}).items():
        c.putheader(k, v)
    if body is not None:
        c.putheader("Content-Type", "application/json")
        c.putheader("Content-Length", str(len(body)))
    c.endheaders()
    if body is not None:
        c.send(body)
    r = c.getresponse()
    data = r.read()
    h = r.getheaders()
    c.close()
    return r.status, data, h


calls = []


def fake_start(command_text, cwd, link=None):
    calls.append((command_text, cwd, link))
    return ui_sessions.create(command_text, cwd, link)


def post(obj, raw=None, **kw):
    """POST /api/sessions with the runner mocked. Returns (status, parsed-json-or-bytes)."""
    calls.clear()
    body = raw if raw is not None else json.dumps(obj).encode()
    with mock.patch.object(ui_runner, "start", fake_start):
        s, data, h = req("/api/sessions", "POST", body, **kw)
    try:
        return s, json.loads(data)
    except ValueError:
        return s, data


def err(payload):
    assert isinstance(payload, dict) and isinstance(payload.get("error"), str), payload
    return payload["error"]


def rp(p):
    return os.path.realpath(p)


try:
    # ------------------------------------------------------------- GET /api/repos
    s, data, h = req("/api/repos")
    assert s == 200, (s, data)
    assert json.loads(data) == {"repos": [
        {"slug": "a/first", "name": "a/first", "path": REPO_A},
        {"slug": "o/r", "name": "Orange Repo", "path": REPO_A},
        {"slug": "z/last", "name": "Zed", "path": REPO_B},
    ]}, data
    ok("GET /api/repos sorted by slug, name from projects.json, fallback slug, projects-only not listed")

    for label, co in [("missing", None), ("empty", ""), ("non-json", "{nope")]:
        if co is None:
            os.unlink(CHECKOUTS)
        else:
            set_registry(co)
        s, data, _ = req("/api/repos")
        assert s == 200 and json.loads(data) == {"repos": []}, (label, s, data)
    ok("checkouts.json missing/empty/non-JSON -> {repos: []}")

    set_registry({"o/r": REPO_A, "bad/val": 5, "bad/none": None})
    s, data, _ = req("/api/repos")
    assert [r["slug"] for r in json.loads(data)["repos"]] == ["o/r"], data
    ok("non-string checkout value skipped")

    set_registry({"o/r": REPO_A}, "{not json")
    s, data, _ = req("/api/repos")
    assert s == 200 and json.loads(data)["repos"] == [{"slug": "o/r", "name": "o/r", "path": REPO_A}], (s, data)
    ok("malformed projects.json -> no 500, name == slug")
    set_registry({"o/r": REPO_A, "z/last": REPO_B}, {"o/r": "Orange Repo"})

    # ------------------------------------------------------------ build_command
    assert ui_repos.build_command("run-issue", "116") == "/run-issue 116"
    assert ui_repos.build_command("pr-grind", "") == "/pr-grind"
    assert ui_repos.MAX_PROMPT_CHARS == 32000
    ok("build_command units, MAX_PROMPT_CHARS")

    # ------------------------------------------------------------ normal POSTs
    reset_sessions()
    s, p = post({"repo": "o/r", "command": "run-issue", "args": "7"})
    assert s == 201, (s, p)
    assert calls == [("/run-issue 7", REPO_A, {"owner": "o", "repo": "r", "issue": 7})] or (
        len(calls) == 1 and calls[0][0] == "/run-issue 7" and rp(calls[0][1]) == rp(REPO_A)
        and calls[0][2] == {"owner": "o", "repo": "r", "issue": 7}), calls
    assert p == ui_server._public(ui_sessions.load(p["id"])), p
    ok("run-issue o/r 7 -> 201 public record; start gets command, checkout cwd, link")

    reset_sessions()
    for text in ("explain this repo", "/prd foo", "  spaced \n text  "):
        s, p = post({"repo": "o/r", "text": text})
        assert s == 201 and calls[0][0] == text, (text, s, p, calls)
    ok("custom text passed byte-for-byte")

    reset_sessions()
    sub = os.path.join(REPO_A, "sub")
    os.mkdir(sub)
    for path in (REPO_B, sub):
        s, p = post({"repo": path, "text": "hi"})
        assert s == 201, (path, s, p)
        assert rp(calls[0][1]) == (rp(REPO_B) if path == REPO_B else rp(REPO_A)), calls
    ok("manual absolute git path accepted without registry entry; subdir -> toplevel")

    # ------------------------------------------------------------ end to end
    reset_sessions()
    fake_dir = tempfile.mkdtemp()
    bindir = os.path.join(fake_dir, "bin")
    os.mkdir(bindir)
    exe = os.path.join(bindir, "claude")
    write(exe, '#!/bin/sh\nif [ "$1" = "auth" ]; then echo \'{"loggedIn": true}\'; exit 0; fi\n'
               'pwd > "$FAKE_DIR/pwd"\nprintf \'%s\\n\' "$@" > "$FAKE_DIR/argv"\n'
               'echo \'{"type":"result","is_error":false,"total_cost_usd":0}\'\n')
    os.chmod(exe, 0o755)
    os.environ["FAKE_DIR"] = fake_dir
    os.environ["PATH"] = bindir + os.pathsep + ORIG_PATH
    try:
        for path in ("o/r", sub):
            pf = os.path.join(fake_dir, "pwd")
            if os.path.exists(pf):
                os.unlink(pf)
            s, data, _ = req("/api/sessions", "POST", json.dumps({"repo": path, "text": "go"}).encode())
            assert s == 201, (s, data)
            for _ in range(100):
                if os.path.exists(pf) and open(pf).read().strip():
                    break
                time.sleep(0.1)
            assert rp(open(pf).read().strip()) == rp(REPO_A), open(pf).read()
            time.sleep(0.5)
    finally:
        os.environ["PATH"] = ORIG_PATH
    ok("end-to-end: fake claude runs in realpath(checkout); subdir -> repo toplevel")

    # ------------------------------------------------------------ duplicates
    def live(cmd, status="starting", issue=7, owner="o", repo="r"):
        reset_sessions()
        rec = ui_sessions.create(cmd, REPO_A, link={"owner": owner, "repo": repo, "issue": issue})
        if status != "starting":
            ui_sessions.update(rec["id"], status=status)
        return rec

    for status in ("starting", "running"):
        rec = live("/run-issue 7", status)
        s, p = post({"repo": "o/r", "command": "run-issue", "args": "7"})
        assert s == 409 and calls == [], (status, s, p, calls)
        assert "o/r#7" in err(p), p
        text = json.dumps(p)
        assert rec["id"] in text and "/api/sessions/" + rec["id"] in text, p
        assert p.get("link") == {"owner": "o", "repo": "r", "issue": 7}, p
    ok("live run-issue -> 409 naming o/r#7, existing id, link, href; start not called")

    rec = live("/pr-grind", "running")
    s, p = post({"repo": "o/r", "command": "pr-grind", "issue": 7})
    assert s == 409 and calls == [], (s, p)
    ok("pr-grind with explicit issue vs live pr-grind -> 409")

    for text in ("/run-issue 7", "/ai-workflow:run-issue 7"):
        live("/run-issue 7")
        s, p = post({"repo": "o/r", "text": text})
        assert s == 409 and calls == [], (text, s, p)
    ok("custom text spelling a run-issue command -> 409")

    for text in ("/run-issue\n7", "/run-issue\t7"):
        live("/run-issue 7")
        s, p = post({"repo": "o/r", "text": text})
        assert s == 409 and calls == [], (repr(text), s, p)
    ok("whitespace-variant custom text (newline/tab) -> 409, dup-check not bypassed")

    reset_sessions()
    calls.clear()
    s, data, _ = req("/api/sessions", "POST", json.dumps(
        {"repo": "o/r", "command": "run-issue", "args": "7 \u0000"}).encode())
    assert s == 400, (s, data)
    assert not [r for r in ui_sessions.list_sessions()
                if r.get("status") in ("starting", "running")], ui_sessions.list_sessions()
    s, p = post({"repo": "o/r", "command": "run-issue", "args": "7"})
    assert s == 201, (s, p)
    ok("NUL in args -> 400, no stuck record, next run-issue 7 -> 201")

    reset_sessions()
    dead = subprocess.Popen(["true"], start_new_session=True)
    dead.wait()
    rec = ui_sessions.create("/run-issue 7", REPO_A, link={"owner": "o", "repo": "r", "issue": 7})
    ui_sessions.update(rec["id"], status="running", pid=dead.pid)
    s, p = post({"repo": "o/r", "command": "run-issue", "args": "7"})
    assert s == 201, (s, p)
    ok("stale running record with gone process group does not block")

    live("/run-issue 7")
    s, p = post({"repo": "O/R", "command": "run-issue", "args": "7"})
    assert s == 409, (s, p)
    ok("owner/repo compare is case-insensitive")

    for status in ("done", "failed", "stopped"):
        live("/run-issue 7", status)
        s, p = post({"repo": "o/r", "command": "run-issue", "args": "7"})
        assert s == 201, (status, s, p)
    ok("terminal records never block")

    live("/run-issue 7")
    for label, body in [
        ("other family", {"repo": "o/r", "command": "pr-grind", "issue": 7}),
        ("other issue", {"repo": "o/r", "command": "run-issue", "args": "8"}),
        ("other repo", {"repo": "z/last", "command": "run-issue", "args": "7"}),
    ]:
        s, p = post(body)
        assert s == 201, (label, s, p)
    ok("different family/issue/repo -> 201")

    # ------------------------------------------------------------ concurrency
    reset_sessions()
    calls.clear()

    def slow_start(command_text, cwd, link=None):
        time.sleep(0.3)
        return ui_sessions.create(command_text, cwd, link)

    results = []

    def go():
        s, data, _ = req("/api/sessions", "POST", json.dumps(
            {"repo": "o/r", "command": "run-issue", "args": "7"}).encode())
        results.append(s)

    with mock.patch.object(ui_runner, "start", slow_start):
        ts = [threading.Thread(target=go) for _ in range(2)]
        [t.start() for t in ts]
        [t.join() for t in ts]
    assert sorted(results) == [201, 409], results
    ok("two simultaneous run-issue o/r#7 -> exactly one 201 and one 409")

    # ------------------------------------------------------------ validation
    reset_sessions()
    good = {"repo": "o/r", "text": "hi"}
    bad_bodies = [
        ("empty body", None, b""),
        ("array", None, b"[1]"),
        ("string", None, b'"x"'),
        ("number", None, b"5"),
        ("invalid json", None, b"{nope"),
        ("repo missing", {"text": "hi"}, None),
        ("repo empty", {"repo": "", "text": "hi"}, None),
        ("repo non-str", {"repo": 5, "text": "hi"}, None),
        ("text empty", {"repo": "o/r", "text": ""}, None),
        ("text whitespace", {"repo": "o/r", "text": " \n\t"}, None),
        ("args non-str", {"repo": "o/r", "command": "run-issue", "args": 7}, None),
        ("issue 0", {"repo": "o/r", "command": "pr-grind", "issue": 0}, None),
        ("issue -1", {"repo": "o/r", "command": "pr-grind", "issue": -1}, None),
        ("issue True", {"repo": "o/r", "command": "pr-grind", "issue": True}, None),
        ("issue str", {"repo": "o/r", "command": "pr-grind", "issue": "7"}, None),
        ("issue float", {"repo": "o/r", "command": "pr-grind", "issue": 7.5}, None),
        ("unknown command", {"repo": "o/r", "command": "rm-rf"}, None),
        ("command non-str", {"repo": "o/r", "command": 5}, None),
        ("both command+text", {"repo": "o/r", "command": "pr-grind", "text": "x"}, None),
        ("neither command+text", {"repo": "o/r"}, None),
        ("NUL byte", {"repo": "o/r", "text": "a\x00b"}, None),
        ("text starts with -", {"repo": "o/r", "text": "--help"}, None),
    ]
    for label, obj, raw in bad_bodies:
        s, p = post(obj, raw=raw)
        assert s == 400 and calls == [], (label, s, p, calls)
        err(p)
    ok("malformed / invalid bodies -> 400, start not called")

    s, p = post({"repo": "o/r", "text": "x" * 32000})
    assert s == 201, (s, p)
    s, p = post({"repo": "o/r", "text": "x" * 32001})
    assert s == 400 and "prompt too long" in err(p) and calls == [], (s, p)
    ok("text 32000 accepted, 32001 -> 400 'prompt too long'")

    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.putrequest("POST", "/api/sessions", skip_host=True, skip_accept_encoding=True)
    c.putheader("Host", HOST)
    c.putheader("Content-Length", "65537")
    c.endheaders()
    assert c.getresponse().status == 413
    c.close()
    ok("Content-Length > 65536 -> 413 without reading the body")

    for args in ("#7", "7 --lean", "https://github.com/o/r/issues/7"):
        reset_sessions()
        s, p = post({"repo": "o/r", "command": "run-issue", "args": args})
        assert s == 201 and calls[0][2]["issue"] == 7, (args, s, p, calls)
    ok("run-issue args '#7' / '7 --lean' / issue URL parse to issue 7")

    # repo validation
    link = os.path.join(tmp, "link-to-plain")
    os.symlink(PLAIN, link)
    link_ok = os.path.join(tmp, "link-to-repo")
    os.symlink(REPO_B, link_ok)
    stale = os.path.join(tmp, "gone")
    set_registry({"o/r": REPO_A, "stale/co": stale})
    for label, repo in [
        ("nonexistent", os.path.join(tmp, "nope")),
        ("plain dir", PLAIN),
        ("relative", "some/relative"),
        ("dotdot", os.path.join(REPO_A, "sub", "..")),
        ("dotdot to other repo", REPO_A + "/../" + os.path.basename(REPO_B)),
        ("symlink to non-repo", link),
        ("unknown slug", "no/such"),
        ("stale checkout", "stale/co"),
    ]:
        s, p = post({"repo": repo, "text": "hi"})
        assert s == 400 and calls == [], (label, s, p, calls)
        assert "not a git repository" in err(p), (label, p)
    s, p = post({"repo": PLAIN, "text": "hi"})
    assert err(p) == f"not a git repository: {PLAIN}", p
    s, p = post({"repo": link_ok, "text": "hi"})
    assert s == 201 and rp(calls[0][1]) == rp(REPO_B), (s, p)
    ok("repo validation 400 'not a git repository: <path>'; symlink to real repo accepted")

    # runner failure
    def failing(*_a, **_k):
        raise ui_runner.RunnerError("claude CLI not found on PATH")

    with mock.patch.object(ui_runner, "start", failing):
        s, data, _ = req("/api/sessions", "POST", json.dumps(good).encode())
    assert s == 502 and "claude CLI not found" in err(json.loads(data)), (s, data)
    ok("RunnerError -> 502 {error}")

    # ------------------------------------------------------------ guard / verbs
    body = json.dumps(good).encode()
    for path, method, b in [("/api/repos", "GET", None), ("/api/sessions", "POST", body)]:
        calls.clear()
        with mock.patch.object(ui_runner, "start", fake_start):
            s, _, h = req(path, method, b, host="evil.example:80")
        assert s == 403 and not calls, (path, s)
        assert not any(k.lower().startswith("access-control-") for k, _ in h)
    calls.clear()
    with mock.patch.object(ui_runner, "start", fake_start):
        s, _, h = req("/api/sessions", "POST", body, origin="http://evil.example")
    assert s == 403 and not calls
    assert not any(k.lower().startswith("access-control-") for k, _ in h)
    ok("bad Host / cross-site Origin -> 403, no CORS, start not called")

    s, _, h = req("/board.json", "POST", b"{}")
    assert s == 405 and dict(h).get("Allow") == "GET", (s, h)
    for m in ("PUT", "DELETE"):
        s, _, h = req("/api/sessions", m)
        assert s == 405, (m, s)
    ok("POST /board.json still 405 Allow: GET; PUT/DELETE /api/sessions -> 405")
finally:
    srv.shutdown()
    srv.server_close()
    shutil.rmtree(data_dir, ignore_errors=True)

print(f"{passed} checks passed")
