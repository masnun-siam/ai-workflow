"""Delivery board data (FR-16): poller snapshot + live sessions + grind state + settings -> /api/delivery.

Inputs (plain data, no I/O):
  snapshot       ui_poller snapshot
  sessions       ui_sessions records; live `/implement-issue <n>` ones (ui_runner._issue_key) count
  grind_index    ui_grind.index() -> {"pr": {(owner, repo, pr): {state, round}}}
  settings       {auto_grind, autopilot_cap, slack_channel, autopilot}; `autopilot` is a list of epic
                 numbers or a {epic: bool} map (the repo's autopilot epics); cap defaults to 2
  cleanup_flags  {issue_n: {uncommitted, unpushed}} for merged issues that need cleanup (ui_mergeclean)

Result: {repo, stale, fetched_at, cap, running, auto_grind, lanes: [{epic, title, autopilot, cap, running, cards}]},
one lane per open epic plus a final "No epic" lane (epic None). Card:
{n, title, column, priority, blocked_by: [n], pr: {n, draft, ci, url} | None,
 session: {id, status} | None, grind_round: int | None, needs_cleanup: None | {uncommitted, unpushed}}.
`column` is ready | in_progress | draft_pr | in_review | grinding | merged. Placement of an open
issue: an OPEN PR decides (grinding if its grind state is not done, else draft_pr / in_review); else a
live session -> in_progress; else `refined` -> ready; else it is left out. A closed-unmerged PR is
ignored, so its issue falls back to Ready. `blocked_by` lists open blockers only.
"""

from __future__ import annotations

import os

import dispatch
import ui_runner
import ui_sessions

DEFAULT_CAP = 2
COLUMNS = ("ready", "in_progress", "draft_pr", "in_review", "grinding", "merged")


def _slug(rec) -> str:
    """owner/repo of a session. `repo` holds the checkout *path* for sessions started from the UI, so the
    link (or the checkouts registry, for a session without one) names it; a bare owner/repo is used as is."""
    link = rec.get("link") if isinstance(rec.get("link"), dict) else {}
    if link.get("owner") and link.get("repo"):
        return f"{link['owner']}/{link['repo']}"
    repo = str(rec.get("repo") or "")
    if repo.startswith("/"):
        path = os.path.realpath(repo)
        return next((k for k, v in dispatch.read_checkouts().items() if os.path.realpath(str(v)) == path), "")
    return repo


def _live_sessions(repo: str, sessions) -> dict:
    """{issue_n: record} of live implement-issue sessions for this repo."""
    out = {}
    for rec in sessions or []:
        if rec.get("status") not in ui_sessions._LIVE:
            continue
        key = ui_runner._issue_key(rec)
        slug = _slug(rec)
        if key and key[1].startswith("implement-issue:") and str(slug).lower() == repo.lower():
            out[int(key[1].split(":")[1])] = rec
    return out


def _epics(settings) -> set:
    a = (settings or {}).get("autopilot") or []
    return {int(k) for k, v in a.items() if v} if isinstance(a, dict) else {int(x) for x in a}


def build(repo, snapshot, sessions, grind_index, settings, cleanup_flags) -> dict:
    data = snapshot.get("data") or {}
    settings = settings or {}
    cap = settings.get("autopilot_cap") or DEFAULT_CAP
    live = _live_sessions(repo, sessions)
    owner, _, name = repo.partition("/")
    grinds = (grind_index or {}).get("pr") or {}
    auto = _epics(settings)

    epics = {i["n"]: i for i in data.get("issues") or [] if "epic" in i["labels"]}
    lanes = {n: [] for n in epics}
    lanes[None] = []

    for i in data.get("issues") or []:
        if "epic" in i["labels"]:
            continue
        if any(p["state"] == "MERGED" for p in i["prs"]):
            continue  # merged into a non-default branch, so still open: its card is in Merged
        pr = next((p for p in i["prs"] if p["state"] == "OPEN"), None)
        sess = live.get(i["n"])
        grind = grinds.get((owner.lower(), name.lower(), pr["n"])) if pr else None
        if pr:
            if grind and grind.get("state") != "done":
                column = "grinding"
            else:
                column = "draft_pr" if pr["draft"] else "in_review"
        elif sess:
            column = "in_progress"
        elif "refined" in i["labels"]:
            column = "ready"
        else:
            continue  # non-refined, no PR, no session: the Planning board covers it
        lanes[i["parent"] if i["parent"] in epics else None].append(
            {
                "n": i["n"],
                "title": i["title"],
                "column": column,
                "priority": i["priority"],
                "blocked_by": [b["n"] for b in i["blocked_by"] if b["state"] == "OPEN"],
                "pr": {"n": pr["n"], "draft": pr["draft"], "ci": pr["ci"], "url": pr["url"]} if pr else None,
                "session": {"id": sess["id"], "status": sess["status"]} if sess else None,
                "grind_round": grind.get("round") if column == "grinding" else None,
                "needs_cleanup": None,
            }
        )

    for m in data.get("merged") or []:
        n = m["closes"][0] if m["closes"] else m["n"]
        lanes[m["epic"] if m["epic"] in epics else None].append(
            {
                "n": n,
                "title": m["title"],
                "column": "merged",
                "priority": None,
                "blocked_by": [],
                "pr": {"n": m["n"], "draft": False, "ci": "success", "url": m["url"]},
                "session": None,
                "grind_round": None,
                "needs_cleanup": (cleanup_flags or {}).get(n),
            }
        )

    running = len(live)
    out = []
    for n, cards in lanes.items():
        title = "No epic" if n is None else epics[n]["title"].removeprefix("Epic:").strip()
        out.append({"epic": n, "title": title, "autopilot": n in auto, "cap": cap, "running": running, "cards": cards})
    out.sort(key=lambda lane: (lane["epic"] is None, lane["epic"] or 0))
    return {
        "repo": repo,
        "stale": snapshot.get("stale", True),
        "fetched_at": snapshot.get("fetched_at"),
        "cap": cap,
        "running": running,
        "auto_grind": settings.get("auto_grind") is True,
        "lanes": out,
    }
