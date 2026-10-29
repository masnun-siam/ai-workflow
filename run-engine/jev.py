"""The one place that runs the `jev` CLI (typed yes/no, choice and score questions). Stdlib only.

ask(point, kind, question, text, ...) -> {"status": "ok", ...answer} or {"status": <why not>}.
Statuses: ok, off (Settings -> Use jev is off), missing (not on PATH), no_answer (timeout or exec error),
failed (non-zero exit, with "exit"), unreadable (bad JSON or field). A failure never raises, and the
`jev` binary never runs while the switch is off. Text is redacted, then cut to MAX_CHARS, before it is sent.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import shared
import ui_settings

MODEL = "jev-1.14.0"  # pinned: an alias such as jev-latest moves without notice
TIMEOUT_S = 8
MAX_CHARS = 4000

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


def ask(
    point: str, kind: str, question: str, text: str, *, options: dict | None = None, levels: list | None = None
) -> dict:
    s = status()
    if s != "ok":
        return {"status": s}
    sent = redact(text)[:MAX_CHARS]
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
