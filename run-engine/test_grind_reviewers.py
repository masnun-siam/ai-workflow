#!/usr/bin/env python3
"""Self-check for run-engine/grind_reviewers.py. `python3 test_grind_reviewers.py` — exit 0 = green. No network."""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
AIW = os.path.join(os.path.dirname(HERE), "bin", "aiw")
sys.path.insert(0, HERE)
data = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = data
import grind_reviewers as gr  # noqa: E402
import ui_server  # noqa: E402

SETTINGS = os.path.join(data, "ui_settings.json")
CHANNELS = os.path.join(data, "channels.json")
FR8 = "no Slack channel or reviewer, its lanes skip grinding"
EMPTY = {"path": None, "channel": None, "mentions": [], "logins": [], "unlogged": [], "skip": None}
BLU = {"id": "r-0000000a", "name": "Blubird", "slack_id": "U0000000A", "github_login": "blubird"}
BOB = {"id": "r-0000000b", "name": "Bob", "slack_id": "U0000000B", "github_login": ""}
GIT = {"id": "r-0000000c", "name": "Gita", "slack_id": "", "github_login": "gita"}


def write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))


def settings(repos, active=("r-0000000a", "r-0000000b", "r-0000000c")):
    write(
        SETTINGS,
        {
            "slack_channels": [{"id": "C0123ABCD", "name": "#rev"}],
            "reviewers": [BLU, BOB, GIT],
            "active_reviewers": list(active),
            "repos": repos,
        },
    )


def aiw(url):
    p = subprocess.run([AIW, "grind-reviewers", "--pr", url], capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout)


# --- missing ui_settings.json: channels.json alone, and the file stays missing
write(CHANNELS, {"channels": {"o/m": "C0999ZZZZ"}, "bot_uid": "U0BOT0000"})
assert gr.resolve("o/m") == {**EMPTY, "path": "slack"}, gr.resolve("o/m")
assert gr.resolve("o/unknown") == EMPTY
assert not os.path.exists(SETTINGS)
print("  ok  missing settings resolves from channels.json, writes nothing")

# --- slack path from a Settings channel: mentions and logins follow the active set, in list order
settings({"o/s": {"slack_channel": "C0123ABCD"}})
r = gr.resolve("o/s")
assert r == {
    "path": "slack",
    "channel": "C0123ABCD",
    "mentions": ["U0000000A", "U0000000B"],
    "logins": ["blubird", "gita"],
    "unlogged": ["U0000000B"],
    "skip": None,
}, r
print("  ok  slack path from Settings, unlogged")

# --- slack path from the channels.json mapping only; case-insensitive repo match
assert gr.resolve("O/M")["path"] == "slack" and gr.resolve("O/M")["channel"] is None
settings({"o/r": {"slack_channel": "C0123ABCD"}})
assert gr.resolve_pr("https://github.com/O/R/pull/1")["channel"] == "C0123ABCD"
print("  ok  mapping only; case-insensitive")

# --- github path: logins, no unlogged
settings({"o/g": {}})
r = gr.resolve("o/g")
assert r == {**EMPTY, "path": "github", "mentions": ["U0000000A", "U0000000B"], "logins": ["blubird", "gita"]}, r
print("  ok  github path")

# --- override beats the active set; [] is an override; null follows the active set
settings({"o/g": {"reviewers": ["r-0000000c"]}, "o/e": {"reviewers": []}, "o/n": {"reviewers": None}})
assert gr.resolve("o/g")["logins"] == ["gita"]
assert gr.resolve("o/e") == {**EMPTY, "skip": FR8}
assert gr.resolve("o/n")["logins"] == ["blubird", "gita"]
print("  ok  repo override")

# --- slack path, login-only reviewer: bot_uid keeps it grinding, none skips
settings({"o/s": {"slack_channel": "C0123ABCD"}}, active=["r-0000000c"])
assert gr.resolve("o/s") == {**EMPTY, "path": "slack", "channel": "C0123ABCD", "logins": ["gita"]}
write(CHANNELS, {"channels": {"o/m": "C0999ZZZZ"}})
assert gr.resolve("o/s") == {**EMPTY, "skip": FR8}
# github path with no login: skip
settings({"o/g": {}}, active=["r-0000000b"])
assert gr.resolve("o/g") == {**EMPTY, "skip": FR8}
print("  ok  FR-8 skips")

# --- invalid stored channel: its own skip, never the mapping
write(CHANNELS, {"channels": {"o/i": "C0999ZZZZ"}, "bot_uid": "U0BOT0000"})
settings({"o/i": {"slack_channel": "general"}})
assert gr.resolve("o/i") == {**EMPTY, "skip": "invalid Slack channel general, pick a channel in Settings"}
print("  ok  invalid channel")

# --- CLI: unknown repo, unparseable url, corrupt settings
assert aiw("https://github.com/x/y/pull/3") == (0, EMPTY)
assert aiw("not a url") == (0, EMPTY)
assert aiw("https://github.com/o/i/pull/3")[1]["skip"].startswith("invalid Slack channel")
write(SETTINGS, "{bad")
code, out = aiw("https://github.com/o/i/pull/3")
assert code == 1 and set(out) == {"error"} and "ui_settings.json" in out["error"], (code, out)
assert gr.resolve("o/i")["path"] == "slack"  # not strict: lenient read, no raise
print("  ok  aiw grind-reviewers")

# --- settings_view and GET/PUT /api/settings
write(CHANNELS, {"channels": {"o/m": "C0999ZZZZ"}, "bot_uid": "U0BOT0000", "bot_label": "Bot"})
settings({"o/s": {"slack_channel": "C0123ABCD"}, "o/g": {}, "o/i": {"slack_channel": "general"}})
srv = ui_server._Server(("127.0.0.1", 0), ui_server._Handler, ())
threading.Thread(target=srv.serve_forever, daemon=True).start()
host = f"127.0.0.1:{srv.server_address[1]}"


def call(method, body=None):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    raw = json.dumps(body).encode() if body is not None else b""
    c.request(method, "/api/settings", body=raw or None, headers={"Host": host, "Content-Length": str(len(raw))})
    r = c.getresponse()
    out = json.loads(r.read())
    c.close()
    return r.status, out


st, got = call("GET")
assert st == 200 and got["bot_label"] == "Bot", got
assert {k: v["path"] for k, v in got["repos"].items()} == {"o/s": "slack", "o/g": "github", "o/i": None}, got
st, put = call("PUT", got)
assert st == 200, put
assert call("GET")[1] == got
with open(SETTINGS, encoding="utf-8") as f:
    stored = json.load(f)
assert "bot_label" not in stored and all("path" not in r for r in stored["repos"].values()), stored
write(CHANNELS, {"bot_label": ""})
assert call("GET")[1]["bot_label"] is None
srv.shutdown()
print("  ok  GET adds bot_label and path; PUT ignores them")
print("grind_reviewers: all checks passed")
