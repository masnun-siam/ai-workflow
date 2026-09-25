#!/usr/bin/env python3
"""Self-check for scripts/kanban.py. `python3 scripts/test_kanban.py` — exit 0 = green.

Deliberately assert-based with no framework, matching run-engine/test_engine.py:
this file must run anywhere python3 does, with no install step.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kanban import STATIONS, build_board  # noqa: E402

passed = 0


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


def ledger(issue, stations, current_index, status="running", **context_extra):
    return {
        "issue": issue,
        "stations": stations,
        "currentIndex": current_index,
        "bounceCounts": {},
        "status": status,
        "trace": [],
        "context": {"repo": "/tmp/whatever", **context_extra},
        "classification": None,
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

print(f"\n{passed} passed")
