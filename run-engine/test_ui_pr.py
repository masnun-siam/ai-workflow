#!/usr/bin/env python3
"""Self-check for run-engine/ui_pr.py. `python3 test_ui_pr.py` — exit 0 = green."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui_pr

d = ui_pr.shape(
    {"number": 9, "title": "T", "html_url": "u", "state": "closed", "merged": True, "user": {"login": "a"},
     "head": {"ref": "feat"}, "base": {"ref": "main"}, "body_html": "<p>x</p>", "additions": 3, "deletions": 1,
     "changed_files": 3, "commits": 1},
    [{"filename": "a.py", "status": "modified", "additions": 3, "deletions": 1, "patch": "@@ -1 +1 @@\n-a\n+b"},
     {"filename": "big", "status": "added", "patch": "x" * (ui_pr.MAX_PATCH + 1)},
     {"filename": "img.png", "status": "added"}],
    [{"sha": "abcdef123", "commit": {"message": "subject\n\nbody", "author": {"name": "N", "date": "t"}}, "author": None}],
    [{"user": {"login": "c"}, "created_at": "2026-01-02", "body_html": "<p>c</p>"}],
    [{"user": {"login": "r"}, "state": "APPROVED", "submitted_at": "2026-01-01", "body_html": ""},
     {"user": {"login": "r"}, "state": "COMMENTED", "submitted_at": "2026-01-03", "body_html": ""},
     {"user": {"login": "r"}, "state": "PENDING", "submitted_at": "2026-01-04", "body_html": "x"}],
    {"statusCheckRollup": [{"name": "ci", "detailsUrl": "l", "status": "COMPLETED", "conclusion": "FAILURE"}]},
)
assert d["state"] == "merged" and d["head"] == "feat" and d["commits"][0] == {"sha": "abcdef1", "subject": "subject", "author": "N", "at": "t"}
assert [f["patch"] is None for f in d["files"]] == [False, True, True] and d["files"][1]["patch_cut"] and not d["files"][2]["patch_cut"]
assert [(c["kind"], c["author"]) for c in d["conversation"]] == [("review", "r"), ("comment", "c")]  # empty COMMENTED + PENDING dropped
assert d["checks"] == [{"name": "ci", "link": "l", "bucket": "red"}]
assert ui_pr.shape({"state": "open", "draft": True}, [], [], [], [], None)["state"] == "draft"
print("  ok  ui_pr")
