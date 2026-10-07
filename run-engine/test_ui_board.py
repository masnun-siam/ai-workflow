#!/usr/bin/env python3
"""Self-check for run-engine/ui_board.py. `python3 test_ui_board.py` — exit 0 = green.

Deliberately assert-based with no framework, matching run-engine/test_engine.py:
this file must run anywhere python3 does, with no install step.
"""

from __future__ import annotations

import importlib.machinery
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ui_board
from ui_board import STATIONS, build_board, memoize_title_fetcher

passed = 0


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


def ledger(
    issue, stations, current_index, status="running",
    bounce_counts=None, trace=None, classification=None, **context_extra,
):
    return {
        "issue": issue,
        "stations": stations,
        "currentIndex": current_index,
        "bounceCounts": bounce_counts or {},
        "status": status,
        "trace": trace or [],
        "context": {"repo": "/tmp/whatever", **context_extra},
        "classification": classification,
        "specialists": [],
    }


def record(led, mtime=1000.0, dir_name=None):
    if dir_name is None:
        dir_name = f"masnun-siam-ai-workflow-issue-{led['issue']}"
    return {"ledger": led, "mtime": mtime, "dir_name": dir_name}


FULL = ["researcher", "planner", "sdet", "dev", "verifier", "reviewer", "fixer"]


def card_for(board, issue):
    for column in board["columns"]:
        for card in column["cards"]:
            if card["issue"] == issue:
                return column["key"], card
    return None, None


def no_title(owner, repo, issue):
    raise AssertionError("fetch_title should not be called in this test")


# --- 1. normal progression places the card in its current station's column --

led = ledger(
    1, FULL, FULL.index("reviewer"),
    pr="https://github.com/masnun-siam/ai-workflow/pull/55",
)
board = build_board([record(led)], {}, lambda o, r, i: "A title")
col, card = card_for(board, 1)
assert col == "reviewer", col
assert card["escalated"] is False
ok("normal progression: card sits in stations[currentIndex]'s column")


# --- 2. lean-mode roster never populates sdet/verifier -----------------------

LEAN = ["researcher", "planner", "dev", "reviewer", "fixer"]
led = ledger(2, LEAN, LEAN.index("dev"))
board = build_board([record(led)], {}, lambda o, r, i: "A title")
col, card = card_for(board, 2)
assert col == "dev", col
for column in board["columns"]:
    if column["key"] in ("sdet", "verifier"):
        assert column["cards"] == [], f"{column['key']} should stay empty for a lean Run"
ok("lean mode: card lands in dev, sdet/verifier columns stay empty")


# --- 3. escalated stays in its last active station's column, badged --------

led = ledger(3, FULL, FULL.index("dev"), status="escalated")
board = build_board([record(led)], {}, lambda o, r, i: "A title")
col, card = card_for(board, 3)
assert col == "dev", col
assert card["escalated"] is True
ok("escalated: badge set, card stays in current station's column")


# --- 4. status=='done' places the card in the 'done' column ----------------

led = ledger(4, FULL, FULL.index("fixer"), status="done")
board = build_board([record(led)], {}, lambda o, r, i: "A title")
col, card = card_for(board, 4)
assert col == "done", col
assert card["escalated"] is False
ok("done status: card placed in the done column regardless of currentIndex")


# --- 5. same issue, two runs: dedup keeps the highest-mtime record ---------

older = ledger(5, FULL, FULL.index("planner"))
newer = ledger(5, FULL, FULL.index("reviewer"))
board = build_board(
    [record(older, mtime=100.0), record(newer, mtime=200.0)], {}, lambda o, r, i: "A title"
)
matches = [
    (col["key"], card) for col in board["columns"] for card in col["cards"] if card["issue"] == 5
]
assert len(matches) == 1, matches
assert matches[0][0] == "reviewer", matches
ok("dedup: only the highest-mtime run's card survives")


# --- 6. owner/repo resolution: context.pr wins when present -----------------

led = ledger(
    6, FULL, FULL.index("dev"),
    pr="https://github.com/acme/widgets/pull/9",
    plan_comment="https://github.com/wrong-owner/wrong-repo/issues/6#issuecomment-1",
)
board = build_board([record(led, dir_name="totally-unrelated-issue-6")], {}, lambda o, r, i: "t")
_, card = card_for(board, 6)
assert (card["owner"], card["repo"]) == ("acme", "widgets"), card
ok("owner/repo: context.pr URL takes priority")


# --- 7. owner/repo resolution: plan_comment used when no pr yet -------------

led = ledger(
    7, FULL, FULL.index("dev"),
    plan_comment="https://github.com/acme/widgets/issues/7#issuecomment-1",
)
board = build_board([record(led, dir_name="totally-unrelated-issue-7")], {}, lambda o, r, i: "t")
_, card = card_for(board, 7)
assert (card["owner"], card["repo"]) == ("acme", "widgets"), card
ok("owner/repo: plan_comment URL used when there's no PR yet")


# --- 8. owner/repo resolution: dir-name fallback when neither URL exists ----

led = ledger(8, FULL, FULL.index("dev"))
board = build_board(
    [record(led, dir_name="blubird-interactiveltd-bop-bd-issue-8")],
    {"blubird-interactiveltd/bop-bd": "DeshiCommerce"},
    lambda o, r, i: "t",
)
_, card = card_for(board, 8)
assert (card["owner"], card["repo"]) == ("blubird-interactiveltd", "bop-bd"), card
ok("owner/repo: dir-name fallback resolved via a known projects.json slug")


# --- 9. project name: resolved from projects.json ---------------------------

led = ledger(9, FULL, FULL.index("dev"), pr="https://github.com/blubird-interactiveltd/bop-bd/pull/1")
board = build_board([record(led)], {"blubird-interactiveltd/bop-bd": "DeshiCommerce"}, lambda o, r, i: "t")
_, card = card_for(board, 9)
assert card["project"] == "DeshiCommerce", card
ok("project name: resolved via projects.json mapping")


# --- 10. project name: falls back to the raw owner/repo slug ---------------

led = ledger(10, FULL, FULL.index("dev"), pr="https://github.com/some-owner/some-repo/pull/1")
board = build_board([record(led)], {}, lambda o, r, i: "t")
_, card = card_for(board, 10)
assert card["project"] == "some-owner/some-repo", card
ok("project name: falls back to raw owner/repo slug when unmapped")


# --- 11. card carries full popup detail: trace, PR/branch/CI, classification, bounces --

led = ledger(
    11, FULL, FULL.index("reviewer"),
    trace=["init: mode=full", "advance->planner", "advance->reviewer"],
    bounce_counts={"dev->reviewer": 1},
    classification={"ticket_type": "feature", "risk_score": 39, "risk_band": "medium", "blast_radius": "unknown"},
    pr="https://github.com/acme/widgets/pull/9",
    branch="issue-11-thing",
    base_branch="master",
    ci="green",
)
board = build_board([record(led)], {}, lambda o, r, i: "t")
_, card = card_for(board, 11)
assert card["trace"] == ["init: mode=full", "advance->planner", "advance->reviewer"], card
assert card["bounceCounts"] == {"dev->reviewer": 1}, card
assert card["classification"] == {
    "ticket_type": "feature", "risk_score": 39, "risk_band": "medium", "blast_radius": "unknown",
}, card
assert card["pr"] == "https://github.com/acme/widgets/pull/9", card
assert card["branch"] == "issue-11-thing", card
assert card["base_branch"] == "master", card
assert card["ci"] == "green", card
ok("card detail: trace/bounceCounts/classification/pr/branch/base_branch/ci all surfaced")


# --- 12. detail fields default sensibly when absent from context/classification ---

led = ledger(12, FULL, FULL.index("planner"))
board = build_board([record(led)], {}, lambda o, r, i: "t")
_, card = card_for(board, 12)
assert card["trace"] == [], card
assert card["bounceCounts"] == {}, card
assert card["classification"] is None, card
assert card["pr"] is None, card
assert card["branch"] is None, card
assert card["base_branch"] is None, card
assert card["ci"] is None, card
ok("card detail: absent context/classification fields default to empty/None, not KeyError")


# --- 13. memoize_title_fetcher: same key hits the cache, different keys don't ----

calls = []


def fake_fetch(owner, repo, issue):
    calls.append((owner, repo, issue))
    return f"title-{issue}"


cached_fetch = memoize_title_fetcher(fake_fetch)
assert cached_fetch("acme", "widgets", 1) == "title-1"
assert cached_fetch("acme", "widgets", 1) == "title-1"
assert calls == [("acme", "widgets", 1)], calls
assert cached_fetch("acme", "widgets", 2) == "title-2"
assert calls == [("acme", "widgets", 1), ("acme", "widgets", 2)], calls
ok("memoize_title_fetcher: repeat calls for the same key hit the cache, new keys don't")

# --- 13b. async mode: miss returns None at once, later call sees the title; junk repos skipped ----

import threading
from concurrent.futures import ThreadPoolExecutor

gate = threading.Event()
async_calls = []


def slow_fetch(owner, repo, issue):
    async_calls.append((owner, repo, issue))
    gate.wait(5)
    return f"slow-{issue}"


with ThreadPoolExecutor(max_workers=2) as pool:
    async_fetch = memoize_title_fetcher(slow_fetch, pool)
    assert async_fetch("acme", "widgets", 1) is None  # does not block on the slow fetch
    assert async_fetch("acme", "widgets", 1) is None  # still pending: not re-submitted
    gate.set()
    pool.shutdown(wait=True)
assert async_calls == [("acme", "widgets", 1)], async_calls
assert async_fetch("acme", "widgets", 1) == "slow-1"
ok("memoize_title_fetcher(pool): miss returns None immediately, no duplicate fetch, title appears once fetched")

junk_calls = []
junk_fetch = memoize_title_fetcher(lambda o, r, i: junk_calls.append((o, r, i)) or "t")
for owner, repo in [("masnun", "siam-ai-workflow-issue-108.lean-misinit"), ("weird", ""), ("", "x"), ("a b", "c")]:
    assert junk_fetch(owner, repo, 1) is None, (owner, repo)
assert junk_calls == [], junk_calls
assert junk_fetch("acme", "widgets", 1) == "t"
ok("memoize_title_fetcher: implausible owner/repo pairs never reach gh")


# --- 15. kanban is gone -----------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
proc = subprocess.run(
    [sys.executable, os.path.join(HERE, "route.py"), "kanban", "--help"],
    capture_output=True, text=True, timeout=30,
)
assert proc.returncode != 0, proc.returncode
assert "invalid choice: 'kanban'" in proc.stderr, proc.stderr
ok("route.py kanban --help: non-zero exit, invalid choice")

assert importlib.machinery.PathFinder.find_spec("kanban", [HERE]) is None
ok("kanban module is not importable")

for fname in ("kanban.py", "test_kanban.py"):
    assert not os.path.exists(os.path.join(HERE, fname)), fname
ok("kanban.py and test_kanban.py do not exist")

# --- 16. no runs ------------------------------------------------------------

old_env = os.environ.get("CLAUDE_PLUGIN_DATA")
try:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["CLAUDE_PLUGIN_DATA"] = tmp
        assert ui_board.scan_records() == []
        os.makedirs(os.path.join(tmp, "runs"))
        assert ui_board.scan_records() == []
finally:
    if old_env is None:
        os.environ.pop("CLAUDE_PLUGIN_DATA", None)
    else:
        os.environ["CLAUDE_PLUGIN_DATA"] = old_env
board = build_board([], {}, no_title)
assert [c["key"] for c in board["columns"]] == STATIONS
assert STATIONS == ["researcher", "planner", "sdet", "dev", "verifier", "reviewer", "fixer", "done"]
assert all(c["cards"] == [] for c in board["columns"])
ok("no runs: scan_records [] and empty board has all 8 columns")

# --- 17. run dir without run.json skipped -----------------------------------

old_env = os.environ.get("CLAUDE_PLUGIN_DATA")
try:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["CLAUDE_PLUGIN_DATA"] = tmp
        os.makedirs(os.path.join(tmp, "runs", "empty-issue-1"))
        good = os.path.join(tmp, "runs", "o-r-issue-2")
        os.makedirs(good)
        led = ledger(2, FULL, 0)
        with open(os.path.join(good, "run.json"), "w", encoding="utf-8") as fh:
            json.dump(led, fh)
        recs = ui_board.scan_records()
        assert len(recs) == 1, recs
        assert recs[0]["ledger"] == led and recs[0]["dir_name"] == "o-r-issue-2"
        assert isinstance(recs[0]["mtime"], float)
finally:
    if old_env is None:
        os.environ.pop("CLAUDE_PLUGIN_DATA", None)
    else:
        os.environ["CLAUDE_PLUGIN_DATA"] = old_env
ok("scan_records skips dirs lacking run.json")

# --- 18. load_projects: missing and valid -----------------------------------

old_path = ui_board.PROJECTS_PATH
try:
    with tempfile.TemporaryDirectory() as tmp:
        ui_board.PROJECTS_PATH = os.path.join(tmp, "nope.json")
        assert ui_board.load_projects() == {}
        p = os.path.join(tmp, "projects.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"a/b": "AB"}, fh)
        ui_board.PROJECTS_PATH = p
        assert ui_board.load_projects() == {"a/b": "AB"}
finally:
    ui_board.PROJECTS_PATH = old_path
ok("load_projects: missing file -> {}, valid file parsed")

# --- 19. unparseable dir name does not raise --------------------------------

led = ledger(20, FULL, 0)
board = build_board([record(led, dir_name="weird")], {}, lambda o, r, i: "t")
_, card = card_for(board, 20)
assert (card["owner"], card["repo"]) == ("weird", ""), card
assert card["project"] == "weird/", card
assert ui_board._guess_owner_repo_from_dir_name("weird", 20, {}) == ("weird", "")
ok("unparseable dir name: owner='weird', repo='', project='weird/'")

# --- 20. dir-name suffix for a different issue number -----------------------

led = ledger(8, FULL, 0)
board = build_board([record(led, dir_name="acme-widgets-issue-99")], {}, lambda o, r, i: "t")
_, card = card_for(board, 8)
assert (card["owner"], card["repo"]) == ("acme", "widgets-issue-99"), card
assert ui_board._guess_owner_repo_from_dir_name("acme-widgets-issue-99", 8, {}) == (
    "acme", "widgets-issue-99")
ok("mismatched issue suffix is not stripped; first-dash partition")

# --- 21. fetch_title degrades without gh ------------------------------------

old_path_env = os.environ.get("PATH")
try:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PATH"] = tmp
        assert ui_board.fetch_title("o", "r", 7) == "Issue #7 (title unavailable)"
finally:
    if old_path_env is None:
        os.environ.pop("PATH", None)
    else:
        os.environ["PATH"] = old_path_env
ok("fetch_title: missing gh -> 'Issue #7 (title unavailable)'")

# --- 22. cards carry a trimmed note and updated time; columns are newest-first ----

older = ledger(31, FULL, 3, status="escalated", blocked_on="x" * 500)
newer = ledger(32, FULL, 3)
board = build_board([record(older, mtime=10.0), record(newer, mtime=20.0)], {}, lambda o, r, i: "t")
dev = next(c for c in board["columns"] if c["key"] == "dev")
assert [c["issue"] for c in dev["cards"]] == [32, 31], dev["cards"]
_, c31 = card_for(board, 31)
_, c32 = card_for(board, 32)
assert c31["note"] == "x" * 200 and c32["note"] == "", (len(c31["note"]), c32["note"])
assert (c31["updated"], c32["updated"]) == (10.0, 20.0)
ok("cards: note trimmed to 200 chars, updated mtime, columns sorted newest first")

print(f"\n{passed} passed")
