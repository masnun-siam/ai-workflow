"""AFK mode (issue #178): a timed autopilot run by the server, so it works with no browser open.

While it runs, each tick:
- answers every `aiw ask` round whose questions all carry a "(Recommended)" option, planning
  interviews included, through the same claim + resume path as the answer page;
- gives every other round to a read-only Opus answerer session (agents/away-answerer.md, started with
  only its tools allowed): a valid reply is answered the same way and logged `by: opus`; a hold, or two
  failed answerers (failed, limited, stopped, invalid reply, over 10 minutes), is logged `held` and the
  round waits for the owner. A human answer or the window ending stops the answerer with no log row;
- retries sessions that failed during the window on a 2m/10m/30m/1h backoff, then holds them;
- retries dispatch lanes that are held or stopped (not ones asking a question) on the same backoff.
When the window ends (expiry or "I'm back") one ntfy push sums it up and the UI shows the log.

State: <data_dir>/afk.json {started, until, log, ended, held_at_end, dismissed}.
Retry bookkeeping lives on the session record or the dispatch lane: afk_retries, afk_retry_at, afk_retry_for.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime

import away_answerer
import dispatch_run
import shared
import ui_notify
import ui_panel
import ui_runner
import ui_sessions
from shared import warn

MAX_SECONDS = 24 * 3600  # "until HH:MM" may roll into tomorrow; never longer than a day
RETRY_DELAYS = (120, 600, 1800, 3600)
MAX_LOG = 500
TICK_SECONDS = 5
ANSWER_SECONDS = 600  # an answerer running longer than this counts as failed
MAX_ATTEMPTS = 2  # answerers per round
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
    if not isinstance(iso, str) or not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()  # 3.10's fromisoformat rejects `Z`
    except ValueError:
        return None


def _held(sessions: list, started) -> int:
    """What the owner will have to look at: waiting rounds, failures autopilot gave up on."""
    sessions = [r for r in sessions if not ui_sessions.is_answerer(r)]
    n = sum(1 for r in sessions if r.get("status") == "waiting")
    for r in sessions:
        ended = _epoch(r.get("ended_at"))
        if (
            r.get("status") == "failed"
            and ended
            and started
            and ended >= started
            and (not r.get("session_id") or (r.get("afk_retries") or 0) >= len(RETRY_DELAYS))
        ):
            n += 1
    return n


def public(sessions=None, now=None) -> dict:
    """What the header polls: the countdown while on, the away summary once it ended."""
    now = now or time.time()
    st = load()
    on = active(now)
    out = {
        "active": on,
        "until": st.get("until") if on else None,
        "started": st.get("started") if on else None,
        "decisions": len(st.get("log") or []),
        "held": 0,
        "summary": None,
    }
    if on:
        out["held"] = _held(ui_sessions.list_sessions() if sessions is None else sessions, st.get("started"))
    elif st.get("ended") and not st.get("dismissed") and st.get("started"):
        out["summary"] = {
            "started": st["started"],
            "ended": st.get("until"),
            "log": st.get("log") or [],
            "held": st.get("held_at_end", 0),
        }
    return out


def start(until, now=None) -> dict:
    """Go AFK until `until` (epoch seconds), or move the end of a running window."""
    now = now or time.time()
    if not isinstance(until, (int, float)) or isinstance(until, bool) or not now < until <= now + MAX_SECONDS:
        raise ValueError("until must be a time within the next 24 hours")
    with _lock:
        st = load()
        if not active(now):
            st = {"started": now, "log": [], "ended": False}
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
    return {
        "at": now,
        "kind": kind,
        "sid": rec.get("id"),
        "link": rec.get("link"),
        "repo": rec.get("repo"),
        "command": str(rec.get("command") or "")[:200],
        "question": str(question or "")[:500],
        "picked": str(picked or "")[:500],
    }


def _round_entry(rec, now, pending, picks, by, why=None, answerer=None, cost=None) -> dict:
    """The log entry for one answered round: the summary strings older readers use, plus the full questions."""
    qs = pending.get("questions") or []
    summary = _entry(
        "answer",
        rec,
        now,
        " / ".join(str(q.get("question") or q.get("header") or "") for q in qs),
        " / ".join(", ".join(p).removesuffix("(Recommended)").strip() for p in picks),
    )
    questions = [
        {
            **{k: v for k, v in q.items() if k != "recommended"},
            "picked": picks[i],
            "why": (why or {}).get(str(i)),
        }
        for i, q in enumerate(qs)
    ]
    return {
        **summary,
        "id": f"{rec['id']}:{pending['id']}",
        "by": by,
        "questions": questions,
        "answerer": answerer,
        "cost": cost,
        "changed": False,
    }


def _round(rec: dict):
    """The pending round of a session waiting on the owner and ready to be resumed, else None."""
    pq = rec.get("pending_question")
    if rec.get("status") != "waiting" or not isinstance(pq, dict) or pq.get("status") != "pending":
        return None
    if rec["id"] in ui_runner._procs or not rec.get("session_id"):
        return None  # claude is still exiting after `aiw ask`; the next tick gets it
    return pq if pq.get("questions") else None


def _recommended(pq: dict) -> bool:
    return all(q.get("recommended") for q in pq["questions"])


def _answer(rec: dict, now: float) -> dict | None:
    pq = _round(rec)
    if pq is None or not _recommended(pq):
        return None  # the rest go to an answerer (_opus)
    qs = pq["questions"]
    text = ui_sessions.answer_text(pq, {str(i): {"labels": [q["recommended"]]} for i, q in enumerate(qs)})
    if ui_sessions.claim_answer(rec["id"], pq["id"]) is None:
        return None
    ui_runner.resume(rec["id"], text)
    return _round_entry(rec, now, pq, [[q["recommended"]] for q in qs], "recommended")


def _held_entry(rec, now, pending, reason, answerer, cost) -> dict:
    qs = pending.get("questions") or []
    entry = _entry(
        "held",
        rec,
        now,
        " / ".join(str(q.get("question") or q.get("header") or "") for q in qs),
        f"Held: {reason}",
    )
    return {
        **entry,
        "id": f"{rec['id']}:{pending['id']}",
        "questions": [{k: v for k, v in q.items() if k != "recommended"} for q in qs],
        "answerer": answerer,
        "cost": cost,
        "reason": reason[:300],
    }


def _start_answerer(rec: dict, pq: dict) -> None:
    sid = rec["id"]
    transcript = os.path.join(ui_sessions.session_dir(sid), "stream.jsonl")
    checkout = rec.get("cwd_path") or ui_runner.read_checkouts().get(rec["repo"], rec["repo"])
    a = ui_runner.start(
        away_answerer.prompt(rec, pq, transcript, checkout),
        rec["repo"],
        agent="ai-workflow:away-answerer",
        model="opus",
        effort="medium",
        claude_cmd=rec.get("claude_cmd"),
        allowed_tools=away_answerer.allowed_tools(),
    )
    ui_sessions.update(a["id"], role=ui_sessions.ANSWERER_ROLE, answers_for=sid, answers_round=pq["id"])
    n = pq.get("answerer_attempts") or 0
    if not ui_sessions.update_pending(sid, pq["id"], answerer=a["id"], answerer_attempts=n + 1):
        ui_runner.stop(a["id"])  # the owner answered while it started


def _answerer_failed(rec, now, pq, aid, reason) -> dict | None:
    """Clear the dead answerer; start the next one, or hold the round after the second failure."""
    sid = rec["id"]
    cost = (ui_sessions.load(aid) or {}).get("cost")
    if not ui_sessions.update_pending(sid, pq["id"], answerer=None):
        return None  # the round is gone
    if (pq.get("answerer_attempts") or 0) < MAX_ATTEMPTS:
        _start_answerer(rec, pq)
        return None
    reason = f"answerer failed ({reason})"
    ui_sessions.update_pending(sid, pq["id"], held=True)
    return _held_entry(rec, now, pq, reason, aid, cost)


def _opus(rec: dict, now: float) -> dict | None:
    pq = _round(rec)
    if pq is None or _recommended(pq) or pq.get("held"):
        return None
    sid, aid = rec["id"], pq.get("answerer")
    if not aid:
        if (pq.get("answerer_attempts") or 0) < MAX_ATTEMPTS:
            _start_answerer(rec, pq)
        return None
    a = ui_sessions.load(aid) or {}
    status = a.get("status")
    if status in ("starting", "running"):
        started = _epoch(a.get("started_at"))
        if started and now - started <= ANSWER_SECONDS:
            return None
        ui_runner.stop(aid)
        return _answerer_failed(rec, now, pq, aid, "timed out after 10 minutes")
    if status != "done":
        if status == "limited":
            ui_runner.stop(aid)  # no auto-resume: a limited answerer is not queued for the reset
        return _answerer_failed(rec, now, pq, aid, status or "missing")
    try:
        reply = away_answerer.parse_reply(ui_panel.final_text(aid), pq)
    except ValueError as e:
        return _answerer_failed(rec, now, pq, aid, f"invalid reply: {e}")
    if "hold" in reply:
        if not ui_sessions.update_pending(sid, pq["id"], held=True, answerer=None):
            return None
        return _held_entry(rec, now, pq, reply["hold"], aid, a.get("cost"))
    answers = reply["answers"]
    text = ui_sessions.answer_text(pq, {i: {"labels": v["labels"]} for i, v in answers.items()})
    if ui_sessions.claim_answer(sid, pq["id"]) is None:
        return None  # the owner answered first
    ui_runner.resume(sid, text)
    n = len(pq["questions"])
    picks = [answers[str(i)]["labels"] for i in range(n)]
    why = {i: v["why"] for i, v in answers.items()}
    return _round_entry(rec, now, pq, picks, "opus", why, aid, a.get("cost"))


def _busy_answerers() -> list:
    return [
        r
        for r in ui_sessions.list_sessions()
        if ui_sessions.is_answerer(r) and r.get("status") in ("starting", "running")
    ]


def _sweep_answerers() -> None:
    """Stop an answerer whose round is gone: the owner answered it, or its session was stopped or deleted."""
    for a in _busy_answerers():
        parent = ui_sessions.load(a.get("answers_for") or "") or {}
        pq = parent.get("pending_question")
        if parent.get("status") != "waiting" or not isinstance(pq, dict) or pq.get("id") != a.get("answers_round"):
            ui_runner.stop(a["id"])


def _retry(rec: dict, now: float, started) -> dict | None:
    sid, status = rec["id"], rec.get("status")
    if ui_sessions.is_answerer(rec):
        return None  # a failed answerer is handled per round (_opus), never resumed
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


def _retry_lanes(now: float) -> list:
    """Held or stopped dispatch lanes: retry on RETRY_DELAYS, keyed by the reason, so a new reason starts over."""
    out = []
    for d in dispatch_run.list_all():
        if d["state"] not in ("running", "paused"):
            continue
        with dispatch_run.locked(d["id"]):
            d = dispatch_run.load(d["id"])
            changed = False
            for k, x in d["lanes"].items():
                why = x.get("held") or (x.get("needs_you") if x.get("needs_you") != "waiting on you" else None)
                if not why:
                    if x.get("afk_retries"):  # it got through: start the count over
                        x.update(afk_retries=None, afk_retry_at=None, afk_retry_for=None)
                        changed = True
                    continue
                n = x.get("afk_retries") or 0
                if x.get("afk_retry_for") != why:
                    if n < len(RETRY_DELAYS):
                        x.update(afk_retry_at=now + RETRY_DELAYS[n], afk_retry_for=why)
                        changed = True
                    continue
                if now < (x.get("afk_retry_at") or 0) or n >= len(RETRY_DELAYS):
                    continue
                x.update(afk_retries=n + 1, afk_retry_for=None)
                dispatch_run.apply_lane_action(d, k, "retry")
                changed = True
                owner, _, name = x["repo"].partition("/")
                out.append(
                    {
                        "at": now,
                        "kind": "retry",
                        "sid": None,
                        "repo": x["repo"],
                        "link": {"owner": owner, "repo": name, "issue": x["n"]},
                        "command": f"dispatch lane #{x['n']}",
                        "question": why[:500],
                        "picked": f"retry {n + 1} of {len(RETRY_DELAYS)}",
                    }
                )
            if changed:
                dispatch_run.save(d)
    return out


def _stop_answerers() -> None:
    """The window is over: stop every busy answerer and free its round. No log row; the round stays waiting."""
    for a in _busy_answerers():
        ui_runner.stop(a["id"])
        ui_sessions.update_pending(a.get("answers_for") or "", a.get("answers_round"), answerer=None)


def _finish(now: float) -> None:
    st = load()
    if st.get("ended") or not st.get("started"):
        return
    _stop_answerers()
    with _lock:
        st = load()
        if st.get("ended") or not st.get("started"):
            return
        held = _held(ui_sessions.list_sessions(), st["started"])
        st.update(ended=True, held_at_end=held)
        _save(st)
    n = len(st.get("log") or [])
    ui_notify.notify(
        "afk", {"id": f"afk-{st['started']}", "note": f"{n} decision{'s' * (n != 1)} made, {held} waiting on you"}
    )


def tick(now=None) -> None:
    now = now or time.time()
    st = load()
    if not st.get("started"):
        return
    if not active(now):
        _finish(now)
        return
    entries = []
    try:
        _sweep_answerers()
    except Exception as exc:  # noqa: BLE001 - one bad answerer must not stop the rest
        warn(f"afk: answerer sweep: {type(exc).__name__}: {exc}")
    for rec in ui_sessions.list_sessions():
        if ui_sessions.is_answerer(rec):
            continue
        for step in (_answer, _opus, lambda r, t: _retry(r, t, st["started"])):
            try:
                e = step(rec, now)
            except Exception as exc:  # noqa: BLE001 - one bad session must not stop the rest
                warn(f"afk: {rec.get('id')}: {type(exc).__name__}: {exc}")
                continue
            if e:
                entries.append(e)
    try:
        entries += _retry_lanes(now)
    except Exception as exc:  # noqa: BLE001 - dispatch trouble must not stop away mode
        warn(f"afk: dispatch lanes: {type(exc).__name__}: {exc}")
    if not entries:
        return
    with _lock:  # re-read: the owner may have extended or ended the window meanwhile
        cur = load()
        if cur.get("started") != st["started"]:
            return
        cur["log"] = ((cur.get("log") or []) + entries)[-MAX_LOG:]
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
