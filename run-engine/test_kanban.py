#!/usr/bin/env python3
"""Self-check for run-engine/kanban.py. `python3 test_kanban.py` — exit 0 = green.

Deliberately assert-based with no framework, matching run-engine/test_engine.py:
this file must run anywhere python3 does, with no install step.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kanban import STATIONS, build_board, memoize_title_fetcher  # noqa: E402

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

print(f"\n{passed} passed")
