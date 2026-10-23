"""In-memory browser notification feed (issue #360): open aiw tabs poll it via GET /api/notifications.

Starts empty on every server start; keeps the newest 200 entries. Entries carry only
id, event, title, body, path, tag and ts, never a credential.
"""

from __future__ import annotations

import collections
import threading
from datetime import datetime, timezone

MAX_ENTRIES = 200
MAX_REPLAY = 5  # a tab far behind skips to the newest and shows at most this many

_lock = threading.Lock()
_entries: collections.deque = collections.deque(maxlen=MAX_ENTRIES)
_next = 1


def add(event: str, title: str, body: str, path: str) -> dict:
    global _next
    with _lock:
        n = _next
        _next += 1
        entry = {
            "id": n,
            "event": event,
            "title": title,
            "body": body,
            "path": path,
            "tag": f"aiw-{n}",
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        _entries.append(entry)
        return dict(entry)


def after(n: int | None) -> dict:
    """`{latest, events}`: entries with id > n (at most the newest 5, oldest first).
    No n, or an n above latest (a server restart), gives no events."""
    with _lock:
        latest = _next - 1
        if n is None or n > latest:
            return {"latest": latest, "events": []}
        newer = [dict(e) for e in _entries if e["id"] > n]
        return {"latest": latest, "events": newer[-MAX_REPLAY:]}
