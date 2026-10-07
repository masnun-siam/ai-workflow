#!/usr/bin/env python3
"""Self-check for run-engine/ui_sessions.py. `python3 test_ui_sessions.py` — exit 0 = green.

Assert-based, no framework, matching test_kanban.py. Every block points
CLAUDE_PLUGIN_DATA at a fresh tempdir so the real data dir is never touched.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ui_sessions  # noqa: E402

passed = 0
ID_RE = re.compile(r"[0-9]{8}T[0-9]{12}Z-[0-9a-f]{8}")
KEYS = {"id", "command", "repo", "link", "session_id", "pid", "status",
        "cost", "started_at", "ended_at", "pending_question", "claude_cmd"}
NEVER = "20990101T000000000000Z-deadbeef"


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


def fresh() -> str:
    d = tempfile.mkdtemp()
    os.environ["CLAUDE_PLUGIN_DATA"] = d
    for k in [k for k in os.environ if k.startswith("AIW_NTFY_")]:
        os.environ.pop(k)
    return d


def meta_path(d, sid):
    return os.path.join(d, "sessions", sid, "meta.json")


def tmps(d):
    return [f for _, _, fs in os.walk(d) for f in fs if f.endswith(".tmp")]


def captured(fn):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        res = fn()
    return res, err.getvalue()


def raises(exc, fn):
    try:
        fn()
    except exc:
        return
    raise AssertionError(f"expected {exc.__name__}")


# 1. create defaults
d = fresh()
r = ui_sessions.create("run-issue", "/tmp/repo")
assert set(r) == KEYS, set(r) ^ KEYS
assert ID_RE.fullmatch(r["id"])
assert r["command"] == "run-issue" and r["repo"] == "/tmp/repo"
for k in ("link", "session_id", "pid", "cost", "ended_at", "pending_question"):
    assert r[k] is None, k
assert r["status"] == "starting"
assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|\+00:00)", r["started_at"]), r["started_at"]
ok("create returns defaults")

# 2. link verbatim + load equality
link = {"owner": "o", "repo": "r", "issue": 7}
r2 = ui_sessions.create("c", "/r", link=link)
assert r2["link"] == link
assert ui_sessions.load(r2["id"]) == r2
ok("link stored verbatim; load == create")

# 3. files on disk
assert os.path.isfile(meta_path(d, r["id"]))
sp = os.path.join(d, "sessions", r["id"], "stream.jsonl")
assert os.path.isfile(sp) and os.path.getsize(sp) == 0
assert ui_sessions.session_dir(r["id"]) == os.path.join(ui_sessions.sessions_dir(), r["id"])
assert ui_sessions.sessions_dir() == os.path.join(d, "sessions")
ok("meta.json and empty stream.jsonl created")

# 4. update merges
u = ui_sessions.update(r["id"], pid=123, session_id="abc", status="running", cost=0.42)
assert u["pid"] == 123 and u["status"] == "running" and u["command"] == "run-issue"
u = ui_sessions.update(r["id"], status="done", ended_at="2026-01-01T00:00:00Z")
assert u["pid"] == 123 and u["session_id"] == "abc" and u["cost"] == 0.42
assert ui_sessions.load(r["id"]) == u and u["status"] == "done"
with open(meta_path(d, r["id"])) as f:
    assert json.load(f) == u
ok("update merges only given keys")

# 5. pending_question nested + clear
q = {"text": "ok?", "options": ["y", {"n": 1}]}
assert ui_sessions.update(r["id"], pending_question=q)["pending_question"] == q
assert ui_sessions.load(r["id"])["pending_question"] == q
assert ui_sessions.update(r["id"], pending_question=None)["pending_question"] is None
assert ui_sessions.load(r["id"])["pending_question"] is None
ok("pending_question set and cleared")

# 6. list newest first
d = fresh()
ids = []
for i in range(3):
    ids.append(ui_sessions.create("c", f"/r{i}")["id"])
    time.sleep(0.002)
lst = ui_sessions.list_sessions()
assert [x["id"] for x in lst] == sorted(ids, reverse=True)
assert [x["id"] for x in lst] == ids[::-1]
ok("list_sessions newest first")

# 7. restart
out = subprocess.run(
    [sys.executable, "-c",
     f"import sys,json; sys.path.insert(0,{HERE!r}); import ui_sessions; "
     "print(json.dumps(ui_sessions.list_sessions()))"],
    env=dict(os.environ), capture_output=True, text=True, check=True).stdout
assert json.loads(out) == ui_sessions.list_sessions() and len(json.loads(out)) == 3
ok("fresh interpreter lists same sessions")

# 8. empty / missing
d = fresh()
assert ui_sessions.list_sessions() == []
os.makedirs(os.path.join(d, "sessions"))
assert ui_sessions.list_sessions() == []
ok("list_sessions empty when dir missing or empty")

# 9. load never created
assert ui_sessions.load(NEVER) is None
ok("load of unknown id is None")

# 10. ignore junk
good = ui_sessions.create("c", "/r")
sd = os.path.join(d, "sessions")
os.makedirs(os.path.join(sd, "20990101T000000000000Z-aaaaaaaa"))  # no meta.json
for name in ("stray.txt", ".meta.xyz.tmp", ".hidden"):
    open(os.path.join(sd, name), "w").close()
res, err = captured(ui_sessions.list_sessions)
assert [x["id"] for x in res] == [good["id"]]
ok("list_sessions ignores dirs without meta and stray/dot files")

# 11. corrupt json
bad = "20990101T000000000001Z-bbbbbbbb"
os.makedirs(os.path.join(sd, bad))
with open(meta_path(d, bad), "w") as f:
    f.write('{"id": ')
res, err = captured(ui_sessions.list_sessions)
assert [x["id"] for x in res] == [good["id"]]
assert any(l.startswith("warning:") and bad in l for l in err.splitlines()), err
res, err = captured(lambda: ui_sessions.load(bad))
assert res is None and "warning:" in err, err
ok("invalid JSON skipped with warning")

# 12. non-object json
for i, body in enumerate(("[]", '"x"')):
    sid = f"20990101T00000000001{i}Z-cccccccc"
    os.makedirs(os.path.join(sd, sid))
    with open(meta_path(d, sid), "w") as f:
        f.write(body)
    res, err = captured(ui_sessions.list_sessions)
    assert [x["id"] for x in res] == [good["id"]]
    assert any(l.startswith("warning:") and sid in l for l in err.splitlines()), err
    res, err = captured(lambda: ui_sessions.load(sid))
    assert res is None and "warning:" in err
ok("non-object JSON skipped with warning")

# 13. interrupted write
d = fresh()
r = ui_sessions.create("c", "/r")
before = ui_sessions.load(r["id"])


def boom(*a, **k):
    raise OSError("boom")


for target in ("json.dump", "os.replace"):
    with mock.patch(target, side_effect=boom):
        raises(OSError, lambda: ui_sessions.update(r["id"], status="x"))
    with open(meta_path(d, r["id"])) as f:
        assert json.load(f) == before
    assert ui_sessions.load(r["id"]) == before
    assert tmps(d) == [], tmps(d)
ok("interrupted write leaves meta intact, no tmp")

# 14. update unknown id
d = fresh()
raises(FileNotFoundError, lambda: ui_sessions.update(NEVER, status="x"))
assert not os.path.exists(os.path.join(d, "sessions", NEVER))
ok("update of unknown id raises FileNotFoundError")

# 15. id immutable
r = ui_sessions.create("c", "/r")
raises(ValueError, lambda: ui_sessions.update(r["id"], id="other"))
assert ui_sessions.load(r["id"])["id"] == r["id"]
ok("id is immutable")

# 16. path safety
d = fresh()
ui_sessions.create("c", "/r")
sib = os.path.join(d, "x")
for bad_id in ("", ".", "..", "../x", "a/b", "a\\b", "/etc", "x\x00",
               ui_sessions.create("c", "/r")["id"] + "/"):
    raises(ValueError, lambda: ui_sessions.load(bad_id))
    raises(ValueError, lambda: ui_sessions.update(bad_id, status="x"))
    raises(ValueError, lambda: ui_sessions.session_dir(bad_id))
assert sorted(os.listdir(d)) == ["sessions"], os.listdir(d)
assert not os.path.exists(sib)
ok("malformed ids rejected, nothing outside sessions dir")

# 17. 50 unique
d = fresh()
ids = [ui_sessions.create("c", "/r")["id"] for _ in range(50)]
assert len(set(ids)) == 50 and all(ID_RE.fullmatch(i) for i in ids)
assert len(ui_sessions.list_sessions()) == 50
ok("50 creates yield 50 unique ids")

# 18. concurrency, real processes
d = fresh()
r = ui_sessions.create("c", "/r")
N, ITER = 8, 200
child = (
    "import sys,os,time; sys.path.insert(0,%r); import ui_sessions\n"
    "sid,k,go=sys.argv[1],int(sys.argv[2]),sys.argv[3]\n"
    "while not os.path.exists(go): time.sleep(0.001)\n"
    "for i in range(%d): ui_sessions.update(sid, writer=k, n=i)\n" % (HERE, ITER)
)
go = os.path.join(tempfile.mkdtemp(), "go")
procs = [subprocess.Popen([sys.executable, "-c", child, r["id"], str(k), go],
                          env=dict(os.environ)) for k in range(N)]
open(go, "w").close()
loads = 0
while any(p.poll() is None for p in procs):
    m = ui_sessions.load(r["id"])
    assert m is not None and m["id"] == r["id"]
    with open(meta_path(d, r["id"])) as f:
        json.load(f)
    loads += 1
assert all(p.returncode == 0 for p in procs), [p.returncode for p in procs]
with open(meta_path(d, r["id"])) as f:
    final = json.load(f)
assert final["writer"] in range(N) and 0 <= final["n"] < ITER
assert tmps(d) == []
ok(f"concurrent writers never corrupt meta ({loads} reads)")

# 19. only written fields (optional mode check)
with open(meta_path(d, r["id"])) as f:
    assert set(json.load(f)) == KEYS | {"writer", "n"}
ok("meta.json holds only written fields")

print(f"\n{passed} checks passed")
sys.exit(0)
