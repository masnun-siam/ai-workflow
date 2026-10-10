"""5h / 7d plan-usage per connected account, for the UI header.

Reads each account's OAuth access token from the macOS Keychain (server-side only, never sent to the browser)
and asks Anthropic's usage endpoint. The token is never refreshed here — that would rotate the refresh token
under the CLI; an expired one reports "re-login needed" until the CLI next runs under that account."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
import urllib.request

import ui_settings
from shared import warn

URL = "https://api.anthropic.com/api/oauth/usage"
POLL = 300.0  # seconds between refreshes of one account
RETRY = 900.0  # after a failure
ACTIVE = 120.0  # only poll while a UI client asked within this window

_cache: dict = {}  # cmd -> {"five_hour", "seven_day", "at", "error"}
_next: dict = {}  # cmd -> earliest next fetch
_last_seen = 0.0
_lock = threading.Lock()


def service(cmd: str) -> str:
    """Keychain service holding this account's credentials: Claude Code suffixes it with a hash of a non-default config dir."""
    d = ui_settings.config_dir(cmd)
    if d == os.path.expanduser("~/.claude"):
        return "Claude Code-credentials"
    return "Claude Code-credentials-" + hashlib.sha256(d.encode()).hexdigest()[:8]


def _window(w) -> dict | None:
    if not isinstance(w, dict) or not isinstance(w.get("utilization"), (int, float)):
        return None
    return {"pct": w["utilization"], "resets_at": w.get("resets_at")}


def fetch(cmd: str, now: float | None = None) -> dict:
    """{five_hour, seven_day} or {"error": str}. Never raises."""
    now = now or time.time()
    try:
        p = subprocess.run(["security", "find-generic-password", "-s", service(cmd), "-w"],
                           capture_output=True, text=True, timeout=15)
        if p.returncode:
            return {"error": "usage unavailable (keychain read denied or no login)"}
        oauth = json.loads(p.stdout)["claudeAiOauth"]
        if (oauth.get("expiresAt") or 0) / 1000 < now:
            return {"error": "re-login needed"}
        req = urllib.request.Request(URL, headers={"Authorization": "Bearer " + oauth["accessToken"],
                                                   "anthropic-beta": "oauth-2025-04-20"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as e:
        warn(f"ui_usage: {cmd}: {type(e).__name__}")  # never the token or the response
        return {"error": "usage unavailable"}
    return {"five_hour": _window(data.get("five_hour")), "seven_day": _window(data.get("seven_day"))}


def refresh(now: float | None = None) -> None:
    now = now or time.time()
    for c in ui_settings.load()["commands"]:
        cmd = c["cmd"]
        if _next.get(cmd, 0) > now:
            continue
        res = fetch(cmd, now)
        with _lock:
            old = _cache.get(cmd, {})
            if "error" in res:  # keep the last good numbers, flagged stale by `error`
                _cache[cmd] = {**old, "error": res["error"], "at": old.get("at")}
                _next[cmd] = now + RETRY
            else:
                _cache[cmd] = {**res, "at": now, "error": None}
                _next[cmd] = now + POLL


def snapshot(now: float | None = None) -> dict:
    """Latest per-account usage; also marks a UI client as present so the poller runs."""
    global _last_seen
    _last_seen = now or time.time()
    with _lock:
        return {cmd: dict(v) for cmd, v in _cache.items()}


def start_timer(interval: float = 5.0) -> threading.Thread:
    def loop():
        while True:
            if time.time() - _last_seen < ACTIVE:
                try:
                    refresh()
                except Exception as exc:  # the header chip must never take the server down
                    warn(f"ui_usage tick failed: {exc}")
            time.sleep(interval)
    t = threading.Thread(target=loop, name="ui-usage", daemon=True)
    t.start()
    return t
