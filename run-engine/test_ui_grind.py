#!/usr/bin/env python3
"""Self-check for run-engine/ui_grind.py. `python3 test_ui_grind.py` — exit 0 = green."""

from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
d = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = d

import ui_board  # noqa: E402
import ui_grind  # noqa: E402
import ui_notify  # noqa: E402
import ui_repos  # noqa: E402
import ui_runner  # noqa: E402
import ui_sessions  # noqa: E402

PR = "https://github.com/o/r/pull/7"
RUNS = {7: {"status": "done", "pr": PR}, 8: {"status": "running", "pr": None}, 9: {"status": "done", "pr": "https://github.com/o/r/pull/9"}}
ui_board.load_run = lambda o, r, n, runs_dir=None: RUNS.get(int(n))
ui_repos.resolve_repo = lambda slug: (d, slug)
started, sent = [], []


def fake_start(text, cwd, link=None, **kw):
    started.append((text, link))
    rec = ui_sessions.create(text, cwd, link)
    return ui_sessions.update(rec["id"], status="running", pid=os.getpgrp())


ui_runner.start = fake_start
ui_runner.grind_live = lambda: len([s for s in started if s]) - freed[0]
ui_notify.notify = lambda event, rec: sent.append((event, rec))
freed = [0]


def state_file(n, **kv):
    os.makedirs(os.path.join(d, "pr-grind"), exist_ok=True)
    h = {"owner": "o", "repo": "r", "number": str(n), "thread": f"https://x.slack.com/archives/C1/p{n}"}
    h.update(kv)
    path = os.path.join(d, "pr-grind", f"o-r-{n}.md")
    with open(path, "w") as f:
        f.write("".join(f"{k}: {v}\n" for k, v in h.items()) + "\n## Round 1\n## Round 2\n")
    return path


# not finished / no PR -> refused, nothing queued
assert ui_grind.request("o", "r", 8)[0] == 409
assert ui_grind.request("o", "r", 404)[0] == 409 and not started
# start: spawned once, link carried, never twice
st, body = ui_grind.request("o", "r", 7)
assert st == 201 or st == 202, (st, body)
assert len(started) == 1 and started[0][1] == {"owner": "o", "repo": "r", "issue": 7} and PR in started[0][0]
assert started[0][0].startswith(ui_runner.GRIND_PREFIX)
idx = ui_grind.index()
assert ui_grind.for_card(idx, "o", "r", 7, PR)["state"] == "running"  # first-grind session, no state file yet
assert ui_grind.request("o", "r", 7)[0] == 409
# state files: round count + states
path = state_file(7)
g = ui_grind.for_card(ui_grind.index(), "O", "R", 7, PR)
assert g == {"state": "idle", "round": 2}, g
code, _ = ui_grind.control("o", "r", 7, "pause")
assert code == 200 and ui_grind.for_card(ui_grind.index(), "o", "r", 7, PR)["state"] == "paused"
code, _ = ui_grind.control("o", "r", 7, "resume")
h = ui_runner._header(path)
assert code == 200 and "paused" not in h and "next-poll" in h
state_file(7, done="2026-10-08T00:00:00Z — merged")
assert ui_grind.for_card(ui_grind.index(), "o", "r", 7, PR)["state"] == "done"
assert ui_grind.control("o", "r", 7, "pause")[0] == 409 and ui_grind.control("o", "r", 9, "pause")[0] == 404
# cap: the third grind waits, then starts once a slot frees
RUNS[10] = {"status": "done", "pr": "https://github.com/o/r/pull/10"}
RUNS[11] = {"status": "done", "pr": "https://github.com/o/r/pull/11"}
n0 = len(started)
assert ui_grind.request("o", "r", 9)[0] in (201, 202)
code, body = ui_grind.request("o", "r", 10)
assert code == 202 and body["state"] == "queued" and len(started) == n0 + 1 or ui_runner.MAX_GRINDS > 2
freed[0] += 1
ui_grind.drain()
assert len(started) == n0 + 2 and ui_grind.for_card(ui_grind.index(), "o", "r", 10, RUNS[10]["pr"])["state"] == "running"
# autostart queues only finished runs that asked, once
rec = ui_sessions.create("/run-issue 11", d, {"owner": "o", "repo": "r", "issue": 11})
ui_sessions.update(rec["id"], status="done", auto_grind=True)
freed[0] += 5
ui_grind.autostart()
assert ui_sessions.load(rec["id"]).get("auto_grind") is False
ui_grind.drain()
assert any(l and l["issue"] == 11 for _, l in started)
# notifications: first scan records history silently, later changes push once
sent.clear()
ui_grind.notify_changes()
assert not sent
state_file(21, paused="2026-10-08T01:00:00Z — rail")
ui_grind.notify_changes()
ui_grind.notify_changes()
assert [e for e, _ in sent] == ["grind-paused"], sent
h, body = ui_notify.compose("grind-paused", sent[0][1])
assert "paused" in h["Title"] and "rail" in body
assert ui_notify.compose("grind-done", {"link": {"issue": 3}})[0]["Title"].startswith("aiw: #3 grind")
print("ui_grind: all checks passed")

# replay after a UI restart: an answered `aiw ask` earlier in the stream must not fail the finished session
import json  # noqa: E402


def replay(events):
    rec = ui_sessions.create("/run-issue 1", d)
    with open(os.path.join(ui_sessions.session_dir(rec["id"]), "stream.jsonl"), "w") as f:
        f.write("".join(json.dumps(e) + "\n" for e in events))
    ui_sessions.update(rec["id"], status="running", pid=999999)  # no such process, re-attached path
    ui_runner._follow(rec["id"], None, 999999, None)
    return ui_sessions.load(rec["id"])["status"]


init = {"type": "system", "subtype": "init", "session_id": "s"}
ask = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "aiw ask <<'EOF'\n{}\nEOF"}}]}}
res = {"type": "result", "is_error": False, "total_cost_usd": 1}
assert replay([init, ask, res, init, res]) == "done"  # ask answered, run resumed and finished
assert replay([init, ask, res]) == "failed"  # ask with nothing recorded still fails
print("ui_runner replay: asked resets per claude process")

# a grind round's link names the run's issue (matched on the ledger's PR), so it lists in that run's Sessions tab
import json as _json  # noqa: E402

os.makedirs(os.path.join(d, "runs", "o-r-7"))
with open(os.path.join(d, "runs", "o-r-7", "run.json"), "w") as f:
    _json.dump({"issue": 7, "context": {"pr": PR}}, f)
assert ui_board.issue_for_pr(PR) == 7 and ui_board.issue_for_pr(PR.upper()) == 7
assert ui_board.issue_for_pr("https://github.com/o/r/pull/99") is None and ui_board.issue_for_pr(None) is None
print("ui_board.issue_for_pr ok")

# custom prompt: queued while running, sent when finished, refused while a question is pending
import shared  # noqa: E402

sent_prompts = []
ui_runner.resume = lambda sid, text: sent_prompts.append((sid, text))
rec = ui_sessions.create("/run-issue 31", d, {"owner": "o", "repo": "r", "issue": 31})
sid = rec["id"]
ui_sessions.update(sid, status="running", pid=os.getpgrp(), session_id="claude-1")
assert ui_runner.send_prompt(sid, "  skip the migration  ") == "queued" and ui_sessions.load(sid)["queued_prompt"] == "skip the migration"
ui_runner._deliver_queued(sid)  # still running: nothing goes out
assert not sent_prompts
ui_sessions.update(sid, status="done")
ui_runner._deliver_queued(sid)
assert sent_prompts == [(sid, "skip the migration")] and ui_sessions.load(sid)["queued_prompt"] is None
ui_sessions.update(sid, status="done")  # the mocked resume leaves the claim in place
assert ui_runner.send_prompt(sid, "and run the tests") == "sent" and sent_prompts[-1] == (sid, "and run the tests")
ui_sessions.update(sid, status="waiting")
for bad, exc in (("x", ui_runner.Conflict),):
    try:
        ui_runner.send_prompt(sid, bad)
        raise SystemExit("waiting session accepted a prompt")
    except exc:
        pass
for bad in ("", "  ", "-rf", "a\x00b", "z" * 4001):
    try:
        ui_runner.send_prompt(sid, bad)
        raise SystemExit(f"accepted {bad[:10]!r}")
    except ValueError:
        pass
print("ui_runner.send_prompt ok")

# rerun CI: only a finished, failed run at the head commit is rerun
calls = []
gh = {"head": {"headRefOid": "abc"}, "runs": [{"databaseId": 5, "status": "completed", "conclusion": "failure"}]}


def fake_gh_json(args, cwd=None, timeout=120):
    return (gh["head"] if args[0] == "pr" else gh["runs"]), None


class P:
    returncode, stdout, stderr = 0, "", ""


shared.gh_json = fake_gh_json
shared.run = lambda cmd, **kw: calls.append(cmd) or P()
assert ui_grind.rerun_ci("o", "r", 7) == (200, {"run": 5}) and calls[-1][:4] == ["gh", "run", "rerun", "5"]
gh["runs"] = [{"databaseId": 6, "status": "in_progress", "conclusion": None}]
assert ui_grind.rerun_ci("o", "r", 7)[0] == 409
gh["runs"] = [{"databaseId": 7, "status": "completed", "conclusion": "success"}]
assert ui_grind.rerun_ci("o", "r", 7)[0] == 409 and ui_grind.rerun_ci("o", "r", 8)[0] == 404
print("ui_grind.rerun_ci ok")

# `done:` written under the last round (not in the header) still ends the loop
path = state_file(30)
with open(path, "a") as f:
    f.write("done: 2026-10-08T12:23:35Z — approved (round 4 clean)\n")
assert ui_grind.for_card(ui_grind.index(), "o", "r", 30, "https://github.com/o/r/pull/30")["state"] == "done"
path = state_file(31)
with open(path, "a") as f:
    f.write("note: done: not a terminal line\nthe fix is done: soon\n")
assert ui_grind.for_card(ui_grind.index(), "o", "r", 31, "https://github.com/o/r/pull/31")["state"] == "idle"
print("body-level done ok")

# replying to a paused grind: resumes the newest /pr-grind session with the decision, then clears the pause
RUNS[12] = {"status": "done", "pr": "https://github.com/o/r/pull/12"}
path12 = state_file(12, paused="2026-10-08T14:00:00Z — critical finding needs a release call")
thread12 = ui_runner._header(path12)["thread"]
g = ui_sessions.create(f"/pr-grind {thread12}", d, {"owner": "o", "repo": "r", "issue": 12})
ui_sessions.update(g["id"], status="done", session_id="claude-g")
with open(os.path.join(ui_sessions.session_dir(g["id"]), "stream.jsonl"), "w") as f:
    f.write(json.dumps({"type": "result", "result": "Paused: pick (a) or (b)"}) + "\n")
assert ui_grind.last_message("o", "r", 12) == "Paused: pick (a) or (b)"
assert ui_grind.for_card(ui_grind.index(), "o", "r", 12, RUNS[12]["pr"])["reason"].endswith("release call")
assert ui_grind.reply("o", "r", 12, "  ")[0] == 400 and "paused" in ui_runner._header(path12)
n_sent = len(sent_prompts)
assert ui_grind.reply("o", "r", 12, "go with (a)") == (200, {"state": "running"})
assert sent_prompts[n_sent][0] == g["id"] and "go with (a)" in sent_prompts[n_sent][1]
assert "paused" not in ui_runner._header(path12)
assert ui_grind.reply("o", "r", 12, "again")[0] == 409  # no longer paused
print("ui_grind.reply ok")

# a pipeline (or session) made before auto_grind existed follows the Settings default; an explicit false wins
import ui_dispatch  # noqa: E402
import ui_settings  # noqa: E402

ui_settings.save({"commands": [], "default": None, "auto_grind": True})
RUNS[40] = {"status": "done", "pr": "https://github.com/o/r/pull/40"}
RUNS[41] = {"status": "done", "pr": "https://github.com/o/r/pull/41"}
RUNS[42] = {"status": "done", "pr": "https://github.com/o/r/pull/42"}
legacy = {"id": "p-20260101000000-aaaaaa", "name": "n", "slug": "o/r", "repo_path": d, "mode": "parallel", "max": 2,
          "status": "active", "created": 1.0, "notified": False,
          "items": [{"issue": 40, "state": "done"}, {"issue": 41, "state": "queued"}]}
explicit = {**legacy, "id": "p-20260101000001-bbbbbb", "auto_grind": False, "items": [{"issue": 42, "state": "done"}]}
ui_dispatch.save(legacy)
ui_dispatch.save(explicit)
assert ui_dispatch.wants_grind() == {"o/r#40", "o/r#41"}, ui_dispatch.wants_grind()
for n in (40, 42, 43):
    r = ui_sessions.create(f"/run-issue {n}", d, {"owner": "o", "repo": "r", "issue": n})
    ui_sessions.update(r["id"], status="done")
RUNS[43] = {"status": "done", "pr": "https://github.com/o/r/pull/43"}
freed[0] += 20
ui_grind.autostart()
queued = {q["issue"] for q in _json.load(open(os.path.join(d, "grind_requests.json")))}
assert queued == {40}, queued  # 42's pipeline said no, 43 is in no pipeline
print("legacy pipeline inherits the default ok")
