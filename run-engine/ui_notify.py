"""ntfy push notifications for UI sessions (issue #121). Stdlib only.

Config: <data_dir>/ui.json (must be mode 0600, it can hold a token or password) with
{"ntfy": {"server", "topic", "token" | "user", "password"}, "public_url"};
AIW_NTFY_SERVER/TOPIC/TOKEN/USER/PASSWORD override the file. A token (Bearer) wins over
user+password (Basic). notify() never raises and never logs a credential.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import quote, urlparse

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
    "afk": ("robot", "aiw: autopilot ended", "aiw: autopilot ended", "Open board"),
}
# While AFK mode runs, autopilot handles or holds these; the one "afk" push at the end sums them up.
_AFK_MUTED = ("waiting", "failed", "grind-paused")
_TAG_SAFE = re.compile(r"[^A-Za-z0-9._#/-]+")


def _tag(text) -> str:
    return _TAG_SAFE.sub("", str(text or ""))[:40]


def _first_line(text, limit=200) -> str:
    line = next((l.strip() for l in str(text or "").splitlines() if l.strip()), "")
    return line if len(line) <= limit else line[: limit - 1] + "…"


def compose(event: str, rec: dict, public_url=None) -> tuple[dict, str]:
    """(headers, body) for one push: an emoji icon + issue/repo tags, a title naming the
    issue, a body that leads with the question or error, and an action button when a
    public URL is set. Pure; notify() adds auth and sends it."""
    icon, with_n, without_n, action = _LOOK.get(event, ("bell", "aiw: update", "aiw: update", "Open"))
    link = rec.get("link") if isinstance(rec.get("link"), dict) else {}
    issue = link.get("issue") if isinstance(link.get("issue"), int) else None
    family = (str(rec.get("command") or "").lstrip("/").split(None, 1) or [""])[0].split(":")[-1]
    tags = [icon] + [t for t in (_tag(family), _tag(str(rec.get("repo") or "").rsplit("/", 1)[-1]),
                                 f"#{issue}" if issue else "") if t]
    headers = {"Title": (with_n.replace("{n}", str(issue)) if issue else without_n),
               "Priority": "default" if event in ("done", "pipeline", "grind-done", "afk") else "high",
               "Tags": ",".join(tags)}
    lines = []
    if event == "waiting":
        q = next(iter((rec.get("pending_question") or {}).get("questions") or []), None) or {}
        lines.append(_first_line(q.get("question") or q.get("header")))
        if q.get("recommended"):
            lines.append(f"Suggested: {_first_line(q['recommended'], 80)}")
    elif event == "failed":
        lines.append(_first_line(rec.get("error")))
    elif event.startswith("grind-") or event == "afk":
        lines.append(_first_line(rec.get("note")))
    lines.append(f"{rec.get('repo', '')} · {_first_line(rec.get('command'), 120)}".strip(" ·"))
    click = click_url(event, rec, public_url)
    if click:
        headers["Click"] = click
        if click.isascii():
            headers["Actions"] = f"view, {action}, {click}"
    return headers, "\n".join(l for l in lines if l)


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


def click_url(event: str, rec: dict, public_url) -> str | None:
    if not public_url:
        return None
    base = str(public_url).rstrip("/")
    if event == "pipeline":
        return f"{base}/#/dispatch/{quote(str(rec['id']), safe='')}"
    if event == "afk":
        return f"{base}/#/"
    if event == "waiting":
        return f"{base}/#/answer/{quote(str(rec['id']), safe='')}"
    link = rec.get("link")
    if isinstance(link, dict) and all(link.get(k) for k in ("owner", "repo", "issue")):
        return (f"{base}/#/run/{quote(str(link['owner']), safe='')}/"
                f"{quote(str(link['repo']), safe='')}/{quote(str(link['issue']), safe='')}")
    return f"{base}/#/sessions"


def dedupe_key(event, rec: dict):
    if event == "waiting":
        q = rec.get("pending_question")
        return f"waiting:{q['id']}" if isinstance(q, dict) and q.get("id") else "waiting"
    return event if event in ("done", "failed") else None


# A grind round ends its session every time; the loop's own grind-done/grind-paused push is the signal.
_QUIET_DONE = ("/pr-grind ", "Start the review grind for PR ")  # keep in step with ui_runner.GRIND_PREFIX


def notify(event: str, rec: dict) -> None:
    if event == "done" and str(rec.get("command", "")).startswith(_QUIET_DONE):
        return
    if event in _AFK_MUTED:
        import ui_afk  # lazy: ui_afk imports the session store, which imports this module
        if ui_afk.active():
            return
    try:
        cfg = load_config()
        ntfy = cfg["ntfy"]
        server, topic, token = ntfy.get("server"), ntfy.get("topic"), ntfy.get("token")
        if not server or not topic:
            return
        if urlparse(str(server)).scheme not in ("http", "https"):
            warn("ntfy server must be an http(s) URL; push skipped")
            return
        headers, text = compose(event, rec, cfg.get("public_url"))
        # Cloudflare's Browser Integrity Check rejects urllib's default User-Agent (error 1010).
        headers["User-Agent"] = "aiw-ui (ntfy publisher)"
        user, password = ntfy.get("user"), ntfy.get("password")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif user and password:
            headers["Authorization"] = "Basic " + base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        body = text.encode("utf-8")
        req = urllib.request.Request(str(server).rstrip("/") + "/" + quote(str(topic), safe=""),
                                     data=body, headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS).close()
    except urllib.error.HTTPError as e:
        warn(f"ntfy push failed ({event} {rec.get('id')}): HTTP {e.code}")
    except Exception as e:  # never let a push failure break the session
        warn(f"ntfy push failed ({event} {rec.get('id')}): {type(e).__name__}")
