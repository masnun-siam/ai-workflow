"""UI headless runner: spawn `claude` detached and follow its stream into the session store.

The child gets its own session/process group (start_new_session) and writes straight to
<session_dir>/stream.jsonl and stderr.log, so it survives the starter. A daemon thread
polls stream.jsonl to fill session_id/cost and the final status. Issue #112; store: #105.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone

import ui_sessions
from dispatch import read_checkouts
from shared import data_dir, ledger_path, run_dir_for, warn

CLAUDE_ARGS = ["--print", "--output-format", "stream-json", "--verbose",
               "--dangerously-skip-permissions"]
STOP_GRACE_SECONDS = 10
POLL_SECONDS = 0.2

# In-process only: re-attach after a restart is out of scope here.
_procs: dict = {}
_stopping: set = set()
# ponytail: in-process lock, single UI server only; flock on the sessions dir if that changes
_resume_lock = threading.Lock()
CONTINUE_PROMPT = "Continue from where you were stopped."


class RunnerError(Exception):
    pass


class Conflict(Exception):
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


def _spawn(sid: str, argv: list, path: str, answer=None, resuming=False, **fields) -> dict:
    """Spawn claude detached, record pid/running, start the follower. Any failure -> _fail."""
    d = ui_sessions.session_dir(sid)
    stream_path = os.path.join(d, "stream.jsonl")
    try:
        offset = os.path.getsize(stream_path) if os.path.exists(stream_path) else 0
        with open(stream_path, "ab") as stream_f, open(os.path.join(d, "stderr.log"), "ab") as err_f:
            proc = subprocess.Popen(argv, cwd=path, stdin=subprocess.DEVNULL, stdout=stream_f,
                                    stderr=err_f, start_new_session=True, close_fds=True)
    except (OSError, ValueError) as e:
        _fail(sid, f"failed to spawn claude: {e}")
    rec = ui_sessions.update(sid, pid=proc.pid, status="running", **fields)
    _procs[sid] = proc
    threading.Thread(target=_follow, args=(sid, proc, offset, answer, resuming), daemon=True).start()
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
    return _spawn(sid, [exe, *CLAUDE_ARGS, command_text], path, cwd_path=path)


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
        return _fallback(sid, answer_text, f"cwd is not a directory: {repo!r}")
    exe = _preflight(sid)
    return _spawn(sid, [exe, *CLAUDE_ARGS, "--resume", rec["session_id"], answer_text], path,
                  answer=answer_text, ended_at=None, error=None, pending_answer=answer_text,
                  resumed_fresh=None, note=None, terminal_handoff=None)


def _issue_key(rec: dict):
    """(repo, issue number) of a /run-issue session, else None."""
    m = re.match(r"/(?:[\w-]+:)?run-issue\s+(.*)", rec.get("command") or "")
    n = re.search(r"(?:^|\s|/issues/)#?(\d+)(?=\s|$)", m.group(1)) if m else None
    return (rec.get("repo"), n.group(1)) if n else None


def _fallback(sid: str, answer, reason: str) -> dict:
    """A resume that could not start: re-enter a /run-issue run fresh from the Ledger, else hand off.

    Reads run.json leniently (shared.read_json would die()); never writes the Ledger.
    """
    rec = ui_sessions.load(sid) or {}
    repo = rec.get("repo")
    key = _issue_key(rec)
    checkouts = read_checkouts()
    path = checkouts.get(repo)
    if key and repo in checkouts and "/" in repo:
        run_json = ledger_path(run_dir_for(os.path.join(data_dir(), "runs"), repo, int(key[1])))
        if os.path.isfile(run_json):
            if not (isinstance(path, str) and os.path.isdir(path)):
                try:
                    with open(run_json, encoding="utf-8") as f:
                        ctx = json.load(f).get("context")
                    path = ctx.get("repo")
                except (OSError, ValueError, AttributeError):
                    path = None
            if isinstance(path, str) and os.path.isdir(path):
                old = rec.get("cwd_path")
                note = "resumed fresh from the Ledger: the previous claude session could not be resumed"
                if old and old != path:
                    note += f" (working directory changed from {old} to {path})"
                exe = _preflight(sid)
                return _spawn(sid, [exe, *CLAUDE_ARGS, f"/run-issue {key[1]}" + (f" {answer}" if answer else "")],
                              path, cwd_path=path, ended_at=None, error=None, resumed_fresh=True, note=note,
                              terminal_handoff=None, pending_answer=answer)
    ui_sessions.update(sid, status="failed", ended_at=_now(), pending_question=None,
                       terminal_handoff=True, pending_answer=answer,
                       error=f"cannot resume: {reason}")
    return ui_sessions.load(sid)


def _follow(sid: str, proc, offset: int = 0, answer=None, resuming=False) -> None:
    path = os.path.join(ui_sessions.session_dir(sid), "stream.jsonl")
    buf, is_error, saw_init, first_err = b"", False, False, None

    def handle(line: bytes) -> None:
        nonlocal is_error, saw_init, first_err
        try:
            ev = json.loads(line)
        except ValueError:
            return
        if not isinstance(ev, dict):
            return
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            saw_init = True
            ui_sessions.update(sid, session_id=ev.get("session_id"))
        elif ev.get("type") == "result":
            is_error = bool(ev.get("is_error"))
            if is_error and first_err is None:
                errs = ev.get("errors")
                first_err = str(errs[0]) if isinstance(errs, list) and errs else str(ev.get("result") or "claude reported an error")
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
            if (answer or resuming) and rc != 0 and not saw_init and first_err is not None:
                _fallback(sid, answer, first_err)  # resume itself failed; nothing was applied
            elif rc == 0 and not is_error:
                if status == "waiting":  # question recorded mid-run: stay waiting for the answer
                    ui_sessions.update(sid, ended_at=_now(), pending_answer=None)
                else:
                    ui_sessions.update(sid, status="done", ended_at=_now(), pending_answer=None)
            else:
                ui_sessions.update(sid, status="failed", ended_at=_now(), pending_question=None,
                                   error=f"claude exited with code {rc}; see stderr.log")
    except Exception as e:  # keep the daemon thread from dying silently
        warn(f"ui_runner follower for {sid} failed: {e}")
    finally:
        if _procs.get(sid) is proc:  # a fallback may have replaced it with a newer process
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
    proc = _procs.get(sid)
    if rec["status"] == "waiting" and (proc is None or proc.poll() is not None):
        return ui_sessions.update(sid, status="stopped", ended_at=_now(), pending_question=None)
    if rec["status"] not in ("starting", "running", "waiting") or not rec.get("pid"):
        return rec
    pgid = rec["pid"]
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
    if proc is None:
        _stopping.discard(sid)  # no follower in this process to clear it (e.g. after a UI restart)
    return ui_sessions.update(sid, status="stopped", ended_at=_now(), pending_question=None)


def resume_stopped(sid: str) -> dict:
    """Continue a stopped session via --resume (Ledger fallback if that fails); no answer is sent."""
    with _resume_lock:
        rec = ui_sessions.load(sid)
        if rec is None:
            raise FileNotFoundError(f"no such session: {sid}")
        if rec.get("status") != "stopped" or sid in _procs:
            raise Conflict("session is not stopped")
        key = _issue_key(rec)
        if key:
            for o in ui_sessions.list_sessions():
                if (o.get("id") != sid and _issue_key(o) == key
                        and o.get("status") in ("starting", "running", "waiting")):
                    raise Conflict(f"session {o['id']} is already live for this issue")
        # claim: makes double-submits safe; pid=None so a /stop during preflight can't kill the old group
        ui_sessions.update(sid, status="starting", pid=None)
        _stopping.discard(sid)
    if not rec.get("session_id"):
        return _fallback(sid, None, "no claude session_id")
    repo = rec.get("repo")
    path = read_checkouts().get(repo, repo)
    if not isinstance(path, str) or not os.path.isdir(path):
        return _fallback(sid, None, f"cwd is not a directory: {repo!r}")
    exe = _preflight(sid)
    return _spawn(sid, [exe, *CLAUDE_ARGS, "--resume", rec["session_id"], CONTINUE_PROMPT], path,
                  resuming=True, cwd_path=path, ended_at=None, error=None, pending_question=None,
                  resumed_fresh=None, note=None, terminal_handoff=None, pending_answer=None)
