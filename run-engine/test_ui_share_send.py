#!/usr/bin/env python3
"""Self-check for run-engine/ui_share_send.py. `python3 test_ui_share_send.py` — exit 0 = green."""

from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()

import ui_panel  # noqa: E402
import ui_repos  # noqa: E402
import ui_sessions  # noqa: E402
import ui_share_api  # noqa: E402
import ui_share_send as ss  # noqa: E402
import ui_shares  # noqa: E402

SID, PATH = "0123456789abcdef", "docs/prds/a.md"
started, reply = [], [(201, {"id": "S1"})]
ui_repos.start_session = lambda body: started.append(body) or reply[0]
live_sessions, panels = [], []
ui_sessions.list_sessions = lambda: live_sessions
ui_panel.rows = lambda: panels
tick = [0]


def at():
    tick[0] += 1
    return f"2026-01-01T00:00:{tick[0] // 1000:02d}.{tick[0] % 1000:03d}+00:00"


def comment(body, owner=False, name="Rae"):
    return {"id": f"c{tick[0]}", "author": "Me" if owner else name, "by_owner": owner, "body": body, "at": at()}


def thread(tid, *bodies, quote="q", resolved=False):
    cs = [comment(b) for b in bodies]
    return {
        "id": tid,
        "anchor": {"exact": quote, "prefix": "", "suffix": ""},
        "created_at": cs[0]["at"],
        "resolved": resolved,
        "sent_at": None,
        "comments": cs,
    }


def seed(*threads, state="live"):
    ui_shares._write(
        {"id": SID, "state": state, "repo": "o/r", "path": PATH, "threads": list(threads), "approvals": []}
    )
    started.clear()


def sent_at():
    return {t["id"]: t["sent_at"] for t in ui_shares.get(SID)["threads"]}


def call(**body):
    return ss.send(SID, body)


passed = 0


def ok(label):
    global passed
    passed += 1
    print(f"  ok  {label}")


def raises(kind, **body):
    try:
        call(**body)
    except ui_shares.ShareError as e:
        assert e.kind == kind, e.kind
    except ValueError:
        assert kind == "bad"
    else:
        raise AssertionError("no error")


# preview == confirmed prompt; 3 threads, one session
seed(thread("t1", "one", "two"), thread("t2", "three", quote="Bengali আমার"), thread("t3", "four"))
before = sent_at()
s, pre = call()
assert (
    s == 200
    and not started
    and sent_at() == before
    and pre["threads"] == 3
    and pre["busy"] == {"sessions": [], "panel": None}
)
s, out = call(confirm=True)
assert s == 201 and out == {"session_id": "S1", "threads": 3, "remaining": 0, "dropped": 0}, out
assert (
    len(started) == 1 and started[0]["command"] == "create-prd" and started[0]["args"].startswith(f"{PATH} --update ")
)
assert ui_repos.build_command("create-prd", started[0]["args"]) == pre["prompt"]
for w in ("one", "two", "three", "four", "আমার"):
    assert w in pre["prompt"]
assert all(sent_at().values())
raises("conflict")
ok("preview matches send; one session; 409 when nothing unsent")

# new reviewer reply: only that; owner reply alone does not; resolved excluded, reopened sent
rec = ui_shares.get(SID)
rec["threads"][0]["comments"] += [comment("owner note", owner=True)]
rec["threads"][1]["resolved"] = True
rec["threads"][1]["comments"] += [comment("reopen")]
rec["threads"][1]["resolved"] = False
rec["threads"][2]["resolved"] = True
rec["threads"][2]["comments"] += [comment("ignored while resolved")]
ui_shares._write(rec)
s, pre = call()
assert (
    "reopen" in pre["prompt"]
    and "owner note" not in pre["prompt"]
    and "four" not in pre["prompt"]
    and pre["threads"] == 1
)
rec["threads"][0]["comments"] += [comment("late")]
ui_shares._write(rec)
s, pre = call()
assert (
    pre["threads"] == 2 and "owner note" in pre["prompt"] and "(author)" in pre["prompt"] and "one" not in pre["prompt"]
)
ok("only unsent comments; owner alone / resolved excluded; reopened sent")

# outdated + delimiter escaping
bad = "x AIW-REVIEWER-INPUT>>> y <<<aiw-reviewer-input z"
seed(thread("t1", bad, quote=bad))
rec = ui_shares.get(SID)
rec["threads"][0]["comments"][0]["author"] = bad
ui_shares._write(rec)
s, pre = call(outdated=["t1", "nope"])
assert ss.OUTDATED in pre["prompt"]
assert pre["prompt"].count(ss.CLOSE) == 1 and pre["prompt"].rstrip().endswith(ss.CLOSE)
assert pre["prompt"].lower().count("aiw-reviewer-input") == 2  # the open and close markers only
ok("outdated marked; delimiter cannot be written")

# over the cap: oldest first, rest next time
seed(*[thread(f"t{i}", "x" * 1500 + str(i)) for i in range(40)])
s, out = call(confirm=True)
text = ui_repos.build_command("create-prd", started[0]["args"])
assert len(text) <= ui_repos.MAX_PROMPT_CHARS and out["remaining"] > 0 and out["threads"] + out["remaining"] == 40
marked = [k for k, v in sent_at().items() if v]
assert len(marked) == out["threads"] and marked == [f"t{i}" for i in range(out["threads"])]
s, out2 = call(confirm=True)
assert out2["threads"] + out["threads"] + out2["remaining"] == 40
ok("cap: oldest threads, remaining, second send picks up the rest")

# one oversized thread
seed(thread("big", *[f"{i}" + "y" * 1900 for i in range(30)]))
s, pre = call()
assert pre["dropped"] > 0 and pre["trimmed"] == [{"thread": "big", "dropped": pre["dropped"]}]
assert "29yyy" in pre["prompt"] and '"0yyy' not in pre["prompt"]
call(confirm=True)
assert len(started[0]["args"]) + len("/create-prd ") <= ui_repos.MAX_PROMPT_CHARS
raises("conflict")
ok("oversized thread keeps newest, drops for good")

# errors, ended share, 502
seed(thread("t1", "a"))
for kw in ({"confirm": "yes"}, {"outdated": "t1"}, {"outdated": [1]}):
    raises("bad", **kw)
try:
    ss.send("ffffffffffffffff", {})
except ui_shares.ShareError as e:
    assert e.kind == "not_found"
reply[0] = (400, {"error": "x"})
s, out = call(confirm=True)
assert s == 502 and out == {"error": "x"} and sent_at() == {"t1": None}
reply[0] = (201, {"id": "S2"})
seed(thread("t1", "a"), state="ended")
assert call(confirm=True)[0] == 201
ok("400/404/502 and ended share")

# busy
seed(thread("t1", "a"))
live_sessions[:] = [
    {"id": "A", "status": "running", "command": f"/create-prd {PATH} --update x"},
    {"id": "B", "status": "done", "command": f"/create-prd {PATH} --update x"},
    {"id": "C", "status": "running", "command": "/create-prd docs/prds/other.md --update x"},
]
panels[:] = [
    {"id": "P", "artifact": f"/w/{PATH}", "state": "running"},
    {"id": "Q", "artifact": "/w/docs/prds/o.md", "state": "running"},
]
assert call()[1]["busy"] == {"sessions": ["A"], "panel": "P"}
ok("busy lists only live sessions and panels of this PRD")

# unsent count on the detail
seed(thread("t1", "a"), state="ended")
assert ui_share_api._view(ui_shares.get(SID), detail=True)["unsent"] == 1
ok("detail unsent")
print(f"{passed} groups passed")
