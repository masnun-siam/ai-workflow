"""Main-tree runs: `aiw maintree acquire|status|release`.

A run started with --no-worktree works in the repo's primary checkout, so only one may
hold it at a time. One record per repo, <data_dir>/maintree/<owner>-<repo>.json:
  {"holder": {"issue", "grind", "since"} | null, "queue": [{"issue", "grind", "seen"}]}

Nothing ticks this. The holder's phase is read from facts that already exist (the run
Ledger, the pr-grind state file, `ci.snapshot`) whenever someone asks, and a done holder
is cleared by the next `acquire`. Every waiter polls, so somebody always asks.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import time

import ci
from shared import atomic_write_text, data_dir, parse_pr_ref, run_dir_for

STALE = 900  # a waiter that has not polled for 15 min (Ctrl-C, killed session) loses its place
POLL = 30


def _path(slug: str) -> str:
    owner, _, repo = slug.lower().partition("/")
    return os.path.join(data_dir(), "maintree", f"{owner}-{repo}.json")


@contextlib.contextmanager
def _locked(slug: str):
    os.makedirs(os.path.dirname(_path(slug)), exist_ok=True)
    with open(_path(slug) + ".lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def load(slug: str) -> dict:
    try:
        with open(_path(slug), encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        rec = None
    return rec if isinstance(rec, dict) else {"holder": None, "queue": []}


def _save(slug: str, rec: dict) -> None:
    os.makedirs(os.path.dirname(_path(slug)), exist_ok=True)
    atomic_write_text(_path(slug), json.dumps(rec, indent=2))


def _ledger(slug: str, issue: int):
    path = os.path.join(run_dir_for(os.path.join(data_dir(), "runs"), slug, issue), "run.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _grind_header(owner: str, repo: str, number: int):
    import ui_runner  # lazy: the UI module is heavy and only its header parser is needed
    path = os.path.join(data_dir(), "pr-grind", f"{owner}-{repo}-{number}.md")
    return ui_runner._header(path) if os.path.isfile(path) else None


def phase(slug: str, holder: dict) -> tuple[str, str | None]:
    """(running|grinding|ci|done|blocked, reason when blocked)."""
    # ponytail: a killed session leaves its ledger "running" and so the holder too; release is the way out
    run = _ledger(slug, holder["issue"])
    if not run or run.get("status") == "running":
        return "running", None
    if run.get("status") != "done":
        return "blocked", f"run {run.get('status')}"
    pr = (run.get("context") or {}).get("pr")
    if not pr:
        return "blocked", "run finished without a PR"
    owner, repo, number = parse_pr_ref(pr)
    if holder.get("grind"):
        if (run.get("context") or {}).get("grind") == "skipped":
            return "blocked", "grind skipped (degraded finish or hold) — release when done"
        h = _grind_header(owner, repo, number)
        if h is None or ("done" not in h and "paused" not in h):
            return "grinding", None
        if "done" not in h:
            return "blocked", "grind paused: " + h["paused"]
        if "approved" not in h["done"]:
            return "blocked", "grind ended: " + h["done"]
    state = ci.snapshot(owner, repo, number)["state"]
    if state == "pending":
        return "ci", None
    if state == "red":
        return "blocked", "CI is red"
    return "done", None


def acquire(slug: str, issue: int, grind: bool) -> dict:
    with _locked(slug):
        rec, now = load(slug), time.time()
        rec["queue"] = [q for q in rec["queue"] if now - q["seen"] < STALE]
        h = rec["holder"]
        if h and h["issue"] == issue:
            h["grind"] = h["grind"] or grind
            _save(slug, rec)
            return {"granted": True}
        ph, why = phase(slug, h) if h else ("free", None)
        if ph == "done":
            rec["holder"] = h = None
        mine = next((q for q in rec["queue"] if q["issue"] == issue), None)
        if mine:
            mine["seen"], mine["grind"] = now, mine["grind"] or grind
        else:
            mine = {"issue": issue, "grind": grind, "seen": now}
            rec["queue"].append(mine)
        if h is None and rec["queue"][0] is mine:
            rec["queue"].pop(0)
            rec["holder"] = {"issue": issue, "grind": mine["grind"], "since": now}
            _save(slug, rec)
            return {"granted": True}
        _save(slug, rec)
        ahead = h["issue"] if h else rec["queue"][0]["issue"]
        return {"granted": False, "ahead": ahead, "phase": ph if h else "queued", "reason": why,
                "position": rec["queue"].index(mine) + 1}


def release(slug: str, issue: int | None = None) -> bool:
    with _locked(slug):
        rec = load(slug)
        h = rec["holder"]
        if not h or (issue is not None and h["issue"] != issue):
            return False
        rec["holder"] = None
        _save(slug, rec)
        return True


def cancel(slug: str, issue: int) -> None:
    with _locked(slug):
        rec = load(slug)
        rec["queue"] = [q for q in rec["queue"] if q["issue"] != issue]
        _save(slug, rec)


def status(slug: str) -> dict:
    rec = load(slug)
    h = rec["holder"]
    if h:
        ph, why = phase(slug, h)
        h = {**h, "phase": ph, "reason": why}
    return {"holder": h, "queue": rec["queue"]}


def for_issue(owner: str, repo: str, issue: int):
    slug = f"{owner}/{repo}"
    rec = load(slug)
    h = rec["holder"]
    if h and h["issue"] == issue:
        ph, why = phase(slug, h)
        return {"role": "holder", "phase": ph, "reason": why}
    for i, q in enumerate(rec["queue"]):
        if q["issue"] == issue:
            ahead = h["issue"] if h else rec["queue"][0]["issue"]
            return {"role": "queued", "position": i + 1, "ahead": ahead}
    return None


def _line(res: dict) -> str:
    why = f": {res['reason']}" if res.get("reason") else ""
    return f"waiting for #{res['ahead']} ({res['phase']}{why}) — position {res['position']}"


def cmd_acquire(args) -> None:
    deadline = time.monotonic() + args.wait
    last = None
    try:
        while True:
            res = acquire(args.slug, args.issue, args.grind)
            if res["granted"]:
                print("granted")
                return
            if _line(res) != last:
                last = _line(res)
                print(last, flush=True)
            if time.monotonic() + POLL > deadline:
                return  # still waiting: exit 0, the caller re-runs and keeps its place
            time.sleep(POLL)
    except KeyboardInterrupt:
        cancel(args.slug, args.issue)
        print("cancelled")
        raise SystemExit(130)


def cmd_status(args) -> None:
    print(json.dumps(status(args.slug), indent=2))


def cmd_release(args) -> None:
    print("released" if release(args.slug, args.issue) else "nothing to release")


def register(sub, add) -> None:
    p = sub.add_parser("maintree", help="one main-tree run per repo: acquire, status, release")
    ops = p.add_subparsers(dest="op", required=True)
    q = ops.add_parser("acquire", help="take the main tree or wait for it (exit 0 either way)")
    q.add_argument("slug")
    q.add_argument("issue", type=int)
    q.add_argument("--grind", action="store_true", help="this run's PR will be grinded")
    q.add_argument("--wait", type=int, default=0, help="seconds to keep polling before returning `waiting …`")
    q.set_defaults(func=cmd_acquire)
    q = ops.add_parser("status")
    q.add_argument("slug")
    q.set_defaults(func=cmd_status)
    q = ops.add_parser("release", help="free the main tree (the way out of a blocked holder)")
    q.add_argument("slug")
    q.add_argument("--issue", type=int)
    q.set_defaults(func=cmd_release)
