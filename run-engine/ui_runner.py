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
import threading
import time
from datetime import datetime, timedelta, timezone

import ci
import review
import shared
import ui_sessions
import ui_settings
from dispatch import read_checkouts
from shared import data_dir, ledger_path, run_dir_for, warn
import ui_board
import ui_events

HEADLESS_PROMPT = ("Headless run: ask via aiw ask, never AskUserQuestion. Gate questions go through "
                   "`aiw ask --json '<AskUserQuestion input>'`; then end your turn. "
                   "When running /run-issue, skip phase 10 (grinding): the aiw ui starts it on request.")
# Sessions started from the guided Flow carry flow_id; skills read this line as their "Flow auto mode".
FLOW_PROMPT = ("Flow auto mode: this session is a step of the aiw ui guided Flow. Ask only grilling "
               "questions; settle every other choice yourself as the command's 'Flow auto mode' section says.")


def _system(rec) -> str:
    return HEADLESS_PROMPT + ("\n" + FLOW_PROMPT if (rec or {}).get("flow_id") else "")


MAX_GRINDS = 2  # grind rounds running at once; idle loops cost nothing
GRIND_PREFIX = "Start the review grind for PR "
CLAUDE_ARGS = ["--print", "--output-format", "stream-json", "--verbose",
               "--dangerously-skip-permissions"]
STOP_GRACE_SECONDS = 10
POLL_SECONDS = 0.2

# session id -> Popen for sessions started here; None for sessions re-attached by reconcile().
_procs: dict = {}
_stopping: set = set()
# ponytail: in-process lock, single UI server only; flock on the sessions dir if that changes
_resume_lock = threading.Lock()
CONTINUE_PROMPT = "Continue from where you were stopped."
LIMIT_BUFFER_SECONDS = 5
LIMIT_TICK_SECONDS = 30
_LIMIT_RE = re.compile(r"usage limit|limit reached|rate.?limit|hit your limit", re.I)
# claude command -> latest rate_limit_info warning seen. ponytail: in-memory, lost on restart
_usage: dict = {}


class RunnerError(Exception):
    pass


class Conflict(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fail(sid: str, msg: str):
    ui_sessions.update(sid, status="failed", error=msg, ended_at=_now())
    raise RunnerError(msg)


def _preflight(sid: str) -> list:
    """argv prefix of the session's bound claude command, after checking it is logged in."""
    cmd = (ui_sessions.load(sid) or {}).get("claude_cmd") or ui_settings.DEFAULT_CMD
    try:
        exe = ui_settings.argv(cmd)
    except ValueError as e:
        _fail(sid, f"claude command {cmd!r} unusable: {e}" if cmd != ui_settings.DEFAULT_CMD
              else "claude CLI not found on PATH")
    login_msg = (f"claude CLI is not logged in, run `{cmd} auth login`"
                 if cmd != ui_settings.DEFAULT_CMD else "claude CLI is not logged in, run `claude auth login`")
    try:
        p = subprocess.run([*exe, "auth", "status", "--json"], capture_output=True,
                           text=True, timeout=30)
        status = json.loads(p.stdout)
    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        _fail(sid, f"{login_msg} (auth status check failed: {e})")
    if not isinstance(status, dict) or status.get("loggedIn") is not True:
        _fail(sid, login_msg)
    return exe


_PS_ERROR = object()  # ps itself failed: liveness unknown, not 'no such process'


def _proc_start(pid):
    # ponytail: lstart has 1s resolution; a pid recycled within the same second looks the same
    try:
        p = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True,
                           text=True, timeout=5, env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired):
        return _PS_ERROR
    return (p.stdout.strip() or None) if p.returncode == 0 else None


def _spawn(sid: str, argv: list, path: str, answer=None, resuming=False, *, env_extra=None,
           pass_fds=(), **fields) -> dict:
    """Spawn claude detached, record pid/running, start the follower. Any failure -> _fail."""
    d = ui_sessions.session_dir(sid)
    stream_path = os.path.join(d, "stream.jsonl")
    try:
        offset = os.path.getsize(stream_path) if os.path.exists(stream_path) else 0
        with open(stream_path, "ab") as stream_f, open(os.path.join(d, "stderr.log"), "ab") as err_f:
            proc = subprocess.Popen(argv, cwd=path, stdin=subprocess.DEVNULL, stdout=stream_f,
                                    stderr=err_f, start_new_session=True, close_fds=True,
                                    env={**os.environ, "AIW_UI_SESSION": sid,
                                         "CLAUDE_PLUGIN_DATA": data_dir(), **(env_extra or {})},
                                    pass_fds=tuple(pass_fds))
    except (OSError, ValueError) as e:
        _fail(sid, f"failed to spawn claude: {e}")
    rec = ui_sessions.update(sid, pid=proc.pid, pid_started=_proc_start(proc.pid),
                             status="running", **fields)
    _procs[sid] = proc
    threading.Thread(target=_follow, args=(sid, proc, None, None, offset, answer, resuming),
                     daemon=True).start()
    return rec


def start(command_text, cwd, link=None, *, extra_args=(), env_extra=None, pass_fds=(),
          gate_questions=False, claude_cmd=None, flow_id=None) -> dict:
    if not isinstance(command_text, str) or not command_text.strip():
        raise ValueError("command_text must be a non-empty string")
    if command_text.startswith("-"):
        raise ValueError("command_text must not start with '-' (claude would parse it as a flag)")
    path = read_checkouts().get(cwd, cwd)
    if not isinstance(path, str) or not os.path.isdir(path):
        raise ValueError(f"cwd is not a directory or known checkout slug: {cwd!r}")

    claude_cmd = claude_cmd or ui_settings.default_cmd()
    sid = ui_sessions.create(command_text, cwd, link, claude_cmd=claude_cmd)["id"]
    if flow_id:
        ui_sessions.update(sid, flow_id=flow_id)
    until = limits().get(claude_cmd, {}).get("limited_until")
    if until and not (extra_args or env_extra or pass_fds):  # queue: the limit timer starts it at reset
        return ui_sessions.update(sid, status="limited", limit_resets_at=until, auto_resume=True,
                                  cwd_path=path, note="queued: account is rate limited")
    exe = _preflight(sid)
    gate = ["--append-system-prompt", _system({"flow_id": flow_id})] if gate_questions else []
    return _spawn(sid, [*exe, *CLAUDE_ARGS, *gate, *extra_args, command_text], path, cwd_path=path,
                  env_extra=env_extra, pass_fds=pass_fds)


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
    return _spawn(sid, [*exe, *CLAUDE_ARGS, "--append-system-prompt", _system(rec),
                  "--resume", rec["session_id"], answer_text], path,
                  answer=answer_text, ended_at=None, error=None, pending_answer=answer_text,
                  resumed_fresh=None, note=None, terminal_handoff=None)


MAX_CUSTOM_PROMPT = 4000


def send_prompt(sid: str, text) -> str:
    """A free-text prompt into a session: "sent" (resumed with it now) or "queued" (it goes out when the
    session ends, so a running station is never interrupted). Conflict when it cannot be taken."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("prompt must be a non-empty string")
    text = text.strip()
    if len(text) > MAX_CUSTOM_PROMPT or "\x00" in text or text.startswith("-"):
        raise ValueError(f"prompt must be at most {MAX_CUSTOM_PROMPT} characters, no NUL bytes, not starting with '-'")
    with _resume_lock:
        rec = ui_sessions.load(sid)
        if rec is None:
            raise FileNotFoundError(f"no such session: {sid}")
        status = rec.get("status")
        if status == "waiting":
            raise Conflict("answer the pending question first")
        if status in ("starting", "running", "limited"):
            ui_sessions.update(sid, queued_prompt=text)
            return "queued"
        if not rec.get("session_id"):
            raise Conflict("this session has no claude session id to resume")
        key = _issue_key(rec)
        for o in ui_sessions.list_sessions() if key else []:
            if o.get("id") != sid and _issue_key(o) == key and o.get("status") in ("starting", "running", "waiting"):
                raise Conflict(f"session {o['id']} is already live for this issue")
        ui_sessions.update(sid, status="starting", pid=None, queued_prompt=None)  # claim: double-submits are safe
    resume(sid, text)
    return "sent"


def _deliver_queued(sid: str) -> None:
    """The session just ended: send the prompt that was queued while it ran."""
    rec = ui_sessions.load(sid) or {}
    text = rec.get("queued_prompt")
    if not text or rec.get("status") not in ("done", "failed"):
        return
    ui_sessions.update(sid, queued_prompt=None)
    try:
        send_prompt(sid, text)
    except (ValueError, Conflict, RunnerError, OSError) as e:
        warn(f"queued prompt for {sid} not sent: {e}")
        ui_sessions.update(sid, note=f"queued prompt not sent: {e}")


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
                return _spawn(sid, [*exe, *CLAUDE_ARGS, "--append-system-prompt", HEADLESS_PROMPT, f"/run-issue {key[1]}" + (f" {answer}" if answer else "")],
                              path, cwd_path=path, ended_at=None, error=None, resumed_fresh=True, note=note,
                              terminal_handoff=None, pending_answer=answer)
    ui_sessions.update(sid, status="failed", ended_at=_now(), pending_question=None,
                       terminal_handoff=True, pending_answer=answer,
                       error=f"cannot resume: {reason}")
    return ui_sessions.load(sid)


def _follow(sid: str, proc, pid=None, started=None, offset: int = 0, answer=None,
            resuming=False) -> None:
    """Follow a session until it exits. proc is None for a re-attached (non-child) pid."""
    path = os.path.join(ui_sessions.session_dir(sid), "stream.jsonl")
    buf, is_error, saw_init, saw_result, first_err, asked = b"", False, False, False, None, False
    limit = None  # rate_limit_info of a rejected event
    cmd = (ui_sessions.load(sid) or {}).get("claude_cmd") or ui_settings.DEFAULT_CMD

    def handle(line: bytes) -> None:
        nonlocal is_error, saw_init, saw_result, first_err, asked, limit
        try:
            ev = json.loads(line)
        except ValueError:
            return
        if not isinstance(ev, dict):
            return
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            saw_init = True
            asked = False  # a new claude process: an earlier `aiw ask` was answered (or this is a replay after a UI restart)
            ui_sessions.update(sid, session_id=ev.get("session_id"))
        elif ev.get("type") == "assistant":
            asked = asked or any(
                e["kind"] == "tool" and e["name"] == "Bash" and isinstance(e["input"], dict)
                and str(e["input"].get("command", "")).lstrip().startswith("aiw ask")
                for e in ui_events.parse_line(line))
        elif ev.get("type") == "rate_limit_event" and isinstance(ev.get("rate_limit_info"), dict):
            info = ev["rate_limit_info"]
            _usage[cmd] = info
            if info.get("status") not in (None, "allowed", "allowed_warning"):
                limit = info
        elif ev.get("type") == "result":
            is_error, saw_result = bool(ev.get("is_error")), True
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

    ps_errors = [0]

    def alive() -> bool:
        # ponytail: one ps per tick per re-attached session; fine for a handful
        if proc is not None:
            return proc.poll() is None
        if not started:
            return False
        cur = _proc_start(pid)
        if cur is _PS_ERROR:  # transient ps failure: keep following, bounded
            ps_errors[0] += 1
            return ps_errors[0] <= 25
        ps_errors[0] = 0
        return cur == started

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
        status = (ui_sessions.load(sid) or {}).get("status")
        if sid not in _stopping and status != "stopped":
            if is_error and (limit or _LIMIT_RE.search(first_err or "")):
                _mark_limited(sid, limit, first_err)
            elif (answer or resuming) and rc != 0 and not saw_init and first_err is not None:
                _fallback(sid, answer, first_err)  # resume itself failed; nothing was applied
            elif proc is None and not (saw_result and not is_error):
                ui_sessions.update(sid, status="failed", ended_at=_now(), pending_question=None,
                                   error="claude exited while the UI was down without a "
                                         "successful result; see stderr.log")
            elif (rc == 0 or proc is None) and not is_error:
                if status == "waiting":  # question recorded mid-run: stay waiting for the answer
                    ui_sessions.update(sid, ended_at=_now(), pending_answer=None)
                elif asked:  # model ran `aiw ask` but nothing was recorded: don't call it done
                    ui_sessions.update(sid, status="failed", ended_at=_now(),
                                       error="aiw ask ran but recorded no question; see stream.jsonl")
                else:
                    ui_sessions.update(sid, status="done", ended_at=_now(), pending_answer=None)
            else:
                ui_sessions.update(sid, status="failed", ended_at=_now(), pending_question=None,
                                   error=f"claude exited with code {rc}; see stderr.log")
            _deliver_queued(sid)
    except Exception as e:  # keep the daemon thread from dying silently
        warn(f"ui_runner follower for {sid} failed: {e}")
    finally:
        if _procs.get(sid) is proc:  # a fallback may have replaced it with a newer process
            _procs.pop(sid, None)
            _stopping.discard(sid)


def _mark_limited(sid: str, info, err) -> None:
    resets = (info or {}).get("resetsAt")
    resets = int(resets) if isinstance(resets, (int, float)) and not isinstance(resets, bool) else None
    ui_sessions.update(sid, status="limited", pending_question=None, error=err, ended_at=None,
                       limit_resets_at=resets, limit_type=(info or {}).get("rateLimitType"),
                       auto_resume=resets is not None)


def limits(now=None) -> dict:
    """{claude command: {limited_until, warning}} for the UI header chips."""
    now = now or time.time()
    out: dict = {}
    for rec in ui_sessions.list_sessions():
        until = rec.get("limit_resets_at")
        if rec.get("status") == "limited" and until and until > now:
            e = out.setdefault(rec.get("claude_cmd") or ui_settings.DEFAULT_CMD, {})
            e["limited_until"] = max(until, e.get("limited_until", 0))
    for cmd, info in list(_usage.items()):
        if info.get("status") == "allowed_warning" and (info.get("resetsAt") or 0) > now:
            out.setdefault(cmd, {})["warning"] = {"type": info.get("rateLimitType"),
                                                 "utilization": info.get("utilization")}
    return out


def _copy_transcript(rec: dict, path: str, new_cmd: str) -> None:
    """Make a session resumable under another account: copy its jsonl into that profile."""
    old = ui_settings.config_dir(rec.get("claude_cmd") or ui_settings.DEFAULT_CMD)
    new = ui_settings.config_dir(new_cmd)
    if old == new:
        return
    slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(path))
    src = os.path.join(old, "projects", slug, f"{rec['session_id']}.jsonl")
    if not os.path.isfile(src):
        raise Conflict(f"transcript not found at {src}")
    dst_dir = os.path.join(new, "projects", slug)
    os.makedirs(dst_dir, exist_ok=True)
    shutil.copyfile(src, os.path.join(dst_dir, os.path.basename(src)))


def cancel_auto(sid: str) -> dict:
    rec = ui_sessions.load(sid)
    if rec is None:
        raise FileNotFoundError(f"no such session: {sid}")
    if rec.get("status") != "limited":
        raise Conflict("session is not limited")
    return ui_sessions.update(sid, auto_resume=False)


def limit_tick(now=None, stagger=2) -> list:
    """Resume every auto-resume limited session whose limit has reset."""
    now = now or time.time()
    out = []
    for rec in ui_sessions.list_sessions():
        until = rec.get("limit_resets_at")
        if rec.get("status") == "limited" and rec.get("auto_resume") and until \
                and until + LIMIT_BUFFER_SECONDS <= now:
            try:
                resume_stopped(rec["id"])
                out.append(rec["id"])
            except (Conflict, RunnerError, FileNotFoundError, OSError) as e:
                warn(f"limit auto-resume of {rec['id']} failed: {e}")
            time.sleep(stagger)
    return out


def start_limit_timer(interval=LIMIT_TICK_SECONDS) -> threading.Thread:
    """First tick runs at once, so limits that reset while the UI was down catch up on startup."""
    def loop():
        while True:
            try:
                limit_tick()
            except Exception as e:  # noqa: BLE001 - keep the timer alive
                warn(f"limit timer tick failed: {e}")
            time.sleep(interval)
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t


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
    proc = _procs.get(sid)
    if rec["status"] == "limited":
        return ui_sessions.update(sid, status="stopped", ended_at=_now(), auto_resume=False)
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


def resume_stopped(sid: str, claude_cmd=None) -> dict:
    """Continue a stopped, limited or failed session via --resume (Ledger fallback if that fails).

    A limited session resumes with its unanswered answer, if any; claude_cmd rebinds it to another
    account first (its transcript is copied into that account's config dir).
    """
    with _resume_lock:
        rec = ui_sessions.load(sid)
        if rec is None:
            raise FileNotFoundError(f"no such session: {sid}")
        if rec.get("status") not in ("stopped", "limited", "failed") or sid in _procs:
            raise Conflict("session is not stopped, limited or failed")
        key = _issue_key(rec)
        if key:
            for o in ui_sessions.list_sessions():
                if (o.get("id") != sid and _issue_key(o) == key
                        and o.get("status") in ("starting", "running", "waiting")):
                    raise Conflict(f"session {o['id']} is already live for this issue")
        repo = rec.get("repo")
        path = read_checkouts().get(repo, repo)
        rebind = {}
        if claude_cmd and claude_cmd != rec.get("claude_cmd"):
            if rec.get("session_id") and isinstance(path, str) and os.path.isdir(path):
                _copy_transcript(rec, path, claude_cmd)
            rebind = {"claude_cmd": claude_cmd}
        # claim: makes double-submits safe; pid=None so a /stop during preflight can't kill the old group
        ui_sessions.update(sid, status="starting", pid=None, limit_resets_at=None, limit_type=None,
                           auto_resume=None, **rebind)
        _stopping.discard(sid)
    prompt = (rec.get("pending_answer") if rec.get("status") == "limited" else None) or CONTINUE_PROMPT
    if not isinstance(path, str) or not os.path.isdir(path):
        return _fallback(sid, None, f"cwd is not a directory: {repo!r}")
    if not rec.get("session_id"):
        if rec.get("status") == "limited":  # limited before claude ever reported a session: start over
            exe = _preflight(sid)
            return _spawn(sid, [*exe, *CLAUDE_ARGS, "--append-system-prompt", _system(rec), rec["command"]], path, cwd_path=path,
                          ended_at=None, error=None)
        return _fallback(sid, None, "no claude session_id")
    exe = _preflight(sid)
    return _spawn(sid, [*exe, *CLAUDE_ARGS, "--append-system-prompt", _system(rec),
                  "--resume", rec["session_id"], prompt], path,
                  resuming=True, cwd_path=path, ended_at=None, error=None, pending_question=None,
                  resumed_fresh=None, note=None, terminal_handoff=None, pending_answer=None)


# ---- pr-grind headless re-entry (ADR 0002, #127) ----------------------------------------
# Stateless tick: every decision is re-derived from the state-file header, so a restarted
# `aiw ui` just resumes. The flock on <state>.lock is inherited by the round's child, so the
# lock lives exactly as long as the round does.

PRGRIND_HEARTBEAT = 1500
PRGRIND_TICK_SECONDS = 60
REENTRY_PROMPT = (
    "This is an automated headless pr-grind re-entry from the aiw ui timer. Take the On-wake "
    "branch, never clear `paused:`, never call ScheduleWakeup or Monitor, follow the headless "
    "steps in SKILL.md, then exit. A stop that needs a human decision is asked through `aiw ask` "
    "as Step 8 says; any other stop stays a plain paused stop."
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


_DONE_LINE = re.compile(r"done: \d{4}-\d\d-\d\dT")


def _header(path: str) -> dict:
    out = {}
    lines = _read_lines(path)
    end = _header_end(lines)
    for ln in lines[:end]:
        k, sep, v = ln.partition(": ")
        if sep:
            out.setdefault(k, v.strip())
    # The skill sometimes ends a loop with `done: <ISO8601> — <reason>` under its last `## Round` instead of in
    # the header. It is terminal and never reverts, so honour it wherever it is (a stray one would restart a
    # finished loop forever).
    for ln in lines[end:]:
        if _DONE_LINE.match(ln):
            out.setdefault("done", ln[len("done: "):].strip())
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
    shared.atomic_write_text(path, "\n".join(lines))


def _iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _valid(h: dict) -> bool:
    for k in ("owner", "repo"):
        v = h.get(k, "")
        if not _NAME_RE.fullmatch(v) or ".." in v or v == ".":
            return False
    # thread is the Slack thread URL (pr-grind's argument): any safe https URL, no argv injection.
    return (re.fullmatch(r"[0-9]+", h.get("number", "")) is not None
            and re.fullmatch(r"https://[^\s\x00-\x1f\x7f-][^\s\x00-\x1f\x7f]*",
                             h.get("thread", "")) is not None)


def _live(rec) -> bool:
    return (rec.get("status") in ("starting", "running") and bool(rec.get("pid"))
            and not _group_gone(rec["pid"], None))


def _new_review(h: dict, now) -> str | None:
    login, mode = (h["author"], "not-author") if h.get("reviewer", "UNRESOLVED") == "UNRESOLVED" \
        else (h["reviewer"], "reviewer")
    p = shared.run(["bash", _POLL_SH, h["owner"], h["repo"], h["number"], login,
                    h.get("poll-since") or _iso(now), mode, "once"], timeout=120)
    if p.returncode != 0:
        raise RuntimeError(f"poll-reviews.sh exited {p.returncode}: {(p.stdout or '')[-200:].strip()}")
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
        h = _header(path)  # re-read under the lock: a round may have written paused/done meanwhile
        if "paused" in h:
            return "paused"
        if "done" in h:
            return "done"
        slug = f"{h['owner']}/{h['repo']}"
        pr_url = f"https://github.com/{slug}/pull/{h['number']}"
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
                due = review._ts(h["next-poll"]) <= now
            except TypeError:
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

        # a grind begun inside /run-issue has no /pr-grind session: take the checkout from any session on this repo
        same = recs or [r for r in ui_sessions.list_sessions()
                        if isinstance(r.get("link"), dict)
                        and (r["link"].get("owner", "").lower(), r["link"].get("repo", "").lower()) == (h["owner"].lower(), h["repo"].lower())]
        cwd = next((r["repo"] for r in same if r.get("repo")), None)
        if cwd is None:
            warn(f"pr-grind tick: no prior session to take a cwd from for {thread}")
            return "invalid"
        if grind_live() >= MAX_GRINDS:
            return "queued"  # next-poll is untouched, so the next tick retries
        _set_header(path, "next-poll", _iso(now + timedelta(seconds=PRGRIND_HEARTBEAT)))
        try:
            issue = ui_board.issue_for_pr(pr_url)  # a link naming the issue puts the round in that run's Sessions tab
            start(cmd, cwd, link={"owner": h["owner"], "repo": h["repo"], "issue": issue} if issue else pr_url, extra_args=["--append-system-prompt", REENTRY_PROMPT],
                  env_extra={"AIW_HEADLESS": "1"}, pass_fds=[lock.fileno()],
                  claude_cmd=next((r["claude_cmd"] for r in same if r.get("claude_cmd")), None))
        except (RunnerError, ValueError) as e:
            warn(f"pr-grind tick: could not start round for {thread}: {e}")
            return "error"
        return "started"
    finally:
        lock.close()


def grind_live() -> int:
    """Grind sessions running right now (a first-grind session or a /pr-grind round)."""
    return sum(1 for r in ui_sessions.list_sessions()
               if str(r.get("command", "")).startswith(("/pr-grind ", GRIND_PREFIX)) and _live(r))


def grinding() -> set:
    """(owner, repo, pr number) of every pr-grind loop that is neither paused nor done."""
    out = set()
    for path in glob.glob(os.path.join(_prgrind_dir(), "*.md")):
        try:
            h = _header(path)
        except OSError:
            continue
        if _valid(h) and "paused" not in h and "done" not in h:
            out.add((h["owner"].lower(), h["repo"].lower(), int(h["number"])))
    return out


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
