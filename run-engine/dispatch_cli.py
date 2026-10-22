"""`aiw dispatch`: plan, start, watch and steer epic dispatches (dispatch_run). Stdlib only.

The `aiw ui` server ticks every running dispatch; these verbs only read and edit the dispatch records,
so the herdr-dispatch skill and the UI see and steer the same dispatches.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time

import dispatch
import dispatch_run as dr
import ui_settings
from shared import data_dir, run

UI_PORT = 8420
WATCH_KINDS = ("needs_you", "held", "awaiting_merge", "finished", "end")
_EPIC = re.compile(r"^(?:([\w.-]+/[\w.-]+)#)?(\d+)$")

CHILDREN = """
query($owner: String!, $name: String!, $n: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $n) {
      title
      subIssues(first: 100) {
        nodes {
          number title state repository { nameWithOwner }
          labels(first: 20) { nodes { name } }
          blockedBy(first: 20) { nodes { number state repository { nameWithOwner } } }
        }
      }
    }
  }
}
"""


def _gh(argv):
    return run(["gh", *argv], timeout=60)


def parse_epic(text: str, gh=_gh) -> tuple:
    """'owner/repo#n' or 'n' (the repo of the current directory) -> (repo, n)."""
    m = _EPIC.match((text or "").strip())
    if not m:
        raise ValueError(f"epic must be owner/repo#N or N, got {text!r}")
    repo = m.group(1)
    if not repo:
        p = gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
        repo = (p.stdout or "").strip()
        if p.returncode != 0 or not repo:
            raise ValueError("not in a GitHub checkout: give the epic as owner/repo#N")
    return repo, int(m.group(2))


def children_from(response: dict) -> tuple:
    """GraphQL CHILDREN response -> (epic title, children for dispatch_run, open blockers outside the set)."""
    issue = (((response or {}).get("data") or {}).get("repository") or {}).get("issue")
    if not isinstance(issue, dict):
        raise ValueError("epic not found")
    nodes = [x for x in (issue.get("subIssues") or {}).get("nodes") or [] if x.get("state") == "OPEN"]
    keys = {dr.key(x["repository"]["nameWithOwner"], x["number"]) for x in nodes}
    out, outside = [], {}
    for x in nodes:
        k = dr.key(x["repository"]["nameWithOwner"], x["number"])
        deps, ext = [], []
        for b in (x.get("blockedBy") or {}).get("nodes") or []:
            bk = dr.key(b["repository"]["nameWithOwner"], b["number"])
            if bk in keys:
                deps.append(bk)
            elif b.get("state") == "OPEN":
                ext.append(bk)
        if ext:
            outside[k] = ext
        out.append(
            {
                "repo": x["repository"]["nameWithOwner"],
                "n": x["number"],
                "title": x.get("title") or "",
                "refined": any(lb.get("name") == "refined" for lb in (x.get("labels") or {}).get("nodes") or []),
                "deps": sorted(deps),
            }
        )
    return issue.get("title") or "", sorted(out, key=lambda c: (c["n"], c["repo"])), outside


def resolve(epic: str, gh=_gh) -> dict:
    repo, n = parse_epic(epic, gh)
    owner, name = repo.split("/")
    p = gh(["api", "graphql", "-f", f"query={CHILDREN}", "-f", f"owner={owner}", "-f", f"name={name}", "-F", f"n={n}"])
    if p.returncode != 0:
        raise ValueError(f"cannot read epic {repo}#{n}: {(p.stderr or p.stdout).strip()[:200]}")
    title, kids, outside = children_from(json.loads(p.stdout))
    return {"epic": f"{repo}#{n}", "title": title, "children": kids, "outside": outside}


def channel(repo: str):
    """The repo's Slack channel for grinding: the id from Settings, "" when channels.json maps it, None for none."""
    ch = ui_settings.repo_settings(repo).get("slack_channel")
    if ch:
        return ch
    try:
        with open(os.path.join(data_dir(), "channels.json"), encoding="utf-8") as f:
            mapped = (json.load(f).get("channels") or {}).get(repo)
    except (OSError, ValueError, AttributeError):
        mapped = None
    return "" if mapped else None


def preview(r: dict, settings: dict, runner: str) -> dict:
    p = dr.plan(r["children"])
    repos = sorted({c["repo"] for c in r["children"]})
    checkouts = {k.lower() for k in dispatch.read_checkouts()}
    for k, ext in r["outside"].items():
        p["warnings"].append(f"{k}: blocked by open {', '.join(ext)} outside the epic")
    for repo in repos:
        if runner == "herdr" and repo.lower() not in checkouts:
            p["warnings"].append(f"{repo}: no local checkout registered (aiw ui -> Repositories)")
        if settings.get("grind", "full") != "off" and channel(repo) is None:
            p["warnings"].append(f"{repo}: no Slack channel, its lanes skip grinding")
    return {"epic": r["epic"], "title": r["title"], "settings": settings, "runner": runner, "lanes": r["children"], **p}


def ensure_feature_branch(repo: str, branch: str, gh=_gh) -> bool:
    """Cut `branch` from the default branch on GitHub when missing. True when it was created."""
    if gh(["api", f"repos/{repo}/git/ref/heads/{branch}"]).returncode == 0:
        return False
    base = gh(["repo", "view", repo, "--json", "defaultBranchRef", "-q", ".defaultBranchRef.name"]).stdout.strip()
    sha = gh(["api", f"repos/{repo}/commits/{base}", "-q", ".sha"]).stdout.strip()
    p = gh(["api", f"repos/{repo}/git/refs", "-f", f"ref=refs/heads/{branch}", "-f", f"sha={sha}"])
    if p.returncode != 0 or not sha:
        raise ValueError(f"cannot create {branch} on {repo}: {(p.stderr or p.stdout).strip()[:200]}")
    return True


def ui_running(port: int = UI_PORT) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def start_ui() -> None:
    log = open(os.path.join(data_dir(), "ui.log"), "a")  # noqa: SIM115 - handed to the detached server
    route = os.path.join(os.path.dirname(os.path.abspath(__file__)), "route.py")
    subprocess.Popen([sys.executable, route, "ui"], stdout=log, stderr=log, start_new_session=True)


def _settings(a) -> dict:
    s = {
        "max": a.max,
        "grind": a.grind,
        "auto_merge": a.auto_merge,
        "feature_branch": a.feature_branch,
        "model": a.model,
        "effort": a.effort,
    }
    return dr.check_settings({**dr.DEFAULTS, **s})


def summary(d: dict) -> dict:
    lanes = [
        {
            k: x.get(k)
            for k in ("repo", "n", "title", "stage", "pr", "needs_you", "held", "gate", "skip_reason", "paused")
        }
        for x in sorted(d["lanes"].values(), key=lambda x: (x["n"], x["repo"]))
    ]
    return {k: d.get(k) for k in ("id", "epic", "runner", "state", "settings", "final_prs")} | {"lanes": lanes}


# --------------------------------------------------------------------------- verbs


def cmd_plan(a) -> None:
    print(json.dumps(preview(resolve(a.epic), _settings(a), a.runner), indent=1))


def start(epic: str, runner: str, s: dict, workspace=None, gh=_gh) -> dict:
    """Resolve the epic, cut the feature branch if asked, record the dispatch. The UI server ticks it."""
    if runner == "herdr" and not workspace:
        raise ValueError("the herdr runner needs a workspace id (herdr pane current)")
    r = resolve(epic, gh)
    if not r["children"]:
        raise ValueError(f"{r['epic']} has no open child issues")
    for repo in sorted({c["repo"] for c in r["children"]}) if s["feature_branch"] else []:
        ensure_feature_branch(repo, s["feature_branch"], gh)
    return dr.create(r["epic"], runner, s, r["children"], workspace=workspace, title=r["title"])


def cmd_start(a) -> None:
    d = start(a.epic, a.runner, _settings(a), a.workspace)
    if not ui_running():
        start_ui()
    print(
        json.dumps(
            {"id": d["id"], "lanes": len(d["lanes"]), "since": d["created_at"], "ui": f"http://127.0.0.1:{UI_PORT}"}
        )
    )


def cmd_ls(a) -> None:
    for d in dr.list_all():
        n = len(d["lanes"])
        closed = sum(1 for x in d["lanes"].values() if x["stage"] == "closed")
        print(f"{d['id']}  {d['state']:<9}  {d['epic']:<24}  {closed}/{n} closed  {d['runner']}")


def cmd_show(a) -> None:
    print(json.dumps(summary(dr.load(a.id)), indent=1))


def cmd_set(a) -> None:
    kv = {}
    for item in a.pairs:
        k, sep, v = item.partition("=")
        if not sep or k not in dr.DEFAULTS:
            raise ValueError(f"expected key=value with key in {sorted(dr.DEFAULTS)}, got {item!r}")
        kv[k] = (
            int(v) if k == "max" else (v.lower() in ("1", "true", "on", "yes")) if k == "auto_merge" else (v or None)
        )
    print(json.dumps(dr.set_settings(a.id, **kv)["settings"]))


def cmd_state(a) -> None:
    dr.set_state(a.id, {"pause": "paused", "resume": "running", "cancel": "cancelled"}[a.op])
    print(a.op + "d" if a.op != "cancel" else "cancelled")


def cmd_lane(a) -> None:
    d = dr.load(a.id)
    k = a.lane if "#" in a.lane else next((k for k, x in d["lanes"].items() if str(x["n"]) == a.lane), a.lane)
    dr.lane_action(a.id, k, a.action, a.text)
    print(f"{k}: {a.action}")


def cmd_end(a) -> None:
    dr.request_end(a.id, a.action)
    print(f"{a.action}: requested; the UI server runs it at its next tick")


def watch(did: str, since: float, timeout: float, interval: float = 10, sleep=time.sleep, clock=time.time) -> tuple:
    """New events after `since`, returned once one needs the user (or the dispatch ended, or timeout)."""
    end = clock() + timeout
    while True:
        d = dr.load(did)
        new = [e for e in d.get("events") or [] if e["at"] > since]
        if any(e["kind"] in WATCH_KINDS for e in new) or d["state"] in ("done", "cancelled") or clock() >= end:
            return new, d["state"]
        sleep(interval)


def cmd_watch(a) -> None:
    since = time.time() if a.since is None else a.since
    new, state = watch(a.id, since, a.timeout)
    for e in new:
        print(
            f"{time.strftime('%H:%M', time.localtime(e['at']))}  {e['lane'] or '-':<20}  {e['kind']:<14}  {e['text']}"
        )
    print(f"state={state} since={max([since] + [e['at'] for e in new])}")


def grind_mode(pr_url: str | None) -> str:
    """deep or simple: the dispatch that owns this PR decides, else Settings."""
    m = re.search(r"github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)", pr_url or "")
    if m:
        for d in dr.list_all():
            if d["state"] in ("running", "paused") and any(
                x["repo"].lower() == m.group(1).lower() and x.get("pr") == int(m.group(2)) for x in d["lanes"].values()
            ):
                return "simple" if d["settings"]["grind"] == "simple" else "deep"
    return ui_settings.grind_mode()


def register(sub, add) -> None:
    p = sub.add_parser("dispatch", help="run an epic's child issues as parallel lanes (herdr tabs or UI sessions)")
    ops = p.add_subparsers(dest="op", required=True)

    def flags(q):
        q.add_argument("epic", help="owner/repo#N, or N in the current checkout")
        q.add_argument("--runner", choices=("herdr", "headless"), default="herdr")
        q.add_argument("--workspace", help="herdr workspace id (herdr pane current)")
        q.add_argument("--max", type=int, default=dr.DEFAULTS["max"])
        q.add_argument("--grind", choices=dr.GRIND_MODES, default=dr.DEFAULTS["grind"])
        q.add_argument("--auto-merge", action="store_true")
        q.add_argument("--feature-branch", default=None, help="every lane's base, cut from the default branch")
        q.add_argument("--model", default=None)
        q.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"), default=None)

    q = ops.add_parser("plan", help="preview the lanes, waves and warnings; changes nothing")
    flags(q)
    q.set_defaults(func=cmd_plan)
    q = ops.add_parser("start", help="start a dispatch (and the aiw ui server that ticks it)")
    flags(q)
    q.set_defaults(func=cmd_start)
    ops.add_parser("ls", help="list dispatches").set_defaults(func=cmd_ls)
    q = ops.add_parser("show", help="print a dispatch as JSON")
    q.add_argument("id")
    q.set_defaults(func=cmd_show)
    q = ops.add_parser("set", help="edit settings live: max=3 grind=simple auto_merge=on model=opus")
    q.add_argument("id")
    q.add_argument("pairs", nargs="+")
    q.set_defaults(func=cmd_set)
    for name in ("pause", "resume", "cancel"):
        q = ops.add_parser(name, help=f"{name} the whole dispatch")
        q.add_argument("id")
        q.set_defaults(func=cmd_state, op=name)
    q = ops.add_parser("lane", help="act on one lane")
    q.add_argument("id")
    q.add_argument("lane", help="issue number, or owner/repo#N")
    q.add_argument("action", choices=dr.LANE_ACTIONS)
    q.add_argument("text", nargs="?", help="the message, for send")
    q.set_defaults(func=cmd_lane)
    q = ops.add_parser("watch", help="block until an event needs you; prints the events and the next --since")
    q.add_argument("id")
    q.add_argument("--since", type=float, default=None, help="from the last watch or start; default now")
    q.add_argument("--timeout", type=float, default=3000.0)
    q.set_defaults(func=cmd_watch)
    q = ops.add_parser("end", help="end-of-dispatch action: open-pr | qa | grind-pr")
    q.add_argument("id")
    q.add_argument("action", choices=dr.END_ACTIONS)
    q.set_defaults(func=cmd_end)
