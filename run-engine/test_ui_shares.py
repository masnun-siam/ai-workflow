#!/usr/bin/env python3
"""Self-check for run-engine/ui_shares.py. `python3 test_ui_shares.py` — exit 0 = green."""

from __future__ import annotations

import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()
import ui_shares as S  # noqa: E402

co = tempfile.mkdtemp()
prds = os.path.join(co, "docs", "prds")
os.makedirs(prds)
n = 0


def ok(label):
    global n
    n += 1
    print("ok", label)


def prd(name="x", status="Draft"):
    line = f"**Status:** {status} · **Slug:** `{name}`\n" if status else ""
    with open(os.path.join(prds, name + ".md"), "w") as f:
        f.write(f"# PRD — T\n\n{line}")


def rejects(kind, *a):
    try:
        S.create(*a)
    except S.ShareError as e:
        assert e.kind == kind, (e.kind, kind)
        return
    raise AssertionError("no ShareError")


R, P = "/repo", "docs/prds/x.md"
prd()
sh, new = S.create(R, P, co)
f = os.path.join(S.shares_dir(), sh["id"] + ".json")
assert new and sh["state"] == "live" and sh["end_reason"] is None and len(sh["token"]) >= 22
assert sh["threads"] == [] and sh["approvals"] == [] and sh["created_at"] and sh["last_seen_at"]
assert os.stat(f).st_mode & 0o777 == 0o600
assert sorted(os.listdir(S.shares_dir())) == [sh["id"] + ".json"]
ok("create")

sh2, new = S.create(R, P, co)
assert not new and sh2["token"] == sh["token"] and sh2["id"] == sh["id"]
prd("y")
out = []
ts = [threading.Thread(target=lambda: out.append(S.create(R, "docs/prds/y.md", co))) for _ in range(8)]
[t.start() for t in ts]
[t.join() for t in ts]
assert len({r[0]["token"] for r in out}) == 1 and sum(r[1] for r in out) == 1
assert len(S.list_shares()) == 2
ok("idempotent + concurrent")

prd("a", "Approved")
rejects("conflict", R, "docs/prds/a.md", co)
prd("d", "Done")
rejects("conflict", R, "docs/prds/d.md", co)
prd("w", "Wibble")
assert S.create(R, "docs/prds/w.md", co)[1]
prd("n", None)
assert S.create(R, "docs/prds/n.md", co)[1]
rejects("invalid", R, "docs/other/x.md", co)
rejects("invalid", R, "docs/prds/nope.md", co)
os.mkdir(os.path.join(prds, "dir.md"))
rejects("invalid", R, "docs/prds/dir.md", co)
os.symlink("/nonexistent", os.path.join(prds, "dang.md"))
rejects("invalid", R, "docs/prds/dang.md", co)
out_f = os.path.join(tempfile.mkdtemp(), "o.md")
open(out_f, "w").write("# o\n")
os.symlink(out_f, os.path.join(prds, "out.md"))
rejects("invalid", R, "docs/prds/out.md", co)
os.symlink("x.md", os.path.join(prds, "ln.md"))
s_ln, _ = S.create(R, "docs/prds/ln.md", co)
assert S.refresh(s_ln["id"], co)["state"] == "live"
os.remove(os.path.join(prds, "ln.md"))
os.symlink(out_f, os.path.join(prds, "ln.md"))
assert S.refresh(s_ln["id"], co)["end_reason"] == "missing"
ok("eligibility")

old = sh["token"]
for r in ("stopped", "approved", "status", "missing"):
    s, _ = S.create(R, "docs/prds/w.md", co)
    e = S.end(s["id"], r)
    assert e["state"] == "ended" and e["end_reason"] == r and e["token"] is None and e["ended_at"]
    assert S.by_token(s["token"]) is None
    assert S.end(s["id"], "stopped")["end_reason"] == r
try:
    S.end(sh["id"], "bogus")
    raise AssertionError
except ValueError:
    pass
assert S.end("../x", "stopped") is None
ok("end")

S.update(sh["id"], lambda r: r["threads"].append({"id": "t"}))
S.update(sh["id"], lambda r: r["approvals"].append({"id": "a"}))
prd("x", "Approved")
assert S.refresh(sh["id"], co)["end_reason"] == "approved"
prd("x", "Draft")
s3, new = S.create(R, P, co)
assert new and s3["id"] == sh["id"] and s3["token"] not in (None, old)
assert s3["threads"] == [{"id": "t"}] and s3["approvals"] == [] and s3["end_reason"] is None and s3["ended_at"] is None
prd("x", "Done")
assert S.refresh(sh["id"], co)["end_reason"] == "status"
prd("x", "Draft")
S.create(R, P, co)
os.remove(os.path.join(prds, "x.md"))
assert S.refresh(sh["id"], co)["end_reason"] == "missing"
prd("x")
S.create(R, P, co)
assert S.refresh(sh["id"], None)["end_reason"] == "missing"
ok("refresh + re-share")

prd("x")
real_clock, t = S.clock, [5000.0]
S.clock = lambda: t[0]
S.end(sh["id"], "stopped")
sx, _ = S.create(R, P, co, S.now_iso())
assert sx["expires_at"] and S.refresh(sx["id"], co)["end_reason"] == "expired"
assert S.get(sx["id"])["token"] is None
sx, _ = S.create(R, P, co, "1970-01-01T01:40:00.000+00:00")  # 6000s
t[0] = 5999.0
assert S.refresh(sx["id"], co)["state"] == "live"
t[0] = 6000.0
assert S.refresh(sx["id"], co)["end_reason"] == "expired"
sx, _ = S.create(R, P, co)
assert sx["expires_at"] is None and S.refresh(sx["id"], co)["state"] == "live"
S.clock = real_clock
ok("expiry ends by time; re-share clears expires_at")

prd("x")
s4, _ = S.create(R, P, co)
assert S.by_token(s4["token"])["id"] == sh["id"]
assert S.by_token("") is None and S.by_token("é☃") is None and S.by_token(None) is None
ok("by_token")

before = S.list_shares()
S._reset_locks()
assert S.list_shares() == before and S.get(sh["id"]) == s4
ok("restart")

try:
    S.delete_record(sh["id"])
    raise AssertionError
except S.ShareError as e:
    assert e.kind == "conflict"
S.end(sh["id"], "stopped")
S.delete_record(sh["id"])
assert S.get(sh["id"]) is None
for bad in ("0" * 16, "../x"):
    try:
        S.delete_record(bad)
        raise AssertionError
    except S.ShareError as e:
        assert e.kind == "not_found"
ok("delete_record")

open(os.path.join(S.shares_dir(), "junk.json"), "w").write("{nope")
open(os.path.join(S.shares_dir(), "0" * 16 + ".json"), "w").write('{"id": "%s"}' % ("0" * 16))
assert S.get("0" * 16) is None and S.end("0" * 16, "stopped") is None
assert all(r["id"] != "junk" for r in S.list_shares())
assert not [x for x in os.listdir(S.shares_dir()) if x.endswith(".tmp")]
ok("corrupt skipped")

import json  # noqa: E402

for sid, extra, want in (("1" * 16, {}, [[], []]), ("2" * 16, {"threads": "x"}, None)):
    with open(os.path.join(S.shares_dir(), sid + ".json"), "w") as fh:
        json.dump({"id": sid, "state": "live", **extra}, fh)
    r = S.get(sid)
    assert (r and [r["threads"], r["approvals"]]) == (want or None), r
ok("missing threads/approvals default to [], non-list is unreadable")


# --- threads, comments, approvals ---
def raises(kind, fn, *a):
    try:
        fn(*a)
    except S.ShareError as e:
        assert e.kind == kind, (e.kind, kind)
        return e
    raise AssertionError("no ShareError")


now = [1000.0]
S.clock = lambda: now[0]
prd("t")
PT = "docs/prds/t.md"
st, _ = S.create(R, PT, co)
sid = st["id"]
A = {"exact": "quote", "prefix": "pre", "suffix": "suf"}
t1 = S.add_thread(sid, "  Ana ", "  hi  ", A)
assert t1["anchor"] == A and t1["resolved"] is False and t1["sent_at"] is None
c = t1["comments"][0]
assert c["author"] == "Ana" and c["body"] == "hi" and c["by_owner"] is False
assert S.add_thread(sid, "A", "b", {"exact": " x "})["anchor"] == {"exact": " x ", "prefix": "", "suffix": ""}
ok("add_thread")

for bad in (
    ("", "b", A),
    ("a" * 61, "b", A),
    ("a", "", A),
    ("a", "   ", A),
    ("a", "b" * 2001, A),
    (5, "b", A),
    ("a", None, A),
    ("a", "b", {"exact": ""}),
    ("a", "b", {"exact": " "}),
    ("a", "b", {"exact": "x" * 1001}),
    ("a", "b", {"exact": "x", "prefix": "p" * 33}),
    ("a", "b", {"exact": "x", "suffix": 3}),
    ("a", "b", None),
    ("a", "b", {"exact": "\ud800"}),
    ("\ud800", "b", A),
    ("a", "\ud800", A),
):
    raises("invalid", S.add_thread, sid, *bad)
assert "x" * 5 not in str(raises("invalid", S.add_thread, sid, "a", "x" * 5000, A))
S.add_thread(sid, "a", "b" * 2000, A)
S.add_thread(sid, "😀" * 60, "ok", A)
raises("invalid", S.add_thread, sid, "😀" * 61, "ok", A)
S.add_thread(sid, "a", "ক" * 2000, {"exact": "ক" * 1000})
ok("limits")

now[0] += 100
t2 = S.add_thread(sid, "Bo", "x", A)
rep = S.add_comment(sid, t2["id"], "Cy", "reply")
assert rep["by_owner"] is False
S.set_resolved(sid, t2["id"], True)
assert S.get(sid)["threads"][-1]["resolved"] is True
oc = S.add_owner_comment(sid, t2["id"], "Boss" * 30, "ack")
assert oc["by_owner"] is True and len(oc["author"]) == 60
assert S.get(sid)["threads"][-1]["resolved"] is True
S.add_comment(sid, t2["id"], "Cy", "again")
assert S.get(sid)["threads"][-1]["resolved"] is False
assert S.set_resolved(sid, t2["id"], True)["resolved"] is True
assert S.set_resolved(sid, t2["id"], False)["resolved"] is False
raises("not_found", S.add_comment, sid, "nope", "a", "b")
raises("not_found", S.add_owner_comment, sid, "nope", "a", "b")
raises("not_found", S.set_resolved, sid, "nope", True)
ok("reply + reopen")

t3 = S.add_thread(sid, "D", "first", A)
r1 = S.add_comment(sid, t3["id"], "D", "second")
S.delete_comment(sid, t3["id"], t3["comments"][0]["id"])
kept = [t for t in S.get(sid)["threads"] if t["id"] == t3["id"]][0]
assert kept["anchor"] == A and [x["id"] for x in kept["comments"]] == [r1["id"]]
S.delete_comment(sid, t3["id"], r1["id"])
assert all(t["id"] != t3["id"] for t in S.get(sid)["threads"])
t4 = S.add_thread(sid, "D", "a", A)
r4 = S.add_comment(sid, t4["id"], "D", "b")
S.delete_comment(sid, t4["id"], r4["id"])
assert len(S.get(sid)["threads"][-1]["comments"]) == 1
S.delete_thread(sid, t4["id"])
raises("not_found", S.delete_thread, sid, t4["id"])
raises("not_found", S.delete_comment, sid, t1["id"], "nope")
raises("not_found", S.delete_comment, sid, "nope", "nope")
ok("deletes")

# cap: seed 500 reviewer comments
cs = [{"id": "c%d" % i, "author": "a", "by_owner": False, "body": "b", "at": "2000"} for i in range(500)]
S.update(
    sid,
    lambda r: r.update(
        threads=[{"id": "seed", "anchor": A, "created_at": "2000", "resolved": False, "sent_at": None, "comments": cs}]
    ),
)
now[0] += 100
raises("full", S.add_thread, sid, "a", "b", A)
raises("full", S.add_comment, sid, "seed", "a", "b")
S.add_owner_comment(sid, "seed", "me", "still works")
S.delete_comment(sid, "seed", "c0")
S.add_comment(sid, "seed", "a", "fits now")
ok("500 cap")

# rate window
S.update(sid, lambda r: r.update(threads=[]))
now[0] += 100
for i in range(20):
    S.add_thread(sid, "a", "b", A)
raises("rate", S.add_thread, sid, "a", "b", A)
raises("invalid", S.add_thread, sid, "a", "", A)
th = S.get(sid)["threads"][0]
S.add_owner_comment(sid, th["id"], "me", "owner free")
raises("rate", S.add_approval, sid, "Zed")
now[0] += 61
S.add_thread(sid, "a", "b", A)
ok("rate")

# approvals
now[0] += 100
v, new = S.add_approval(sid, " Ana ")
assert new and v["name"] == "Ana" and len(v["key"]) >= 24
h = S.get(sid)["approvals"][0]["key_hash"]
assert v["key"] not in open(S._path(sid)).read() and h != v["key"]
v2, new2 = S.add_approval(sid, "ANA")
assert (
    not new2 and "key" not in v2 and S.get(sid)["approvals"][0]["key_hash"] == h and len(S.get(sid)["approvals"]) == 1
)
e1 = raises("not_found", S.withdraw_approval, sid, "Ana", "wrong")
e2 = raises("not_found", S.withdraw_approval, sid, "Nobody", v["key"])
assert str(e1) == str(e2)
raises("not_found", S.withdraw_approval, sid, "Ana", "é")
S.withdraw_approval(sid, "aNA", v["key"])
assert S.get(sid)["approvals"] == []
raises("not_found", S.withdraw_approval, sid, "Ana", v["key"])
S.update(
    sid,
    lambda r: r.update(
        approvals=[{"id": "a%d" % i, "name": "n%d" % i, "at": "2000", "key_hash": "h"} for i in range(100)]
    ),
)
now[0] += 100
raises("full", S.add_approval, sid, "late")
S.add_approval(sid, "n5")
S.delete_approval(sid, "a5")
raises("not_found", S.delete_approval, sid, "a5")
assert len(S.get(sid)["approvals"]) == 99
ok("approvals")

# concurrency
now[0] += 100
S.update(sid, lambda r: r.update(threads=[], approvals=[]))
S.RATE_MAX = 10**6
ts = [threading.Thread(target=S.add_thread, args=(sid, "a", "b", A)) for _ in range(50)]
[t.start() for t in ts]
[t.join() for t in ts]
assert len(S.get(sid)["threads"]) == 50
S.RATE_MAX = 20
now[0] += 100
tid = S.get(sid)["threads"][0]["id"]
ts = [
    threading.Thread(target=S.add_comment, args=(sid, tid, "a", "r")),
    threading.Thread(target=S.add_owner_comment, args=(sid, tid, "me", "o")),
]
[t.start() for t in ts]
[t.join() for t in ts]
assert sorted(c["by_owner"] for c in S.get(sid)["threads"][0]["comments"]) == [False, False, True]
ok("concurrency")

# listeners
calls = []
S.listeners.append(lambda s, k: calls.append(k))
S.listeners.append(lambda s, k: 1 / 0)
now[0] += 100
tt = S.add_thread(sid, "a", "b", A)
S.add_comment(sid, tt["id"], "a", "c")
S.add_owner_comment(sid, tt["id"], "me", "o")
S.add_approval(sid, "Lee")
S.add_approval(sid, "lee")
assert calls == ["comment", "comment", "approval"], calls
S.listeners.clear()
ok("listeners")

# unread, mark_sent, public views
sh_now = S.get(sid)
assert S.unread(dict(sh_now, last_seen_at=None))["comments"] == len(
    [1 for t in sh_now["threads"] for c in t["comments"] if not c["by_owner"]]
)
assert S.unread(dict(sh_now, last_seen_at="9999")) == {"comments": 0, "approvals": 0, "at": None}
u = S.unread(dict(sh_now, last_seen_at=sh_now["approvals"][0]["at"]))
assert u["approvals"] == 0 and u["at"] is None or u["at"] > sh_now["approvals"][0]["at"]
S.mark_sent(sid, {tt["id"]: "2030-01-02", "nope": "x"})
S.mark_sent(sid, {tt["id"]: "2030-01-01"})
assert [t for t in S.get(sid)["threads"] if t["id"] == tt["id"]][0]["sent_at"] == "2030-01-02"
pub = str(S.public_threads(S.get(sid))) + str(S.public_approvals(S.get(sid)))
assert "sent_at" not in pub and "key_hash" not in pub
assert set(S.public_approvals(S.get(sid))[0]) == {"name", "at"}
ok("unread, mark_sent, public")

# ended share
S.end(sid, "stopped")
raises("not_found", S.add_thread, sid, "a", "b", A)
raises("not_found", S.add_comment, sid, tt["id"], "a", "b")
raises("not_found", S.add_approval, sid, "x")
raises("not_found", S.withdraw_approval, sid, "Lee", "k")
S.add_owner_comment(sid, tt["id"], "me", "late")
S.set_resolved(sid, tt["id"], True)
S.delete_approval(sid, S.get(sid)["approvals"][0]["id"])
S.delete_record(sid)
assert sid not in S._rates
ok("ended share")

print(f"{n} groups green")
