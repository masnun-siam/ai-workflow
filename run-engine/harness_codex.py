"""The Codex adapter. #871 ships only the parser: one `codex exec --json` line -> UI events
(the `ui_events` shapes, plus `session_id` and `limit`). #878 adds the rest of the adapter."""

from __future__ import annotations

import json
import re

from ui_events import _n

# Copied from ui_runner._LIMIT_RE so the parser does not import the runner. G1 replaces it.
LIMIT_RE = re.compile(r"usage limit|limit reached|rate.?limit|hit your limit", re.I)


def parse_line(line) -> list:
    try:
        ev = json.loads(line)
    except ValueError:  # includes UnicodeDecodeError
        return []
    if not isinstance(ev, dict):
        return []
    kind = ev.get("type")
    if kind == "thread.started":
        tid = ev.get("thread_id")
        return [{"kind": "session_id", "id": tid, "model": None}] if isinstance(tid, str) else []
    if kind == "item.completed":
        return _item(ev.get("item"))
    if kind == "turn.completed":
        return [{"kind": "result", "cost": None, "is_error": False, "text": None, "tokens": _tokens(ev.get("usage"))}]
    if kind == "turn.failed":
        err = ev.get("error")
        return _failed(err.get("message") if isinstance(err, dict) else None)
    if kind == "error":
        return _failed(ev.get("message"))
    return []


def _item(item) -> list:
    if not isinstance(item, dict) or not isinstance(item.get("type"), str):
        return []
    if item["type"] == "agent_message":
        return [{"kind": "text", "text": item["text"]}] if isinstance(item.get("text"), str) else []
    if item["type"] == "command_execution":
        cmd = item.get("command")
        return [{"kind": "tool", "name": "Bash", "input": {"command": cmd}}] if isinstance(cmd, str) else []
    return [{"kind": "tool", "name": item["type"], "input": item}]


def _tokens(usage):
    """OpenAI usage: `input_tokens` is the whole prompt, `cached_input_tokens` the cached part of it,
    which is what `ui_events.tokens_of` means by input and cached. PROVISIONAL until the real fixture."""
    if not isinstance(usage, dict):
        return None
    tokens = {
        "input": _n(usage.get("input_tokens")),
        "cached": _n(usage.get("cached_input_tokens")),
        "output": _n(usage.get("output_tokens")),
    }
    return tokens if any(tokens.values()) else None


def _failed(message) -> list:
    text = message if isinstance(message, str) else None
    out = [{"kind": "result", "cost": None, "is_error": True, "text": text, "tokens": None}]
    if text and LIMIT_RE.search(text):
        out.append({"kind": "limit", "resets_at": None, "type": None, "info": None})
    return out
