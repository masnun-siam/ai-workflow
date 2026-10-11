#!/usr/bin/env python3
"""Self-check for run-engine/ui_settings.py. `python3 test_ui_settings.py` — exit 0 = green."""

from __future__ import annotations

import os
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

d = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = d
bindir = os.path.join(d, "bin")
os.makedirs(bindir)
for name, out in (("claude", '{"loggedIn": true}'), ("cc-profile", '{"loggedIn": false}')):
    p = os.path.join(bindir, name)
    with open(p, "w") as f:
        f.write(f"#!/bin/sh\necho '{out}'\n")
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
os.environ["PATH"] = bindir + os.pathsep + os.environ["PATH"]

import ui_settings  # noqa: E402


def raises(fn, *a):
    try:
        fn(*a)
    except ValueError:
        return True
    return False


BUILTIN = {"label": "claude", "cmd": "claude", "builtin": True}
assert {k: v for k, v in ui_settings.load().items() if k != "vault_dir"} == {"commands": [BUILTIN], "default": "claude", "auto_grind": False}
assert ui_settings.load()["vault_dir"] == os.path.expanduser("~/Documents/notes")
assert ui_settings.default_cmd() == "claude"
assert ui_settings.argv("cc masum") == [os.path.join(bindir, "cc-profile"), "masum"]  # alias -> script
assert ui_settings.argv("claude --model x")[1:] == ["--model", "x"]
assert raises(ui_settings.argv, "") and raises(ui_settings.argv, "nope-xyz") and raises(ui_settings.argv, "a 'b")
saved = ui_settings.save({"commands": [{"label": "Main", "cmd": "claude"}, {"label": "Masum", "cmd": "cc masum"}],
                          "default": "Masum"})
assert ui_settings.load() == saved and ui_settings.default_cmd() == "cc masum"
assert saved["commands"][0] == BUILTIN and [c["label"] for c in saved["commands"]] == ["claude", "Main", "Masum"]
assert raises(ui_settings.save, {"commands": [{"label": "A", "cmd": "claude"}, {"label": "A", "cmd": "claude"}]})
assert raises(ui_settings.save, {"commands": [{"label": "A", "cmd": "nope-xyz"}]})
assert raises(ui_settings.save, {"commands": [], "default": "ghost"})
assert ui_settings.load() == saved  # failed saves leave the file alone
# the built-in: renamable, can be default, cmd is always claude, never dropped
s2 = ui_settings.save({"commands": [{"label": "Work", "cmd": "rm -rf /", "builtin": True}, {"label": "Masum", "cmd": "cc masum"}],
                       "default": "Work"})
assert s2["commands"][0] == {"label": "Work", "cmd": "claude", "builtin": True} and s2["default"] == "Work"
assert ui_settings.default_cmd() == "claude"
assert ui_settings.save({"commands": [{"label": "Masum", "cmd": "cc masum"}]})["commands"][0] == BUILTIN
assert raises(ui_settings.save, {"commands": [{"label": "Masum", "cmd": "claude", "builtin": True}, {"label": "Masum", "cmd": "cc masum"}]})
assert raises(ui_settings.save, {"commands": [{"label": " ", "cmd": "claude", "builtin": True}]})
saved = ui_settings.load()
assert ui_settings.check_login("claude")["ok"] and not ui_settings.check_login("cc x")["ok"]
assert not ui_settings.check_login("nope-xyz")["ok"]
print("ui_settings: 20 checks passed")
