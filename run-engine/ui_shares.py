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
from collections import deque
from datetime import datetime, timezone

import shared
import ui_actions
import ui_planning

clock = time.time  # tests replace it
_ID = re.compile(r"[0-9a-f]{16}")
_REASONS = ("stopped", "approved", "status", "missing")
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
NAME_MAX, COMMENT_MAX, EXACT_MAX, CONTEXT_MAX = 60, 2000, 1000, 32
MAX_COMMENTS, MAX_APPROVALS, RATE_MAX, RATE_WINDOW = 500, 100, 20, 60  # RATE_WINDOW in seconds
listeners: list = []  # fn(share, kind): kind "comment" or "approval"; called after a reviewer write, outside the lock
_rates: dict[str, deque] = {}  # accepted reviewer write times per share, in memory only
_rate_lock = threading.Lock()  # always taken inside the record lock


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
    if not ok:
        return None
    for key in ("threads", "approvals"):
        if not isinstance(rec.setdefault(key, []), list):
            return None
    return rec


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
    with _rate_lock:
        _rates.pop(sid, None)


# --- threads, comments, approvals (FR-4 to FR-7, FR-13) ---


def _text(value, field: str, lo: int, hi: int, strip: bool = True) -> str:
    """A str that encodes as UTF-8, trimmed unless `strip` is off, of lo..hi code points. Never echoes the input."""
    bad = ShareError(
        "invalid", f"{field} must be {lo} to {hi} characters" if lo else f"{field} must be at most {hi} characters"
    )
    if not isinstance(value, str):
        raise bad
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise bad from None
    value = value.strip() if strip else value
    if not lo <= len(value) <= hi or (lo and not value.strip()):
        raise bad
    return value


def _anchor(anchor) -> dict:
    if not isinstance(anchor, dict):
        raise ShareError("invalid", "anchor must be an object")
    return {
        "exact": _text(anchor.get("exact"), "anchor text", 1, EXACT_MAX, strip=False),
        "prefix": _text(anchor.get("prefix", ""), "anchor prefix", 0, CONTEXT_MAX, strip=False),
        "suffix": _text(anchor.get("suffix", ""), "anchor suffix", 0, CONTEXT_MAX, strip=False),
    }


def _thread(rec: dict, tid) -> dict:
    for t in rec["threads"]:
        if t["id"] == tid:
            return t
    raise ShareError("not_found", "thread not found")


def _live(rec: dict) -> None:
    if rec["state"] != "live":
        raise ShareError("not_found", "share not found")


def _take_slot(sid: str) -> None:
    now = clock()
    with _rate_lock:
        q = _rates.setdefault(sid, deque())
        while q and q[0] <= now - RATE_WINDOW:
            q.popleft()
        if len(q) >= RATE_MAX:
            raise ShareError("rate", "too many comments; try again in a minute")
        q.append(now)


def reviewer_comment_count(share: dict) -> int:
    return sum(not c["by_owner"] for t in share["threads"] for c in t["comments"])


def _comment(author: str, body: str, by_owner: bool) -> dict:
    return {"id": secrets.token_hex(6), "author": author, "by_owner": by_owner, "body": body, "at": now_iso()}


def _reviewer_write(sid: str, thread_id, name, body, anchor=None):
    """Validate, check the caps in order, then append. Returns (thread, comment); listeners run after the lock."""
    out = {}

    def fn(rec):
        _live(rec)
        thread = _thread(rec, thread_id) if anchor is None else None
        author, text = _text(name, "name", 1, NAME_MAX), _text(body, "comment", 1, COMMENT_MAX)
        point = _anchor(anchor) if anchor is not None else None
        if reviewer_comment_count(rec) >= MAX_COMMENTS:
            raise ShareError("full", f"this share holds at most {MAX_COMMENTS} comments")
        _take_slot(sid)
        c = _comment(author, text, False)
        if thread is None:
            thread = {
                "id": secrets.token_hex(6),
                "anchor": point,
                "created_at": c["at"],
                "resolved": False,
                "sent_at": None,
                "comments": [],
            }
            rec["threads"].append(thread)
        thread["comments"].append(c)
        thread["resolved"] = False
        out.update(thread=thread, comment=c)

    _notify(update(sid, fn), "comment")
    return out["thread"], out["comment"]


def _notify(share: dict, kind: str) -> None:
    for fn in list(listeners):
        try:
            fn(share, kind)
        except Exception as e:
            shared.warn(f"shares: listener failed ({type(e).__name__})")


def add_thread(sid, name, body, anchor) -> dict:
    return _reviewer_write(sid, None, name, body, anchor if anchor is not None else {})[0]


def add_comment(sid, thread_id, name, body) -> dict:
    return _reviewer_write(sid, thread_id, name, body)[1]


def add_owner_comment(sid, thread_id, author, body) -> dict:
    out = {}

    def fn(rec):
        thread = _thread(rec, thread_id)
        who = _text(author, "author", 0, 10**6, strip=False)[:NAME_MAX]
        out["c"] = _comment(who, _text(body, "comment", 1, COMMENT_MAX), True)
        thread["comments"].append(out["c"])

    update(sid, fn)
    return out["c"]


def set_resolved(sid, thread_id, resolved: bool) -> dict:
    out = {}

    def fn(rec):
        out["t"] = _thread(rec, thread_id)
        out["t"]["resolved"] = bool(resolved)

    update(sid, fn)
    return out["t"]


def delete_comment(sid, thread_id, comment_id) -> None:
    def fn(rec):
        thread = _thread(rec, thread_id)
        rest = [c for c in thread["comments"] if c["id"] != comment_id]
        if len(rest) == len(thread["comments"]):
            raise ShareError("not_found", "comment not found")
        if rest:
            thread["comments"] = rest
        else:
            rec["threads"].remove(thread)

    update(sid, fn)


def delete_thread(sid, thread_id) -> None:
    update(sid, lambda rec: rec["threads"].remove(_thread(rec, thread_id)))


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def add_approval(sid, name):
    """Returns ({name, at, key?}, created); the key is shown once, only when created."""
    out = {}

    def fn(rec):
        _live(rec)
        who = _text(name, "name", 1, NAME_MAX)
        for a in rec["approvals"]:
            if a["name"].casefold() == who.casefold():
                out["view"], out["created"] = {"name": a["name"], "at": a["at"]}, False
                return
        if len(rec["approvals"]) >= MAX_APPROVALS:
            raise ShareError("full", f"this share holds at most {MAX_APPROVALS} approvals")
        _take_slot(sid)
        key = secrets.token_urlsafe(24)
        a = {"id": secrets.token_hex(6), "name": who, "at": now_iso(), "key_hash": _key_hash(key)}
        rec["approvals"].append(a)
        out["view"], out["created"] = {"name": who, "at": a["at"], "key": key}, True

    rec = update(sid, fn)
    if out["created"]:
        _notify(rec, "approval")
    return out["view"], out["created"]


def withdraw_approval(sid, name, key) -> None:
    def fn(rec):
        _live(rec)
        miss = ShareError("not_found", "approval not found")
        if not isinstance(name, str) or not isinstance(key, str):
            raise miss
        want = _key_hash(key) if key.isascii() else ""
        for a in rec["approvals"]:
            if a["name"].casefold() == name.strip().casefold() and hmac.compare_digest(a["key_hash"], want):
                rec["approvals"].remove(a)
                return
        raise miss

    update(sid, fn)


def delete_approval(sid, approval_id) -> None:
    def fn(rec):
        rest = [a for a in rec["approvals"] if a["id"] != approval_id]
        if len(rest) == len(rec["approvals"]):
            raise ShareError("not_found", "approval not found")
        rec["approvals"] = rest

    update(sid, fn)


def unread(share: dict) -> dict:
    """Reviewer comments and approvals after last_seen_at (all when null), with the newest `at` (null if none)."""
    seen = share.get("last_seen_at") or ""
    comments = [c["at"] for t in share["threads"] for c in t["comments"] if not c["by_owner"] and c["at"] > seen]
    approvals = [a["at"] for a in share["approvals"] if a["at"] > seen]
    return {"comments": len(comments), "approvals": len(approvals), "at": max(comments + approvals, default=None)}


def mark_sent(sid, sent: dict) -> None:
    def fn(rec):
        for t in rec["threads"]:
            at = sent.get(t["id"])
            if isinstance(at, str) and (t["sent_at"] is None or at > t["sent_at"]):
                t["sent_at"] = at

    update(sid, fn)


def public_comment(c: dict) -> dict:
    return {k: c[k] for k in ("id", "author", "by_owner", "body", "at")}


def public_thread(t: dict) -> dict:
    return {
        "id": t["id"],
        "anchor": t["anchor"],
        "resolved": t["resolved"],
        "comments": [public_comment(c) for c in t["comments"]],
    }


def public_threads(share: dict) -> list:
    return [public_thread(t) for t in share["threads"]]


def public_approvals(share: dict) -> list:
    return [{"name": a["name"], "at": a["at"]} for a in share["approvals"]]
