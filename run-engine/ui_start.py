"""Guarded start of a skill from a card or the Start dialog (FR-15, FR-19). Stdlib only.

`start(repo, skill, arg)` is the one door. Under a per-repo lock it refuses (Conflict, HTTP 409) an
implement-issue start for an issue that has a live session, an open PR, a lane in a running dispatch, or an
open blocker; pr-grind's per-PR double-start guard is ui_repos.start_session's. Running an epic's issues in
parallel is a dispatch's job (dispatch_run), not this module's.

ponytail: the `_recent` window (30 s) is what stops a double start from a double click.
"""

from __future__ import annotations

import os
import re
import threading
import time

import dispatch
import dispatch_run
import repo_skills
import ui_delivery
import ui_grind
import ui_panel
import ui_poller
import ui_repos
import ui_sessions
import ui_settings

SKILLS = ("create-tasks", "refine-issues", "implement-issue", "pr-grind", "peer-review")
RECENT_SECONDS = 30
_locks: dict = {}
_locks_guard = threading.Lock()
_recent: dict = {}  # (repo, skill, arg) -> monotonic time of the last start


class Conflict(Exception):
    """The start is refused (HTTP 409). `id`: the live session that already does the work, when there is one."""

    def __init__(self, message, id=None):
        super().__init__(message)
        self.id = id


def _lock(repo: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(repo.lower(), threading.RLock())


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
    owned = dispatch_run.active_lane(repo, n=n)
    if owned:
        raise Conflict(f"#{n} runs in dispatch {owned[0]}")
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


def _guard_refine(repo, arg, sessions) -> None:
    """A live /refine-issues session that already covers any of these issues refuses the start."""
    want = set(arg.split())
    for rec in sessions:
        p = repo_skills.parse(rec.get("command"))
        if (
            p
            and p[0] == "refine-issues"
            and rec.get("status") in ui_sessions._LIVE
            and str(ui_delivery._slug(rec)).lower() == repo.lower()
            and want & set(re.findall(r"\d+", p[1]))
        ):
            raise Conflict(f"/refine-issues is already running for {arg}", rec.get("id"))


def start(
    repo,
    skill,
    arg,
    *,
    lenses=None,
    snapshot=None,
    sessions=None,
    launch=None,
    channel=None,
    model=None,
    effort=None,
    issue=None,
    claude_cmd=None,
    pin_account=False,
) -> dict:
    """{session} (the session id), or {panel} for peer-review.
    ValueError -> 400, Conflict -> 409, RuntimeError -> 502."""
    if skill not in SKILLS:
        raise ValueError(f"skill must be one of {', '.join(SKILLS)}")
    arg = str(arg if arg is not None else "").strip()
    if not arg or arg.startswith("-") or any(c in arg for c in "\x00\n"):
        raise ValueError("arg is required")
    if skill == "implement-issue":
        if not re.fullmatch(r"#?\d+", arg):
            raise ValueError(f"{skill} takes an issue number")
        arg = arg.lstrip("#")
    elif skill == "refine-issues":  # an epic number, or several issue numbers
        if not re.fullmatch(r"#?\d+(?:[\s,]+#?\d+)*", arg):
            raise ValueError("refine-issues takes an epic or issue numbers")
        arg = " ".join(n.lstrip("#") for n in re.split(r"[\s,]+", arg))
    elif skill == "pr-grind" and not re.fullmatch(r"#?\d+|https://\S+", arg):
        raise ValueError("pr-grind takes a PR number or URL")
    if issue is None and skill == "refine-issues" and arg.isdigit():  # one issue: link the session to it
        issue = int(arg)
    ui_settings.check_run(model, effort)
    with _lock(repo):
        snapshot = snapshot if snapshot is not None else ui_poller.snapshot(repo)
        if skill == "implement-issue":
            _guard_implement(
                repo, int(arg), snapshot, sessions if sessions is not None else ui_sessions.list_sessions()
            )
        if skill == "refine-issues":
            _guard_refine(repo, arg, sessions if sessions is not None else ui_sessions.list_sessions())
        key, now = (repo.lower(), skill, arg), time.monotonic()
        if now - _recent.get(key, -1e9) < RECENT_SECONDS:
            raise Conflict(f"{skill} {arg} was just started")
        if skill == "peer-review":
            path = arg if os.path.isabs(arg) else os.path.join(_checkout(repo), arg)
            out = {"panel": ui_panel.start(_checkout(repo), path, lenses)}
        else:
            text = f"/{skill} {arg}"
            if skill == "pr-grind":
                text = ui_grind.grind_text(arg, channel)
            status, body = (launch or ui_repos.start_session)(
                {
                    "repo": repo,
                    "text": text,
                    **{k: v for k, v in (("model", model), ("effort", effort)) if v},
                    **({"issue": issue} if issue is not None else {}),
                    **({"claude_cmd": claude_cmd} if claude_cmd else {}),
                    **({"pin_account": True} if pin_account else {}),
                }
            )
            if status == 409:
                raise Conflict(body.get("error", "already running"))
            if status != 201:
                raise (ValueError if status == 400 else RuntimeError)(body.get("error", f"start failed ({status})"))
            out = {"session": body["id"]}
        _recent[key] = now
        return out
