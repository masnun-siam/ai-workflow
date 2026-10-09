#!/usr/bin/env python3
"""Self-check for run-engine/ui_flows.py. `python3 test_ui_flows.py` — exit 0 = green."""

from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

d = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = d

import ui_flows  # noqa: E402
import ui_sessions  # noqa: E402
import ui_settings  # noqa: E402


def raises(exc, fn, *a):
    try:
        fn(*a)
    except exc:
        return True
    return False


def session(command, result_text, status="done"):
    rec = ui_sessions.create(command, "o/r")
    with open(os.path.join(ui_sessions.session_dir(rec["id"]), "stream.jsonl"), "w") as f:
        f.write(json.dumps({"type": "result", "result": result_text}) + "\n")
    ui_sessions.update(rec["id"], status=status, ended_at="2026-10-09T15:00:00+00:00")
    return rec["id"]


# ---- one-time import: dump -> prd -> gh-issue sessions chain into one flow
s_dump = session("/dump export bookings as csv", "Filed.\n→ next: /ai-workflow:prd 05-Work/P/Bookings Export")
s_prd = session("/prd 05-Work/P/Bookings Export", "PRD written.\n`→ next: /gh-issue 05-Work/P/Bookings Export/PRD.md`")
s_iss = session("/gh-issue 05-Work/P/Bookings Export/PRD.md", "Created.\n→ next: herdr-dispatch 41 42")
s_other = session("/prd something else", "→ next: /gh-issue x.md")
flows = ui_flows.list_all()
assert len(flows) == 1, flows
f = flows[0]
assert (f["folder"], f["prd"], f["issues"]) == ("05-Work/P/Bookings Export", "05-Work/P/Bookings Export/PRD.md", [41, 42]), f
assert f["sessions"] == [s_dump, s_prd, s_iss], f["sessions"]
assert ui_sessions.load(s_prd)["flow_id"] == f["id"] and "flow_id" not in ui_sessions.load(s_other)
assert ui_flows.summary(f)["name"] == "Bookings Export" and ui_flows.summary(f)["step"] == "dispatch"
assert f["updated"] == 1791558000.0  # the last session's ended_at, in UTC
session("/dump later idea", "→ next: /prd 05-Work/P/Later")
assert len(ui_flows.list_all()) == 1  # import runs once
print("ok import chains dump/prd/gh-issue sessions once")

# ---- create / update / archive; empty never-run flows hidden then pruned
g = ui_flows.create({"repo": "o/r", "text": "  "})
assert all(x["id"] != g["id"] for x in ui_flows.list_all())  # empty: hidden
g = ui_flows.update(g["id"], {"text": "A new idea about exports"})
assert ui_flows.list_all()[0]["id"] == g["id"] and ui_flows.summary(g)["name"] == "A new idea about exports"
sid = session("/dump A new idea about exports", "")
g = ui_flows.update(g["id"], {"sid": sid})
assert g["sessions"] == [sid] and ui_sessions.load(sid)["flow_id"] == g["id"]
assert raises(ValueError, ui_flows.update, g["id"], {"issues": ["7"]})
assert raises(ValueError, ui_flows.update, g["id"], {"text": 5})
assert raises(ValueError, ui_flows.update, g["id"], {"sid": "../x"})
assert raises(ui_flows.NotFound, ui_flows.update, "f-00000000000000-000000", {})
assert raises(ui_flows.NotFound, ui_flows.update, "../etc", {})
ui_flows.set_archived(g["id"], True)
assert all(x["id"] != g["id"] for x in ui_flows.list_all())
assert any(x["id"] == g["id"] for x in ui_flows.list_all(include_archived=True))
e = ui_flows.create({})
assert os.path.exists(ui_flows._path(e["id"]))
ui_flows.list_all(now=e["updated"] + ui_flows.EMPTY_TTL + 1)
assert not os.path.exists(ui_flows._path(e["id"]))
t0 = ui_flows.load(g["id"])["updated"]
assert ui_flows.update(g["id"], {"repo": "/abs/path", "text": g["text"]})["updated"] == t0  # same work, new repo spelling
print("ok create, update, archive, prune empty")

# ---- issue progress from raw stream lines


def use(i, name, inp):
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": i, "name": name, "input": inp}]}})


def res(i, text, err=False):
    return json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": i, "content": [{"type": "text", "text": text}], "is_error": err}]}})


lines = [
    use("a", "Bash", {"command": 'gh issue create --title "Tool runtime permissions" --label refined --body-file /tmp/b.md'}),
]
p = ui_flows.issue_progress(lines)
assert p["reading"] is False and p["rows"] == [{"number": None, "title": "Tool runtime permissions", "state": "creating"}]
lines += [
    res("a", "https://github.com/o/r/issues/214\n"),
    use("b", "Bash", {"command": "gh issue create --title 'Rate limits' --body-file x"}),
    res("b", "https://github.com/o/r/issues/215"),
    use("c", "Agent", {"subagent_type": "ai-workflow:gh-issue-factchecker", "prompt": "Check https://github.com/o/r/issues/214"}),
    res("c", "PASS"),
    use("d", "Agent", {"subagent_type": "ai-workflow:gh-issue-factchecker", "prompt": "Check issue #215"}),
    res("d", "ISSUES FOUND: wrong path"),
]
p = ui_flows.issue_progress(lines)
assert [(r["number"], r["state"]) for r in p["rows"]] == [(214, "checked"), (215, "fixing")], p
lines += [use("e", "Bash", {"command": "gh issue edit 215 --body-file /tmp/b.md"}), res("e", "https://github.com/o/r/issues/215")]
assert [r["state"] for r in ui_flows.issue_progress(lines)["rows"]] == ["checked", "fixed"]
assert ui_flows.issue_progress([use("x", "Bash", {"command": 'gh issue create --title "X"'}), res("x", "error", True)])["rows"][0]["state"] == "failed"
assert ui_flows.issue_progress([])["reading"] is True
print("ok issue progress: creating, created, checking, checked, fixing, fixed, failed")

# ---- notes: read-only, confined to the vault
vault = os.path.join(d, "notes")
os.makedirs(os.path.join(vault, "05-Work", "P"))
with open(os.path.join(vault, "05-Work", "P", "Dump.md"), "w") as fh:
    fh.write("# Dump\nhello")
with open(os.path.join(d, "secret.md"), "w") as fh:
    fh.write("nope")
ui_settings.save({"commands": [], "vault_dir": vault})
n = ui_flows.read_note("05-Work/P/Dump.md")
assert n["text"].startswith("# Dump") and n["url"] == "obsidian://open?vault=notes&file=05-Work/P/Dump"
assert ui_flows.read_note("05-Work/P/Dump")["path"] == "05-Work/P/Dump.md"
assert raises(ValueError, ui_flows.read_note, "../secret.md")
assert raises(ValueError, ui_flows.read_note, os.path.join(d, "secret.md"))
assert raises(ValueError, ui_flows.read_note, "05-Work/P/x.txt")
assert raises(ui_flows.NotFound, ui_flows.read_note, "05-Work/P/Missing.md")
os.symlink(os.path.join(d, "secret.md"), os.path.join(vault, "link.md"))
assert raises(ValueError, ui_flows.read_note, "link.md")
print("ok notes read-only inside the vault; traversal, absolute paths, symlinks out and non-md refused")

# ---- sessions started from a flow get the Flow auto mode line; others don't
import ui_runner  # noqa: E402
assert "Flow auto mode" in ui_runner._system({"flow_id": "f-1"}) and ui_runner.HEADLESS_PROMPT in ui_runner._system({"flow_id": "f-1"})
assert ui_runner._system({}) == ui_runner._system(None) == ui_runner.HEADLESS_PROMPT
print("ok Flow auto mode prompt only for flow sessions")

# ---- a create loop: one command, a shell-variable title, several URLs -> one row per issue
loop = [use("L", "Bash", {"command": 'for k in 0 1 2; do gh issue create --title "${titles[$k]}" --body-file b$k; done'}),
        res("L", "https://github.com/o/r/issues/64\nhttps://github.com/o/r/issues/65\nhttps://github.com/o/r/issues/66\n")]
rows = ui_flows.issue_progress(loop)["rows"]
assert [(r["number"], r["title"], r["state"]) for r in rows] == [(64, "", "created"), (65, "", "created"), (66, "", "created")], rows
print("ok a create loop gives one row per issue, titles left for the UI to look up")

# ---- one factcheck over several issues, per-issue verdicts; background factcheck; edit that landed despite a failing shell
base = [use("c", "Bash", {"command": 'gh issue create --title "A"'}),
        res("c", "https://github.com/o/r/issues/7\nhttps://github.com/o/r/issues/8\n")]
multi = base + [use("f", "Agent", {"prompt": "factcheck #7 and #8"}), res("f", "#7: PASS\n#8: ISSUES FOUND, wrong file")]
assert [r["state"] for r in ui_flows.issue_progress(multi)["rows"]] == ["checked", "fixing"]
bg = base + [use("f", "Agent", {"prompt": "factcheck #7"}), res("f", "Async agent launched successfully. agentId: x")]
assert [r["state"] for r in ui_flows.issue_progress(bg)["rows"]] == ["checking", "created"]
landed = multi + [use("e", "Bash", {"command": "gh issue edit 8 --body-file b; rm -r /tmp/x"}), res("e", "Exit code 1\nhttps://github.com/o/r/issues/8\nblocked", True)]
assert [r["state"] for r in ui_flows.issue_progress(landed)["rows"]] == ["checked", "fixed"]
print("ok multi-issue factcheck verdicts, background factcheck, edit that landed despite a shell error")
