#!/usr/bin/env python3
"""Self-check for run-engine/harness_codex.py, the Codex stream parser (issue #871).

`python3 test_harness_codex.py` — exit 0 = green. Assert-based, no framework.
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import harness_codex  # noqa: E402
import ui_runner  # noqa: E402

parse = harness_codex.parse_line
passed = 0


def ok(label: str) -> None:
    global passed
    passed += 1


def line(**ev) -> str:
    return json.dumps(ev)


def done(item) -> str:
    return line(type="item.completed", item=item)


def result(tokens) -> dict:
    return {"kind": "result", "cost": None, "is_error": False, "text": None, "tokens": tokens}


def error(text) -> dict:
    return {"kind": "result", "cost": None, "is_error": True, "text": text, "tokens": None}


LIMIT = {"kind": "limit", "resets_at": None, "type": None, "info": None}
TID = "0199a213-81c0-7800-8aa1-bbab2a035a53"

# --- input that is not an event ---
for bad in ("", "not json", "[1,2]", "null", "42", b"\xff\xfe", line(), line(type=5), line(type="zzz")):
    assert parse(bad) == [], bad
ok("non-events -> []")
assert parse(line(type="thread.started", thread_id=TID).encode()) == parse(line(type="thread.started", thread_id=TID))
ok("bytes == str")
assert parse(line(type="turn.started")) == []
ok("turn.started -> []")

# --- thread.started ---
assert parse(line(type="thread.started", thread_id=TID)) == [{"kind": "session_id", "id": TID, "model": None}]
assert parse(line(type="thread.started")) == []
assert parse(line(type="thread.started", thread_id=7)) == []
ok("thread.started")

# --- items ---
msg = {"id": "i", "type": "agent_message", "text": "hi"}
assert parse(line(type="item.started", item=msg)) == []
assert parse(line(type="item.updated", item=msg)) == []
assert parse(done(msg)) == [{"kind": "text", "text": "hi"}]
assert parse(done({"type": "agent_message", "text": None})) == []
ok("agent_message only on item.completed")
cmd = {"id": "c", "type": "command_execution", "command": "ls", "exit_code": 0, "status": "completed"}
assert parse(done(cmd)) == [{"kind": "tool", "name": "Bash", "input": {"command": "ls"}}]
assert parse(line(type="item.started", item=cmd)) == []
assert parse(done({"type": "command_execution"})) == []
ok("command_execution -> Bash")
for t in ("file_change", "mcp_tool_call", "reasoning"):
    item = {"id": "x", "type": t, "text": "t"}
    assert parse(done(item)) == [{"kind": "tool", "name": t, "input": item}], t
ok("other items -> tool by type")
for bad in ("str", [1], None, {"id": "x"}, {"type": 3}):
    assert parse(line(type="item.completed", item=bad)) == [], bad
assert parse(line(type="item.completed")) == []
ok("malformed item -> []")

# --- turn.completed tokens ---
usage = {"input_tokens": 1200, "cached_input_tokens": 1000, "output_tokens": 80}
assert parse(line(type="turn.completed", usage=usage)) == [result({"input": 1200, "cached": 1000, "output": 80})]
assert parse(line(type="turn.completed")) == [result(None)]
zero = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
assert parse(line(type="turn.completed", usage=zero)) == [result(None)]
odd = {"input_tokens": True, "cached_input_tokens": -5, "output_tokens": "9", "reasoning_output_tokens": 4}
assert parse(line(type="turn.completed", usage=odd)) == [result(None)]
assert parse(line(type="turn.completed", usage={"input_tokens": 10, "output_tokens": 2})) == [
    result({"input": 10, "cached": 0, "output": 2})
]
ok("turn.completed tokens")

# --- turn.failed / error ---
assert parse(line(type="turn.failed", error={"message": "model overloaded"})) == [error("model overloaded")]
assert parse(line(type="turn.failed")) == [error(None)]
assert parse(line(type="turn.failed", error="boom")) == [error(None)]
assert parse(line(type="error", message="bad request")) == [error("bad request")]
assert parse(line(type="error", message={"x": 1})) == [error(None)]
assert parse(line(type="error", message="Rate limit exceeded")) == [error("Rate limit exceeded"), LIMIT]
ok("turn.failed / error")
assert harness_codex.LIMIT_RE.pattern == ui_runner._LIMIT_RE.pattern
assert harness_codex.LIMIT_RE.flags == ui_runner._LIMIT_RE.flags
ok("LIMIT_RE matches ui_runner")

# --- fixture ---
# Provisional guard: when the real fixture lands, rename this to codex_stream.jsonl and drop the guard.
FIXTURE = os.path.join(HERE, "fixtures", "codex_stream.provisional.jsonl")
assert os.path.isfile(FIXTURE)
ok("provisional fixture present")
with open(FIXTURE, "rb") as f:
    events = [e for raw in f.read().splitlines() for e in parse(raw)]
ASK = 'aiw ask --json \'{"questions":[{"question":"Proceed?"}]}\''
LIMIT_MSG = "You've hit your usage limit. Try again later."
session = {"kind": "session_id", "id": TID, "model": None}
expected = [
    session,
    {"kind": "tool", "name": "Bash", "input": {"command": ASK}},
    {"kind": "text", "text": "Waiting for your answer."},
    result({"input": 1200, "cached": 1000, "output": 80}),
    session,
    {"kind": "tool", "name": "Bash", "input": {"command": "git status --short"}},
    {
        "kind": "tool",
        "name": "file_change",
        "input": {
            "id": "item_1",
            "type": "file_change",
            "changes": [{"path": "README.md", "kind": "update"}],
            "status": "completed",
        },
    },
    {"kind": "tool", "name": "reasoning", "input": {"id": "item_3", "type": "reasoning", "text": "thinking"}},
    {"kind": "text", "text": "Done."},
    result({"input": 2000, "cached": 1500, "output": 150}),
    error(LIMIT_MSG),
    LIMIT,
    error(LIMIT_MSG),
    LIMIT,
]
assert events == expected, events
ok("fixture -> exact event list")
bash = [e["input"]["command"] for e in events if e["kind"] == "tool" and e["name"] == "Bash"]
assert bash.count(ASK) == 1 and bash.count("git status --short") == 1
ok("one Bash event per command")
assert sum(e["tokens"]["input"] for e in events if e["kind"] == "result" and not e["is_error"]) == 3200
ok("per-turn tokens, not cumulative")

print(f"{passed} checks passed")
