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
        text = ev.get("result")
        return [
            {
                "kind": "result",
                "cost": cost if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None,
                "is_error": bool(ev.get("is_error")),
                "text": text if isinstance(text, str) else None,
            }
        ]
    return []


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
