#!/usr/bin/env python3
"""Self-check for run-engine/ui_cleanup.py. `python3 test_ui_cleanup.py` — exit 0 = green.

Real git in tempdirs; CLAUDE_PLUGIN_DATA points at a fresh tempdir. No gh: PR state is "unknown".
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ui_cleanup  # noqa: E402
import ui_sessions  # noqa: E402

passed = 0


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


def git(cwd, *a):
    subprocess.run(["git", "-C", cwd, *a], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def setup(issue: int, status: str):
    """data dir + main checkout + worktree + ledger + one stopped session linked to the issue."""
    root = tempfile.mkdtemp()
    os.environ["CLAUDE_PLUGIN_DATA"] = os.path.join(root, "data")
    main = os.path.join(root, "proj")
    os.makedirs(main)
    git(main, "init", "-q", "-b", "main")
    git(main, "commit", "-q", "--allow-empty", "-m", "init")
    origin = os.path.join(root, "origin.git")  # real runs branch from origin/<base>, so main is on a remote
    subprocess.run(["git", "init", "-q", "--bare", origin], check=True)
    git(main, "remote", "add", "origin", origin)
    git(main, "push", "-q", "origin", "main")
    wt, branch = os.path.join(root, f"wt-issue-{issue}"), f"issue-{issue}-thing"
    git(main, "worktree", "add", "-q", wt, "-b", branch)
    run_dir = os.path.join(root, "data", "runs", f"acme-widgets-issue-{issue}")
    os.makedirs(run_dir)
    ledger = {"issue": issue, "status": status, "stations": ["dev"], "currentIndex": 0,
              "context": {"main_checkout": main, "worktree": wt, "branch": branch}}
    json.dump(ledger, open(os.path.join(run_dir, "run.json"), "w"))
    s = ui_sessions.create("/run-issue", main, link={"owner": "acme", "repo": "widgets", "issue": issue})
    ui_sessions.update(s["id"], status="stopped")
    return main, wt, branch, run_dir, s["id"]


def branches(main):
    return subprocess.run(["git", "-C", main, "branch", "--list"], capture_output=True, text=True).stdout


# stopped run: worktree + data go, branch stays
main, wt, branch, run_dir, sid = setup(7, "running")
[t] = ui_cleanup.find_targets()
assert t["key"] == "acme/widgets#7" and t["status"] == "stopped", t
d = ui_cleanup.describe(t)
assert d["has_worktree"] and d["flags"] == [] and d["sessions"] == 1, d
r = ui_cleanup.clean(t, False)
assert r["ok"], r
assert not os.path.exists(wt) and not os.path.exists(run_dir) and ui_sessions.load(sid) is None
assert branch in branches(main)
assert ui_cleanup.find_targets() == []
ok("stopped run: worktree, run dir, session removed; branch kept")

# dirty worktree blocks until forced
main, wt, branch, run_dir, sid = setup(8, "running")
open(os.path.join(wt, "x.txt"), "w").write("wip")
[t] = ui_cleanup.find_targets()
assert ui_cleanup.describe(t)["flags"] == ["uncommitted changes"]
r = ui_cleanup.clean(t, False)
assert not r["ok"] and r["flagged"] and os.path.isdir(wt) and os.path.isdir(run_dir)
assert ui_cleanup.clean(t, True)["ok"] and not os.path.exists(wt)
ok("dirty worktree blocked unless forced")

# done run: branch deleted too; unpushed commit flagged
main, wt, branch, run_dir, sid = setup(9, "done")
git(wt, "commit", "-q", "--allow-empty", "-m", "work")
[t] = ui_cleanup.find_targets()
assert t["status"] == "done" and ui_cleanup.describe(t)["flags"] == ["1 unpushed commit(s)"]
assert not ui_cleanup.clean(t, False)["ok"] and branch in branches(main)
r = ui_cleanup.clean(t, True)
assert r["ok"] and branch not in branches(main) and not os.path.exists(run_dir), r
assert any("issue left open" in n for n in r["notes"])
ok("done run: unpushed flagged, then branch deleted and issue left open without a PR")

# live session and escalated ledger are never targets
main, wt, branch, run_dir, sid = setup(10, "running")
ui_sessions.update(sid, status="running")
assert ui_cleanup.find_targets() == []
ui_sessions.update(sid, status="stopped")
led = json.load(open(os.path.join(run_dir, "run.json")))
led["status"] = "escalated"
json.dump(led, open(os.path.join(run_dir, "run.json"), "w"))
assert ui_cleanup.find_targets() == []
ok("live sessions and escalated runs are not listed")

# escalated but PR merged on GitHub: offered as done
ui_cleanup._pr_merged = lambda pr: True
main, wt, branch, run_dir, sid = setup(12, "escalated")
led = json.load(open(os.path.join(run_dir, "run.json")))
led["context"]["pr"] = "https://github.com/acme/widgets/pull/9"
json.dump(led, open(os.path.join(run_dir, "run.json"), "w"))
[t12] = [x for x in ui_cleanup.find_targets() if x["issue"] == 12]
assert t12["status"] == "done"
ui_cleanup._pr_merged = lambda pr: False
assert not [x for x in ui_cleanup.find_targets() if x["issue"] == 12]
ok("escalated run is cleanable only when its PR is merged")

# session-less unfinished ledger: hidden while fresh (CLI run may be live), offered once stale
main, wt, branch, run_dir, sid = setup(11, "running")
shutil.rmtree(ui_sessions.session_dir(sid))
assert [x for x in ui_cleanup.find_targets() if x["issue"] == 11] == []
old = time.time() - ui_cleanup.STALE_SECONDS - 60
os.utime(os.path.join(run_dir, "run.json"), (old, old))
[t] = [x for x in ui_cleanup.find_targets() if x["issue"] == 11]
assert t["status"] == "stopped" and t["sessions"] == []
ok("session-less unfinished ledger is offered only once stale")

# link-less session: session dir only
setup(11, "running")
loose = ui_sessions.create("/other", "/tmp")
ui_sessions.update(loose["id"], status="done")
keys = {t["key"] for t in ui_cleanup.find_targets()}
assert f"session:{loose['id']}" in keys
t = next(t for t in ui_cleanup.find_targets() if t["key"] == f"session:{loose['id']}")
assert ui_cleanup.clean(t, False)["ok"] and ui_sessions.load(loose["id"]) is None
ok("link-less session cleaned alone")

# main-tree run: nothing removed; base checked out when clean; a done run's branch is deleted
def setup_main(issue: int, status: str):
    main, wt, branch, run_dir, sid = setup(issue, status)
    git(main, "worktree", "remove", "--force", wt)
    git(main, "checkout", "-q", branch)
    led = json.load(open(os.path.join(run_dir, "run.json")))
    led["context"].update(tree="main", worktree=main, base_branch="main", carried=[])
    json.dump(led, open(os.path.join(run_dir, "run.json"), "w"))
    return main, branch, run_dir


def head(main):
    return subprocess.run(["git", "-C", main, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True).stdout.strip()


main, branch, run_dir = setup_main(12, "done")
[t] = ui_cleanup.find_targets()
assert t["plan"]["worktree"] is None and t["plan"]["branch"] == branch, t["plan"]
assert ui_cleanup.describe(t)["has_worktree"] is False
r = ui_cleanup.clean(t, False)
assert r["ok"], r
assert os.path.isdir(main) and head(main) == "main" and branch not in branches(main) and not os.path.exists(run_dir)
ok("main-tree cleanup checks out the base and deletes the done branch, keeps the checkout")

main, branch, run_dir = setup_main(13, "done")
open(os.path.join(main, "dirty.txt"), "w").write("wip")
[t] = ui_cleanup.find_targets()
r = ui_cleanup.clean(t, False)
assert r["ok"] and head(main) == branch and branch in branches(main), r
ok("a dirty main tree stays on its branch")

print(f"{passed} passed")
