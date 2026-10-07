"""ntfy push notifications for UI sessions (issue #121). Stdlib only.

Config: <data_dir>/ui.json (must be mode 0600, it can hold a token) with
{"ntfy": {"server", "topic", "token"}, "public_url"}; AIW_NTFY_SERVER/TOPIC/TOKEN
override the file. notify() never raises and never logs the token.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import quote, urlparse

from shared import data_dir, warn

TIMEOUT_SECONDS = 5

_TITLES = {"waiting": "aiw: waiting on you", "done": "aiw: run done", "failed": "aiw: session failed"}


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
    for key in ("server", "topic", "token"):
        val = os.environ.get(f"AIW_NTFY_{key.upper()}")
        if val:
            ntfy[key] = val
    return cfg


def click_url(event: str, rec: dict, public_url) -> str | None:
    if not public_url:
        return None
    base = str(public_url).rstrip("/")
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


def notify(event: str, rec: dict) -> None:
    try:
        cfg = load_config()
        ntfy = cfg["ntfy"]
        server, topic, token = ntfy.get("server"), ntfy.get("topic"), ntfy.get("token")
        if not server or not topic:
            return
        if urlparse(str(server)).scheme not in ("http", "https"):
            warn("ntfy server must be an http(s) URL; push skipped")
            return
        headers = {"Title": _TITLES.get(event, "aiw: update"),
                   "Priority": "default" if event == "done" else "high"}
        click = click_url(event, rec, cfg.get("public_url"))
        if click:
            headers["Click"] = click
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = f"{rec.get('command', '')}\n{rec.get('repo', '')}".encode("utf-8")
        req = urllib.request.Request(str(server).rstrip("/") + "/" + quote(str(topic), safe=""),
                                     data=body, headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS).close()
    except urllib.error.HTTPError as e:
        warn(f"ntfy push failed ({event} {rec.get('id')}): HTTP {e.code}")
    except Exception as e:  # never let a push failure break the session
        warn(f"ntfy push failed ({event} {rec.get('id')}): {type(e).__name__}")
