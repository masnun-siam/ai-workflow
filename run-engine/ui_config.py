"""Settings for what used to be file-only: ntfy notifications (`<data_dir>/ui.json`), the peer-review
policy (overrides in `<data_dir>/config.json`, laid over the shipped `run-engine/config.json` by
`shared.load_config`), and the repo registry (remove one, check every GitHub remote).

Secrets never leave the server: `notify_public` says whether a token or password is set, not what it
is, and a save keeps the stored one unless a new value (or `""` to clear it) is sent. ui.json is
written mode 0600, which `ui_notify.load_config` requires.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import dispatch
import ui_notify
from shared import data_dir, gh_json, load_config, read_json, write_json, GLOBAL_CONFIG

_SECRETS = ("token", "password")
MAX_PROMPT = 8000
_ui_lock = threading.Lock()  # one read-modify-write of ui.json at a time (readers take no lock)


def _ui_path() -> str:
    return os.path.join(data_dir(), "ui.json")


def _read_ui() -> dict:
    try:
        with open(_ui_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def notify_public() -> dict:
    cfg = _read_ui()
    ntfy = cfg.get("ntfy") if isinstance(cfg.get("ntfy"), dict) else {}
    n = ui_notify.load_config()["ntfy"]  # environment overrides count
    available = sys.platform == "darwin"
    notifier = available and shutil.which("terminal-notifier") is not None
    return {
        "matrix": ui_notify.matrix(cfg),
        "events": [{"key": k, "label": label, "group": g} for k, label, g in ui_notify.EVENTS],
        "ntfy_ready": bool(n.get("server") and n.get("topic")),
        "mac": {"available": available, "notifier": notifier, "clickable": notifier and bool(cfg.get("public_url"))},
        "server": ntfy.get("server") or "",
        "topic": ntfy.get("topic") or "",
        "user": ntfy.get("user") or "",
        "public_url": cfg.get("public_url") or "",
        "token_set": bool(ntfy.get("token")),
        "password_set": bool(ntfy.get("password")),
        "env": [k for k in ("server", "topic", "token", "user", "password") if os.environ.get(f"AIW_NTFY_{k.upper()}")],
    }


def _write_ui(cfg: dict) -> None:
    path = _ui_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(path + ".tmp", 0o600)
    os.replace(path + ".tmp", path)


def save_notify(body: dict) -> dict:
    with _ui_lock:
        _save_notify(body)
    return notify_public()


def save_channel(body: dict) -> dict:
    """{event, channel, on} -> that one matrix cell; unknown or non-boolean stored cells are dropped."""
    event, channel, on = body.get("event"), body.get("channel"), body.get("on")
    if event not in {k for k, _, _ in ui_notify.EVENTS}:
        raise ValueError("unknown event")
    if channel not in ui_notify.CHANNELS:
        raise ValueError("unknown channel")
    if type(on) is not bool:
        raise ValueError("on must be true or false")
    with _ui_lock:
        cfg = _read_ui()
        cfg["channels"] = ui_notify.stored_cells(cfg)
        cfg["channels"].setdefault(event, {})[channel] = on
        _write_ui(cfg)
    return notify_public()


def _save_notify(body: dict) -> None:
    cfg = _read_ui()
    ntfy = dict(cfg.get("ntfy") or {})
    for key in ("server", "topic", "user", *_SECRETS):
        if key not in body or (key in _SECRETS and body[key] is None):
            continue  # a secret not sent is kept
        val = body[key]
        if not isinstance(val, str) or len(val) > 500 or "\n" in val:
            raise ValueError(f"{key} must be one line of text")
        if val.strip():
            ntfy[key] = val.strip()
        else:
            ntfy.pop(key, None)
    for key in ("server",):
        if ntfy.get(key) and not ntfy[key].startswith(("https://", "http://")):
            raise ValueError("server must be an http(s) URL")
    if "public_url" in body:
        url = body["public_url"]
        if not isinstance(url, str) or (url.strip() and not url.strip().startswith(("https://", "http://"))):
            raise ValueError("public URL must be an http(s) URL")
        if url.strip():
            cfg["public_url"] = url.strip()
        else:
            cfg.pop("public_url", None)
    cfg["ntfy"] = ntfy
    _write_ui(cfg)


def _override_path() -> str:
    return os.path.join(data_dir(), "config.json")


def review_public() -> dict:
    pr = load_config()["peer_review"]
    shipped = read_json(GLOBAL_CONFIG)["peer_review"]
    return {
        "max_rounds": pr["max_rounds"],
        "default_lenses": list(pr["default_lenses"]),
        "lenses": {k: v["prompt"] for k, v in (pr.get("lenses") or {}).items()},  # only the prompt is editable
        "shipped": {
            "max_rounds": shipped["max_rounds"],
            "default_lenses": shipped["default_lenses"],
            "lenses": {k: v["prompt"] for k, v in (shipped.get("lenses") or {}).items()},
        },
        "overridden": os.path.isfile(_override_path()),
    }


def save_review(body: dict) -> dict:
    """{max_rounds, default_lenses, lenses: {name: prompt}} -> the override file; {"reset": true} removes it."""
    if body.get("reset") is True:
        try:
            os.remove(_override_path())
        except FileNotFoundError:
            pass
        return review_public()
    known = read_json(GLOBAL_CONFIG)["peer_review"].get("lenses") or {}
    rounds = body.get("max_rounds")
    if not isinstance(rounds, int) or isinstance(rounds, bool) or not 1 <= rounds <= 10:
        raise ValueError("max rounds must be a whole number from 1 to 10")
    lenses = body.get("lenses") or {}
    if not isinstance(lenses, dict) or any(k not in known for k in lenses):
        raise ValueError(f"lenses must be some of {', '.join(known)}")
    for k, v in lenses.items():
        if not isinstance(v, str) or not v.strip() or len(v) > MAX_PROMPT:
            raise ValueError(f"the {k} prompt must be 1 to {MAX_PROMPT} characters")
    default = body.get("default_lenses")
    if not isinstance(default, list) or not default or any(x not in known for x in default):
        raise ValueError("pick at least one default lens")
    over = {"max_rounds": rounds, "default_lenses": list(dict.fromkeys(default))}
    changed = {k: {"prompt": v} for k, v in lenses.items() if v != known[k]["prompt"]}  # only what differs
    if changed:
        over["lenses"] = changed
    write_json(_override_path(), {"peer_review": over})
    return review_public()


def remove_repo(slug) -> dict:
    if not isinstance(slug, str) or not dispatch.remove_checkout(slug):
        raise ValueError(f"{slug!r} is not registered")
    return {"ok": True}


def check_repos(runner=gh_json) -> dict:
    """{slug: None | problem} for every registered repo: one `gh repo view` each, 8 at a time."""
    slugs = list(dispatch.read_checkouts())

    def one(slug):
        if slug.startswith("local/"):
            return slug, "no GitHub remote"
        out, proc = runner(["repo", "view", slug, "--json", "nameWithOwner"], timeout=20)
        if out is None:
            msg = (proc.stderr or proc.stdout or "gh failed").strip().splitlines()
            return slug, (msg[-1] if msg else "gh failed")[:200]
        return slug, None

    with ThreadPoolExecutor(8) as pool:
        return dict(pool.map(one, slugs))
