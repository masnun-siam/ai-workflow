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
print("ui_grind: all checks passed")
