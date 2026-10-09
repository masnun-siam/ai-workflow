"""Tests for ui_tailscale + the owner-only tailnet guard in ui_server. Run: python3 test_ui_tailscale.py

A fake `tailscale` on PATH records its argv and answers from env, so no real tailnet config is touched.
"""
import http.client
import io
import json
import os
import stat
import sys
import tempfile
import threading
from contextlib import redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ui_server  # noqa: E402
import ui_tailscale as ts  # noqa: E402

n_ok = 0


def ok(label):
    global n_ok
    n_ok += 1
    print(f"  ok  {label}")


tmp = tempfile.mkdtemp()
LOG = os.path.join(tmp, "calls.log")
FAKE = os.path.join(tmp, "tailscale")
with open(FAKE, "w") as f:
    f.write('''#!/usr/bin/env python3
import os, sys
a = sys.argv[1:]
open(os.environ["FAKE_TS_LOG"], "a").write(" ".join(a) + "\\n")
if a[:2] == ["status", "--json"]:
    print(os.environ["FAKE_TS_STATUS"])
elif a[:3] == ["serve", "status", "--json"]:
    print(os.environ.get("FAKE_TS_SERVE", "{}"))
else:
    sys.exit(int(os.environ.get("FAKE_TS_RC", "0")))
''')
os.chmod(FAKE, os.stat(FAKE).st_mode | stat.S_IXUSR)

RUNNING = json.dumps({"BackendState": "Running", "Self": {"DNSName": "mac.tail.ts.net.", "UserID": 7},
                      "User": {"7": {"LoginName": "Owner@Example.com"}}})
OLD = os.environ["PATH"]


def env(status=RUNNING, serve="{}", rc="0", path=True):
    os.environ.update(FAKE_TS_LOG=LOG, FAKE_TS_STATUS=status, FAKE_TS_SERVE=serve, FAKE_TS_RC=rc)
    os.environ["PATH"] = (tmp + os.pathsep + OLD) if path else "/nonexistent"
    open(LOG, "w").close()


def calls():
    return open(LOG).read().splitlines()


def quiet(fn, *a):
    err = io.StringIO()
    with redirect_stderr(err):
        res = fn(*a)
    return res, err.getvalue()


# --- node()
env(path=False)
assert ts.node() is None and ts.up(8420) is None
ok("no tailscale on PATH: nothing to serve")
env(status=json.dumps({"BackendState": "Stopped"}))
assert ts.node() is None and quiet(ts.up, 8420)[0] is None and not any(c.startswith("serve") for c in calls())
ok("tailscale stopped: not serving")
env()
assert ts.node() == {"dns": "mac.tail.ts.net", "login": "Owner@Example.com"}
ok("node: DNS name without the trailing dot, owner login")

# --- up()
r, _ = quiet(ts.up, 8420)
assert r == {"url": "https://mac.tail.ts.net", "hosts": {"mac.tail.ts.net"}, "login": "Owner@Example.com", "https_port": 443}, r
assert "serve --bg --https=443 http://127.0.0.1:8420" in calls()
ok("serves 127.0.0.1:<port> on 443 by default, tailnet-only (no funnel)")
assert not any("funnel" in c for c in calls())
env()
r, _ = quiet(ts.up, 8420, 8443)
assert r["url"] == "https://mac.tail.ts.net:8443" and r["hosts"] == {"mac.tail.ts.net:8443"}
ok("another port gives a :port URL and Host")

busy = json.dumps({"Web": {"mac.tail.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8787"}}}}})
env(serve=busy)
r, err = quiet(ts.up, 8420)
assert r is None and "already serves http://127.0.0.1:8787" in err and not any(c.startswith("serve --bg") for c in calls()), calls()
ok("an occupied port is never overwritten")
mine = json.dumps({"Web": {"mac.tail.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8420"}}}}})
env(serve=mine)
r, _ = quiet(ts.up, 8420)
assert r and r["hosts"] == {"mac.tail.ts.net"} and not any(c.startswith("serve --bg") for c in calls()), (r, calls())
ok("a handler left pointing at this very port by an earlier aiw ui is adopted, not refused")
other = json.dumps({"Web": {"mac.tail.ts.net:8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8787"}}}}})
env(serve=other)
assert quiet(ts.up, 8420)[0] is not None
ok("a different port in use does not block 443")
env()
assert quiet(ts.up, 8420, 8080)[0] is None and "must be one of" in quiet(ts.up, 8420, 8080)[1]
ok("only 443, 8443 and 10000 are accepted")
env(rc="1")
r, err = quiet(ts.up, 8420)
assert r is None and "serve failed" in err
ok("a failing serve command is reported, not fatal")

env()
ts.down(443)
assert "serve --https=443 off" in calls()
ok("down removes only our handler")

# --- owner-only guard on a real server
srv = ui_server._Server(("127.0.0.1", 0), ui_server._Handler, (), lambda *a: None)
srv.allowed_hosts |= {"mac.tail.ts.net:8443"}
srv.tailnet_hosts, srv.tailnet_login = frozenset({"mac.tail.ts.net:8443"}), "owner@example.com"
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]


def get(host, **headers):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.putrequest("GET", "/api/health", skip_host=True)
    c.putheader("Host", host)
    for k, v in headers.items():
        c.putheader(k.replace("_", "-"), v)
    c.endheaders()
    r = c.getresponse()
    r.read()
    c.close()
    return r.status


try:
    assert get("mac.tail.ts.net:8443") == 403
    ok("tailnet host without a login header is refused")
    assert get("mac.tail.ts.net:8443", Tailscale_User_Login="mallory@example.com") == 403
    ok("tailnet host with someone else's login is refused")
    assert get("mac.tail.ts.net:8443", Tailscale_User_Login="OWNER@example.com") == 200
    ok("the owner's login (case-insensitive) is allowed")
    assert get("mac.tail.ts.net:8443", Tailscale_User_Login="owner@example.com", Origin="https://evil.example") == 403
    ok("the Origin check still applies on the tailnet")
    assert get(f"127.0.0.1:{port}") == 200
    ok("loopback needs no login header")
    assert get("mac.tail.ts.net") == 403
    ok("a tailnet name on a port we never served is not an allowed Host")
finally:
    srv.shutdown()
    os.environ["PATH"] = OLD

print(f"\n{n_ok} passed")
