#!/usr/bin/env python3
"""Self-check for run-engine/ui_grind.py. `python3 test_ui_grind.py` — exit 0 = green."""

from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
d = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = d

import ui_grind  # noqa: E402
import ui_notify  # noqa: E402
import ui_sessions  # noqa: E402

sent = []
ui_notify.notify = lambda event, rec: sent.append((event, rec))


def state_file(n, rounds=2, **kv):
    os.makedirs(os.path.join(d, "pr-grind"), exist_ok=True)
    h = {"owner": "o", "repo": "r", "number": str(n), "thread": f"https://x.slack.com/archives/C1/p{n}"}
    h.update(kv)
    path = os.path.join(d, "pr-grind", f"o-r-{n}.md")
    with open(path, "w") as f:
        f.write(
            "".join(f"{k}: {v}\n" for k, v in h.items())
            + "\n"
            + "".join(f"## Round {i}\n" for i in range(1, rounds + 1))
        )
    return path


# state files: round count + states
state_file(10)
state_file(11, paused="2026-10-08T00:00:00Z — rail")
state_file(12, done="2026-10-08T00:00:00Z — approved")
idx = ui_grind.index()["pr"]
assert idx[("o", "r", 10)] == {"state": "idle", "round": 2}
assert idx[("o", "r", 11)]["state"] == "paused" and "rail" in idx[("o", "r", 11)]["reason"]
assert idx[("o", "r", 12)]["state"] == "done"
rec = ui_sessions.create("/pr-grind https://x.slack.com/archives/C1/p10", d)
ui_sessions.update(rec["id"], status="running", pid=os.getpgrp())
assert ui_grind.index()["pr"][("o", "r", 10)]["state"] == "running"
print("  ok  index states and rounds")

# the queue and autostart are gone
for name in ("request", "control", "reply", "rerun_ci", "drain", "_enqueue", "tick"):
    assert not hasattr(ui_grind, name), name
assert not os.path.exists(os.path.join(d, "grind_requests.json"))
print("  ok  no queue")

# notifications: first scan records history silently, later changes push once, labelled by the PR
sent.clear()
ui_grind.notify_changes()
assert not sent
state_file(21, paused="2026-10-08T01:00:00Z — rail")
ui_grind.notify_changes()
ui_grind.notify_changes()
assert [e for e, _ in sent] == ["grind-paused"], sent
assert sent[0][1]["link"] == {"owner": "o", "repo": "r", "issue": 21}
h, body = ui_notify.compose("grind-paused", sent[0][1])
assert "paused" in h["Title"] and "rail" in body
state_file(10, done="2026-10-08T02:00:00Z — approved")
ui_grind.notify_changes()
assert [e for e, _ in sent] == ["grind-paused", "grind-done"], sent
print("  ok  notify_changes on paused and done")


# autostart
def pr(n, draft):
    return {"n": n, "url": f"https://github.com/o/r/pull/{n}", "draft": draft, "state": "OPEN", "ci": "success"}


def snap(prs, stale=False):
    return {"stale": stale, "fetched_at": 1.0, "data": {"issues": [{"n": 1, "prs": prs}], "merged": [], "open_prs": []}}


calls = []


def fake_start(body):
    calls.append(body)
    return 201, {"id": "S"}


on = {"auto_grind": True, "slack_channel": "C0123"}
prev, now = snap([pr(60, True), pr(61, True)]), snap([pr(60, False), pr(61, True)])
assert ui_grind.autostart("o/r", now, prev, on, start=fake_start) == [60]
assert calls == [{"repo": "o/r", "text": "/pr-grind https://github.com/o/r/pull/60 --channel C0123"}], calls
calls.clear()
assert ui_grind.autostart("o/r", now, prev, {"auto_grind": False}, start=fake_start) == [] and not calls
assert ui_grind.autostart("o/r", snap([pr(60, False)], stale=True), prev, on, start=fake_start) == [] and not calls
assert ui_grind.autostart("o/r", now, snap([]), on, start=fake_start) == [] and not calls  # first seen ready
state_file(60)  # a grind state file (any state) exists -> never twice
assert ui_grind.autostart("o/r", now, prev, on, start=fake_start) == [] and not calls
state_file(60, done="x")
assert ui_grind.autostart("o/r", now, prev, on, start=fake_start) == [] and not calls
os.unlink(os.path.join(d, "pr-grind", "o-r-60.md"))
assert ui_grind.autostart("o/r", now, prev, on, start=lambda b: (409, {"error": "live"})) == []  # live grind: 409
assert ui_grind.grind_text("u", "") == "/pr-grind u" and ui_grind.grind_text("u", "a b;c") == "/pr-grind u"
print("  ok  autostart")


# skip_ci / stop: user-triggered, keyed by repo + PR
import ui_runner  # noqa: E402

for n in (70, 71, 72):
    for f in os.listdir(os.path.join(d, "pr-grind")):
        if f.startswith(f"o-r-{n}"):
            os.unlink(os.path.join(d, "pr-grind", f))
paused = state_file(70, paused="2026-10-08T00:00:00Z — CI red")
state_file(71)
prompts = []
ui_runner.send_prompt = lambda sid, text: prompts.append((sid, text)) or "sent"


def conflict(fn, *a):
    try:
        fn(*a)
    except ui_grind.Conflict as e:
        return str(e)
    raise AssertionError("expected Conflict")


assert "no grind loop" in conflict(ui_grind.skip_ci, "o/r", 99) and "no grind loop" in conflict(
    ui_grind.stop, "o/r", 99
)
assert "not paused" in conflict(ui_grind.skip_ci, "o/r", 71)
assert "no finished" in conflict(ui_grind.skip_ci, "o/r", 70), "nothing to reply to yet"
r70 = ui_sessions.create("/pr-grind https://x.slack.com/archives/C1/p70", d)
ui_sessions.update(r70["id"], status="done", session_id="c-1")
assert ui_grind.skip_ci("O/R", 70) == {"state": "running"}
assert (
    len(prompts) == 1 and prompts[0][0] == r70["id"] and "Skip CI for now" in prompts[0][1] and "#70" in prompts[0][1]
)
assert "paused" not in ui_runner._header(paused), "the pause is cleared"
assert ui_grind.index()["pr"][("o", "r", 70)]["state"] == "idle"
assert "not paused" in conflict(ui_grind.skip_ci, "o/r", 70)
ui_runner.send_prompt = lambda sid, text: (_ for _ in ()).throw(ui_runner.Conflict("busy"))
state_file(72, paused="2026-10-08T00:00:00Z — CI red")
ui_sessions.update(
    ui_sessions.create("/pr-grind https://x.slack.com/archives/C1/p72", d)["id"], status="done", session_id="c-2"
)
assert conflict(ui_grind.skip_ci, "o/r", 72) == "busy" and "paused" in ui_runner._header(
    os.path.join(d, "pr-grind", "o-r-72.md")
)
print("  ok  skip_ci")

assert ui_grind.stop("o/r", 71) == {"ok": True, "state": "done"}
h = ui_runner._header(os.path.join(d, "pr-grind", "o-r-71.md"))
assert h["done"].endswith("stopped from the UI") and ui_grind.index()["pr"][("o", "r", 71)]["state"] == "done"
assert ui_runner.prgrind_tick(os.path.join(d, "pr-grind", "o-r-71.md")) == "done", "the re-entry timer skips it"
assert ui_grind.stop("o/r", 71) == {"ok": True, "state": "done"}  # twice is fine
assert ui_grind.stop("o/r", 72)["state"] == "done" and ui_grind.index()["pr"][("o", "r", 72)]["state"] == "done"
print("  ok  stop")
print("ui_grind: all checks passed")
