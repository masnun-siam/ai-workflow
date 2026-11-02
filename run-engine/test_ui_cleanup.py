#!/usr/bin/env python3
"""Self-check for run-engine/ui_cleanup.py. `python3 test_ui_cleanup.py` — exit 0 = green."""

from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ui_cleanup  # noqa: E402
import ui_sessions  # noqa: E402

root = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = os.path.join(root, "data")
checkout = os.path.join(root, "proj")
os.makedirs(checkout)
open(os.path.join(checkout, "keep.txt"), "w").write("x")

done = ui_sessions.create("/implement-issue 1", checkout)
ui_sessions.update(done["id"], status="done")
stopped = ui_sessions.create("/pr-grind 2", checkout)
ui_sessions.update(stopped["id"], status="stopped")
live = ui_sessions.create("/implement-issue 3", checkout)
ui_sessions.update(live["id"], status="running")

items = ui_cleanup.find_targets()
assert {i["key"] for i in items} == {done["id"], stopped["id"]}, items
assert all({"key", "label", "repo", "flags"} <= set(i) for i in items)
assert {i["label"] for i in items} == {"/implement-issue 1", "/pr-grind 2"}
print("  ok  lists finished sessions only")

removed = ui_cleanup.clean([done["id"], live["id"], "nope", "../etc"])
assert removed == [done["id"]], removed
assert ui_sessions.load(done["id"]) is None
assert ui_sessions.load(live["id"]) is not None and ui_sessions.load(stopped["id"]) is not None
assert os.path.exists(os.path.join(checkout, "keep.txt"))
print("  ok  removes chosen finished sessions only; checkout untouched")

# a session resumed between find_targets and the loop keeps its directory
back = ui_sessions.create("/pr-grind 4", checkout)
ui_sessions.update(back["id"], status="done")
real_load = ui_sessions.load
ui_sessions.load = lambda k: {**real_load(k), "status": "running"} if k == back["id"] else real_load(k)
try:
    assert ui_cleanup.clean([back["id"]]) == []
finally:
    ui_sessions.load = real_load
assert os.path.isdir(ui_sessions.session_dir(back["id"]))
print("  ok  skips a session that went live after the listing")
