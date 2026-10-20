#!/usr/bin/env python3
"""Self-check for run-engine/ui_board.py. `python3 test_ui_board.py` — exit 0 = green."""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ui_board

assert ui_board.plausible_repo("a", "b")
assert not ui_board.plausible_repo("a", "b-issue-1")
assert not ui_board.plausible_repo("", "b")
assert not ui_board.plausible_repo("a b", "c")
print("ok  plausible_repo")

old_path = ui_board.PROJECTS_PATH
try:
    with tempfile.TemporaryDirectory() as tmp:
        ui_board.PROJECTS_PATH = os.path.join(tmp, "nope.json")
        assert ui_board.load_projects() == {}
        p = os.path.join(tmp, "projects.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"a/b": "AB"}, fh)
        ui_board.PROJECTS_PATH = p
        assert ui_board.load_projects() == {"a/b": "AB"}
finally:
    ui_board.PROJECTS_PATH = old_path
print("ok  load_projects: missing file -> {}, valid file parsed")

old_path_env = os.environ.get("PATH")
try:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PATH"] = tmp
        assert ui_board.fetch_title("o", "r", 7) == "Issue #7 (title unavailable)"
finally:
    os.environ["PATH"] = old_path_env
print("ok  fetch_title: missing gh -> unavailable")

saved = os.environ.get("CLAUDE_PLUGIN_DATA")
with tempfile.TemporaryDirectory() as dd:
    os.environ["CLAUDE_PLUGIN_DATA"] = dd
    with open(os.path.join(dd, "checkouts.json"), "w") as fh:
        json.dump({"masnun-siam/typevocal": "/x/typevocal"}, fh)
    assert "masnun-siam/typevocal" in ui_board.known_projects()
if saved is None:
    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
else:
    os.environ["CLAUDE_PLUGIN_DATA"] = saved
print("ok  known_projects includes registered checkouts")
