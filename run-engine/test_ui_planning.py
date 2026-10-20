#!/usr/bin/env python3
"""Self-check for run-engine/ui_planning.py. `python3 test_ui_planning.py` — exit 0 = green."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()
import peer_review  # noqa: E402
import ui_planning  # noqa: E402

co = tempfile.mkdtemp()
os.makedirs(os.path.join(co, "docs", "prds"))


def prd(slug, status, title="Thing"):
    with open(os.path.join(co, "docs", "prds", f"{slug}.md"), "w") as f:
        f.write(
            f"# PRD — {title}\n\n**Status:** {status} · **Date:** 2026-10-20 · **Slug:** `{slug}` · **Owner:** me\n"
        )


def issue(n, labels=(), parent=None, subs=()):
    return {
        "n": n,
        "title": f"i{n}",
        "state": "OPEN",
        "labels": list(labels),
        "priority": None,
        "parent": parent,
        "sub_issues": list(subs),
        "blocked_by": [],
        "prs": [],
    }


snap = {
    "stale": False,
    "fetched_at": 5.0,
    "data": {
        "issues": [issue(100, ["epic", "prd-appr"], subs=range(1, 9))]
        + [issue(n, ["refined"] if n <= 3 else [], parent=100) for n in range(1, 9)]
        + [issue(200, ["epic", "prd-done"], subs=[20])]
        + [issue(20, ["refined", "prd-done"], parent=200)],
        "merged": [],
        "open_prs": [{"n": 7, "title": "PRD: rev", "url": "u7", "draft": False, "head": "prd-rev", "ci": "none"}],
    },
}

assert ui_planning.build("o/r", co, snap, {})["prds"] == []  # no PRDs

prd("drft", "Draft", "A draft")
prd("rev", "In review")
prd("appr", "Approved")
prd("done", "Approved")
prd("fresh", "Approved")
panel = peer_review.new_panel("o/r", os.path.join(co, "docs", "prds", "drft.md"), ["critical", "cto", "qa"], None)
r = ui_planning.build("o/r", co, snap, {"drft": panel})
by = {p["slug"]: p for p in r["prds"]}
assert r["repo"] == "o/r" and not r["stale"] and r["fetched_at"] == 5.0
assert (
    by["drft"]["column"] == "draft" and by["drft"]["title"] == "A draft" and by["drft"]["path"] == "docs/prds/drft.md"
)
assert by["drft"]["panel"]["id"] == panel and by["drft"]["panel"]["root_session"] is None
assert os.path.isabs(by["drft"]["abs_path"]) and by["drft"]["abs_path"].endswith("docs/prds/drft.md")
assert by["drft"]["panel"]["approved"] == 0 and by["drft"]["panel"]["total"] == 3
assert (by["drft"]["panel"]["round"], by["drft"]["panel"]["state"]) == (1, "running")
assert by["rev"]["column"] == "in_review" and by["rev"]["pr"] == {"n": 7, "url": "u7"}
assert by["appr"]["column"] == "tasks_filed" and (by["appr"]["issues"], by["appr"]["refined"], by["appr"]["epic"]) == (
    8,
    3,
    100,
)
assert by["done"]["column"] == "refined"
assert by["fresh"]["column"] == "approved" and by["fresh"]["epic"] is None and by["fresh"]["panel"] is None

os.remove(os.path.join(co, "docs", "prds", "drft.md"))  # deleted draft: card gone next build
assert "drft" not in {p["slug"] for p in ui_planning.build("o/r", co, snap, {})["prds"]}
print("ok")
