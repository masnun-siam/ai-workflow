#!/usr/bin/env python3
"""Self-check for usage-limit handling in ui_runner. `python3 test_ui_limits.py` — exit 0 = green."""

from __future__ import annotations

import json
import os
import re
import stat
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

root = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = os.path.join(root, "data")
os.environ["HOME"] = root  # ~/.claude-profiles/* resolve under the sandbox
work = os.path.join(root, "work")
os.makedirs(work)
bindir = os.path.join(root, "bin")
os.makedirs(bindir)
STREAMS = os.path.join(root, "streams")
os.makedirs(STREAMS)
for name in ("claude", "cc-profile"):
    p = os.path.join(bindir, name)
    with open(p, "w") as f:  # `<cmd> auth ...` -> logged in; else log argv and play $FAKE_STREAM
        f.write(f"""#!/bin/sh
if [ "$1" = "auth" ] || [ "$2" = "auth" ]; then echo '{{"loggedIn": true}}'; exit 0; fi
echo "{name} $*" >> {root}/calls
cat {STREAMS}/$(cat {root}/mode)
""")
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
os.environ["PATH"] = bindir + os.pathsep + os.environ["PATH"]

import ui_runner  # noqa: E402
import ui_sessions  # noqa: E402

INIT = '{"type":"system","subtype":"init","session_id":"sess-1"}'
REJECT = ('{"type":"rate_limit_event","rate_limit_info":{"status":"rejected","resetsAt":%d,'
          '"rateLimitType":"five_hour"}}')
ERR = '{"type":"result","is_error":true,"result":"You\'ve hit your limit"}'
OK = '{"type":"result","is_error":false,"total_cost_usd":0.1}'
WARN = ('{"type":"rate_limit_event","rate_limit_info":{"status":"allowed_warning",'
        '"resetsAt":%d,"rateLimitType":"seven_day","utilization":0.95}}')


def stream(name, *lines):
    with open(os.path.join(STREAMS, name), "w") as f:
        f.write("\n".join(lines) + "\n")


def mode(name):
    with open(os.path.join(root, "mode"), "w") as f:
        f.write(name)


def wait(sid, status, t=10):
    end = time.time() + t
    while time.time() < end:
        rec = ui_sessions.load(sid)
        if rec["status"] == status:
            return rec
        time.sleep(0.05)
    raise AssertionError((status, ui_sessions.load(sid)))


def calls():
    p = os.path.join(root, "calls")
    return open(p).read().splitlines() if os.path.exists(p) else []


future = int(time.time()) + 3600
past = int(time.time()) - 60

# rejected event + error result -> limited with reset time, auto-resume on
stream("limit", INIT, REJECT % future, ERR)
mode("limit")
a = ui_runner.start("/run-issue 1", work)
rec = wait(a["id"], "limited")
assert rec["limit_resets_at"] == future and rec["auto_resume"] is True and rec["limit_type"] == "five_hour"
assert rec["session_id"] == "sess-1" and rec["claude_cmd"] == "claude"
assert ui_runner.limits()["claude"]["limited_until"] == future

# not due yet -> tick leaves it; due -> auto-resumes with --resume and the continue prompt
assert ui_runner.limit_tick(stagger=0) == []
stream("ok", INIT, OK)
mode("ok")
ui_sessions.update(a["id"], limit_resets_at=past)
assert ui_runner.limit_tick(stagger=0) == [a["id"]]
assert wait(a["id"], "done")["limit_resets_at"] is None
assert any("--resume sess-1" in c and ui_runner.CONTINUE_PROMPT in c for c in calls()), calls()

# cancel-auto stops the timer; manual resume still works; stop works on a limited run
mode("limit")
b = ui_runner.start("/run-issue 2", work)
wait(b["id"], "limited")
ui_sessions.update(b["id"], limit_resets_at=past)
ui_runner.cancel_auto(b["id"])
assert ui_runner.limit_tick(stagger=0) == []
assert ui_runner.stop(b["id"])["status"] == "stopped"

# limit text without a reset time -> limited, no auto-resume
stream("nolimit_time", INIT, ERR)
mode("nolimit_time")
c = ui_runner.start("/run-issue 3", work)
rec = wait(c["id"], "limited")
assert rec["limit_resets_at"] is None and rec["auto_resume"] is False
assert ui_runner.limit_tick(stagger=0) == []

# plain failure stays failed
stream("boom", INIT, '{"type":"result","is_error":true,"result":"boom"}')
mode("boom")
d = ui_runner.start("/run-issue 4", work)
assert wait(d["id"], "failed")["status"] == "failed"

# new run on a limited account is queued, then started by the timer at reset
mode("limit")
e = ui_runner.start("/run-issue 5", work)
wait(e["id"], "limited")
n_calls = len(calls())
q = ui_runner.start("/run-issue 6", work)
assert q["status"] == "limited" and q["auto_resume"] and q["limit_resets_at"] >= future - 5
assert len(calls()) == n_calls  # nothing spawned
stream("ok", INIT, OK)
mode("ok")
ui_sessions.update(q["id"], limit_resets_at=past)
ui_runner.limit_tick(stagger=0)
wait(q["id"], "done")
assert any(c.endswith("/run-issue 6") for c in calls()), calls()  # no session_id -> fresh start

# resume on another account: transcript copied into that profile, run rebound
slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(work))
src = os.path.join(root, ".claude", "projects", slug)
os.makedirs(src)
with open(os.path.join(src, "sess-1.jsonl"), "w") as f:
    f.write("{}\n")
os.environ.pop("CLAUDE_CONFIG_DIR", None)
f_ = ui_runner.start("/run-issue 7", work, claude_cmd="cc other")
wait(f_["id"], "done")
while f_["id"] in ui_runner._procs:
    time.sleep(0.05)
ui_sessions.update(f_["id"], status="limited", claude_cmd="claude", session_id="sess-1")
ui_runner.resume_stopped(f_["id"], "cc work")
dst = os.path.join(root, ".claude-profiles", "work", "projects", slug, "sess-1.jsonl")
assert os.path.isfile(dst)
assert ui_sessions.load(f_["id"])["claude_cmd"] == "cc work"
time.sleep(0.5)
assert any(c.startswith("cc-profile work") and "--resume sess-1" in c for c in calls()), calls()

# warning chip data
ui_runner._usage["cc work"] = json.loads(WARN % future)["rate_limit_info"]
assert ui_runner.limits()["cc work"]["warning"]["utilization"] == 0.95
print("ui_limits: all checks passed")
