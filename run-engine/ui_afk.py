"""AFK mode (issue #178): a timed autopilot run by the server, so it works with no browser open.

While it runs, each tick:
- answers every `aiw ask` round whose questions all carry a "(Recommended)" option, through the
  same claim + resume path as the answer page (rounds with any other question are held);
- sends "Skip CI for now" to a grind paused on CI, at most once per PR per window;
- retries sessions that failed during the window on a 2m/10m/30m/1h backoff, then holds them.
When the window ends (expiry or "I'm back") one ntfy push sums it up and the UI shows the log.

State: <data_dir>/afk.json {started, until, skipped_ci, log, ended, held_at_end, dismissed}.
Retry bookkeeping lives on the session record: afk_retries, afk_retry_at, afk_retry_for.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime

import shared
import ui_board
import ui_grind
import ui_notify
import ui_runner
import ui_sessions
import ui_status
from shared import warn

MAX_SECONDS = 24 * 3600  # "until HH:MM" may roll into tomorrow; never longer than a day
RETRY_DELAYS = (120, 600, 1800, 3600)
MAX_LOG = 500
TICK_SECONDS = 5
SKIP_CI_REPLY = "Skip CI for now, complete the grind, then come back and fix the CI"  # keep in step with ui_static/run.js
_CI_REASON = re.compile(r"\b(ci|gate\s*2|checks?)\b", re.I)  # same test as pausedOnCi in ui_static/run.js
_lock = threading.Lock()


def _path() -> str:
    return os.path.join(shared.data_dir(), "afk.json")


def load() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        return {}
    return st if isinstance(st, dict) else {}


def _save(st: dict) -> None:
    shared.atomic_write_text(_path(), json.dumps(st))


def active(now=None) -> bool:
    until = load().get("until")
    return isinstance(until, (int, float)) and until > (now or time.time())


def _epoch(iso) -> float | None:
    try:
        return datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError):
        return None


def _held(sessions: list, started) -> int:
    """What the owner will have to look at: waiting rounds, paused grinds, failures autopilot gave up on."""
    n = sum(1 for r in sessions if r.get("status") == "waiting")
    n += sum(1 for v in ui_grind.index()["pr"].values() if v["state"] == "paused")
    for r in sessions:
        ended = _epoch(r.get("ended_at"))
        if r.get("status") == "failed" and ended and started and ended >= started and \
                (not r.get("session_id") or (r.get("afk_retries") or 0) >= len(RETRY_DELAYS)):
            n += 1
    return n


def public(sessions=None, now=None) -> dict:
    """What the header polls: the countdown while on, the away summary once it ended."""
    now = now or time.time()
    st = load()
    on = active(now)
    out = {"active": on, "until": st.get("until") if on else None, "started": st.get("started") if on else None,
           "decisions": len(st.get("log") or []), "held": 0, "summary": None}
    if on:
        out["held"] = _held(ui_sessions.list_sessions() if sessions is None else sessions, st.get("started"))
    elif st.get("ended") and not st.get("dismissed") and st.get("started"):
        out["summary"] = {"started": st["started"], "ended": st.get("until"), "log": st.get("log") or [],
                          "held": st.get("held_at_end", 0)}
    return out


def start(until, now=None) -> dict:
    """Go AFK until `until` (epoch seconds), or move the end of a running window."""
    now = now or time.time()
    if not isinstance(until, (int, float)) or isinstance(until, bool) or not now < until <= now + MAX_SECONDS:
        raise ValueError("until must be a time within the next 24 hours")
    with _lock:
        st = load()
        if not active(now):
            st = {"started": now, "skipped_ci": [], "log": [], "ended": False}
        st["until"] = until
        _save(st)
    return public(now=now)


def stop(now=None) -> dict:
    """I'm back: end the window now."""
    now = now or time.time()
    with _lock:
        st = load()
        if isinstance(st.get("until"), (int, float)) and st["until"] > now:
            st["until"] = now
            _save(st)
    tick(now)  # sends the summary push at once instead of on the next tick
    return public(now=now)


def dismiss() -> dict:
    with _lock:
        st = load()
        if st:
            st["dismissed"] = True
            _save(st)
    return public()


def _entry(kind: str, rec: dict, now: float, question, picked) -> dict:
    return {"at": now, "kind": kind, "sid": rec.get("id"), "link": rec.get("link"), "repo": rec.get("repo"),
            "command": str(rec.get("command") or "")[:200], "question": str(question or "")[:500],
            "picked": str(picked or "")[:500]}


def _answer(rec: dict, now: float) -> dict | None:
    pq = rec.get("pending_question")
    if rec.get("status") != "waiting" or not isinstance(pq, dict) or pq.get("status") != "pending":
        return None
    if rec["id"] in ui_runner._procs or not rec.get("session_id"):
        return None  # claude is still exiting after `aiw ask`; the next tick gets it
    qs = pq.get("questions") or []
    if not qs or not all(q.get("recommended") for q in qs):
        return None  # held: a question without a recommendation is the owner's call
    text = ui_sessions.answer_text(pq, {str(i): {"labels": [q["recommended"]]} for i, q in enumerate(qs)})
    if ui_sessions.claim_answer(rec["id"], pq["id"]) is None:
        return None
    ui_runner.resume(rec["id"], text)
    return _entry("answer", rec, now, " / ".join(str(q.get("question") or q.get("header") or "") for q in qs),
                  " / ".join(q["recommended"].removesuffix("(Recommended)").strip() for q in qs))


def _retry(rec: dict, now: float, started) -> dict | None:
    sid, status = rec["id"], rec.get("status")
    if rec.get("afk_retries") and status in ("done", "waiting"):  # a retry got through: start the count over
        ui_sessions.update(sid, afk_retries=None, afk_retry_at=None, afk_retry_for=None)
        return None
    ended = _epoch(rec.get("ended_at"))
    if status != "failed" or not rec.get("session_id") or not ended or not started or ended < started:
        return None  # only failures from this window, and only ones claude can --resume
    n = rec.get("afk_retries") or 0
    if rec.get("afk_retry_for") != rec.get("ended_at"):  # a fresh failure: schedule the next attempt
        if n < len(RETRY_DELAYS):
            ui_sessions.update(sid, afk_retry_at=now + RETRY_DELAYS[n], afk_retry_for=rec.get("ended_at"))
        return None
    if now < (rec.get("afk_retry_at") or 0):
        return None
    ui_sessions.update(sid, afk_retries=n + 1)
    try:
        ui_runner.resume_stopped(sid)
    except ui_runner.Conflict as e:  # e.g. a newer session owns the issue: leave it to the owner
        ui_sessions.update(sid, afk_retries=len(RETRY_DELAYS))
        warn(f"afk: not retrying {sid}: {e}")
        return None
    return _entry("retry", rec, now, rec.get("error"), f"retry {n + 1} of {len(RETRY_DELAYS)}")


def _ci_red(owner: str, repo: str, issue: int) -> bool:
    st = ui_status.cached(owner, repo, issue)
    return bool(st and (st.get("pr") or {}).get("ci") == "red")


def _skip_ci(skipped: list, now: float) -> list:
    out = []
    for _, h in ui_grind._state_files():
        key = f"{h['owner']}/{h['repo']}#{h['number']}".lower()
        if "done" in h or "paused" not in h or key in skipped:
            continue
        issue = ui_board.issue_for_pr(f"https://github.com/{h['owner']}/{h['repo']}/pull/{h['number']}")
        if not issue or not (_CI_REASON.search(h["paused"] or "") or _ci_red(h["owner"], h["repo"], issue)):
            continue
        status, res = ui_grind.reply(h["owner"], h["repo"], issue, SKIP_CI_REPLY)
        if status != 200:  # e.g. the round that paused is still exiting: try again next tick
            continue
        skipped.append(key)
        out.append(_entry("skip-ci", {"link": {"owner": h["owner"], "repo": h["repo"], "issue": issue},
                                      "repo": f"{h['owner']}/{h['repo']}", "command": f"/pr-grind {h['thread']}"},
                          now, h["paused"], "Skip CI for now"))
    return out


def _finish(now: float) -> None:
    with _lock:
        st = load()
        if st.get("ended") or not st.get("started"):
            return
        held = _held(ui_sessions.list_sessions(), st["started"])
        st.update(ended=True, held_at_end=held)
        _save(st)
    n = len(st.get("log") or [])
    ui_notify.notify("afk", {"id": f"afk-{st['started']}",
                             "note": f"{n} decision{'s' * (n != 1)} made, {held} waiting on you"})


def tick(now=None) -> None:
    now = now or time.time()
    st = load()
    if not st.get("started"):
        return
    if not active(now):
        _finish(now)
        return
    entries, skipped = [], list(st.get("skipped_ci") or [])
    for rec in ui_sessions.list_sessions():
        for step in (_answer, lambda r, t: _retry(r, t, st["started"])):
            try:
                e = step(rec, now)
            except Exception as exc:  # noqa: BLE001 - one bad session must not stop the rest
                warn(f"afk: {rec.get('id')}: {type(exc).__name__}: {exc}")
                continue
            if e:
                entries.append(e)
    try:
        entries += _skip_ci(skipped, now)
    except Exception as exc:  # noqa: BLE001
        warn(f"afk: skip ci: {type(exc).__name__}: {exc}")
    if not entries and skipped == list(st.get("skipped_ci") or []):
        return
    with _lock:  # re-read: the owner may have extended or ended the window meanwhile
        cur = load()
        if cur.get("started") != st["started"]:
            return
        cur["log"] = ((cur.get("log") or []) + entries)[-MAX_LOG:]
        cur["skipped_ci"] = skipped
        _save(cur)


def start_timer(interval: float = TICK_SECONDS) -> threading.Thread:
    def loop():
        while True:
            try:
                tick()
            except Exception as e:  # noqa: BLE001 - keep the timer alive
                warn(f"afk tick failed: {type(e).__name__}: {e}")
            time.sleep(interval)
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t
