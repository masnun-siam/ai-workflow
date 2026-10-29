#!/usr/bin/env python3
"""Self-check for `aiw jev` (jev_cli.py) with a stub `jev` on PATH. `python3 test_jev_cli.py` — exit 0 = green."""

from __future__ import annotations

import json
import os
import stat
import subprocess
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
calls, stdin_log = os.path.join(d, "calls"), os.path.join(d, "stdin")

import ui_settings  # noqa: E402

OK = '{"choice":"real","probabilities":{"real":0.834,"flaky":0.166}}'


def stub(body: str) -> None:
    p = os.path.join(bindir, "jev")
    with open(p, "w") as f:
        f.write(f'#!/bin/sh\necho "$@" >> {calls}\ncat > {stdin_log}\n{body}\n')
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
    for f in (calls, stdin_log):
        if os.path.exists(f):
            os.remove(f)


def read(f):
    return open(f).read() if os.path.exists(f) else ""


def aiw(op, content, path=bindir):
    src = os.path.join(d, "in.txt")
    with open(src, "w") as f:
        f.write(content)
    env = {**os.environ, "PATH": path + ":/usr/bin:/bin"}
    p = subprocess.run(
        [sys.executable, os.path.join(HERE, "route.py"), "jev", op, "--file", src],
        capture_output=True,
        text=True,
        env=env,
    )
    return p


def run(op, content, path=bindir):
    p = aiw(op, content, path)
    assert p.returncode == 0, (op, p.returncode, p.stderr)
    return json.loads(p.stdout), p.stderr


NONE = {"hint": "none", "probability": 0}

stub(f"echo '{OK}'")
r, _ = run("ci-hint", "boom")
assert r == {"hint": "real", "probability": 0.83, "status": "ok"}, r
argv = read(calls)
assert "--model" in argv and "real=" in argv and "flaky=" in argv, argv

stub('echo \'{"choice":"flaky","probabilities":{"real":0.2,"flaky":0.8}}\'')
assert run("ci-hint", "boom")[0] == {"hint": "flaky", "probability": 0.8, "status": "ok"}

# off: stub never invoked, both verbs
stub(f"echo '{OK}'")  # also clears the call log
ui_settings.save({"use_jev": False})
for op, body in (("ci-hint", "boom"), ("finding-hint", '[{"id":1,"text":"a"}]')):
    r, _ = run(op, body)
    if op == "ci-hint":
        assert r == {**NONE, "status": "off"}, r
    else:
        assert r == [{"id": 1, **NONE, "status": "off"}], r
    assert read(calls) == "", op
ui_settings.save({"use_jev": True})

# missing
assert run("ci-hint", "boom", emptydir)[0] == {**NONE, "status": "missing"}

# failed
for body in ("exit 3", "echo not-json"):
    stub(body)
    assert run("ci-hint", "boom")[0] == {**NONE, "status": "failed"}, body
stub(f"echo '{OK}'")
assert run("ci-hint", "")[0] == {**NONE, "status": "failed"}
assert read(calls) == ""
p = subprocess.run(
    [sys.executable, os.path.join(HERE, "route.py"), "jev", "ci-hint", "--file", os.path.join(d, "nope")],
    capture_output=True,
    text=True,
    env={**os.environ, "PATH": bindir + ":/usr/bin:/bin"},
)
assert p.returncode == 0 and json.loads(p.stdout) == {**NONE, "status": "failed"}

# tail
stub(f"echo '{OK}'")
run("ci-hint", "HEAD " + "x " * 2496 + "TAIL")
sent = read(stdin_log)
assert "TAIL" in sent and "HEAD" not in sent

# findings
stub(f"echo '{OK}'")
r, err = run("finding-hint", json.dumps([{"id": i, "text": f"SECRETTEXT{i}"} for i in range(1, 22)]))
assert [e["id"] for e in r] == list(range(1, 21)), r
assert len(read(calls).splitlines()) == 20
assert "SECRETTEXT" not in err

r, _ = run("finding-hint", json.dumps([{"text": "a"}, {"id": None, "text": "b"}, {"id": 7, "text": "c"}]))
assert [e["id"] for e in r] == ["#1", "#2", 7], r
assert run("finding-hint", "{}")[0] == []
assert run("finding-hint", "garbage")[0] == []

assert not os.path.exists(os.path.join(d, "jev_cache.json"))
print("ok")
