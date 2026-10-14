"""Parse claude stream-json lines into UI events and tail a stream file (#114)."""

from __future__ import annotations

import json
import os


def parse_line(line) -> list:
    try:
        ev = json.loads(line)
    except ValueError:  # includes UnicodeDecodeError
        return []
    if not isinstance(ev, dict):
        return []
    if ev.get("type") == "assistant":
        msg = ev.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        out = []
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                out.append({"kind": "text", "text": block["text"]})
            elif block.get("type") == "tool_use" and isinstance(block.get("name"), str):
                out.append({"kind": "tool", "name": block["name"], "input": block.get("input")})
        return out
    if ev.get("type") == "result":
        cost = ev.get("total_cost_usd")
        tokens = tokens_of(ev.get("usage"))
        text = ev.get("result")
        return [
            {
                "kind": "result",
                "cost": cost if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None,
                "is_error": bool(ev.get("is_error")),
                "text": text if isinstance(text, str) else None,
                "tokens": tokens,
            }
        ]
    return []


def _n(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def tokens_of(usage):
    """A result event's `usage` -> {input, cached, output}, or None. `input` counts every prompt token
    (fresh + cache writes + cache reads), so it matches what the cost was charged on; `cached` is
    the cache-read part of it."""
    if not isinstance(usage, dict):
        return None
    cached = _n(usage.get("cache_read_input_tokens"))
    total_in = _n(usage.get("input_tokens")) + _n(usage.get("cache_creation_input_tokens")) + cached
    out = _n(usage.get("output_tokens"))
    return {"input": total_in, "cached": cached, "output": out} if total_in or out else None


def read_from(path: str, offset: int):
    try:
        f = open(path, "rb")
    except FileNotFoundError:
        return [], offset
    with f:
        if offset >= os.fstat(f.fileno()).st_size:
            return [], offset
        f.seek(offset)
        # ponytail: tail read in one go, add a byte cap if streams get huge
        chunk = f.read()
    end = chunk.rfind(b"\n")
    if end < 0:
        return [], offset
    events = []
    for line in chunk[:end].split(b"\n"):
        events.extend(parse_line(line))
    return events, offset + end + 1
