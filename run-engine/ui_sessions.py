"""UI session store: one dir per session under <data_dir>/sessions/<id>/.

Each holds meta.json (the record) and stream.jsonl (raw event stream, owned by the
runner). Vocabulary: docs/prd/workflow-control-ui.md, issue #105. Records survive a
restart because they live only on disk.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone

from shared import data_dir, warn

# Timestamp prefix makes ids sort by creation time; the strict whitelist doubles as
# path-traversal protection (no separators, "..", NUL, empty, trailing slash).
_ID_RE = re.compile(r"[0-9]{8}T[0-9]{12}Z-[0-9a-f]{8}")


def sessions_dir() -> str:
    return os.path.join(data_dir(), "sessions")


def session_dir(sid: str) -> str:
    if not isinstance(sid, str) or not _ID_RE.fullmatch(sid):
        raise ValueError(f"invalid session id: {sid!r}")
    return os.path.join(sessions_dir(), sid)


def _atomic_write_json(path: str, data: dict) -> None:
    # Unique temp name per writer, then os.replace: readers never see a partial file.
    # (shared.write_json opens the target directly, so it is not atomic.)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".meta.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _read_meta(path: str):
    # Not shared.read_json: that die()s on missing/bad files; here one bad record
    # must not take the whole list down.
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        warn(f"skipping unreadable session record: {path} ({e})")
        return None
    if not isinstance(data, dict):
        warn(f"skipping corrupt session record: {path}")
        return None
    return data


def create(command: str, repo: str, link=None) -> dict:
    os.makedirs(sessions_dir(), exist_ok=True)
    while True:
        now = datetime.now(timezone.utc)
        sid = f"{now.strftime('%Y%m%dT%H%M%S%f')}Z-{secrets.token_hex(4)}"
        try:
            os.mkdir(session_dir(sid))  # exclusive: collision -> new suffix
            break
        except FileExistsError:
            continue
    open(os.path.join(session_dir(sid), "stream.jsonl"), "a").close()
    record = {
        "id": sid, "command": command, "repo": repo, "link": link,
        "session_id": None, "pid": None, "status": "starting", "cost": None,
        "started_at": now.isoformat(), "ended_at": None, "pending_question": None,
    }
    _atomic_write_json(os.path.join(session_dir(sid), "meta.json"), record)
    return record


def load(sid: str):
    return _read_meta(os.path.join(session_dir(sid), "meta.json"))


def update(sid: str, **fields) -> dict:
    if "id" in fields:
        raise ValueError("session id is immutable")
    path = os.path.join(session_dir(sid), "meta.json")
    # flock (POSIX; repo targets macOS/Linux) serialises read-modify-write so
    # concurrent writers both land; atomic replace still guards readers.
    with open(os.path.join(session_dir(sid), ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        record = _read_meta(path)
        if record is None:
            raise ValueError(f"corrupt session record: {path}")
        record.update(fields)
        _atomic_write_json(path, record)
    return record


def set_pending(sid: str, round) -> dict:
    """Store a question round (ADR 0001 shape) and mark the session waiting."""
    if not isinstance(round, dict):
        raise ValueError("round must be an object")
    rid, qs = round.get("id"), round.get("questions")
    if not isinstance(rid, str) or not rid:
        raise ValueError("round id must be a non-empty string")
    if not isinstance(qs, list) or not qs:
        raise ValueError("questions must be a non-empty list")
    questions = []
    for q in qs:
        if not isinstance(q, dict):
            raise ValueError("question must be an object")
        multi, free, opts = q.get("multiSelect", False), q.get("allowFreeText", True), q.get("options")
        if not isinstance(multi, bool) or not isinstance(free, bool):
            raise ValueError("multiSelect and allowFreeText must be bool")
        if not isinstance(opts, list) or not opts:
            raise ValueError("question needs options")
        options, seen = [], set()
        for o in opts:
            label = o.get("label") if isinstance(o, dict) else None
            if not isinstance(label, str) or not label:
                raise ValueError("option label must be a non-empty string")
            if label in seen:
                raise ValueError(f"duplicate option label: {label!r}")
            seen.add(label)
            options.append({"label": label, "description": o.get("description")})
        questions.append({
            "header": q.get("header"), "question": q.get("question"), "multiSelect": multi,
            "options": options,
            "recommended": next((o["label"] for o in options if o["label"].endswith("(Recommended)")), None),
            "allowFreeText": free,
        })
    rec = {"id": rid, "status": "pending", "allowFreeText": True, "questions": questions}
    return update(sid, pending_question=rec, status="waiting")


def claim_answer(sid: str, round_id: str):
    """Atomically consume the pending round; returns the record to the single winner, else None."""
    path = os.path.join(session_dir(sid), "meta.json")
    with open(os.path.join(session_dir(sid), ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        record = _read_meta(path)
        if record is None:
            raise ValueError(f"corrupt session record: {path}")
        pq = record.get("pending_question")
        if (record.get("status") != "waiting" or not isinstance(pq, dict)
                or pq.get("status") != "pending" or pq.get("id") != round_id):
            return None
        record.update(pending_question=None, status="starting")
        _atomic_write_json(path, record)
    return record


def list_sessions() -> list:
    try:
        names = os.listdir(sessions_dir())
    except FileNotFoundError:
        return []
    records = []
    for name in sorted(names, reverse=True):
        if not _ID_RE.fullmatch(name):
            continue
        record = _read_meta(os.path.join(sessions_dir(), name, "meta.json"))
        if record is not None:
            records.append(record)
    return records
