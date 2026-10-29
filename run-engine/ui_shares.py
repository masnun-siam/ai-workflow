"""Share store (FR-1, FR-11, FR-12): one JSON record per repo + PRD path, `<data_dir>/shares/<id>.json`.

A share is live (has a token) or ended (token null, threads kept). The module keeps no cache: every call
reads the file, so a restart loses nothing. Writes go through `update`, one lock per record.
ShareError.kind maps to HTTP for the route layers: invalid 400, not_found 404, conflict 409, full 409, rate 429.
Never log a token.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone

import shared
import ui_actions
import ui_planning

clock = time.time  # tests replace it
_ID = re.compile(r"[0-9a-f]{16}")
_REASONS = ("stopped", "approved", "status", "missing")
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class ShareError(Exception):
    def __init__(self, kind: str, message: str = ""):
        super().__init__(message or kind)
        self.kind = kind


def now_iso() -> str:
    return datetime.fromtimestamp(clock(), timezone.utc).isoformat(timespec="milliseconds")


def share_id(repo: str, rel: str) -> str:
    return hashlib.sha256(f"{repo}\0{rel}".encode()).hexdigest()[:16]


def shares_dir() -> str:
    return os.path.join(shared.data_dir(), "shares")


def _lock(sid: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(sid, threading.Lock())


def _reset_locks() -> None:
    """Drop the in-process lock table (tests: simulate a restart)."""
    with _locks_guard:
        _locks.clear()


def _check_id(sid) -> str:
    if not isinstance(sid, str) or not _ID.fullmatch(sid):
        raise ShareError("not_found", "share not found")
    return sid


def _path(sid: str) -> str:
    return os.path.join(shares_dir(), sid + ".json")


def _read(sid: str):
    try:
        with open(_path(_check_id(sid)), encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return None
    ok = isinstance(rec, dict) and rec.get("id") == sid and rec.get("state") in ("live", "ended")
    return rec if ok else None


def _write(rec: dict) -> None:
    os.makedirs(shares_dir(), exist_ok=True)
    shared.atomic_write_text(_path(rec["id"]), json.dumps(rec, indent=2, ensure_ascii=False) + "\n")


def get(sid):
    try:
        return _read(sid)
    except ShareError:
        return None


def find(repo: str, rel: str):
    return get(share_id(repo, rel))


def list_shares() -> list:
    out = []
    try:
        names = sorted(os.listdir(shares_dir()))
    except OSError:
        return out
    for name in names:
        stem, ext = os.path.splitext(name)
        rec = _read(stem) if ext == ".json" and _ID.fullmatch(stem) else None
        if rec is None:
            if ext != ".tmp":
                shared.warn(f"shares: skipping unreadable or foreign file {name}")
            continue
        out.append(rec)
    return out


def by_token(token):
    if not isinstance(token, str) or not token:
        return None
    want, found = token.encode(), None
    for rec in list_shares():  # no early exit: every live token is compared
        have = rec.get("token")
        if rec["state"] == "live" and isinstance(have, str) and hmac.compare_digest(have.encode(), want):
            found = rec
    return found


def prd_state(checkout, rel) -> dict:
    out = {"reason": "missing", "status": None, "title": None, "path": None, "updated_at": None}
    if not checkout or not isinstance(rel, str) or not ui_actions._PRD.fullmatch(rel):
        return out
    try:
        root = os.path.realpath(os.path.join(checkout, "docs", "prds"))
        real = os.path.realpath(os.path.join(checkout, rel))
        if os.path.commonpath([root, real]) != root or not os.path.isfile(real):
            return out
        parsed = ui_planning._parse(real)
        mtime = os.stat(real).st_mtime
    except (OSError, ValueError):
        return out
    if parsed is None:
        return out
    status = parsed["status"]
    out.update(
        status=status,
        title=parsed["title"],
        path=real,
        updated_at=datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="milliseconds"),
        reason={"Approved": "approved", "Done": "status"}.get(status),
    )
    return out


def _end_rec(rec: dict, reason: str) -> None:
    rec.update(state="ended", end_reason=reason, ended_at=now_iso(), token=None)


def create(repo: str, rel: str, checkout):
    if not isinstance(rel, str) or not ui_actions._PRD.fullmatch(rel):
        raise ShareError("invalid", "path must be docs/prds/<name>.md")
    sid = share_id(repo, rel)
    with _lock(sid):
        st = prd_state(checkout, rel)
        rec = _read(sid)
        live = rec is not None and rec["state"] == "live"
        if st["reason"]:
            if live:
                _end_rec(rec, st["reason"])
                _write(rec)
            if st["reason"] == "missing":
                raise ShareError("invalid", "the PRD file was not found under docs/prds/")
            if st["reason"] == "approved":
                raise ShareError("conflict", "PRD is Approved; only Draft or In review PRDs can be shared")
            raise ShareError("conflict", f"PRD status is {st['status']}; only Draft or In review PRDs can be shared")
        if live:
            return rec, False
        now = now_iso()
        rec = rec or {
            "id": sid,
            "repo": repo,
            "path": rel,
            "last_seen_at": now,
            "threads": [],
        }
        rec.update(
            token=secrets.token_urlsafe(32),
            state="live",
            end_reason=None,
            created_at=now,
            ended_at=None,
            approvals=[],
        )
        _write(rec)
        return rec, True


def end(sid, reason: str):
    if reason not in _REASONS:
        raise ValueError(f"bad end reason: {reason!r}")
    try:
        _check_id(sid)
    except ShareError:
        return None
    with _lock(sid):
        rec = _read(sid)
        if rec is not None and rec["state"] == "live":
            _end_rec(rec, reason)
            _write(rec)
        return rec


def refresh(sid, checkout):
    rec = get(sid)
    if rec is None or rec["state"] != "live":
        return rec
    reason = prd_state(checkout, rec["path"])["reason"]
    return end(sid, reason) if reason else rec


def update(sid, fn) -> dict:
    _check_id(sid)
    with _lock(sid):
        rec = _read(sid)
        if rec is None:
            raise ShareError("not_found", "share not found")
        fn(rec)  # a ShareError here aborts before the write
        _write(rec)
        return rec


def mark_seen(sid) -> dict:
    return update(sid, lambda rec: rec.update(last_seen_at=now_iso()))


def delete_record(sid) -> None:
    _check_id(sid)
    with _lock(sid):
        rec = _read(sid)
        if rec is None:
            raise ShareError("not_found", "share not found")
        if rec["state"] == "live":
            raise ShareError("conflict", "stop the share before deleting it")
        os.remove(_path(sid))
