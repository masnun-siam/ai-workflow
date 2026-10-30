"""ui_actions: the drawer's writes build the right gh argv, validate input, and a PRD save commits one file."""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui_actions  # noqa: E402

calls = []


def ok_runner(args):
    calls.append(args)
    return {"html_url": "https://github.com/o/r/issues/1#c"}, subprocess.CompletedProcess(args, 0, "", "")


def bad_runner(args):
    return None, subprocess.CompletedProcess(args, 1, "", "GraphQL: Pull request is not mergeable")


assert ui_actions.comment("o", "r", "7", "hi there", ok_runner)["url"].endswith("#c")
assert calls[-1] == ["api", "repos/o/r/issues/7/comments", "-f", "body=hi there"]
ui_actions.set_state("o", "r", 7, "closed", "not_planned", ok_runner)
assert calls[-1] == ["issue", "close", "7", "-R", "o/r", "--reason", "not planned"]
ui_actions.set_state("o", "r", 7, "open", None, ok_runner)
assert calls[-1] == ["issue", "reopen", "7", "-R", "o/r"]
ui_actions.merge("o", "r", "9", ok_runner)
assert calls[-1] == ["pr", "merge", "9", "-R", "o/r", "--merge"], "a merge commit, never squash"
assert ui_actions.set_pr_state("o", "r", 9, "closed", ok_runner) == {"ok": True, "state": "closed"}
assert calls[-1] == ["pr", "close", "9", "-R", "o/r"], "branch kept, no comment"
assert ui_actions.set_pr_state("o", "r", 9, "open", ok_runner) == {"ok": True, "state": "open"}
assert calls[-1] == ["pr", "reopen", "9", "-R", "o/r"]
n_calls = len(calls)
for bad in (
    lambda: ui_actions.set_pr_state("o", "r", 9, "merged", ok_runner),
    lambda: ui_actions.set_pr_state("o", "r", 9, None, ok_runner),
    lambda: ui_actions.set_pr_state("o", "../x", 9, "closed", ok_runner),
    lambda: ui_actions.set_pr_state("o", "r", "7; rm", "open", ok_runner),
):
    try:
        bad()
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
assert len(calls) == n_calls, "a bad state or id runs no gh command"
try:
    ui_actions.set_pr_state("o", "r", 9, "open", bad_runner)
    raise AssertionError("expected RuntimeError")
except RuntimeError as e:
    assert "not mergeable" in str(e)
for bad in (
    lambda: ui_actions.comment("o", "r", "7", "  ", ok_runner),
    lambda: ui_actions.comment("o", "../x", "7", "x", ok_runner),
    lambda: ui_actions.set_state("o", "r", "7", "closed", "duplicate", ok_runner),
    lambda: ui_actions.set_state("o", "r", "7", "locked", None, ok_runner),
    lambda: ui_actions.merge("o", "r", "7; rm", ok_runner),
):
    try:
        bad()
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
try:
    ui_actions.merge("o", "r", "9", bad_runner)
    raise AssertionError("expected RuntimeError")
except RuntimeError as e:
    assert "not mergeable" in str(e)
print("ok  gh writes: comment, close/reopen with reason, merge commit; bad input refused; gh errors surface")

with tempfile.TemporaryDirectory() as co:
    g = lambda *a: subprocess.run(["git", *a], cwd=co, capture_output=True, text=True, check=True)  # noqa: E731
    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    os.makedirs(os.path.join(co, "docs", "prds"))
    with open(os.path.join(co, "docs", "prds", "x.md"), "w") as f:
        f.write("# X\n")
    with open(os.path.join(co, "other.txt"), "w") as f:
        f.write("a")
    g("add", "-A")
    g("commit", "-qm", "init")
    with open(os.path.join(co, "other.txt"), "w") as f:
        f.write("staged, not ours")
    g("add", "other.txt")
    r = ui_actions.read_prd(co, "docs/prds/x.md")
    blob = g("hash-object", "docs/prds/x.md").stdout.strip()
    assert r == {"path": "docs/prds/x.md", "text": "# X\n", "sha": blob, "branch": "main"}, "sha is git's blob hash"
    assert ui_actions.save_prd(co, "docs/prds/x.md", "# X\n")["committed"] is False
    for stale in ("0" * 40, 5):
        try:
            ui_actions.save_prd(co, "docs/prds/x.md", "# X\n\nmore\n", stale)
            raise AssertionError("a stale base_sha must be refused")
        except (ui_actions.Conflict, ValueError) as e:
            assert (str(e) == "changed on disk") == (stale == "0" * 40)
    assert open(os.path.join(co, "docs", "prds", "x.md")).read() == "# X\n", "refused save writes nothing"
    r = ui_actions.save_prd(co, "docs/prds/x.md", "# X\n\nmore\n", blob)
    assert r["committed"] and r["branch"] == "main" and r["commit"]
    assert r["sha"] == g("hash-object", "docs/prds/x.md").stdout.strip()
    assert g("show", "--name-only", "--format=%s", "HEAD").stdout.split() == [
        "docs(prd):",
        "edit",
        "x",
        "from",
        "aiw",
        "ui",
        "docs/prds/x.md",
    ]
    assert "other.txt" in g("diff", "--cached", "--name-only").stdout, "someone else's staged change stays staged"
    for rel in ("../etc/passwd", "docs/prds/../../x.md", "docs/prds/none.md", "README.md"):
        try:
            ui_actions.read_prd(co, rel)
            raise AssertionError(rel)
        except ValueError:
            pass
print("ok  PRD: read with branch, save commits only that file, unchanged is a no-op, paths outside docs/prds refused")

snap = {
    "data": {
        "issues": [
            {"n": 1, "parent": None, "sub_issues": [4]},
            {"n": 2, "parent": 1, "sub_issues": []},
            {"n": 3, "parent": 9, "sub_issues": []},
            {"n": 4, "parent": None, "sub_issues": []},
        ]
    }
}
assert ui_actions.open_children(snap, 1) == [2, 4]
calls.clear()
assert ui_actions.close_epic("o", "r", 1, [2, 4], ok_runner) == {"ok": True, "closed": [2, 4, 1]}
assert [c[:3] for c in calls] == [["issue", "close", "2"], ["issue", "close", "4"], ["issue", "close", "1"]]
n = {"i": 0}


def fail_second(args):
    n["i"] += 1
    return ok_runner(args) if n["i"] != 2 else bad_runner(args)


try:
    ui_actions.close_epic("o", "r", 1, [2, 4], fail_second)
    raise AssertionError("expected RuntimeError")
except RuntimeError as e:
    assert "#4" in str(e) and "closed so far: #2" in str(e), e
print("ok  close epic: children (parent or sub-issue) first, then the epic; a failure says what closed")
