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
for name in ("codex", "codex2"):  # `<cmd> login status` -> logged in; else log argv and play $FAKE_STREAM
    p = os.path.join(bindir, name)
    with open(p, "w") as f:
        f.write(f"""#!/bin/sh
if [ "$1" = "login" ]; then exit 0; fi
echo "{name} $*" >> {root}/calls
cat {STREAMS}/$(cat {root}/mode)
""")
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
os.environ["PATH"] = bindir + os.pathsep + os.environ["PATH"]

import ui_notify  # noqa: E402

ui_notify.send_mac = lambda *a, **k: None  # the fan-out would show a real banner
import ui_runner  # noqa: E402
import ui_sessions  # noqa: E402

INIT = '{"type":"system","subtype":"init","session_id":"sess-1"}'
REJECT = '{"type":"rate_limit_event","rate_limit_info":{"status":"rejected","resetsAt":%d,"rateLimitType":"five_hour"}}'
ERR = '{"type":"result","is_error":true,"result":"You\'ve hit your limit"}'
OK = '{"type":"result","is_error":false,"total_cost_usd":0.1}'
WARN = (
    '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed_warning",'
    '"resetsAt":%d,"rateLimitType":"seven_day","utilization":0.95}}'
)


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
a = ui_runner.start("/implement-issue 1", work)
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
b = ui_runner.start("/implement-issue 2", work)
wait(b["id"], "limited")
ui_sessions.update(b["id"], limit_resets_at=past)
ui_runner.cancel_auto(b["id"])
assert ui_runner.limit_tick(stagger=0) == []
assert ui_runner.stop(b["id"])["status"] == "stopped"

# a limited answerer is never auto-resumed
mode("limit")
d_ = ui_runner.start("/implement-issue 4", work)
wait(d_["id"], "limited")
ui_sessions.update(d_["id"], limit_resets_at=past, role=ui_sessions.ANSWERER_ROLE)
r_ = ui_runner.limit_tick(stagger=0)
assert r_ == [], (r_, d_["id"], a["id"])
assert ui_runner.stop(d_["id"])["status"] == "stopped"

# limit text without a reset time -> limited, no auto-resume
stream("nolimit_time", INIT, ERR)
mode("nolimit_time")
c = ui_runner.start("/implement-issue 3", work)
rec = wait(c["id"], "limited")
assert rec["limit_resets_at"] is None and rec["auto_resume"] is False
assert ui_runner.limit_tick(stagger=0) == []

# plain failure stays failed
stream("boom", INIT, '{"type":"result","is_error":true,"result":"boom"}')
mode("boom")
d = ui_runner.start("/implement-issue 4", work)
assert wait(d["id"], "failed")["status"] == "failed"

# new run on a limited account is queued, then started by the timer at reset
mode("limit")
e = ui_runner.start("/implement-issue 5", work)
wait(e["id"], "limited")
n_calls = len(calls())
q = ui_runner.start("/implement-issue 6", work)
assert q["status"] == "limited" and q["auto_resume"] and q["limit_resets_at"] >= future - 5
assert len(calls()) == n_calls  # nothing spawned
stream("ok", INIT, OK)
mode("ok")
ui_sessions.update(q["id"], limit_resets_at=past)
ui_runner.limit_tick(stagger=0)
wait(q["id"], "done")
assert any(c.endswith("/ai-workflow:implement-issue 6") for c in calls()), (
    calls()
)  # no session_id -> fresh start, resolved (#439)

# resume on another account: transcript copied into that profile, run rebound
slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(work))
src = os.path.join(root, ".claude", "projects", slug)
os.makedirs(src)
with open(os.path.join(src, "sess-1.jsonl"), "w") as f:
    f.write("{}\n")
os.environ.pop("CLAUDE_CONFIG_DIR", None)
f_ = ui_runner.start("/implement-issue 7", work, claude_cmd="cc other")
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

# hold: a limited session stays put until release; guards; a held queued prompt waits for release
h_ = ui_sessions.create("/implement-issue 6", work)
for bad in ("done", "failed", "stopped", "queued"):
    ui_sessions.update(h_["id"], status=bad)
    try:
        ui_runner.hold(h_["id"])
        raise AssertionError(f"held a {bad} session")
    except ui_runner.Conflict:
        pass
try:
    ui_runner.release(h_["id"])
    raise AssertionError("released a session that is not held")
except ui_runner.Conflict:
    pass
for live_ in ("starting", "running", "waiting", "limited"):
    ui_sessions.update(h_["id"], status=live_)
    assert ui_runner.hold(h_["id"])["hold"] is True
ui_sessions.update(h_["id"], limit_resets_at=past, auto_resume=True, session_id="sess-1")
assert ui_runner.limit_tick(stagger=0) == []
assert ui_sessions.load(h_["id"])["status"] == "limited"
ui_runner.release(h_["id"])
assert ui_sessions.load(h_["id"]).get("hold") is None
ui_sessions.update(h_["id"], auto_resume=False)

sent_ = []
real_send, ui_runner.send_prompt = ui_runner.send_prompt, lambda sid, text: sent_.append((sid, text))
ui_sessions.update(h_["id"], status="running", queued_prompt="next")
ui_runner.hold(h_["id"])
ui_sessions.update(h_["id"], status="done")
ui_runner._deliver_queued(h_["id"])
assert sent_ == [] and ui_sessions.load(h_["id"])["queued_prompt"] == "next"
ui_runner.release(h_["id"])
assert sent_ == [(h_["id"], "next")]
sent_.clear()
ui_sessions.update(h_["id"], status="running", queued_prompt="later", hold=True)
ui_runner.release(h_["id"])  # still running: it goes out when the run ends
assert sent_ == [] and ui_sessions.load(h_["id"])["queued_prompt"] == "later"
ui_runner.send_prompt = real_send
ui_sessions.update(h_["id"], status="stopped", queued_prompt=None)

# ---- Codex: resume and auto-resume stay on the session's harness (#882) ----
import ui_settings  # noqa: E402

# PROVISIONAL: hand-written Codex lines until the real G1 fixture exists
CX_INIT = '{"type":"thread.started","thread_id":"th-1"}'
CX_LIMIT = '{"type":"turn.failed","error":{"message":"You\'ve hit your usage limit."}}'
CX_OK = '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}'
stream("cx_limit", CX_INIT, CX_LIMIT)
stream("cx_ok", CX_INIT, CX_OK)
CX = {"label": "Codex", "cmd": "codex", "harness": "codex"}
CX2 = {"label": "Codex2", "cmd": "codex2", "harness": "codex"}


def settings(*accounts, default="claude"):
    ui_settings.save({"commands": list(accounts), "default": default})


def settle(sid):
    end = time.time() + 10
    while sid in ui_runner._procs and time.time() < end:
        time.sleep(0.05)


def refused(fn, msg):
    try:
        fn()
    except ui_runner.Conflict as e:
        assert str(e) == msg, (str(e), msg)
        assert isinstance(e, ui_runner.RunnerError)
        return
    raise AssertionError(f"not refused: {msg}")


def stopped(cmd, harness, n, sid_="th-1"):
    return ui_sessions.create(f"/implement-issue {n}", work, claude_cmd=cmd, harness=harness)["id"], sid_


settings(CX, CX2)

# no reset time: limited, auto-resume after a doubling wait on its own account
mode("cx_limit")
g = ui_runner.start("/implement-issue 20", work, claude_cmd="codex")["id"]
t0 = time.time()
rec = wait(g, "limited")
settle(g)
assert rec["harness"] == "codex" and rec["session_id"] == "th-1" and rec["claude_cmd"] == "codex", rec
assert rec["auto_resume"] is True and rec["limit_backoff"] == 1 and abs(rec["limit_resets_at"] - (t0 + 60)) <= 5, rec
assert ui_runner.limit_tick(now=t0 + 30, stagger=0) == []
n_calls = len(calls())
assert ui_runner.limit_tick(now=t0 + 70, stagger=0) == [g]
t1 = time.time()
rec = wait(g, "limited")
settle(g)
assert any(c.startswith("codex exec resume") and "th-1" in c for c in calls()[n_calls:]), calls()
assert rec["limit_backoff"] == 2 and abs(rec["limit_resets_at"] - (t1 + 120)) <= 5 and rec["claude_cmd"] == "codex"
ui_sessions.update(g, limit_backoff=6)
ui_runner._mark_limited(g, None, "x")
rec = ui_sessions.load(g)
assert rec["limit_backoff"] == 7 and abs(rec["limit_resets_at"] - (time.time() + 3600)) <= 5, rec
soon = future - 1000  # before the Claude sessions' reset above, so the tick resumes only this one
ui_runner._mark_limited(g, {"resets_at": soon}, "x")  # a reset time clears the count
assert ui_sessions.load(g)["limit_backoff"] is None and ui_sessions.load(g)["limit_resets_at"] == soon
ui_sessions.update(g, limit_backoff=3)

# with a reset time: not before it, resumed after it; a run without a limit clears the count
mode("cx_ok")
assert ui_runner.limit_tick(now=soon - 10, stagger=0) == []
assert ui_runner.limit_tick(now=soon + 10, stagger=0) == [g]
rec = wait(g, "done")
settle(g)
assert rec.get("limit_backoff") is None and rec["claude_cmd"] == "codex", rec

# Claude: a no-reset limit never gets a back-off count
assert ui_sessions.load(c["id"]).get("limit_backoff") is None and ui_sessions.load(c["id"])["auto_resume"] is False

# own account removed, or switched to another harness: stays limited, auto-resume off, note, no retry
for accounts, label in (((CX,), "codex2"), ((CX, {**CX2, "harness": "claude"}), "Codex2")):
    settings(CX, CX2)
    k, _ = stopped("codex2", "codex", 21)
    ui_sessions.update(k, status="limited", session_id="th-1", auto_resume=True, limit_resets_at=past)
    settings(*accounts)
    n_calls = len(calls())
    assert ui_runner.limit_tick(stagger=0) == []
    rec = ui_sessions.load(k)
    want = f"account {label} is no longer a codex account; resume it on a codex account"
    assert rec["status"] == "limited" and rec["auto_resume"] is False and rec["note"] == want, rec
    assert ui_runner.limit_tick(stagger=0) == [] and ui_sessions.load(k) == rec and len(calls()) == n_calls
    ui_sessions.update(k, status="stopped")

# a limited Claude session whose account turned Codex: auto-resume off with the note, not a retry every tick
settings({"label": "Work", "cmd": "cc work", "harness": "codex"})
k, _ = stopped("cc work", None, 26)
ui_sessions.update(k, status="limited", session_id="sess-1", auto_resume=True, limit_resets_at=past)
n_calls = len(calls())
assert ui_runner.limit_tick(stagger=0) == [] and len(calls()) == n_calls
rec = ui_sessions.load(k)
assert rec["auto_resume"] is False and rec["note"] == (
    "account Work is no longer a claude account; resume it on a claude account"
), rec
ui_sessions.update(k, status="stopped")

# cross-harness resume refused: nothing spawned, nothing copied, record unchanged
settings(CX, CX2)
k, _ = stopped("codex", "codex", 22)
ui_sessions.update(k, status="limited", session_id="th-1", auto_resume=True, limit_resets_at=future, limit_backoff=2)
before, n_calls = ui_sessions.load(k), len(calls())
refused(lambda: ui_runner.resume_stopped(k, "cc work"), "this session ran on codex; pick a codex account")
assert ui_sessions.load(k) == before and len(calls()) == n_calls
ui_sessions.update(k, status="stopped")
k, _ = stopped("cc other", None, 23)
ui_sessions.update(k, status="limited", session_id="sess-1")
before = ui_sessions.load(k)
refused(lambda: ui_runner.resume_stopped(k, "codex"), "this session ran on claude; pick a claude account")
assert ui_sessions.load(k) == before and len(calls()) == n_calls
ui_sessions.update(k, status="stopped")

# Codex account removed: a Codex default takes over; a Claude default refuses before any claim
k, _ = stopped("codex2", "codex", 24)
ui_sessions.update(k, status="stopped", session_id="th-1")
settings(CX, default="Codex")
mode("cx_ok")
ui_runner.resume_stopped(k)
assert wait(k, "done")["claude_cmd"] == "codex"
settle(k)
assert calls()[-1].startswith("codex exec resume") and "th-1" in calls()[-1], calls()[-1]
ui_sessions.update(k, claude_cmd="codex2", status="stopped")
settings(CX)
n_calls = len(calls())
gone = "account codex2 was removed; pick a codex account"
refused(lambda: ui_runner.resume_stopped(k), gone)
refused(lambda: ui_runner.send_prompt(k, "next"), gone)
refused(lambda: ui_runner.resume(k, "an answer"), gone)
assert ui_sessions.load(k)["status"] == "stopped" and len(calls()) == n_calls

# Claude account removed: resumed on its recorded command, whatever the default is
k, _ = stopped("cc gone", None, 25)
ui_sessions.update(k, status="stopped", session_id="sess-1")
settings(CX, default="Codex")
mode("ok")
ui_runner.resume_stopped(k)
assert wait(k, "done")["claude_cmd"] == "cc gone"
settle(k)
assert calls()[-1].startswith("cc-profile gone") and "--resume sess-1" in calls()[-1], calls()[-1]
assert not os.path.exists(os.path.join(root, ".claude-profiles", "gone"))
settings()

# warning chip data
ui_runner._usage["cc work"] = json.loads(WARN % future)["rate_limit_info"]
assert ui_runner.limits()["cc work"]["warning"]["utilization"] == 0.95
print("ui_limits: all checks passed")
