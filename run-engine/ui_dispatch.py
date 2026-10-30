"""Dispatches in the UI server: facts for the lane engine, the tick timer, Inbox items, notices, API bodies.

Every TICK_SECONDS each running dispatch is loaded under its lock, given facts and ticked (dispatch_run.tick).
Facts come from the board poller's snapshots (no GitHub call of its own: the poller's budget and rate-limit
pauses cover it; a lane whose repo is stale gets no facts and waits), the pr-grind state files and the
runner's view of the lane session. Every SYNC_SECONDS the epic's children are re-read (one GraphQL call), so
issues QA files join as lanes. On server start the timer simply carries on from the files.
"""

from __future__ import annotations

import threading
import time

import dispatch_cli
import dispatch_run as dr
import dispatch_runners
import ui_gh
import ui_grind
import ui_notify
import ui_settings
import ui_sessions
from shared import warn

TICK_SECONDS = 30
SYNC_SECONDS = 300
LIVE = ("running", "paused")


# --------------------------------------------------------------------------- facts


def _pr_of(x: dict, data: dict, issue):
    """The lane's PR: the one it already has, else the open one, else a merged one."""
    if issue is not None:
        prs = issue.get("prs") or []
    else:  # closed issue: the merged list still names the PR that closed it
        prs = [
            {**m, "state": "MERGED", "draft": False, "ci": "success", "conflict": False}
            for m in data.get("merged") or []
            if x["n"] in (m.get("closes") or [])
        ]
    if x.get("pr"):
        return next((p for p in prs if p["n"] == x["pr"]), None)
    return next((p for p in prs if p.get("state") == "OPEN"), None) or next(
        (p for p in prs if p.get("state") == "MERGED"), None
    )


def _grind(repo: str, pr: int, files=None):
    owner, _, name = repo.lower().partition("/")
    for _, h in files if files is not None else ui_grind._state_files():
        if (h["owner"].lower(), h["repo"].lower(), int(h["number"])) == (owner, name, pr):
            if "done" in h:
                return {"state": "done", "reason": h["done"], "due": None}
            if "paused" in h:
                return {"state": "paused", "reason": h["paused"], "due": None}
            return {"state": "idle", "reason": "", "due": h.get("dispatch-due")}
    return None


def lane_facts(x: dict, snap, status=None, grind_files=None, channel=dispatch_cli.channel, solo=ui_gh.solo):
    """Facts for one lane (schema in dispatch_run), or None when its repo has no fresh snapshot.
    ponytail: the poller reads the first 100 open issues; a lane past that would look closed."""
    if not snap or snap.get("stale") or snap.get("fetched_at") is None:
        return None
    data = snap.get("data") or {}
    issue = next((i for i in data.get("issues") or [] if i["n"] == x["n"]), None)
    f = {
        "issue_open": issue is not None,
        "refined": bool(issue and "refined" in issue.get("labels", [])),
        # ponytail: the poller names blockers by number, so they are taken to be in the lane's repo
        "blockers_open": [
            dr.key(x["repo"], b["n"]) for b in (issue or {}).get("blocked_by", []) if b["state"] == "OPEN"
        ],
    }
    ch = channel(x["repo"])
    f["slack"], f["channel"] = ch is not None, ch or None
    f["solo"] = solo(x["repo"])
    p = _pr_of(x, data, issue)
    if p:
        extra = next((o for o in data.get("open_prs") or [] if o["n"] == p["n"]), {})
        f["pr"] = {
            **{k: p.get(k) for k in ("n", "url", "draft", "state", "ci", "conflict", "sha")},
            "approved": p.get("review") == "approved" or bool(extra.get("reviewer")),
        }
        f["grind"] = _grind(x["repo"], p["n"], grind_files)
    if x.get("handle") and status:
        try:
            f["agent"], f["limited_until"] = status(x["handle"])
        except Exception as e:  # noqa: BLE001 - an unreachable runner reads as "no news", not as gone
            warn(f"dispatch: status of {x['repo']}#{x['n']}: {e}")
    return f


# --------------------------------------------------------------------------- tick


def repos() -> set:
    """Repos with a live dispatch lane: the poller keeps them fresh."""
    return {
        x["repo"]
        for d in dr.list_all()
        if d["state"] in LIVE
        for x in d["lanes"].values()
        if x["stage"] in dr.ACTIVE or x["stage"] == "queued"
    }


def _busy(d: dict) -> bool:
    """A finished dispatch still needs ticks for end actions, outboxes and a QA session's new issues."""
    if d["state"] in LIVE:
        return True
    if d["state"] == "done":
        return bool(d.get("end_requests") or d.get("qa") or any(x.get("outbox") for x in d["lanes"].values()))
    return False


def tick_one(
    did: str,
    snapshot,
    runner_for=dispatch_runners.for_dispatch,
    resolve=dispatch_cli.resolve,
    resolve_issues=dispatch_cli.resolve_issues,
    now=None,
    grind_files=None,
) -> list:
    now = now or time.time()
    with dr.locked(did):
        d = dr.load(did)
        if not _busy(d):
            return []
        runner = runner_for(d)
        if now - (d.get("synced_at") or 0) >= SYNC_SECONDS:
            d["synced_at"] = now
            try:
                listed = d.get("issues")
                kids = resolve_issues(listed)["children"] if listed else resolve(d["epic"])["children"]
                for k in dr.sync_lanes(d, kids):
                    dr.event(d, k, "lane", "joined the dispatch")
            except Exception as e:  # noqa: BLE001
                warn(f"dispatch {did}: cannot re-read the {'issues' if d.get('issues') else 'epic'}: {e}")
        files = list(ui_grind._state_files()) if grind_files is None else grind_files
        facts = {}
        for k, x in d["lanes"].items():
            if x["stage"] in dr.ACTIVE or x["stage"] == "queued":
                f = lane_facts(x, snapshot(x["repo"]), runner.status, files)
                if f is not None:
                    facts[k] = f
        return dr.tick(d, facts, runner, now=now, notify=notify)


def tick_all(snapshot) -> None:
    for d in dr.list_all():
        if _busy(d):
            try:
                tick_one(d["id"], snapshot)
            except Exception as e:  # noqa: BLE001 - one broken dispatch must not stop the others
                warn(f"dispatch {d['id']} tick failed: {e}")


def start_timer(snapshot, interval=TICK_SECONDS) -> threading.Thread:
    def loop():
        while True:
            tick_all(snapshot)
            time.sleep(interval)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t


# --------------------------------------------------------------------------- notices


def notify(d: dict, k, kind: str, text: str) -> None:
    x = d["lanes"].get(k) if k else None
    title = f"aiw: {k or d['epic'] or d['title']}"
    owner, _, name = (x["repo"] if x else dr.dispatch_repo(d)).partition("/")
    ui_notify.notify(
        "dispatch",
        {
            "repo": f"{owner}/{name}",
            "note": f"{title} {text}",
            "link": {"owner": owner, "repo": name, "issue": x["n"] if x else None},
        },
    )


# --------------------------------------------------------------------------- Inbox and API


def inbox_items(dispatches: list) -> list:
    """Inbox rows (ui_inbox's item shape) for lanes that need the user and finished dispatches."""
    out = []
    for d in dispatches:
        if d["state"] not in LIVE and not (d["state"] == "done" and not d.get("seen_done")):
            continue
        for k, x in d["lanes"].items():
            row = {
                "repo": x["repo"],
                "at": None,
                "dispatch": d["id"],
                "lane": k,
                "issue": x["n"],
                "title": x.get("title", ""),
                "stage": x["stage"],
                "pr": x.get("pr"),
            }
            if x.get("needs_you"):
                out.append(
                    {
                        "key": f"dispatch:{d['id']}:{k}:needs",
                        "group": "answer",
                        "type": "dispatch_lane",
                        "reason": x["needs_you"],
                        **row,
                    }
                )
            elif x.get("held"):
                out.append(
                    {
                        "key": f"dispatch:{d['id']}:{k}:held",
                        "group": "fix",
                        "type": "dispatch_lane",
                        "reason": x["held"],
                        **row,
                    }
                )
            elif x["stage"] == "awaiting_merge":
                out.append(
                    {
                        "key": f"dispatch:{d['id']}:{k}:merge",
                        "group": "decide",
                        "type": "dispatch_lane",
                        "reason": f"PR #{x.get('pr')} is ready to merge",
                        **row,
                    }
                )
            elif (x.get("limited_until") or 0) > time.time():
                out.append(
                    {
                        "key": f"dispatch:{d['id']}:{k}:limited",
                        "group": "wait",
                        "type": "dispatch_lane",
                        "reason": "Claude usage limit",
                        "resets_at": x["limited_until"],
                        **row,
                    }
                )
        if d["state"] == "done":
            out.append(
                {
                    "key": f"dispatch:{d['id']}:done",
                    "group": "decide",
                    "type": "dispatch_done",
                    "repo": dr.dispatch_repo(d),
                    "at": None,
                    "dispatch": d["id"],
                    "epic": d["epic"],
                    "title": d.get("title", ""),
                    "feature_branch": d["settings"].get("feature_branch"),
                    "final_prs": d.get("final_prs") or {},
                }
            )
    return out


DUPLICATED = ("pr_ready", "pr_conflict", "grind_paused", "session_failed")


def drop_owned(items: list, dispatches: list) -> list:
    """Inbox rows minus the generic ones (PR ready or conflicting, grind paused, session failed) for an issue
    or PR a live dispatch lane owns: the lane's own row carries that, with the dispatch's action."""
    owned = set()
    for d in dispatches:
        if d["state"] in LIVE:
            for x in d["lanes"].values():
                if x["stage"] in dr.ACTIVE:
                    owned.add((x["repo"].lower(), "issue", x["n"]))
                    if x.get("pr"):
                        owned.add((x["repo"].lower(), "pr", x["pr"]))

    def mine(i):
        repo = (i.get("repo") or "").lower()
        link = i.get("link") if isinstance(i.get("link"), dict) else {}
        n = i.get("issue") or link.get("issue")
        return (repo, "issue", n) in owned or (repo, "pr", i.get("pr")) in owned

    return [i for i in items if not (i.get("type") in DUPLICATED and mine(i))]


def _usage(x: dict) -> dict:
    """Cost and tokens of a lane's headless sessions (herdr tabs report none), and its elapsed seconds.
    ponytail: a session's cost is its last result event's; resumed turns may undercount."""
    cost, tokens = 0.0, 0
    for h in x.get("handles") or []:
        try:
            rec = ui_sessions.load(h["session"]) if isinstance(h, dict) and h.get("session") else None
        except ValueError:  # a session record that is gone or malformed costs nothing
            rec = None
        if rec:
            cost += rec.get("cost") or 0
            t = rec.get("tokens") or {}
            tokens += (t.get("input") or 0) + (t.get("output") or 0)
    start = x.get("started_at")
    return {
        "cost": round(cost, 4),
        "tokens": tokens,
        "seconds": int((x.get("ended_at") or time.time()) - start) if start else 0,
    }


def public(d: dict, full: bool = False) -> dict:
    lanes = []
    for k, x in sorted(d["lanes"].items(), key=lambda kv: (kv[1]["n"], kv[0])):
        lanes.append(
            {
                "key": k,
                **{
                    f: x.get(f)
                    for f in (
                        "repo",
                        "n",
                        "title",
                        "deps",
                        "stage",
                        "pr",
                        "needs_you",
                        "held",
                        "gate",
                        "skip_reason",
                        "paused",
                        "hold_merge",
                        "limited_until",
                        "started_at",
                        "ended_at",
                    )
                },
                "session": (x.get("handle") or {}).get("session"),
                "tab": (x.get("handle") or {}).get("tab"),
                "usage": _usage(x),
            }
        )
    tot = {f: sum(lane["usage"][f] for lane in lanes) for f in ("cost", "tokens")}
    out = {
        f: d.get(f)
        for f in ("id", "epic", "issues", "title", "runner", "state", "settings", "created_at", "ended_at", "final_prs")
    }
    out.update(lanes=lanes, totals={**tot, "seconds": int((d.get("ended_at") or time.time()) - d["created_at"])})
    if full:
        out["events"] = d.get("events") or []
    return out


def read_lane(did: str, k: str) -> dict:
    """What the lane session shows now: a herdr pane's text, or a headless session's id to open."""
    d = dr.load(did)
    x = d["lanes"].get(k)
    if x is None or not x.get("handle"):
        raise ValueError(f"lane {k} has no session")
    if d["runner"] == "headless":
        return {"session": x["handle"]["session"]}
    return {"text": dispatch_runners.for_dispatch(d).read(x["handle"])}


def seen(did: str) -> dict:
    with dr.locked(did):
        d = dr.load(did)
        d["seen_done"] = True
        dr.save(d)
        return public(d)


def _target(body: dict) -> tuple:
    """('epic', text) or ('issues', refs): exactly one of the two, issues a list of strings."""
    epic, issues = body.get("epic"), body.get("issues")
    if (epic is None) == (issues is None):
        raise ValueError("give either epic or issues")
    if epic is not None:
        return "epic", str(epic or "")
    if not isinstance(issues, list) or not all(isinstance(r, str) for r in issues):
        raise ValueError("issues must be a list of owner/repo#N strings")
    dispatch_cli.parse_issues(issues)  # the count and one-repo rules, before any GitHub call
    return "issues", list(dict.fromkeys(issues))


def _settings(body: dict, kind: str) -> dict:
    s = dr.check_settings(
        {**dr.DEFAULTS, **{k: v for k, v in (body.get("settings") or {}).items() if k in dr.DEFAULTS}}
    )
    _check_account(s)
    if kind == "issues":
        dr._no_feature_branch(s)
    return s


def _check_account(s: dict) -> None:
    if s.get("account") is not None and s["account"] not in {c["label"] for c in ui_settings.load()["commands"]}:
        raise ValueError("account must be a label saved in Settings")


def set_settings(did: str, body: dict) -> dict:
    _check_account(body)
    return public(dr.set_settings(did, **body))


def start(body: dict) -> dict:
    """POST /api/dispatches: start a dispatch from the UI (headless lanes unless herdr is asked for)."""
    runner = body.get("runner") or "headless"
    kind, target = _target(body)
    s = _settings(body, kind)
    if kind == "issues":
        return public(dispatch_cli.start(None, runner, s, body.get("workspace"), issues=target))
    return public(dispatch_cli.start(target, runner, s, body.get("workspace")))


def plan(body: dict) -> dict:
    runner = body.get("runner") or "headless"
    kind, target = _target(body)
    s = _settings(body, kind)
    if kind == "issues":
        return dispatch_cli.preview(dispatch_cli.resolve_issues(target, bodies=True), s, runner)
    return dispatch_cli.preview(dispatch_cli.resolve(target, bodies=True), s, runner)
