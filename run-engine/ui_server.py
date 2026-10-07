#!/usr/bin/env python3
"""`aiw ui` — loopback-only workflow control UI server.

Every request passes a Host/Origin guard (DNS-rebinding and cross-site defence);
no CORS headers are ever emitted.
"""

from __future__ import annotations

import errno
import http.server
import json
import subprocess
from urllib.parse import urlsplit

from shared import die
from ui_board import build_board, fetch_title, load_projects, memoize_title_fetcher, scan_records


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
        if path == "/api/health":
            self._send(200, "application/json; charset=utf-8", b'{"ok": true}')
        elif path == "/board.json":
            board = build_board(scan_records(), load_projects(), self.server.fetch_title)
            self._send(200, "application/json; charset=utf-8", json.dumps(board).encode("utf-8"))
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found")

    def _method_not_allowed(self):
        if _guard(self):
            self._send(405, "text/plain; charset=utf-8", b"method not allowed", {"Allow": "GET"})

    do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = _method_not_allowed


class _Server(http.server.ThreadingHTTPServer):
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
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            die(1, f"cannot bind 127.0.0.1:{port}: {exc}")
        holder = _port_holder(port)
        if holder:
            die(1, f"port {port} is already in use by PID {holder[0]} ({holder[1]}) — stop it or pass --port")
        die(1, f"port {port} is already in use (http://127.0.0.1:{port}/) — stop it or pass --port")
    print(f"serving http://127.0.0.1:{port}/ — Ctrl+C to stop")
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
