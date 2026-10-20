#!/usr/bin/env python3
"""Self-check for run-engine/ui_mergeclean.py on temp git repos. `python3 test_ui_mergeclean.py`"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui_mergeclean as mc  # noqa: E402

tmp = os.path.realpath(tempfile.mkdtemp())
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_GLOBAL": "/dev/null",
}


def git(cwd, *a):
    p = subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True, env=ENV)
    assert p.returncode == 0, (a, p.stderr)
    return p.stdout.strip()


git(tmp, "init", "-q", "--bare", "-b", "main", "origin.git")
main = os.path.join(tmp, "main")
subprocess.run(["git", "clone", "-q", os.path.join(tmp, "origin.git"), main], check=True, capture_output=True, env=ENV)
git(main, "checkout", "-q", "-b", "main")
open(os.path.join(main, "a"), "w").write("a")
git(main, "add", "a")
git(main, "commit", "-qm", "init")
git(main, "push", "-q", "origin", "main")
git(main, "fetch", "-q")
open(os.path.join(tmp, "outside"), "w").write("keep")


def wt(n, slug="x"):
    git(main, "worktree", "add", "-q", "-b", f"issue-{n}-{slug}", f".worktrees/{n}-{slug}", "origin/main")
    return os.path.join(main, ".worktrees", f"{n}-{slug}")


def exists_branch(b):
    return bool(git(main, "branch", "--list", b))


# clean worktree: removed with its branch by on_merged
p1 = wt(1)
assert mc.check(main, 1) is None
assert mc.on_merged("o/r", [1], checkout=main) == {}
assert not os.path.exists(p1) and not exists_branch("issue-1-x")

# uncommitted file: kept, flagged
p2 = wt(2)
open(os.path.join(p2, "f"), "w").write("x")
assert mc.on_merged("o/r", [2], checkout=main) == {2: {"uncommitted": ["f"], "unpushed": []}}
assert os.path.isdir(p2) and exists_branch("issue-2-x")
assert mc.clean(main, 2, False)["removed"] == [] and os.path.isdir(p2)

# unpushed commit: sha listed
p3 = wt(3)
open(os.path.join(p3, "g"), "w").write("g")
git(p3, "add", "g")
git(p3, "commit", "-qm", "wip")
sha = git(p3, "rev-parse", "HEAD")
assert mc.check(main, 3) == {"uncommitted": [], "unpushed": [sha]}
assert os.path.isdir(p3)

# confirm discards flagged work; the main checkout and outside files are untouched
res = mc.clean(main, 2, True)
assert not os.path.exists(p2) and not exists_branch("issue-2-x") and res["flagged"] is None
assert os.path.isfile(os.path.join(main, "a")) and open(os.path.join(tmp, "outside")).read() == "keep"
assert git(main, "rev-parse", "--abbrev-ref", "HEAD") == "main"

# worktree removed by hand: only the branch goes
p4 = wt(4)
import shutil  # noqa: E402

shutil.rmtree(p4)
git(main, "worktree", "prune")
assert exists_branch("issue-4-x")
assert mc.on_merged("o/r", [4], checkout=main) == {}
assert not exists_branch("issue-4-x")

# unknown issue / issue whose branch is the main checkout's HEAD: nothing happens
assert mc.clean(main, 99, True) == {"removed": [], "flagged": None}
git(main, "branch", "issue-5-y")
git(main, "checkout", "-q", "issue-5-y")
assert mc.clean(main, 5, True)["removed"] == [] and exists_branch("issue-5-y")
assert mc.on_merged("o/r", [1], checkout=os.path.join(tmp, "nope")) == {}
print("ok")
