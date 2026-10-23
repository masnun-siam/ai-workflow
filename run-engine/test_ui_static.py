#!/usr/bin/env python3
"""Self-check for static serving in run-engine/ui_server.py (issue #109, rewritten for the built app).
`python3 test_ui_static.py` — exit 0 = green. Assert-based, like test_ui_server.py.
Reads the committed run-engine/ui_dist (no Node, no build step needed).
"""

from __future__ import annotations

import http.client
import mimetypes
import os
import shutil
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ui_server  # noqa: E402

passed = 0
DIST = os.path.join(HERE, "ui_dist")


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


def req(port, path, host=None, origin=None):
    host = f"127.0.0.1:{port}" if host is None else host
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
    if host:
        c.putheader("Host", host)
    if origin is not None:
        c.putheader("Origin", origin)
    c.endheaders()
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, r, body


def read(p):
    with open(p, "rb") as f:
        return f.read()


srv = ui_server._Server(("127.0.0.1", 0), ui_server._Handler, ())
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
tmp = tempfile.mkdtemp()
real_dist = ui_server.DIST_DIR
try:
    # the committed build
    assert os.path.isfile(os.path.join(DIST, "index.html")), "run-engine/ui_dist is committed: build it from ui/"
    index = read(os.path.join(DIST, "index.html"))
    s, r, body = req(port, "/")
    assert s == 200 and r.getheader("Content-Type", "").startswith("text/html") and body == index
    assert int(r.getheader("Content-Length")) == len(body) and r.getheader("Cache-Control") == "no-cache"
    ok("GET / serves ui_dist/index.html, no-cache")
    for p in ("/next/", "/next", "/next/index.html"):
        assert req(port, p)[0] == 404, p
    ok("the /next/ alias is gone")

    assets = sorted(os.listdir(os.path.join(DIST, "assets")))
    js = next(a for a in assets if a.endswith(".js"))
    css = next(a for a in assets if a.endswith(".css"))
    s, r, body = req(port, f"/assets/{js}")
    assert s == 200 and r.getheader("Content-Type", "").startswith("text/javascript")
    assert body == read(os.path.join(DIST, "assets", js)) and int(r.getheader("Content-Length")) == len(body)
    assert r.getheader("Cache-Control") == "public, max-age=31536000, immutable"
    s, r, _ = req(port, f"/assets/{css}")
    assert s == 200 and r.getheader("Content-Type", "").startswith("text/css")
    assert req(port, f"/next/assets/{js}")[0] == 404
    assert req(port, f"/assets/{js}?v=1")[0] == 200
    ok("hashed assets: content types, immutable cache, query string ignored")

    # root-level files: not hashed, so they revalidate
    for p, t in (
        ("/sw.js", "text/javascript"),
        ("/manifest.webmanifest", "application/manifest+json"),
        ("/icons/icon.svg", "image/svg+xml"),
    ):
        s, r, body = req(port, p)
        assert s == 200 and r.getheader("Content-Type", "").startswith(t), (p, s, r.getheader("Content-Type"))
        assert body == read(os.path.join(DIST, p.lstrip("/"))) and r.getheader("Cache-Control") == "no-cache", p
    s, _, body = req(port, "/icons/icon-192.png")
    assert s == 200 and body[:4] == b"\x89PNG"
    ok("sw.js at the root, manifest and icons served from ui_dist, no-cache")

    # the old /static/ route is gone
    for p in ("/static/app.js", "/static/icons/icon.svg", "/static/vendor/preact.mjs"):
        assert req(port, p)[0] == 404, p
    ok("/static/ is gone")

    # 404s and traversal on the real tree
    s, _, body = req(port, "/assets/nope.js")
    assert s == 404 and b"not found" in body
    ok("missing 404")
    for p in ("/assets", "/assets/", "/icons/", "/next/assets/"):
        assert req(port, p)[0] == 404, p
    ok("directories 404, no listing")
    for p in (
        "/assets/../../route.py",
        "/assets/../../../etc/passwd",
        "/assets/%2e%2e/%2e%2e/route.py",
        "/assets/%2E%2E/%2E%2E/route.py",
        "/assets/..%2f..%2froute.py",
        "/assets/%252e%252e/route.py",
        "/assets//etc/passwd",
        "/icons/../../ui_server.py",
        "/next/../ui_server.py",
        "/next/%2e%2e/ui_server.py",
    ):
        s, _, body = req(port, p)
        assert s == 404 and b"def " not in body and b"root:" not in body, (p, s)
    ok("traversal variants 404")
    assert req(port, "/assets/a%00.js")[0] == 404
    ok("NUL byte 404")

    # guard
    for p, kw in (
        ("/", {"host": "evil.example"}),
        ("/", {"host": ""}),
        (f"/assets/{js}", {"origin": "http://evil.example"}),
        ("/sw.js", {"host": "evil.example"}),
    ):
        s, r, _ = req(port, p, **kw)
        assert s == 403, (p, kw, s)
        assert not any(k.lower().startswith("access-control-") for k, _ in r.getheaders())
    s, r, _ = req(port, "/")
    assert not any(k.lower().startswith("access-control-") for k, _ in r.getheaders())
    ok("guard applies, no CORS")

    # temp root: types, symlink, sibling prefix, missing build
    root = os.path.join(tmp, "ui_dist")
    os.makedirs(os.path.join(root, "assets"))
    for n in ("assets/a.js", "assets/a.css", "a.html", "assets/a.mjs", "index.html"):
        with open(os.path.join(root, n), "w") as f:
            f.write("x")
    with open(os.path.join(tmp, "secret.txt"), "w") as f:
        f.write("SECRET")
    os.symlink(os.path.join(tmp, "secret.txt"), os.path.join(root, "assets", "link"))
    os.makedirs(os.path.join(tmp, "ui_dist_evil"))
    with open(os.path.join(tmp, "ui_dist_evil", "x.js"), "w") as f:
        f.write("EVIL")
    ui_server.DIST_DIR = root
    try:
        for n, t in (("assets/a.js", "text/javascript"), ("assets/a.css", "text/css")):
            s, r, _ = req(port, f"/{n}")
            assert s == 200 and r.getheader("Content-Type", "").startswith(t), (n, s)
        s, r, _ = req(port, "/")
        assert (
            s == 200
            and r.getheader("Content-Type", "").startswith("text/html")
            and r.getheader("Cache-Control") == "no-cache"
        )
        ok("js/css/html content types")
        mimetypes.add_type("application/x-bogus", ".mjs")
        s, r, _ = req(port, "/assets/a.mjs")
        assert s == 200 and r.getheader("Content-Type", "").startswith("text/javascript")
        ok(".mjs forced to text/javascript")
        s, _, body = req(port, "/assets/link")
        assert s == 404 and b"SECRET" not in body
        ok("escaping symlink 404")
        s, _, body = req(port, "/assets/../../ui_dist_evil/x.js")
        assert s == 404 and b"EVIL" not in body
        ok("sibling-prefix escape 404")
        ui_server.DIST_DIR = os.path.join(tmp, "missing")
        assert req(port, "/")[0] == 404
        ok("no build: 404, not a crash")
    finally:
        ui_server.DIST_DIR = real_dist

    # the built page wires up the manifest and the offline service worker
    html = index.decode()
    assert "manifest.webmanifest" in html and "/static/" not in html
    assert "serviceWorker" not in html, "registered once, from the bundle (src/main.tsx)"
    js = "".join(
        read(os.path.join(DIST, "assets", f)).decode()
        for f in os.listdir(os.path.join(DIST, "assets"))
        if f.endswith(".js")
    )
    assert js.count("serviceWorker.register") == 1 and "sw.js" in js
    assert b"/static/" not in read(os.path.join(DIST, "manifest.webmanifest"))
    ok("index.html links the manifest and registers sw.js; nothing points at /static/")
finally:
    srv.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)

print(f"{passed} checks passed")
