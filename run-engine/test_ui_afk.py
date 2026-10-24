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
started, stopped = [], []


def fake_start(prompt, cwd, link=None, **kw):
    """A real session record, so ui_sessions.update works on it; no claude process."""
    rec = ui_sessions.create(prompt, cwd, link, claude_cmd=kw.get("claude_cmd"))
    started.append({"id": rec["id"], "prompt": prompt, **kw})
    return ui_sessions.update(rec["id"], status="running")


def fake_stop(sid):
    stopped.append(sid)
    return ui_sessions.update(sid, status="stopped", auto_resume=False)


ui_runner.start, ui_runner.stop = fake_start, fake_stop
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
e = log[0]
assert e["id"] == f"{a}:q-1" and e["by"] == "recommended" and e["answerer"] is None and e["cost"] is None
assert e["changed"] is False
q0 = e["questions"][0]
assert q0["picked"] == ["Approve and start (Recommended)"] and q0["why"] is None and "recommended" not in q0
assert [o["label"] for o in q0["options"]] == ["Approve and start (Recommended)", "Abort"]
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

# #188 no longer holds in a window: planning interviews are answered too, logged as Recommended
resumed.clear()
planning = [
    waiting(command=c)
    for c in (
        "/prd x",
        "/create-prd x",
        "/ai-workflow:create-prd x",
        "/dump x",
        "/ai-workflow:prd x",
        "/create-tasks p",
        "/ai-workflow:create-tasks p",
        "/refine-issues docs/tasks/x.md",
    )
]
gi = waiting(command="/implement-issue 9")
ui_afk.tick(t + 1)
assert all(ui_sessions.load(h)["status"] != "waiting" for h in planning)
assert sorted(sid for sid, _ in resumed) == sorted([c, gi, *planning]), resumed
answers = [e for e in ui_afk.load()["log"] if e["kind"] == "answer"]
assert sorted(e["sid"] for e in answers) == sorted([c, gi, *planning])
assert all(e["by"] == "recommended" for e in answers)

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

# ---- Opus answerer (#463) ----
import ui_panel  # noqa: E402
import away_answerer  # noqa: E402

for r in ui_sessions.list_sessions():  # leave nothing from the cases above waiting
    if r["status"] in ("waiting", "running", "starting"):
        ui_sessions.update(r["id"], status="stopped", pending_question=None)
W = time.time()
ui_afk.start(W + 7200, W)
started.clear()
stopped.clear()
resumed.clear()
retried.clear()
replies = {}
ui_panel.final_text = lambda sid: replies[sid]
OK = 'AWAY-ANSWER: {"answers": {"0": {"labels": ["Approve"], "why": "safe"}}}'
BAD = 'AWAY-ANSWER: {"answers": {"0": {"labels": ["Nope"], "why": "x"}}}'


def log_of(sid):
    return [e for e in ui_afk.load()["log"] if e["sid"] == sid]


def pq(sid):
    return ui_sessions.load(sid)["pending_question"]


def finish(aid, reply, status="done", cost=0.3):
    replies[aid] = reply
    ui_sessions.update(aid, status=status, cost=cost)


# valid reply: start kwargs, then resume with labels only and an Opus row
v = waiting(rec=False)
ui_afk.tick(W)
assert len(started) == 1, started
k = started[0]
assert (k["agent"], k["model"], k["effort"], k["claude_cmd"]) == ("ai-workflow:away-answerer", "opus", "medium", None)
assert k["allowed_tools"] == away_answerer.allowed_tools() and "Read" in k["allowed_tools"]
a = ui_sessions.load(k["id"])
assert (a["role"], a["answers_for"], a["answers_round"]) == ("away-answerer", v, "q-1"), a
assert pq(v)["answerer"] == k["id"] and pq(v)["answerer_attempts"] == 1
ui_afk.tick(W)
assert len(started) == 1 and not log_of(v)  # still running: nothing starts, nothing logs
finish(k["id"], OK)
ui_afk.tick(W)
assert resumed == [(v, 'Answer to q-1: {"0":{"labels":["Approve"]}}')], resumed
e = log_of(v)[0]
assert (e["by"], e["answerer"], e["cost"], e["kind"]) == ("opus", k["id"], 0.3, "answer"), e
assert e["questions"][0]["picked"] == ["Approve"] and e["questions"][0]["why"] == "safe"

# hold: one held row, round stays waiting, no more answerers
n0 = len(started)
h = waiting(rec=False)
ui_afk.tick(W)
finish(started[n0]["id"], 'AWAY-ANSWER: {"hold": "destructive"}')
ui_afk.tick(W)
e = log_of(h)[0]
assert e["kind"] == "held" and e["reason"] == "destructive" and e["picked"] == "Held: destructive", e
assert e["answerer"] == started[n0]["id"] and e["cost"] == 0.3 and e["id"] == f"{h}:q-1"
assert e["questions"] and all("picked" not in q for q in e["questions"])
assert ui_sessions.load(h)["status"] == "waiting" and pq(h)["held"] is True
ui_afk.tick(W)
ui_afk.tick(W)
assert len(started) == n0 + 1 and len(log_of(h)) == 1

# invalid labels twice: exactly two answerers, then held
n0 = len(started)
i = waiting(rec=False)
ui_afk.tick(W)
finish(started[n0]["id"], BAD)
ui_afk.tick(W)  # first failure starts the second answerer in the same tick
assert len(started) == n0 + 2 and not log_of(i) and pq(i)["answerer"] == started[n0 + 1]["id"]
finish(started[n0 + 1]["id"], BAD)
ui_afk.tick(W)
ui_afk.tick(W)
assert len(started) == n0 + 2, "no third answerer"
e = log_of(i)[0]
assert e["kind"] == "held" and e["reason"].startswith("answerer failed (invalid reply"), e
assert ui_sessions.load(i)["status"] == "waiting" and pq(i)["answerer_attempts"] == 2

# timeout: stopped by the tick, counted as a failure; limited counts as one too
n0 = len(started)
m = waiting(rec=False)
ui_afk.tick(W)
first = started[n0]["id"]
ui_afk.tick(W + ui_afk.ANSWER_SECONDS + 60)
assert first in stopped and len(started) == n0 + 2, (stopped, started)
second = started[n0 + 1]["id"]
ui_sessions.update(second, status="limited")
ui_afk.tick(W)
assert second in stopped and len(started) == n0 + 2
e = log_of(m)[0]
assert e["kind"] == "held" and e["reason"] == "answerer failed (limited)", e

# a failed answerer is not retried and not counted as held
before = ui_afk.public(now=W)["held"]
ui_sessions.update(
    first,
    status="failed",
    session_id="zz",
    ended_at=ui_runner._iso(__import__("datetime").datetime.now(__import__("datetime").timezone.utc)),
)
ui_afk.tick(W + 1)
ui_afk.tick(W + 1 + ui_afk.RETRY_DELAYS[0] + 1)
assert not retried and ui_afk.public(now=W)["held"] == before

# the owner answers while the answerer runs: it is stopped, its reply discarded, no row
n0 = len(started)
r = waiting(rec=False)
ui_afk.tick(W)
ra = started[n0]["id"]
assert ui_sessions.claim_answer(r, "q-1") is not None
replies[ra] = OK
ui_afk.tick(W)
assert ra in stopped and not log_of(r) and all(sid != r for sid, _ in resumed)

# the window ends while an answerer runs: stopped, round freed and still waiting, no row
n0 = len(started)
w = waiting(rec=False)
ui_afk.tick(W)
wa = started[n0]["id"]
assert pq(w)["answerer"] == wa
ui_afk.stop(W + 1)
assert wa in stopped and pq(w)["answerer"] is None and pq(w)["answerer_attempts"] == 1
assert ui_sessions.load(w)["status"] == "waiting" and not log_of(w)

# a fully recommended round never starts an answerer
ui_sessions.update(w, status="stopped", pending_question=None)
ui_afk.start(W + 7200, W + 2)
n0 = len(started)
fr = waiting()
ui_afk.tick(W + 2)
assert len(started) == n0 and log_of(fr)[0]["by"] == "recommended"

print("test_ui_afk: ok")
