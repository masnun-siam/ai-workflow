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
assert idx[("o", "r", 10)] == {"state": "idle", "round": 2, "thread": "https://x.slack.com/archives/C1/p10"}
assert idx[("o", "r", 11)]["state"] == "paused" and "rail" in idx[("o", "r", 11)]["reason"]
assert idx[("o", "r", 12)]["state"] == "done"
rec = ui_sessions.create("/pr-grind https://x.slack.com/archives/C1/p10", d)
ui_sessions.update(rec["id"], status="running", pid=os.getpgrp())
assert ui_grind.index()["pr"][("o", "r", 10)]["state"] == "running"
# a /pr-grind <pr url> just started (no state file yet, or an old done loop) is running
fresh = ui_sessions.create("/pr-grind https://github.com/O/R/pull/90 --channel C1", d)
ui_sessions.update(fresh["id"], status="running", pid=os.getpgrp())
again = ui_sessions.create("/pr-grind https://github.com/o/r/pull/12", d)
ui_sessions.update(again["id"], status="running", pid=os.getpgrp())
idx = ui_grind.index()["pr"]
assert idx[("o", "r", 90)] == {"state": "running", "round": 0, "thread": None}
assert idx[("o", "r", 12)]["state"] == "running"
for r_ in (fresh, again):
    ui_sessions.update(r_["id"], status="done")
assert ("o", "r", 90) not in ui_grind.index()["pr"] and ui_grind.index()["pr"][("o", "r", 12)]["state"] == "done"
ui_sessions.update(rec["id"], status="done")
assert ui_grind.index()["pr"][("o", "r", 10)]["state"] == "idle"
# the plugin spelling (#439 stores resolved commands) is the same loop
plug = ui_sessions.create("/ai-workflow:pr-grind https://x.slack.com/archives/C1/p10", d)
ui_sessions.update(plug["id"], status="running", pid=os.getpgrp())
fresh = ui_sessions.create("/ai-workflow:pr-grind https://github.com/o/r/pull/91", d)
ui_sessions.update(fresh["id"], status="running", pid=os.getpgrp())
other = ui_sessions.create("/pr-grind https://x.slack.com/archives/C1/p10 --channel C", d)  # not the same arg
idx = ui_grind.index()["pr"]
assert idx[("o", "r", 10)]["state"] == "running" and idx[("o", "r", 91)]["state"] == "running"
for r_ in (plug, fresh):
    ui_sessions.update(r_["id"], status="done")
ui_sessions.update(other["id"], status="running", pid=os.getpgrp())
assert ui_grind.index()["pr"][("o", "r", 10)]["state"] == "idle"
ui_sessions.update(other["id"], status="done")
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
# per issue: the issue's switch overrides the repo's auto_grind (#1 owns both PRs here)
assert ui_grind.autostart("o/r", now, prev, {"auto_grind": True, "issue_grind": {1: False}}, start=fake_start) == []
assert ui_grind.autostart("o/r", now, prev, {"auto_grind": False, "issue_grind": {1: True}}, start=fake_start) == [60]
calls.clear()
bare = snap([])
bare["data"]["open_prs"] = [pr(62, False)]
bare_prev = snap([])
bare_prev["data"]["open_prs"] = [pr(62, True)]
assert ui_grind.autostart(
    "o/r", bare, bare_prev, {"auto_grind": True, "issue_grind": {1: False}}, start=fake_start
) == [62]
assert ui_grind.autostart("o/r", bare, bare_prev, {"issue_grind": {1: True}}, start=fake_start) == [], "no issue: repo"
calls.clear()
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

# set_issue: stores the switch; on starts a grind for a ready PR with none, off stops a live loop
import ui_settings  # noqa: E402

calls.clear()
ready = snap([pr(80, False)])
ready["data"]["issues"][0]["n"] = 8
assert ui_grind.set_issue("o/r", 8, True, ready, {"slack_channel": ""}, start=fake_start) == {
    "repo": "o/r",
    "issue": 8,
    "on": True,
}
assert ui_settings.repo_settings("o/r")["issue_grind"][8] is True
assert calls == [{"repo": "o/r", "text": "/pr-grind https://github.com/o/r/pull/80"}], calls
calls.clear()
state_file(80)
ui_grind.set_issue("o/r", 8, True, ready, {}, start=fake_start)
assert not calls, "a loop already exists: not started twice"
ui_grind.set_issue("o/r", 8, False, ready, {}, start=fake_start)
assert (
    ui_grind.index()["pr"][("o", "r", 80)]["state"] == "done"
    and ui_settings.repo_settings("o/r")["issue_grind"][8] is False
)
draft = snap([pr(81, True)])
draft["data"]["issues"][0]["n"] = 9
ui_grind.set_issue("o/r", 9, True, draft, {}, start=fake_start)
assert not calls, "a draft PR is not ready: the grind starts when it turns ready"
ui_grind.set_issue("o/r", 10, True, snap([]), {}, start=lambda b: (502, {"error": "x"}))  # no PR: only the switch
assert ui_settings.repo_settings("o/r")["issue_grind"][10] is True
os.unlink(os.path.join(d, "pr-grind", "o-r-80.md"))
try:
    ui_grind.set_issue("o/r", 8, True, ready, {}, start=lambda b: (502, {"error": "x"}))
    raise AssertionError("expected RuntimeError")
except RuntimeError:
    pass
print("  ok  set_issue")
print("ui_grind: all checks passed")
