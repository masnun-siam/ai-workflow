"""The one place that runs the `jev` CLI (typed yes/no, choice and score questions). Stdlib only.

ask(point, kind, question, text, ...) -> {"status": "ok", ...answer} or {"status": <why not>}.
Statuses: ok, off (Settings -> Use jev is off), missing (not on PATH), no_answer (timeout or exec error),
failed (non-zero exit, with "exit"), unreadable (bad JSON or field). A failure never raises, and the
`jev` binary never runs while the switch is off. Text is redacted, then cut to MAX_CHARS, before it is sent.

peek(...) reads the cache only (None on a miss or when jev is off or missing).

The CACHED points (urgency, readiness, duplicate) are answered, in the server only (start_timer), from a cache of ok answers (memory, flushed to
jev_cache.json by the server's timer; 2000 entries, 7 days) and capped at CEILING calls an hour: past it they
return {"status": "capped"}. Every other point (risk, route, hints) is never cached, counted or refused.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time

import shared
import ui_settings

MODEL = "jev-1.14.0"  # pinned: an alias such as jev-latest moves without notice
TIMEOUT_S = 8
MAX_CHARS = 4000
CACHED = ("urgency", "readiness", "duplicate")
MAX_ENTRIES = 2000
MAX_AGE_S = 7 * 86400
CEILING = 500
WINDOW_S = 3600
FLUSH_S = 60

_now = time.time  # tests set this to drive the clock
_lock = threading.Lock()  # guards the cache, the dirty flag and the window; never held while jev runs
_cache: dict | None = None
_dirty = False
_server = False  # set by start_timer(): only the server reads or writes the cache
_window_start = 0.0
_window_calls = 0

_REDACTED = "[redacted]"
_PREFIX = re.compile(r"\b(?:ghp_|gho_|ghu_|ghs_|ghr_|github_pat_|glpat-|sk-|xox[abprs]-|AIza|npm_)[A-Za-z0-9_-]{16,}")
_AWS = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}")
_AUTH = re.compile(r"(\bauthorization\s*:[ \t]*)[^\n]*", re.I)
_BEARER = re.compile(r"(\bbearer\s+)\S+", re.I)
_ASSIGN = re.compile(r"(\b[\w.-]*(?:key|token|secret)[\w.-]*\s*[=:]\s*)[^\s]+", re.I)
_HEX = re.compile(r"[0-9a-fA-F]{32,}")
_B64 = re.compile(r"[A-Za-z0-9+/_-]{40,}={0,2}")


def status() -> str:
    """off, missing or ok. Never runs jev."""
    if not ui_settings.use_jev():
        return "off"
    return "ok" if shutil.which("jev") else "missing"


def redact(text: str) -> str:
    for rx in (_PREFIX, _AWS, _HEX, _B64):
        text = rx.sub(_REDACTED, text)
    for rx in (_AUTH, _BEARER, _ASSIGN):
        text = rx.sub(lambda m: m.group(1) + _REDACTED, text)
    return text


def _fail(point: str, status_: str, **extra) -> dict:
    shared.warn(f"jev {point}: {status_}")
    return {"status": status_, **extra}


def _path() -> str:
    return os.path.join(shared.data_dir(), "jev_cache.json")


def _load() -> dict:
    """The cache, loaded on first use. Call with _lock held. A missing or corrupt file is an empty cache."""
    global _cache
    if _cache is None:
        try:
            with open(_path()) as f:
                data = json.load(f)
            _cache = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _fresh(entry: dict) -> bool:
    return _now() - entry["at"] < MAX_AGE_S


def spent() -> int:
    """Counted calls in the current hour."""
    with _lock:
        return _window_calls if _now() - _window_start < WINDOW_S else 0


def flush() -> None:
    """Write the cache if it changed, dropping expired entries. A failed write stays dirty."""
    global _dirty
    with _lock:
        if not _dirty or _cache is None:
            return
        for k in [k for k, e in _cache.items() if not _fresh(e)]:
            del _cache[k]
        try:
            shared.atomic_write_text(_path(), json.dumps(_cache))
        except OSError:
            shared.warn("jev cache: flush failed")
            return
        _dirty = False


def start_timer(interval: float = FLUSH_S) -> threading.Thread:
    global _server
    _server = True

    def loop():
        while True:
            time.sleep(interval)
            try:
                flush()
            except Exception as e:  # noqa: BLE001 - keep the timer alive
                shared.warn(f"jev cache flush: {type(e).__name__}: {e}")

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t


def _sent_key(point, kind, question, text, options, levels) -> tuple[str, str]:
    """The redacted, cut text that is sent, and its cache key. Shared by ask and peek so they never disagree."""
    sent = redact(text)[:MAX_CHARS]
    digest = hashlib.sha256(json.dumps([kind, question, options, levels, sent], sort_keys=True).encode())
    return sent, f"{point}:{digest.hexdigest()}"


def peek(
    point: str, kind: str, question: str, text: str, *, options: dict | None = None, levels: list | None = None
) -> dict | None:
    """The cached ok answer for a call, or None. Never runs jev, never counts against the ceiling, never writes."""
    if status() != "ok":
        return None
    key = _sent_key(point, kind, question, text, options, levels)[1]
    with _lock:
        hit = _load().get(key)
        return {"status": "ok", **hit["answer"]} if hit and _fresh(hit) else None


def ask(
    point: str, kind: str, question: str, text: str, *, options: dict | None = None, levels: list | None = None
) -> dict:
    global _window_start, _window_calls, _dirty
    s = status()
    if s != "ok":
        return {"status": s}
    sent, key = _sent_key(point, kind, question, text, options, levels)
    if point not in CACHED:
        return _run(point, kind, question, sent, options, levels)
    with _lock:
        hit = _load().get(key) if _server else None
        if hit and _fresh(hit):
            return {"status": "ok", **hit["answer"]}
        now = _now()
        if now - _window_start >= WINDOW_S:
            _window_start, _window_calls = now, 0
        if _window_calls >= CEILING:
            return {"status": "capped"}
        _window_calls += 1  # a failed call spent an invocation too
    r = _run(point, kind, question, sent, options, levels)
    if r["status"] == "ok" and _server:
        answer = {k: v for k, v in r.items() if k != "status"}
        with _lock:
            cache = _load()
            cache[key] = {"answer": answer, "probability": r.get("p", r.get("confidence")), "at": _now()}
            while len(cache) > MAX_ENTRIES:
                del cache[min(cache, key=lambda k: cache[k]["at"])]
            _dirty = True
    return r


def _run(point: str, kind: str, question: str, sent: str, options: dict | None, levels: list | None) -> dict:
    cmd = [shutil.which("jev"), kind, question, "--model", MODEL, "--state-file", "-", "-o", "json"]
    for k, v in (options or {}).items():
        cmd += ["--option", f"{k}={v}"]
    for level in levels or []:
        cmd += ["--level", level]
    try:
        p = subprocess.run(cmd, input=sent, capture_output=True, text=True, timeout=TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return _fail(point, "no_answer")
    if p.returncode != 0:
        return _fail(point, "failed", exit=p.returncode)
    try:
        out = json.loads(p.stdout)
        if kind == "noul":
            return {"status": "ok", "p": float(out["noul"])}
        if kind == "choice":
            choice = out["choice"]
            return {
                "status": "ok",
                "choice": choice,
                "p": float(out.get("probabilities", {}).get(choice, out.get("confidence", 0))),
            }
        return {"status": "ok", "score": float(out["score"]), "confidence": float(out.get("confidence", 0))}
    except (ValueError, KeyError, TypeError, AttributeError):
        return _fail(point, "unreadable")
