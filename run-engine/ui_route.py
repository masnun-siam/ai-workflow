"""Route a typed idea to a feature (a PRD) or a small change (one issue), with the `jev` CLI. Stdlib only.

POST /api/route {"text"} -> {"route": "feature"|"small_change"|null, "confidence", "why"}.
A null route means jev could not tell, is not installed, or failed: the UI then asks the user to pick.
"""

from __future__ import annotations

import json
import shutil
import subprocess

MODEL = "jev-1.14.0"  # pinned: an alias such as jev-latest moves without notice
TIMEOUT_S = 8
MAX_CHARS = 4000
MIN_CONFIDENCE = 0.4

QUESTION = "Is this request a new feature that needs a product spec, or a small change that fits in one issue?"
OPTIONS = {
    "feature": "A new capability or workflow with several decisions to settle (who, what, edge cases); needs a written spec and several issues",
    "small_change": "A bug fix, a tweak, a chore or one contained change that fits in a single issue",
    "unclear": "Too vague to tell",
}
WHY = {
    "feature": "it adds a new capability with its own decisions to settle",
    "small_change": "it reads as a fix or one contained change",
}


def _none(why: str) -> dict:
    return {"route": None, "confidence": 0.0, "why": why}


def route(text) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text is required")
    exe = shutil.which("jev")
    if not exe:
        return _none("jev is not installed")
    cmd = [exe, "choice", QUESTION, "--model", MODEL, "--state-file", "-", "-o", "json"]
    for k, v in OPTIONS.items():
        cmd += ["--option", f"{k}={v}"]
    try:
        p = subprocess.run(cmd, input=text.strip()[:MAX_CHARS], capture_output=True, text=True, timeout=TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return _none("jev did not answer")
    if p.returncode != 0:
        return _none("jev failed (exit %d)" % p.returncode)
    try:
        out = json.loads(p.stdout)
        choice = out["choice"]
        conf = float(out.get("probabilities", {}).get(choice, out.get("confidence", 0)))
    except (ValueError, KeyError, TypeError):
        return _none("jev gave an unreadable answer")
    if choice not in WHY or conf < MIN_CONFIDENCE:
        return {"route": None, "confidence": conf, "why": "too vague to tell"}
    return {"route": choice, "confidence": conf, "why": WHY[choice]}
