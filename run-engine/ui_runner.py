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

HEADLESS_PROMPT = ("Headless run: ask via aiw ask, never AskUserQuestion. Gate questions go through "
                   "`aiw ask --json '<AskUserQuestion input>'`; then end your turn.")
CLAUDE_ARGS = ["--print", "--output-format", "stream-json", "--verbose",
               "--dangerously-skip-permissions", "--append-system-prompt", HEADLESS_PROMPT]
STOP_GRACE_SECONDS = 10
POLL_SECONDS = 0.2

# In-process only: re-attach after a restart is out of scope here.
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


def _spawn(sid: str, argv: list, path: str, **fields) -> dict:
    """Spawn claude detached, record pid/running, start the follower. Any failure -> _fail."""
    d = ui_sessions.session_dir(sid)
    stream_path = os.path.join(d, "stream.jsonl")
    try:
        offset = os.path.getsize(stream_path) if os.path.exists(stream_path) else 0
        with open(stream_path, "ab") as stream_f, open(os.path.join(d, "stderr.log"), "ab") as err_f:
            proc = subprocess.Popen(argv, cwd=path, stdin=subprocess.DEVNULL, stdout=stream_f,
                                    stderr=err_f, start_new_session=True, close_fds=True,
                                    env={**os.environ, "AIW_HEADLESS": "1", "AIW_UI_SESSION": sid})
    except (OSError, ValueError) as e:
        _fail(sid, f"failed to spawn claude: {e}")
    rec = ui_sessions.update(sid, pid=proc.pid, status="running", **fields)
    _procs[sid] = proc
    threading.Thread(target=_follow, args=(sid, proc, offset), daemon=True).start()
    return rec


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
    return _spawn(sid, [exe, *CLAUDE_ARGS, command_text], path)


def resume(sid: str, answer_text) -> dict:
    if not isinstance(answer_text, str) or not answer_text.strip():
        raise ValueError("answer_text must be a non-empty string")
    if answer_text.startswith("-"):
        raise ValueError("answer_text must not start with '-' (claude would parse it as a flag)")
    rec = ui_sessions.load(sid)
    if rec is None:
        raise FileNotFoundError(f"no such session: {sid}")
    if not rec.get("session_id"):
        _fail(sid, "cannot resume: session has no claude session_id")
    repo = rec.get("repo")
    path = read_checkouts().get(repo, repo)
    if not isinstance(path, str) or not os.path.isdir(path):
        _fail(sid, f"cannot resume: cwd is not a directory: {repo!r}")
    exe = _preflight(sid)
    return _spawn(sid, [exe, *CLAUDE_ARGS, "--resume", rec["session_id"], answer_text], path,
                  ended_at=None, error=None)


def _follow(sid: str, proc, offset: int = 0) -> None:
    path = os.path.join(ui_sessions.session_dir(sid), "stream.jsonl")
    buf, is_error, asked = b"", False, False

    def handle(line: bytes) -> None:
        nonlocal is_error, asked
        try:
            ev = json.loads(line)
        except ValueError:
            return
        if not isinstance(ev, dict):
            return
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            ui_sessions.update(sid, session_id=ev.get("session_id"))
        elif ev.get("type") == "assistant":
            msg = ev.get("message")
            for b in (msg.get("content") if isinstance(msg, dict) else None) or ():
                cmd = (b.get("input") or {}).get("command") if isinstance(b, dict) and b.get("name") == "Bash" else None
                if isinstance(cmd, str) and cmd.startswith("aiw ask"):
                    asked = True
        elif ev.get("type") == "result":
            is_error = bool(ev.get("is_error"))
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

    try:
        while proc.poll() is None:
            drain()
            time.sleep(POLL_SECONDS)
        drain()
        if buf.strip():
            handle(buf)  # final line without trailing newline
        rc = proc.returncode
        status = (ui_sessions.load(sid) or {}).get("status")
        if sid not in _stopping and status != "stopped":
            if rc == 0 and not is_error:
                if status == "waiting":  # question recorded mid-run: stay waiting for the answer
                    ui_sessions.update(sid, ended_at=_now())
                elif asked:  # model ran `aiw ask` but nothing was recorded: don't call it done
                    ui_sessions.update(sid, status="failed", ended_at=_now(),
                                       error="aiw ask ran but recorded no question; see stream.jsonl")
                else:
                    ui_sessions.update(sid, status="done", ended_at=_now())
            else:
                ui_sessions.update(sid, status="failed", ended_at=_now(), pending_question=None,
                                   error=f"claude exited with code {rc}; see stderr.log")
    except Exception as e:  # keep the daemon thread from dying silently
        warn(f"ui_runner follower for {sid} failed: {e}")
    finally:
        _procs.pop(sid, None)
        _stopping.discard(sid)


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
