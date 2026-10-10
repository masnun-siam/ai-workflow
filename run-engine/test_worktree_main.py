"""Tests for `worktree create --main-tree`: plain asserts, run with `python3 test_worktree_main.py`."""
import json
import os
import subprocess
import sys
import tempfile

os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()
HERE = os.path.dirname(os.path.abspath(__file__))
ROUTE = os.path.join(HERE, "route.py")

n_ok = 0


def ok(label):
    global n_ok
    n_ok += 1
    print(f"  ok  {label}")


def sh(*a, cwd):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True)


def aiw(*a, cwd):
    return subprocess.run([sys.executable, ROUTE, *a], cwd=cwd, capture_output=True, text=True)


root = tempfile.mkdtemp()
origin, main = os.path.join(root, "origin.git"), os.path.join(root, "main")
sh("git", "init", "-q", "--bare", "-b", "main", origin, cwd=root)
sh("git", "clone", "-q", origin, main, cwd=root)
for k, v in (("user.email", "t@t"), ("user.name", "t")):
    sh("git", "config", k, v, cwd=main)
open(os.path.join(main, "a.txt"), "w").write("a\n")
open(os.path.join(main, "b.txt"), "w").write("b\n")
sh("git", "add", "a.txt", "b.txt", cwd=main)
sh("git", "commit", "-qm", "init", cwd=main)
sh("git", "branch", "-M", "main", cwd=main)
sh("git", "push", "-q", "origin", "main", cwd=main)

run_dir = os.path.join(root, "run")
assert aiw("init", run_dir, "--issue", "5", "--repo", main, cwd=main).returncode == 0

# owner's uncommitted work: one modified tracked file, one untracked file
open(os.path.join(main, "a.txt"), "w").write("a mine\n")
open(os.path.join(main, "notes.md"), "w").write("mine\n")

p = aiw("worktree", "create", run_dir, "--main-tree", "--title", "Fix the thing", "--base", "main", cwd=main)
assert p.returncode == 0, p.stderr
ctx = json.load(open(os.path.join(run_dir, "run.json")))["context"]
assert ctx["tree"] == "main" and ctx["branch"] == "issue-5-fix-the-thing"
assert ctx["worktree"] == ctx["repo"] == ctx["main_checkout"] == os.path.abspath(main)
assert sorted(ctx["carried"]) == ["a.txt", "notes.md"]
assert sh("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=main).stdout.strip() == "issue-5-fix-the-thing"
assert open(os.path.join(main, "a.txt")).read() == "a mine\n"
assert not os.path.exists(os.path.join(root, "wt-issue-5"))
ok("branches in the main checkout, carries the owner's edits, records them")

# resume: elsewhere, then create again -> back on the branch, nothing re-recorded
sh("git", "stash", "-q", "-u", cwd=main)  # test-only: get a clean tree to switch branches
sh("git", "checkout", "-q", "main", cwd=main)
p = aiw("worktree", "create", run_dir, "--main-tree", "--title", "Fix the thing", "--base", "main", cwd=main)
assert p.returncode == 0 and "resumed on issue-5-fix-the-thing" in p.stdout, p.stdout + p.stderr
assert sh("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=main).stdout.strip() == "issue-5-fix-the-thing"
sh("git", "stash", "pop", "-q", cwd=main)
ok("resume re-checks-out the run's branch")

# collision: base changed b.txt, owner also edited b.txt -> refuse, name it, keep the edit
sh("git", "checkout", "-q", "main", cwd=main)
sh("git", "checkout", "-q", "--", "a.txt", cwd=main)
os.remove(os.path.join(main, "notes.md"))
open(os.path.join(main, "b.txt"), "w").write("b upstream\n")
sh("git", "commit", "-qam", "upstream", cwd=main)
sh("git", "push", "-q", "origin", "main", cwd=main)
sh("git", "reset", "-q", "--hard", "HEAD~1", cwd=main)
open(os.path.join(main, "b.txt"), "w").write("b mine\n")
run_dir2 = os.path.join(root, "run2")
aiw("init", run_dir2, "--issue", "6", "--repo", main, cwd=main)
p = aiw("worktree", "create", run_dir2, "--main-tree", "--title", "x", "--base", "main", cwd=main)
assert p.returncode == 1 and "b.txt" in p.stderr, p.stderr
assert open(os.path.join(main, "b.txt")).read() == "b mine\n"
assert sh("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=main).stdout.strip() == "main"
ok("a carried edit that collides with the base refuses and names the file")

print(f"{n_ok} passed")
