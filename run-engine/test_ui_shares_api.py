#!/usr/bin/env python3
"""Self-check for run-engine/ui_share_api.py through the UI server. `python3 test_ui_shares_api.py` — exit 0 = green."""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

data_dir = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = data_dir

import ui_gh  # noqa: E402
import ui_server  # noqa: E402
import ui_share_runtime as rt  # noqa: E402
import ui_shares  # noqa: E402
import ui_tailscale  # noqa: E402

ui_gh.status = lambda *a, **k: {"ok": True, "login": "me", "error": None}
passed = 0


def ok(label):
    global passed
    passed += 1
    print(f"  ok  {label}")


# fake runtime
fake = {"err": None, "syncs": 0, "up": 0}


def ensure_up():
    if fake["err"]:
        raise fake["err"]
    fake["up"] += 1
    return {"base": "https://box.ts.net:8443"}


rt.ensure_up = ensure_up
rt.sync = lambda: fake.update(syncs=fake["syncs"] + 1)
rt.link = lambda s: f"https://box.ts.net:8443/s/{s['token']}"
rt.reachable = lambda: True

checkout = tempfile.mkdtemp()
git = lambda *a: subprocess.run(["git", *a], cwd=checkout, capture_output=True, check=True)  # noqa: E731
git("init", "-q")
git("config", "user.name", "Ada")
os.makedirs(os.path.join(checkout, "docs", "prds"))


def prd(name, status="Draft"):
    with open(os.path.join(checkout, "docs", "prds", name), "w") as f:
        f.write(f"# Title of {name}\n\n**Status:** {status}\n\nbody\n")


prd("a.md")
prd("approved.md", "Approved")
with open(os.path.join(checkout, "docs", "prds", "nostatus.md"), "w") as f:
    f.write("# No status\n\ntext\n")
with open(os.path.join(data_dir, "checkouts.json"), "w") as f:
    json.dump({"o/r": checkout}, f)

srv = ui_server._Server(("127.0.0.1", 0), ui_server._Handler, ["tail.ts.net"])
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
HOST = f"127.0.0.1:{port}"


def call(method, path, body=None, host=HOST, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    c.putheader("Host", host)
    for k, v in (headers or {}).items():
        c.putheader(k, v)
    raw = json.dumps(body).encode() if body is not None else None
    if raw is not None:
        c.putheader("Content-Length", str(len(raw)))
    c.endheaders(raw)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, (
        json.loads(data) if data and r.getheader("Content-Type", "").startswith("application/json") else data
    )


START = {"repo": "o/r", "path": "docs/prds/a.md", "confirm": True}
try:
    # start
    s, sh = call("POST", "/api/shares", START)
    assert s == 201 and sh["url"].startswith("https://box.ts.net:8443/s/") and sh["state"] == "live", (s, sh)
    sid = sh["id"]
    s, again = call("POST", "/api/shares", {"repo": "o/r", "path": "docs/prds/a.md"})
    assert s == 200 and again["id"] == sid and again["url"] == sh["url"]
    ok("start 201 then 200 without confirm")
    for bad in (None, False, "true", 1):
        s, _ = call("POST", "/api/shares", {"repo": "o/r", "path": "docs/prds/nostatus.md", "confirm": bad})
        assert s == 400, bad
    s, _ = call("POST", "/api/shares", {"repo": "o/r", "path": "docs/prds/nostatus.md"})
    assert s == 400 and ui_shares.find("o/r", "docs/prds/nostatus.md") is None
    ok("confirm must be true")
    for body in (
        {"repo": "x/y", "path": "docs/prds/a.md", "confirm": True},
        {"repo": "o/r", "path": "README.md", "confirm": True},
        {"repo": "o/r", "path": "docs/prds/../a.md", "confirm": True},
        {"repo": "o/r", "path": "docs/prds/zz.md", "confirm": True},
    ):
        assert call("POST", "/api/shares", body)[0] == 400, body
    s, e = call("POST", "/api/shares", {"repo": "o/r", "path": "docs/prds/approved.md", "confirm": True})
    assert s == 409, (s, e)
    assert call("POST", "/api/shares", {"repo": "o/r", "path": "docs/prds/nostatus.md", "confirm": True})[0] == 201
    ok("400 repo/path/missing, 409 approved, unparsed header accepted")

    # runtime errors leave nothing
    prd("b.md")
    fake["err"] = ui_tailscale.FunnelError("port_taken", "port busy")
    s, e = call("POST", "/api/shares", {"repo": "o/r", "path": "docs/prds/b.md", "confirm": True})
    assert s == 409 and e["error"] == "port busy"
    fake["err"] = ui_tailscale.FunnelError("unavailable", "Tailscale is stopped")
    s, e = call("POST", "/api/shares", {"repo": "o/r", "path": "docs/prds/b.md", "confirm": True})
    assert s == 503 and e["error"] == "Tailscale is stopped"
    fake["err"] = None
    assert ui_shares.find("o/r", "docs/prds/b.md") is None
    ok("runtime 409/503 create nothing")

    # list and get
    s, lst = call("GET", "/api/shares")
    assert s == 200 and {x["id"] for x in lst} >= {sid}
    row = next(x for x in lst if x["id"] == sid)
    assert set(row) == {"id", "repo", "path", "title", "state", "url", "comments", "unread", "reachable", "end_reason"}
    assert row["title"] == "Title of a.md" and row["reachable"] is True
    s, det = call("GET", f"/api/shares/{sid}")
    assert (
        s == 200 and det["threads"] == [] and det["approvals"] == [] and "last_seen_at" in det and det["prd_updated_at"]
    )
    assert call("GET", "/api/shares/0123456789abcdef")[0] == 404
    assert call("GET", "/api/shares/zz")[0] == 404
    ok("list/get fields, 404")

    # seed reviewer content through the store
    t = ui_shares.add_thread(sid, "Rev", "first", {"exact": "body"})
    ui_shares.add_comment(sid, t["id"], "Rev2", "second")
    view, _ = ui_shares.add_approval(sid, "Rev3")
    s, det = call("GET", f"/api/shares/{sid}")
    assert det["unread"] == 3 and det["comments"] == 2
    flat = json.dumps(det)
    assert "key_hash" not in flat and "key" not in det["approvals"][0] and flat.count(ui_shares.get(sid)["token"]) == 1
    ok("unread, no key_hash, token only in url")
    assert call("POST", f"/api/shares/{sid}/seen")[0] == 204
    assert call("GET", f"/api/shares/{sid}")[1]["unread"] == 0
    ui_shares.add_comment(sid, t["id"], "Rev4", "third")
    assert call("GET", f"/api/shares/{sid}")[1]["unread"] == 1
    assert call("POST", "/api/shares/0123456789abcdef/seen")[0] == 404
    ok("seen")

    # replies and resolve
    cp = f"/api/shares/{sid}/threads/{t['id']}"
    s, c = call("POST", cp + "/comments", {"body": "ok"})
    assert s == 201 and c["by_owner"] is True and c["author"] == "Ada"
    git("config", "--unset", "user.name")
    s, c2 = call("POST", cp + "/comments", {"body": "ok2"})
    if c2["author"] != "Author":  # a global user.name may still apply
        assert subprocess.run(["git", "config", "user.name"], cwd=checkout, capture_output=True).stdout.strip()
    git("config", "user.name", "Ada")
    for b in ({"body": ""}, {"body": "x" * 2001}, {}):
        assert call("POST", cp + "/comments", b)[0] == 400
    assert call("POST", f"/api/shares/{sid}/threads/nope/comments", {"body": "x"})[0] == 404
    assert call("GET", f"/api/shares/{sid}")[1]["comments"] == 3
    s, th = call("PATCH", cp, {"resolved": True})
    assert s == 200 and th["resolved"] is True
    assert call("PATCH", cp, {"resolved": "yes"})[0] == 400
    assert call("PATCH", f"/api/shares/{sid}/threads/nope", {"resolved": True})[0] == 404
    ok("replies and resolve")

    # deletes
    first = ui_shares.get(sid)["threads"][0]["comments"][0]["id"]
    assert call("DELETE", f"{cp}/comments/{first}")[0] == 204
    det = call("GET", f"/api/shares/{sid}")[1]
    assert len(det["threads"]) == 1 and det["threads"][0]["comments"][0]["id"] != first
    assert call("DELETE", f"{cp}/comments/{first}")[0] == 404
    assert call("DELETE", f"{cp}")[0] == 204 and call("DELETE", cp)[0] == 404
    t2 = ui_shares.add_thread(sid, "R", "solo", {"exact": "body"})
    only = ui_shares.get(sid)["threads"][0]["comments"][0]["id"]
    assert call("DELETE", f"/api/shares/{sid}/threads/{t2['id']}/comments/{only}")[0] == 204
    assert call("GET", f"/api/shares/{sid}")[1]["threads"] == []
    aid = call("GET", f"/api/shares/{sid}")[1]["approvals"][0]["id"]
    assert call("DELETE", f"/api/shares/{sid}/approvals/{aid}")[0] == 204
    assert call("DELETE", f"/api/shares/{sid}/approvals/{aid}")[0] == 404
    assert call("DELETE", f"/api/shares/{sid}/record")[0] == 409
    ok("deletes")

    # stop; ended share keeps working; re-share failing keeps threads
    t3 = ui_shares.add_thread(sid, "R", "keep", {"exact": "body"})
    before = fake["syncs"]
    s, ended = call("DELETE", f"/api/shares/{sid}")
    assert s == 200 and ended["end_reason"] == "stopped" and ended["url"] is None and ended["reachable"] is False
    assert fake["syncs"] > before
    assert call("DELETE", f"/api/shares/{sid}")[0] == 200
    assert call("DELETE", "/api/shares/0123456789abcdef")[0] == 404
    assert call("POST", f"/api/shares/{sid}/threads/{t3['id']}/comments", {"body": "late"})[0] == 201
    assert call("PATCH", f"/api/shares/{sid}/threads/{t3['id']}", {"resolved": False})[0] == 200
    fake["err"] = ui_tailscale.FunnelError("unavailable", "down")
    assert call("POST", "/api/shares", START)[0] == 503
    rec = ui_shares.get(sid)
    assert rec["state"] == "ended" and len(rec["threads"]) == 1
    fake["err"] = None
    ok("stop idempotent, ended share accepts reply, failed re-share leaves record")
    assert call("DELETE", f"/api/shares/{sid}/record")[0] == 204 and ui_shares.get(sid) is None
    assert call("DELETE", f"/api/shares/{sid}/record")[0] == 404
    ok("record delete")

    # PRD turns Approved -> reported ended
    s, sh = call("POST", "/api/shares", START)
    assert s == 201
    prd("a.md", "Approved")
    before = fake["syncs"]
    row = next(x for x in call("GET", "/api/shares")[1] if x["id"] == sh["id"])
    assert row["state"] == "ended" and row["end_reason"] == "approved" and fake["syncs"] > before
    ok("end check on list")

    # guard
    for kw in (
        {"host": "evil.example"},
        {"host": "box.ts.net:8443"},
        {"headers": {"Origin": "http://evil.example"}},
    ):
        assert call("GET", "/api/shares", **kw)[0] == 403, kw
        assert call("DELETE", "/api/shares/0123456789abcdef", **kw)[0] == 403, kw
    assert call("POST", "/api/shares", START, host="box.ts.net:8443")[0] == 403
    srv.tailnet_login = "me@x"
    assert call("GET", "/api/shares", host="tail.ts.net")[0] == 403
    assert call("GET", "/api/shares", host="tail.ts.net", headers={"Tailscale-User-Login": "bob@x"})[0] == 403
    assert call("GET", "/api/shares", host="tail.ts.net", headers={"Tailscale-User-Login": "me@x"})[0] == 200
    ok("guard")
finally:
    srv.shutdown()
    srv.server_close()

print(f"{passed} checks passed")
