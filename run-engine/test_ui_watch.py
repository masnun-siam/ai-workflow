#!/usr/bin/env python3
"""Self-check for run-engine/ui_watch.py. `python3 test_ui_watch.py` — exit 0 = green."""

from __future__ import annotations

import json
import os
import sys
import tempfile

d = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = d
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui_watch  # noqa: E402

DAY = 86400
assert ui_watch.recent(now=1e9) == []
ui_watch.touch("o/r", now=1e9)
ui_watch.touch("o/s", now=1e9 - 6 * DAY)
assert sorted(ui_watch.recent(now=1e9)) == ["o/r", "o/s"]
assert ui_watch.recent(now=1e9 + 2 * DAY) == ["o/r"], "o/s was opened 8 days ago"
assert ui_watch.recent(now=1e9 + 8 * DAY) == []
print("  ok  recent: 7-day window")

before = open(os.path.join(d, "ui_opened.json")).read()
ui_watch.touch("o/r", now=1e9 + 30)  # inside a minute: no write
assert open(os.path.join(d, "ui_opened.json")).read() == before
ui_watch.touch("o/r", now=1e9 + 120)
assert json.load(open(os.path.join(d, "ui_opened.json")))["o/r"] == 1e9 + 120
ui_watch.touch("o/t", now=1e9 + 9 * DAY)  # a write drops what has expired
assert sorted(json.load(open(os.path.join(d, "ui_opened.json")))) == ["o/t"]
open(os.path.join(d, "ui_opened.json"), "w").write("not json")
assert ui_watch.recent() == []
print("  ok  persisted in the data dir, throttled, pruned, tolerant of a broken file")
print("ui_watch: all checks passed")
