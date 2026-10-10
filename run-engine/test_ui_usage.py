#!/usr/bin/env python3
"""Self-check for ui_usage. `python3 test_ui_usage.py` — exit 0 = green."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()
os.environ.pop("CLAUDE_CONFIG_DIR", None)

import ui_usage as u  # noqa: E402


def ok(msg):
    print("  ok ", msg)


assert u.service("claude") == "Claude Code-credentials"
d = os.path.expanduser("~/.claude-profiles/masum")
assert u.service("cc masum") == "Claude Code-credentials-" + hashlib.sha256(d.encode()).hexdigest()[:8]
ok("keychain service: bare for the default dir, hash-suffixed per profile")

assert u._window({"utilization": 34.0, "resets_at": "x", "limit_dollars": None}) == {"pct": 34.0, "resets_at": "x"}
assert u._window(None) is None and u._window({"utilization": None}) is None
ok("window parsing tolerates missing windows")

calls = []
res = {"five_hour": {"pct": 10, "resets_at": "r"}, "seven_day": None}
u.fetch = lambda cmd, now=None: calls.append(cmd) or dict(res)
u.refresh(now=1000.0)
snap = u.snapshot()
assert snap["claude"]["five_hour"]["pct"] == 10 and snap["claude"]["error"] is None and snap["claude"]["at"] == 1000.0
n = len(calls)
u.refresh(now=1100.0)  # inside POLL: cached, no refetch
assert len(calls) == n
ok("refresh caches per account and respects the poll interval")

res.clear(); res["error"] = "re-login needed"
u.refresh(now=1000.0 + u.POLL + 1)
snap = u.snapshot()
assert snap["claude"]["error"] == "re-login needed" and snap["claude"]["five_hour"]["pct"] == 10
ok("a failed fetch keeps the last good numbers and flags the error")
print("passed")
