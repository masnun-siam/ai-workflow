#!/usr/bin/env python3
"""Self-check for #877: every stream reader parses through the session's harness adapter.
`python3 test_harness_streams.py` — exit 0 = green.

A stub adapter (a made-up line format) drives the follower, the transcript, `final_text` and `last_tokens`
with no Claude parsing involved; the Claude adapter's `parse_line` and `resume_command` are pinned too.
"""

from __future__ import annotations

import http.client
import json
import os
import shlex
import sys
import tempfile
import threading
import types
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()
os.environ["AIW_NO_MAC_BANNER"] = "1"

import ui_notify  # noqa: E402

ui_notify.send_mac = lambda *a, **k: None
import harness  # noqa: E402
import harness_claude  # noqa: E402
import ui_events  # noqa: E402
import ui_origin  # noqa: E402
import ui_panel  # noqa: E402
import ui_runner  # noqa: E402
import ui_server  # noqa: E402
import ui_sessions  # noqa: E402

passed = 0


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


def j(o) -> str:
    return json.dumps(o)


# ------------------------------------------------------------------ harness_claude.parse_line
INIT = {"type": "system", "subtype": "init", "session_id": "sess-abc", "model": "claude-test"}
assert harness_claude.parse_line(j(INIT)) == [{"kind": "session_id", "id": "sess-abc", "model": "claude-test"}]
assert harness_claude.parse_line(j({**INIT, "model": ""})) == [{"kind": "session_id", "id": "sess-abc", "model": None}]
no_model = {k: v for k, v in INIT.items() if k != "model"}
assert harness_claude.parse_line(j(no_model)) == [{"kind": "session_id", "id": "sess-abc", "model": None}]
ok("system/init -> session_id, model or None")

ASSIST = {
    "type": "assistant",
    "message": {
        "content": [
            {"type": "text", "text": "hi"},
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
        ]
    },
}
assert harness_claude.parse_line(j(ASSIST)) == ui_events.parse_line(j(ASSIST)) != []
ok("assistant text + tool_use: same events as ui_events.parse_line")

INFO = {"status": "rejected", "resetsAt": 1900000000, "rateLimitType": "five_hour"}
RL = {"type": "rate_limit_event", "rate_limit_info": INFO}
assert harness_claude.parse_line(j(RL)) == [
    {"kind": "limit", "resets_at": 1900000000, "type": "five_hour", "info": INFO}
]
warn_info = {"status": "allowed_warning", "resetsAt": 1900000000}
assert harness_claude.parse_line(j({**RL, "rate_limit_info": warn_info}))[0]["kind"] == "limit"
assert harness_claude.parse_line(j({**RL, "rate_limit_info": {**INFO, "resetsAt": "soon"}}))[0]["resets_at"] is None
assert harness_claude.parse_line(j({**RL, "rate_limit_info": {**INFO, "resetsAt": True}}))[0]["resets_at"] is None
assert harness_claude.parse_line(j({**RL, "rate_limit_info": "x"})) == []
ok("rate_limit_event -> limit (rejected, warning, non-int resetsAt)")

USAGE = {"input_tokens": 10, "output_tokens": 5}
RES = {"type": "result", "is_error": False, "total_cost_usd": 0.5, "result": "done", "usage": USAGE}
assert harness_claude.parse_line(j(RES)) == [
    {
        "kind": "result",
        "cost": 0.5,
        "is_error": False,
        "text": "done",
        "tokens": {"input": 10, "cached": 0, "output": 5},
    }
]
ERR = {"type": "result", "is_error": True, "result": "boom", "errors": ["No conversation found with id x"]}
(e,) = harness_claude.parse_line(j(ERR))
assert e["error"] == "No conversation found with id x" and e["text"] == "boom"
assert "error" not in harness_claude.parse_line(j({**ERR, "errors": []}))[0]
ok("result: tokens; error result carries errors[0] as `error`, text unchanged")

for bad in ("", "   ", "{not json", "[1,2]", j({"type": "user"}), b"\xff\xfe"):
    assert harness_claude.parse_line(bad) == [], bad
assert harness_claude.parse_line(j(INIT).encode()) == harness_claude.parse_line(j(INIT))
ok("unknown / malformed / blank -> []; bytes input works")

# ------------------------------------------------------------------ harness_claude.resume_command
rc = harness_claude.resume_command("claude", "/tmp/a b;x", "s1")
assert rc == "cd '/tmp/a b;x' && claude --resume s1", rc
assert shlex.split(rc) == ["cd", "/tmp/a b;x", "&&", "claude", "--resume", "s1"]
assert harness_claude.resume_command("claude", None, "s1") is None
assert harness_claude.resume_command("claude", "/tmp", None) is None
ok("resume_command: quoted, round-trips, None without path or id")


# ------------------------------------------------------------------ stub adapter
def stub_parse(line) -> list:
    line = line.decode() if isinstance(line, bytes) else line
    parts = line.split()
    if not parts:
        return []
    tag, rest = parts[0], parts[1:]
    if tag == "S":
        return [{"kind": "session_id", "id": rest[0], "model": rest[1] if len(rest) > 1 else None}]
    if tag == "T":
        return [{"kind": "text", "text": " ".join(rest)}]
    if tag == "B":
        return [{"kind": "tool", "name": "Bash", "input": {"command": " ".join(rest)}}]
    if tag == "R":
        cost = float(rest[0]) if rest[0] != "-" else None
        tokens = {"input": int(rest[1]), "cached": 0, "output": int(rest[2])}
        return [{"kind": "result", "cost": cost, "is_error": False, "text": "stub result", "tokens": tokens}]
    if tag == "E":
        out = [{"kind": "result", "cost": None, "is_error": True, "text": " ".join(rest), "tokens": None}]
        return out
    if tag == "L":
        return [{"kind": "limit", "resets_at": int(rest[0]) if rest else None, "type": None, "info": None}]
    return []


stub = types.SimpleNamespace(
    parse_line=stub_parse,
    resume_command=lambda cmd, path, sid: f"stub-resume {sid}" if sid else None,
)
patch = mock.patch.dict(harness._ADAPTERS, {"stub": stub})
patch.start()
# the stub stream must never reach Claude's parser
claude_guard = mock.patch.object(ui_events, "parse_line", side_effect=AssertionError("claude parser used"))


class DoneProc:
    returncode, pid = 0, 0

    def poll(self):
        return 0


def session(lines, harness_id="stub", **fields) -> str:
    sid = ui_sessions.create("/implement-issue 1", "o/r", harness=harness_id)["id"]
    ui_sessions.update(sid, **{"status": "running", **fields})
    with open(os.path.join(ui_sessions.session_dir(sid), "stream.jsonl"), "w") as f:
        f.write("".join(line + "\n" for line in lines))
    return sid


def follow(lines, **fields) -> dict:
    sid = session(lines, **fields)
    with claude_guard:
        ui_runner._follow(sid, DoneProc(), None, None, 0)
    return ui_sessions.load(sid)


r = follow(["S th-1 gpt-x", "T hello", "R 0.25 10 2"])
assert r["session_id"] == "th-1" and r["model"] == "gpt-x" and r["status"] == "done", r
ok("_follow (stub): session id and model written, done")

r = follow(["S th-1", "R 0.1 10 2", "R 0.2 5 1"])
assert r["tokens"] == {"input": 15, "cached": 0, "output": 3} and r["cost"] == 0.2, r
r = follow(["S th-1", "R 0.1 10 2", "S th-2", "R 0.3 4 4"])
assert r["tokens"] == {"input": 4, "cached": 0, "output": 4} and r["cost"] == 0.3, r
r = follow(["S th-1", "R - 1 1"])
assert r["cost"] is None and r["tokens"] == {"input": 1, "cached": 0, "output": 1}, r
ok("_follow (stub): tokens summed per run, reset by session_id; cost from each result, None passes")

r = follow(["S th-1", "B aiw ask --json {}", "R 0.1 1 1"], pending_question={"id": "q"}, status="waiting")
assert r["status"] == "waiting", r
r = follow(["S th-1", "B aiw ask --json {}", "R 0.1 1 1"])
assert r["status"] == "failed" and "aiw ask ran but recorded no question" in r["error"], r
ok("_follow (stub): aiw ask detected from the common tool event")

ui_runner._usage.clear()
r = follow(["S th-1", "L 1900000000", "E boom"])
assert r["status"] == "limited" and r["limit_resets_at"] == 1900000000 and r["auto_resume"] is True, r
r = follow(["S th-1", "L", "E boom"])
assert r["status"] == "limited" and r["limit_resets_at"] is None and not r["auto_resume"], r
r = follow(["S th-1", "E You hit your limit"])
assert r["status"] == "limited" and r["error"] == "You hit your limit", r
assert ui_runner._usage == {}, ui_runner._usage
ok("_follow (stub): limit event / limit text -> limited; _usage untouched without info")

# ------------------------------------------------------------------ Claude parity of _follow
CLAUDE_STREAM = [j(INIT), j(ASSIST), j(RES)]
sid = session(CLAUDE_STREAM, harness_id="claude")
ui_runner._follow(sid, DoneProc(), None, None, 0)
r = ui_sessions.load(sid)
assert (r["session_id"], r["model"], r["cost"], r["status"]) == ("sess-abc", "claude-test", 0.5, "done"), r
assert r["tokens"] == {"input": 10, "cached": 0, "output": 5}, r
ui_runner._usage.clear()
sid = session([j(INIT), j(RL), j(ERR)], harness_id="claude")
ui_runner._follow(sid, DoneProc(), None, None, 0)
r = ui_sessions.load(sid)
assert r["status"] == "limited" and r["limit_resets_at"] == 1900000000 and r["limit_type"] == "five_hour", r
assert r["error"] == "No conversation found with id x" and r["auto_resume"] is True, r
assert ui_runner._usage[r.get("claude_cmd") or "claude"] == INFO
sid = session([j(INIT), j({**RL, "rate_limit_info": warn_info}), j(RES)], harness_id="claude")
ui_runner._follow(sid, DoneProc(), None, None, 0)
assert ui_sessions.load(sid)["status"] == "done"
ok("_follow (claude): same record as before; errors[0] wins; rejected limit -> limited, warning does not")

# ------------------------------------------------------------------ transcript endpoint
srv = ui_server._Server(("127.0.0.1", 0), ui_server._Handler, ())
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]


def get(path):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
    c.putheader("Host", f"127.0.0.1:{port}")
    c.endheaders()
    r = c.getresponse()
    body = json.loads(r.read())
    c.close()
    return body


sid = session([j(INIT), j(RL), j(ASSIST), j(ERR), j(RES)], harness_id="claude")
body = get(f"/api/sessions/{sid}/stream")
want = [e for line in (ASSIST, ERR, RES) for e in ui_events.parse_line(j(line))]
assert body["events"] == want, body
ok("transcript (claude): text/tool/result only, same JSON as ui_events (no `error` key)")

sid = session(["S th-1", "L 5", "T hi", "B ls", "R 0.1 1 1"])
with claude_guard:
    first = get(f"/api/sessions/{sid}/stream?offset=0")
    again = get(f"/api/sessions/{sid}/stream?offset={first['offset']}")
assert [e["kind"] for e in first["events"]] == ["text", "tool", "result"], first
assert again["events"] == [], again
with open(os.path.join(ui_sessions.session_dir(sid), "stream.jsonl"), "a") as f:
    f.write("T tail")  # no newline: a terminal session's tail is complete
ui_sessions.update(sid, status="done")
with claude_guard:
    tail = get(f"/api/sessions/{sid}/stream?offset={first['offset']}")
assert tail["events"] == [{"kind": "text", "text": "tail"}], tail
ok("transcript (stub): stub events, no session_id/limit; offset chaining and terminal tail")

# ------------------------------------------------------------------ final_text
assert ui_panel.final_text(session([j(ASSIST), j(RES)], harness_id="claude")) == "done"
assert ui_panel.final_text(session([j(ASSIST)], harness_id="claude")) == "hi"
with claude_guard:
    assert ui_panel.final_text(session(["T first", "R 0.1 1 1", "T later"])) == "stub result"
    assert ui_panel.final_text(session(["T first", "T Verdict: approve"])) == "Verdict: approve"
orphan = session([j(ASSIST), j(RES)], harness_id="claude")
os.remove(os.path.join(ui_sessions.session_dir(orphan), "meta.json"))
assert ui_sessions.load(orphan) is None and ui_panel.final_text(orphan) == "done"
ok("final_text: last result text else last text, through the session's adapter; no record -> claude")

# ------------------------------------------------------------------ last_tokens / _with_tokens
two = {**RES, "usage": {"input_tokens": 1, "output_tokens": 1}}
sid = session([j(INIT), j(two), j(RES)], harness_id="claude")
assert ui_sessions.last_tokens(sid) == {"input": 10, "cached": 0, "output": 5}
with claude_guard:
    sid = session(["S a", "R 0.1 3 4"])
    assert ui_sessions.last_tokens(sid) == {"input": 3, "cached": 0, "output": 4}
    rec = {**ui_sessions.load(sid), "status": "done"}
    rec.pop("tokens", None)
    assert ui_sessions._with_tokens(rec)["tokens"] == {"input": 3, "cached": 0, "output": 4}
    with mock.patch.object(ui_sessions, "last_tokens", side_effect=AssertionError("rescanned")):
        ui_sessions._with_tokens({**rec, "tokens": None})
ok("last_tokens / _with_tokens: last result through the adapter; a record with tokens is not rescanned")

# ------------------------------------------------------------------ _public
p = ui_server._public({"id": "c", "cwd_path": "/tmp/a b", "session_id": "s1", "cost": None})
assert p["harness"] == "claude" and p["run_note"] is None and p["cost"] is None
assert p["resume_command"] == "cd '/tmp/a b' && claude --resume s1"
p = ui_server._public({"id": "s", "harness": "stub", "cwd_path": "/tmp", "session_id": "s9", "run_note": "x"})
assert p["harness"] == "stub" and p["resume_command"] == "stub-resume s9" and p["run_note"] == "x"
assert ui_server._public({"id": "s", "harness": "stub", "cwd_path": "/tmp"})["resume_command"] is None
assert ui_server._public({"id": "x"})["resume_command"] is None
note = "x is not a Codex model; ran on Codex's default"
assert ui_server._public({"id": "x", "run_note": note})["run_note"] == note
ok("_public: harness, run_note, the adapter's resume_command, null cost")

# ------------------------------------------------------------------ ui_origin stays Claude-only
sid = session(["S a", "T hi", "B gh issue create", "R 0.1 1 1"])
assert ui_origin._made(ui_sessions.load(sid)) == (set(), set())
ok("ui_origin._made on a non-Claude stream -> empty sets, no raise")

srv.shutdown()
patch.stop()
print(f"{passed} checks passed")
