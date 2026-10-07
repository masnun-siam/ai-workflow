"""UI headless runner: spawn `claude` detached and follow its stream into the session store.

The child gets its own session/process group (start_new_session) and writes straight to
<session_dir>/stream.jsonl and stderr.log, so it survives the starter. A daemon thread
polls stream.jsonl to fill session_id/cost and the final status. Issue #112; store: #105.
"""

from __future__ import annotations

import fcntl
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone

import ci
import shared
import ui_sessions
from dispatch import read_checkouts
from shared import warn

CLAUDE_ARGS = ["--print", "--output-format", "stream-json", "--verbose",
               "--dangerously-skip-permissions"]
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


def start(command_text, cwd, link=None, *, extra_args=(), env_extra=None, pass_fds=()) -> dict:
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
            proc = subprocess.Popen([exe, *CLAUDE_ARGS, *extra_args, command_text], cwd=path,
                                    stdin=subprocess.DEVNULL, stdout=stream_f, stderr=err_f,
                                    env={**os.environ, **env_extra} if env_extra else None,
                                    start_new_session=True, close_fds=True,
                                    pass_fds=tuple(pass_fds))
        except OSError as e:
            _fail(sid, f"failed to spawn claude: {e}")
        finally:
            err_f.close()
    finally:
        stream_f.close()
    rec = ui_sessions.update(sid, pid=proc.pid, status="running")
    _procs[sid] = proc
    threading.Thread(target=_follow, args=(sid, proc), daemon=True).start()
    return rec


def _follow(sid: str, proc) -> None:
    path = os.path.join(ui_sessions.session_dir(sid), "stream.jsonl")
    offset, buf, is_error = 0, b"", False

    def handle(line: bytes) -> None:
        nonlocal is_error
        try:
            ev = json.loads(line)
        except ValueError:
            return
        if not isinstance(ev, dict):
            return
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            ui_sessions.update(sid, session_id=ev.get("session_id"))
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
        if sid not in _stopping and (ui_sessions.load(sid) or {}).get("status") != "stopped":
            if rc == 0 and not is_error:
                ui_sessions.update(sid, status="done", ended_at=_now())
            else:
                ui_sessions.update(sid, status="failed", ended_at=_now(),
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


# ---- pr-grind headless re-entry (ADR 0002, #127) ----------------------------------------
# Stateless tick: every decision is re-derived from the state-file header, so a restarted
# `aiw ui` just resumes. The flock on <state>.lock is inherited by the round's child, so the
# lock lives exactly as long as the round does.

PRGRIND_HEARTBEAT = 1500
PRGRIND_TICK_SECONDS = 60
REENTRY_PROMPT = (
    "This is an automated headless pr-grind re-entry from the aiw ui timer. Take the On-wake "
    "branch, never clear `paused:`, never call ScheduleWakeup or Monitor, follow the headless "
    "steps in SKILL.md, then exit."
)
_NAME_RE = re.compile(r"[A-Za-z0-9_.-]+")
_POLL_SH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "skills", "pr-grind", "scripts", "poll-reviews.sh")


def _prgrind_dir() -> str:
    return os.path.join(shared.data_dir(), "pr-grind")


def _read_lines(path: str) -> list:
    with open(path, encoding="utf-8", newline="") as f:
        return f.read().split("\n")


def _header_end(lines: list) -> int:
    return next((i for i, ln in enumerate(lines) if ln.startswith("## ")), len(lines))


def _header(path: str) -> dict:
    out = {}
    for ln in _read_lines(path)[:_header_end(_read_lines(path))]:
        k, sep, v = ln.partition(": ")
        if sep:
            out.setdefault(k, v.strip())
    return out


def _set_header(path: str, key: str, value) -> None:
    lines = _read_lines(path)
    end = _header_end(lines)
    idx = next((i for i in range(end) if lines[i].startswith(key + ": ")), None)
    new = None if value is None else f"{key}: {value}"
    if idx is not None:
        if new is None:
            del lines[idx]
        else:
            lines[idx] = new
    elif new is not None:
        last = max((i for i in range(end) if ": " in lines[i]), default=-1)
        lines.insert(last + 1, new)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(lines))
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s):
    dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _valid(h: dict) -> bool:
    for k in ("owner", "repo"):
        v = h.get(k, "")
        if not _NAME_RE.fullmatch(v) or ".." in v or v == ".":
            return False
    return (re.fullmatch(r"[0-9]+", h.get("number", "")) is not None
            and re.fullmatch(r"https://[A-Za-z0-9.-]+/%s/%s/pull/%s" % (
                re.escape(h["owner"]), re.escape(h["repo"]), h["number"]),
                h.get("thread", "")) is not None)


def _live(rec) -> bool:
    return (rec.get("status") in ("starting", "running") and bool(rec.get("pid"))
            and not _group_gone(rec["pid"], None))


def _new_review(h: dict, now) -> str | None:
    login, mode = (h["author"], "not-author") if h.get("reviewer", "UNRESOLVED") == "UNRESOLVED" \
        else (h["reviewer"], "reviewer")
    p = shared.run(["bash", _POLL_SH, h["owner"], h["repo"], h["number"], login,
                    h.get("poll-since") or _iso(now), mode, "once"], timeout=120)
    dates = sorted(ln.split()[0] for ln in (p.stdout or "").splitlines()
                   if ln.startswith("20"))
    return dates[-1] if dates else None


def prgrind_tick(path: str, now=None) -> str:
    now = now or datetime.now(timezone.utc)
    h = _header(path)
    if not _valid(h):
        warn(f"pr-grind tick: invalid state header in {path}")
        return "invalid"
    if "paused" in h:
        return "paused"
    if "done" in h:
        return "done"
    thread, cmd = h["thread"], f"/pr-grind {h['thread']}"
    recs = [r for r in ui_sessions.list_sessions() if r.get("command") == cmd]
    if any(_live(r) for r in recs):
        return "busy"
    lock = open(path[:-3] + ".lock", "a")
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "locked"
        slug = f"{h['owner']}/{h['repo']}"
        view, _ = shared.gh_json(["pr", "view", h["number"], "--repo", slug, "--json", "state"])
        if not isinstance(view, dict):
            warn(f"pr-grind tick: gh pr view failed for {slug}#{h['number']}")
            return "error"
        state = str(view.get("state", "")).upper()
        if state in ("MERGED", "CLOSED"):
            _set_header(path, "done", f"{_iso(now)} \u2014 {state.lower()}")
            return "done"

        due = True
        if "next-poll" in h:
            try:
                due = _parse_iso(h["next-poll"]) <= now
            except ValueError:
                warn(f"pr-grind tick: unparseable next-poll {h['next-poll']!r} in {path}")
        trigger = due
        try:
            newest = _new_review(h, now)
            if newest:
                _set_header(path, "poll-since", newest)
                trigger = True
            elif "poll-since" not in h:
                _set_header(path, "poll-since", _iso(now))
        except Exception as e:  # noqa: BLE001 - a broken trigger must not stop the heartbeat
            warn(f"pr-grind tick: review check failed: {e}")
        try:
            snap = ci.snapshot(h["owner"], h["repo"], int(h["number"]))
            seen = f"{snap['head_sha']} {snap['state']}"
            if "ci-seen" not in h:
                _set_header(path, "ci-seen", seen)
            elif h["ci-seen"] != seen:
                _set_header(path, "ci-seen", seen)
                trigger = True
        except Exception as e:  # noqa: BLE001
            warn(f"pr-grind tick: ci check failed: {e}")
        if not trigger:
            return "idle"

        cwd = next((r["repo"] for r in recs if r.get("repo")), None)
        if cwd is None:
            warn(f"pr-grind tick: no prior session to take a cwd from for {thread}")
            return "invalid"
        _set_header(path, "next-poll", _iso(now + timedelta(seconds=PRGRIND_HEARTBEAT)))
        try:
            start(cmd, cwd, link=thread, extra_args=["--append-system-prompt", REENTRY_PROMPT],
                  env_extra={"AIW_HEADLESS": "1"}, pass_fds=[lock.fileno()])
        except (RunnerError, ValueError) as e:
            warn(f"pr-grind tick: could not start round for {thread}: {e}")
            return "error"
        return "started"
    finally:
        lock.close()


def prgrind_tick_all(now=None) -> list:
    out = []
    for path in sorted(glob.glob(os.path.join(_prgrind_dir(), "*.md"))):
        try:
            h = _header(path)
            if "next-poll" not in h or "paused" in h or "done" in h:
                continue
            out.append((path, prgrind_tick(path, now=now)))
        except Exception as e:  # noqa: BLE001 - one bad file must not kill the timer
            warn(f"pr-grind tick failed for {path}: {e}")
    return out


def start_prgrind_timer(interval=PRGRIND_TICK_SECONDS) -> threading.Thread:
    def loop():
        while True:
            prgrind_tick_all()
            time.sleep(interval)
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t
