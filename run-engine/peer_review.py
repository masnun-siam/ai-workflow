"""Peer-review panel store and lens offers.

A panel is one folder per run under `<data_dir>/peer-review/<panel-id>/`: `panel.json` (artifact,
lenses, root session, round, dropped/failed lenses, state) and `round-<n>/<lens>.md`, each lens
session's free-text final message. The only machine-read part of a verdict is a closing
`Verdict: approve|changes` line; a missing line counts as `changes`. Nothing else is validated.

`ui_panel.py` runs the sessions (one `peer-reviewer` per lens, verdicts relayed to the root session);
this module is the store and the round arithmetic: `advance` approves when every active lens
approves, opens the next round otherwise, and stops as "cap reached" after `peer_review.max_rounds`
(config) rounds. Nothing auto-approves. `offers` / `check_lenses` give the lens picker and the
server the lenses each command offers.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

from shared import data_dir, load_config, write_json


def _policy() -> dict:
    return load_config(None)["peer_review"]


def offers() -> dict:
    """What the web UI needs to draw the lens picker: no lens is hardcoded in the frontend."""
    policy = _policy()
    return {
        "default": list(policy["default_lenses"]),
        "max_rounds": policy["max_rounds"],
        "kinds": {k: list(v["offer"]) for k, v in policy["kinds"].items()},
    }


def check_lenses(kind: str, picked: list) -> list[str]:
    """The picked lenses, deduplicated; ValueError names the offered set when one isn't offered."""
    kinds = _policy()["kinds"]
    if kind not in kinds:
        raise ValueError(f"{kind or 'this command'} has no peer review; one of {', '.join(kinds)}")
    offer = kinds[kind]["offer"]
    bad = [x for x in picked if x not in offer]
    if bad or not picked:
        raise ValueError(f"{kind} offers the lenses {', '.join(offer)}; got {', '.join(map(str, bad)) or 'none'}")
    return list(dict.fromkeys(picked))


# --- lens-session panels (PRD FR-13): one folder per panel, free-text verdicts, no JSON validation ---

_PANEL_ID = re.compile(r"p-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}")
_VERDICT = re.compile(r"^[\s*_`>#-]*verdict:\s*[*_`]*(approve|changes)\b", re.I | re.M)


def panel_dir(panel: str) -> str:
    if not isinstance(panel, str) or not _PANEL_ID.fullmatch(panel):
        raise ValueError(f"invalid panel id: {panel!r}")
    return os.path.join(data_dir(), "peer-review", panel)


def load_panel(panel: str) -> dict:
    """The panel record; FileNotFoundError when there is no such panel."""
    with open(os.path.join(panel_dir(panel), "panel.json"), encoding="utf-8") as fh:
        return json.load(fh)


def update_panel(panel: str, **fields) -> dict:
    # ponytail: no lock; the UI's one tick thread and the request handlers touch different fields
    rec = {**load_panel(panel), **fields}
    write_json(os.path.join(panel_dir(panel), "panel.json"), rec)
    return rec


def new_panel(repo: str, artifact: str, lenses: list, root_session: str | None) -> str:
    """A fresh panel folder (never reused); returns its id."""
    if not lenses:
        raise ValueError("a panel needs at least one lens")
    while True:
        panel = f"p-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{os.urandom(3).hex()}"
        try:
            os.makedirs(panel_dir(panel))
            break
        except FileExistsError:
            continue
    write_json(
        os.path.join(panel_dir(panel), "panel.json"),
        {
            "id": panel,
            "repo": repo,
            "artifact": os.path.abspath(artifact),
            "lenses": list(dict.fromkeys(lenses)),
            "root_session": root_session,
            "round": 1,
            "dropped": [],
            "failed": [],
            "state": "running",
            "reason": None,
        },
    )
    return panel


def _verdict_path(panel: str, rnd: int, lens: str) -> str:
    return os.path.join(panel_dir(panel), f"round-{rnd}", f"{lens}.md")


def read_verdict(panel: str, lens: str, rnd: int | None = None) -> str | None:
    """approve | changes for a lens that reported in the round (default: the open one), else None."""
    p = _verdict_path(panel, rnd or load_panel(panel)["round"], lens)
    try:
        with open(p, encoding="utf-8") as fh:
            found = _VERDICT.findall(fh.read())
    except FileNotFoundError:
        return None
    return found[-1].lower() if found else "changes"  # no verdict line: not an approval


def record_verdict(panel: str, lens: str, text: str) -> str:
    """Write round-<n>/<lens>.md and return its verdict. A missing verdict line counts as changes."""
    rec = load_panel(panel)
    if lens not in rec["lenses"] or lens in rec["dropped"]:
        raise ValueError(f"{lens!r} is not an active lens of {panel}")
    p = _verdict_path(panel, rec["round"], lens)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text or "")
    if lens in rec["failed"]:
        update_panel(panel, failed=[x for x in rec["failed"] if x != lens])
    return read_verdict(panel, lens)


def mark_failed(panel: str, lens: str) -> None:
    rec = load_panel(panel)
    if lens in rec["lenses"] and lens not in rec["dropped"] and lens not in rec["failed"]:
        update_panel(panel, failed=[*rec["failed"], lens])


def drop_lens(panel: str, lens: str) -> None:
    rec = load_panel(panel)
    if lens in rec["lenses"] and lens not in rec["dropped"]:
        update_panel(panel, dropped=[*rec["dropped"], lens], failed=[x for x in rec["failed"] if x != lens])


def advance(panel: str) -> str:
    """wait | approved | next | cap reached | failed. Moves on only once every active lens has reported."""
    rec = load_panel(panel)
    if rec["state"] != "running":
        return rec["state"]
    active = [x for x in rec["lenses"] if x not in rec["dropped"]]
    if not active:
        update_panel(panel, state="failed", reason="every lens was dropped")
        return "failed"
    verdicts = [read_verdict(panel, x) for x in active]
    if None in verdicts:
        return "wait"
    if all(v == "approve" for v in verdicts):
        update_panel(panel, state="approved")
        return "approved"
    if rec["round"] >= rec.get(
        "max_rounds", _policy()["max_rounds"]
    ):  # last verdicts stay on disk for display; nothing auto-approves
        update_panel(panel, state="cap reached")
        return "cap reached"
    update_panel(panel, round=rec["round"] + 1)
    return "next"


def panel_status(panel: str) -> dict:
    rec = load_panel(panel)
    active = [x for x in rec["lenses"] if x not in rec["dropped"]]
    per = {x: "failed" if x in rec["failed"] else read_verdict(panel, x) or "waiting" for x in active}
    return {
        "approved": sum(v == "approve" for v in per.values()),
        "total": len(active),
        "round": rec["round"],
        "max_rounds": rec.get("max_rounds", _policy()["max_rounds"]),  # raised per panel by "more rounds"
        "state": rec["state"],
        "reason": rec.get("reason"),
        "lenses": per,
    }
