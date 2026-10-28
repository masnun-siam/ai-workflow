"""Run the repo's `make restart` from the UI (Settings -> Server). Stdlib only.

The child is detached (own session), so it outlives the restart of this server (launchd or supervisord).
Its output goes to `<data_dir>/restart.log` and its exit code to `<data_dir>/restart.exit`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time

from shared import data_dir

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))  # plugin root
STALE_S = 600
TAIL_LINES = 40


class Conflict(Exception):
    pass


def _paths() -> tuple:
    d = data_dir()
    return os.path.join(d, "restart.log"), os.path.join(d, "restart.exit")


def available() -> bool:
    try:
        with open(os.path.join(ROOT, "Makefile")) as f:
            has_target = any(line.startswith("restart:") for line in f)
    except OSError:
        return False
    return has_target and shutil.which("make") is not None


def _running(log: str, exit_path: str) -> bool:
    # ponytail: a crashed run (no exit file) stops looking "running" after STALE_S; a pid check if that matters
    return os.path.exists(log) and not os.path.exists(exit_path) and time.time() - os.path.getmtime(log) < STALE_S


def status() -> dict:
    log, exit_path = _paths()
    code = None
    try:
        with open(exit_path) as f:
            code = int(f.read().strip())
    except (OSError, ValueError):
        pass
    try:
        with open(log, errors="replace") as f:
            tail = "".join(f.readlines()[-TAIL_LINES:])
    except OSError:
        tail = ""
    return {"available": available(), "running": _running(log, exit_path), "exit_code": code, "log_tail": tail}


def start() -> dict:
    if not available():
        raise ValueError("no `make restart` target in this install")
    log, exit_path = _paths()
    if _running(log, exit_path):
        raise Conflict("a restart is already running")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    for p in (log, exit_path):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    with open(log, "wb") as out:
        subprocess.Popen(
            ["sh", "-c", 'make restart; echo $? > "$1"', "sh", exit_path],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return {"ok": True}
