#!/usr/bin/env python3
"""Self-check for run-engine/ui_afk.py. `python3 test_ui_afk.py` — exit 0 = green."""

from __future__ import annotations

import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
d = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = d
for k in [k for k in os.environ if k.startswith("AIW_NTFY_")]:
    del os.environ[k]

import ui_afk  # noqa: E402
import ui_notify  # noqa: E402

ui_notify.send_mac = lambda *a, **k: None  # the fan-out would show a real banner
import ui_runner  # noqa: E402
import ui_sessions  # noqa: E402

resumed, retried, pushed = [], [], []
ui_runner.resume = lambda sid, text: resumed.append((sid, text)) or ui_sessions.update(sid, status="running")
ui_runner.resume_stopped = lambda sid, cmd=None: (
    retried.append(sid) or ui_sessions.update(sid, status="running", ended_at=None)
)
ui_notify.load_config = lambda: {"ntfy": {"server": "https://ntfy.example", "topic": "t"}}


class _Resp:
    def close(self):
        pass


ui_notify.urllib.request.urlopen = lambda req, timeout=None: (
    pushed.append((req.headers.get("Title"), req.data.decode())) or _Resp()
)


def Q(label="Approve and start (Recommended)", rec=True):
    return {
        "id": "q-1",
        "questions": [
            {
                "header": "Plan",
                "question": "Approve the plan?",
                "multiSelect": False,
                "options": [{"label": label if rec else "Approve"}, {"label": "Abort"}],
            }
        ],
    }


def waiting(rec=True, sid_ok=True, command="/implement-issue 1"):
    s = ui_sessions.create(command, d, {"owner": "o", "repo": "r", "issue": 1})
    if sid_ok:
        ui_sessions.update(s["id"], session_id="abc")
    ui_sessions.set_pending(s["id"], Q(rec=rec))
    return s["id"]


now = time.time()

# off: nothing is touched, and the waiting push still goes out
a = waiting()
ui_afk.tick(now)
assert not resumed and not ui_afk.active(now)
assert any("waiting" in (t or "") for t, _ in pushed), pushed

# start validation
for bad in (None, "x", True, now - 1, now + ui_afk.MAX_SECONDS + 10):
    try:
        ui_afk.start(bad, now)
        raise AssertionError(f"accepted {bad!r}")
    except ValueError:
        pass
pub = ui_afk.start(now + 3600, now)
assert pub["active"] and pub["until"] == now + 3600 and ui_afk.active(now)

# recommended round: answered with the recommended label via the normal answer text
pushed.clear()
b = waiting(rec=False)  # no recommendation -> held, and no push while AFK
assert not pushed, pushed
ui_runner._procs[a] = None  # claude still exiting after `aiw ask`: wait
ui_afk.tick(now)
assert not resumed
del ui_runner._procs[a]
ui_afk.tick(now)
assert resumed == [(a, 'Answer to q-1: {"0":{"labels":["Approve and start (Recommended)"]}}')], resumed
assert ui_sessions.load(b)["status"] == "waiting"
log = ui_afk.load()["log"]
assert len(log) == 1 and log[0]["kind"] == "answer" and log[0]["picked"] == "Approve and start", log
assert ui_afk.public(now=now)["held"] == 1  # b

# extend keeps the window and its log
ui_afk.start(now + 80000, now + 10)
assert ui_afk.load()["started"] == now and len(ui_afk.load()["log"]) == 1

# failed retries: only failures from this window, on the 2m/10m/30m/1h ladder, then held
old = ui_sessions.create("/implement-issue 2", d)["id"]
ui_sessions.update(old, status="failed", session_id="x", ended_at="2020-01-01T00:00:00+00:00")
f = ui_sessions.create("/implement-issue 3", d, {"owner": "o", "repo": "r", "issue": 3})["id"]
nosid = ui_sessions.create("/implement-issue 4", d)["id"]


def fail(sid, t):
    ui_sessions.update(
        sid,
        status="failed",
        ended_at=ui_runner._iso(__import__("datetime").datetime.fromtimestamp(t, __import__("datetime").timezone.utc)),
    )


ui_sessions.update(f, session_id="s3")
fail(f, now + 1)
fail(nosid, now + 1)
t = now + 2
for i, delay in enumerate(ui_afk.RETRY_DELAYS):
    ui_afk.tick(t)  # schedules
    assert len(retried) == i, (i, retried)
    ui_afk.tick(t + delay - 1)
    assert len(retried) == i
    ui_afk.tick(t + delay)
    assert retried[-1] == f and len(retried) == i + 1
    t += delay + 1
    fail(f, t)
    t += 1
ui_afk.tick(t + 10_000)
assert len(retried) == len(ui_afk.RETRY_DELAYS) and old not in retried and nosid not in retried
assert ui_afk.public(now=t)["held"] == 3  # b, f exhausted, nosid
# success resets the counter
ui_sessions.update(f, status="done")
ui_afk.tick(t)
assert ui_sessions.load(f).get("afk_retries") is None

# a grind paused on CI is never answered with a skip-CI reply, and is not counted as held
os.makedirs(os.path.join(d, "pr-grind"), exist_ok=True)


def grind(n, paused):
    with open(os.path.join(d, "pr-grind", f"o-r-{n}.md"), "w") as fh:
        fh.write(
            f"owner: o\nrepo: r\nnumber: {n}\nthread: https://x.slack.com/archives/C1/p{n}\npaused: {paused}\n\n## Round 1\n"
        )


grind(70, "2026-10-09T00:00:00Z — Gate 2 failed: CI red")
held_before = ui_afk.public(now=t)["held"]
ui_afk.tick(t)
assert not any(e["kind"] == "skip-ci" for e in ui_afk.load()["log"])
assert ui_afk.public(now=t)["held"] == held_before

# outside AFK nothing retries or answers, and the end push fires exactly once
pushed.clear()
n_log = len(ui_afk.load()["log"])
pub = ui_afk.stop(t)
assert not pub["active"] and pub["summary"]["log"] and len(pub["summary"]["log"]) == n_log
assert [p[0] for p in pushed] == ["aiw: away mode ended"], pushed
assert f"{n_log} decisions made" in pushed[0][1]
ui_afk.tick(t + 5)
assert len(pushed) == 1
c = waiting()
fail(f, t + 6)
ui_afk.tick(t + 7)
assert all(s != c for s, _ in resumed) and len(retried) == len(ui_afk.RETRY_DELAYS)
assert ui_afk.dismiss()["summary"] is None

# a new window starts a fresh log
ui_afk.start(t + 3600, t)
assert ui_afk.load()["log"] == []

# #188: create-prd (and old prd) and dump interviews are never auto-answered (also plugin-prefixed); other families still are
resumed.clear()
held = [
    waiting(command=c)
    for c in (
        "/prd x",
        "/create-prd x",
        "/dump x",
        "/ai-workflow:prd x",
        "/create-tasks p",
        "/refine-issues docs/tasks/x.md",
    )
]
gi = waiting(command="/implement-issue 9")
ui_afk.tick(t + 1)
assert all(ui_sessions.load(h)["status"] == "waiting" for h in held), [ui_sessions.load(h)["status"] for h in held]
assert sorted(sid for sid, _ in resumed) == sorted([c, gi]), resumed  # c: the /implement-issue left waiting above
assert sorted(e["sid"] for e in ui_afk.load()["log"] if e["kind"] == "answer") == sorted([c, gi])

# dispatch lanes: a held lane is retried on the backoff; one asking a question is left to the answer path
import dispatch_run  # noqa: E402

dl = dispatch_run.create("o/r#1", "headless", {}, [{"repo": "o/r", "n": n, "refined": True} for n in (41, 42, 43)])
dl["lanes"]["o/r#41"].update(stage="merge_gate", held="CI is red", pr=410, handle={"session": "x"})
dl["lanes"]["o/r#42"].update(stage="implementing", needs_you="waiting on you", handle={"session": "y"})
dispatch_run.save(dl)
ui_afk.start(t + 3600, now=t)
ui_afk.tick(t + 2)  # schedules the first retry
assert dispatch_run.load(dl["id"])["lanes"]["o/r#41"]["held"] == "CI is red"
ui_afk.tick(t + 2 + ui_afk.RETRY_DELAYS[0])
x41 = dispatch_run.load(dl["id"])["lanes"]["o/r#41"]
assert x41["held"] is None and x41["afk_retries"] == 1
assert x41["outbox"] == [["send", dispatch_run.ci_fix_prompt(410)]], x41  # red CI: fix it in the PR's session
assert dispatch_run.load(dl["id"])["lanes"]["o/r#42"]["needs_you"] == "waiting on you"
assert any(e["command"] == "dispatch lane #41" for e in ui_afk.load()["log"])

print("test_ui_afk: ok")
