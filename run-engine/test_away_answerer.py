#!/usr/bin/env python3
"""Self-check for run-engine/away_answerer.py. `python3 test_away_answerer.py` — exit 0 = green."""

from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()

import away_answerer as aa  # noqa: E402

PENDING = {
    "id": "r1",
    "status": "pending",
    "questions": [
        {
            "header": "H",
            "question": "Q0",
            "multiSelect": False,
            "allowFreeText": True,
            "options": [{"label": "A", "description": "a"}, {"label": "B", "description": "b", "preview": "pv"}],
        },
        {
            "header": "H",
            "question": "Q1",
            "multiSelect": True,
            "allowFreeText": True,
            "options": [{"label": "X", "description": "x"}, {"label": "Y", "description": "y"}],
        },
    ],
}


def reply(obj) -> str:
    return "Thinking...\nAWAY-ANSWER: " + (obj if isinstance(obj, str) else json.dumps(obj)) + "\n\n"


def fails(text, needle=""):
    try:
        aa.parse_reply(text, PENDING)
    except ValueError as e:
        assert needle in str(e), str(e)
        return
    raise AssertionError(f"expected ValueError for {text!r}")


def pick(a0=("A",), a1=("X", "Y"), why="because"):
    return {"answers": {"0": {"labels": list(a0), "why": why}, "1": {"labels": list(a1), "why": why}}}


# prompt
p = aa.prompt({"command": "/implement-issue 5", "repo": "/r"}, PENDING, "/t/transcript.jsonl", "/c")
assert p and not p.startswith("-")
for s in ("/implement-issue 5", "/r", "/t/transcript.jsonl", "/c", "AWAY-ANSWER:", '"preview": "pv"', '"label": "Y"'):
    assert s in p, s

# valid picks, single and multi-select
assert aa.parse_reply(reply(pick()), PENDING) == pick()
# a hold
assert aa.parse_reply(reply({"hold": " unsure "}), PENDING) == {"hold": "unsure"}
# a 400-character why is cut to 300
out = aa.parse_reply(reply(pick(why="w" * 400)), PENDING)
assert len(out["answers"]["0"]["why"]) == 300
assert len(aa.parse_reply(reply({"hold": "h" * 400}), PENDING)["hold"]) == 300

# failures
fails("no line at all", "AWAY-ANSWER")
fails("")
fails(reply(pick()) + "and then more text", "AWAY-ANSWER")  # line not last
fails(reply("{nope"), "bad JSON")
fails(reply([1]), "exactly")
fails(reply({"answers": {}, "hold": "x"}), "exactly")
fails(reply({"hold": ""}), "non-empty")
fails(reply({"hold": 3}), "non-empty")
other = pick()
other["answers"]["0"] = {"other": "free text"}
fails(reply(other), "free text is not allowed")
fails(reply(pick(a0=("Z",))), "not an option")
fails(reply(pick(a0=("A", "B"))), "only one label")
missing = pick()
del missing["answers"]["1"]
fails(reply(missing), "one entry per question")
fails(reply(pick(why="  ")), "non-empty")
nowhy = pick()
del nowhy["answers"]["0"]["why"]
fails(reply(nowhy), "labels and why")

print("ok")
