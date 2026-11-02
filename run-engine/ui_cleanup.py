"""Clean up finished sessions for the UI: list them, and remove the chosen ones' records.

A target is one finished session (status not live), keyed by its session id. Only the
session's own directory under the data dir is removed: never a git checkout, worktree or branch.
"""

from __future__ import annotations

import shutil

import ui_sessions

LIVE = ("starting", "running", "waiting", "limited", "queued")  # queued: a batch day not started yet


def find_targets() -> list:
    """Finished sessions as [{key, label, repo, flags}], newest first."""
    return [
        {"key": s["id"], "label": s.get("command") or "session", "repo": s.get("repo"), "flags": []}
        for s in ui_sessions.list_sessions()
        if s.get("status") not in LIVE
    ]


def clean(keys: list) -> list:
    """Remove the records of the named finished sessions; returns the keys removed. Unknown or live keys are skipped."""
    ok = {t["key"] for t in find_targets()}  # re-derived: the client never names paths
    removed = [k for k in keys if k in ok]
    done = []
    for k in removed:
        try:
            rec = ui_sessions.load(k)
        except ValueError:
            continue
        if rec is None or rec.get("status") in LIVE:  # resumed (or gone) since find_targets
            continue
        # ponytail: a window remains between this check and rmtree; the full fix is the ui_sessions.update flock
        shutil.rmtree(ui_sessions.session_dir(k), ignore_errors=True)
        done.append(k)
    return done
