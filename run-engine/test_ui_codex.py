#!/usr/bin/env python3
"""Self-check for the Codex adapter end to end (issue #878). `python3 test_ui_codex.py` — exit 0 = green.

A fake `codex` on PATH answers `login status` by $FAKE_CODEX_LOGIN and, for `exec`, records its argv and
environment and prints Codex JSONL. A temp data dir holds a Codex account in ui_settings.json.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DATA = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = DATA

import harness  # noqa: E402
import harness_codex  # noqa: E402
import repo_skills  # noqa: E402
import ui_runner  # noqa: E402
import ui_sessions  # noqa: E402
import ui_settings  # noqa: E402
from harness_claude import HEADLESS_PROMPT  # noqa: E402

passed = 0
FAKE = r"""#!/bin/sh
if [ "$1" = login ] && [ "$2" = status ]; then
  [ -n "$FAKE_CODEX_SAY" ] && echo "$FAKE_CODEX_SAY" >&2
  exit "${FAKE_CODEX_LOGIN:-0}"
fi
echo exec >> "$FAKE_DIR/calls"
printf '%s\0' "$@" > "$FAKE_DIR/argv"
printf '%s\n%s\n' "$AIW_UI_SESSION" "$CLAUDE_PLUGIN_DATA" > "$FAKE_DIR/env"
echo '{"type":"thread.started","thread_id":"th-1"}'
echo '{"type":"item.completed","item":{"id":"i0","type":"agent_message","text":"hi"}}'
[ "$FAKE_CODEX_USAGE" = none ] || printf '{"type":"turn.completed","usage":%s}\n' "$FAKE_CODEX_USAGE"
"""
FAKE_DIR = tempfile.mkdtemp()
BIN = os.path.join(FAKE_DIR, "bin")
os.mkdir(BIN)
with open(os.path.join(BIN, "codex"), "w") as f:
    f.write(FAKE)
os.chmod(os.path.join(BIN, "codex"), 0o755)
os.environ["PATH"] = BIN + os.pathsep + os.environ.get("PATH", "")
os.environ["FAKE_DIR"] = FAKE_DIR


def usage(i: int, c: int, o: int) -> None:
    """The cumulative thread usage the fake prints in the next run's one `turn.completed` (codex-cli 0.166.0)."""
    os.environ["FAKE_CODEX_USAGE"] = json.dumps({"input_tokens": i, "cached_input_tokens": c, "output_tokens": o})


def tok(i: int, c: int, o: int) -> dict:
    return {"input": i, "cached": c, "output": o}


usage(1, 0, 1)
with open(os.path.join(DATA, "ui_settings.json"), "w") as f:
    json.dump(
        {
            "commands": [
                {"label": "Claude", "cmd": "claude"},
                {"label": "Codex", "cmd": "codex", "harness": "codex", "models": []},
            ],
            "default": "Claude",
        },
        f,
    )
FLAGS = ["--json", harness_codex.BYPASS_FLAG, "--skip-git-repo-check"]
EXE = os.path.join(BIN, "codex")


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


def argv() -> list:
    with open(os.path.join(FAKE_DIR, "argv")) as f:
        return f.read().split("\0")[:-1]


def calls() -> int:
    try:
        with open(os.path.join(FAKE_DIR, "calls")) as f:
            return len(f.read().split())
    except FileNotFoundError:
        return 0


def finished(sid: str) -> dict:
    end = time.time() + 20
    while time.time() < end:
        rec = ui_sessions.load(sid)
        if rec.get("status") not in ("starting", "running") and sid not in ui_runner._procs:
            return rec
        time.sleep(0.05)
    raise AssertionError(f"session {sid} did not finish: {ui_sessions.load(sid)}")


# 1. Contract
CONTRACT = [
    "ID",
    "CUMULATIVE_USAGE",
    "preflight",
    "check_login",
    "start_argv",
    "resume_argv",
    "parse_line",
    "resume_command",
    "skill_text",
]
for ad in (harness.get("claude"), harness.get("codex")):
    assert all(hasattr(ad, n) for n in CONTRACT), [n for n in CONTRACT if not hasattr(ad, n)]
assert harness_codex.ID == "codex"
assert harness.get("codex") is harness.for_record({"harness": "codex"}) is harness.for_cmd("codex") is harness_codex
ok("contract: codex exposes every name, the registry resolves it")

# 3. Mapping paragraph
plugin = os.path.dirname(HERE)
for s in (
    "AskUserQuestion",
    "aiw ask",
    "SKILL.md",
    ".claude/skills/<name>/SKILL.md",
    "Agent/subagent or SendMessage",
    "ScheduleWakeup/Monitor",
    f"{plugin}/skills/<name>/SKILL.md",
):
    assert s in harness_codex.TOOL_MAPPING, s
assert "<plugin>" not in harness_codex.TOOL_MAPPING
ok("mapping paragraph: every mapping, <plugin> replaced with the plugin dir")

# 2. Gated start: argv, prompt, stored command; a fresh thread's tokens as reported (8, #907)
work = tempfile.mkdtemp()
usage(14196, 10880, 5)
sid = ui_runner.start("/ai-workflow:implement-issue 12", work, gate_questions=True, claude_cmd="codex")["id"]
rec = finished(sid)
a = argv()
assert a[:4] == ["exec", *FLAGS] and len(a) == 5, a[:4]
assert a[4].startswith(HEADLESS_PROMPT + "\n\n" + harness_codex.TOOL_MAPPING + "\n\n"), a[4][:300]
skill = repo_skills.codex_prompt("/ai-workflow:implement-issue 12", work)
assert a[4].endswith(skill) and skill.endswith("ARGUMENTS: 12"), a[4][-200:]
assert f"Base directory for this skill: {plugin}/skills/implement-issue" in a[4]
assert rec["command"] == "/ai-workflow:implement-issue 12" and rec["harness"] == "codex", rec
assert rec["session_id"] == "th-1", rec
assert rec["tokens"] == rec["tokens_total"] == tok(14196, 10880, 5) and rec.get("cost") is None, rec
ok("gated start: exec argv, headless + mapping + skill prompt, short command, tokens as reported, no cost")

# 7. Environment
with open(os.path.join(FAKE_DIR, "env")) as f:
    assert f.read().split("\n")[:2] == [sid, DATA]
ok("environment: AIW_UI_SESSION and CLAUDE_PLUGIN_DATA reach the child")

# 5. Follow-up and answer: resume argv, prompt only, skill-resolved; tokens per run (8, #907)
usage(28416, 24960, 34)
assert ui_runner.send_prompt(sid, "now run /ai-workflow:create-tasks docs/prds/x.md") == "sent"
rec = finished(sid)
a = argv()
assert a[:6] == ["exec", "resume", *FLAGS, "th-1"] and len(a) == 7, a[:6]
assert a[6] == repo_skills.codex_prompt("now run /ai-workflow:create-tasks docs/prds/x.md", work)
assert HEADLESS_PROMPT not in a[6] and harness_codex.TOOL_MAPPING not in a[6]
assert rec["tokens"] == tok(14220, 14080, 29) and rec["tokens_total"] == tok(28416, 24960, 34), rec
assert rec.get("cost") is None, rec
ui_sessions.update(sid, status="waiting", pending_question={"id": "q-1"})
usage(42684, 39040, 328)
ui_runner.resume(sid, "Answer to q-1: yes")
rec = finished(sid)
assert argv()[6] == "Answer to q-1: yes", argv()[6]
assert rec["tokens"] == tok(14268, 14080, 294) and rec["tokens_total"] == tok(42684, 39040, 328), rec
ui_sessions.update(sid, status="stopped")
os.environ["FAKE_CODEX_USAGE"] = "none"  # a run with no turn.completed keeps the stored total
ui_runner.resume_stopped(sid)
rec = finished(sid)
assert argv()[6] == ui_runner.CONTINUE_PROMPT and argv()[1] == "resume"
assert rec["tokens_total"] == tok(42684, 39040, 328), rec
ui_sessions.update(sid, status="limited", pending_answer="/ai-workflow:create-tasks docs/prds/x.md")
usage(50000, 45000, 400)
ui_runner.resume_stopped(sid)
rec = finished(sid)
assert argv()[6] == repo_skills.codex_prompt("/ai-workflow:create-tasks docs/prds/x.md", work), argv()[6][:200]
assert rec["tokens"] == tok(7316, 5960, 72) and rec["tokens_base"] == tok(42684, 39040, 328), rec
ok("resume: exec resume argv, no preamble, follow-up skill-resolved, tokens per run, a run without usage skipped")

# replay after a UI restart: re-reading the whole stream ends on the live result
live = rec["tokens"]
dead = subprocess.Popen(["true"])
dead.wait()
ui_sessions.update(sid, status="running", tokens=None)
ui_runner._procs[sid] = None
ui_runner._follow(sid, None, dead.pid, "Thu Jan  1 00:00:00 1970")
rec = ui_sessions.load(sid)
assert rec["tokens"] == live and rec["tokens_total"] == tok(50000, 45000, 400), rec
ok("replay: re-attaching reads every run's usage and ends with the live per-run tokens")

# clamping: a reported value below the base gives 0
ui_sessions.update(sid, status="stopped")
usage(10, 50000, 500)
ui_runner.resume_stopped(sid)
rec = finished(sid)
assert rec["tokens"] == tok(0, 5000, 100), rec
# an old record with no stored total: the first resumed run as reported
ui_sessions.update(sid, status="stopped", tokens_total=None)
usage(60000, 55000, 600)
ui_runner.resume_stopped(sid)
assert finished(sid)["tokens"] == tok(60000, 55000, 600)
ok("tokens: a drop below the base clamps at 0; a record from before #907 records its first run as reported")

# limited before any thread id: starts over, gated, a new thread with no base
ui_sessions.update(sid, status="limited", session_id=None)
usage(900, 800, 7)
ui_runner.resume_stopped(sid)
rec = finished(sid)
assert argv()[1] == "--json" and argv()[4].startswith(HEADLESS_PROMPT) and argv()[4].endswith(skill)
assert rec.get("tokens_base") is None and rec["tokens"] == rec["tokens_total"] == tok(900, 800, 7), rec
ok("resume_stopped with no thread id: a fresh gated start with the skill prompt, tokens as reported")

# repo copy: base dir is the repo copy, command is the repo spelling
os.makedirs(os.path.join(work, ".claude", "skills", "implement-issue"))
with open(os.path.join(work, ".claude", "skills", "implement-issue", "SKILL.md"), "w") as f:
    f.write("---\nname: implement-issue\n---\nrepo body\n")
sid2 = ui_runner.start("/ai-workflow:implement-issue 12", work, gate_questions=True, claude_cmd="codex")["id"]
rec = finished(sid2)
assert rec["command"] == "/implement-issue 12", rec["command"]
assert f"Base directory for this skill: {work}/.claude/skills/implement-issue\n\nrepo body" in argv()[4]
ok("repo copy: its base directory in the prompt, repo spelling stored")

# 4. Non-gated start and the re-entry instructions; queued start (_start_claimed)
finished(ui_runner.start("plain text", work, claude_cmd="codex")["id"])
assert argv()[4] == "plain text"
finished(ui_runner.start("/pr-grind 7", work, instructions=[ui_runner.REENTRY_PROMPT], claude_cmd="codex")["id"])
assert argv()[4].startswith(ui_runner.REENTRY_PROMPT + "\n\n" + harness_codex.TOOL_MAPPING)
q = ui_sessions.create("/ai-workflow:implement-issue 12", work, claude_cmd="codex", harness="codex")
q = ui_sessions.update(q["id"], status="starting", cwd_path=work, command="/ai-workflow:implement-issue 12")
ui_sessions.update(q["id"], tokens_base=tok(1, 1, 1), tokens_total=tok(1, 1, 1))  # a fresh start drops both
usage(30, 20, 3)
ui_runner._start_claimed(q)
rec = finished(q["id"])
assert rec.get("tokens_base") is None and rec["tokens"] == rec["tokens_total"] == tok(30, 20, 3), rec
assert argv()[4].startswith(HEADLESS_PROMPT) and "repo body" in argv()[4]
ok("starts: no instructions = skill prompt only; re-entry and queued starts carry the preamble")

with (
    mock.patch.object(ui_runner.subprocess, "Popen", side_effect=OSError("no exec")),
    mock.patch.object(ui_runner, "_preflight", return_value=[EXE]),
):
    try:
        ui_runner.start("plain text", work, claude_cmd="codex")
        raise AssertionError("expected RunnerError")
    except ui_runner.RunnerError as e:
        assert str(e) == "failed to spawn codex: no exec", e
ok("a spawn failure names the harness")

# 6. Login
n = calls()
os.environ["FAKE_CODEX_LOGIN"] = "1"
os.environ["FAKE_CODEX_SAY"] = "Not logged in"
base = "codex CLI is not logged in, run `codex login`"
try:
    ui_runner.start("/ai-workflow:implement-issue 12", work, claude_cmd="codex")
    raise AssertionError("expected RunnerError")
except ui_runner.RunnerError as e:
    assert str(e) == base + " (Not logged in)", e
rec = ui_sessions.list_sessions()[0]
assert rec["status"] == "failed" and rec["error"] == base + " (Not logged in)" and calls() == n
assert ui_settings.check_login("codex") == {"ok": False, "message": base + " (Not logged in)"}
os.environ["FAKE_CODEX_SAY"] = ""
assert ui_settings.check_login("codex") == {"ok": False, "message": base}
os.environ["FAKE_CODEX_LOGIN"] = "0"
assert ui_settings.check_login("codex") == {"ok": True, "message": "logged in"}
assert harness_codex.check_login("nope-codex-878") == {
    "ok": False,
    "message": "codex command 'nope-codex-878' unusable: 'nope-codex-878' not found on PATH",
}
with mock.patch.object(ui_settings, "argv", side_effect=ValueError("x")):
    assert harness_codex.check_login("codex")["message"] == "codex CLI not found on PATH"
os.environ["FAKE_CODEX_LOGIN"] = "1"
os.environ["FAKE_CODEX_SAY"] = "caf\xe9"
real_run = subprocess.run
with mock.patch.object(
    subprocess, "run", lambda a, **k: real_run(["sh", "-c", "printf 'caf\\351\\n' >&2; exit 1"], **k)
):
    assert harness_codex.check_login("codex")["message"] == base + " (caf\ufffd)"
os.environ["FAKE_CODEX_LOGIN"] = "0"
with mock.patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(["codex"], 30)):
    m = harness_codex.check_login("codex")["message"]
    assert m.startswith(base + " (login status check failed: ") and m.endswith(")"), m
    try:
        harness_codex.preflight("codex")
        raise AssertionError("expected LoginError")
    except harness.LoginError as e:
        assert str(e) == m
ok("login: messages for logged out, silent CLI, not on PATH, unusable, timeout; no exec when it fails")

# 9. Resume command
d = tempfile.mkdtemp()
path = os.path.join(d, "a dir $(touch PWNED)")
os.mkdir(path)
for cmd, words in [("codex", ["codex"]), ('codex -p "my profile"', ["codex", "-p", "my profile"])]:
    rc = harness_codex.resume_command(cmd, path, "th-1")
    assert shlex.split(rc) == ["cd", path, "&&", *words, "resume", "th-1"], rc
    subprocess.run(
        ["sh", "-c", rc], cwd=d, env={**os.environ, "FAKE_DIR": tempfile.mkdtemp()}, check=True, capture_output=True
    )
    assert not os.path.exists(os.path.join(d, "PWNED")) and not os.path.exists(os.path.join(path, "PWNED"))
assert harness_codex.resume_command("codex", "", "th-1") is None
assert harness_codex.resume_command("codex", path, None) is None
ok("resume_command: every word quoted, survives sh -c, None without path or id")

print(f"{passed} passed")
