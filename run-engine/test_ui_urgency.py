#!/usr/bin/env python3
"""Self-check for run-engine/ui_urgency.py and jev.peek with a stub `jev` on PATH. `python3 test_ui_urgency.py` — exit 0 = green."""

from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

d = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = d
bindir = os.path.join(d, "bin")
os.makedirs(bindir)
score_file, log = os.path.join(d, "score"), os.path.join(d, "log")
with open(os.path.join(bindir, "jev"), "w") as f:
    f.write(
        f'#!/bin/sh\ncat > /dev/null\necho x >> {log}\necho "{{\\"score\\": $(cat {score_file}), \\"confidence\\": 0.9}}"\n'
    )
os.chmod(os.path.join(bindir, "jev"), 0o755)
os.environ["PATH"] = bindir + ":/usr/bin:/bin"

import jev  # noqa: E402
import ui_inbox  # noqa: E402
import ui_settings  # noqa: E402
import ui_urgency  # noqa: E402

jev._server = True  # the server's timer sets this; only the server uses the cache


class FakePool:
    def __init__(self):
        self.jobs = []

    def submit(self, fn, *a):
        self.jobs.append((fn, a))

    def run(self):
        jobs, self.jobs = self.jobs, []
        for fn, a in jobs:
            fn(*a)
        return len(jobs)


pool = ui_urgency._pool = FakePool()


def setscore(v):
    open(score_file, "w").write(str(v))


def calls():
    return len(open(log).read().split()) if os.path.exists(log) else 0


def item(n, typ="grind_paused", **kw):
    return {"key": f"k{n}", "group": "fix", "type": typ, "reason": f"reason {n}", **kw}


items = [item(n) for n in range(5)]
setscore(4.0)
assert ui_urgency.urgency(items[0]) is None  # nothing cached yet
assert ui_urgency.scan(items) == 3 and len(pool.jobs) == 3
assert ui_urgency.scan(items) == 2 and len(pool.jobs) == 5  # in flight are not started twice
assert ui_urgency.scan(items) == 0
assert pool.run() == 5 and calls() == 5
assert ui_urgency.urgency(items[0]) == 5
assert ui_urgency.scan(items) == 0  # all cached
print("  ok  pass limit, in flight, cache")

for score, want in ((0.0, 1), (2.4, 3), (2.5, 4), (9.0, 5)):
    assert ui_urgency._urgency({"score": score}) == want, score
print("  ok  mapping")

items[1] = item(1, reason="changed")
assert ui_urgency.scan(items) == 1  # a changed text is scored again
pool.run()
dup = [item(7, reason="same"), item(8, reason="same")]
assert ui_urgency.scan(dup) == 1  # same text, one call
pool.run()
assert ui_urgency.scan([item(9, "pr_ready"), {"key": "l", "group": "fix", "type": "dispatch_lane", "at": None}]) == 0
print("  ok  changed text, dedupe, unscored types")

before = calls()
jev._window_start, jev._window_calls = jev._now(), 400
assert ui_urgency.scan([item(20)]) == 0
jev._window_calls = 0
ui_settings.save({"use_jev": False})
assert ui_urgency.scan([item(21)]) == 0 and ui_urgency.urgency(items[0]) is None and calls() == before
assert jev.peek("urgency", "score", ui_urgency.QUESTION, "x", levels=ui_urgency.LEVELS) is None
print("  ok  ceiling skip, jev off")

ui_settings.save({"use_jev": True})
assert ui_inbox.urgency_text(items[0]) and ui_urgency.urgency(items[0]) == 5
print("ui_urgency: all checks passed")
