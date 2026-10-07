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
import subprocess
import sys
from urllib.parse import parse_qs, unquote, urlsplit

import ui_events
import ui_sessions
from shared import die
from ui_board import build_board, fetch_title, load_projects, memoize_title_fetcher, scan_records


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
    origin = handler.headers.get("Origin")
    if origin is not None and urlsplit(origin.strip()).netloc.lower() != host:
        handler._send(403, "text/plain; charset=utf-8", b"forbidden")
        return False
    return True


def _public(rec: dict) -> dict:
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
        elif path.startswith("/static/"):
            _serve_static(self, path[len("/static/"):])
        elif path == "/api/health":
            self._send(200, "application/json; charset=utf-8", b'{"ok": true}')
        elif path == "/board.json":
            board = build_board(scan_records(), load_projects(), self.server.fetch_title)
            self._send(200, "application/json; charset=utf-8", json.dumps(board).encode("utf-8"))
        elif path == "/api/sessions":
            body = {"sessions": [_public(r) for r in ui_sessions.list_sessions()]}
            self._send(200, "application/json; charset=utf-8", json.dumps(body).encode("utf-8"))
        else:
            parts = path.split("/")
            if len(parts) in (4, 5) and parts[:3] == ["", "api", "sessions"] and (len(parts) == 4 or parts[4] == "stream"):
                self._session(parts[3], len(parts) == 5)
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

    def _method_not_allowed(self):
        if not _guard(self):
            return
        if self.command == "HEAD":
            self.send_response(405)
            self.send_header("Allow", "GET")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self._send(405, "text/plain; charset=utf-8", b"method not allowed", {"Allow": "GET"})

    # every verb needs a do_* or stdlib answers 501 before _guard runs
    do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = do_TRACE = do_CONNECT = _method_not_allowed


class _Server(http.server.ThreadingHTTPServer):
    # macOS lets a 127.0.0.1 bind succeed while another process holds 0.0.0.0:<port> when reuse is on
    allow_reuse_address = False

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


def cmd_serve(args) -> None:
    port = args.port
    extras = args.allow_host or []
    try:
        server = _Server(("127.0.0.1", port), _Handler, extras, memoize_title_fetcher(fetch_title))
    except (OSError, OverflowError) as exc:
        if getattr(exc, "errno", None) != errno.EADDRINUSE:
            die(1, f"cannot bind 127.0.0.1:{port}: {exc}")
        holder = _port_holder(port)
        if holder:
            die(1, f"port {port} is already in use by PID {holder[0]} ({holder[1]}) — stop it or pass --port")
        die(1, f"port {port} is already in use (http://127.0.0.1:{port}/) — stop it or pass --port")
    print(f"serving http://127.0.0.1:{server.server_address[1]}/ — Ctrl+C to stop")
    if extras:
        print("also allowing hosts: " + ", ".join(extras))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()


def register(sub, add) -> None:
    p = sub.add_parser("ui", help="workflow control UI server (loopback only)")
    p.add_argument("--port", type=int, default=8420)
    p.add_argument(
        "--allow-host",
        action="append",
        default=None,
        metavar="HOST",
        help="extra accepted Host header, exact match (repeatable); give name:port unless the proxy serves "
        "the default port, e.g. a tailscale serve name on 443 is passed bare",
    )
    p.set_defaults(func=cmd_serve)
