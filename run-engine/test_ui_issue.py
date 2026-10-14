#!/usr/bin/env python3
"""Self-check for run-engine/ui_issue.py. `python3 test_ui_issue.py` — exit 0 = green."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui_issue

assert ui_issue.valid("masnun-siam", "ai-workflow", "12")
assert (
    not ui_issue.valid("-x", "repo", "1")
    and not ui_issue.valid("o", "r/../x", "1")
    and not ui_issue.valid("o", "r", "1a")
)

d = ui_issue.shape(
    {
        "number": 3,
        "title": "T",
        "html_url": "u",
        "state": "closed",
        "state_reason": "not_planned",
        "user": None,
        "labels": [{"name": "bug", "color": "f00"}],
        "assignees": [{"login": "a"}],
        "milestone": {"title": "v1"},
        "body_html": '<p><a href="x">l</a></p>',
        "comments": 2,
    },
    [{"user": {"login": "bob"}, "created_at": "t", "body_html": "<p>hi</p>"}],
)
assert d["author"] == "ghost" and d["assignees"] == ["a"] and d["milestone"] == "v1" and not d["is_pr"]
assert 'target="_blank"' in d["body_html"] and d["comment_count"] == 2 and len(d["comments"]) == 1
assert ui_issue.shape({"pull_request": {}}, [])["is_pr"]
print("  ok  ui_issue")

rows = [
    {
        "number": 4,
        "title": "Old",
        "labels": [{"name": "bug"}],
        "updatedAt": "2026-01-01T00:00:00Z",
        "url": "https://g/4",
    },
    {
        "number": 9,
        "title": "PR",
        "labels": [],
        "updatedAt": "2026-02-01T00:00:00Z",
        "isDraft": True,
        "url": "javascript:x",
    },
    {"title": "no number"},
]
assert ui_issue.shape_open(rows) == [
    {
        "number": 4,
        "title": "Old",
        "labels": ["bug"],
        "updated_at": "2026-01-01T00:00:00Z",
        "draft": False,
        "url": "https://g/4",
    },
    {"number": 9, "title": "PR", "labels": [], "updated_at": "2026-02-01T00:00:00Z", "draft": True, "url": None},
]
assert ui_issue.open_items("o", "r", "nope")[0] == 400
print("ok  open issue/PR list shaping")
