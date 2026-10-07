"""UI headless runner: spawn `claude` detached and follow its stream into the session store.

The child gets its own session/process group (start_new_session) and writes straight to
<session_dir>/stream.jsonl and stderr.log, so it survives the starter. A daemon thread
polls stream.jsonl to fill session_id/cost and the final status. Issue #112; store: #105.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone

import ui_sessions
from dispatch import read_checkouts
from shared import warn

CLAUDE_ARGS = ["--print", "--output-format", "stream-json", "--verbose",
               "--dangerously-skip-permissions"]
STOP_GRACE_SECONDS = 10
POLL_SECONDS = 0.2

# pid -> Popen for sessions started here; None for sessions re-attached by reconcile().
_procs: dict = {}
_stopping: set = set()


class RunnerError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fail(sid: str, msg: str):
    ui_sessions.update(sid, status="failed", error=msg, ended_at=_now())
    raise RunnerError(msg)


def _preflight(sid: str) -> str:
    exe = shutil.which("claude")
    if exe is None:
        _fail(sid, "claude CLI not found on PATH")
    login_msg = "claude CLI is not logged in, run `claude auth login`"
    try:
        p = subprocess.run([exe, "auth", "status", "--json"], capture_output=True,
                           text=True, timeout=30)
        status = json.loads(p.stdout)
    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        _fail(sid, f"{login_msg} (auth status check failed: {e})")
    if not isinstance(status, dict) or status.get("loggedIn") is not True:
        _fail(sid, login_msg)
    return exe


def _proc_start(pid) -> str | None:
    # ponytail: lstart has 1s resolution; a pid recycled within the same second looks the same
    try:
        p = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True,
                           text=True, timeout=5, env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (p.stdout.strip() or None) if p.returncode == 0 else None


def start(command_text, cwd, link=None) -> dict:
    if not isinstance(command_text, str) or not command_text.strip():
        raise ValueError("command_text must be a non-empty string")
    if command_text.startswith("-"):
        raise ValueError("command_text must not start with '-' (claude would parse it as a flag)")
    path = read_checkouts().get(cwd, cwd)
    if not isinstance(path, str) or not os.path.isdir(path):
        raise ValueError(f"cwd is not a directory or known checkout slug: {cwd!r}")

    sid = ui_sessions.create(command_text, cwd, link)["id"]
    exe = _preflight(sid)
    d = ui_sessions.session_dir(sid)
    stream_f = open(os.path.join(d, "stream.jsonl"), "ab")
    try:
        err_f = open(os.path.join(d, "stderr.log"), "ab")
        try:
            proc = subprocess.Popen([exe, *CLAUDE_ARGS, command_text], cwd=path,
                                    stdin=subprocess.DEVNULL, stdout=stream_f, stderr=err_f,
                                    start_new_session=True, close_fds=True)
        except OSError as e:
            _fail(sid, f"failed to spawn claude: {e}")
        finally:
            err_f.close()
    finally:
        stream_f.close()
    rec = ui_sessions.update(sid, pid=proc.pid, pid_started=_proc_start(proc.pid),
                            status="running")
    _procs[sid] = proc
    threading.Thread(target=_follow, args=(sid, proc), daemon=True).start()
    return rec


def _follow(sid: str, proc, pid=None, started=None) -> None:
    """Follow a session until it exits. proc is None for a re-attached (non-child) pid."""
    path = os.path.join(ui_sessions.session_dir(sid), "stream.jsonl")
    offset, buf, is_error, saw_result = 0, b"", False, False

    def handle(line: bytes) -> None:
        nonlocal is_error, saw_result
        try:
            ev = json.loads(line)
        except ValueError:
            return
        if not isinstance(ev, dict):
            return
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            ui_sessions.update(sid, session_id=ev.get("session_id"))
        elif ev.get("type") == "result":
            is_error, saw_result = bool(ev.get("is_error")), True
            ui_sessions.update(sid, cost=ev.get("total_cost_usd"))

    def drain() -> None:
        nonlocal offset, buf
        with open(path, "rb") as f:
            f.seek(offset)
            chunk = f.read()
        offset += len(chunk)
        *whole, buf = (buf + chunk).split(b"\n")
        for line in whole:
            handle(line)

    def alive() -> bool:
        # ponytail: one ps per tick per re-attached session; fine for a handful
        return proc.poll() is None if proc is not None else _proc_start(pid) == started

    try:
        while alive():
            drain()
            time.sleep(POLL_SECONDS)
        try:
            drain()
        except FileNotFoundError:
            if proc is not None:
                raise  # re-attached sessions may legitimately have no stream
        if buf.strip():
            handle(buf)  # final line without trailing newline
        rc = proc.returncode if proc is not None else None
        if sid not in _stopping and (ui_sessions.load(sid) or {}).get("status") != "stopped":
            if proc is None and not (saw_result and not is_error):
                ui_sessions.update(sid, status="failed", ended_at=_now(),
                                   error="claude exited while the UI was down without a "
                                         "successful result; see stderr.log")
            elif (rc == 0 or proc is None) and not is_error:
                ui_sessions.update(sid, status="done", ended_at=_now())
            else:
                ui_sessions.update(sid, status="failed", ended_at=_now(),
                                   error=f"claude exited with code {rc}; see stderr.log")
    except Exception as e:  # keep the daemon thread from dying silently
        warn(f"ui_runner follower for {sid} failed: {e}")
    finally:
        _procs.pop(sid, None)
        _stopping.discard(sid)


def reconcile() -> None:
    """Call once at UI startup: re-attach live sessions, close the ones that died meanwhile."""
    for rec in ui_sessions.list_sessions():
        sid = rec["id"]
        try:
            if rec.get("status") not in ("starting", "running") or sid in _procs:
                continue
            pid, started = rec.get("pid"), rec.get("pid_started")
            if not pid:
                ui_sessions.update(sid, status="failed", ended_at=_now(),
                                   error="session never started (UI exited before spawn)")
            elif started and _proc_start(pid) == started:
                # ponytail: _procs check-and-set is unlocked; reconcile is startup-only
                _procs[sid] = None
                threading.Thread(target=_follow, args=(sid, None, pid, started),
                                 daemon=True).start()
            else:
                _follow(sid, None, pid, started)  # not ours/dead: loop exits, closes from stream
        except Exception as e:
            warn(f"ui_runner reconcile of {sid} failed: {e}")


def _group_gone(pgid: int, proc) -> bool:
    if proc is not None:
        proc.poll()  # reap the zombie leader so killpg(0) can report the group gone
    try:
        os.killpg(pgid, 0)
        return False
    except (ProcessLookupError, PermissionError):
        return True  # PermissionError: pid reused by another user's group, not ours


def stop(sid: str) -> dict:
    rec = ui_sessions.load(sid)
    if rec is None:
        raise FileNotFoundError(f"no such session: {sid}")
    if rec["status"] not in ("starting", "running") or not rec.get("pid"):
        return rec
    pgid, proc = rec["pid"], _procs.get(sid)
    if proc is not None and proc.poll() is not None:
        return rec  # already exited: let the follower record done/failed
    _stopping.add(sid)
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    deadline = time.time() + STOP_GRACE_SECONDS
    while not _group_gone(pgid, proc) and time.time() < deadline:
        time.sleep(0.05)
    if not _group_gone(pgid, proc):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        end = time.time() + 2
        while not _group_gone(pgid, proc) and time.time() < end:
            time.sleep(0.05)
    return ui_sessions.update(sid, status="stopped", ended_at=_now())
