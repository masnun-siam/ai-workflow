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
ID = "0199a213-81c0-7800-8aa1-bbab2a035a53"

# --- input that is not an event ---
for bad in ("", "not json", "[1,2]", "null", "42", b"\xff\xfe", line(), line(type=5), line(type="zzz")):
    assert parse(bad) == [], bad
ok("non-events -> []")
assert parse(line(type="thread.started", thread_id=ID).encode()) == parse(line(type="thread.started", thread_id=ID))
ok("bytes == str")
assert parse(line(type="turn.started")) == []
ok("turn.started -> []")

# --- thread.started ---
assert parse(line(type="thread.started", thread_id=ID)) == [{"kind": "session_id", "id": ID, "model": None}]
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

# --- the shell wrapper Codex puts around every command ---
assert parse(done({"type": "command_execution", "command": "/bin/zsh -lc 'git status --short'"})) == [
    {"kind": "tool", "name": "Bash", "input": {"command": "git status --short"}}
]
assert parse(done({"type": "command_execution", "command": "/bin/bash -c \"aiw ask --json '{}'\""})) == [
    {"kind": "tool", "name": "Bash", "input": {"command": "aiw ask --json '{}'"}}
]
for raw in ("ls -la", "/bin/zsh -lc", "/bin/zsh -x 'ls'", "/bin/zsh -lc 'unclosed"):
    assert parse(done({"type": "command_execution", "command": raw})) == [
        {"kind": "tool", "name": "Bash", "input": {"command": raw}}
    ], raw
ok("shell wrapper removed, anything else kept")

# --- fixture recorded from codex-cli 0.166.0: an aiw ask run, two resumes, a failed run ---
FIXTURE = os.path.join(HERE, "fixtures", "codex_stream.jsonl")
with open(FIXTURE, "rb") as f:
    events = [e for raw in f.read().splitlines() for e in parse(raw)]
TID = "01a1a2fc-5ee5-7443-bac0-d09ae1ff20a4"
ASK = (
    'aiw ask --json \'{"questions":[{"question":"Proceed?","header":"Gate","options":'
    '[{"label":"Yes","description":"go on"},{"label":"No","description":"stop"}],'
    '"multiSelect":false}]}\''
)
FAILED = "The 'no-such-model-xyz' model is not supported when using Codex with a ChatGPT account."
session = {"kind": "session_id", "id": TID, "model": None}


def bash(cmd) -> dict:
    return {"kind": "tool", "name": "Bash", "input": {"command": cmd}}


def text(t) -> dict:
    return {"kind": "text", "text": t}


expected = [
    session,
    text("I\u2019ll run that exact command."),
    bash(ASK),
    text("The question was recorded and sent to the human for an answer."),
    result({"input": 28560, "cached": 24960, "output": 102}),
    session,
    text("I\u2019ll run the two status checks and append the requested line in order."),
    bash("git status --short"),
    bash("printf 'hello\\n' >> README.md"),
    bash("git status --short"),
    text("I appended \u201chello\u201d to README.md and confirmed it appears as modified in the final status."),
    result({"input": 87256, "cached": 82560, "output": 239}),
    session,
    text("I\u2019ll append the line to README.md using the file-editing tool."),
    {
        "kind": "tool",
        "name": "file_change",
        "input": {
            "id": "item_1",
            "type": "file_change",
            "changes": [{"path": "/private/tmp/codex-fixture.XrsQ/README.md", "kind": "update"}],
            "status": "completed",
        },
    },
    text("Added \u201cworld\u201d to the end of README.md."),
    result({"input": 117089, "cached": 108032, "output": 329}),
    {"kind": "session_id", "id": "01a1a2fd-0ac7-75b3-826e-dc39fb189f59", "model": None},
    {
        "kind": "tool",
        "name": "error",
        "input": {
            "id": "item_0",
            "type": "error",
            "message": "Model metadata for `no-such-model-xyz` not found. "
            "Defaulting to fallback metadata; this can degrade performance and cause issues.",
        },
    },
    error(FAILED),  # the top-level `error` comes first
    error(FAILED),  # then `turn.failed` with the same message
]
assert events == expected, events
ok("fixture -> exact event list")
cmds = [e["input"]["command"] for e in events if e["kind"] == "tool" and e["name"] == "Bash"]
assert [c for c in cmds if c.startswith("aiw ask")] == [ASK]
ok("one Bash event per command, aiw ask detectable")
assert sum(e["tokens"]["input"] for e in events if e["kind"] == "result" and not e["is_error"]) == 232905
ok("per-turn tokens, not cumulative")

print(f"{passed} checks passed")
