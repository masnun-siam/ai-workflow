#!/usr/bin/env python3
"""`aiw ui` — loopback-only workflow control UI server.

Every request passes a Host/Origin guard (DNS-rebinding and cross-site defence);
no CORS headers are ever emitted.
"""

from __future__ import annotations

import errno
import http.server
import json
import mimetypes
import os
import shlex
import signal
import glob
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit

import peer_review
import dispatch
import dispatch_run
import jev
import ui_actions
import ui_afk
import ui_bootstrap
import ui_cleanup
import ui_config
import ui_delivery
import ui_dispatch
import ui_events
import ui_feed
import ui_gh
import ui_grind
import ui_inbox
import ui_issue
import ui_mergeclean
import ui_migrate
import ui_notify
import ui_origin
import ui_panel
import ui_planning
import ui_poller
import ui_pr
import ui_repos
import ui_restart
import ui_duplicate
import ui_route
import ui_runner
import ui_share_api
import ui_share_runtime
import ui_sessions
import ui_start
import ui_settings
import ui_shares
import ui_tailscale
import ui_urgency
import ui_usage
import ui_vault
import ui_watch
import shared
from shared import die, warn


mimetypes.add_type("application/manifest+json", ".webmanifest")
DIST_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui_dist")  # the built app (committed; see ui/)


def _serve_static(handler, rel: str) -> None:
    """The built app: index.html and anything outside assets/ revalidate, hashed assets/* are immutable."""
    root = os.path.realpath(DIST_DIR)
    try:
        # unquote once only: %252e stays literal; realpath containment (not string checks) blocks escapes
        full = os.path.realpath(os.path.join(root, unquote(rel).lstrip("/")))
        if os.path.commonpath([root, full]) != root or not os.path.isfile(full):
            raise FileNotFoundError
        with open(full, "rb") as f:
            body = f.read()
    except (ValueError, FileNotFoundError, IsADirectoryError):
        handler._send(404, "text/plain; charset=utf-8", b"not found")
        return
    except OSError as e:  # e.g. PermissionError: broken install, not a missing file
        print(f"ui_server: cannot read {rel!r}: {e}", file=sys.stderr)
        handler._send(500, "text/plain; charset=utf-8", b"internal error")
        return
    ext = os.path.splitext(full)[1].lower()
    ctype = "text/javascript" if ext in (".js", ".mjs") else mimetypes.guess_type(full)[0] or "application/octet-stream"
    if ctype.startswith("text/"):
        ctype += "; charset=utf-8"
    hashed = os.path.relpath(full, root).startswith("assets" + os.sep)
    cache = "public, max-age=31536000, immutable" if hashed else "no-cache"
    handler._send(200, ctype, body, {"Cache-Control": cache})


def _guard(handler) -> bool:
    host = (handler.headers.get("Host") or "").strip().lower()
    if host not in handler.server.allowed_hosts:
        handler._send(403, "text/plain; charset=utf-8", b"forbidden")
        return False
    if host in handler.server.tailnet_hosts:
        who = (handler.headers.get("Tailscale-User-Login") or "").strip().lower()
        if not who or who != (handler.server.tailnet_login or "").lower():
            handler._send(403, "text/plain; charset=utf-8", b"forbidden: tailnet access is limited to the node owner")
            return False
    origin = handler.headers.get("Origin")
    if origin is not None and urlsplit(origin.strip()).netloc.lower() != host:
        handler._send(403, "text/plain; charset=utf-8", b"forbidden")
        return False
    return True


def _can_browse(handler) -> bool:
    """The folder dialog opens on the server's screen, so only offer it to a local macOS browser."""
    host = (handler.headers.get("Host") or "").strip().lower().rsplit(":", 1)[0]
    return sys.platform == "darwin" and host in ("127.0.0.1", "localhost")


MAX_BODY = 65536


def _panel_of(rec: dict):
    """The panel a session roots or reviews for: its status plus the session's part in it."""
    if not rec.get("panel"):
        return None
    try:
        return {**ui_panel.public(rec["panel"]), "role": rec.get("panel_role"), "lens": rec.get("panel_lens")}
    except (FileNotFoundError, ValueError):
        return None


def _bootstrap_of(rec: dict):
    """The bootstrap run a session belongs to, or None."""
    if not rec.get("bootstrap"):
        return None
    try:
        return ui_bootstrap.load(rec["bootstrap"])
    except ValueError:
        return None


def _public(rec: dict) -> dict:
    p, sid = rec.get("cwd_path"), rec.get("session_id")
    return {
        "id": rec.get("id"),
        "command": rec.get("command"),
        "repo": rec.get("repo"),
        "link": rec.get("link"),
        "slug": ui_delivery._slug(rec) or None,
        "session_id": rec.get("session_id"),
        "outcome": rec.get("status"),
        "cost": rec.get("cost"),
        "tokens": rec.get("tokens"),
        "model": rec.get("model") or rec.get("run_model"),
        "effort": rec.get("run_effort"),
        "started_at": rec.get("started_at"),
        "ended_at": rec.get("ended_at"),
        "waiting": rec.get("pending_question") is not None,
        "pending_question": rec.get("pending_question"),
        "error": rec.get("error"),
        "resumed_fresh": rec.get("resumed_fresh"),
        "note": rec.get("note"),
        "terminal_handoff": rec.get("terminal_handoff"),
        "pending_answer": rec.get("pending_answer"),
        "queued_prompt": rec.get("queued_prompt"),
        "claude_cmd": rec.get("claude_cmd"),
        "limit_resets_at": rec.get("limit_resets_at"),
        "limit_type": rec.get("limit_type"),
        "auto_resume": rec.get("auto_resume"),
        "no_repo": rec.get("no_repo") is True,
        "vault_folder": rec.get("vault_folder"),
        "peer_review": _panel_of(rec),
        "bootstrap": _bootstrap_of(rec),
        "repo_path": p,
        "resume_command": f"cd {shlex.quote(p)} && claude --resume {shlex.quote(sid)}" if p and sid else None,
    }


# engine-era API prefixes that no longer exist (POST answers 404, not 405)
_REMOVED = [["api", p] for p in ("runs", "pipelines", "flows", "notes", "dispatch", "maintree", "grind", "autopilot")]


# ---- boards: poller snapshots in memory, hooks after each fresh poll ----------------------------------

POLLER = ui_poller._default
_watched: set = set()  # repos opened since start: only the first look (a poll now) hangs off this; see _watched_copy
_watch_lock = threading.Lock()
VIEW_SECONDS = 120  # a repo the UI asked about this recently is polled on the normal cadence (see _hot)
_seen: dict = {}  # repo -> last request naming it; "*" -> last all-repos request (global Inbox, or a board without repo)
_flags: dict = {}  # repo -> {issue: {uncommitted, unpushed}}: merged issues whose cleanup was held back


def _registered(repo) -> str:
    """The registered slug for `repo` (case-insensitive); ValueError when it is not in the checkouts registry."""
    slug = next((k for k in dispatch.read_checkouts() if isinstance(repo, str) and k.lower() == repo.lower()), None)
    if not slug:
        raise ValueError(f"unknown repo: {repo!r}")
    return slug


def _watch(repo: str) -> None:
    ui_watch.touch(repo)
    with _watch_lock:
        _seen[repo] = time.time()
        new = repo not in _watched
        _watched.add(repo)
    if new:  # first look at this repo: fetch now, off the request thread (reads never wait on GitHub)
        threading.Thread(target=POLLER.poll, args=(repo,), daemon=True).start()


def _repoll(slug: str, out):
    """After a GitHub write: poll that repo now, on this thread, so the UI's refetch sees the change instead of
    data up to a minute old. Returns `out`. A repo that is not registered or a failed poll changes nothing."""
    try:
        POLLER.poll(_registered(slug), full=True)
    except (ValueError, OSError) as e:
        warn(f"repoll {slug}: {e}")
    return out


def _live_repos() -> set:
    return {ui_delivery._slug(r) for r in ui_sessions.list_sessions() if r.get("status") in ui_sessions._LIVE}


def _watched_copy() -> list:
    """Repos the poller keeps fresh: registered, with a GitHub remote, and opened in the last 7 days or live."""
    checkouts = dispatch.read_checkouts()
    names = {k.lower(): k for k in checkouts if not k.startswith("local/")}
    want = set(ui_watch.recent()) | _live_repos() | ui_dispatch.repos()
    return sorted({names[w.lower()] for w in want if w.lower() in names})


def _hot() -> set:
    """Repos on the normal poll cadence: viewed in the last VIEW_SECONDS (every watched one while the global
    Inbox is open) or with a live session (its hooks need fresh data). The rest poll every few minutes."""
    now = time.time()
    with _watch_lock:
        seen = {r for r, t in _seen.items() if now - t < VIEW_SECONDS}
    if "*" in seen:
        return set(_watched_copy())
    live = {r.lower() for r in _live_repos() | ui_dispatch.repos()}  # dispatch lanes need fresh facts
    return {r for r in _watched_copy() if r in seen or r.lower() in live}


def _link(repo: str, n: int) -> dict:
    owner, _, name = repo.partition("/")
    return {"owner": owner, "repo": name, "issue": n}


def _on_fresh(repo: str, snap: dict, prev: dict) -> None:
    """After a fresh, non-stale poll: notify, clean merged worktrees, grind autostart."""
    if snap.get("stale") or snap.get("fetched_at") is None:
        return
    settings = ui_settings.repo_settings(repo)
    first = prev == ui_poller.empty()  # nothing seen before: everything in the snapshot would look new
    if not first:
        for p in ui_grind.turned_ready(snap, {"data": prev}):
            ui_notify.notify(
                "pr-ready",
                {
                    "id": f"{repo}#{p['n']}:ready",
                    "repo": repo,
                    "link": _link(repo, p["n"]),
                    "note": f"PR #{p['n']} is ready for review",
                },
            )
        seen = {m["n"] for m in prev.get("merged") or []}
        issues = [n for m in snap["data"]["merged"] if m["n"] not in seen for n in m["closes"]]
        flagged = ui_mergeclean.on_merged(repo, issues) if issues else {}
        for n, f in flagged.items():
            if n not in _flags.setdefault(repo, {}):
                ui_notify.notify(
                    "needs-cleanup",
                    {
                        "id": f"{repo}#{n}:cleanup",
                        "repo": repo,
                        "link": _link(repo, n),
                        "note": f"#{n} merged; its worktree holds uncommitted or unpushed work",
                    },
                )
            _flags[repo][n] = f
    if not first:
        ui_grind.autostart(repo, snap, {"data": prev}, settings)


POLLER.on_fresh = _on_fresh
ui_origin.SNAPSHOT = POLLER.snapshot


def _panels(checkout: str) -> dict:
    """PRD slug -> id of the newest peer-review panel whose artifact is that PRD file."""
    base = os.path.join(peer_review.data_dir(), "peer-review")
    by_artifact = {}
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:  # ids start with a timestamp
        try:
            by_artifact[os.path.realpath(peer_review.load_panel(name)["artifact"])] = name
        except (OSError, ValueError, KeyError):
            continue
    out = {}
    for path in glob.glob(os.path.join(checkout, "docs", "prds", "*.md")):
        meta, panel = ui_planning._parse(path), by_artifact.get(os.path.realpath(path))
        if meta and panel:
            out[meta["slug"]] = panel
    return out


def _duplicate(b: dict) -> dict:
    """POST /api/duplicate: does the typed capture match an open issue or a PRD?"""
    repo = _registered(b.get("repo"))
    _watch(repo)  # a repo seen for the first time is polled, off this thread
    return ui_duplicate.check(repo, b.get("text"), POLLER.snapshot(repo), dispatch.read_checkouts()[repo])


def _board_body(path: str, repo: str, sessions=None, grinds=None) -> dict:
    """The body of GET /api/planning or /api/delivery for one registered repo, from memory. The all-repos call
    scans the sessions and grind state once and passes them in."""
    snap = POLLER.snapshot(repo)
    if path == "/api/planning":
        body = ui_planning.build(repo, dispatch.read_checkouts()[repo], snap, _panels(dispatch.read_checkouts()[repo]))
        for p in body["prds"]:
            p["account"] = ui_origin.prd_label(repo, os.path.splitext(os.path.basename(p["path"]))[0])
    else:
        body = ui_delivery.build(
            repo,
            snap,
            ui_sessions.list_sessions() if sessions is None else sessions,
            ui_grind.index() if grinds is None else grinds,
            ui_settings.repo_settings(repo),
            _flags.get(repo, {}),
            solo=ui_gh.solo(repo),
        )
    return {**body, "error": snap.get("error"), "retry_at": snap.get("retry_at")}


def _all_boards(path: str, refresh: bool):
    """(200, {repos, stale}) for the board endpoints without `repo`: one body per watched repo, sorted by slug.
    Counts as viewing every watched repo, like the global Inbox. A repo whose build raises is a meta-only entry."""
    with _watch_lock:
        _seen["*"] = time.time()
    watched = _watched_copy()
    if refresh:  # one thread for all repos, never the request thread
        threading.Thread(target=lambda: [POLLER.poll(r, full=True) for r in watched], daemon=True).start()
    sessions, grinds = ui_sessions.list_sessions(), ui_grind.index()
    repos = []
    for r in watched:
        try:
            repos.append(_board_body(path, r, sessions, grinds))
        except Exception as e:
            warn(f"{path} {r}: {e}")
            snap = POLLER.snapshot(r)
            repos.append(
                {
                    "repo": r,
                    "stale": True,
                    "fetched_at": snap.get("fetched_at"),
                    "error": str(e),
                    "retry_at": snap.get("retry_at"),
                }
            )
    stale = sorted(e["repo"] for e in repos if e.get("stale") or e.get("fetched_at") is None)
    return 200, {"repos": repos, "stale": stale}


def _board(path: str, query: str):
    """(status, body) for GET /api/planning and /api/delivery."""
    q = parse_qs(query)
    refresh = (q.get("refresh") or [""])[0] == "1"
    if not (q.get("repo") or [""])[0]:
        return _all_boards(path, refresh)
    try:
        repo = _registered(q["repo"][0])
    except ValueError as e:
        return 400, {"error": str(e)}
    _watch(repo)
    if refresh:  # the board's Refresh: fetch now, off this thread
        threading.Thread(target=POLLER.poll, args=(repo,), kwargs={"full": True}, daemon=True).start()
    return 200, _board_body(path, repo)


def _share_rows() -> list:
    """One row per share with unseen reviewer activity, live or ended (ui_inbox's `shares`)."""
    checkouts, rows = dispatch.read_checkouts(), []
    for s in ui_shares.list_shares():
        u = ui_shares.unread(s)
        if not (u["comments"] or u["approvals"]):
            continue
        title = ui_shares.prd_state(checkouts.get(s["repo"]), s["path"])["title"]
        rows.append(
            {
                "id": s["id"],
                "repo": s["repo"],
                "path": s["path"],
                "title": title or os.path.splitext(os.path.basename(s["path"]))[0],
                "comments": u["comments"],
                "approvals": u["approvals"],
                "at": u["at"],
            }
        )
    return rows


def _on_share_activity(share: dict, kind: str) -> None:
    """ui_shares listener: the throttled `prd-comment` push, carrying only the count and the title."""
    row = next((r for r in _share_rows() if r["id"] == share["id"]), None)
    if row:
        ui_notify.prd_comment(row["id"], ui_inbox.share_summary(row["comments"], row["approvals"], row["title"]))


def _inbox(query: str):
    """(status, body) for GET /api/inbox."""
    repo = (parse_qs(query).get("repo") or [""])[0]
    if repo:
        try:
            repo = _registered(repo)
        except ValueError as e:
            return 400, {"error": str(e)}
        _watch(repo)
    else:
        with _watch_lock:
            _seen["*"] = time.time()
    watched = [repo] if repo else _watched_copy()
    recs = ui_sessions.list_sessions()
    body = _inbox_items(repo, watched, recs)
    return 200, {**body, "afk": ui_afk.public(recs), "gh": ui_gh.status()}


def _inbox_items(repo, watched, recs) -> dict:
    """The Inbox body {items, stale}: built, merged with the dispatch lanes, ranked by cached urgency."""
    labels = {c["cmd"]: c["label"] for c in ui_settings.load()["commands"]}
    body = ui_inbox.build(
        sessions=recs,
        panels=ui_panel.rows(),
        shares=_share_rows(),
        grind_index=ui_grind.index(),
        flags=_flags,
        repos=ui_repos.list_repos(),
        snapshots={r: POLLER.snapshot(r) for r in watched},
        gh=ui_gh.status(),
        alive=set(ui_runner._procs),
        account_labels=labels,
        slug=ui_delivery._slug,
        watched=watched,
        repo=repo or None,
        settings={r: ui_settings.repo_settings(r) for r in watched},
        solo={r: ui_gh.solo(r) for r in watched},
        bootstraps=ui_bootstrap.list_all(),
    )
    dispatches = dispatch_run.list_all()
    lanes = [i for i in ui_dispatch.inbox_items(dispatches) if not repo or i["repo"].lower() == repo.lower()]
    mine = ui_dispatch.drop_owned(body["items"], dispatches)  # a dispatch's issue shows once: as its lane
    body["items"] = ui_inbox.rank(mine + lanes, ui_urgency.urgency)
    return body


class _NotFound(Exception):
    """An unknown id in a POST route (HTTP 404)."""


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, status: int, content_type: str, body: bytes, headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not _guard(self):
            return
        path = urlsplit(self.path).path
        if path == "/":
            _serve_static(self, "index.html")
        elif path in ("/sw.js", "/manifest.webmanifest") or path.startswith(("/assets/", "/icons/")):
            _serve_static(self, path)  # sw.js at the root so its scope covers the whole app
        elif path == "/api/health":
            self._send(200, "application/json; charset=utf-8", b'{"ok": true}')
        elif path == "/api/restart":
            self._json(200, ui_restart.status())
        elif path == "/api/repos":
            self._json(
                200,
                {
                    "repos": ui_repos.list_repos(),
                    "can_browse": _can_browse(self),
                    "scan_roots": ui_repos.default_roots(),
                },
            )
        elif path == "/api/inbox":
            self._json(*_inbox(urlsplit(self.path).query))
        elif path == "/api/notifications":
            v = (parse_qs(urlsplit(self.path).query, keep_blank_values=True).get("after") or [None])[0]
            if v is not None and not (v.isascii() and v.isdigit()):
                self._json(400, {"error": "after must be a whole number"})
            else:
                self._json(200, ui_feed.after(int(v) if v is not None else None))
        elif path in ("/api/planning", "/api/delivery"):
            self._json(*_board(path, urlsplit(self.path).query))
        elif path == "/api/settings":
            self._json(200, ui_settings.load())
        elif path == "/api/settings/notify":
            self._json(200, ui_config.notify_public())
        elif path == "/api/settings/review":
            self._json(200, ui_config.review_public())
        elif path == "/api/github/owners":
            self._json(*ui_vault.github_owners())
        elif path == "/api/github/branches":
            self._json(*ui_gh.branches((parse_qs(urlsplit(self.path).query).get("repo") or [""])[0]))
        elif path == "/api/vault/folders":
            self._json(200, {"vault": ui_vault.vault(), "folders": ui_vault.folders()})
        elif path == "/api/vault/prd":
            folder = (parse_qs(urlsplit(self.path).query).get("folder") or [""])[0]
            try:
                self._json(200, ui_vault.prd_info(folder))
            except ValueError as e:
                self._json(400, {"error": str(e)})
        elif path == "/api/prd":
            q = parse_qs(urlsplit(self.path).query)
            try:
                repo = _registered((q.get("repo") or [""])[0])
                self._json(200, ui_actions.read_prd(dispatch.read_checkouts()[repo], (q.get("path") or [""])[0]))
            except ValueError as e:
                self._json(400, {"error": str(e)})
        elif path == "/api/shares" or path.startswith("/api/shares/"):
            self._shares(path)
        elif path == "/api/peer-review":
            self._json(200, peer_review.offers())
        elif path == "/api/dispatches":
            self._json(200, {"dispatches": [ui_dispatch.public(d) for d in dispatch_run.list_all()]})
        elif path == "/api/bootstraps":
            try:
                repo = (parse_qs(urlsplit(self.path).query).get("repo") or [""])[0]
                runs = ui_bootstrap.list_all()
                if repo:
                    repo = _registered(repo).lower()
                    runs = [r for r in runs if r["repo"].lower() == repo]
                self._json(200, {"runs": runs})
            except ValueError as e:
                self._json(400, {"error": str(e)})
        elif path.startswith("/api/dispatches/"):
            self._dispatch_get(path.split("/")[3:])
        elif path == "/api/sessions/cleanup":
            self._json(200, {"items": ui_cleanup.find_targets()})
        elif path == "/api/sessions":
            recs = ui_sessions.list_sessions()
            body = {
                "sessions": [_public(r) for r in recs if not ui_sessions.is_answerer(r)],
                "limits": ui_runner.limits(),
                "usage": ui_usage.snapshot(),
                "afk": ui_afk.public(recs),
                "gh": ui_gh.status(),
            }
            self._send(200, "application/json; charset=utf-8", json.dumps(body).encode("utf-8"))
        else:
            parts = path.split("/")
            if (
                len(parts) in (4, 5)
                and parts[:3] == ["", "api", "sessions"]
                and (len(parts) == 4 or parts[4] == "stream")
            ):
                self._session(parts[3], len(parts) == 5)
            elif len(parts) == 6 and parts[:3] == ["", "api", "issues"]:
                if ui_issue.valid(*parts[3:]):
                    self._json(*ui_issue.fetch(*parts[3:]))
                else:
                    self._json(400, {"error": "bad issue id"})
            elif len(parts) == 6 and parts[:3] == ["", "api", "repos"] and parts[5] == "open":
                if ui_issue.valid(parts[3], parts[4], "1"):
                    kind = (parse_qs(urlsplit(self.path).query).get("kind") or ["issue"])[0]
                    self._json(*ui_issue.open_items(parts[3], parts[4], kind))
                else:
                    self._json(400, {"error": "bad repo"})
            elif len(parts) == 6 and parts[:3] == ["", "api", "pulls"]:
                if ui_pr.valid(*parts[3:]):
                    self._json(*ui_pr.fetch(*parts[3:]))
                else:
                    self._json(400, {"error": "bad pull request id"})
            else:
                self._send(404, "text/plain; charset=utf-8", b"not found")

    def _session(self, sid: str, stream: bool) -> None:
        try:
            rec = ui_sessions.load(sid)
        except ValueError:
            rec = None
        if rec is None:
            self._send(404, "text/plain; charset=utf-8", b"not found")
            return
        if not stream:
            body = _public(rec)
        else:
            raw = parse_qs(urlsplit(self.path).query, keep_blank_values=True).get("offset", ["0"])[0]
            try:
                offset = int(raw)
            except ValueError:
                offset = -1
            if offset < 0:
                self._send(400, "text/plain; charset=utf-8", b"bad offset")
                return
            sp = os.path.join(ui_sessions.session_dir(sid), "stream.jsonl")
            events, new_offset = ui_events.read_from(sp, offset)
            if rec.get("status") in ("done", "failed", "stopped"):
                # terminal session: no more writes, so an unterminated last line is complete
                try:
                    with open(sp, "rb") as f:
                        f.seek(new_offset)
                        tail = f.read()
                except FileNotFoundError:
                    tail = b""
                if tail:
                    events += ui_events.parse_line(tail)
                    new_offset += len(tail)
            body = {"events": events, "offset": new_offset}
        self._send(200, "application/json; charset=utf-8", json.dumps(body).encode("utf-8"))

    def _dispatch_get(self, rest: list) -> None:
        """GET /api/dispatches/<id> (with events) and /api/dispatches/<id>/lane?key=<owner/repo#n>."""
        try:
            if len(rest) == 1:
                self._json(200, ui_dispatch.public(dispatch_run.load(rest[0]), full=True))
            elif len(rest) == 2 and rest[1] == "lane":
                key = (parse_qs(urlsplit(self.path).query).get("key") or [""])[0]
                self._json(200, ui_dispatch.read_lane(rest[0], key))
            else:
                self._send(404, "text/plain; charset=utf-8", b"not found")
        except ValueError as e:
            self._json(404 if "no dispatch" in str(e) else 400, {"error": str(e)})
        except (RuntimeError, OSError) as e:
            self._json(502, {"error": str(e)})

    def _dispatch_post(self, rest: list) -> None:
        """POST /api/dispatches, /plan, /<id>/settings|state|lane|end|seen."""
        did = rest[0] if rest else ""
        op = rest[1] if len(rest) == 2 else None
        if not rest:
            self._dispatch(ui_dispatch.start, ok=201)
        elif rest == ["plan"]:
            self._dispatch(ui_dispatch.plan)
        elif op == "settings":
            self._dispatch(lambda b: ui_dispatch.set_settings(did, b))
        elif op == "state":
            self._dispatch(lambda b: ui_dispatch.public(dispatch_run.set_state(did, b.get("state"))))
        elif op == "lane":
            self._dispatch(
                lambda b: ui_dispatch.public(
                    dispatch_run.lane_action(did, b.get("lane"), b.get("action"), b.get("text"))
                )
            )
        elif op == "end":
            self._dispatch(lambda b: ui_dispatch.public(dispatch_run.request_end(did, b.get("action"))))
        elif op == "seen":
            self._dispatch(lambda b: ui_dispatch.seen(did))
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found")

    def _bootstrap_post(self, rid: str, op: str) -> None:
        """POST /api/bootstraps/<id>/continue|retry|stop; an unknown id is 404."""
        fn = {"continue": ui_bootstrap.continue_run, "retry": ui_bootstrap.retry, "stop": ui_bootstrap.stop}[op]

        def call(_body):
            try:
                return fn(rid)
            except ValueError as e:
                if str(e).startswith(("no bootstrap", "bad bootstrap id")):
                    raise _NotFound(str(e)) from e
                raise

        try:
            self._dispatch(call)
        except _NotFound as e:
            self._json(404, {"error": str(e)})

    def _json(self, status: int, body) -> None:
        self._send(status, "application/json; charset=utf-8", json.dumps(body).encode("utf-8"))

    def do_POST(self):
        if not _guard(self):
            return
        parts = urlsplit(self.path).path.split("/")
        if parts == ["", "api", "sessions"]:
            self._start()
        elif parts == ["", "api", "restart"]:
            self._dispatch(lambda b: ui_restart.start(), ok=202)
        elif parts == ["", "api", "route"]:
            self._dispatch(lambda b: ui_route.route(b.get("text")))
        elif parts == ["", "api", "duplicate"]:
            self._dispatch(_duplicate)
        elif parts == ["", "api", "repos", "browse"]:
            body = self._read_body()
            if body is None:
                return
            if _can_browse(self):
                self._json(200, {"path": ui_repos.browse_folder(body.get("start"))})
            else:
                self._json(403, {"error": "folder picker is only available locally on macOS"})
        elif parts == ["", "api", "sessions", "cleanup"]:
            self._cleanup()
        elif parts == ["", "api", "vault", "suggest"]:
            body = self._read_body()
            if body is not None:
                self._json(*ui_vault.suggest(body.get("text")))
        elif parts == ["", "api", "repos", "publish"]:
            self._dispatch(
                lambda b: ui_vault.publish_repo(b.get("slug"), b.get("owner"), b.get("name"), b.get("private", True)),
                ok=201,
            )
        elif parts == ["", "api", "repos", "create"]:
            # Also from a tailnet browser: the parent is typed there (the folder dialog is local only),
            # and create_repo still requires an existing absolute folder and a new name.
            self._dispatch(lambda b: ui_vault.create_repo(b.get("parent"), b.get("name"), b.get("prd_folder")), ok=201)
        elif parts == ["", "api", "review"]:
            self._dispatch(self._review)
        elif len(parts) == 5 and parts[:3] == ["", "api", "review"] and parts[4] == "lens":
            self._review_lens(parts[3])
        elif len(parts) == 5 and parts[:3] == ["", "api", "review"] and parts[4] == "rounds":
            self._review_rounds(parts[3])
        elif len(parts) == 5 and parts[:3] == ["", "api", "bootstraps"] and parts[4] in ("continue", "retry", "stop"):
            self._bootstrap_post(parts[3], parts[4])
        elif parts[:3] == ["", "api", "dispatches"]:
            self._dispatch_post(parts[3:])
        elif parts == ["", "api", "start"]:
            self._dispatch(self._board_start)
        elif parts == ["", "api", "grind", "issue"]:
            self._dispatch(self._grind_issue)
        elif parts in (["", "api", "grind", "skip-ci"], ["", "api", "grind", "stop"]):
            self._dispatch(lambda b: self._grind(parts[3], b))
        elif parts == ["", "api", "cleanup"]:
            self._dispatch(self._merge_cleanup)
        elif parts == ["", "api", "afk"]:
            self._dispatch(lambda b: ui_afk.start(b.get("until")))
        elif parts == ["", "api", "afk", "change"]:
            self._dispatch(ui_afk.change)
        elif parts in (["", "api", "afk", "stop"], ["", "api", "afk", "dismiss"]):
            self._dispatch(lambda b: ui_afk.stop() if parts[3] == "stop" else ui_afk.dismiss())
        elif parts == ["", "api", "repos", "register"]:
            self._dispatch(
                lambda b: {"path": ui_repos.register(b.get("slug"), b.get("path")), "repos": ui_repos.list_repos()}
            )
        elif parts == ["", "api", "settings", "notify"]:
            self._dispatch(ui_config.save_notify)
        elif parts == ["", "api", "settings", "notify", "channel"]:
            self._dispatch(ui_config.save_channel)
        elif parts == ["", "api", "settings", "notify", "test"]:
            self._dispatch(lambda b: ui_notify.send_test(b.get("channel")))
        elif parts == ["", "api", "settings", "review"]:
            self._dispatch(ui_config.save_review)
        elif parts == ["", "api", "repos", "remove"]:
            self._dispatch(lambda b: {**ui_config.remove_repo(b.get("slug")), "repos": ui_repos.list_repos()})
        elif parts == ["", "api", "repos", "check"]:
            self._dispatch(lambda b: {"problems": ui_config.check_repos()})
        elif parts == ["", "api", "repos", "scan"]:
            self._dispatch(self._scan)
        elif parts == ["", "api", "settings", "test"]:
            body = self._read_body()
            if body is not None:
                cmd = body.get("cmd")
                self._json(
                    200,
                    ui_settings.check_login(cmd)
                    if isinstance(cmd, str) and cmd.strip()
                    else {"ok": False, "message": "cmd required"},
                )
        elif len(parts) == 5 and parts[:3] == ["", "api", "sessions"] and parts[4] == "answer":
            self._answer(parts[3])
        elif len(parts) == 5 and parts[:3] == ["", "api", "sessions"] and parts[4] == "prompt":
            self._prompt(parts[3])
        elif len(parts) == 5 and parts[:3] == ["", "api", "sessions"] and parts[4] == "rerun":
            self._rerun(parts[3])
        elif (
            len(parts) == 5
            and parts[:3] == ["", "api", "sessions"]
            and parts[4]
            in (
                "stop",
                "resume",
                "cancel-auto",
                "start-now",
            )
        ):
            {
                "stop": self._stop,
                "resume": self._resume,
                "cancel-auto": self._cancel_auto,
                "start-now": self._start_now,
            }[parts[4]](parts[3])
        elif len(parts) == 7 and parts[1:3] in (["api", "issues"], ["api", "pulls"]) and parts[6] == "comment":
            self._dispatch(lambda b: ui_actions.comment(*parts[3:6], b.get("text")))
        elif len(parts) == 7 and parts[1:3] == ["api", "issues"] and parts[6] == "state":
            self._dispatch(
                lambda b: _repoll(
                    f"{parts[3]}/{parts[4]}", ui_actions.set_state(*parts[3:6], b.get("state"), b.get("reason"))
                )
            )
        elif len(parts) == 7 and parts[1:3] == ["api", "pulls"] and parts[6] == "state":
            self._dispatch(
                lambda b: _repoll(f"{parts[3]}/{parts[4]}", ui_actions.set_pr_state(*parts[3:6], b.get("state")))
            )
        elif len(parts) == 7 and parts[1:3] == ["api", "pulls"] and parts[6] == "merge":
            self._dispatch(lambda b: _repoll(f"{parts[3]}/{parts[4]}", ui_actions.merge(*parts[3:6])))
        elif parts == ["", "api", "epics", "close"]:
            self._dispatch(self._close_epic)
        elif parts == ["", "api", "prd"]:
            self._dispatch(
                lambda b: ui_actions.save_prd(
                    dispatch.read_checkouts()[_registered(b.get("repo"))],
                    b.get("path"),
                    b.get("text"),
                    b.get("base_sha"),
                )
            )
        elif parts[:3] == ["", "api", "shares"]:
            self._shares(self.path)
        elif parts[1:3] in _REMOVED:
            self._send(404, "text/plain; charset=utf-8", b"not found")
        else:
            self._method_not_allowed(guarded=True)

    def _shares(self, path: str) -> None:
        """Owner share routes; a body is read only for the routes that take one."""
        parts = urlsplit(path).path.split("/")
        body = None
        if self.command in ("POST", "PATCH") and parts[-1] != "seen":
            body = self._read_body()
            if body is None:
                return
        status, out = ui_share_api.handle(self.command, parts, body, urlsplit(path).query)
        if status == 204:
            self._send(204, "application/json; charset=utf-8", b"")
        else:
            self._json(status, out)

    def do_DELETE(self):
        if not _guard(self):
            return
        if urlsplit(self.path).path.startswith("/api/shares/"):
            self._shares(self.path)
        else:
            self._method_not_allowed(guarded=True)

    def do_PATCH(self):
        if not _guard(self):
            return
        if urlsplit(self.path).path.startswith("/api/shares/"):
            self._shares(self.path)
        else:
            self._method_not_allowed(guarded=True)

    @staticmethod
    def _close_epic(body: dict) -> dict:
        repo = _registered(body.get("repo"))
        epic = body.get("epic")
        if not isinstance(epic, int) or isinstance(epic, bool) or epic < 1:
            raise ValueError("epic must be an issue number")
        owner, _, name = repo.partition("/")
        return _repoll(
            repo, ui_actions.close_epic(owner, name, epic, ui_actions.open_children(POLLER.snapshot(repo), epic))
        )

    @staticmethod
    def _grind(action: str, body: dict) -> dict:
        repo, pr = _registered(body.get("repo")), body.get("pr")
        if type(pr) is not int or pr < 1:
            raise ValueError("pr must be a PR number")
        return (ui_grind.skip_ci if action == "skip-ci" else ui_grind.stop)(repo, pr)

    @staticmethod
    def _grind_issue(body: dict) -> dict:
        repo, issue, on = _registered(body.get("repo")), body.get("issue"), body.get("on")
        if type(issue) is not int or issue < 1 or type(on) is not bool:
            raise ValueError("issue must be an issue number and on must be true or false")
        return ui_grind.set_issue(repo, issue, on, POLLER.snapshot(repo), ui_settings.repo_settings(repo))

    def _review_rounds(self, panel: str) -> None:
        body = self._read_body()
        if body is None:
            return
        try:
            self._json(200, ui_panel.add_rounds(panel, body.get("add")))
        except (FileNotFoundError, ValueError) as e:
            missing = isinstance(e, FileNotFoundError) or str(e).startswith("invalid panel id")
            self._json(404 if missing else 400, {"error": "not found" if missing else str(e)})
        except ui_panel.Conflict as e:
            self._json(409, {"error": str(e)})

    def _rerun(self, sid: str) -> None:
        try:
            rec = ui_sessions.load(sid)
        except ValueError:
            rec = None
        if rec is None:
            self._json(404, {"error": "not found"})
            return
        status, payload = ui_repos.rerun(rec)
        self._json(status, _public(payload) if status == 201 else payload)

    @staticmethod
    def _board_start(body: dict) -> dict:
        repo = _registered(body.get("repo"))
        if body.get("via") not in (None, "headless"):
            raise ValueError("cards start headless sessions; run an epic's issues in parallel with a dispatch")
        return ui_start.start(
            repo,
            body.get("skill"),
            body.get("arg"),
            lenses=body.get("lenses"),
            model=body.get("model"),
            effort=body.get("effort"),
            issue=body.get("issue"),
            claude_cmd=body.get("claude_cmd"),
            pin_account=body.get("pin_account") is True,
            snapshot=POLLER.snapshot(repo),
            channel=ui_settings.repo_settings(repo)["slack_channel"],
        )

    @staticmethod
    def _merge_cleanup(body: dict) -> dict:
        repo, issue = _registered(body.get("repo")), body.get("issue")
        if type(issue) is not int or issue < 1 or body.get("confirm") is not True:
            raise ValueError("issue must be a number and confirm must be true")
        if not any(issue in m["closes"] or issue == m["n"] for m in POLLER.snapshot(repo)["data"]["merged"]):
            raise ui_start.Conflict(f"#{issue}'s PR is not merged")
        checkout = dispatch.read_checkouts()[repo]
        res = ui_mergeclean.clean(checkout, issue, confirm=True)
        _flags.get(repo, {}).pop(issue, None)
        return {"removed": res["removed"]}

    @staticmethod
    def _review(body: dict) -> dict:
        try:
            panel = ui_panel.start(body.get("repo"), body.get("artifact"), body.get("lenses"), body.get("root_session"))
        except ui_runner.RunnerError as e:
            raise ValueError(str(e))
        return {"panel": panel}

    def _review_lens(self, panel: str) -> None:
        body = self._read_body()
        if body is None:
            return
        try:
            ui_panel.lens_action(panel, body.get("lens"), body.get("action"))
            self._json(200, {"panel": panel})
        except (FileNotFoundError, ValueError) as e:
            missing = isinstance(e, FileNotFoundError) or str(e).startswith("invalid panel id")
            self._json(404 if missing else 400, {"error": "not found" if missing else str(e)})
        except ui_panel.Conflict as e:
            self._json(409, {"error": str(e)})

    @staticmethod
    def _scan(body: dict) -> dict:
        roots = body.get("roots") or ui_repos.default_roots()
        if not isinstance(roots, list) or not all(
            isinstance(r, str) and os.path.isabs(r) and ".." not in r.split(os.sep) for r in roots
        ):
            raise ValueError("roots must be a list of absolute folders")
        res = ui_repos.scan_and_register([r for r in roots if os.path.isdir(r)])
        return {**res, "repos": ui_repos.list_repos()}

    def _dispatch(self, fn, ok: int = 200) -> None:
        """Run a call on the JSON body, mapping its errors to HTTP statuses."""
        body = self._read_body()
        if body is None:
            return
        try:
            self._json(ok, fn(body))
        except (ValueError, TypeError) as e:
            self._json(400, {"error": str(e)})
        except (
            ui_start.Conflict,
            ui_grind.Conflict,
            ui_actions.Conflict,
            dispatch_run.Conflict,
            ui_restart.Conflict,
            ui_afk.Conflict,
            ui_bootstrap.Conflict,
        ) as e:
            self._json(409, {"error": str(e), **({"id": e.id} if getattr(e, "id", None) else {})})
        except (RuntimeError, OSError, ui_runner.RunnerError) as e:  # RunnerError, a failed herdr call
            self._json(502, {"error": str(e)})

    def _cleanup(self) -> None:
        body = self._read_body()
        if body is None:
            return
        keys = body.get("keys")
        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
            self._json(400, {"error": "keys must be a list of session keys"})
            return
        self._json(200, {"removed": ui_cleanup.clean(keys)})

    def _stop(self, sid: str) -> None:
        try:
            rec = ui_sessions.load(sid)
        except ValueError:
            rec = None
        if rec is None:
            self._json(404, {"error": "not found"})
            return
        if rec.get("status") in ("done", "failed", "stopped"):
            self._json(409, {"error": "session already finished"})
            return
        rec = ui_runner.stop(sid)
        if rec.get("status") != "stopped":
            self._json(409, {"error": "session is starting, retry"})
            return
        self._json(200, _public(rec))

    def _start_now(self, sid: str) -> None:
        try:
            self._json(200, _public(ui_runner.start_now(sid)))
        except (FileNotFoundError, ValueError):
            self._json(404, {"error": "not found"})
        except ui_runner.NotQueued as e:
            self._json(409, {"error": str(e)})

    def _prompt(self, sid: str) -> None:
        body = self._read_body()
        if body is None:
            return
        try:
            state = ui_runner.send_prompt(sid, body.get("text"))
        except (FileNotFoundError, ValueError) as e:
            self._json(
                404 if isinstance(e, FileNotFoundError) else 400,
                {"error": "not found" if isinstance(e, FileNotFoundError) else str(e)},
            )
            return
        except ui_runner.Conflict as e:
            self._json(409, {"error": str(e)})
            return
        except (ui_runner.RunnerError, OSError) as e:
            self._json(500, {"error": str(e)})
            return
        self._json(202 if state == "queued" else 200, {"state": state})

    def _cancel_auto(self, sid: str) -> None:
        try:
            self._json(200, _public(ui_runner.cancel_auto(sid)))
        except (FileNotFoundError, ValueError):
            self._json(404, {"error": "not found"})
        except ui_runner.Conflict as e:
            self._json(409, {"error": str(e)})

    def _resume(self, sid: str) -> None:
        cmd = None
        if (self.headers.get("Content-Length") or "0").strip() not in (
            "",
            "0",
        ):  # optional {"claude_cmd": <saved label>}
            body = self._read_body()
            if body is None:
                return
            if body.get("claude_cmd") is not None:
                saved = {c["label"]: c["cmd"] for c in ui_settings.load()["commands"]}
                cmd = saved.get(body["claude_cmd"])
                if cmd is None:
                    self._json(400, {"error": "claude_cmd must be a label saved in Settings"})
                    return
        try:
            rec = ui_runner.resume_stopped(sid, cmd)
        except (FileNotFoundError, ValueError):
            self._json(404, {"error": "not found"})
            return
        except ui_runner.Conflict as e:
            self._json(409, {"error": str(e)})
            return
        except (ui_runner.RunnerError, OSError) as e:
            self._json(500, {"error": str(e)})
            return
        self._json(200, _public(rec))

    def _read_body(self):
        """Parsed JSON object body, or None after sending the 4xx."""
        try:
            n = int(self.headers.get("Content-Length") or "")
        except ValueError:
            n = -1
        if n < 0:
            self._json(400, {"error": "bad Content-Length"})
            return None
        if n > MAX_BODY:
            self._json(413, {"error": "body too large"})
            return None
        try:
            body = json.loads(self.rfile.read(n))
        except ValueError:
            body = None
        if not isinstance(body, dict):
            self._json(400, {"error": "body must be a JSON object"})
            return None
        return body

    def do_PUT(self):
        if not _guard(self):
            return
        if urlsplit(self.path).path != "/api/settings":
            self._method_not_allowed(guarded=True)
            return
        body = self._read_body()
        if body is None:
            return
        try:
            self._json(200, ui_settings.save(body))
        except ValueError as e:
            self._json(400, {"error": str(e)})

    def _start(self) -> None:
        body = self._read_body()
        if body is None:
            return
        status, payload = ui_repos.start_session(body)
        self._json(status, _public(payload) if status == 201 else payload)

    def _answer(self, sid: str) -> None:
        try:
            rec = ui_sessions.load(sid)
        except ValueError:
            rec = None
        if rec is None:
            self._json(404, {"error": "not found"})
            return
        if not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
            self._json(415, {"error": "Content-Type must be application/json"})
            return
        try:
            length = int(self.headers.get("Content-Length"))
        except (TypeError, ValueError):
            self._json(400, {"error": "Content-Length required"})
            return
        if length < 0:
            self._json(400, {"error": "bad Content-Length"})
            return
        if length > MAX_BODY:
            self._json(413, {"error": f"body over {MAX_BODY} bytes"})
            return
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            body = None
        if not isinstance(body, dict):
            self._json(400, {"error": "body must be a JSON object"})
            return
        pending = rec.get("pending_question")
        if rec.get("status") != "waiting" or not isinstance(pending, dict):
            self._json(409, {"error": "session is not waiting for an answer"})
            return
        if sid in ui_runner._procs:
            self._json(409, {"error": "session process is still running"})
            return
        if not rec.get("session_id"):
            self._json(409, {"error": "session has no claude session_id to resume"})
            return
        round_id = body.get("round_id")
        if not isinstance(round_id, str) or not round_id:
            self._json(400, {"error": "round_id required"})
            return
        if round_id != pending.get("id"):
            self._json(409, {"error": "round_id is not the current pending round"})
            return
        try:
            text = ui_sessions.answer_text(pending, body.get("answers"))
        except ValueError as e:
            self._json(400, {"error": str(e)})
            return
        if ui_sessions.claim_answer(sid, round_id) is None:
            self._json(409, {"error": "round already answered"})
            return
        try:
            rec = ui_runner.resume(sid, text)
        except (ui_runner.RunnerError, ValueError, OSError) as e:
            self._json(500, {"error": str(e)})
            return
        self._json(200, _public(rec))

    def _method_not_allowed(self, guarded: bool = False):
        if not guarded and not _guard(self):
            return
        if self.command == "HEAD":
            self.send_response(405)
            self.send_header("Allow", "GET")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self._send(405, "text/plain; charset=utf-8", b"method not allowed", {"Allow": "GET"})

    # every verb needs a do_* or stdlib answers 501 before _guard runs
    do_HEAD = do_OPTIONS = do_TRACE = do_CONNECT = _method_not_allowed


class _Server(http.server.ThreadingHTTPServer):
    # Reuse is on so a restart is not refused while closed connections sit in TIME_WAIT; cmd_serve probes
    # the port first because macOS would otherwise let a 127.0.0.1 bind succeed over a 0.0.0.0 holder.
    allow_reuse_address = True
    # A cold page load fires a dozen module/font requests at once; the default backlog of 5 resets some of them.
    request_queue_size = 128
    # Set by cmd_serve when `tailscale serve` fronts this server: Host values that arrive over the
    # tailnet, and the one login allowed to use them (the UI can start agents).
    tailnet_hosts: frozenset = frozenset()
    tailnet_login = None

    def __init__(self, address, handler, allowed_hosts):
        super().__init__(address, handler)
        port = self.server_address[1]
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"} | {h.strip().lower() for h in allowed_hosts}


def _port_holder(port: int):
    try:
        out = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True, timeout=5
        ).stdout.splitlines()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if len(out) < 2:
        return None
    fields = out[1].split()
    return (fields[1], fields[0]) if len(fields) >= 2 else None


def _port_answers(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def cmd_serve(args) -> None:
    ui_migrate.clear_old_data(shared.data_dir())  # before any timer starts or module reads the data dir
    port = args.port
    extras = args.allow_host or []
    try:
        if _port_answers(port):
            raise OSError(errno.EADDRINUSE, "address in use")
        server = _Server(
            ("127.0.0.1", port),
            _Handler,
            extras,
        )
    except (OSError, OverflowError) as exc:
        if getattr(exc, "errno", None) != errno.EADDRINUSE:
            die(1, f"cannot bind 127.0.0.1:{port}: {exc}")
        holder = _port_holder(port)
        if holder:
            die(1, f"port {port} is already in use by PID {holder[0]} ({holder[1]}) — stop it or pass --port")
        die(1, f"port {port} is already in use (http://127.0.0.1:{port}/) — stop it or pass --port")
    ts = None
    if not args.no_tailscale:
        ts = ui_tailscale.up(server.server_address[1], args.tailscale_port)
        if ts:
            server.allowed_hosts |= ts["hosts"]
            server.tailnet_hosts, server.tailnet_login = frozenset(ts["hosts"]), ts["login"]
    ui_shares.listeners.append(_on_share_activity)  # reviewer comments and approvals -> prd-comment
    ui_share_runtime.configure(args.tailscale_port, tailscale_enabled=not args.no_tailscale)
    ui_runner.reconcile()  # re-attach sessions that outlived the last UI, close the ones that died
    ui_grind.start_timer()  # ntfy on grind pause/finish
    ui_runner.start_prgrind_timer()  # re-enter pr-grind loops whose session ended (reviews, CI, heartbeat)
    ui_runner.start_limit_timer()  # auto-resume limited runs, incl. catch-up of resets missed while down
    POLLER.start(_watched_copy, hot=_hot)  # boards: poll every repo a board was opened for, run the hooks
    ui_bootstrap.start_timer()  # bootstrap runs: next phase from the ended phase session
    ui_panel.start_timer()  # lens verdicts -> root, rounds, cap
    ui_usage.start_timer()  # 5h/7d usage per account, only while the UI is open
    ui_dispatch.start_timer(POLLER.snapshot)  # dispatch lanes: facts from the boards, tick, launch, merge
    jev.start_timer()  # flush the jev answer cache to disk; writes nothing until a cached point ran
    # the scorer builds its own item list: _inbox would mark every watched repo as viewed (_hot)
    ui_urgency.start_timer(lambda: _inbox_items(None, _watched_copy(), ui_sessions.list_sessions())["items"])
    ui_afk.start_timer()  # AFK mode: auto-answer, skip CI on paused grinds, retry failures; ends the window
    ui_share_runtime.start()  # serve live shares again on the same link; nothing runs when there are none
    ui_share_runtime.start_timer()  # re-check every live share once a minute
    print(f"serving http://127.0.0.1:{server.server_address[1]}/ — Ctrl+C to stop")
    if ts:
        print(f"also on your tailnet: {ts['url']}/ (only {ts['login']}; removed when this exits)")
    if ui_share_runtime.summary():
        print(ui_share_runtime.summary())
    if extras:
        print("also allowing hosts: " + ", ".join(extras))
    for sig in (signal.SIGTERM, signal.SIGHUP):  # SIGHUP: closed terminal; let `finally` remove the tailscale handler
        signal.signal(sig, lambda *_: sys.exit(0))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
        ui_share_runtime.stop()  # its own funnel handler, separate from the tailnet serve below
        if ts:
            ui_tailscale.down(ts["https_port"])


def register(sub, add) -> None:
    p = sub.add_parser("ui", help="workflow control UI server (loopback; also your tailnet when tailscale is running)")
    p.add_argument("--port", type=int, default=8420)
    p.add_argument(
        "--allow-host",
        action="append",
        default=None,
        metavar="HOST",
        help="extra accepted Host header, exact match (repeatable); give name:port unless the proxy serves "
        "the default port, e.g. a tailscale serve name on 443 is passed bare",
    )
    p.add_argument(
        "--no-tailscale",
        action="store_true",
        help="do not serve on the tailnet (default: serve there when tailscale is running)",
    )
    p.add_argument(
        "--tailscale-port",
        type=int,
        default=ui_tailscale.DEFAULT_HTTPS_PORT,
        metavar="PORT",
        help="HTTPS port on the tailnet name: 443, 8443 or 10000 (default 443; an occupied port is never overwritten)",
    )
    p.set_defaults(func=cmd_serve)
