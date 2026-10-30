"""Bootstrap runs: "Bootstrap repo" from the UI as a chain of one headless session per phase (PRD FR-11, FR-13, FR-14).

A run is `<data_dir>/bootstraps/<id>.json`. `tick()` moves each `running` run on from its phase session's end
state: a final message whose last line is `BOOTSTRAP: <phase> done #<issue>` (the phase the run expects) marks the
phase done and starts the next one (audit: `waiting`, docs: `done`); anything else stops the run at that phase.
Chain decisions are serialised per run (flock), so a double end event starts at most one session.
run state: running | waiting | stopped | done | ended. phase state: pending | running | done | failed.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone

import ui_panel
import ui_runner
import ui_sessions
from shared import atomic_write_text, data_dir, warn

PHASES = ("audit", "decide", "constitution", "guides", "gates", "docs")
OPEN_STATES = ("running", "waiting", "stopped")
TICK_SECONDS = 5
ATTACH_GRACE_SECONDS = 60  # a phase with no session yet is being started; after this the start is lost
FORMS = "accepted: (empty), audit, or <phase> <issue> with phase one of decide, constitution, guides, gates, docs and issue 123 or #123"
_LINE = re.compile(r"BOOTSTRAP: (\w+) done #(\d+)")
_ARGS = re.compile(r"(\w+)\s+#?(\d+)")


class Conflict(Exception):
    """The repo already has a run that is running, waiting or stopped (HTTP 409). `id`: that run;
    `session`: its current phase session, if any."""

    def __init__(self, message, id=None, session=None):
        super().__init__(message)
        self.id = id
        self.session = session


def _dir() -> str:
    p = os.path.join(data_dir(), "bootstraps")
    os.makedirs(p, exist_ok=True)
    return p


def _path(rid: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{12}", rid or ""):
        raise ValueError(f"bad bootstrap id: {rid!r}")
    return os.path.join(_dir(), rid + ".json")


@contextlib.contextmanager
def store_locked():
    """Store-wide lock: the one-run-per-repo check and the save are one step."""
    with open(os.path.join(_dir(), ".store.lock"), "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


@contextlib.contextmanager
def locked(rid: str):
    """Cross-process lock on one run. Not re-entrant."""
    with open(_path(rid)[:-5] + ".lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save(run: dict) -> None:
    run["updated_at"] = _now()
    atomic_write_text(_path(run["id"]), json.dumps(run, indent=1))


def load(rid: str):
    try:
        with open(_path(rid), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def list_all() -> list:
    out = []
    for name in sorted(os.listdir(_dir())):
        if name.endswith(".json"):
            try:
                out.append(load(name[:-5]))
            except (OSError, ValueError):
                continue
    return sorted((r for r in out if r), key=lambda r: r["created_at"], reverse=True)


def parse_input(args: str):
    """(phase, issue or None) from the Start input; ValueError (with the accepted forms) otherwise."""
    s = (args or "").strip()
    if s in ("", "audit"):
        return "audit", None
    m = _ARGS.fullmatch(s)
    if m and m.group(1) in PHASES[1:]:
        return m.group(1), int(m.group(2))
    raise ValueError(f"bad bootstrap input {s!r}; {FORMS}")


def phase_of(run: dict) -> str:
    """The phase the run is at: the first one not done."""
    return next((p["name"] for p in run["phases"] if p["state"] != "done"), PHASES[-1])


def _phase(run: dict, name: str) -> dict:
    return next(p for p in run["phases"] if p["name"] == name)


def _set_issue(run: dict, issue: int) -> None:
    run["issue"], run["branch"] = issue, f"bootstrap/{issue}"


def create(repo: str, phase: str, issue) -> dict:
    """A new `running` run starting at `phase`, earlier phases `done`. Conflict when `repo` has an open run."""
    with store_locked():
        for r in list_all():
            if r["repo"].lower() == repo.lower() and r["state"] in OPEN_STATES:
                cur = _phase(r, phase_of(r))
                raise Conflict(
                    f"a bootstrap run is already {r['state']} for {r['repo']} at {cur['name']} (run {r['id']})",
                    r["id"],
                    cur["session_id"]
                    or next((p["session_id"] for p in reversed(r["phases"]) if p["session_id"]), None),
                )
        at = PHASES.index(phase)
        run = {
            "id": secrets.token_hex(6),
            "repo": repo,
            "issue": None,
            "branch": None,
            "phases": [
                {"name": n, "session_id": None, "state": "done" if i < at else "running" if i == at else "pending"}
                for i, n in enumerate(PHASES)
            ],
            "state": "running",
            "error": None,
            "created_at": _now(),
        }
        if issue:
            _set_issue(run, issue)
        save(run)
    return run


def attach(rid: str, sid: str) -> None:
    """Link a session to the run's running phase (the start endpoint's side of `create`)."""
    with locked(rid):
        _attach(load(rid), sid)


def _attach(run: dict, sid: str) -> None:
    _phase(run, phase_of(run))["session_id"] = sid
    save(run)
    ui_sessions.update(sid, bootstrap=run["id"])


def discard(rid: str) -> None:
    """Delete a run whose first session never started."""
    with locked(rid):
        os.unlink(_path(rid))


def _session_of(run: dict):
    """The session record of the run's last session, for the account, model and effort the next one inherits."""
    sid = next((p["session_id"] for p in reversed(run["phases"]) if p["session_id"]), None)
    return ui_sessions.load(sid) if sid else None


def start_phase(run: dict, phase: str) -> dict:
    """Start `phase`'s session on the run's repo and link it. Call with the run's lock held and the phase `running`.
    Same account, model and effort as the session before it; its questions go to the Inbox."""
    prev = _session_of(run) or {}
    issue = run["issue"]
    owner, _, name = run["repo"].partition("/")
    rec = ui_runner.start(
        f"/repo-bootstrap {phase} {issue}" if issue else f"/repo-bootstrap {phase}",
        run["repo"],
        {"owner": owner, "repo": name, "issue": issue} if issue else None,
        gate_questions=True,
        claude_cmd=prev.get("claude_cmd"),
        run_model=prev.get("run_model"),
        effort=prev.get("run_effort"),
    )
    _attach(run, rec["id"])
    return rec


def parse_line(text: str, expect: str, issue=None):
    """The issue number of a last line `BOOTSTRAP: <expect> done #<n>` (n equal to `issue` when that is set), else None."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    m = _LINE.fullmatch(lines[-1]) if lines else None
    if not m or m.group(1) != expect or (issue is not None and int(m.group(2)) != issue):
        return None
    return int(m.group(2))


def _stop(run: dict, phase: dict, error: str) -> None:
    phase["state"], run["state"], run["error"] = "failed", "stopped", error
    save(run)


def _age(run: dict) -> float:
    return time.time() - datetime.fromisoformat(run["updated_at"]).timestamp()


def tick_one(rid: str) -> None:
    with locked(rid):
        run = load(rid)
        if not run or run["state"] != "running":
            return
        cur = _phase(run, phase_of(run))
        sid = cur["session_id"]
        if sid is None:  # being started right now, else the start was lost
            if _age(run) > ATTACH_GRACE_SECONDS:
                _stop(run, cur, "phase session is gone")
            return
        rec = ui_sessions.load(sid)
        if rec is None:
            return _stop(run, cur, "phase session is gone")
        status = rec.get("status")
        if status in ui_sessions._LIVE:
            return
        issue = parse_line(ui_panel.final_text(sid), cur["name"], run["issue"]) if status == "done" else None
        if issue is None:
            fallback = "phase session was stopped" if status == "stopped" else "phase ended without reporting done"
            return _stop(run, cur, rec.get("error") or fallback)
        cur["state"] = "done"
        if cur["name"] == "audit":
            _set_issue(run, issue)
            run["state"] = "waiting"
        elif cur["name"] == PHASES[-1]:
            run["state"] = "done"
        else:
            nxt = _phase(run, PHASES[PHASES.index(cur["name"]) + 1])
            nxt["state"] = "running"
        save(run)
        if run["state"] != "running":
            return
        try:
            start_phase(run, nxt["name"])
        except (ValueError, ui_runner.RunnerError, OSError) as e:
            _stop(run, nxt, f"could not start {nxt['name']}: {e}")


_lock = threading.Lock()


def tick() -> None:
    """One pass over every running run. One run's failure never stops the others."""
    with _lock:
        for run in list_all():
            if run["state"] != "running":
                continue
            try:
                tick_one(run["id"])
            except Exception as e:  # noqa: BLE001
                warn(f"bootstrap {run['id']}: tick failed: {e}")


def start_timer(interval: float = TICK_SECONDS) -> threading.Thread:
    def loop():
        while True:
            try:
                tick()
            except Exception as e:  # noqa: BLE001 - keep the timer alive
                warn(f"bootstrap timer tick failed: {e}")
            time.sleep(interval)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t
