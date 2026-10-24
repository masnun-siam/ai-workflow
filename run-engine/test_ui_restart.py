#!/usr/bin/env python3
"""Self-check for run-engine/ui_restart.py. `python3 test_ui_restart.py` — exit 0 = green."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

data = tempfile.mkdtemp()
root = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = data

import ui_restart  # noqa: E402

ui_restart.ROOT = root


def makefile(recipe):
    with open(os.path.join(root, "Makefile"), "w") as f:
        f.write(f"restart:\n\t{recipe}\n")


def wait_done():
    for _ in range(100):
        st = ui_restart.status()
        if st["exit_code"] is not None:
            return st
        time.sleep(0.1)
    raise AssertionError("restart did not finish")


try:
    # no Makefile
    assert ui_restart.status()["available"] is False
    try:
        ui_restart.start()
        raise AssertionError("start without a Makefile must raise")
    except ValueError:
        pass
    # a Makefile with no restart: target
    with open(os.path.join(root, "Makefile"), "w") as f:
        f.write("build:\n\ttrue\n")
    assert ui_restart.available() is False

    # success: output lands in the log tail, exit code 0
    makefile("echo hi")
    assert ui_restart.start() == {"ok": True}
    st = wait_done()
    assert st["exit_code"] == 0 and "hi" in st["log_tail"] and st["running"] is False and st["available"] is True

    # a second start while one runs is a Conflict; a new run clears the old exit file
    makefile("sleep 2")
    ui_restart.start()
    assert ui_restart.status()["running"] is True and ui_restart.status()["exit_code"] is None
    try:
        ui_restart.start()
        raise AssertionError("second start must raise Conflict")
    except ui_restart.Conflict:
        pass
    assert wait_done()["exit_code"] == 0

    # failure is non-zero (make itself exits 2 when a recipe fails)
    makefile("exit 3")
    ui_restart.start()
    assert wait_done()["exit_code"] not in (None, 0)

    # the child runs in its own session
    pidfile = os.path.join(root, "pid")
    makefile(f"sleep 2 & echo $$! > {pidfile}; wait")
    ui_restart.start()
    for _ in range(50):
        if os.path.exists(pidfile) and open(pidfile).read().strip():
            break
        time.sleep(0.1)
    assert os.getsid(int(open(pidfile).read())) != os.getsid(0)
    wait_done()

    # a crashed run (log, no exit file) stops looking running after the age limit
    log, ex = ui_restart._paths()
    os.remove(ex)
    old = time.time() - ui_restart.STALE_S - 5
    os.utime(log, (old, old))
    assert ui_restart.status()["running"] is False
finally:
    shutil.rmtree(data, ignore_errors=True)
    shutil.rmtree(root, ignore_errors=True)

print("test_ui_restart: ok")
