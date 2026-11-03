#!/usr/bin/env python3
"""Golden Claude argv: `python3 test_harness_golden.py` — exit 0 = green.

Pins, as literal lists, the claude argv of every spawn path (start, answer, Continue, batch start, panel lens,
Away answerer, grind re-entry, headless and herdr dispatch lanes) and which starts skip the account-limit queue.
The literals are written out here on purpose, never built from ui_runner's constants: a refactor that moves or
rewords a flag or prompt must turn this red. Only `_spawn` (the single spawn point) and `_preflight` are mocked.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

data_dir = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = data_dir

import away_answerer  # noqa: E402
import ci  # noqa: E402
import dispatch  # noqa: E402
import dispatch_runners  # noqa: E402
import peer_review  # noqa: E402
import shared  # noqa: E402
import ui_afk  # noqa: E402
import ui_panel  # noqa: E402
import ui_runner  # noqa: E402
import ui_sessions  # noqa: E402

passed = 0


def ok(label):
    global passed
    passed += 1
    print(f"  ok  {label}")


BASE = ["--print", "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions"]
RESTRICTED = ["--print", "--output-format", "stream-json", "--verbose"]  # no bypass flag, used with --allowedTools
HEADLESS = (
    "Headless run: ask via aiw ask, never AskUserQuestion. Gate questions go through "
    "`aiw ask --json '<AskUserQuestion input>'`; then end your turn. "
    "Never call ScheduleWakeup: a pending wakeup keeps this process alive, and the UI cannot take "
    "an answer until it exits."
)
REENTRY = (
    "This is an automated headless pr-grind re-entry from the aiw ui timer. Take the On-wake "
    "branch, never clear `paused:`, never call ScheduleWakeup or Monitor, follow the headless "
    "steps in SKILL.md, then exit. A stop that needs a human decision is asked through `aiw ask` "
    "as Step 8 says; any other stop stays a plain paused stop."
)
CONTINUE = "Continue from where you were stopped."
GATE = ["--append-system-prompt", HEADLESS]
LENS_TOOLS = ",".join(away_answerer.allowed_tools("peer-reviewer"))
AWAY_TOOLS = ",".join(away_answerer.allowed_tools())

work = tempfile.mkdtemp()  # no .claude/skills here: every /skill resolves to the plugin spelling


def fake_spawn(sid, argv, path, *a, **k):
    return ui_sessions.load(sid)


def capture():
    """Patch the spawn point; the caller reads `sp.call_args`."""
    return mock.patch.object(ui_runner, "_spawn", side_effect=fake_spawn)


preflight = mock.patch.object(ui_runner, "_preflight", return_value=["claude"])
preflight.start()


def spawned(fn, *a, **kw) -> list:
    with capture() as sp:
        fn(*a, **kw)
    assert sp.call_count == 1, sp.call_args_list
    return sp.call_args[0][1]


def record(cmd, **fields) -> str:
    sid = ui_sessions.create(cmd, work)["id"]
    ui_sessions.update(sid, cwd_path=work, **fields)
    return sid


# ---- 1. start --------------------------------------------------------------------------------
argv = spawned(ui_runner.start, "/implement-issue 1", work)
assert argv == ["claude", *BASE, "/ai-workflow:implement-issue 1"], argv
argv = spawned(ui_runner.start, "/implement-issue 1", work, gate_questions=True)
assert argv == ["claude", *BASE, *GATE, "/ai-workflow:implement-issue 1"], argv
argv = spawned(
    ui_runner.start,
    "/implement-issue 1",
    work,
    gate_questions=True,
    run_model="opus",
    effort="high",
    claude_cmd="claude",
)
want = ["claude", *BASE, "--append-system-prompt", HEADLESS, "--model", "opus", "--effort", "high"]
assert argv == [*want, "/ai-workflow:implement-issue 1"], argv
argv = spawned(ui_runner.start, "go", work, allowed_tools=["Read", "Bash(git status:*)"])
assert argv == ["claude", *RESTRICTED, "--allowedTools", "Read,Bash(git status:*)", "go"], argv
ok("start: plain, gated, gated with model/effort, allowed_tools")

# ---- 2. resume with an answer -----------------------------------------------------------------
sid = record("/implement-issue 2", session_id="sess-1", run_model="opus", run_effort="high", status="waiting")
argv = spawned(ui_runner.resume, sid, "Answer to q-1: x")
want = ["claude", *BASE, "--append-system-prompt", HEADLESS, "--model", "opus", "--effort", "high"]
assert argv == [*want, "--resume", "sess-1", "Answer to q-1: x"], argv
sid = record("/implement-issue 3", session_id="sess-1", status="waiting")
argv = spawned(ui_runner.resume, sid, "Answer to q-1: x")
assert argv == ["claude", *BASE, *GATE, "--resume", "sess-1", "Answer to q-1: x"], argv
ok("resume: with and without run model/effort")

# ---- 3. Continue (resume_stopped) -------------------------------------------------------------
sid = record("/implement-issue 4", session_id="sess-1", run_model="opus", run_effort="high", status="stopped")
argv = spawned(ui_runner.resume_stopped, sid)
want = ["claude", *BASE, *GATE, "--model", "opus", "--effort", "high", "--resume", "sess-1"]
assert argv == [*want, CONTINUE], argv
sid = record("/implement-issue 5", run_model="opus", run_effort="high", status="limited")
argv = spawned(ui_runner.resume_stopped, sid)
assert argv == ["claude", *BASE, *GATE, "--model", "opus", "--effort", "high", "/ai-workflow:implement-issue 5"], argv
lens_tools = away_answerer.allowed_tools("peer-reviewer")
sid = record("/implement-issue 10", allowed_tools=lens_tools, status="limited")  # a lens limited before its session
argv = spawned(ui_runner.resume_stopped, sid)
assert argv == ["claude", *RESTRICTED, "--allowedTools", LENS_TOOLS, *GATE, "/ai-workflow:implement-issue 10"], argv
ok("Continue: --resume, and a fresh start when limited before any session")

# ---- 4. batch start (_start_claimed) ----------------------------------------------------------
sid = record("/implement-issue 6", run_model="sonnet", run_effort="low", status="starting")
argv = spawned(ui_runner._start_claimed, ui_sessions.load(sid), "b")
assert argv == ["claude", *BASE, *GATE, "--model", "sonnet", "--effort", "low", "/ai-workflow:implement-issue 6"], argv
ok("batch start")

# ---- 5. panel lens ----------------------------------------------------------------------------
panel = {"id": "p1", "artifact": "/a/prd.md", "repo": work, "round": 1, "lens_sessions": {}}
with (
    mock.patch.object(peer_review, "load_panel", return_value=panel),
    mock.patch.object(peer_review, "update_panel"),
    capture() as sp,
):
    ui_panel._start_lens("p1", "qa")
argv = sp.call_args[0][1]
want = ["claude", *RESTRICTED, "--allowedTools", LENS_TOOLS, "--agent", "ai-workflow:peer-reviewer", "--model", "opus"]
assert argv[:-1] == want, argv
assert argv[-1].startswith("Review the artifact at /a/prd.md through the qa lens."), argv[-1]
lens_sid = sp.call_args[0][0]
ui_sessions.update(lens_sid, session_id="sess-L", status="done")
argv = spawned(ui_runner.resume, lens_sid, "again")
assert argv == ["claude", *RESTRICTED, "--allowedTools", LENS_TOOLS, *GATE, "--resume", "sess-L", "again"], argv
ok("panel lens: start, and resume without --agent/--model")

# ---- 6. Away answerer -------------------------------------------------------------------------
sid = record("/implement-issue 7", status="waiting", session_id="sess-W")
pq = {"id": "q-1", "status": "pending", "questions": [{"question": "Ship?", "options": [{"label": "Yes"}]}]}
ui_sessions.set_pending(sid, pq)
with capture() as sp:
    ui_afk._start_answerer(ui_sessions.load(sid), pq)
argv = sp.call_args[0][1]
want = ["claude", *RESTRICTED, "--allowedTools", AWAY_TOOLS, "--agent", "ai-workflow:away-answerer", "--model", "opus"]
assert argv[:-1] == [*want, "--effort", "medium"], argv
assert argv[-1].startswith("Answer the question round below"), argv[-1]
answerer = sp.call_args[0][0]
ui_sessions.update(answerer, session_id="sess-A", status="done")
argv = spawned(ui_runner.resume, answerer, "again")
want = ["claude", *RESTRICTED, "--allowedTools", AWAY_TOOLS, *GATE, "--effort", "medium", "--resume", "sess-A"]
assert argv == [*want, "again"], argv
ok("Away answerer: start, and resume keeps --effort only")

# ---- 7. grind re-entry (prgrind_tick) ---------------------------------------------------------
THREAD = "https://acme.slack.com/archives/C0123/p1700000000000100"
grind_dir = os.path.join(data_dir, "pr-grind")
os.makedirs(grind_dir, exist_ok=True)
state = os.path.join(grind_dir, "p1.md")
with open(state, "w") as f:
    f.write(
        "owner: o\nrepo: r\nnumber: 7\n"
        f"thread: {THREAD}\nreviewer: alice\nauthor: bob\n"
        "next-poll: 2030-06-01T11:00:00Z\npoll-since: 2030-06-01T10:00:00Z\nci-seen: abc green\n"
        "\n## Round 1\n"
    )
record(f"/pr-grind {THREAD}", status="done")
with (
    mock.patch.object(shared, "gh_json", return_value=({"state": "OPEN"}, "")),
    mock.patch.object(ci, "snapshot", return_value={"head_sha": "abc", "state": "green"}),
    mock.patch.object(ui_runner, "_new_review", return_value=None),
    capture() as sp,
):
    got = ui_runner.prgrind_tick(state, now=datetime(2030, 6, 1, 12, tzinfo=timezone.utc))
assert got == "started", got
assert sp.call_count == 1
argv = sp.call_args[0][1]
assert argv == ["claude", *BASE, "--append-system-prompt", REENTRY, f"/ai-workflow:pr-grind {THREAD}"], argv
kw = sp.call_args.kwargs
assert kw["command"] == f"/ai-workflow:pr-grind {THREAD}", kw
assert kw["env_extra"] == {"AIW_HEADLESS": "1"} and len(kw["pass_fds"]) == 1, kw
ok("grind re-entry")


# ---- 8. headless dispatch lane ----------------------------------------------------------------
class FakeSettings:
    @staticmethod
    def load():
        return {"commands": [{"label": "work", "cmd": "claude"}]}


headless = dispatch_runners.Headless(settings=FakeSettings)
lane = {"repo": work}
d = {"settings": {"model": "opus", "effort": "high", "account": "work"}}
argv = spawned(headless.start, lane, "/implement-issue 8", d)
assert argv == ["claude", *BASE, *GATE, "--effort", "high", "--model", "opus", "/ai-workflow:implement-issue 8"], argv
argv = spawned(headless.start, lane, "/implement-issue 9", {"settings": {}})
assert argv == ["claude", *BASE, *GATE, "/ai-workflow:implement-issue 9"], argv
ok("headless dispatch lane: --effort before --model")

# ---- 9. herdr dispatch lane -------------------------------------------------------------------
co = tempfile.mkdtemp()
dispatch.register_checkout("o/r", co)
calls: list = []


def cli(argv, timeout=60):
    calls.append(argv)
    out = (
        json.dumps({"result": {"tab": {"tab_id": "t1"}, "pane": {"pane_id": "p1"}}})
        if argv[:2] == ["tab", "create"]
        else ""
    )
    return subprocess.CompletedProcess(argv, 0, out, "")


herdr = dispatch_runners.Herdr("w1", cli)
lane = {"repo": "o/r", "n": 5}
herdr.start(lane, "/ai-workflow:implement-issue 5", {"id": "abc", "settings": {"model": "opus", "effort": "high"}})
agent_start = ["agent", "start", "aiw-abc-issue-5", "--kind", "claude", "--pane", "p1", "--timeout", "120000", "--"]
assert calls[1] == [*agent_start, "--dangerously-skip-permissions", "--model", "opus", "--effort", "high"], calls[1]
calls.clear()
herdr.start(lane, "/ai-workflow:implement-issue 5", {"id": "abc", "settings": {}})
assert calls[1] == [*agent_start, "--dangerously-skip-permissions"], calls[1]
ok("herdr dispatch lane: --model before --effort")

# ---- 10. account-limit queue bypass -----------------------------------------------------------
bypass = {
    "agent": {"agent": "ai-workflow:peer-reviewer"},
    "model": {"model": "opus"},
    "env_extra": {"env_extra": {"AIW_HEADLESS": "1"}},
    "pass_fds": {"pass_fds": [0]},
    "re-entry extra_args": {"extra_args": ["--append-system-prompt", REENTRY]},
    "dispatch effort extra_args": {"extra_args": ["--effort", "high"]},
}
queued = {"plain": {}, "run_model/effort": {"run_model": "opus", "effort": "high"}}
with mock.patch.object(ui_runner, "limits", return_value={"cc-x": {"limited_until": 4102444800}}):
    for i, (label, kw) in enumerate([*bypass.items(), *queued.items()]):
        with capture() as sp:
            rec = ui_runner.start(f"/implement-issue {100 + i}", work, claude_cmd="cc-x", **kw)
        if label in bypass:
            assert sp.call_count == 1, label
        else:
            assert sp.call_count == 0 and rec["status"] == "limited", (label, rec)
ok("limit queue: agent/model/env_extra/pass_fds/extra_args bypass it, run model/effort alone does not")

preflight.stop()
print(f"\n{passed} checks passed")
