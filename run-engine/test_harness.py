#!/usr/bin/env python3
"""Self-check for run-engine/harness.py + harness_claude.py. `python3 test_harness.py` — exit 0 = green.

The registry, the Claude adapter's argv and login checks, and the runner/dispatch/settings callers that go
through it. Subprocesses and spawns are mocked; nothing runs claude.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import types
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

data_dir = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = data_dir

import dispatch_runners  # noqa: E402
import harness  # noqa: E402
import harness_claude  # noqa: E402
import repo_skills  # noqa: E402
import ui_runner  # noqa: E402
import ui_sessions  # noqa: E402
import ui_settings  # noqa: E402

passed = 0


def ok(label):
    global passed
    passed += 1
    print(f"  ok  {label}")


BASE = ["--print", "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions"]
RESTRICTED = BASE[:-1]
H = harness_claude.HEADLESS_PROMPT
work = tempfile.mkdtemp()

# ---- registry ---------------------------------------------------------------------------------
assert harness.get("claude") is harness_claude
try:
    harness.get("nope")
    raise AssertionError("unknown harness must raise")
except ValueError as e:
    assert str(e) == "unknown harness 'nope'", e
assert harness.for_record({}) is harness.for_record(None) is harness.for_record({"harness": "claude"}) is harness_claude
stub = types.SimpleNamespace(ID="stub", check_login=lambda cmd: {"ok": True, "message": f"stub {cmd}"})
with mock.patch.dict(harness._ADAPTERS, {"stub": stub}):
    assert harness.for_record({"harness": "stub"}) is stub
    with mock.patch.object(ui_settings, "harness_of", return_value="stub"):
        assert harness.for_cmd("cc-x") is stub
        assert ui_settings.check_login("cc-x") == {"ok": True, "message": "stub cc-x"}
with mock.patch.object(ui_settings, "harness_of", return_value="nope"):  # a harness with no adapter
    assert ui_settings.check_login("cx") == {"ok": False, "message": "unknown harness 'nope'"}
assert ui_settings.check_login("nope-xyz-876")["ok"] is False
ok("registry: get, for_record, for_cmd, check_login delegates and never raises")

# ---- start_argv / resume_argv -----------------------------------------------------------------
sa = harness_claude.start_argv
assert sa(["claude"], "go") == (["claude", *BASE, "go"], "go")
assert sa(["claude"], "go", instructions=["a", "b"])[0] == ["claude", *BASE, "--append-system-prompt", "a\n\nb", "go"]
argv, _ = sa(["claude"], "go", instructions=["i"], effort="e", agent="ag", model="m", run_model="rm", run_effort="re")
want = ["--append-system-prompt", "i", "--effort", "e", "--agent", "ag", "--model", "m", "--model", "rm"]
assert argv == ["claude", *BASE, *want, "--effort", "re", "go"], argv
argv, _ = sa(["claude"], "go", allowed_tools=["Read", "Bash(x:*)"])
assert argv == ["claude", *RESTRICTED, "--allowedTools", "Read,Bash(x:*)", "go"], argv
assert sa(["claude"], "go", rec={"allowed_tools": ["Read"]})[0] == [
    "claude",
    *RESTRICTED,
    "--allowedTools",
    "Read",
    "go",
]
ra = harness_claude.resume_argv
assert ra(["c"], "s1", "p", rec={}) == (["c", *BASE, "--append-system-prompt", H, "--resume", "s1", "p"], "p")
argv, _ = ra(["c"], "s1", "p", rec={"run_model": "opus", "run_effort": "high", "allowed_tools": ["Read"]})
want = ["c", *RESTRICTED, "--allowedTools", "Read", "--append-system-prompt", H, "--model", "opus", "--effort", "high"]
assert argv == [*want, "--resume", "s1", "p"], argv
assert harness_claude.skill_text("/implement-issue 1", work) == repo_skills.resolve("/implement-issue 1", work)
ok("claude start_argv/resume_argv order, allowed_tools, skill_text")


# ---- preflight --------------------------------------------------------------------------------
def run_returning(stdout):
    return mock.patch.object(
        harness_claude.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout, "")
    )


def login_error(cmd):
    try:
        harness_claude.preflight(cmd)
    except harness.LoginError as e:
        return str(e)
    raise AssertionError("expected LoginError")


with mock.patch.object(ui_settings, "argv", side_effect=lambda c: [c]):
    with run_returning('{"loggedIn": true}'):
        assert harness_claude.preflight("claude") == ["claude"]
    with run_returning('{"loggedIn": false}'):
        assert login_error("claude") == "claude CLI is not logged in, run `claude auth login`"
        assert login_error("cc-x") == "claude CLI is not logged in, run `cc-x auth login`"
    with run_returning("garbage"):
        msg = login_error("claude")
        assert msg.startswith("claude CLI is not logged in, run `claude auth login` (auth status check failed: "), msg
with mock.patch.object(ui_settings, "argv", side_effect=ValueError("not found")):
    assert login_error("claude") == "claude CLI not found on PATH"
    assert login_error("nope") == "claude command 'nope' unusable: not found"
    sid = ui_sessions.create("x", work, claude_cmd="nope")["id"]
    try:
        ui_runner._preflight(sid)
        raise AssertionError("expected RunnerError")
    except ui_runner.RunnerError as e:
        assert str(e) == "claude command 'nope' unusable: not found"
    rec = ui_sessions.load(sid)
    assert rec["status"] == "failed" and rec["error"] == "claude command 'nope' unusable: not found", rec
ok("preflight: logged in, logged out, check failed, unusable; _preflight fails the session")


# ---- ui_runner.start --------------------------------------------------------------------------
def fake_spawn(sid, argv, path, *a, **k):
    return ui_sessions.load(sid)


def spawn():
    return mock.patch.object(ui_runner, "_spawn", side_effect=fake_spawn)


with mock.patch.object(ui_runner, "_preflight", return_value=["claude"]):
    with spawn() as sp, mock.patch.object(ui_settings, "harness_of", return_value="claude"):
        rec = ui_runner.start("go", work, instructions=["x"], direct_effort="low", claude_cmd="claude")
    assert rec["harness"] == "claude", rec
    assert sp.call_args[0][1] == ["claude", *BASE, "--append-system-prompt", "x", "--effort", "low", "go"]
    assert sp.call_args.kwargs["command"] == "go"
    ok("start: records harness; instructions and direct_effort reach the argv")

    bypass = [
        {"instructions": ["x"]},
        {"env_extra": {"A": "1"}},
        {"pass_fds": [0]},
        {"agent": "a"},
        {"model": "m"},
        {"direct_effort": "high"},
    ]
    queued = [{}, {"run_model": "opus"}, {"effort": "high"}, {"run_model": "opus", "effort": "high"}]
    with mock.patch.object(ui_runner, "limits", return_value={"cc-x": {"limited_until": 4102444800}}):
        for kw in [*bypass, *queued]:
            with spawn() as sp:
                rec = ui_runner.start("go", work, claude_cmd="cc-x", **kw)
            if kw in bypass:
                assert sp.call_count == 1, kw
            else:
                assert sp.call_count == 0 and rec["status"] == "limited" and rec["harness"] == "claude", (kw, rec)
    ok("queue bypass: instructions/env/fds/agent/model/direct_effort skip it; run_model/effort alone do not")

# ---- ui_sessions.create -----------------------------------------------------------------------
assert ui_sessions.create("x", work, harness="claude")["harness"] == "claude"
assert "harness" not in ui_sessions.create("x", work)
ok("ui_sessions.create: harness stored only when given")


# ---- dispatch_runners.Headless ----------------------------------------------------------------
class KwRunner:
    def start(self, prompt, repo, **kw):
        self.kw = kw
        return {"id": "s"}


class FakeSettings:
    @staticmethod
    def load():
        return {"commands": [{"label": "work", "cmd": "claude"}]}


kr = KwRunner()
dispatch_runners.Headless(runner=kr, settings=FakeSettings).start(
    {"repo": work}, "/implement-issue 1", {"settings": {"effort": "high", "model": "opus", "account": "work"}}
)
assert kr.kw["direct_effort"] == "high" and kr.kw["model"] == "opus" and "extra_args" not in kr.kw, kr.kw
ok("headless dispatch passes direct_effort and model")

print(f"\n{passed} checks passed")
