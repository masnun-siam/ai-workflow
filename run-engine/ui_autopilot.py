"""Guarded start and the autopilot tick (FR-15, FR-16, FR-19). Stdlib only.

`start(repo, skill, arg, via)` is the one door for starting a skill from a card or from autopilot. Under a
per-repo lock it refuses (Conflict, HTTP 409) an implement-issue start for an issue that has a live session or
an open PR, or is blocked by an open issue; pr-grind's per-PR double-start guard is ui_repos.start_session's.
`tick(repo, snapshot, sessions, settings)` runs after each fresh poll and starts eligible issues of the
autopilot epics (refined, unblocked, no open PR, no live session) in `priority:` then number order, up to
`autopilot_cap` minus the live implement-issue sessions of the repo. Never on stale data.

ponytail: herdr-started tabs are not sessions, so they neither count against the cap nor show as live; the
`_recent` window (30 s) is what stops a double start from a double click or two racing ticks.
"""

from __future__ import annotations

import os
import re
import sys
import threading
import time

import dispatch
import ui_delivery
import ui_grind
import ui_panel
import ui_poller
import ui_repos
import ui_sessions
from shared import run

SKILLS = ("create-tasks", "refine-issues", "implement-issue", "pr-grind", "peer-review")
RECENT_SECONDS = 30
_RANK = {"high": 0, "medium": 1, "low": 2}
_locks: dict = {}
_locks_guard = threading.Lock()
_recent: dict = {}  # (repo, skill, arg) -> monotonic time of the last start


class Conflict(Exception):
    """The start is refused (HTTP 409)."""


def _lock(repo: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(repo.lower(), threading.RLock())


def _herdr(argv):
    return run(["herdr", *argv], timeout=60)


def _checkout(repo: str) -> str:
    path = next((p for k, p in dispatch.read_checkouts().items() if k.lower() == repo.lower()), None)
    if not isinstance(path, str) or not os.path.isdir(path):
        raise ValueError(f"no local checkout registered for {repo}")
    return path


def _issue(snapshot, n: int):
    return next((i for i in (snapshot.get("data") or {}).get("issues") or [] if i["n"] == n), None)


def _guard_implement(repo, n, snapshot, sessions) -> None:
    if n in ui_delivery._live_sessions(repo, sessions):
        raise Conflict(f"#{n} already has a live session")
    i = _issue(snapshot, n)
    if i is None:
        return  # not in the snapshot (closed, or nothing fetched yet): the session itself will sort it out
    if any(p["state"] == "OPEN" for p in i["prs"]):
        raise Conflict(f"#{n} already has an open PR")
    if any(p["state"] == "MERGED" for p in i["prs"]):
        raise Conflict(f"#{n}'s PR is already merged")
    blockers = [b["n"] for b in i["blocked_by"] if b["state"] == "OPEN"]
    if blockers:
        raise Conflict(f"#{n} is blocked by " + ", ".join(f"#{b}" for b in blockers))


def _via_herdr(repo, skill, arg, herdr) -> dict:
    cwd = _checkout(repo)
    label = (
        f"issue-{arg}"
        if skill in ("implement-issue", "pr-grind")
        else f"{skill}-{re.sub(r'[^A-Za-z0-9]+', '-', arg)[-24:].strip('-')}"
    )
    made = herdr(["tab", "create", "--cwd", cwd, "--label", label])
    pane = ((made.stdout or "").split() or [""])[-1]  # herdr prints the new pane id last
    if made.returncode != 0 or not pane:
        raise RuntimeError(f"herdr tab create failed: {(made.stderr or made.stdout or '').strip()[:200]}")
    for argv in (
        ["agent", "start", label, "--kind", "claude", "--pane", pane],
        ["agent", "prompt", label, f"/ai-workflow:{skill} {arg}"],
    ):
        res = herdr(argv)
        if res.returncode != 0:
            raise RuntimeError(f"herdr {argv[1]} failed: {(res.stderr or res.stdout or '').strip()[:200]}")
    return {"session": f"herdr:{label}", "via": "herdr"}


def start(
    repo,
    skill,
    arg,
    via="headless",
    *,
    lenses=None,
    snapshot=None,
    sessions=None,
    launch=None,
    herdr=None,
    channel=None,
) -> dict:
    """{session} (headless: the session id; herdr: `herdr:<tab label>`) or {panel} for peer-review.
    ValueError -> 400, Conflict -> 409, RuntimeError -> 502."""
    if skill not in SKILLS:
        raise ValueError(f"skill must be one of {', '.join(SKILLS)}")
    if via not in ("headless", "herdr"):
        raise ValueError("via must be headless or herdr")
    arg = str(arg if arg is not None else "").strip()
    if not arg or arg.startswith("-") or any(c in arg for c in "\x00\n"):
        raise ValueError("arg is required")
    if skill in ("implement-issue", "refine-issues"):
        if not re.fullmatch(r"#?\d+", arg):
            raise ValueError(f"{skill} takes an issue number")
        arg = arg.lstrip("#")
    elif skill == "pr-grind" and not re.fullmatch(r"#?\d+|https://\S+", arg):
        raise ValueError("pr-grind takes a PR number or URL")
    if skill == "peer-review" and via == "herdr":
        raise ValueError("peer-review starts headless")
    with _lock(repo):
        snapshot = snapshot if snapshot is not None else ui_poller.snapshot(repo)
        if skill == "implement-issue":
            _guard_implement(
                repo, int(arg), snapshot, sessions if sessions is not None else ui_sessions.list_sessions()
            )
        key, now = (repo.lower(), skill, arg), time.monotonic()
        if now - _recent.get(key, -1e9) < RECENT_SECONDS:
            raise Conflict(f"{skill} {arg} was just started")
        if skill == "peer-review":
            path = arg if os.path.isabs(arg) else os.path.join(_checkout(repo), arg)
            out = {"panel": ui_panel.start(_checkout(repo), path, lenses)}
        elif via == "herdr":
            out = _via_herdr(repo, skill, arg, herdr or _herdr)
        else:
            text = f"/{skill} {arg}"
            if skill == "pr-grind":
                text = ui_grind.grind_text(arg, channel)
            status, body = (launch or ui_repos.start_session)({"repo": repo, "text": text})
            if status == 409:
                raise Conflict(body.get("error", "already running"))
            if status != 201:
                raise (ValueError if status == 400 else RuntimeError)(body.get("error", f"start failed ({status})"))
            out = {"session": body["id"]}
        _recent[key] = now
        return out


def _rank(i) -> tuple:
    return (_RANK.get((i.get("priority") or "").lower(), 3), i["n"])


def tick(repo, snapshot, sessions, settings, **kw) -> list:
    """Start eligible issues up to the cap; returns the issue numbers started. `kw` goes to `start`."""
    if (snapshot or {}).get("stale", True):
        return []
    epics = ui_delivery._epics(settings)
    if not epics:
        return []
    cap = (settings or {}).get("autopilot_cap") or ui_delivery.DEFAULT_CAP
    with _lock(repo):  # the whole pass: a racing tick waits, then sees these starts in _recent
        return _tick(repo, snapshot, sessions, epics, cap, kw)


def _tick(repo, snapshot, sessions, epics, cap, kw) -> list:
    started = []
    now = time.monotonic()
    live = set(ui_delivery._live_sessions(repo, sessions)) | {
        int(a)
        for (r, s, a), t in _recent.items()
        if r == repo.lower() and s == "implement-issue" and now - t < RECENT_SECONDS
    }
    slots = cap - len(live)
    eligible = sorted(
        (
            i
            for i in snapshot["data"].get("issues") or []
            if "refined" in i["labels"]
            and "epic" not in i["labels"]
            and i["parent"] in epics
            and i["n"] not in live
            and not any(b["state"] == "OPEN" for b in i["blocked_by"])
            and not any(p["state"] in ("OPEN", "MERGED") for p in i["prs"])
        ),
        key=_rank,
    )
    for i in eligible:
        if slots <= 0:
            break
        try:
            start(repo, "implement-issue", i["n"], "headless", snapshot=snapshot, sessions=sessions, **kw)
        except Conflict:
            continue  # another tick or a person got there first; it counts in the next tick
        except (ValueError, RuntimeError) as exc:
            print(f"ui_autopilot: {repo}#{i['n']}: {exc}", file=sys.stderr)
            continue
        started.append(i["n"])
        slots -= 1
    return started
