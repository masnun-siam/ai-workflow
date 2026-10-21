"""Peer-review panels run by the UI (PRD FR-13/FR-14, UI-relay transport).

One headless `peer-reviewer` session per lens, all linked to a root session. `tick()` moves each panel on:
a finished lens session's final text becomes its verdict (`peer_review.record_verdict`); once every lens of the
round has reported the root is resumed with the verdicts to revise the artifact in place; when its turn ends the
same lens sessions are resumed to re-review. The store (panel.json, round-<n>/<lens>.md) is peer_review.py.

panel.phase: waiting_root (lenses start when the root's turn ends) | lenses | root (revising) | done.
"""

from __future__ import annotations

import os
import threading
import time

import peer_review
import ui_events
import ui_notify
import ui_runner
import ui_sessions
from shared import warn

LENS_AGENT, LENS_MODEL = "ai-workflow:peer-reviewer", "opus"
TICK_SECONDS = 5
_BUSY = ("starting", "running", "waiting", "limited", "queued")
_lock = threading.RLock()


class Conflict(Exception):
    pass


def final_text(sid: str) -> str:
    """The last turn's final answer: the stream's last result text, else its last assistant text."""
    path = os.path.join(ui_sessions.session_dir(sid), "stream.jsonl")
    result = text = None
    try:
        with open(path, "rb") as fh:
            for line in fh:
                for ev in ui_events.parse_line(line):
                    if ev["kind"] == "result" and ev["text"] is not None:
                        result = ev["text"]
                    elif ev["kind"] == "text":
                        text = ev["text"]
    except FileNotFoundError:
        pass
    return result if result is not None else (text or "")


def _status(sid) -> str | None:
    rec = ui_sessions.load(sid) if sid else None
    return rec.get("status") if rec else None


def _lens(lens: str) -> dict:
    return peer_review._policy()["lenses"][lens]


def _lens_prompt(panel: dict, lens: str, rnd: int) -> str:
    revised = " The artifact was revised since your last round: re-read it and re-review." if rnd > 1 else ""
    return (
        f"Review the artifact at {panel['artifact']} through the {lens} lens. This is round {rnd} of "
        f"panel {panel['id']}.{revised} You are read-only: edit nothing. Reply to the root only. "
        f"Lens: {_lens(lens)['focus']}. {_lens(lens)['prompt']} "
        "Report at most 8 findings, most severe first, each citing the artifact line (or file:line) it is about; "
        "a finding that needs a fact only the user has is a question, not a fix. "
        "End your final message with a line `Verdict: approve` or `Verdict: changes`."
    )


def _start_lens(panel_id: str, lens: str) -> None:
    p = peer_review.load_panel(panel_id)
    rec = ui_runner.start(_lens_prompt(p, lens, p["round"]), p["repo"], agent=LENS_AGENT, model=LENS_MODEL)
    ui_sessions.update(rec["id"], panel=panel_id, panel_role="lens", panel_lens=lens)
    peer_review.update_panel(panel_id, lens_sessions={**p.get("lens_sessions", {}), lens: rec["id"]})


def _fail(panel_id: str, reason: str) -> None:
    p = peer_review.load_panel(panel_id)
    for sid in (p.get("lens_sessions") or {}).values():
        if _status(sid) in _BUSY:
            try:
                ui_runner.stop(sid)
            except Exception as e:  # noqa: BLE001 - best effort, the panel is over either way
                warn(f"panel {panel_id}: stopping {sid} failed: {e}")
    peer_review.update_panel(panel_id, state="failed", reason=reason, phase="done")


def start(repo: str, artifact: str, lenses: list, root_session: str | None = None, after_root: bool = False) -> str:
    """A new panel; returns its id. Without a root session a fresh headless root is started on `repo`.
    after_root: the lenses wait for the root's current turn to end (the artifact is written by it)."""
    if not isinstance(repo, str) or not repo:
        raise ValueError("repo must be a string")
    if not isinstance(artifact, str) or not os.path.isabs(artifact) or not os.path.isfile(artifact):
        raise ValueError("artifact must be the absolute path of an existing file")
    if not isinstance(lenses, list) or not lenses or not all(isinstance(x, str) for x in lenses):
        raise ValueError("lenses must be a non-empty list of lens names")
    lenses = peer_review.check_lenses("custom", lenses)  # ValueError names what is offered
    if root_session is not None and (not isinstance(root_session, str) or ui_sessions.load(root_session) is None):
        raise ValueError(f"root_session {root_session!r} is not a known session")
    with _lock:
        panel_id = peer_review.new_panel(repo, artifact, lenses, root_session)
        try:
            if root_session is None:
                root_session = ui_runner.start(
                    f"/ai-workflow:peer-review --root {panel_id} {artifact}", repo, gate_questions=True
                )["id"]
                peer_review.update_panel(panel_id, root_session=root_session)
            ui_sessions.update(root_session, panel=panel_id, panel_role="root")
            peer_review.update_panel(panel_id, phase="waiting_root" if after_root else "lenses", lens_sessions={})
            if not after_root:
                for lens in lenses:
                    _start_lens(panel_id, lens)
        except (ValueError, ui_runner.RunnerError, OSError) as e:
            _fail(panel_id, f"could not start: {e}")
            raise
    return panel_id


def _root_message(panel: dict, rnd: int) -> str:
    parts = [f"Peer-review panel {panel['id']}, round {rnd - 1} verdicts on {panel['artifact']}:"]
    for lens in panel["lenses"]:
        if lens in panel["dropped"]:
            continue
        try:
            with open(peer_review._verdict_path(panel["id"], rnd - 1, lens), encoding="utf-8") as fh:
                body = fh.read().strip()
        except FileNotFoundError:
            body = "(no verdict)"
        parts.append(f"\n--- {lens} ---\n{body}")
    parts.append(
        f"\nNow revise the artifact in place to address these findings, then end your turn. "
        f"The panel asks the same lenses to re-review as round {rnd}."
    )
    return "\n".join(parts)


def _tick_panel(panel_id: str) -> None:
    p = peer_review.load_panel(panel_id)
    if p["state"] != "running":
        return
    if not os.path.isfile(p["artifact"]):
        _fail(panel_id, "artifact deleted")
        return
    root = p.get("root_session")
    phase = p.get("phase", "lenses")
    if phase in ("waiting_root", "root", "lenses"):
        rs = _status(root)
        if rs in ("failed", "stopped", None):
            _fail(panel_id, f"root session {rs or 'is gone'}")
            return
    if phase == "waiting_root":
        if rs == "done":
            peer_review.update_panel(panel_id, phase="lenses")
            for lens in p["lenses"]:
                _start_lens(panel_id, lens)
    elif phase == "root":
        if rs == "done":
            peer_review.update_panel(panel_id, phase="lenses")
            for lens in p["lenses"]:
                if lens in p["dropped"]:
                    continue
                sid = p["lens_sessions"].get(lens)
                try:
                    ui_runner.resume(sid, _lens_prompt(p, lens, p["round"]))
                except (ValueError, FileNotFoundError, ui_runner.RunnerError, OSError) as e:
                    warn(f"panel {panel_id}: re-review request to {lens} failed: {e}")
                    peer_review.mark_failed(panel_id, lens)
    elif phase == "lenses":
        for lens in p["lenses"]:
            if lens in p["dropped"] or lens in p["failed"] or peer_review.read_verdict(panel_id, lens) is not None:
                continue
            ls = _status(p["lens_sessions"].get(lens))
            if ls == "done":
                peer_review.record_verdict(panel_id, lens, final_text(p["lens_sessions"][lens]))
            elif ls in ("failed", "stopped", None):
                peer_review.mark_failed(panel_id, lens)
        if rs in _BUSY:  # revising needs an idle root; the verdicts wait on disk
            return
        before = peer_review.load_panel(panel_id)
        if peer_review.advance(panel_id) == "next":
            peer_review.update_panel(panel_id, phase="root")
            ui_runner.resume(root, _root_message(before, before["round"] + 1))
        elif peer_review.load_panel(panel_id)["state"] != "running":
            peer_review.update_panel(panel_id, phase="done")
            if peer_review.load_panel(panel_id)["state"] == "cap reached":  # one push: the state never re-runs
                ui_notify.notify(
                    "panel-cap",
                    {
                        "id": panel_id,
                        "repo": p["repo"],
                        "note": f"{os.path.basename(p['artifact'])}: round cap reached",
                    },
                )


def tick() -> None:
    """One pass over every running panel. A panel that errors is failed, never retried in a loop."""
    base = os.path.join(peer_review.data_dir(), "peer-review")
    try:
        names = os.listdir(base)
    except FileNotFoundError:
        return
    with _lock:
        for name in names:
            try:
                if os.path.isfile(os.path.join(base, name, "panel.json")):
                    _tick_panel(name)
            except Exception as e:  # noqa: BLE001
                warn(f"panel {name}: tick failed: {e}")
                try:
                    _fail(name, f"tick failed: {e}")
                except Exception:  # noqa: BLE001
                    pass


def lens_action(panel_id: str, lens, action) -> dict:
    """Re-run or drop a failed lens. ValueError: unknown lens/action; Conflict: the lens is not failed."""
    with _lock:
        p = peer_review.load_panel(panel_id)
        if lens not in p["lenses"]:
            raise ValueError(f"unknown lens {lens!r}; the panel is {', '.join(p['lenses'])}")
        if action not in ("rerun", "drop"):
            raise ValueError("action must be rerun or drop")
        if lens not in p["failed"]:
            raise Conflict(f"{lens} has not failed")
        if action == "drop":
            peer_review.drop_lens(panel_id, lens)
        else:
            try:
                _start_lens(panel_id, lens)
            except ui_runner.RunnerError as e:
                raise Conflict(f"could not restart {lens}: {e}")
            peer_review.update_panel(panel_id, failed=[x for x in p["failed"] if x != lens])
        return public(panel_id)


def add_rounds(panel_id: str, add) -> dict:
    """Raise a capped panel's round limit by `add` (1..5) and send the root the last round's verdicts, as `tick`
    does for a next round. ValueError: bad `add`; Conflict: not at its cap, or the root cannot take it."""
    if type(add) is not int or not 1 <= add <= 5:
        raise ValueError("add must be a whole number from 1 to 5")
    with _lock:
        p = peer_review.load_panel(panel_id)
        if p["state"] != "cap reached":
            raise Conflict("the panel is not at its round cap")
        root = p.get("root_session")
        if _status(root) in (*_BUSY, None):
            raise Conflict("the root session is not idle")
        cap = peer_review.panel_status(panel_id)["max_rounds"]
        peer_review.update_panel(
            panel_id, max_rounds=cap + add, round=p["round"] + 1, state="running", reason=None, phase="root"
        )
        try:
            ui_runner.resume(root, _root_message(p, p["round"] + 1))
        except (ValueError, FileNotFoundError, ui_runner.RunnerError, OSError) as e:
            peer_review.update_panel(panel_id, max_rounds=cap, round=p["round"], state="cap reached", phase="done")
            raise Conflict(f"could not resume the root session: {e}")
        return public(panel_id)


def public(panel_id: str) -> dict:
    return {"panel": panel_id, **peer_review.panel_status(panel_id)}


def start_timer(interval: float = TICK_SECONDS) -> threading.Thread:
    def loop():
        while True:
            try:
                tick()
            except Exception as e:  # noqa: BLE001 - keep the timer alive
                warn(f"panel timer tick failed: {e}")
            time.sleep(interval)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t
