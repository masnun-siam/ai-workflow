"""`aiw ask` — record a gate question for a headless (UI) run instead of calling AskUserQuestion.

ADR 0001 (docs/adr/0001-headless-question-pause.md), issue #118. The UI runner sets
AIW_HEADLESS=1 and AIW_UI_SESSION=<ui session id>; the round lands in the session's
pending_question via ui_sessions.set_pending and the model ends its turn.
"""

from __future__ import annotations

import json
import os
import secrets
import sys

import ui_sessions
from shared import die


def cmd_ask(args) -> None:
    if os.environ.get("AIW_HEADLESS") != "1":
        die(2, "aiw ask is for headless runs; interactive runs use AskUserQuestion")
    sid = os.environ.get("AIW_UI_SESSION", "")
    try:
        rec = ui_sessions.load(sid)
    except ValueError:
        rec = None
    if rec is None:
        die(2, "AIW_UI_SESSION is missing or names no known UI session")
    payload = json.loads(args.json if args.json is not None else sys.stdin.read())
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object with a 'questions' list")
    pending = rec.get("pending_question")
    # ponytail: no lock across this check and set_pending; one model asks serially. Lock if that changes.
    if rec.get("status") == "waiting" and isinstance(pending, dict) and pending.get("status") == "pending":
        rid = pending["id"]
    else:
        rid = f"q-{secrets.token_hex(4)}"
        ui_sessions.set_pending(sid, {"id": rid, "questions": payload.get("questions")})
    print(f"RECORDED {rid}. The question is now with the human. End your turn immediately; "
          f"the answer arrives as your next message: Answer to {rid}: {{...}}")


def register(sub, add) -> None:
    p = sub.add_parser("ask", help="record a gate question for a headless run (AskUserQuestion stand-in)")
    p.add_argument("--json", help="AskUserQuestion input as JSON; read from stdin when omitted")
    p.set_defaults(func=cmd_ask)
