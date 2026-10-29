"""Owner routes for PRD share links (`/api/shares...`), pure of HTTP: `handle` returns `(status, body)`.

`ui_server._Handler` calls it behind `_guard`; the public share listener never does. A 204 carries body None.
Errors from the store and the runtime are mapped to statuses here, so nothing is raised past `handle`.
Never puts a token (outside `url`), `key_hash` or a withdraw key in a response.
"""

from __future__ import annotations

import threading

import dispatch
import shared
import ui_actions
import ui_share_runtime as runtime
import ui_shares
import ui_tailscale

_start_lock = threading.Lock()  # two clicks on one PRD make one share
_STATUS = {"invalid": 400, "not_found": 404, "conflict": 409, "full": 409, "rate": 429}
_NOT_FOUND = (404, {"error": "share not found"})


def _checkouts() -> dict:
    return dispatch.read_checkouts()


def _registered(repo) -> str:
    slug = next((k for k in _checkouts() if isinstance(repo, str) and k.lower() == repo.lower()), None)
    if not slug:
        raise ValueError(f"unknown repo: {repo!r}")
    return slug


def _author(checkout) -> str:
    proc = shared.run(["git", "config", "user.name"], cwd=checkout)
    return (proc.stdout or "").strip() if proc.returncode == 0 and (proc.stdout or "").strip() else "Author"


def _summary(share: dict) -> dict:
    live = share["state"] == "live"
    un = ui_shares.unread(share)
    st = ui_shares.prd_state(_checkouts().get(share["repo"]), share["path"])
    return {
        "id": share["id"],
        "repo": share["repo"],
        "path": share["path"],
        "title": st["title"],
        "state": share["state"],
        "url": runtime.link(share) if live else None,
        "comments": ui_shares.reviewer_comment_count(share),
        "unread": un["comments"] + un["approvals"],
        "reachable": runtime.reachable() if live else False,
        "end_reason": share.get("end_reason"),
        "_prd_updated_at": st["updated_at"],
    }


def _view(share: dict, detail: bool = False) -> dict:
    out = _summary(share)
    updated = out.pop("_prd_updated_at")
    if detail:
        out.update(
            threads=[{**ui_shares.public_thread(t), "id": t["id"]} for t in share["threads"]],
            approvals=[{"id": a["id"], "name": a["name"], "at": a["at"]} for a in share["approvals"]],
            last_seen_at=share.get("last_seen_at"),
            prd_updated_at=updated,
        )
    return out


def _end_check() -> None:
    """End live shares whose PRD left Draft or In review; release the runtime when none is left live."""
    ended = False
    for share in ui_shares.list_shares():
        if share["state"] == "live":
            after = ui_shares.refresh(share["id"], _checkouts().get(share["repo"]))
            ended = ended or after is None or after["state"] != "live"
    if ended:
        runtime.sync()


def _list():
    _end_check()
    return 200, [_view(s) for s in ui_shares.list_shares()]


def _get(sid):
    _end_check()
    share = ui_shares.get(sid)
    return (200, _view(share, detail=True)) if share else _NOT_FOUND


def _start(body):
    body = body or {}
    repo = _registered(body.get("repo"))
    checkout, rel = _checkouts()[repo], body.get("path")
    ui_actions._prd_path(checkout, rel)  # ValueError: bad path or no such file
    with _start_lock:
        sid = ui_shares.share_id(repo, rel)
        share = ui_shares.refresh(sid, checkout)
        if share is not None and share["state"] == "live":
            runtime.sync()  # FR-12: retry a share that is not reachable
            return 200, _view(share)
        if body.get("confirm") is not True:
            return 400, {"error": "confirm must be true"}
        reason = ui_shares.prd_state(checkout, rel)["reason"]
        if reason:
            raise ui_shares.ShareError("conflict", "only Draft or In review PRDs can be shared")
        try:
            runtime.ensure_up()
        except ui_tailscale.FunnelError as e:
            return (409 if e.kind == "port_taken" else 503), {"error": str(e)}
        try:
            share, created = ui_shares.create(repo, rel, checkout)
        except BaseException:
            runtime.sync()  # nothing live: take the funnel down again
            raise
        return (201 if created else 200), _view(share)


def _stop(sid):
    share = ui_shares.end(sid, "stopped")
    if share is None:
        return _NOT_FOUND
    runtime.sync()
    return 200, _view(share)


def _reply(sid, tid, body):
    share = ui_shares.get(sid)
    if share is None:
        return _NOT_FOUND
    author = _author(_checkouts().get(share["repo"]))
    return 201, ui_shares.public_comment(ui_shares.add_owner_comment(sid, tid, author, (body or {}).get("body")))


def _resolve(sid, tid, body):
    resolved = (body or {}).get("resolved")
    if not isinstance(resolved, bool):
        return 400, {"error": "resolved must be true or false"}
    t = ui_shares.set_resolved(sid, tid, resolved)
    return 200, {**ui_shares.public_thread(t), "id": t["id"]}


def _record(sid):
    ui_shares.delete_record(sid)
    runtime.sync()
    return 204, None


def _route(method, p, body, query):
    n = len(p)  # p: path parts after "shares"
    if method == "GET" and n == 0:
        return _list()
    if method == "POST" and n == 0:
        return _start(body)
    if method == "GET" and n == 1:
        return _get(p[0])
    if method == "DELETE" and n == 1:
        return _stop(p[0])
    if method == "POST" and n == 2 and p[1] == "seen":
        ui_shares.mark_seen(p[0])
        return 204, None
    if method == "DELETE" and n == 2 and p[1] == "record":
        return _record(p[0])
    if method == "DELETE" and n == 3 and p[1] == "threads":
        ui_shares.delete_thread(p[0], p[2])
        return 204, None
    if method == "PATCH" and n == 3 and p[1] == "threads":
        return _resolve(p[0], p[2], body)
    if method == "DELETE" and n == 3 and p[1] == "approvals":
        ui_shares.delete_approval(p[0], p[2])
        return 204, None
    if method == "POST" and n == 4 and p[1] == "threads" and p[3] == "comments":
        return _reply(p[0], p[2], body)
    if method == "DELETE" and n == 5 and p[1] == "threads" and p[3] == "comments":
        ui_shares.delete_comment(p[0], p[2], p[4])
        return 204, None
    return 404, {"error": "not found"}


def handle(method: str, parts: list, body=None, query: str = ""):
    """`parts` is the split path (`["", "api", "shares", ...]`). Returns (status, body)."""
    try:
        return _route(method, parts[3:], body, query)
    except ui_shares.ShareError as e:
        return _STATUS.get(e.kind, 400), {"error": str(e)}
    except ValueError as e:
        return 400, {"error": str(e)}
    except ui_tailscale.FunnelError as e:
        return (409 if e.kind == "port_taken" else 503), {"error": str(e)}
    except (OSError, RuntimeError) as e:
        return 502, {"error": str(e)}
