"""ntfy push notifications for UI sessions (issue #121). Stdlib only.

Config: <data_dir>/ui.json (must be mode 0600, it can hold a token or password) with
{"ntfy": {"server", "topic", "token" | "user", "password"}, "public_url"};
AIW_NTFY_SERVER/TOPIC/TOKEN/USER/PASSWORD override the file. A token (Bearer) wins over
user+password (Basic). notify() never raises and never logs a credential.
"""

from __future__ import annotations

import base64
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlparse

import repo_skills
import ui_feed
from shared import data_dir, warn

TIMEOUT_SECONDS = 5

# event -> (ntfy emoji shortcode shown as the icon, title with/without an issue number, action label).
# Titles stay ASCII: they travel as an HTTP header.
_LOOK = {
    "waiting": ("speech_balloon", "aiw: #{n} waiting on you", "aiw: waiting on you", "Answer"),
    "done": ("white_check_mark", "aiw: #{n} is done", "aiw: run done", "Open run"),
    "failed": ("x", "aiw: #{n} failed", "aiw: session failed", "Open run"),
    "grind-paused": ("pause_button", "aiw: #{n} grind paused", "aiw: grind paused", "Open run"),
    "grind-done": ("mag", "aiw: #{n} grind finished", "aiw: grind finished", "Open run"),
    "pipeline": ("checkered_flag", "aiw: pipeline finished", "aiw: pipeline finished", "Open pipeline"),
    "afk": ("robot", "aiw: away mode ended", "aiw: away mode ended", "Open Inbox"),
    "pr-ready": ("eyes", "aiw: #{n} PR is ready", "aiw: PR is ready", "Open Inbox"),
    "needs-cleanup": ("broom", "aiw: #{n} needs cleanup", "aiw: needs cleanup", "Open Inbox"),
    "panel-cap": ("no_entry", "aiw: review panel hit its cap", "aiw: review panel hit its cap", "Open Inbox"),
    "prd-comment": ("speech_balloon", "aiw: new PRD comments", "aiw: new PRD comments", "Open Inbox"),
    "dispatch": ("rocket", "aiw: #{n} in a dispatch needs you", "aiw: a dispatch needs you", "Open Inbox"),
}
# The matrix rows in display order: (event, label, group).
EVENTS = (
    ("waiting", "A session is waiting on you", "Needs you"),
    ("failed", "A session failed", "Needs you"),
    ("dispatch", "A dispatch needs you", "Needs you"),
    ("panel-cap", "Review panel hit its cap", "Needs you"),
    ("prd-comment", "Reviewers commented on a PRD", "Needs you"),
    ("pr-ready", "PR is ready for review", "Pull requests"),
    ("needs-cleanup", "Merged issue needs cleanup", "Pull requests"),
    ("grind-paused", "Grind paused", "Pull requests"),
    ("grind-done", "Grind finished", "Pull requests"),
    ("done", "A session is done", "Finished"),
    ("pipeline", "Pipeline finished", "Finished"),
    ("afk", "Away mode ended", "Finished"),
)
CHANNELS = ("browser", "ntfy", "mac")


def default_cell(event: str, channel: str) -> bool:
    if event == "prd-comment":  # per-event exception: the browser only, the push is throttled and terse
        return channel == "browser"
    if channel == "ntfy":
        return True
    return next(g for k, _, g in EVENTS if k == event) != "Finished" and event != "grind-done"


def stored_cells(cfg: dict) -> dict:
    """The known event/channel cells of cfg["channels"] that hold a boolean; anything else is ignored."""
    raw = cfg.get("channels") if isinstance(cfg.get("channels"), dict) else {}
    out = {}
    for event, _, _ in EVENTS:
        row = raw.get(event) if isinstance(raw.get(event), dict) else {}
        cells = {ch: row[ch] for ch in CHANNELS if isinstance(row.get(ch), bool)}
        if cells:
            out[event] = cells
    return out


def matrix(cfg: dict) -> dict:
    """{event: {channel: bool}} for every event: the defaults, overlaid with the stored cells."""
    stored = stored_cells(cfg)
    return {e: {ch: stored.get(e, {}).get(ch, default_cell(e, ch)) for ch in CHANNELS} for e, _, _ in EVENTS}


_BOARD = (
    "afk",
    "pr-ready",
    "needs-cleanup",
    "panel-cap",
    "dispatch",
    "prd-comment",
)  # no session page: the click lands on the Inbox
# While away mode runs, it handles or holds these; the one "afk" push at the end sums them up.
_AFK_MUTED = ("waiting", "failed", "grind-paused")
_TAG_SAFE = re.compile(r"[^A-Za-z0-9._#/-]+")


def _tag(text) -> str:
    return _TAG_SAFE.sub("", str(text or ""))[:40]


def _first_line(text, limit=200) -> str:
    line = next((ln.strip() for ln in str(text or "").splitlines() if ln.strip()), "")
    return line if len(line) <= limit else line[: limit - 1] + "…"


def compose(event: str, rec: dict, public_url=None) -> tuple[dict, str]:
    """(headers, body) for one push: an emoji icon + issue/repo tags, a title naming the
    issue, a body that leads with the question or error, and an action button when a
    public URL is set. Pure; notify() adds auth and sends it."""
    icon, with_n, without_n, action = _LOOK.get(event, ("bell", "aiw: update", "aiw: update", "Open"))
    link = rec.get("link") if isinstance(rec.get("link"), dict) else {}
    issue = link.get("issue") if isinstance(link.get("issue"), int) else None
    family = (repo_skills.parse(rec.get("command")) or ("",))[0]
    tags = [icon] + [
        t
        for t in (_tag(family), _tag(str(rec.get("repo") or "").rsplit("/", 1)[-1]), f"#{issue}" if issue else "")
        if t
    ]
    headers = {
        "Title": (with_n.replace("{n}", str(issue)) if issue else without_n),
        "Priority": "default" if event in ("done", "pipeline", "grind-done", "afk") else "high",
        "Tags": ",".join(tags),
    }
    lines = []
    if event == "waiting":
        q = next(iter((rec.get("pending_question") or {}).get("questions") or []), None) or {}
        lines.append(_first_line(q.get("question") or q.get("header")))
        if q.get("recommended"):
            lines.append(f"Suggested: {_first_line(q['recommended'], 80)}")
    elif event == "failed":
        lines.append(_first_line(rec.get("error")))
    elif event.startswith("grind-") or event in _BOARD:
        lines.append(_first_line(rec.get("note")))
    lines.append(f"{rec.get('repo', '')} · {_first_line(rec.get('command'), 120)}".strip(" ·"))
    click = click_url(event, rec, public_url)
    if click:
        headers["Click"] = click
        if click.isascii():
            headers["Actions"] = f"view, {action}, {click}"
    return headers, "\n".join(ln for ln in lines if ln)


def load_config() -> dict:
    path = os.path.join(data_dir(), "ui.json")
    cfg: dict = {}
    try:
        mode = os.stat(path).st_mode & 0o777
    except FileNotFoundError:
        mode = None
    if mode is not None:
        if mode & 0o077:
            warn(f"ignoring {path}: mode {oct(mode)} is looser than 0600; run chmod 600 {path}")
        else:
            try:
                with open(path, encoding="utf-8") as f:
                    raw = f.read()
                if raw.strip():
                    cfg = json.loads(raw)
                    if not isinstance(cfg, dict):
                        warn(f"ignoring {path}: expected a JSON object")
                        cfg = {}
            except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
                warn(f"ignoring {path}: unreadable ({type(e).__name__})")
                cfg = {}
    ntfy = cfg.get("ntfy")
    cfg["ntfy"] = ntfy = dict(ntfy) if isinstance(ntfy, dict) else {}
    for key in ("server", "topic", "token", "user", "password"):
        val = os.environ.get(f"AIW_NTFY_{key.upper()}")
        if val:
            ntfy[key] = val
    return cfg


def click_path(event: str, rec: dict) -> str:
    if (
        event == "pipeline" or event not in _BOARD and rec.get("id")
    ):  # a session: pipeline, waiting, done, failed, grind
        return f"#/sessions/{quote(str(rec['id']), safe='')}"
    return "#/inbox" if event in _BOARD else "#/activity"


def click_url(event: str, rec: dict, public_url) -> str | None:
    if not public_url:
        return None
    return f"{str(public_url).rstrip('/')}/{click_path(event, rec)}"


def dedupe_key(event, rec: dict):
    if event == "waiting":
        q = rec.get("pending_question")
        return f"waiting:{q['id']}" if isinstance(q, dict) and q.get("id") else "waiting"
    return event if event in ("done", "failed") else None


# A grind round ends its session every time; the loop's own grind-done/grind-paused push is the signal.
_QUIET_DONE_PREFIX = "Start the review grind for PR "  # keep in step with ui_runner.GRIND_PREFIX


def send_ntfy(cfg: dict, headers: dict, text: str, event: str, rec: dict) -> str | None:
    """POST one push to ntfy. None on success, else a short error."""
    ntfy = cfg["ntfy"]
    server, topic, token = ntfy.get("server"), ntfy.get("topic"), ntfy.get("token")
    if not server or not topic:
        return "ntfy is not set up"
    if urlparse(str(server)).scheme not in ("http", "https"):
        warn("ntfy server must be an http(s) URL; push skipped")
        return "ntfy server must be an http(s) URL"
    # Cloudflare's Browser Integrity Check rejects urllib's default User-Agent (error 1010).
    headers = {**headers, "User-Agent": "aiw-ui (ntfy publisher)"}
    user, password = ntfy.get("user"), ntfy.get("password")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif user and password:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        str(server).rstrip("/") + "/" + quote(str(topic), safe=""),
        data=text.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS).close()
    except urllib.error.HTTPError as e:
        warn(f"ntfy push failed ({event} {rec.get('id')}): HTTP {e.code}")
        return f"HTTP {e.code}"
    except Exception as e:  # never let a push failure break the session
        warn(f"ntfy push failed ({event} {rec.get('id')}): {type(e).__name__}")
        return type(e).__name__
    return None


def _never_raise(label: str, fn, *args) -> None:
    try:
        fn(*args)
    except Exception as e:
        warn(f"{label} notification failed: {type(e).__name__}")


_PRD_COMMENT_GAP = 60.0
_prd_last: dict = {}  # ponytail: one float per share id for the life of the process; it never needs pruning at this size
_prd_lock = threading.Lock()


def prd_comment(share_id: str, summary: str, now=None) -> bool:
    """Raise `prd-comment` at most once per share per minute; the push body is exactly `summary`."""
    t = time.monotonic() if now is None else now
    with _prd_lock:
        if share_id in _prd_last and t - _prd_last[share_id] < _PRD_COMMENT_GAP:
            return False
        _prd_last[share_id] = t
    notify("prd-comment", {"note": summary})
    return True


def notify(event: str, rec: dict) -> None:
    """Route one event to every channel its matrix cell turns on; each channel is independent."""
    if rec.get("role") == "away-answerer":  # literal: ui_sessions imports this module
        return
    cmd = rec.get("command")
    if event == "done" and (repo_skills.is_skill(cmd, "pr-grind") or str(cmd or "").startswith(_QUIET_DONE_PREFIX)):
        return
    if event in _AFK_MUTED:
        import ui_afk  # lazy: ui_afk imports the session store, which imports this module

        if ui_afk.active():
            return
    try:
        cfg = load_config()
        cells = matrix(cfg).get(event, {"browser": False, "ntfy": True, "mac": False})  # unknown event: ntfy only
        headers, text = compose(event, rec, cfg.get("public_url"))
        if cells["browser"]:
            _never_raise("browser", ui_feed.add, event, headers["Title"], text, click_path(event, rec))
        sends = []
        if cells["ntfy"]:
            sends.append(("ntfy", send_ntfy, cfg, headers, text, event, rec))
        if cells["mac"]:
            sends.append(("mac", send_mac, headers["Title"], text, headers.get("Click")))
        threads = [threading.Thread(target=_never_raise, args=a, daemon=True) for a in sends]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    except Exception as e:  # never let a notification failure break the session
        warn(f"notification failed ({event} {rec.get('id')}): {type(e).__name__}")


@functools.cache
def _notifier() -> str | None:
    return shutil.which("terminal-notifier")  # the server's PATH only, cached for the process


def send_mac(title: str, body: str, link: str | None = None, run=subprocess.run) -> str | None:
    """macOS banner: terminal-notifier (clickable when `link`) else AppleScript. None on success, else a short error.
    Env `AIW_NO_MAC_BANNER` (non-empty) turns it off, read on every call (the test runner sets it)."""
    if sys.platform != "darwin":
        return "Only on macOS"
    if os.environ.get("AIW_NO_MAC_BANNER"):
        return "Turned off by AIW_NO_MAC_BANNER"
    title, body = title[:80], (body or title)[:200]
    tn = _notifier()
    if tn:
        argv = [tn, "-title", title, "-message", body, *(["-open", link] if link else [])]
    else:  # argv, never the script text: nothing in `body` can run as AppleScript
        script = [
            "-e",
            "on run argv",
            "-e",
            "display notification (item 1 of argv) with title (item 2 of argv)",
            "-e",
            "end run",
        ]
        argv = ["osascript", *script, body, title]
    try:
        r = run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as e:
        warn(f"macOS notification failed: {type(e).__name__}")
        return type(e).__name__
    return f"exit {r.returncode}" if r.returncode else None


def send_test(channel) -> dict:
    """One sample push on `channel` alone, ignoring the matrix and Away mode. The error is a status,
    a fixed phrase or an exception class name, never the URL (it holds the topic)."""
    if channel not in ("ntfy", "mac"):
        raise ValueError("channel must be ntfy or mac")
    cfg = load_config()
    title, body = "aiw: test notification", "This is a test from aiw ui."
    public_url = cfg.get("public_url")
    link = f"{str(public_url).rstrip('/')}/#/settings/notifications" if public_url else None
    if channel == "mac":
        err = send_mac(title, body, link)
    else:
        headers = {"Title": title, "Priority": "default", "Tags": "bell", **({"Click": link} if link else {})}
        err = send_ntfy(cfg, headers, body, "test", {})
    return {"ok": err is None, **({"error": err} if err else {})}
