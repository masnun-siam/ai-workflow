"""Review grinding state for the UI: an index of what state each pr-grind loop is in, and ntfy when one
pauses or finishes. Stdlib only.

State lives where pr-grind already keeps it: <pr_grind_dir>/<owner>-<repo>-<pr>.md (headers
`paused:` / `done:`, one `## Round n` heading per round). Re-entering an existing loop is
ui_runner.prgrind_tick's; `autostart` begins a loop when a PR turns ready (FR-10).
"""

from __future__ import annotations

import glob
import json
import os
import re
import threading
import time
from datetime import datetime, timezone

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


class Conflict(Exception):
    """The loop is not in a state that allows the action (HTTP 409)."""


SKIP_CI_REPLY = "Skip CI for now, complete the grind, then come back and fix the CI"


def _loop(repo: str, pr) -> tuple:
    """(state file, header) of the loop for `repo`'s PR; Conflict when there is none."""
    owner, _, name = str(repo).lower().partition("/")
    for path, h in _state_files():
        if (h["owner"].lower(), h["repo"].lower(), int(h["number"])) == (owner, name, pr):
            return path, h
    raise Conflict(f"no grind loop for {repo}#{pr}")


def skip_ci(repo: str, pr: int) -> dict:
    """A paused loop's "Skip CI for now": the decision goes to its newest finished /pr-grind session, then the
    pause is cleared so the re-entry timer takes the loop on. Conflict when it is not paused or has no session."""
    path, h = _loop(repo, pr)
    if "paused" not in h or "done" in h:
        raise Conflict("this grind is not paused")
    pat = re.compile(rf"/pull/{pr}\b")
    target = next(
        (
            r
            for r in ui_sessions.list_sessions()
            if str(r.get("command", "")).startswith("/pr-grind ")
            and (r["command"] == f"/pr-grind {h['thread']}" or pat.search(r["command"]))
            and r.get("session_id")
            and r.get("status") in ("done", "failed", "stopped")
        ),
        None,
    )
    if not target:
        raise Conflict("no finished grind session to reply to")
    try:
        ui_runner.send_prompt(target["id"], f"Human decision on the paused grind (PR #{pr}): {SKIP_CI_REPLY}")
    except (ui_runner.Conflict, ui_runner.RunnerError, OSError) as e:
        raise Conflict(str(e))
    ui_runner._set_header(path, "paused", None)
    return {"state": "running"}


def stop(repo: str, pr: int) -> dict:
    """End the loop from the UI: `done:` in its header, which the re-entry timer skips. The PR stays open."""
    path, h = _loop(repo, pr)
    if "done" not in h:
        ui_runner._set_header(path, "done", f"{ui_runner._iso(datetime.now(timezone.utc))} \u2014 stopped from the UI")
    return {"ok": True, "state": "done"}


def _data(snap) -> dict:
    """Accepts a poller snapshot ({data, ...}) or bare snapshot data."""
    snap = snap or {}
    return snap.get("data") if isinstance(snap.get("data"), dict) else snap


def _prs(data: dict) -> dict:
    """{pr number: pr} over every open PR the snapshot knows (issue-linked and bare)."""
    out = {p["n"]: p for p in data.get("open_prs") or []}
    for i in data.get("issues") or []:
        for p in i.get("prs") or []:
            if p.get("state", "OPEN") == "OPEN":
                out.setdefault(p["n"], p)
    return out


def turned_ready(snapshot, prev) -> list:
    """Open PRs that were drafts in `prev` and are not now. A PR first seen ready is not "turned"."""
    before = _prs(_data(prev))
    return [p for n, p in _prs(_data(snapshot)).items() if not p.get("draft") and before.get(n, {}).get("draft")]


def autostart(repo: str, snapshot: dict, prev_snapshot: dict, settings: dict, start=None) -> list:
    """Start `/pr-grind <pr url>` (plus the repo's Slack channel) for each PR that turned ready since the
    previous poll, when the repo has auto_grind on. Returns the PR numbers started. Nothing on stale data,
    nothing for a PR with a grind state file (any state) or a live grind (start_session answers 409)."""
    if not (settings or {}).get("auto_grind") or (snapshot or {}).get("stale", True):
        return []
    if start is None:
        import ui_repos

        start = ui_repos.start_session
    owner, _, name = repo.lower().partition("/")
    have = {(h["owner"].lower(), h["repo"].lower(), int(h["number"])) for _, h in _state_files()}
    started = []
    for p in turned_ready(snapshot, prev_snapshot):
        if (owner, name, p["n"]) in have:
            continue
        text = grind_text(p["url"], (settings or {}).get("slack_channel"))
        status, body = start({"repo": repo, "text": text})
        if status == 201:
            started.append(p["n"])
        elif status != 409:
            warn(f"grind autostart {repo}#{p['n']}: {status} {body.get('error') if isinstance(body, dict) else body}")
    return started


def grind_text(pr_url: str, channel) -> str:
    """The /pr-grind prompt; `--channel <id>` names the repo's Slack channel (pr-grind's channels config otherwise)."""
    ch = str(channel or "").strip()
    return f"/pr-grind {pr_url}" + (f" --channel {ch}" if ch and ch.replace("_", "").isalnum() else "")


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
