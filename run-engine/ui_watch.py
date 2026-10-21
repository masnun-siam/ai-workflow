"""Which repos the poller watches: every registered repo with a GitHub remote that the UI opened in the last
7 days or that has a live session. "Opened" is any request naming `?repo=`; the times persist in
<data_dir>/ui_opened.json so a restart keeps the set."""

from __future__ import annotations

import json
import os
import threading
import time

import shared

DAYS = 7
_lock = threading.Lock()


def _path() -> str:
    return os.path.join(shared.data_dir(), "ui_opened.json")


def _load() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in d.items() if isinstance(v, (int, float))} if isinstance(d, dict) else {}


def touch(repo: str, now=None) -> None:
    now = now or time.time()
    with _lock:
        d = _load()
        if now - d.get(repo, 0) < 60:  # written at most once a minute per repo
            return
        d = {k: v for k, v in d.items() if now - v < DAYS * 86400}
        d[repo] = now
        os.makedirs(shared.data_dir(), exist_ok=True)
        shared.atomic_write_text(_path(), json.dumps(d))


def recent(now=None) -> list:
    now = now or time.time()
    with _lock:
        return [k for k, v in _load().items() if now - v < DAYS * 86400]
