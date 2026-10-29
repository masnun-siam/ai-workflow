#!/usr/bin/env python3
"""Self-check for run-engine/ui_share_runtime.py with a fake `tailscale`. `python3 test_ui_share_runtime.py`."""

from __future__ import annotations

import argparse
import http.client
import io
import json
import os
import socket
import stat
import sys
import tempfile
import threading
from contextlib import redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()
import dispatch  # noqa: E402
import ui_server  # noqa: E402
import ui_share_public  # noqa: E402
import ui_share_runtime as R  # noqa: E402
import ui_shares as S  # noqa: E402
import ui_tailscale as ts  # noqa: E402

n = 0


def ok(label):
    global n
    n += 1
    print("ok", label)


tmp = tempfile.mkdtemp()
LOG = os.path.join(tmp, "calls.log")
FAKE = os.path.join(tmp, "tailscale")
with open(FAKE, "w") as f:
    f.write("""#!/usr/bin/env python3
import os, sys
a = sys.argv[1:]
open(os.environ["FAKE_TS_LOG"], "a").write(" ".join(a) + "\\n")
if a[:2] == ["status", "--json"]:
    print(os.environ["FAKE_TS_STATUS"])
elif a[:3] == ["serve", "status", "--json"]:
    print(os.environ.get("FAKE_TS_SERVE", "{}"))
elif a[:3] == ["funnel", "status", "--json"]:
    print(os.environ.get("FAKE_TS_FUNNEL", "{}"))
elif a[0] == "funnel" and os.environ.get("FAKE_TS_FUNNEL_ERR"):
    sys.stderr.write(os.environ["FAKE_TS_FUNNEL_ERR"])
    sys.exit(1)
else:
    sys.exit(0)
""")
os.chmod(FAKE, os.stat(FAKE).st_mode | stat.S_IXUSR)
RUNNING = json.dumps(
    {
        "BackendState": "Running",
        "Self": {"DNSName": "mac.tail.ts.net.", "UserID": 7},
        "User": {"7": {"LoginName": "Owner@Example.com"}},
    }
)
os.environ["PATH"] = tmp + os.pathsep + os.environ["PATH"]
KEY = "mac.tail.ts.net:8443"


def env(serve="{}", funnel="{}", funnel_err=""):
    os.environ.update(FAKE_TS_LOG=LOG, FAKE_TS_STATUS=RUNNING, FAKE_TS_SERVE=serve, FAKE_TS_FUNNEL=funnel)
    os.environ["FAKE_TS_FUNNEL_ERR"] = funnel_err


def calls():
    return open(LOG).read().splitlines()


def funnel_cmds():
    return [c for c in calls() if c.startswith("funnel") and "status" not in c]


def reset(enabled=True):
    """A fresh process as far as the runtime is concerned: module state gone, files kept."""
    R._server = R._thread = R._funnel = R._base = None
    R._reachable = False
    R.configure(443, tailscale_enabled=enabled)
    open(LOG, "w").close()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def quiet(fn, *a):
    err = io.StringIO()
    with redirect_stderr(err):
        res = fn(*a)
    return res, err.getvalue()


def web(port, proxy, funnel_on=False):
    cfg = {"Web": {f"mac.tail.ts.net:{port}": {"Handlers": {"/": {"Proxy": proxy}}}}}
    if funnel_on:
        cfg["AllowFunnel"] = {f"mac.tail.ts.net:{port}": True}
    return json.dumps(cfg)


def refused(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


# --- fixtures
dist = tempfile.mkdtemp()
os.makedirs(os.path.join(dist, "assets"))
with open(os.path.join(dist, "share.html"), "w") as f:
    f.write("<html><head></head></html>")
ui_share_public.DIST_DIR = dist
co = os.path.realpath(tempfile.mkdtemp())
os.makedirs(os.path.join(co, "docs", "prds"))
SLUG = "o/r"
dispatch.register_checkout(SLUG, co)


def write_prd(name, status="Draft"):
    with open(os.path.join(co, "docs", "prds", name + ".md"), "w") as f:
        f.write(f"# PRD — {name}\n\n**Status:** {status} · **Slug:** `{name}`\n\nBody\n")


def share(name):
    write_prd(name)
    rec, _ = S.create(SLUG, f"docs/prds/{name}.md", co)
    return rec


def get_prd(rec):
    c = http.client.HTTPConnection("127.0.0.1", R._server.server_address[1], timeout=5)
    c.request("GET", f"/s/{rec['token']}/api/prd", headers={"Host": KEY})
    return c.getresponse().status


RECORD = os.path.join(os.environ["CLAUDE_PLUGIN_DATA"], "share-runtime.json")

# --- no live share: nothing starts, nothing is called
env()
reset()
R.start()
R.tick()
R.stop()
assert not [c for c in calls() if c.startswith("funnel")] and R._server is None and not os.path.exists(RECORD)
ok("no live share: start, tick and stop make no funnel call and start no listener")

# --- first share
a = share("a")
reset()
base = R.ensure_up()
fport = base["https_port"]
assert base["base"] == f"https://{KEY}" and fport == 8443
lport = base["listener_port"]
assert f"funnel --bg --yes --https=8443 http://127.0.0.1:{lport}" in calls()
assert json.load(open(RECORD)) == {"listener_port": lport, "funnel_port": 8443}
assert R._server.allowed_hosts == {KEY} and R.reachable() and get_prd(a) == 200
assert R.link(a) == f"https://{KEY}/s/{a['token']}"
ok("ensure_up: listener, funnel, record, allowed host, real request answers")
before = len(calls())
assert R.ensure_up() == base and len(calls()) == before
ok("ensure_up again changes nothing and runs no command")

# --- ending shares
b = share("b")
S.end(a["id"], "stopped")
R.sync()
assert R._funnel is not None and get_prd(b) == 200 and "funnel --https=8443 off" not in calls()
ok("ending one of two live shares leaves both up")
S.end(b["id"], "stopped")
R.sync()
assert "funnel --https=8443 off" in calls() and refused(lport) and not os.path.exists(RECORD) and not R.reachable()
ok("ending the last share removes funnel, listener and record")

# --- tick
c = share("c")
reset()
R.ensure_up()
write_prd("c", "Approved")
R.tick()
assert S.get(c["id"])["state"] == "ended" and "funnel --https=8443 off" in calls() and R._server is None
ok("one tick ends an Approved share and removes the funnel")
d, e = share("d"), share("e")
reset()
R.ensure_up()
real = S.refresh


def flaky(sid, checkout):
    if sid == d["id"]:
        raise RuntimeError("boom")
    return real(sid, checkout)


S.refresh = flaky
write_prd("e", "Approved")
_, err = quiet(R.tick)
S.refresh = real
assert S.get(e["id"])["state"] == "ended" and S.get(d["id"])["state"] == "live" and "boom" not in err
ok("an exception in one share does not stop the others")
S.end(d["id"], "stopped")
R.sync()
assert isinstance(R.start_timer(interval=3600), threading.Thread)
ok("start_timer returns a daemon thread")

# --- restart
f_ = share("f")
reset()
first = R.ensure_up()
R.stop()
assert "funnel --https=8443 off" in calls() and refused(first["listener_port"]) and os.path.exists(RECORD)
reset()
R.start()
assert R._funnel and R._server.server_address[1] == first["listener_port"] and R._funnel["https_port"] == 8443
assert R.link(f_) == f"https://{KEY}/s/{f_['token']}" and get_prd(f_) == 200
ok("stop keeps the record; the next start serves the same link on the same ports")
R.stop()
write_prd("f", "Approved")
reset()
R.start()
assert S.get(f_["id"])["state"] == "ended" and not funnel_cmds() and not os.path.exists(RECORD)
ok("an ineligible PRD at start is ended and leaves no funnel")

# --- leftover of an unclean exit
g = share("g")
lp = free_port()
open(RECORD, "w").write(json.dumps({"listener_port": lp, "funnel_port": 8443}))
ours = web(8443, f"http://127.0.0.1:{lp}", funnel_on=True)
env(serve=ours, funnel=ours)
reset()
R.start()
assert R._server.server_address[1] == lp and R.reachable() and not any("funnel --bg" in c for c in calls())
ok("a leftover funnel on the recorded port is adopted")
R.stop()
S.end(g["id"], "stopped")
open(RECORD, "w").write(json.dumps({"listener_port": lp, "funnel_port": 8443}))
reset()
R.start()
assert "funnel --https=8443 off" in calls() and not os.path.exists(RECORD)
ok("no live share + leftover: removed")

# --- foreign handler on the recorded funnel port
h = share("h")
open(RECORD, "w").write(json.dumps({"listener_port": lp, "funnel_port": 8443}))
env(serve=web(8443, "http://127.0.0.1:8787"))
reset()
_, err = quiet(R.start)
assert S.get(h["id"])["state"] == "live" and not R.reachable() and not funnel_cmds() and "not overwriting" in err
R.tick()
assert not funnel_cmds()  # the tick never retries by itself
env()
R.sync()
assert R.reachable() and any("funnel --bg" in c and "--https=8443" in c for c in calls())
ok("foreign handler: live, not reachable, no other port; sync retries once it is gone")

# --- tailscale goes down and back
env(funnel=web(8443, f"http://127.0.0.1:{R._server.server_address[1]}", funnel_on=True))
R.tick()
assert R.reachable()
env()
R.tick()
assert not R.reachable() and S.get(h["id"])["state"] == "live"
env(funnel=web(8443, f"http://127.0.0.1:{R._server.server_address[1]}", funnel_on=True))
R.tick()
assert R.reachable()
ok("tick follows funnel_reachable; the share stays live")
R.stop()
S.end(h["id"], "stopped")
R.sync()

# --- funnel port equal to the UI's
i = share("i")
open(RECORD, "w").write(json.dumps({"listener_port": lp, "funnel_port": 8443}))
env()
reset()
R.configure(8443)
_, err = quiet(R.sync)
assert not funnel_cmds() and not R.reachable() and "UI's own tailnet port" in err
ok("recorded funnel port equal to the UI's: no funnel, not reachable, warned")
os.remove(RECORD)
S.end(i["id"], "stopped")

# --- funnel refused / --no-tailscale
j = share("j")
env(funnel_err="Funnel not available")
reset()
try:
    R.ensure_up()
    raise AssertionError
except ts.FunnelError as ex:
    assert ex.kind == "refused"
assert R._server is None and not os.path.exists(RECORD)
ok("funnel not permitted: FunnelError, no listener, no record")
env()
reset(enabled=False)
try:
    R.ensure_up()
    raise AssertionError
except ts.FunnelError as ex:
    assert ex.kind == "unavailable" and "--no-tailscale" in str(ex) and not funnel_cmds()
ok("--no-tailscale: unavailable, names the flag, no call")
S.end(j["id"], "stopped")

# --- cmd_serve keeps the UI's own tailnet serve separate from the funnel
env()
reset()
port = free_port()
ui_server._Server.serve_forever = lambda self: None  # return at once: start, then exit
ui_server.signal.signal = lambda *a: None
ui_server.cmd_serve(argparse.Namespace(port=port, allow_host=None, no_tailscale=False, tailscale_port=443))
c = calls()
assert f"serve --bg --https=443 http://127.0.0.1:{port}" in c and "serve --https=443 off" in c
assert not [x for x in c if x.startswith("funnel")]
ok("cmd_serve with no live share: tailnet serve up and removed, no funnel call")

print(f"{n} checks passed")
