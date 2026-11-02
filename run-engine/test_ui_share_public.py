#!/usr/bin/env python3
"""Self-check for run-engine/ui_share_public.py. `python3 test_ui_share_public.py` — exit 0 = green."""

from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()
import dispatch  # noqa: E402
import ui_share_public as P  # noqa: E402
import ui_shares as S  # noqa: E402

n = 0


def ok(label):
    global n
    n += 1
    print("ok", label)


co = os.path.realpath(tempfile.mkdtemp())
prds = os.path.join(co, "docs", "prds")
os.makedirs(prds)
PRD = os.path.join(prds, "x.md")
SLUG = "secret-org/secret-repo"


def write_prd(status="Draft", text="Body line\r\nsecond"):
    with open(PRD, "w", newline="") as f:
        f.write(f"# PRD — Title\n\n**Status:** {status} · **Slug:** `x`\n\n{text}\n")


write_prd()
dispatch.register_checkout(SLUG, co)
share, _ = S.create(SLUG, "docs/prds/x.md", co)
TOKEN, SID = share["token"], share["id"]

dist = tempfile.mkdtemp()
os.makedirs(os.path.join(dist, "assets"))
os.makedirs(os.path.join(dist, ".vite"))
for name, body in {
    "share.html": "<html><head><title>s</title></head></html>",
    "assets/share-abc.js": "x()",
    "assets/lazy.css": "a{}",
    "assets/ui-only.js": "y()",
}.items():
    with open(os.path.join(dist, name), "w") as f:
        f.write(body)
manifest = {
    "share.html": {"file": "assets/share-abc.js", "src": "share.html", "isEntry": True, "dynamicImports": ["lazy.js"]},
    "lazy.js": {"file": "assets/lazy.js", "css": ["assets/lazy.css"]},
    "index.html": {"file": "assets/ui-only.js", "src": "index.html", "isEntry": True},
}
with open(os.path.join(dist, ".vite", "manifest.json"), "w") as f:
    json.dump(manifest, f)
with open(os.path.join(dist, "assets", "lazy.js"), "w") as f:
    f.write("z()")
P.DIST_DIR = dist

srv = P.make_server()
port = srv.server_address[1]
assert srv.server_address[0] == "127.0.0.1" and srv.allowed_hosts == set()
HOST = "share.example.ts.net"
srv.allowed_hosts.add(HOST)
threading.Thread(target=srv.serve_forever, daemon=True).start()


def req(method, path, body=None, host=HOST, origin="auto", ctype="application/json", length="auto", raw=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    if host is not None:
        c.putheader("Host", host)
    if method in ("POST", "DELETE"):
        if origin == "auto":
            origin = f"https://{host}"
        if origin is not None:
            c.putheader("Origin", origin)
        if ctype:
            c.putheader("Content-Type", ctype)
        data = raw if raw is not None else json.dumps(body).encode("utf-8")
        if length == "auto":
            length = str(len(data))
        if length is not None:
            c.putheader("Content-Length", length)
        c.endheaders(data)
    else:
        c.endheaders()
    r = c.getresponse()
    out = r.read()
    hdrs = dict(r.getheaders())
    c.close()
    return r.status, hdrs, out


def js(*a, **k):
    st, h, b = req(*a, **k)
    return st, (json.loads(b) if b and h["Content-Type"].startswith("application/json") else None)


def headers_ok(h):
    assert h["Referrer-Policy"] == "no-referrer" and h["X-Robots-Tag"] == "noindex" and h["Cache-Control"] == "no-store"
    assert h["Content-Security-Policy"] == (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"
    )


BASE = f"/s/{TOKEN}"
WRONG = "/s/" + "A" * 43
T = {"name": "Ann", "body": "hi", "anchor": {"exact": "Body", "prefix": "", "suffix": ""}}

# --- the one 404
st, h, ref = req("GET", "/")
assert st == 404 and ref == b"not found"
headers_ok(h)
cases = [
    ("GET", "/api/sessions"),
    ("GET", "/api/shares"),
    ("GET", "/s/"),
    ("GET", WRONG),
    ("GET", f"{BASE}/api/sessions"),
    ("GET", f"{BASE}/assets/ui-only.js"),
    ("GET", f"{BASE}/assets/../x"),
    ("GET", f"{BASE}/../x"),
    ("GET", f"{BASE}/assets/%2e%2e/share.html"),
    ("GET", f"{BASE}/api/prd", None, "evil.com"),
    ("GET", f"{BASE}/api/prd", None, None),
    ("GET", f"{BASE}/api/prd", None, f"127.0.0.1:{port}"),
    ("PUT", f"{BASE}/api/threads"),
    ("PATCH", f"{BASE}/api/threads"),
    ("OPTIONS", f"{BASE}/api/threads"),
    ("POST", f"{BASE}/api/threads", T, HOST, None),
    ("POST", f"{BASE}/api/threads", T, HOST, "auto", "text/plain"),
    ("POST", f"{BASE}/api/threads", T, HOST, "auto", None),
    ("POST", f"{BASE}/api/threads", T, HOST, "https://evil.com"),
    ("DELETE", f"{BASE}/api/approvals", {"name": "A", "key": "k"}, HOST, None),
    ("POST", f"{WRONG}/api/threads", T),
    ("GET", f"{BASE}/api/nope"),
    ("POST", f"{BASE}/api/prd", T),
]
for c in cases:
    st, h, body = req(*c)
    assert st == 404 and body == ref, (c, st, body)
    headers_ok(h)
st, h, _ = req("HEAD", f"{BASE}/api/prd")
assert st == 404
assert req("POST", f"{BASE}/api/threads", T, HOST, "auto", "application/json; charset=utf-8")[0] == 201
ok("every guard gives the same 404")

# an expired share is the same 404
S.update(SID, lambda r: r.update(expires_at="2000-01-01T00:00:00.000+00:00"))
st, h, body = req("GET", f"{BASE}/api/prd")
assert st == 404 and body == ref and S.get(SID)["end_reason"] == "expired"
headers_ok(h)
S.create(SLUG, "docs/prds/x.md", co)
TOKEN, SID = S.get(SID)["token"], SID
BASE = f"/s/{TOKEN}"
ok("expired share gives the same 404")

# --- page and assets
st, h, body = req("GET", BASE)
assert st == 200 and h["Content-Type"].startswith("text/html")
assert body == f'<html><head><base href="/s/{TOKEN}/"><title>s</title></head></html>'.encode()
assert req("GET", BASE + "/")[2] == body
headers_ok(h)
st, h, body = req("GET", f"{BASE}/assets/share-abc.js")
assert st == 200 and body == b"x()" and h["Content-Type"].startswith("text/javascript")
assert req("GET", f"{BASE}/assets/lazy.js")[0] == 200 and req("GET", f"{BASE}/assets/lazy.css")[0] == 200
assert req("GET", f"{BASE}/assets/ui-only.js")[2] == ref
os.remove(os.path.join(dist, "share.html"))
assert req("GET", BASE)[2] == ref
ok("page and asset allow-list")

# --- prd
st, d = js("GET", f"{BASE}/api/prd")
assert st == 200 and set(d) == {"title", "status", "text", "updated_at"} and d["title"] == "Title"
assert "Body line\nsecond" in d["text"] and "\r" not in d["text"] and d["status"] == "Draft"
write_prd(text="Edited")
assert "Edited" in js("GET", f"{BASE}/api/prd")[1]["text"]
ok("api/prd reads the file now")

# --- threads, comments, approvals
st, t = js("POST", f"{BASE}/api/threads", T)
assert st == 201 and t["comments"][0]["author"] == "Ann" and t["resolved"] is False
st, c = js("POST", f"{BASE}/api/threads/{t['id']}/comments", {"name": "Bob", "body": "re"})
assert st == 201 and c["author"] == "Bob" and c["by_owner"] is False
assert js("POST", f"{BASE}/api/threads/ffff/comments", {"name": "B", "body": "r"})[0] == 404
assert req("POST", f"{BASE}/api/threads/ffff/comments", {"name": "B", "body": "r"})[2] == ref
lst = js("GET", f"{BASE}/api/threads")[1]
assert len(lst) == 2 and len(next(x for x in lst if x["id"] == t["id"])["comments"]) == 2
st, a = js("POST", f"{BASE}/api/approvals", {"name": "Cy"})
assert st == 201 and a["key"]
st, a2 = js("POST", f"{BASE}/api/approvals", {"name": "cy"})
assert st == 200 and "key" not in a2
assert js("GET", f"{BASE}/api/approvals")[1] == [{"name": "Cy", "at": a["at"]}]
for bad in ({"name": "Cy", "key": "wrong"}, {"name": "Zed", "key": a["key"]}):
    assert req("DELETE", f"{BASE}/api/approvals", bad)[2] == ref
assert js("DELETE", f"{BASE}/api/approvals", {"name": ""})[0] == 400
assert req("DELETE", f"{BASE}/api/approvals", {"name": "Cy", "key": a["key"]})[0] == 204
assert js("GET", f"{BASE}/api/approvals")[1] == []
ok("threads, comments, approvals")

# --- validation, limits
S.clock = lambda: 1000.0
assert js("POST", f"{BASE}/api/threads", {**T, "body": "x" * 2001})[0] == 400
assert js("POST", f"{BASE}/api/threads", {**T, "name": "n" * 61})[0] == 400
assert js("POST", f"{BASE}/api/threads", {**T, "anchor": {"exact": "e" * 1001}})[0] == 400
assert js("POST", f"{BASE}/api/threads", {**T, "body": "\ud800"})[0] == 400
st, e = js("POST", f"{BASE}/api/threads", raw=b"[1]")
assert st == 400 and "error" in e
assert js("POST", f"{BASE}/api/threads", raw=b"{bad")[0] == 400
assert req("POST", f"{BASE}/api/threads", raw=b"{}", length=None)[0] == 400
assert req("POST", f"{BASE}/api/threads", raw=b"x" * 16385)[0] == 413
assert req("POST", f"{WRONG}/api/threads", raw=b"x" * 16385)[2] == ref
headers_ok(req("POST", f"{BASE}/api/threads", raw=b"x" * 16385)[1])
# the earlier writes used the real clock; with a fixed one the window holds RATE_MAX more
S._rates.clear()
for i in range(S.RATE_MAX):
    assert js("POST", f"{BASE}/api/threads", {**T, "body": f"r{i}"})[0] == 201, i
st, h, _ = req("POST", f"{BASE}/api/threads", T)
assert st == 429
headers_ok(h)
S.clock = __import__("time").time
S._rates.clear()
S.update(
    SID,
    lambda r: r["threads"].__setitem__(
        slice(None),
        [
            {
                "id": "aa",
                "anchor": {"exact": "e", "prefix": "", "suffix": ""},
                "created_at": "",
                "resolved": False,
                "sent_at": None,
                "comments": [
                    {"id": str(i), "author": "a", "by_owner": False, "body": "b", "at": "t"} for i in range(500)
                ],
            }
        ],
    ),
)
st, h, _ = req("POST", f"{BASE}/api/threads", T)
assert st == 409
headers_ok(h)
S.update(SID, lambda r: r["threads"].clear())
S.update(
    SID,
    lambda r: r["approvals"].extend({"id": str(i), "name": f"n{i}", "at": "t", "key_hash": "h"} for i in range(100)),
)
assert js("POST", f"{BASE}/api/approvals", {"name": "new"})[0] == 409
assert js("POST", f"{BASE}/api/approvals", {"name": "n1"})[0] == 200
S.update(SID, lambda r: r["approvals"].clear())
ok("validation, 409, 413, 429")

# --- xss and Bengali round trip
xss = "<img src=x onerror=alert(1)>"
st, h, body = req("POST", f"{BASE}/api/threads", {"name": xss, "body": xss, "anchor": {"exact": xss}})
assert st == 201 and h["Content-Type"] == "application/json; charset=utf-8"
assert json.loads(body)["comments"][0]["body"] == xss and xss.encode() in body
bn = "ক" * 1000
big = {"name": "ক" * 60, "body": "ক" * 2000, "anchor": {"exact": bn, "prefix": "ক" * 32, "suffix": "ক" * 32}}
S._rates.clear()
raw = json.dumps(big, ensure_ascii=False).encode()
assert len(raw) <= P.MAX_BODY
assert req("POST", f"{BASE}/api/threads", raw=raw)[0] == 201
ok("xss and Bengali")

# --- no leaks
S.update(SID, lambda r: r["threads"].clear())
leaks = [SLUG, "secret-repo", "docs/prds/x.md", PRD, co]
branchy = [
    ("GET", f"{BASE}/api/threads"),
    ("GET", f"{BASE}/api/approvals"),
    ("GET", BASE + "/assets/share-abc.js"),
    ("GET", BASE),
    ("POST", f"{BASE}/api/threads", T),
    ("GET", "/"),
    ("GET", WRONG),
]
os.makedirs(dist, exist_ok=True)
with open(os.path.join(dist, "share.html"), "w") as f:
    f.write("<html><head></head></html>")
for c in branchy:
    st, h, body = req(*c)
    blob = body + repr(h).encode()
    assert not any(x.encode() in blob for x in leaks), c
d = js("GET", f"{BASE}/api/prd")[1]
assert not any(k in d for k in ("repo", "path", "branch"))
ok("no repo, path or branch leaks")

# --- concurrent writes
S._rates.clear()
S.update(SID, lambda r: r["threads"].clear())
res = []
ts = [
    threading.Thread(target=lambda i=i: res.append(js("POST", f"{BASE}/api/threads", {**T, "body": f"c{i}"})[0]))
    for i in range(20)
]
[x.start() for x in ts]
[x.join() for x in ts]
assert res == [201] * 20, res
assert len(S.get(SID)["threads"]) == 20, len(S.get(SID)["threads"])
ok("20 concurrent threads all saved")

# --- the end check
write_prd("Approved")
assert req("GET", f"{BASE}/api/threads")[2] == ref
assert S.get(SID)["end_reason"] == "approved"
outside = os.path.join(tempfile.mkdtemp(), "o.md")
with open(outside, "w") as f:
    f.write("# PRD — o\n\n**Status:** Draft\n")
for breakit in (lambda: os.remove(PRD), lambda: (os.remove(PRD), os.symlink(outside, PRD))):
    write_prd("Draft")
    tok = S.create(SLUG, "docs/prds/x.md", co)[0]["token"]
    assert req("GET", f"/s/{tok}/api/prd")[0] == 200
    breakit()
    assert req("GET", f"/s/{tok}/api/prd")[2] == ref
    assert S.get(SID)["end_reason"] == "missing"
os.path.lexists(PRD) and os.remove(PRD)
ok("end check: approved, missing, symlink")

assert P._Handler.timeout > 0
_old_timeout, P._Handler.timeout = P._Handler.timeout, 0.5
import socket  # noqa: E402

with socket.create_connection(("127.0.0.1", port), timeout=5) as idle:
    assert idle.recv(1) == b""  # server closed the silent connection
P._Handler.timeout = _old_timeout
ok("idle connection times out")

print(f"{n} groups passed")
