"""Public share listener (FR-2, FR-3, FR-6, FR-11, FR-13): the only HTTP server that is ever public.

It answers the share page, its assets and the share API for one token's PRD, and nothing else. Every
other request, every failed guard and every unknown or ended token gets the same 404. It imports none of
`ui_server`'s handlers on purpose. Never log a token: `log_message` is a no-op.
"""

from __future__ import annotations

import http.server
import json
import mimetypes
import os
import re
from urllib.parse import urlsplit

import dispatch
import shared
import ui_shares

DIST_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui_dist")  # tests replace it
MAX_BODY = 16384
_ROUTE = re.compile(r"^/s/(?P<token>[A-Za-z0-9_-]{16,128})(?P<rest>/.*)?$")
_ASSET = re.compile(r"^/assets/(?P<name>.+)$")
_COMMENTS = re.compile(r"^/api/threads/(?P<tid>[0-9a-f]+)/comments$")
_HEAD = re.compile(r"<head>", re.IGNORECASE)
_SECURITY_HEADERS = {
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex",
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"
    ),
}
_NOT_FOUND = ("text/plain; charset=utf-8", b"not found")
_JSON = "application/json; charset=utf-8"
_ERRORS = {"invalid": 400, "conflict": 409, "full": 409, "rate": 429}
_manifest_cache: dict = {}  # (dist dir, manifest mtime) -> set of allowed asset paths


class PublicServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    request_queue_size = 128

    def __init__(self, address, handler):
        super().__init__(address, handler)
        self.allowed_hosts: set = set()  # "<dns>:<port>" values, filled by the runtime once the funnel is up


def make_server(port: int = 0) -> PublicServer:
    """Bound to 127.0.0.1, not started: the caller runs serve_forever()."""
    return PublicServer(("127.0.0.1", port), _Handler)


def _asset_closure(manifest: dict, key: str, seen: set) -> None:
    chunk = manifest.get(key)
    if key in seen or not isinstance(chunk, dict):
        return
    seen.add(key)
    for k in ("imports", "dynamicImports"):
        for dep in chunk.get(k) or []:
            _asset_closure(manifest, dep, seen)


def allowed_assets() -> set:
    """Files the build's manifest lists for the share.html entry, lazy chunks included; empty if unreadable."""
    path = os.path.join(DIST_DIR, ".vite", "manifest.json")
    try:
        stamp = (DIST_DIR, os.stat(path).st_mtime_ns)
        if stamp in _manifest_cache:
            return _manifest_cache[stamp]
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        return set()
    entries = [
        k for k, v in manifest.items() if k == "share.html" or (isinstance(v, dict) and v.get("src") == "share.html")
    ]
    keys: set = set()
    for k in entries:
        _asset_closure(manifest, k, keys)
    files = set()
    for k in keys:
        chunk = manifest[k]
        files.update([chunk.get("file"), *(chunk.get("css") or []), *(chunk.get("assets") or [])])
    out = {f for f in files if isinstance(f, str)}
    _manifest_cache.clear()
    _manifest_cache[stamp] = out
    return out


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # also swallows log_error, so no token reaches a log
        pass

    def _send(self, status: int, content_type: str, body: bytes = b"") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in _SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _not_found(self) -> None:
        self._send(404, *_NOT_FOUND)

    def _json(self, status: int, data) -> None:
        self._send(status, _JSON, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _handle(self) -> None:
        try:
            self._route()
        except ui_shares.ShareError as e:
            self._share_error(e)
        except (BrokenPipeError, ConnectionResetError):
            raise
        except Exception as e:
            shared.warn(f"share listener: {type(e).__name__}")
            self._json(500, {"error": "internal error"})

    def _share_error(self, e: ui_shares.ShareError) -> None:
        status = _ERRORS.get(e.kind)
        if status is None:
            self._not_found()
        else:
            self._json(status, {"error": str(e)})

    def _route(self) -> None:
        host = (self.headers.get("Host") or "").strip().lower()
        m = _ROUTE.match(urlsplit(self.path).path)
        if not host or host not in self.server.allowed_hosts or not m:
            return self._not_found()
        method, rest = self.command, m["rest"] or "/"
        if method not in ("GET", "POST", "DELETE") or (method != "GET" and not self._write_allowed(host)):
            return self._not_found()
        handler = self._pick(method, rest)
        if handler is None:
            return self._not_found()
        share = ui_shares.by_token(m["token"])
        if share is None:
            return self._not_found()
        share = ui_shares.refresh(share["id"], dispatch.read_checkouts().get(share["repo"]))
        if share is None or share["state"] != "live":
            return self._not_found()
        handler[0](share, *handler[1:])

    def _write_allowed(self, host: str) -> bool:
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        origin = self.headers.get("Origin")
        return ctype == "application/json" and bool(origin) and urlsplit(origin).netloc.lower() == host

    def _pick(self, method: str, rest: str):
        """(handler, *args) for a known route, else None."""
        if method == "GET":
            if rest == "/":
                return (self._page,)
            asset = _ASSET.match(rest)
            if asset:
                return (self._asset, asset["name"])
            table = {"/api/prd": self._prd, "/api/threads": self._threads, "/api/approvals": self._approvals}
            return (table[rest],) if rest in table else None
        if rest == "/api/approvals":
            return (self._approve if method == "POST" else self._withdraw,)
        if method == "POST" and rest == "/api/threads":
            return (self._new_thread,)
        comments = _COMMENTS.match(rest)
        return (self._new_comment, comments["tid"]) if method == "POST" and comments else None

    # --- GET ---

    def _page(self, share) -> None:
        try:
            with open(os.path.join(DIST_DIR, "share.html"), encoding="utf-8") as f:
                html = f.read()
        except OSError:
            return self._not_found()
        base = f'<head><base href="/s/{share["token"]}/">'
        self._send(200, "text/html; charset=utf-8", _HEAD.sub(lambda _: base, html, count=1).encode("utf-8"))

    def _asset(self, share, name: str) -> None:
        rel = "assets/" + name
        root = os.path.realpath(os.path.join(DIST_DIR, "assets"))
        real = os.path.realpath(os.path.join(DIST_DIR, rel))
        if rel not in allowed_assets() or os.path.commonpath([root, real]) != root or not os.path.isfile(real):
            return self._not_found()
        ctype = (
            "text/javascript" if real.endswith(".js") else mimetypes.guess_type(real)[0] or "application/octet-stream"
        )
        with open(real, "rb") as f:
            self._send(200, ctype, f.read())

    def _prd(self, share) -> None:
        state = ui_shares.prd_state(dispatch.read_checkouts().get(share["repo"]), share["path"])
        if not state["path"]:
            return self._not_found()
        with open(state["path"], "rb") as f:
            text = f.read().decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        self._json(
            200, {"title": state["title"], "status": state["status"], "text": text, "updated_at": state["updated_at"]}
        )

    def _threads(self, share) -> None:
        self._json(200, ui_shares.public_threads(share))

    def _approvals(self, share) -> None:
        self._json(200, ui_shares.public_approvals(share))

    # --- POST and DELETE ---

    def _body(self):
        """The JSON object body, or None after answering 400 or 413. Never reads past MAX_BODY."""
        raw = self.headers.get("Content-Length") or ""
        if not raw.isascii() or not raw.isdigit():
            self._json(400, {"error": "Content-Length required"})
            return None
        if int(raw) > MAX_BODY:
            self._json(413, {"error": "request too large"})
            return None
        try:
            data = json.loads(self.rfile.read(int(raw)).decode("utf-8"))
        except (ValueError, RecursionError):
            data = None
        if not isinstance(data, dict):
            self._json(400, {"error": "body must be a JSON object"})
            return None
        return data

    def _new_thread(self, share) -> None:
        data = self._body()
        if data is not None:
            self._json(
                201,
                ui_shares.public_thread(
                    ui_shares.add_thread(share["id"], data.get("name"), data.get("body"), data.get("anchor"))
                ),
            )

    def _new_comment(self, share, tid: str) -> None:
        data = self._body()
        if data is not None:
            self._json(
                201,
                ui_shares.public_comment(ui_shares.add_comment(share["id"], tid, data.get("name"), data.get("body"))),
            )

    def _approve(self, share) -> None:
        data = self._body()
        if data is not None:
            view, created = ui_shares.add_approval(share["id"], data.get("name"))
            self._json(201 if created else 200, view)

    def _withdraw(self, share) -> None:
        data = self._body()
        if data is None:
            return
        name = data.get("name")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= ui_shares.NAME_MAX:
            return self._json(400, {"error": f"name must be 1 to {ui_shares.NAME_MAX} characters"})
        ui_shares.withdraw_approval(share["id"], name, data.get("key"))
        self._send(204, _JSON)

    do_POST = do_DELETE = do_GET = _handle
    do_HEAD = do_PUT = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = _handle
