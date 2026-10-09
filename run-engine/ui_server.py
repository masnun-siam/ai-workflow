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
import re
import shlex
import signal
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, unquote, urlsplit

import ui_cleanup
import ui_dispatch
import ui_events
import ui_grind
import ui_issue
import ui_pr
import ui_repos
import ui_runner
import ui_sessions
import ui_settings
import ui_status
import ui_tailscale
import shared
from shared import die
from ui_board import build_board, fetch_title, load_projects, plausible_repo, load_run, memoize_title_fetcher, scan_records


mimetypes.add_type("application/manifest+json", ".webmanifest")
STATIC_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui_static")


def _serve_static(handler, rel: str) -> None:
    root = os.path.realpath(STATIC_DIR)
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
    handler._send(200, ctype, body, {"Cache-Control": "no-cache"})


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


MAX_FREE_TEXT = 4000
MAX_BODY = 65536


def _answer_text(pending: dict, answers) -> str:
    """Validate answers against the pending round; return the text to resume with."""
    qs = pending["questions"]
    if not isinstance(answers, dict) or set(answers) != {str(i) for i in range(len(qs))}:
        raise ValueError("answers must be an object with exactly one entry per question index")
    out = {}
    for i, q in enumerate(qs):
        a = answers[str(i)]
        if not isinstance(a, dict) or len(a) != 1 or next(iter(a)) not in ("labels", "other"):
            raise ValueError(f"answer {i} must be exactly one of labels or other")
        if "labels" in a:
            labels = a["labels"]
            valid = {o["label"] for o in q["options"]}
            if not isinstance(labels, list) or not labels or not all(isinstance(l, str) for l in labels):
                raise ValueError(f"answer {i}: labels must be a non-empty list of strings")
            if len(set(labels)) != len(labels):
                raise ValueError(f"answer {i}: duplicate labels")
            if not q["multiSelect"] and len(labels) > 1:
                raise ValueError(f"answer {i}: only one label allowed")
            if any(l not in valid or "\0" in l for l in labels):
                raise ValueError(f"answer {i}: label is not an option of this question")
            out[str(i)] = {"labels": labels}
        else:
            other = a["other"]
            if not q.get("allowFreeText", True):
                raise ValueError(f"answer {i}: free text not allowed")
            if not isinstance(other, str) or not other.strip() or "\0" in other:
                raise ValueError(f"answer {i}: free text must be a non-empty string without NUL")
            if len(other) > MAX_FREE_TEXT:
                raise ValueError(f"answer {i}: free text over the {MAX_FREE_TEXT} character cap")
            out[str(i)] = {"other": other}
    text = f"Answer to {pending['id']}: " + json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    try:
        text.encode("utf-8")  # lone surrogates can't be passed as argv
    except UnicodeEncodeError:
        raise ValueError("free text must be valid UTF-8") from None
    return text


def _public(rec: dict) -> dict:
    p, sid = rec.get("cwd_path"), rec.get("session_id")
    return {
        "id": rec.get("id"),
        "command": rec.get("command"),
        "repo": rec.get("repo"),
        "link": rec.get("link"),
        "session_id": rec.get("session_id"),
        "outcome": rec.get("status"),
        "cost": rec.get("cost"),
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
        "repo_path": p,
        "resume_command": f"cd {shlex.quote(p)} && claude --resume {shlex.quote(sid)}" if p and sid else None,
    }


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
        elif path == "/sw.js":  # served at the root so its scope covers the whole app
            _serve_static(self, "sw.js")
        elif path.startswith("/static/"):
            _serve_static(self, path[len("/static/"):])
        elif path == "/api/health":
            self._send(200, "application/json; charset=utf-8", b'{"ok": true}')
        elif path == "/board.json":
            board = build_board(scan_records(), load_projects(), self.server.fetch_title)
            member = ui_dispatch.membership()
            gidx = ui_grind.index()
            for column in board["columns"]:
                for card in column["cards"]:
                    card["grind"] = ui_grind.for_card(gidx, card["owner"], card["repo"], card["issue"], card["pr"])
                    card["gh"] = _gh_status(card["owner"], card["repo"], card["issue"], card["pr"], card["branch"])
                    card["pipeline"] = member.get(f"{card['owner']}/{card['repo']}#{card['issue']}".lower())
            self._send(200, "application/json; charset=utf-8", json.dumps(board).encode("utf-8"))
        elif path == "/api/repos":
            self._json(200, {"repos": ui_repos.list_repos(), "can_browse": _can_browse(self), "scan_roots": ui_repos.default_roots()})
        elif path == "/api/settings":
            self._json(200, ui_settings.load())
        elif path == "/api/cleanup":
            self._json(200, {"items": list(_TITLE_POOL.map(ui_cleanup.describe, ui_cleanup.find_targets()))})
        elif path == "/api/pipelines":
            self._json(200, {"pipelines": [ui_dispatch.summary(p) for p in ui_dispatch.list_all()]})
        elif path.startswith("/api/pipelines/"):
            body = ui_dispatch.detail(path.split("/")[3], _gh_status) if len(path.split("/")) == 4 else None
            if body:
                owner, _, repo = body["slug"].partition("/")
                gidx = ui_grind.index()
                for it in body["items"]:
                    it["grind"] = ui_grind.for_card(gidx, owner, repo, it["issue"], (it.get("run") or {}).get("pr"))
            self._json(200, body) if body else self._json(404, {"error": "not found"})
        elif path == "/api/sessions":
            body = {"sessions": [_public(r) for r in ui_sessions.list_sessions()],
                    "limits": ui_runner.limits()}
            self._send(200, "application/json; charset=utf-8", json.dumps(body).encode("utf-8"))
        else:
            parts = path.split("/")
            if len(parts) in (4, 5) and parts[:3] == ["", "api", "sessions"] and (len(parts) == 4 or parts[4] == "stream"):
                self._session(parts[3], len(parts) == 5)
            elif len(parts) == 6 and parts[:3] == ["", "api", "runs"]:
                self._run(parts[3], parts[4], parts[5])
            elif len(parts) == 6 and parts[:3] == ["", "api", "issues"]:
                if ui_issue.valid(*parts[3:]):
                    self._json(*ui_issue.fetch(*parts[3:]))
                else:
                    self._json(400, {"error": "bad issue id"})
            elif len(parts) == 6 and parts[:3] == ["", "api", "pulls"]:
                if ui_pr.valid(*parts[3:]):
                    self._json(*ui_pr.fetch(*parts[3:]))
                else:
                    self._json(400, {"error": "bad pull request id"})
            else:
                self._send(404, "text/plain; charset=utf-8", b"not found")

    def _run(self, owner: str, repo: str, n: str) -> None:
        try:
            body = load_run(owner, repo, n)
        except ValueError:
            self._send(400, "text/plain; charset=utf-8", b"bad run id")
            return
        if body is None:
            self._send(404, "text/plain; charset=utf-8", b"not found")
            return
        body["title"] = self.server.fetch_title(owner, repo, int(n))
        body["gh"] = _gh_status(owner, repo, int(n), body["pr"], body["branch"])
        body["grind"] = ui_grind.for_card(ui_grind.index(), owner, repo, int(n), body["pr"])
        if body["grind"] and body["grind"]["state"] == "paused":
            body["grind"] = {**body["grind"], "message": ui_grind.last_message(owner, repo, int(n))}
        self._send(200, "application/json; charset=utf-8", json.dumps(body).encode("utf-8"))

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

    def _json(self, status: int, body: dict) -> None:
        self._send(status, "application/json; charset=utf-8", json.dumps(body).encode("utf-8"))

    def do_POST(self):
        if not _guard(self):
            return
        parts = urlsplit(self.path).path.split("/")
        if parts == ["", "api", "sessions"]:
            self._start()
        elif parts == ["", "api", "repos", "browse"]:
            body = self._read_body()
            if body is None:
                return
            if _can_browse(self):
                self._json(200, {"path": ui_repos.browse_folder(body.get("start"))})
            else:
                self._json(403, {"error": "folder picker is only available locally on macOS"})
        elif parts == ["", "api", "cleanup"]:
            self._cleanup()
        elif parts == ["", "api", "repos", "register"]:
            self._dispatch(lambda b: {"path": ui_repos.register(b.get("slug"), b.get("path")), "repos": ui_repos.list_repos()})
        elif parts == ["", "api", "repos", "scan"]:
            self._dispatch(self._scan)
        elif parts[:3] == ["", "api", "dispatch"] and parts[3:] == ["preview"]:
            self._dispatch(lambda b: ui_dispatch.preview(b.get("input"), b.get("repo")))
        elif parts == ["", "api", "pipelines"]:
            self._dispatch(ui_dispatch.create, 201)
        elif len(parts) == 5 and parts[:3] == ["", "api", "pipelines"] and parts[4] == "delete":
            self._dispatch(lambda b: ui_dispatch.delete(parts[3]) or {"ok": True})
        elif len(parts) == 5 and parts[:3] == ["", "api", "pipelines"]:
            self._dispatch(lambda b: ui_dispatch.act(parts[3], parts[4], b))
        elif len(parts) == 7 and parts[:3] == ["", "api", "pipelines"] and parts[4] == "items" and parts[5].isdigit():
            self._dispatch(lambda b: ui_dispatch.act(parts[3], parts[6], b, issue=int(parts[5])))
        elif len(parts) == 4 and parts[:3] == ["", "api", "grind"] and parts[3] in ("start", "pause", "resume", "rerun-ci", "reply"):
            self._grind(parts[3])
        elif parts == ["", "api", "settings", "test"]:
            body = self._read_body()
            if body is not None:
                cmd = body.get("cmd")
                self._json(200, ui_settings.check_login(cmd) if isinstance(cmd, str) and cmd.strip()
                           else {"ok": False, "message": "cmd required"})
        elif len(parts) == 5 and parts[:3] == ["", "api", "sessions"] and parts[4] == "answer":
            self._answer(parts[3])
        elif len(parts) == 5 and parts[:3] == ["", "api", "sessions"] and parts[4] == "prompt":
            self._prompt(parts[3])
        elif len(parts) == 5 and parts[:3] == ["", "api", "sessions"] and parts[4] in ("stop", "resume", "cancel-auto"):
            {"stop": self._stop, "resume": self._resume, "cancel-auto": self._cancel_auto}[parts[4]](parts[3])
        else:
            self._method_not_allowed(guarded=True)

    def _grind(self, action: str) -> None:
        body = self._read_body()
        if body is None:
            return
        owner, repo, issue = body.get("owner"), body.get("repo"), body.get("issue")
        if not (isinstance(owner, str) and isinstance(repo, str) and isinstance(issue, int) and not isinstance(issue, bool)):
            self._json(400, {"error": "owner, repo and issue are required"})
            return
        try:
            status, res = (ui_grind.request(owner, repo, issue) if action == "start"
                           else ui_grind.rerun_ci(owner, repo, issue) if action == "rerun-ci"
                           else ui_grind.reply(owner, repo, issue, body.get("text")) if action == "reply"
                           else ui_grind.control(owner, repo, issue, action))
        except ValueError as e:
            status, res = 400, {"error": str(e)}
        self._json(status, res)

    @staticmethod
    def _scan(body: dict) -> dict:
        roots = body.get("roots") or ui_repos.default_roots()
        if not isinstance(roots, list) or not all(isinstance(r, str) and os.path.isabs(r) and ".." not in r.split(os.sep) for r in roots):
            raise ValueError("roots must be a list of absolute folders")
        res = ui_repos.scan_and_register([r for r in roots if os.path.isdir(r)])
        return {**res, "repos": ui_repos.list_repos()}

    def _dispatch(self, fn, ok: int = 200) -> None:
        """Run a ui_dispatch call on the JSON body, mapping its errors to HTTP statuses."""
        body = self._read_body()
        if body is None:
            return
        try:
            self._json(ok, fn(body))
        except ui_dispatch.NeedsCheckout as e:
            self._json(409, {"error": str(e), "code": "no_checkout", "slug": e.slug, "candidates": e.candidates})
        except ui_dispatch.NotFound:
            self._json(404, {"error": "not found"})
        except ui_dispatch.Conflict as e:
            self._json(409, {"error": str(e)})
        except (ValueError, TypeError) as e:
            self._json(400, {"error": str(e)})

    def _cleanup(self) -> None:
        body = self._read_body()
        if body is None:
            return
        asked = body.get("items")
        if not isinstance(asked, list) or not all(isinstance(a, dict) and isinstance(a.get("key"), str) for a in asked):
            self._json(400, {"error": "items must be a list of {key, force?}"})
            return
        targets = {t["key"]: t for t in ui_cleanup.find_targets()}  # re-derived: the client never names paths
        results = [
            ui_cleanup.clean(targets[a["key"]], a.get("force") is True) if a["key"] in targets
            else {"key": a["key"], "ok": False, "error": "not cleanable (gone, live, or escalated)"}
            for a in asked
        ]
        self._json(200, {"results": results})

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

    def _prompt(self, sid: str) -> None:
        body = self._read_body()
        if body is None:
            return
        try:
            state = ui_runner.send_prompt(sid, body.get("text"))
        except (FileNotFoundError, ValueError) as e:
            self._json(404 if isinstance(e, FileNotFoundError) else 400,
                       {"error": "not found" if isinstance(e, FileNotFoundError) else str(e)})
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
        if (self.headers.get("Content-Length") or "0").strip() not in ("", "0"):  # optional {"claude_cmd": <saved label>}
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
            text = _answer_text(pending, body.get("answers"))
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
    do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = do_TRACE = do_CONNECT = _method_not_allowed


# Bounded so a cold /board.json can't fan out unbounded `gh` processes.
_TITLE_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="title")


def _gh_status(owner, repo, issue, pr, branch):
    if not plausible_repo(owner, repo):
        return None
    # ledger values reach `gh` argv: only https PR URLs and non-option branch names
    pr = pr if isinstance(pr, str) and pr.startswith("https://") else None
    branch = branch if isinstance(branch, str) and branch and not branch.startswith("-") else None
    return ui_status.get(owner, repo, issue, pr, branch, _TITLE_POOL)


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

    def __init__(self, address, handler, allowed_hosts, fetch_title):
        super().__init__(address, handler)
        port = self.server_address[1]
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"} | {h.strip().lower() for h in allowed_hosts}
        self.fetch_title = fetch_title


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
    port = args.port
    extras = args.allow_host or []
    try:
        if _port_answers(port):
            raise OSError(errno.EADDRINUSE, "address in use")
        server = _Server(("127.0.0.1", port), _Handler, extras, memoize_title_fetcher(fetch_title, _TITLE_POOL, os.path.join(shared.data_dir(), "titles.json")))
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
    ui_runner.reconcile()  # re-attach sessions that outlived the last UI, close the ones that died
    ui_dispatch.start_timer()  # advance dispatch pipelines (needs reconciled session states)
    ui_grind.start_timer()  # queued/auto grinds, ntfy on pause/finish
    ui_runner.start_prgrind_timer()  # re-enter pr-grind loops whose session ended (reviews, CI, heartbeat)
    ui_runner.start_limit_timer()  # auto-resume limited runs, incl. catch-up of resets missed while down
    print(f"serving http://127.0.0.1:{server.server_address[1]}/ — Ctrl+C to stop")
    if ts:
        print(f"also on your tailnet: {ts['url']}/ (only {ts['login']}; removed when this exits)")
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
    p.add_argument("--no-tailscale", action="store_true",
                   help="do not serve on the tailnet (default: serve there when tailscale is running)")
    p.add_argument("--tailscale-port", type=int, default=ui_tailscale.DEFAULT_HTTPS_PORT, metavar="PORT",
                   help="HTTPS port on the tailnet name: 443, 8443 or 10000 (default 443; an occupied port is never overwritten)")
    p.set_defaults(func=cmd_serve)
