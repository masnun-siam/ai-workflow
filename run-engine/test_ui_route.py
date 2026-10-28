#!/usr/bin/env python3
"""Self-check for run-engine/ui_route.py with a fake `jev` on PATH. `python3 test_ui_route.py` — exit 0 = green."""

from __future__ import annotations

import os
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ui_route  # noqa: E402

bin_dir = tempfile.mkdtemp()
fake = os.path.join(bin_dir, "jev")


def fake_jev(body: str) -> None:
    with open(fake, "w") as f:
        f.write("#!/bin/sh\ncat >/dev/null\n" + body + "\n")
    os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)


old_path = os.environ.get("PATH", "")

# no jev on PATH: no route, and a reason
os.environ["PATH"] = tempfile.mkdtemp()
r = ui_route.route("fix the login 404")
assert r["route"] is None and "not installed" in r["why"], r

os.environ["PATH"] = bin_dir + os.pathsep + old_path

fake_jev(
    """echo '{"choice":"small_change","confidence":0.8,"probabilities":{"feature":0.1,"small_change":0.88,"unclear":0.02}}'"""
)
r = ui_route.route("fix the login 404")
assert r["route"] == "small_change" and r["confidence"] == 0.88, r

fake_jev(
    """echo '{"choice":"feature","confidence":0.9,"probabilities":{"feature":0.91,"small_change":0.08,"unclear":0.01}}'"""
)
assert ui_route.route("schedule campaigns")["route"] == "feature"

# unclear, or a weak winner: the user picks
fake_jev("""echo '{"choice":"unclear","probabilities":{"unclear":0.6,"feature":0.2,"small_change":0.2}}'""")
assert ui_route.route("stuff")["route"] is None
fake_jev("""echo '{"choice":"feature","probabilities":{"feature":0.35,"small_change":0.34,"unclear":0.31}}'""")
assert ui_route.route("stuff")["route"] is None

# a failing or garbled jev never raises
fake_jev("exit 3")
r = ui_route.route("x")
assert r["route"] is None and "exit 3" in r["why"], r
fake_jev("echo not-json")
assert ui_route.route("x")["route"] is None

# empty text is a caller error
for bad in ("", "   ", None, 5):
    try:
        ui_route.route(bad)
        raise AssertionError(f"route({bad!r}) must raise")
    except ValueError:
        pass

print("ok")
