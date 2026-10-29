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
assert {k: v for k, v in ui_settings.load().items() if k not in ("vault_dir", "jev_installed")} == {
    "commands": [BUILTIN],
    "default": "claude",
    "repos": {},
    "grind_mode": "deep",
    "use_jev": True,
    "run_model": None,
    "run_effort": None,
}
assert ui_settings.load()["vault_dir"] == os.path.expanduser("~/Documents/notes")
assert ui_settings.default_cmd() == "claude"
assert ui_settings.argv("cc masum") == [os.path.join(bindir, "cc-profile"), "masum"]  # alias -> script
assert ui_settings.argv("claude --model x")[1:] == ["--model", "x"]
assert raises(ui_settings.argv, "") and raises(ui_settings.argv, "nope-xyz") and raises(ui_settings.argv, "a 'b")
saved = ui_settings.save(
    {"commands": [{"label": "Main", "cmd": "claude"}, {"label": "Masum", "cmd": "cc masum"}], "default": "Masum"}
)
assert ui_settings.load() == saved and ui_settings.default_cmd() == "cc masum"
assert saved["commands"][0] == BUILTIN and [c["label"] for c in saved["commands"]] == ["claude", "Main", "Masum"]
assert raises(ui_settings.save, {"commands": [{"label": "A", "cmd": "claude"}, {"label": "A", "cmd": "claude"}]})
assert raises(ui_settings.save, {"commands": [{"label": "A", "cmd": "nope-xyz"}]})
assert raises(ui_settings.save, {"commands": [], "default": "ghost"})
assert ui_settings.load() == saved  # failed saves leave the file alone
# the built-in: renamable, can be default, cmd is always claude, never dropped
s2 = ui_settings.save(
    {
        "commands": [{"label": "Work", "cmd": "rm -rf /", "builtin": True}, {"label": "Masum", "cmd": "cc masum"}],
        "default": "Work",
    }
)
assert s2["commands"][0] == {"label": "Work", "cmd": "claude", "builtin": True} and s2["default"] == "Work"
assert ui_settings.default_cmd() == "claude"
assert ui_settings.save({"commands": [{"label": "Masum", "cmd": "cc masum"}]})["commands"][0] == BUILTIN
assert raises(
    ui_settings.save,
    {"commands": [{"label": "Masum", "cmd": "claude", "builtin": True}, {"label": "Masum", "cmd": "cc masum"}]},
)
assert raises(ui_settings.save, {"commands": [{"label": " ", "cmd": "claude", "builtin": True}]})
saved = ui_settings.load()
assert ui_settings.check_login("claude")["ok"] and not ui_settings.check_login("cc x")["ok"]
assert not ui_settings.check_login("nope-xyz")["ok"]

# --- per-repo settings, legacy auto_grind migration
import json  # noqa: E402

import dispatch  # noqa: E402

dispatch.register_checkout("o/a", "/x/a")
dispatch.register_checkout("o/b", "/x/b")
with open(ui_settings._path(), "w") as f:
    json.dump({"auto_grind": True, "commands": []}, f)
s3 = ui_settings.load()
assert s3["repos"]["o/a"]["auto_grind"] and s3["repos"]["o/b"]["auto_grind"] and "auto_grind" not in s3
assert "auto_grind" not in json.load(open(ui_settings._path()))
assert ui_settings.repo_settings("o/a") == {
    "auto_grind": True,
    "slack_channel": "",
    "issue_grind": {},
}
assert ui_settings.repo_settings("o/none")["auto_grind"] is False
assert ui_settings.set_issue_grind("O/a", 5, False) == {5: False} and ui_settings.set_issue_grind("o/a", 6, True) == {
    5: False,
    6: True,
}
assert ui_settings.repo_settings("o/a")["issue_grind"] == {5: False, 6: True}
ui_settings.save(ui_settings.load())
assert ui_settings.repo_settings("o/a")["issue_grind"] == {5: False, 6: True}, "a Settings save keeps the switches"
assert raises(ui_settings.set_issue_grind, "o/a", 0, True) and raises(ui_settings.set_issue_grind, "o/a", 5, "on")
# grind_mode: deep by default, a partial save sets it, other saves keep it, anything else is refused
assert ui_settings.grind_mode() == "deep" and ui_settings.load()["grind_mode"] == "deep"
ui_settings.save({"grind_mode": "simple"})
assert ui_settings.grind_mode() == "simple" and ui_settings.load()["grind_mode"] == "simple"
ui_settings.save({"repos": {"o/a": {"slack_channel": "C1"}}})
assert ui_settings.grind_mode() == "simple", "a save without grind_mode keeps it"
assert raises(ui_settings.validate, {"grind_mode": "fast"})
ui_settings.save({"grind_mode": "deep"})
cur = ui_settings.load()
r = ui_settings.save({"commands": [], "repos": {**cur["repos"], "o/a": {"auto_grind": True, "slack_channel": "C2"}}})
assert r["repos"]["o/a"] == {"auto_grind": True, "slack_channel": "C2"} and r["repos"]["o/b"]["slack_channel"] == ""
assert raises(ui_settings.save, {"commands": [], "repos": {"o/a": {"slack_channel": 5}}})
# a stored Auto-build cap or epic list from before dispatches is ignored, never shown
r = ui_settings.save({"repos": {"o/a": {"autopilot_cap": 4, "slack_channel": "#x"}}, "autopilot": {"o/a": [7]}})
assert r["repos"]["o/a"] == {"auto_grind": False, "slack_channel": "#x"} and "autopilot" not in r and r["commands"]
# run_model / run_effort: null by default, a partial save sets them, other saves keep them, bad values 400
assert ui_settings.load()["run_model"] is None and ui_settings.load()["run_effort"] is None
ui_settings.save({"run_model": "opus", "run_effort": "xhigh"})
assert ui_settings.load()["run_model"] == "opus" and ui_settings.load()["run_effort"] == "xhigh"
ui_settings.save({"grind_mode": "simple"})
assert ui_settings.run_model() == "opus" and ui_settings.run_effort() == "xhigh", "other saves keep them"
ui_settings.save({"run_model": None})
assert ui_settings.run_model() is None and ui_settings.run_effort() == "xhigh"
assert raises(ui_settings.validate, {"run_model": "default"}) and raises(ui_settings.validate, {"run_effort": "huge"})
# use_jev: on by default, a partial save sets it, other saves keep it, non-booleans are refused
assert ui_settings.use_jev() is True and ui_settings.load()["use_jev"] is True
ui_settings.save({"use_jev": False})
assert ui_settings.use_jev() is False and ui_settings.load()["use_jev"] is False
ui_settings.save({"grind_mode": "simple"})
ui_settings.save({"repos": {"o/a": {"slack_channel": "C1"}}})
assert ui_settings.use_jev() is False, "saves without use_jev keep it"
before = open(ui_settings._path()).read()
for bad in ("no", 0, None):
    assert raises(ui_settings.save, {"use_jev": bad}) and open(ui_settings._path()).read() == before
ui_settings.save({**ui_settings.load(), "use_jev": True})
assert ui_settings.use_jev() is True and "jev_installed" not in json.loads(open(ui_settings._path()).read())
# jev_installed follows PATH (the real PATH is dropped so a developer's jev cannot change the result)
real_path = os.environ["PATH"]
os.environ["PATH"] = bindir
assert ui_settings.load()["jev_installed"] is False
p = os.path.join(bindir, "jev")
with open(p, "w") as f:
    f.write("#!/bin/sh\n")
os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
assert ui_settings.load()["jev_installed"] is True
os.environ["PATH"] = real_path
print("ui_settings: 44 checks passed")
