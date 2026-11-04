#!/usr/bin/env python3
"""Self-check for run-engine/ui_settings.py. `python3 test_ui_settings.py` — exit 0 = green."""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

d = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = d
bindir = os.path.join(d, "bin")
os.makedirs(bindir)
for name, out in (("claude", '{"loggedIn": true}'), ("cc-profile", '{"loggedIn": false}'), ("codex", "{}")):
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


BUILTIN = {"label": "claude", "cmd": "claude", "builtin": True, "harness": "claude"}
HARNESSES = [
    {
        "id": "claude",
        "label": "Claude Code",
        "models": ["opus", "sonnet", "haiku"],
        "efforts": ["low", "medium", "high", "xhigh", "max"],
        "usage": True,
    },
    {"id": "codex", "label": "Codex", "models": None, "efforts": ["low", "medium", "high", "xhigh"], "usage": False},
]
assert {k: v for k, v in ui_settings.load().items() if k not in ("vault_dir", "jev_installed", "personal_plugin")} == {
    "commands": [BUILTIN],
    "default": "claude",
    "repos": {},
    "slack_channels": [],
    "reviewers": [],
    "active_reviewers": [],
    "grind_mode": "deep",
    "review_mode": "single",
    "use_jev": True,
    "run_model": None,
    "run_effort": None,
    "harnesses": HARNESSES,
}
assert ui_settings.load()["vault_dir"] == os.path.expanduser("~/Documents/notes")
assert ui_settings.default_cmd() == "claude"
assert ui_settings.argv("cc masum") == [os.path.join(bindir, "cc-profile"), "masum"]  # alias -> script
assert ui_settings.argv("claude --model x")[1:] == ["--model", "x"]
assert raises(ui_settings.argv, "") and raises(ui_settings.argv, "nope-xyz") and raises(ui_settings.argv, "a 'b")
saved = ui_settings.save(
    {
        "commands": [{"label": "Main", "cmd": "claude --model x"}, {"label": "Masum", "cmd": "cc masum"}],
        "default": "Masum",
    }
)
assert ui_settings.load() == saved and ui_settings.default_cmd() == "cc masum"
assert saved["commands"][0] == BUILTIN and [c["label"] for c in saved["commands"]] == ["claude", "Main", "Masum"]
assert raises(ui_settings.save, {"commands": [{"label": "A", "cmd": "claude -c"}, {"label": "A", "cmd": "claude -r"}]})
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
assert s2["commands"][0] == {**BUILTIN, "label": "Work"} and s2["default"] == "Work"
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
    "reviewers": None,
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
ui_settings.save({"repos": {"o/a": {"slack_channel": ""}}})
assert ui_settings.grind_mode() == "simple", "a save without grind_mode keeps it"
assert raises(ui_settings.validate, {"grind_mode": "fast"})
ui_settings.save({"grind_mode": "deep"})
# review_mode: single by default, a partial save sets it, other saves keep it, anything else is refused
assert ui_settings.review_mode() == "single" and ui_settings.load()["review_mode"] == "single"
ui_settings.save({"review_mode": "loop"})
assert ui_settings.review_mode() == "loop" and ui_settings.load()["review_mode"] == "loop"
ui_settings.save({"grind_mode": "simple"})
ui_settings.save({"repos": {"o/a": {"slack_channel": ""}}})
assert ui_settings.review_mode() == "loop", "saves without review_mode keep it"
before = open(ui_settings._path()).read()
for bad in ("fast", None, 1):
    assert raises(ui_settings.save, {"review_mode": bad}) and open(ui_settings._path()).read() == before, bad
ui_settings.save({"grind_mode": "deep", "review_mode": "single"})
cur = ui_settings.load()
r = ui_settings.save(
    {
        "commands": [],
        "slack_channels": [{"id": "C0123ABCD", "name": "#rev"}],
        "repos": {**cur["repos"], "o/a": {"auto_grind": True, "slack_channel": "C0123ABCD"}},
    }
)
assert (
    r["repos"]["o/a"] == {"auto_grind": True, "slack_channel": "C0123ABCD", "reviewers": None, "channel_invalid": False}
    and r["repos"]["o/b"]["slack_channel"] == ""
)
assert raises(ui_settings.save, {"commands": [], "repos": {"o/a": {"slack_channel": 5}}})
r = ui_settings.save({"repos": {"o/a": {"reviewer": "bob"}}})  # the old per-repo field: accepted, not stored
assert "reviewer" not in r["repos"]["o/a"] and "reviewer" not in json.load(open(ui_settings._path()))["repos"]["o/a"]
# a stored Auto-build cap or epic list from before dispatches is ignored, never shown
r = ui_settings.save({"repos": {"o/a": {"autopilot_cap": 4, "slack_channel": ""}}, "autopilot": {"o/a": [7]}})
assert (
    r["repos"]["o/a"] == {"auto_grind": False, "slack_channel": "", "reviewers": None, "channel_invalid": False}
    and "autopilot" not in r
    and r["commands"]
)
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
ui_settings.save({"repos": {"o/a": {"slack_channel": ""}}})
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
# personal_plugin follows installed_plugins.json under CLAUDE_CONFIG_DIR; missing or unreadable means false
cfgdir = tempfile.mkdtemp()
os.environ["CLAUDE_CONFIG_DIR"] = cfgdir
assert ui_settings.load()["personal_plugin"] is False
os.makedirs(os.path.join(cfgdir, "plugins"))
with open(os.path.join(cfgdir, "plugins", "installed_plugins.json"), "w") as f:
    json.dump({"version": 2, "plugins": {"ai-workflow-personal@mine": [{}]}}, f)
assert ui_settings.load()["personal_plugin"] is True
assert "personal_plugin" not in json.loads(open(ui_settings._path()).read())
del os.environ["CLAUDE_CONFIG_DIR"]
sp = ui_settings._path()
with open(sp, "w") as f:
    f.write("{broken")
ui_settings.save({})
assert [n for n in os.listdir(d) if n.startswith("ui_settings.json.corrupt-")]
ok_ = True
with open(sp, "w") as f:
    json.dump({"repos": {"bad slug": {}, "o/r": {"auto_grind": True}}}, f)
ui_settings.save({})
assert ui_settings.repo_settings("o/r")["auto_grind"] is True
try:
    ui_settings.save({"repos": {"bad slug": {}}})
    raise SystemExit("invalid sent slug must raise")
except ValueError:
    pass
ts = [threading.Thread(target=ui_settings.set_issue_grind, args=("o/r", i, True)) for i in range(1, 21)]
[t.start() for t in ts]
[t.join() for t in ts]
assert len(ui_settings.repo_settings("o/r")["issue_grind"]) == 20
print("ui_settings: corrupt aside, bad stored slug dropped, concurrent set_issue_grind kept")
# slack_channels: a validated [{id, name}] list; a repo picks a listed id, "", or keeps its unchanged legacy value
ui_settings.save({"slack_channels": [], "repos": {"o/a": {"slack_channel": ""}, "o/b": {"slack_channel": ""}}})
REV = {"id": "C0B8385GKNK", "name": "#reviews"}
assert ui_settings.save({"slack_channels": [{"id": " C0B8385GKNK ", "name": " #reviews "}]})["slack_channels"] == [REV]
assert ui_settings.load()["slack_channels"] == [REV]
ui_settings.save({"grind_mode": "simple"})
assert ui_settings.load()["slack_channels"] == [REV], "a partial save keeps the list"
assert ui_settings.save({"slack_channels": [{**REV, "name": "#rev"}]})["slack_channels"] == [{**REV, "name": "#rev"}]
many = [{"id": f"C{i:08d}", "name": "n"} for i in range(51)]
assert len(ui_settings.save({"slack_channels": many[:50]})["slack_channels"]) == 50
before = open(ui_settings._path()).read()


def msg(body):
    try:
        ui_settings.save(body)
    except ValueError as e:
        assert open(ui_settings._path()).read() == before, "a failed save writes nothing"
        return str(e)


assert msg({"slack_channels": many}) == "at most 50"
assert msg({"slack_channels": [{"id": "reviews", "name": "#reviews"}]}) == "channel id must look like C0123ABCD"
for bad in ("C0123", "X0123ABCD", "c0123abcd", "C0123ABCD12345", 5):
    assert msg({"slack_channels": [{"id": bad, "name": "n"}]}) == "channel id must look like C0123ABCD", bad
for bad in ("", "  ", "x" * 61, 5, None):
    assert msg({"slack_channels": [{"id": "C0123ABCD", "name": bad}]}) == "channel name must be 1 to 60 characters"
assert ui_settings.save(
    {"slack_channels": [{"id": "G0123ABCD", "name": "x" * 60}, {"id": "D0123ABCD", "name": "x" * 60}]}
)
before = open(ui_settings._path()).read()
assert msg({"slack_channels": [REV, {**REV, "name": "other"}]}) == "channel C0B8385GKNK is already listed"
assert msg({"slack_channels": "C0B8385GKNK"}) == "slack_channels must be a list"
assert msg({"slack_channels": ["C0B8385GKNK"]}) == "channel id must look like C0123ABCD"
# a picked channel can't be dropped, unless the same save moves the repo off it
r = ui_settings.save({"slack_channels": [REV], "repos": {"o/a": {"slack_channel": "C0B8385GKNK"}}})
assert r["repos"]["o/a"]["slack_channel"] == "C0B8385GKNK" and r["repos"]["o/a"]["channel_invalid"] is False
assert r["repos"]["o/b"]["channel_invalid"] is False, '"" is never invalid'
before = open(ui_settings._path()).read()
assert msg({"slack_channels": []}) == "channel C0B8385GKNK is used by o/a"
assert msg({"repos": {"o/b": {"slack_channel": "C0123ABCD"}}}) == "slack_channel C0123ABCD is not a listed channel"
assert ui_settings.save({"slack_channels": [], "repos": {"o/a": {"slack_channel": ""}}})["slack_channels"] == []
# an unchanged legacy value saves and reads as invalid; another unlisted value is refused
with open(ui_settings._path(), "w") as f:
    json.dump({"repos": {"o/a": {"slack_channel": "#x"}}}, f)
ui_settings.save({"repos": {"o/a": {"slack_channel": "#x"}}})
assert ui_settings.load()["repos"]["o/a"]["channel_invalid"] is True
assert raises(ui_settings.save, {"repos": {"o/a": {"slack_channel": "#y"}}})
assert "channel_invalid" not in open(ui_settings._path()).read()
# reviewers: a validated list with server ids, a global active set, a per-repo override (null = follow it)
import re  # noqa: E402

ui_settings.save({"repos": {"o/a": {"slack_channel": ""}}})
BOT = {"name": "Blubird AI Agent", "slack_id": "U0BS34962FK", "github_login": "blubird-ai-agent"}
MASUM = {"name": "Masum", "slack_id": "U0373SRT22G", "github_login": "gsm-masum"}
r = ui_settings.save({"reviewers": [BOT, MASUM]})
assert [{k: v for k, v in x.items() if k != "id"} for x in r["reviewers"]] == [BOT, MASUM]
assert all(re.match(r"^r-[0-9a-f]{8}$", x["id"]) for x in r["reviewers"]) and ui_settings.load() == r
bot_id, masum_id = (x["id"] for x in r["reviewers"])
assert bot_id != masum_id and r["active_reviewers"] == [] and r["repos"]["o/a"]["reviewers"] is None
r = ui_settings.save(
    {
        "reviewers": [
            {**r["reviewers"][0], "name": "Bot"},
            r["reviewers"][1],
            {"github_login": "copilot", "name": "Copilot"},
        ]
    }
)
assert [x["id"] for x in r["reviewers"][:2]] == [bot_id, masum_id] and r["reviewers"][0]["name"] == "Bot", (
    "renames keep ids"
)
cop_id = r["reviewers"][2]["id"]
assert cop_id not in (bot_id, masum_id) and r["reviewers"][2]["slack_id"] == ""
LIST = r["reviewers"]
before = open(ui_settings._path()).read()
assert msg({"reviewers": [{"name": "x", "slack_id": "", "github_login": " "}]}) == "add a Slack id or a GitHub login"
assert msg({"reviewers": [{"name": "x", "slack_id": "@bot"}]}) == "Slack id must look like U0123ABCD"
for bad in ("a b", "x" * 40, "org/team"):
    assert msg({"reviewers": [{"name": "x", "github_login": bad}]}) == "not a GitHub login", bad
assert msg({"reviewers": [BOT, {**MASUM, "slack_id": BOT["slack_id"]}]}) == "Slack id U0BS34962FK is already listed"
assert msg({"reviewers": [MASUM, {**BOT, "github_login": "Gsm-Masum"}]}) == "login gsm-masum is already listed"
for bad in ("", "  ", "x" * 61, None):
    assert msg({"reviewers": [{**BOT, "name": bad}]}) == "reviewer name must be 1 to 60 characters", bad
many = [{"name": "n", "slack_id": f"U{i:08d}"} for i in range(51)]
assert msg({"reviewers": many}) == "at most 50" and msg({"reviewers": "x"}) == "reviewers must be a list"
for bad in ("abc", "r-XYZ12345", "r-1234567", 5):
    assert msg({"reviewers": [{**BOT, "id": bad}]}) == "reviewer id must be r-<8 hex>", bad
assert msg({"reviewers": [{**BOT, "id": bot_id}, {**MASUM, "id": bot_id}]}) == "duplicate reviewer id"
assert msg({"active_reviewers": ["r-00000000"]}) == "unknown reviewer id r-00000000"
assert msg({"active_reviewers": bot_id}) == "active_reviewers must be a list of ids"
assert msg({"repos": {"o/a": {"reviewers": ["r-00000000"]}}}) == "unknown reviewer id r-00000000"
assert msg({"repos": {"o/a": {"reviewers": "x"}}}) == "reviewers must be a list of ids or null"
assert msg({"reviewers": LIST[1:], "active_reviewers": [bot_id]}) == f"unknown reviewer id {bot_id}", (
    "removed in the same PUT"
)
assert len(ui_settings.save({"reviewers": many[:50]})["reviewers"]) == 50
r = ui_settings.save({"reviewers": LIST, "active_reviewers": [bot_id, bot_id]})
assert r["active_reviewers"] == [bot_id] and ui_settings.save({"active_reviewers": []})["active_reviewers"] == []
r = ui_settings.save(
    {"active_reviewers": [bot_id], "repos": {"o/a": {"reviewers": [bot_id, masum_id]}, "o/b": {"reviewers": [bot_id]}}}
)
assert r["repos"]["o/a"]["reviewers"] == [bot_id, masum_id] and r["repos"]["o/b"]["reviewers"] == [bot_id]
assert ui_settings.repo_settings("o/b")["reviewers"] == [bot_id]
# omitted keeps: a partial save, and a Repositories table row (auto_grind + slack_channel only)
ui_settings.save({"grind_mode": "simple"})
ui_settings.save({"repos": {"o/a": {"auto_grind": True, "slack_channel": ""}}})
r = ui_settings.load()
assert (
    r["reviewers"] == LIST
    and r["active_reviewers"] == [bot_id]
    and r["repos"]["o/a"]["reviewers"] == [bot_id, masum_id]
)
ui_settings.save({"repos": {"o/b": {"reviewers": []}}})
assert (
    ui_settings.save({"repos": {"o/b": {"auto_grind": True, "slack_channel": ""}}})["repos"]["o/b"]["reviewers"] == []
)
ui_settings.save({"repos": {"o/b": {"reviewers": [bot_id]}}})
# cascade: dropping the bot removes it from the active set and from both overrides (o/b is not in the PUT)
r = ui_settings.save({"reviewers": LIST[1:], "repos": {"o/a": {"slack_channel": ""}}})
assert r["active_reviewers"] == [] and r["repos"]["o/a"]["reviewers"] == [masum_id]
assert r["repos"]["o/b"]["reviewers"] == [], "emptied by the cascade: an explicit empty override, not null"
assert bot_id not in open(ui_settings._path()).read()
r = ui_settings.save({"repos": {"o/a": {"reviewers": None}}})
assert r["repos"]["o/a"]["reviewers"] is None
assert ui_settings.save({"repos": {"o/a": {"slack_channel": ""}}})["repos"]["o/a"]["reviewers"] is None

# FR-9: the first load seeds the lists from the old settings, once
import glob  # noqa: E402
import json  # noqa: E402

CJ = os.path.join(d, "channels.json")


def pre_upgrade(stored, cj=None):
    """Write a pre-upgrade ui_settings.json (no `reviewers`) and channels.json (removed when None)."""
    with open(ui_settings._path(), "w") as f:
        json.dump(stored, f)
    if cj is None:
        if os.path.exists(CJ):
            os.remove(CJ)
    elif isinstance(cj, str):
        with open(CJ, "w") as f:
            f.write(cj)
    else:
        with open(CJ, "w") as f:
            json.dump(cj, f)


def file():
    with open(ui_settings._path()) as f:
        return f.read()


A, B2 = "C0B8385GKNK", "C0123ABCD9"
pre_upgrade(
    {"repos": {"o/a": {"slack_channel": A}, "o/b": {"slack_channel": f" {A} "}, "o/c": {"slack_channel": "#reviews"}}},
    {"channels": {"o/a": A, "o/z": B2, "o/n": 5, "o/m": "bad"}},
)
r = ui_settings.load()
assert r["slack_channels"] == [{"id": A, "name": A}, {"id": B2, "name": B2}], r["slack_channels"]
assert r["repos"]["o/a"]["slack_channel"] == A and r["repos"]["o/b"]["slack_channel"] == f" {A} "
assert r["repos"]["o/c"]["slack_channel"] == "#reviews" and r["repos"]["o/c"]["channel_invalid"] is True
assert not r["repos"]["o/a"]["channel_invalid"] and "o/z" not in r["repos"]
assert r["reviewers"] == [] and r["active_reviewers"] == []
before = file()
assert ui_settings.load() == r and file() == before and ui_settings.repo_settings("o/a") and file() == before

# the bot: bot_label cut to 60, or Review bot; an invalid bot_uid seeds nothing
pre_upgrade({}, {"bot_uid": "U0BS34962FK", "bot_label": "L" * 80})
r = ui_settings.load()
assert [{k: v for k, v in x.items() if k != "id"} for x in r["reviewers"]] == [
    {"name": "L" * 60, "slack_id": "U0BS34962FK", "github_login": ""}
]
assert re.match(r"^r-[0-9a-f]{8}$", r["reviewers"][0]["id"]) and r["active_reviewers"] == [r["reviewers"][0]["id"]]
for label in (None, "", "   ", 5):
    pre_upgrade({}, {"bot_uid": "U0BS34962FK", **({} if label is None else {"bot_label": label})})
    assert ui_settings.load()["reviewers"][0]["name"] == "Review bot", label
pre_upgrade({}, {"bot_uid": "@bot", "bot_label": "Bot"})
r = ui_settings.load()
assert r["reviewers"] == [] and r["active_reviewers"] == []

# GitHub reviewers: deduped ignoring case; the override only where no channel is set anywhere
pre_upgrade(
    {
        "repos": {
            "o/x": {"reviewer": "copilot"},
            "o/y": {"reviewer": " Copilot ", "slack_channel": A},
            "o/w": {"reviewer": "copilot"},
            "o/v": {"reviewer": "bob-1"},
            "o/t": {"reviewer": "org/team"},
        }
    },
    {"bot_uid": "U0BS34962FK", "bot_label": "Bot", "channels": {"o/w": B2}},
)
r = ui_settings.load()
assert [x["github_login"] for x in r["reviewers"]] == ["", "copilot", "bob-1"], r["reviewers"]
bot, cop, bob = (x["id"] for x in r["reviewers"])
assert r["reviewers"][1]["name"] == "copilot" and r["reviewers"][1]["slack_id"] == "" and r["active_reviewers"] == [bot]
assert r["repos"]["o/x"]["reviewers"] == [cop] and r["repos"]["o/v"]["reviewers"] == [bob]
assert r["repos"]["o/y"]["reviewers"] is None and r["repos"]["o/w"]["reviewers"] is None
assert r["repos"]["o/t"]["reviewers"] is None
assert not any(v.get("reviewer") for v in json.loads(file())["repos"].values()), "the old key is dropped"
ids = {x["id"] for x in r["reviewers"]}
ui_settings.load()
ui_settings.repo_settings("o/x")
assert {x["id"] for x in ui_settings.load()["reviewers"]} == ids

# two racing first loads: one set of ids, the one in the file
pre_upgrade({"repos": {"o/x": {"reviewer": "copilot"}}}, {"bot_uid": "U0BS34962FK"})
got = []
ts = [threading.Thread(target=lambda: got.append(ui_settings.load()["reviewers"])) for _ in range(4)]
for t in ts:
    t.start()
for t in ts:
    t.join()
assert all(g == got[0] for g in got) and json.loads(file())["reviewers"] == got[0] and len(got[0]) == 2

# corrupt: a load leaves it alone; save() moves it aside and does not hang
pre_upgrade({}, "{broken")
with open(ui_settings._path(), "w") as f:
    f.write("{broken")
r = ui_settings.load()
assert file() == "{broken" and r["slack_channels"] == [] and r["reviewers"] == []
for p in glob.glob(ui_settings._path() + ".corrupt-*"):
    os.remove(p)
ui_settings.save({})
assert glob.glob(ui_settings._path() + ".corrupt-*") and json.loads(file())["reviewers"] == []
with open(ui_settings._path(), "w") as f:
    f.write("[1]")
assert ui_settings.load()["reviewers"] == [] and file() == "[1]"

# save() on a pre-upgrade file keeps the seeded lists
pre_upgrade({"repos": {"o/a": {"slack_channel": A, "reviewer": "copilot"}}}, {"bot_uid": "U0BS34962FK"})
r = ui_settings.save({"grind_mode": "simple"})
assert r["grind_mode"] == "simple" and r["slack_channels"] == [{"id": A, "name": A}]
assert [x["github_login"] for x in r["reviewers"]] == ["", "copilot"] and r["active_reviewers"] == [
    r["reviewers"][0]["id"]
]
assert r["repos"]["o/a"]["slack_channel"] == A and r["repos"]["o/a"]["reviewers"] is None
assert ui_settings.save({"use_jev": False})["reviewers"] == r["reviewers"], "the seeded list passes validation"

# missing ui_settings.json: created with the marker; missing or corrupt channels.json seeds nothing
for cj in (None, "{broken", "[1]"):
    os.remove(ui_settings._path())
    pre_upgrade({}, cj)
    os.remove(ui_settings._path())
    assert ui_settings.load()["slack_channels"] == [] and json.loads(file())["reviewers"] == [], cj

# at most 50 per list
pre_upgrade({"repos": {f"o/r{i}": {"slack_channel": f"C{i:08d}", "reviewer": f"u{i}"} for i in range(51)}})
r = ui_settings.load()
assert len(r["slack_channels"]) == 50 and len(r["reviewers"]) == 50
pre_upgrade({"repos": {f"o/r{i}": {"reviewer": f"u{i}"} for i in range(51)}})
r = ui_settings.load()
assert len(r["reviewers"]) == 50 and r["repos"]["o/r50"]["reviewers"] is None and r["repos"]["o/r0"]["reviewers"]


# --- account harness and models (#870)
def error(fn, *a):
    """The ValueError message fn raises, or None."""
    try:
        fn(*a)
    except ValueError as e:
        return str(e)
    return None


def stored_accounts():
    return json.loads(file())["commands"]


os.remove(ui_settings._path())
ui_settings.load()["harnesses"][0]["models"].append("x")
assert ui_settings.load()["harnesses"] == HARNESSES, "a caller cannot change the constant"
# an old account (no harness) and an unknown harness both load as claude, nothing else changes
with open(ui_settings._path(), "w") as f:
    json.dump(
        {"commands": [{"label": "Old", "cmd": "cc old"}, {"label": "Odd", "cmd": "cc odd", "harness": "bogus"}]}, f
    )
assert ui_settings.load()["commands"][1:] == [
    {"label": "Old", "cmd": "cc old", "harness": "claude"},
    {"label": "Odd", "cmd": "cc odd", "harness": "claude"},
]
# a Codex account saves and reloads with its harness and models; a Claude row has no models key
CODEX = {"label": "Codex", "cmd": "codex", "harness": "codex", "models": ["gpt-5-codex"]}
r = ui_settings.save({"commands": [BUILTIN, CODEX, {"label": "Main", "cmd": "cc main", "models": [1, ""]}]})
assert r["commands"] == [BUILTIN, CODEX, {"label": "Main", "cmd": "cc main", "harness": "claude"}], r["commands"]
assert ui_settings.load()["commands"] == r["commands"]
assert stored_accounts() == [CODEX, {"label": "Main", "cmd": "cc main", "harness": "claude"}], "Claude models dropped"
r = ui_settings.save({"commands": [{"label": "C2", "cmd": "codex", "harness": "codex"}]})
assert r["commands"][1] == {"label": "C2", "cmd": "codex", "harness": "codex", "models": []}
# the read-only harnesses list is accepted in a body and never stored
r = ui_settings.save({**ui_settings.load(), "harnesses": [{"id": "x"}]})
assert "harnesses" not in json.loads(file()) and r["harnesses"] == HARNESSES
# the 400 messages
H, B, M, U = (
    "harness must be claude or codex",
    "the built-in account is always claude",
    "models must be a list of at most 20 model names",
    "each account needs its own command",
)
assert error(ui_settings.save, {"commands": [{"label": "A", "cmd": "codex", "harness": "gemini"}]}) == H
assert error(ui_settings.save, {"commands": [{"label": "A", "cmd": "codex", "harness": None}]}) == H
assert error(ui_settings.save, {"commands": [{**BUILTIN, "harness": "codex"}]}) == B
assert error(ui_settings.save, {"commands": [{**BUILTIN, "harness": "bogus"}]}) == H
assert error(ui_settings.save, {"commands": [{**BUILTIN, "harness": "claude"}]}) is None
assert ui_settings.load()["commands"] == [BUILTIN] and stored_accounts() == []


def codex_models(models):
    return error(
        ui_settings.validate, {"commands": [{"label": "X", "cmd": "codex", "harness": "codex", "models": models}]}
    )


assert codex_models([f"m{i}" for i in range(20)]) is None and codex_models([f"m{i}" for i in range(21)]) == M
assert codex_models(["a" * 80]) is None and codex_models(["a" * 81]) == M
assert codex_models(["openai/gpt-5.1:mini_x-2"]) is None
for bad in ([""], ["-gpt"], ["gpt 5"], [5], [None], "gpt-5", {"m": 1}, None):
    assert codex_models(bad) == M, bad
# duplicate commands: refused on a full save, the built-in claude counted
dup = [{"label": "A", "cmd": "codex", "harness": "codex"}, {"label": "B", "cmd": "codex "}]
assert error(ui_settings.save, {"commands": dup}) == U
assert error(ui_settings.save, {"commands": [{"label": "A", "cmd": "claude"}]}) == U
# a stored duplicate loads as it is (both claude); a partial save keeps it; an Accounts save refuses it
with open(ui_settings._path(), "w") as f:
    json.dump({"commands": [{"label": "A", "cmd": "cc x"}, {"label": "B", "cmd": "cc x"}]}, f)
assert [c["harness"] for c in ui_settings.load()["commands"]] == ["claude"] * 3
ui_settings.save({"repos": {"o/a": {"slack_channel": ""}}})
assert [c["label"] for c in stored_accounts()] == ["A", "B"]
assert error(ui_settings.save, {"commands": ui_settings.load()["commands"]}) == U
# hand-edited junk in a stored Codex models list is dropped on load, so a partial save still validates
with open(ui_settings._path(), "w") as f:
    junk = ["ok-1", "", 5, "-x", *[f"m{i}" for i in range(25)]]
    json.dump({"commands": [{"label": "C", "cmd": "codex", "harness": "codex", "models": junk}]}, f)
assert ui_settings.load()["commands"][1]["models"] == ["ok-1", *[f"m{i}" for i in range(19)]]
assert error(ui_settings.save, {"repos": {"o/a": {"slack_channel": ""}}}) is None
# harness_of / models_of
ui_settings.save({"commands": [CODEX, {"label": "Main", "cmd": "cc main"}]})
assert ui_settings.harness_of("codex") == "codex" and ui_settings.models_of("codex") == ["gpt-5-codex"]
assert ui_settings.harness_of("cc main") == "claude" and ui_settings.models_of("cc main") == []
assert ui_settings.harness_of("claude") == "claude" and ui_settings.models_of("claude") == []
assert ui_settings.harness_of("nope") == "claude" and ui_settings.models_of("nope") == []
# run_model / run_effort stay on the Claude lists
assert raises(ui_settings.validate, {"run_model": "gpt-5"}) and raises(ui_settings.validate, {"run_effort": "minimal"})
# check_run per harness (#880): Codex accepts any value (it falls back), Claude and no cmd keep the lists
for m, e in (("opus", None), ("gpt-5", "max"), (None, "anything"), ("default", "xhigh")):
    assert error(ui_settings.check_run, m, e, "codex") is None, (m, e)
assert error(ui_settings.check_run, "", None, "codex") == "model must be a non-empty string"
assert error(ui_settings.check_run, None, "a\x00b", "codex") == "effort must be a non-empty string"
assert error(ui_settings.check_run, None, 5, "codex") == "effort must be a non-empty string"
for cmd in ("cc main", None):
    assert error(ui_settings.check_run, "gpt-5", None, cmd) == "model must be one of opus, sonnet, haiku"
    assert error(ui_settings.check_run, None, "ultra", cmd) == "effort must be one of low, medium, high, xhigh, max"
    assert error(ui_settings.check_run, "opus", "max", cmd) is None
print("ui_settings: 158 checks passed")
