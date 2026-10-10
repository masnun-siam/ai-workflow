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

sys.path.insert(0, HERE)
import checks  # noqa: E402
from shared import load_ledger  # noqa: E402

sh("git", "checkout", "-q", "--", "b.txt", cwd=main)
run_dir3 = os.path.join(root, "run3")
aiw("init", run_dir3, "--issue", "7", "--repo", main, cwd=main)
open(os.path.join(main, "mine.txt"), "w").write("mine\n")
assert aiw("worktree", "create", run_dir3, "--main-tree", "--title", "y", "--base", "main", cwd=main).returncode == 0
aiw("set", run_dir3, "base_branch=main", cwd=main)
led = load_ledger(run_dir3)

assert checks.check_sdet_pre(led, {}, main, {}).ok
ok("sdet precheck ignores carried paths")
open(os.path.join(main, "stray.txt"), "w").write("x\n")
assert not checks.check_sdet_pre(led, {}, main, {}).ok
os.remove(os.path.join(main, "stray.txt"))
ok("sdet precheck still fails on a non-carried dirty path")

open(os.path.join(main, "c.txt"), "w").write("c\n")
sh("git", "add", "c.txt", cwd=main)
sh("git", "commit", "-qm", "work", cwd=main)
assert checks._carried_guard(led, main).ok
sh("git", "add", "mine.txt", cwd=main)
sh("git", "commit", "-qm", "oops", cwd=main)
r = checks._carried_guard(led, main)
assert not r.ok and "mine.txt" in r.reason
ok("committing a carried path fails the guard")

p = aiw("gitnexus", "clean", main, cwd=main)
assert p.returncode == 0 and "main checkout" in p.stderr, p.stderr
ok("gitnexus clean refuses a main checkout")

# staged owner changes would ride into the first commit: refuse before branching
sh("git", "checkout", "-q", "main", cwd=main)
sh("git", "reset", "-q", "--hard", "origin/main", cwd=main)
open(os.path.join(main, "staged.txt"), "w").write("s\n")
sh("git", "add", "staged.txt", cwd=main)
run_dir4 = os.path.join(root, "run4")
aiw("init", run_dir4, "--issue", "8", "--repo", main, cwd=main)
p = aiw("worktree", "create", run_dir4, "--main-tree", "--title", "z", "--base", "main", cwd=main)
assert p.returncode == 1 and "staged" in p.stderr.lower(), p.stderr
assert sh("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=main).stdout.strip() == "main"
ok("staged owner changes refuse the main-tree branch and say how to unstage")
sh("git", "reset", "-q", "--hard", "origin/main", cwd=main)

# a carried untracked DIRECTORY is guarded by prefix
os.makedirs(os.path.join(main, "newdir"))
open(os.path.join(main, "newdir", "x.py"), "w").write("x\n")
run_dir5 = os.path.join(root, "run5")
aiw("init", run_dir5, "--issue", "9", "--repo", main, cwd=main)
assert aiw("worktree", "create", run_dir5, "--main-tree", "--title", "d", "--base", "main", cwd=main).returncode == 0
aiw("set", run_dir5, "base_branch=main", cwd=main)
led5 = load_ledger(run_dir5)
assert "newdir/" in led5.context["carried"], led5.context["carried"]
sh("git", "add", "newdir/x.py", cwd=main)
sh("git", "commit", "-qm", "oops", cwd=main)
r = checks._carried_guard(led5, main)
assert not r.ok and "newdir/x.py" in r.reason, r.reason
ok("a committed file inside a carried untracked directory fails the guard")

print(f"{n_ok} passed")
