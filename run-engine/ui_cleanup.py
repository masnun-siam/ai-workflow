"""Clean up finished runs for the UI: remove the per-run worktree, run dir and linked sessions.

A target is one issue (`owner/repo#n`: its ledger run plus every linked session) or one
link-less session (`session:<id>`). Only terminal work is eligible: a ledger `done`, or a
run whose sessions are all stopped/failed/done. Live sessions and escalated ledgers are
never listed. `done` runs also lose their local branch, and their issue is closed when the
PR is merged. The main clone, checkouts.json and remote branches are never touched.
"""

from __future__ import annotations

import os
import time
import shutil

import ui_sessions
from shared import data_dir, gh_json, run
from ui_board import _resolve_owner_repo, load_projects, scan_records

# A ledger with no UI session may belong to a live CLI run; only offer it once untouched this long.
STALE_SECONDS = 3600
LIVE = ("starting", "running", "waiting", "limited")


def _git(cwd: str, *args: str):
    return run(["git", "-C", cwd, *args], timeout=60)


def _worktree_plan(ledger: dict) -> dict:
    """Paths recorded by `worktree create`, accepted only while they still have its exact shape."""
    ctx = ledger.get("context") if isinstance(ledger.get("context"), dict) else {}
    issue, main, wt, branch = ledger.get("issue"), ctx.get("main_checkout"), ctx.get("worktree"), ctx.get("branch")
    out = {"main": None, "worktree": None, "branch": None, "pr": ctx.get("pr")}
    if isinstance(main, str) and isinstance(wt, str) and isinstance(issue, int) and os.path.isdir(main):
        expect = os.path.abspath(os.path.join(main, "..", f"wt-issue-{issue}"))
        if os.path.abspath(wt) == expect:
            out["main"], out["worktree"] = main, expect
            if isinstance(branch, str) and branch.startswith(f"issue-{issue}-"):
                out["branch"] = branch
    return out


def _flags(plan: dict, with_unpushed: bool) -> list:
    """What cleanup would destroy: uncommitted files, plus (only when the branch is deleted) unpushed commits."""
    flags = []
    wt = plan["worktree"]
    if wt and os.path.isdir(wt) and (_git(wt, "status", "--porcelain").stdout or "").strip():
        flags.append("uncommitted changes")
    br = plan["branch"]
    if with_unpushed and br and _git(plan["main"], "rev-parse", "--verify", "-q", f"refs/heads/{br}").returncode == 0:
        n = (_git(plan["main"], "rev-list", "--count", br, "--not", "--remotes").stdout or "").strip()
        if n.isdigit() and int(n) > 0:
            flags.append(f"{n} unpushed commit(s)")
    return flags


def _pr_merged(pr):
    """True/False from gh, None when there is no PR or gh could not say."""
    if not (isinstance(pr, str) and pr.startswith("https://")):
        return None
    state, _ = gh_json(["pr", "view", pr, "--json", "state", "-q", ".state"], timeout=30)
    return state == "MERGED" if isinstance(state, str) else None


def _link_key(s: dict):
    link = s.get("link") if isinstance(s.get("link"), dict) else {}
    o, r, n = link.get("owner"), link.get("repo"), link.get("issue")
    return (o, r, n) if isinstance(o, str) and isinstance(r, str) and isinstance(n, int) else None


def find_targets() -> list:
    """Eligible targets: [{key, owner, repo, issue, status, sessions, run_dirs, plan, label}]."""
    runs_dir = os.path.join(data_dir(), "runs")
    projects = load_projects()
    by_key = {}  # (owner, repo, issue) -> {"sessions": [...], "records": [...]}
    loose = []
    for s in ui_sessions.list_sessions():
        k = _link_key(s)
        if k:
            by_key.setdefault(k, {"sessions": [], "records": []})["sessions"].append(s)
        else:
            loose.append(s)
    for rec in scan_records():
        o, r = _resolve_owner_repo(rec["ledger"], rec["dir_name"], projects)
        by_key.setdefault((o, r, rec["ledger"]["issue"]), {"sessions": [], "records": []})["records"].append(rec)

    out = []
    for (o, r, n), g in sorted(by_key.items(), key=lambda kv: str(kv[0])):
        if any(s.get("status") in LIVE for s in g["sessions"]):
            continue
        latest = max(g["records"], key=lambda x: x["mtime"])["ledger"] if g["records"] else None
        done = bool(latest and latest.get("status") == "done")
        if latest and latest.get("status") == "escalated":
            # Escalated means waiting on a human, so it is kept, unless GitHub says the PR already merged.
            if _pr_merged((latest.get("context") or {}).get("pr")) is not True:
                continue
            done = True
        if not done and not g["sessions"] and time.time() - max(x["mtime"] for x in g["records"]) < STALE_SECONDS:
            continue  # unfinished ledger with no UI session: a CLI run may still be live until it goes quiet
        out.append({
            "key": f"{o}/{r}#{n}", "owner": o, "repo": r, "issue": n, "label": None,
            "status": "done" if done else "stopped",
            "sessions": [s["id"] for s in g["sessions"]],
            "run_dirs": [os.path.join(runs_dir, x["dir_name"]) for x in g["records"]],
            "plan": _worktree_plan(latest) if latest else None,
        })
    for s in loose:
        if s.get("status") not in LIVE:
            out.append({"key": f"session:{s['id']}", "owner": None, "repo": None, "issue": None,
                        "label": s.get("command") or "session", "status": "stopped",
                        "sessions": [s["id"]], "run_dirs": [], "plan": None})
    return out


def describe(t: dict) -> dict:
    """Preview shape for the dialog: adds the dirty/unpushed flags and PR merge state."""
    plan, done = t["plan"], t["status"] == "done"
    return {
        "key": t["key"], "owner": t["owner"], "repo": t["repo"], "issue": t["issue"], "label": t["label"],
        "status": t["status"],
        "branch": plan["branch"] if plan else None,
        "has_worktree": bool(plan and plan["worktree"] and os.path.isdir(plan["worktree"])),
        "pr_merged": _pr_merged(plan["pr"]) if plan and done else None,
        "flags": _flags(plan, done) if plan else [],
        "sessions": len(t["sessions"]),
    }


def clean(t: dict, force: bool) -> dict:
    """Clean one target: {key, ok, notes[], error?, flagged?}. Never raises; stops before deleting data on a git failure."""
    key, plan, done, notes = t["key"], t["plan"], t["status"] == "done", []
    flags = _flags(plan, done) if plan else []
    if flags and not force:
        return {"key": key, "ok": False, "flagged": flags, "error": "unsaved work: " + ", ".join(flags)}

    if done and plan:
        merged = _pr_merged(plan["pr"])
        if merged:
            slug = f"{t['owner']}/{t['repo']}"
            state, _ = gh_json(["issue", "view", str(t["issue"]), "-R", slug, "--json", "state", "-q", ".state"], timeout=30)
            if state == "OPEN":
                p = run(["gh", "issue", "close", str(t["issue"]), "-R", slug, "--reason", "completed",
                         "--comment", "Closed by aiw ui cleanup: the linked PR is merged."], timeout=30)
                notes.append("issue closed" if p.returncode == 0 else "could not close issue: " + (p.stderr or "").strip()[:200])
        else:
            notes.append("issue left open: PR " + ("not merged" if merged is False else "state unknown"))

    if plan and plan["worktree"]:
        wt, main = plan["worktree"], plan["main"]
        if os.path.isdir(wt):
            p = _git(main, "worktree", "remove", "--force", wt)
            if p.returncode != 0:
                return {"key": key, "ok": False, "notes": notes,
                        "error": "git worktree remove failed: " + (p.stderr or "").strip()[:300]}
        _git(main, "worktree", "prune")
        if done and plan["branch"] and _git(main, "rev-parse", "--verify", "-q", f"refs/heads/{plan['branch']}").returncode == 0:
            p = _git(main, "branch", "-D", plan["branch"])
            if p.returncode != 0:
                notes.append("could not delete branch: " + (p.stderr or "").strip()[:200])

    for sid in t["sessions"]:
        shutil.rmtree(ui_sessions.session_dir(sid), ignore_errors=True)
    for d in t["run_dirs"]:
        shutil.rmtree(d, ignore_errors=True)
    return {"key": key, "ok": True, "notes": notes}
