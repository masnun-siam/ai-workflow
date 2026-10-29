"""Route a typed idea to a feature (a PRD) or a small change (one issue), with the `jev` CLI. Stdlib only.

POST /api/route {"text"} -> {"route": "feature"|"small_change"|null, "confidence", "why"}.
A null route means jev could not tell, is not installed, or failed: the UI then asks the user to pick.
"""

from __future__ import annotations

import jev

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

NOT_OK = {
    "off": "jev is off",
    "missing": "jev is not installed",
    "no_answer": "jev did not answer",
    "failed": "jev failed (exit {exit})",
    "unreadable": "jev gave an unreadable answer",
}


def _none(why: str) -> dict:
    return {"route": None, "confidence": 0.0, "why": why}


def route(text) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text is required")
    r = jev.ask("route", "choice", QUESTION, text.strip(), options=OPTIONS)
    if r["status"] != "ok":
        return _none(NOT_OK[r["status"]].format(**r))
    choice, conf = r["choice"], r["p"]
    if choice not in WHY or conf < MIN_CONFIDENCE:
        return {"route": None, "confidence": conf, "why": "too vague to tell"}
    return {"route": choice, "confidence": conf, "why": WHY[choice]}
