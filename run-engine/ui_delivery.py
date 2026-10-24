"""Delivery board data (FR-16): poller snapshot + live sessions + grind state + settings -> /api/delivery.

Inputs (plain data, no I/O):
  snapshot       ui_poller snapshot
  sessions       ui_sessions records; live `/implement-issue <n>` ones (ui_runner._issue_key) count
  grind_index    ui_grind.index() -> {"pr": {(owner, repo, pr): {state, round}}}
  settings       ui_settings.repo_settings: auto_grind, issue_grind, slack_channel
  cleanup_flags  {issue_n: {uncommitted, unpushed}} for merged issues that need cleanup (ui_mergeclean)
  solo           the user owns the repo (ui_gh.solo)

Result: {repo, stale, fetched_at, running, auto_grind, lanes: [{epic, title, running, cards}]},
one lane per open epic plus a final "No epic" lane (epic None). Card:
{n, title, column, priority, blocked_by: [n], pr: {n, draft, ci, url, review, conflict} | None,
 session: {id, status} | None, grind: {state, round, reason, thread} | None, grind_on: bool,
 mergeable: bool (ui_inbox.merge_ready), needs_cleanup: None | {uncommitted, unpushed}}.
`review` is approved | changes_requested | review_required | none. `grind` is the PR's loop (state running |
idle | paused; reason only when paused), None when it has none or is done.
`column` is unrefined | ready | in_progress | draft_pr | in_review | grinding | merged. Placement of an open
issue: an OPEN PR decides (grinding if its grind state is not done, else draft_pr / in_review); else a
live session -> in_progress; else `refined` -> ready; else unrefined. A closed-unmerged PR is
ignored, so its issue falls back to Ready. `blocked_by` lists open blockers only.
"""

from __future__ import annotations

import os

import dispatch
import ui_inbox
import ui_runner
import ui_sessions

COLUMNS = ("unrefined", "ready", "in_progress", "draft_pr", "in_review", "grinding", "merged")


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


def build(repo, snapshot, sessions, grind_index, settings, cleanup_flags, solo=False) -> dict:
    data = snapshot.get("data") or {}
    settings = settings or {}
    live = _live_sessions(repo, sessions)
    owner, _, name = repo.partition("/")
    grinds = (grind_index or {}).get("pr") or {}

    epics = {i["n"]: i for i in data.get("issues") or [] if "epic" in i["labels"]}
    lanes = {n: [] for n in epics}
    lanes[None] = []
    # an epic's children, as ui_planning counts them: parent, its sub_issues, or the `prd-<slug>` label
    owner_of = {}
    for e in epics.values():
        for lab in (x for x in e["labels"] if x.startswith("prd-")):
            owner_of[lab] = e["n"]
        owner_of.update({s: e["n"] for s in e["sub_issues"]})

    def epic_of(i):
        if i["parent"] in epics:
            return i["parent"]
        return owner_of.get(i["n"]) or next(
            (owner_of[x] for x in i["labels"] if x in owner_of and x.startswith("prd-")), None
        )

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
            column = "unrefined"  # still to refine, in its epic's lane or the No epic lane
        on = ui_inbox.grind_on(settings, i["n"])
        lanes[epic_of(i)].append(
            {
                "n": i["n"],
                "title": i["title"],
                "column": column,
                "grind_on": on,
                "mergeable": ui_inbox.merge_ready(pr, grind, on, solo),
                "priority": i["priority"],
                "blocked_by": [b["n"] for b in i["blocked_by"] if b["state"] == "OPEN"],
                "pr": {
                    "n": pr["n"],
                    "draft": pr["draft"],
                    "ci": pr["ci"],
                    "url": pr["url"],
                    "review": pr.get("review", "none"),
                    "conflict": pr.get("conflict", False),
                }
                if pr
                else None,
                "session": {"id": sess["id"], "status": sess["status"]} if sess else None,
                "grind": {
                    "state": grind["state"],
                    "round": grind["round"],
                    "reason": ui_inbox.split_reason(grind.get("reason"))[1],
                    "thread": grind.get("thread"),
                }
                if grind and grind.get("state") != "done"
                else None,
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
                "grind_on": False,
                "mergeable": False,
                "priority": None,
                "blocked_by": [],
                "pr": {"n": m["n"], "draft": False, "ci": "success", "url": m["url"], "review": "none"},
                "session": None,
                "grind": None,
                "needs_cleanup": (cleanup_flags or {}).get(n),
            }
        )

    running = len(live)
    out = []
    for n, cards in lanes.items():
        title = "No epic" if n is None else epics[n]["title"].removeprefix("Epic:").strip()
        out.append({"epic": n, "title": title, "running": running, "cards": cards})
    out.sort(key=lambda lane: (lane["epic"] is None, lane["epic"] or 0))
    return {
        "repo": repo,
        "stale": snapshot.get("stale", True),
        "fetched_at": snapshot.get("fetched_at"),
        "running": running,
        "auto_grind": settings.get("auto_grind") is True,
        "lanes": out,
    }
