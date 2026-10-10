"""Tests for maintree: plain asserts, run with `python3 test_maintree.py`."""
import json
import os
import sys
import tempfile

os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import maintree as m  # noqa: E402
import shared  # noqa: E402

n_ok = 0


def ok(label):
    global n_ok
    n_ok += 1
    print(f"  ok  {label}")


SLUG = "o/r"
CI = {"state": "green"}
m.ci.snapshot = lambda owner, repo, number: {"state": CI["state"], "head_sha": "x", "failing": []}


def ledger(issue, status, pr=None):
    d = shared.run_dir_for(os.path.join(shared.data_dir(), "runs"), SLUG, issue)
    os.makedirs(d, exist_ok=True)
    ctx = {"pr": pr} if pr else {}
    with open(os.path.join(d, "run.json"), "w") as f:
        json.dump({"issue": issue, "status": status, "context": ctx}, f)


def grind_file(pr, line):
    d = os.path.join(shared.data_dir(), "pr-grind")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"o-r-{pr}.md"), "w") as f:
        f.write(f"owner: o\nrepo: r\nnumber: {pr}\nthread: https://x.slack.com/t\n{line}\n")


PR = "https://github.com/o/r/pull/{}"

# --- porcelain_paths
assert shared.porcelain_paths(" M a.py\n?? b/c.txt\nR  old.py -> new.py\n") == ["a.py", "b/c.txt", "new.py"]
ok("porcelain_paths: modified, untracked, rename target")

# --- first caller gets the tree, second waits behind it
assert m.acquire(SLUG, 1, grind=False) == {"granted": True}
ledger(1, "running")
w = m.acquire(SLUG, 2, grind=False)
assert not w["granted"] and w["ahead"] == 1 and w["phase"] == "running" and w["position"] == 1
ok("second caller waits behind a running holder")
assert m.acquire(SLUG, 1, grind=False) == {"granted": True}
ok("re-acquire by the holder (resume, its own grind) is granted")

# --- done + green CI releases on the next poll; FIFO
m.acquire(SLUG, 3, grind=False)
ledger(1, "done", PR.format(11))
assert m.acquire(SLUG, 3, grind=False)["granted"] is False
ok("FIFO: #3 cannot jump #2 when the tree frees")
assert m.acquire(SLUG, 2, grind=False) == {"granted": True}
ok("holder done + CI green -> released, first waiter gets it")

# --- CI pending / red
ledger(2, "done", PR.format(12))
CI["state"] = "pending"
assert m.status(SLUG)["holder"]["phase"] == "ci"
CI["state"] = "red"
h = m.status(SLUG)["holder"]
assert h["phase"] == "blocked" and h["reason"] == "CI is red"
ok("pending CI holds, red CI blocks")
CI["state"] = "green"

# --- grind: missing file = grinding, paused = blocked, done approved = released
assert m.release(SLUG, 2) is True
assert m.acquire(SLUG, 3, grind=True) == {"granted": True}
ledger(3, "done", PR.format(13))
assert m.status(SLUG)["holder"]["phase"] == "grinding"
grind_file(13, "paused: 2026-10-10T00:00:00Z — needs a decision")
assert m.status(SLUG)["holder"]["phase"] == "blocked"
grind_file(13, "done: 2026-10-10T00:00:00Z — rail 4 stopped")
assert m.status(SLUG)["holder"]["phase"] == "blocked"
grind_file(13, "done: 2026-10-10T00:00:00Z — approved")
assert m.status(SLUG)["holder"]["phase"] == "done"
ok("grind: not started -> grinding, paused/unapproved -> blocked, approved -> done")

# --- escalated run blocks; manual release of a blocked or dead-running holder hands over
m.release(SLUG)
m.acquire(SLUG, 4, grind=False)
ledger(4, "escalated")
assert m.status(SLUG)["holder"]["phase"] == "blocked"
ledger(4, "running")  # a killed session leaves the ledger running forever
m.acquire(SLUG, 5, grind=False)
assert m.acquire(SLUG, 5, grind=False)["granted"] is False
assert m.release(SLUG) is True and m.acquire(SLUG, 5, grind=False) == {"granted": True}
ok("manual release of a stuck holder hands the tree to the first waiter")

# --- stale waiter dropped, cancel removes
m.release(SLUG)
m.acquire(SLUG, 6, grind=False)
ledger(6, "running")
m.acquire(SLUG, 7, grind=False)
m.acquire(SLUG, 8, grind=False)
rec = m.load(SLUG)
rec["queue"][0]["seen"] -= m.STALE + 1
m._save(SLUG, rec)
assert m.acquire(SLUG, 8, grind=False)["position"] == 1
ok("waiter silent past STALE loses its place")
m.cancel(SLUG, 8)
assert m.status(SLUG)["queue"] == []
ok("cancel removes a waiter")

# --- for_issue
assert m.for_issue("o", "r", 6)["role"] == "holder"
m.acquire(SLUG, 9, grind=False)
assert m.for_issue("O", "R", 9) == {"role": "queued", "position": 1, "ahead": 6}
assert m.for_issue("o", "r", 99) is None
ok("for_issue: holder / queued / unrelated")

# --- phase 10 skipped on a degraded finish: not "grinding" forever
m.cancel(SLUG, 9)
m.release(SLUG)
m.acquire(SLUG, 20, grind=True)
d = shared.run_dir_for(os.path.join(shared.data_dir(), "runs"), SLUG, 20)
os.makedirs(d, exist_ok=True)
json.dump({"issue": 20, "status": "done", "context": {"pr": PR.format(20), "grind": "skipped"}}, open(os.path.join(d, "run.json"), "w"))
h = m.status(SLUG)["holder"]
assert h["phase"] == "blocked" and "skipped" in h["reason"], h
ok("a run that skipped phase 10 blocks the tree instead of reading as grinding")

print(f"{n_ok} passed")
