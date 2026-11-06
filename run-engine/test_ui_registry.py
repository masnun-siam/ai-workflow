#!/usr/bin/env python3
"""Self-check for run-engine/skill_registry.py + GET /api/registry (issue #926).

`python3 test_ui_registry.py` — exit 0 = green. Assert-based, no framework.
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()

import repo_skills  # noqa: E402
import skill_registry  # noqa: E402
import ui_server  # noqa: E402

passed = 0


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


SHIPPED = skill_registry.REGISTRY_PATH
EXPECTED = {
    "create-prd", "create-tasks", "small-change", "refine-issues", "implement-issue",
    "after-merge", "pr-review", "pr-review-unmapped", "verifier-locally", "docs-updater",
    "reproduce-bug", "security-sweep", "map-prds", "agentic-onboard", "ci-optimize",
    "skill-feedback", "release-pr", "faq-updater", "pr-grind", "peer-review", "dump", "worklog",
}  # fmt: skip

# --- shipped file ---
s = skill_registry.steps()
assert set(s) == EXPECTED, set(s) ^ EXPECTED
assert all(set(e) == {"plugin", "skill", "runs_in"} for e in s.values())
ok("shipped registry lists exactly the 22 steps, each with plugin, skill, runs_in")
assert skill_registry.command("create-prd") == "/blubird:create-prd"
assert skill_registry.command("dump") == "/ai-workflow-personal:dump"
assert skill_registry.command("pr-review-unmapped") == "/ai-workflow:pr-review"
ok("command(step) is /<plugin>:<skill>")
try:
    skill_registry.command("not-a-step")
    raise AssertionError("unknown step must raise")
except ValueError as e:
    assert "not-a-step" in str(e)
ok("command(unknown step) raises ValueError naming it")

names = repo_skills.names()
for step, e in s.items():
    if e["plugin"] == repo_skills.PLUGIN:
        assert e["skill"] in names, (step, e)
assert "ai-workflow-personal" in skill_registry.PLUGINS
assert repo_skills.PERSONAL_PLUGIN == "ai-workflow-personal"
assert [x for x, e in s.items() if e["plugin"] == repo_skills.PERSONAL_PLUGIN] == ["dump", "worklog"]
ok("every ai-workflow skill exists under skills/; personal entries use repo_skills.PERSONAL_PLUGIN")


def with_registry(data):
    """Point the loader at a temp file holding `data` (a dict, or raw text)."""
    fd, p = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        f.write(data if isinstance(data, str) else json.dumps(data))
    skill_registry.REGISTRY_PATH = p


with open(SHIPPED) as f:
    shipped = json.load(f)

# --- FR-1: one changed entry changes that step's command and no other ---
before = {x: skill_registry.command(x) for x in EXPECTED}
changed = json.loads(json.dumps(shipped))
changed["steps"]["implement-issue"] = {"plugin": "ai-workflow", "skill": "x", "runs_in": "issue"}
with_registry(changed)
after = {x: skill_registry.command(x) for x in EXPECTED}
assert after["implement-issue"] == "/ai-workflow:x"
assert {x for x in EXPECTED if before[x] != after[x]} == {"implement-issue"}
ok("one changed entry changes only that step's command (read per call)")

# --- failure paths ---
BAD = {
    "runs_in": {"plugin": "blubird", "skill": "create-prd", "runs_in": "somewhere"},
    "plugin": {"plugin": "nope", "skill": "create-prd", "runs_in": "docs"},
    "missing": {"plugin": "blubird", "runs_in": "docs"},
    "name": {"plugin": "blubird", "skill": "Bad Name", "runs_in": "docs"},
    "not-object": "blubird:create-prd",
}
for label, bad in BAD.items():
    d = json.loads(json.dumps(shipped))
    d["steps"]["create-prd"] = bad
    with_registry(d)
    try:
        skill_registry.steps()
        raise AssertionError(f"{label} must raise")
    except ValueError as e:
        assert "create-prd" in str(e), (label, e)
ok("unknown runs_in, unknown plugin, missing key, bad skill name, non-object raise ValueError naming the step")
for raw in ("{not json", '{"steps": []}', "[]"):
    with_registry(raw)
    try:
        skill_registry.steps()
        raise AssertionError(f"{raw!r} must raise")
    except ValueError:
        pass
ok("invalid JSON or no steps object raises ValueError")

# --- HTTP ---
srv = ui_server._Server(("127.0.0.1", 0), ui_server._Handler, [])
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
HOST = f"127.0.0.1:{port}"


def req(path, host=HOST):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
    c.putheader("Host", host)
    c.endheaders()
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, data


skill_registry.REGISTRY_PATH = SHIPPED
st, body = req("/api/registry")
assert st == 200, (st, body)
got = json.loads(body)
assert got == skill_registry.view(), got
assert got["steps"]["create-prd"] == {
    "plugin": "blubird",
    "skill": "create-prd",
    "runs_in": "docs",
    "command": "/blubird:create-prd",
}
ok("GET /api/registry is 200 and equals view()")
st, _ = req("/api/registry", host="evil.example")
assert st == 403, st
ok("GET /api/registry with a foreign Host is 403")
with_registry("{not json")
st, body = req("/api/registry")
assert st == 500 and json.loads(body) == {"error": "internal error"}, (st, body)
skill_registry.REGISTRY_PATH = SHIPPED
ok("a malformed registry answers 500 JSON")

srv.shutdown()
print(f"{passed} passed")
