#!/usr/bin/env python3
"""Self-check for run-engine/jev.py with a stub `jev` on PATH. `python3 test_jev.py` — exit 0 = green."""

from __future__ import annotations

import contextlib
import io
import os
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

d = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = d
bindir = os.path.join(d, "bin")
emptydir = os.path.join(d, "empty")
os.makedirs(bindir)
os.makedirs(emptydir)
argv_log, stdin_log = os.path.join(d, "argv"), os.path.join(d, "stdin")

import jev  # noqa: E402
import ui_settings  # noqa: E402


def stub(body: str) -> None:
    p = os.path.join(bindir, "jev")
    with open(p, "w") as f:
        f.write(f'#!/bin/sh\necho "$@" >> {argv_log}\ncat > {stdin_log}\n{body}\n')
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
    for f in (argv_log, stdin_log):
        if os.path.exists(f):
            os.remove(f)


def ask(*a, **k):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        r = jev.ask(*a, **k)
    return r, err.getvalue()


def read(f):
    return open(f).read() if os.path.exists(f) else ""


os.environ["PATH"] = bindir + ":/usr/bin:/bin"

# ok: each kind, model pinned
stub("""echo '{"noul":0.7}'""")
r, err = ask("risk", "noul", "q?", "text")
assert r == {"status": "ok", "p": 0.7} and err == "", (r, err)
assert "--model jev-1.14.0" in read(argv_log)
stub("""echo '{"choice":"a","confidence":0.5,"probabilities":{"a":0.9}}'""")
assert ask("route", "choice", "q?", "t", options={"a": "A", "b": "B"})[0] == {"status": "ok", "choice": "a", "p": 0.9}
assert "--option a=A --option b=B" in read(argv_log)
stub("""echo '{"choice":"a","confidence":0.5}'""")
assert ask("route", "choice", "q?", "t", options={"a": "A"})[0]["p"] == 0.5
stub("""echo '{"score":2.5,"confidence":0.6}'""")
r, _ = ask("urgency", "score", "q?", "t", levels=["low", "high"])
assert r == {"status": "ok", "score": 2.5, "confidence": 0.6}, r
assert "--level low --level high" in read(argv_log)

# failures: null answer, one warning with the point and status only
stub("sleep 9")
jev.TIMEOUT_S = 1
r, err = ask("route", "noul", "q?", "SECRETTEXT")
assert r == {"status": "no_answer"} and err == "warning: jev route: no_answer\n", (r, err)
stub("echo LEAKED >&2; exit 3")
r, err = ask("route", "noul", "q?", "SECRETTEXT")
assert r == {"status": "failed", "exit": 3} and err == "warning: jev route: failed\n", (r, err)
for body in ("echo not-json", """echo '{"other":1}'""", "echo '[1]'"):
    stub(body)
    r, err = ask("route", "noul", "q?", "SECRETTEXT")
    assert r == {"status": "unreadable"} and err == "warning: jev route: unreadable\n", (r, err)

# missing: silent
os.environ["PATH"] = emptydir
r, err = ask("route", "noul", "q?", "t")
assert r == {"status": "missing"} and err == ""
os.environ["PATH"] = bindir + ":/usr/bin:/bin"

# off: silent, and jev is never run
stub("""echo '{"noul":0.7}'""")
ui_settings.save({"use_jev": False})
r, err = ask("route", "noul", "q?", "t")
assert r == {"status": "off"} and err == "" and not os.path.exists(argv_log)
assert jev.status() == "off"
ui_settings.save({"use_jev": True})
assert jev.status() == "ok"

# redaction
secrets = [
    "ghp_" + "a1B2c3D4" * 3,
    "github_pat_" + "a1B2c3D4" * 4,
    "sk-ant-" + "a1B2c3D4" * 3,
    "xoxb-" + "1234567890" * 3,
    "AKIA" + "ABCD1234EFGH5678",
    "GH_TOKEN=abc123",
    "api_key: abc123",
    "MY_SECRET=abc123",
    "Authorization: Basic abc123",
    "Bearer abc123.def456",
    "0123456789abcdef" * 2 + "01234567",
    "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo" + "abcdefghijklmn",
]
r, _ = ask("route", "noul", "q?", "\n".join(secrets) + "\nfix the login 404 in the task-list")
sent = read(stdin_log)
for s in secrets:
    val = s.split("=")[-1].split(": ")[-1].split("Basic ")[-1].split("Bearer ")[-1]
    assert val not in sent, (val, sent)
assert "[redacted]" in sent and sent.endswith("fix the login 404 in the task-list"), sent
assert "GH_TOKEN=[redacted]" in sent and "Authorization: [redacted]" in sent

# truncation after redaction
ask("route", "noul", "q?", "x " * 2500)
assert len(read(stdin_log)) == 4000

print("ok")
