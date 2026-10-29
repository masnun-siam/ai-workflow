"""Inbox urgency (FR-4): a background scorer asks jev how urgent each scorable Inbox item is and fills jev's cache.

`urgency(item)` only reads that cache, so building the Inbox never runs or waits on jev. `scan(items)` is one
pass of the scorer: up to PASS_MAX new items, three calls at a time, skipped once SKIP_AT of the hour's calls are spent.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import jev
import ui_inbox
from shared import warn

QUESTION = "How urgent is this item for the person running these coding sessions?"
LEVELS = [  # lowest first: jev's score is the expected level from 0
    "cosmetic, can wait",
    "minor, can be handled later today",
    "work is waiting on it, but nothing is lost by waiting",
    "blocking work in progress or about to affect other people",
    "irreversible, outward-facing or blocking work right now",
]
PASS_MAX = 3
SKIP_AT = 400
TICK_SECONDS = 30

_pool = ThreadPoolExecutor(max_workers=3)
_in_flight: set = set()  # texts being scored
_lock = threading.Lock()


def _urgency(r: dict) -> int:
    return min(5, max(1, int(r["score"] + 0.5) + 1))  # round half up, not round()'s banker's rounding


def _peek(text: str):
    return jev.peek("urgency", "score", QUESTION, text, levels=LEVELS)


def urgency(item) -> int | None:
    """1-5 from the cache, None when the item is not scored (yet), jev is off or the type is not scorable."""
    text = ui_inbox.urgency_text(item)
    r = _peek(text) if text else None
    return _urgency(r) if r else None


def _score(text: str) -> None:
    try:
        jev.ask("urgency", "score", QUESTION, text, levels=LEVELS)  # an ok answer lands in the cache
    except Exception as exc:  # noqa: BLE001 - a scoring job must never raise
        warn(f"inbox urgency: {type(exc).__name__}")
    finally:
        with _lock:
            _in_flight.discard(text)


def scan(items) -> int:
    """One pass: start scoring the first PASS_MAX uncached, not in-flight items; returns how many started."""
    if jev.status() != "ok" or jev.spent() >= SKIP_AT:
        return 0
    todo: list = []
    for i in items:
        text = ui_inbox.urgency_text(i)
        if text and text not in todo and text not in _in_flight and not _peek(text):
            todo.append(text)
            if len(todo) == PASS_MAX:
                break
    with _lock:
        _in_flight.update(todo)
    for text in todo:
        _pool.submit(_score, text)
    return len(todo)


def start_timer(items_fn, interval: float = TICK_SECONDS) -> threading.Thread:
    def loop():
        while True:
            try:
                scan(items_fn())
            except Exception as e:  # noqa: BLE001 - keep the timer alive
                warn(f"inbox urgency scan: {type(e).__name__}: {e}")
            time.sleep(interval)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t
