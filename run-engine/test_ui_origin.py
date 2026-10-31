#!/usr/bin/env python3
"""Self-check for run-engine/ui_origin.py. `python3 test_ui_origin.py` — exit 0 = green."""

from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()

import dispatch  # noqa: E402
import ui_origin  # noqa: E402
import ui_sessions  # noqa: E402
import ui_settings  # noqa: E402

work = tempfile.mkdtemp()
checkout = os.path.join(work, "app")
os.makedirs(os.path.join(checkout, "docs", "prds"))
with open(os.path.join(checkout, "docs", "prds", "reminders.md"), "w") as f:
    f.write("# Reminders\n\n**Status:** Approved · **Slug:** `reminders`\n")

dispatch.read_checkouts = lambda: {"o/app": checkout, "o/other": work}
ui_settings.load = lambda: {
    "commands": [{"label": "main", "cmd": "claude"}, {"label": "work", "cmd": "claude-work"}],
    "default": "main",
}
ui_origin.PINNED_TTL = 0

issue = {"parent": None, "sub_issues": [], "blocked_by": [], "assignees": [], "prs": []}
epic = {**issue, "n": 6, "title": "Epic", "labels": ["epic", "prd-reminders"], "sub_issues": [7]}
child = {
    **issue,
    "n": 7,
    "title": "Child",
    "labels": ["refined", "prd-reminders"],
    "parent": 6,
    "prs": [{"n": 30, "url": "u", "state": "OPEN"}],
}
snap = {"data": {"issues": [epic, child], "merged": [{"n": 31, "closes": [8]}], "open_prs": [], "closed_epics": []}}
ui_origin.SNAPSHOT = lambda repo: snap


def session(text: str, repo: str, pin: bool, cmd: str, lines: list) -> str:
    sid = ui_sessions.create(text, repo, None, claude_cmd=cmd)["id"]
    with open(os.path.join(ui_sessions.session_dir(sid), "stream.jsonl"), "w") as f:
        f.writelines(json.dumps(x) + "\n" for x in lines)
    if pin:
        ui_sessions.update(sid, pin_account=True)
    return sid


def use(name: str, **args) -> dict:
    return {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": name, "name": args.pop("tool"), "input": args}]},
    }


def result(name: str, text: str) -> dict:
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": name, "content": text}]}}


assert ui_origin.account_for(checkout, "/create-tasks docs/prds/reminders.md") is None, "nothing pinned"
assert ui_origin.prd_label("o/app", "reminders") is None

session(
    "/create-prd reminders",
    checkout,
    False,
    "claude-work",
    [use("a", tool="Write", file_path=f"{checkout}/docs/prds/reminders.md")],
)
assert ui_origin.account_for(checkout, "/create-tasks docs/prds/reminders.md") is None, (
    "an unpinned session binds nothing"
)

prd = session(
    "/create-prd reminders",
    checkout,
    True,
    "claude-work",
    [
        use("r", tool="Read", file_path=f"{checkout}/docs/prds/older.md"),
        use("w", tool="Write", file_path=f"{checkout}/docs/prds/reminders.md"),
    ],
)
session(
    "/create-tasks Small change (no PRD): fix it",
    checkout,
    True,
    "claude-work",
    [
        use("g", tool="Bash", command="gh issue create --title x"),
        result("g", "https://github.com/o/app/issues/20"),
        result("other", "https://github.com/o/app/issues/21"),
    ],
)

for label, text, link in [
    ("PRD path, as a checkout path", f"/ai-workflow:create-prd {checkout}/docs/prds/reminders.md --update", None),
    ("the epic by link", "/create-tasks docs/x", {"issue": 6}),
    ("a child by link", "/implement-issue 7", {"owner": "o", "repo": "app", "issue": 7}),
    ("children in the arguments", "/ai-workflow:refine-issues 7 9", None),
    ("a dispatch lane prompt", "/ai-workflow:implement-issue 7 (base main)", None),
    ("the child's PR by URL", "/pr-grind https://github.com/o/app/pull/30", None),
    ("the small change's issue", "/implement-issue 20", None),
]:
    assert ui_origin.account_for("o/app", text, link) == "claude-work", label
    print(f"  ok  {label}")

assert ui_origin.account_for("o/app", "/implement-issue 21") is None, "only the issue that session filed"
assert ui_origin.account_for("o/app", "/create-tasks docs/prds/older.md") is None, "a PRD it only read"
assert ui_origin.account_for("o/other", "/implement-issue 20") is None, "another repo's numbers are not this one's"
assert ui_origin.account_for("o/app", "Review docs for 2026 changes") is None, "free text is not an issue list"
assert ui_origin.prd_label("o/app", "reminders") == "work"

ui_settings.load = lambda: {"commands": [{"label": "main", "cmd": "claude"}], "default": "main"}
assert ui_origin.account_for("o/app", "/implement-issue 7") is None, "an account gone from Settings falls back"
assert prd
print("  ok  everything else")
