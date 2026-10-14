#!/usr/bin/env python3
"""Self-check for run-engine/ui_vault.py and no-repo sessions. `python3 test_ui_vault.py` — exit 0 = green.

Assert-based, no framework. CLAUDE_PLUGIN_DATA and the vault point at temp dirs; nothing real is touched.
"""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DATA = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = DATA

import dispatch  # noqa: E402
import ui_repos  # noqa: E402
import ui_runner  # noqa: E402
import ui_settings  # noqa: E402
import ui_vault  # noqa: E402

passed = 0


def ok(label):
    global passed
    passed += 1
    print(f"  ok  {label}")


VAULT = tempfile.mkdtemp()
os.makedirs(os.path.join(VAULT, "05-Work", "Shop", "Checkout"))
os.makedirs(os.path.join(VAULT, "05-Work", "Shop", ".hidden"))
os.makedirs(os.path.join(VAULT, "05-Work", "Gym"))
PRD = """---
tags: [work]
---
# PRD — Checkout

**Status:** Approved · **Date:** 2026-10-15

## Overview
One-page checkout for the shop.

## Problem
Carts are abandoned.
"""
with open(os.path.join(VAULT, "05-Work", "Shop", "Checkout", "PRD.md"), "w") as fh:
    fh.write(PRD)
ui_settings.vault_dir = lambda: VAULT  # the vault the server would read from Settings

# --- folder rules and listing
assert ui_vault.valid_folder("05-Work/Shop/Checkout") and ui_vault.valid_folder("05-Work/New Idea/First Cut")
for bad in ("05-Work/../x", "05-Work/a/../../etc", "Other/x", "05-Work/.git", "05-Work/a/b/c", "", None, "/05-Work/a"):
    assert not ui_vault.valid_folder(bad), bad
assert [f["path"] for f in ui_vault.folders()] == ["05-Work/Gym", "05-Work/Shop", "05-Work/Shop/Checkout"]
assert ui_vault.folders(tempfile.mkdtemp()) == [], "no 05-Work: an empty list, not an error"
ok("vault folders: 05-Work/<Project>[/<Feature>] only, hidden and traversal refused")

# --- Claude's suggestion is parsed defensively
got = ui_vault.parse_suggestion(
    'Sure!\n{"project": "Gym/App", "feature": "Check-ins", "new_project": true, "why": "' + "x" * 300 + '"}'
)
assert (
    got["project"] == "Gym App"
    and got["feature"] == "Check-ins"
    and got["new_project"] is True
    and got["new_feature"] is False
)
assert len(got["why"]) == 200
for bad in ("no json here", '{"project": ""}', '{"project": ".x", "feature": "y"}', "[1]"):
    assert ui_vault.parse_suggestion(bad) is None, bad
assert ui_vault.suggest("")[0] == 400
ok("suggestion: JSON pulled from prose, slashes stripped, empty or hidden names rejected")

# --- PRD status and README
info = ui_vault.prd_info("05-Work/Shop/Checkout")
assert info == {"exists": True, "status": "Approved", "title": "Checkout", "folder": "05-Work/Shop/Checkout"}, info
assert ui_vault.prd_info("05-Work/Gym")["exists"] is False
try:
    ui_vault.prd_info("05-Work/../x")
    raise AssertionError("traversal accepted")
except ValueError:
    pass
readme = ui_vault.readme_from_prd(PRD, "shop")
assert (
    readme.startswith("# Checkout\n\nOne-page checkout for the shop.")
    and "tags" not in readme
    and "Carts" not in readme
)
ok("PRD: status and title read from the header; README is the title plus the Overview")

# --- create_repo: local git repo, PRD copied, registered as local/<name>
parent = tempfile.mkdtemp()
made = ui_vault.create_repo(parent, "shop", "05-Work/Shop/Checkout")
assert made["slug"] == "local/shop" and os.path.isdir(os.path.join(made["path"], ".git"))
with open(os.path.join(made["path"], "docs", "prds", "checkout.md")) as fh:
    assert fh.read().startswith("# PRD — Checkout"), "frontmatter stripped"
assert dispatch.read_checkouts()["local/shop"] == made["path"]
log = subprocess.run(["git", "-C", made["path"], "log"], capture_output=True, text=True)
assert log.returncode != 0, "nothing committed"
for args, why in (
    ((parent, "shop", None), "exists or registered"),
    ((parent, "../x", None), "bad name"),
    (("relative", "y", None), "relative parent"),
    ((parent, "z", "05-Work/Gym"), "no PRD"),
):
    try:
        ui_vault.create_repo(*args)
        raise AssertionError(why)
    except ValueError:
        pass
assert not os.path.exists(os.path.join(parent, "z")), "a failed create leaves nothing behind"
bare = ui_vault.create_repo(parent, "empty")
with open(os.path.join(bare["path"], "README.md")) as fh:
    assert fh.read() == "# empty\n" and bare["files"] == ["README.md"]
ok("create repo: git init, PRD in docs/prds/, README, local/<name> registered, nothing committed; bad input refused")

# --- a local repo is re-registered under its GitHub name once it has an origin
subprocess.run(["git", "-C", made["path"], "remote", "add", "origin", "git@github.com:acme/shop.git"], check=True)
ui_repos.promote_local()
co = dispatch.read_checkouts()
assert "local/shop" not in co and co["acme/shop"] == made["path"] and co["local/empty"] == bare["path"]
ok("promote: local/<name> becomes owner/repo when an origin appears; others untouched")

# a local repo whose origin name is already another checkout stays local and says why
taken = ui_vault.create_repo(parent, "dup")
subprocess.run(["git", "-C", taken["path"], "remote", "add", "origin", "https://github.com/acme/shop.git"], check=True)
ui_repos.promote_local()
assert dispatch.read_checkouts()["local/dup"] == taken["path"], "nothing overwritten"
assert not dispatch.rename_checkout("local/dup", "ACME/shop") and not dispatch.rename_checkout("gone/x", "a/b")
ok("promote: a taken owner/repo is never overwritten")

# --- no-repo sessions run in the vault, only for the commands that allow it
started = []
ui_runner.start = lambda text, cwd, link=None, **kw: started.append((text, cwd, link)) or {"id": "x"}
ui_repos.ui_sessions.update = lambda sid, **f: {"id": sid, **f}
s, res = ui_repos.start_session(
    {"no_repo": True, "command": "create-prd", "args": "gym check-ins", "vault_folder": "05-Work/Gym/Check-ins"}
)
assert s == 201 and started[-1][1] == VAULT and started[-1][2] is None, (s, res)
text = started[-1][0]
assert (
    text.startswith("/create-prd gym check-ins") and "05-Work/Gym/Check-ins" in text and text.endswith("--to obsidian")
), text
assert res["no_repo"] is True and res["vault_folder"] == "05-Work/Gym/Check-ins"
s, res = ui_repos.start_session({"no_repo": True, "text": "sketch a pricing page"})
assert s == 201 and "No vault folder was chosen" in started[-1][0]
s, res = ui_repos.start_session({"no_repo": True, "command": "run-issue", "args": "7"})
assert s == 400 and "needs a repo" in res["error"], res
s, res = ui_repos.start_session({"no_repo": True, "command": "dump", "args": "x", "vault_folder": "05-Work/../etc"})
assert s == 400, res
s, res = ui_repos.start_session({"repo": "local/empty", "command": "run-issue", "args": "7"})
assert s == 400 and "GitHub remote" in res["error"], res
s, res = ui_repos.start_session({"repo": "local/dup", "command": "run-issue", "args": "7"})
assert s == 400 and "already registered to another checkout" in res["error"], res
assert json.dumps(started)  # nothing odd went to the runner
ok("no-repo sessions: vault cwd, folder hint, create-prd --to obsidian; other commands and local repos refused")

print(f"\n{passed} checks passed")
