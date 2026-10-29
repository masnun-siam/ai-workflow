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
print(f"{n} groups green")
