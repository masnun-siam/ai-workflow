"""Away mode answerer: the prompt for one question round and the validator for its reply.

PRD: docs/prds/away-mode-answerer.md (FR-3, FR-4). The answerer's final message ends with one line
`AWAY-ANSWER: <json>`, either {"answers": {"0": {"labels": [...], "why": "..."}, ...}} or
{"hold": "reason"}. Labels are checked exactly like a human answer (ui_sessions.answer_text), so an
injected instruction can at most steer a pick among the offered options. Anything else is a failure.
"""

from __future__ import annotations

import json
import os

import ui_sessions

PREFIX = "AWAY-ANSWER:"
MAX_WHY = 300
AGENT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agents", "away-answerer.md")


def allowed_tools() -> list:
    """The agent file's `tools:` list: the one source for what the answerer session may call."""
    with open(AGENT_FILE, encoding="utf-8") as f:
        for line in f:
            if line.startswith("tools:"):
                return line[len("tools:") :].strip().split(", ")
    raise ValueError(f"no tools: line in {AGENT_FILE}")


def prompt(rec: dict, pending: dict, transcript: str, checkout: str) -> str:
    return (
        f"Answer the question round below for the session that asked it (command: {rec.get('command')}, "
        f"repo: {rec.get('repo')}). Its transcript is at {transcript} and its checkout is at {checkout}; "
        "read them, read-only, to decide. Pick option labels for every question, each with a one-line reason, "
        "or hold the whole round with a reason when you cannot decide safely. Questions, with every option:\n"
        f"{json.dumps(pending['questions'], ensure_ascii=False, indent=1)}\n"
        f"End your final message with one line `{PREFIX} <json>`, where json is "
        '{"answers": {"0": {"labels": ["<offered label>"], "why": "<reason>"}, ...}} with one entry per '
        "question index (one label for a single-select question, one or more for a multi-select one, only "
        'labels the question offers, no free text), or {"hold": "<reason>"}.'
    )


def _reason(value, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} must be a non-empty string")
    return value.strip()[:MAX_WHY]


def parse_reply(text: str, pending: dict) -> dict:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines or not lines[-1].startswith(PREFIX):
        raise ValueError(f"last line must start with {PREFIX}")
    try:
        data = json.loads(lines[-1][len(PREFIX) :])
    except ValueError:
        raise ValueError("bad JSON") from None
    if not isinstance(data, dict) or len(data) != 1 or next(iter(data)) not in ("answers", "hold"):
        raise ValueError("reply must be an object with exactly answers or hold")
    if "hold" in data:
        return {"hold": _reason(data["hold"], "hold reason")}
    answers = data["answers"]
    if not isinstance(answers, dict):
        raise ValueError("answers must be an object")
    labels = {}
    for i, a in answers.items():
        if not isinstance(a, dict) or "other" in a:
            raise ValueError(
                f"answer {i}: free text is not allowed" if isinstance(a, dict) else f"answer {i} must be an object"
            )
        if set(a) != {"labels", "why"}:
            raise ValueError(f"answer {i} must have exactly labels and why")
        labels[i] = {"labels": a["labels"]}
    ui_sessions.answer_text(pending, labels)  # same rules as a human answer; its ValueError is the reason
    return {
        "answers": {
            i: {"labels": answers[i]["labels"], "why": _reason(answers[i]["why"], f"answer {i} why")} for i in answers
        }
    }
