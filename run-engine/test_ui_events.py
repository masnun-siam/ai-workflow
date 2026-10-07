#!/usr/bin/env python3
"""Self-check for run-engine/ui_events.py + the /api/sessions* routes (issue #114).

`python3 test_ui_events.py` — exit 0 = green. Assert-based, no framework.
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

data_dir = tempfile.mkdtemp()
old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
os.environ["CLAUDE_PLUGIN_DATA"] = data_dir

import ui_events
import ui_server
import ui_sessions

passed = 0


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


def boom(*_a, **_k):
    raise AssertionError("fetch_title must not be called")


INIT = {"type": "system", "subtype": "init", "session_id": "abc"}
A1 = {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}
A2 = {"type": "assistant", "message": {"content": [
    {"type": "text", "text": "running"},
    {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]}}
UR = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}]}}
RES = {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.0421, "result": "done"}
FIXTURE = "".join(json.dumps(o) + "\n" for o in (INIT, A1, A2, UR, RES))
EXPECTED = [
    {"kind": "text", "text": "hi"},
    {"kind": "text", "text": "running"},
    {"kind": "tool", "name": "Bash", "input": {"command": "ls"}},
    {"kind": "result", "cost": 0.0421, "is_error": False, "text": "done"},
]


def pl(obj):
    return ui_events.parse_line(json.dumps(obj))


# ---------------------------------------------------------------- parse_line
assert pl(A1) == [{"kind": "text", "text": "hi"}]
ok("parse assistant text")
assert pl(A2) == EXPECTED[1:3]
ok("parse text + tool_use")
assert pl(RES) == [EXPECTED[3]]
ok("parse result")
assert pl({**RES, "is_error": True})[0]["is_error"] is True
ok("result is_error true")
assert ui_events.parse_line(json.dumps(A1).encode()) == [{"kind": "text", "text": "hi"}]
ok("parse bytes input")
for label, o in [
    ("system/init", INIT), ("user tool_result", UR), ("unknown type", {"type": "zzz"}),
    ("thinking block", {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "x"}]}}),
]:
    assert pl(o) == [], label
ok("ignored event types -> []")
for label, raw in [
    ("invalid json", "{nope"), ("array", "[1]"), ("number", "5"), ("string", '"s"'),
    ("bad utf8", b"\xff\xfe{\n"), ("blank", ""), ("blank nl", "\n"),
]:
    assert ui_events.parse_line(raw) == [], label
for label, o in [
    ("string message", {"type": "assistant", "message": "x"}),
    ("non-list content", {"type": "assistant", "message": {"content": "x"}}),
    ("non-str text", {"type": "assistant", "message": {"content": [{"type": "text", "text": 5}]}}),
    ("tool_use no name", {"type": "assistant", "message": {"content": [{"type": "tool_use", "input": {}}]}}),
]:
    assert pl(o) == [], label
ok("malformed lines -> [] without raising")
for v in (None, "0.1", True):
    r = pl({**RES, "total_cost_usd": v})
    assert len(r) == 1 and r[0]["cost"] is None, v
r = pl({k: v for k, v in RES.items() if k != "total_cost_usd"})
assert r[0]["cost"] is None
ok("result cost missing/str/bool -> None")

# ------------------------------------------------------------------ read_from
tmp = tempfile.mkdtemp()
path = os.path.join(tmp, "s.jsonl")
with open(path, "w") as f:
    f.write(FIXTURE)
size = os.path.getsize(path)
ev, off = ui_events.read_from(path, 0)
assert ev == EXPECTED and off == size
ok("read_from 0 -> all events, offset == size")
first_line = len((json.dumps(INIT) + "\n" + json.dumps(A1) + "\n").encode())
ev, mid = ui_events.read_from(path, first_line)
assert ev == EXPECTED[1:] and mid == size
ev1, o1 = ui_events.read_from(path, 0)
ev2, o2 = ui_events.read_from(path, o1)
assert ev2 == [] and o2 == o1
ok("mid-file offset; chaining never duplicates")
assert ui_events.read_from(path, size) == ([], size)
ok("offset == size -> ([], size)")
for big in (size + 100, 10**30):
    assert ui_events.read_from(path, big) == ([], big)
ok("offset past EOF -> ([], same), no OverflowError")

part = os.path.join(tmp, "p.jsonl")
line = json.dumps(A1) + "\n"
with open(part, "w") as f:
    f.write(FIXTURE + line[:-8])
ev, off = ui_events.read_from(part, 0)
assert ev == EXPECTED and off == size
with open(part, "a") as f:
    f.write(line[-8:])
ev, off2 = ui_events.read_from(part, off)
assert ev == [{"kind": "text", "text": "hi"}] and off2 == size + len(line)
assert ui_events.read_from(part, off2) == ([], off2)
ok("partial last line held back, returned exactly once")

big = os.path.join(tmp, "b.jsonl")
garbage = "garbage-not-json\n" * 20000
with open(big, "w") as f:
    f.write(garbage + json.dumps(A1) + "\n")
ev, off = ui_events.read_from(big, len(garbage))
assert ev == [{"kind": "text", "text": "hi"}] and off == os.path.getsize(big)
ok("reads only from offset")

empty = os.path.join(tmp, "e.jsonl")
open(empty, "w").close()
assert ui_events.read_from(empty, 0) == ([], 0)
assert ui_events.read_from(os.path.join(tmp, "missing"), 7) == ([], 7)
ok("empty / missing file")
shutil.rmtree(tmp, ignore_errors=True)

# ----------------------------------------------------------------------- HTTP
srv = ui_server._Server(("127.0.0.1", 0), ui_server._Handler, (), boom)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
HOST = f"127.0.0.1:{port}"
ALLOWED = {"id", "command", "repo", "link", "session_id", "outcome", "cost",
           "started_at", "ended_at", "waiting", "pending_question", "error"}


def req(path, method="GET", host=HOST, origin=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    c.putheader("Host", host)
    if origin is not None:
        c.putheader("Origin", origin)
    c.endheaders()
    r = c.getresponse()
    body = r.read()
    h = r.getheaders()
    c.close()
    return r.status, r, body, h


def no_cors(h):
    return not any(k.lower().startswith("access-control-") for k, _ in h)


def jget(path):
    s, _, b, _ = req(path)
    assert s == 200, (path, s, b)
    return json.loads(b)


try:
    assert jget("/api/sessions") == {"sessions": []}
    ok("no sessions dir -> empty list")

    old = ui_sessions.create("/run-issue", "r/old")
    new = ui_sessions.create("/run-issue", "r/new", link="http://x")
    ui_sessions.update(old["id"], status="done", cost=0.0421, pid=4242, token="SECRET-META",
                       ended_at="2026-01-01T00:00:00+00:00")
    ui_sessions.update(new["id"], status="waiting", pid=999,
                       pending_question={"q": "ok?"}, session_id="sess-1")
    with open(os.path.join(data_dir, "ui.json"), "w") as f:
        json.dump({"ntfy": {"token": "SECRET-TOKEN-XYZ"}}, f)
    os.makedirs(os.path.join(ui_sessions.sessions_dir(), "20200101T000000000000Z-00000000"))
    with open(os.path.join(ui_sessions.sessions_dir(), "20200101T000000000000Z-00000000", "meta.json"), "w") as f:
        f.write("{corrupt")
    corrupt_id = "20200101T000000000000Z-00000000"
    sp = os.path.join(ui_sessions.session_dir(old["id"]), "stream.jsonl")
    with open(sp, "w") as f:
        f.write(FIXTURE)

    s, r, b, _ = req("/api/sessions", host=HOST)
    assert s == 200 and r.getheader("Content-Type", "").startswith("application/json")
    rows = json.loads(b)["sessions"]
    assert [x["id"] for x in rows] == [new["id"], old["id"]]
    for x in rows:
        assert set(x) == ALLOWED, set(x) ^ ALLOWED
    by = {x["id"]: x for x in rows}
    assert by[old["id"]]["outcome"] == "done" and by[new["id"]]["outcome"] == "waiting"
    assert by[new["id"]]["waiting"] is True and by[old["id"]]["waiting"] is False
    assert by[new["id"]]["pending_question"] == {"q": "ok?"}
    ok("list: newest first, allowlisted keys, outcome, waiting, corrupt skipped")

    d = jget(f"/api/sessions/{old['id']}")
    assert d == by[old["id"]] and d["cost"] == 0.0421
    ok("detail == list projection")
    assert req(f"/api/sessions/{corrupt_id}")[0] == 404
    ok("corrupt record detail 404")

    st = jget(f"/api/sessions/{old['id']}/stream?offset=0")
    assert st["events"] == EXPECTED and st["offset"] == size
    assert st["events"][-1]["cost"] == d["cost"]
    ok("stream offset=0 -> events + offset; cost matches detail")
    assert jget(f"/api/sessions/{old['id']}/stream")["events"] == EXPECTED
    ok("stream no offset == 0")
    assert jget(f"/api/sessions/{old['id']}/stream?offset={size}") == {"events": [], "offset": size}
    with open(sp, "a") as f:
        f.write(json.dumps(A1) + "\n")
    st = jget(f"/api/sessions/{old['id']}/stream?offset={size}")
    assert st["events"] == [{"kind": "text", "text": "hi"}] and st["offset"] > size
    ok("stream appended line returns only new event")
    assert jget(f"/api/sessions/{old['id']}/stream?offset=99999999") == {"events": [], "offset": 99999999}
    ok("stream offset past EOF -> [] same offset")
    for bad in ("abc", "-1", ""):
        s, _, _, _ = req(f"/api/sessions/{old['id']}/stream?offset={bad}")
        assert s == 400, bad
    ok("bad offset -> 400")

    unknown = "20990101T000000000000Z-deadbeef"
    assert req(f"/api/sessions/{unknown}")[0] == 404
    assert req(f"/api/sessions/{unknown}/stream")[0] == 404
    ok("unknown id -> 404")
    v = old["id"]
    for p in ["/api/sessions/nope", "/api/sessions/..", "/api/sessions/%2e%2e", "/api/sessions/a%2Fb",
              "/api/sessions/../sessions", "/api/sessions/x/y/stream", f"/api/sessions/{v}/other",
              "/api/sessions/", f"/api/sessions/{v}/stream/"]:
        s, _, _, _ = req(p)
        assert s == 404, (p, s)
    ok("malformed ids / paths -> 404")

    for p in ("/api/sessions", f"/api/sessions/{v}", f"/api/sessions/{v}/stream"):
        for label, kw in (("host", dict(host="evil.example")),
                          ("origin", dict(origin="http://evil.example"))):
            s, _, _, h = req(p, **kw)
            assert s == 403 and no_cors(h), (p, label, s)
        assert no_cors(req(p)[3])
    ok("403 on bad host/origin, no CORS headers")
    s, r, _, _ = req("/api/sessions", method="POST")
    assert s == 405 and r.getheader("Allow") == "GET"
    ok("POST -> 405")

    bodies = b"".join(req(p)[2] for p in ("/api/sessions", f"/api/sessions/{v}",
                                          f"/api/sessions/{new['id']}",
                                          f"/api/sessions/{v}/stream"))
    for secret in (b"SECRET-TOKEN-XYZ", b"SECRET-META", b"4242", b"999"):
        assert secret not in bodies, secret
    assert all("pid" not in x for x in rows)
    ok("secrets and pid never leak")
finally:
    srv.shutdown()
    srv.server_close()
    shutil.rmtree(data_dir, ignore_errors=True)
    if old_data is None:
        os.environ.pop("CLAUDE_PLUGIN_DATA", None)
    else:
        os.environ["CLAUDE_PLUGIN_DATA"] = old_data

print(f"{passed} checks passed")
