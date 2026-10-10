"""Edit a started run: turn review off before it starts, turn auto-grind off before it is queued.

Both are flags read at a boundary, never an interruption. Review goes through `aiw skip-review`
(the CLI is the only writer of run.json); auto-grind is a flag on the session record that
`ui_grind.autostart` reads once, when the run finishes.
"""
from __future__ import annotations

import os
import subprocess
import sys

import ui_repos
import ui_sessions
from shared import data_dir, run_dir_for

ROUTE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "route.py")


def validate(body: dict) -> dict:
    """Only the keys we accept, type-checked. Review can only be turned OFF: a run whose
    roster lost its reviewer cannot get it back."""
    if not isinstance(body, dict) or not ({"review", "auto_grind"} & set(body)):
        raise ValueError("send review and/or auto_grind")
    out = {}
    if "review" in body:
        if body["review"] is not False:
            raise ValueError("review can only be turned off for an existing run")
        out["review"] = False
    if "auto_grind" in body:
        if not isinstance(body["auto_grind"], bool):
            raise ValueError("auto_grind must be true or false")
        out["auto_grind"] = body["auto_grind"]
    return out


def skip_review(owner: str, repo: str, issue: int, runs_dir: str | None = None) -> str:
    """'applied' | 'unchanged' | 'too_late' | 'not_started'."""
    run_dir = run_dir_for(runs_dir or os.path.join(data_dir(), "runs"), f"{owner}/{repo}", issue)
    if not os.path.isfile(os.path.join(run_dir, "run.json")):
        return "not_started"
    proc = subprocess.run([sys.executable, ROUTE, "skip-review", run_dir], capture_output=True, text=True, timeout=30)
    if proc.returncode == 0:
        return "unchanged" if "already skipped" in proc.stdout else "applied"
    if proc.returncode == 1:
        return "too_late"
    raise ValueError(f"skip-review failed: {proc.stderr.strip()[:200]}")


def set_auto_grind(session_id: str, value: bool) -> str:
    """Explicit False, never a removed key: a pipeline's default would otherwise re-enable it."""
    try:
        ui_sessions.update(session_id, auto_grind=value)
    except (FileNotFoundError, ValueError):
        return "no_session"
    return "applied"


def session_of(owner: str, repo: str, issue: int):
    """The newest run-issue session linked to this issue, or None."""
    best = None
    for rec in ui_sessions.list_sessions():
        link = rec.get("link")
        if not isinstance(link, dict) or link.get("issue") != issue:
            continue
        if (str(link.get("owner")).lower(), str(link.get("repo")).lower()) != (owner.lower(), repo.lower()):
            continue
        if ui_repos.family(rec.get("command") or "") != "run-issue":
            continue
        if best is None or (rec.get("started_at") or 0) > (best.get("started_at") or 0):
            best = rec
    return best


def apply(owner: str, repo: str, issue: int, body: dict, session_id: str | None = None) -> dict:
    """Per-field outcome for one run. `session_id` skips the lookup when the caller has it."""
    want = validate(body)
    out = {}
    if "review" in want:
        out["review"] = skip_review(owner, repo, issue)
    if "auto_grind" in want:
        sid = session_id or (session_of(owner, repo, issue) or {}).get("id")
        out["auto_grind"] = set_auto_grind(sid, want["auto_grind"]) if sid else "no_session"
    return out
