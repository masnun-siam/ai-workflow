"""Review grinding state for the UI: an index of what state each pr-grind loop is in, and ntfy when one
pauses or finishes. Stdlib only.

State lives where pr-grind already keeps it: <pr_grind_dir>/<owner>-<repo>-<pr>.md (headers
`paused:` / `done:`, one `## Round n` heading per round). Starting a grind is the pr-grind skill's job and
re-entering an existing loop is ui_runner.prgrind_tick's; grind autostart returns in E3.
"""

from __future__ import annotations

import glob
import json
import os
import threading
import time

import shared
import ui_notify
import ui_runner
import ui_sessions
from shared import warn

_lock = threading.Lock()
_NOTIFIED = "grind_notified.json"


def _store(name: str) -> str:
    return os.path.join(shared.data_dir(), name)


def _load(name: str, default):
    try:
        with open(_store(name), encoding="utf-8") as f:
            v = json.load(f)
    except (OSError, ValueError):
        return default
    return v if isinstance(v, type(default)) else default


def _save(name: str, value) -> None:
    shared.atomic_write_text(_store(name), json.dumps(value))


def _state_files():
    """(path, header) for every valid pr-grind state file."""
    for path in glob.glob(os.path.join(ui_runner._prgrind_dir(), "*.md")):
        try:
            h = ui_runner._header(path)
        except OSError:
            continue
        if ui_runner._valid(h):
            yield path, h


def index() -> dict:
    """One scan: {"pr": {(owner, repo, pr): {state, round}}}. state is running | idle | paused | done."""
    sessions = ui_sessions.list_sessions()
    live = {r.get("command") for r in sessions if ui_runner._live(r)}
    by_pr = {}
    for path, h in _state_files():
        if "done" in h:
            st = "done"
        elif "paused" in h:
            st = "paused"
        elif f"/pr-grind {h['thread']}" in live:
            st = "running"
        else:
            st = "idle"
        rounds = sum(1 for ln in ui_runner._read_lines(path) if ln.startswith("## Round "))
        by_pr[(h["owner"].lower(), h["repo"].lower(), int(h["number"]))] = (
            {"state": st, "round": rounds, "reason": h["paused"]} if st == "paused" else {"state": st, "round": rounds}
        )
    return {"pr": by_pr}


def notify_changes() -> None:
    """ntfy when a loop pauses or finishes. The first scan only records what already exists."""
    keys = {}
    for _, h in _state_files():
        base = f"{h['owner']}/{h['repo']}#{h['number']}"
        if "done" in h:
            keys[f"{base}:done"] = ("grind-done", h, h["done"])
        elif "paused" in h:
            keys[f"{base}:paused:{h['paused']}"] = ("grind-paused", h, h["paused"])
    seen = _load(_NOTIFIED, [])
    if not os.path.exists(_store(_NOTIFIED)):
        _save(_NOTIFIED, sorted(keys))
        return
    fresh = [k for k in keys if k not in seen]
    if not fresh:
        return
    for k in fresh:
        event, h, note = keys[k]
        link = {"owner": h["owner"], "repo": h["repo"], "issue": int(h["number"])}  # labelled by the PR number
        ui_notify.notify(
            event,
            {
                "id": k,
                "link": link,
                "repo": f"{h['owner']}/{h['repo']}",
                "command": f"/pr-grind {h['thread']}",
                "note": note,
            },
        )
    _save(_NOTIFIED, sorted(set(seen) | set(fresh)))


def start_timer(interval: float = 30.0) -> threading.Thread:
    def loop():
        while True:
            try:
                notify_changes()
            except Exception as e:  # noqa: BLE001 - one bad scan must not stop the timer
                warn(f"grind tick: notify_changes: {type(e).__name__}: {e}")
            time.sleep(interval)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t
