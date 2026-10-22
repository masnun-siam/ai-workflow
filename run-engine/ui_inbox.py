"""Inbox data (FR-7): everything that needs the user, across repos -> /api/inbox. Pure over its inputs.

Inputs (plain data, no I/O):
  sessions        ui_sessions records
  panels          [{id, repo, artifact, state, round, max_rounds, approved, total, prd_status}], one per
                  peer-review panel (prd_status: the artifact's PRD status, None when it is not a PRD)
  grind_index     ui_grind.index() -> {"pr": {(owner, repo, pr): {state, round, reason?}}}
  flags           {repo: {issue: {uncommitted, unpushed}}}: merged issues whose cleanup was held back
  repos           [{slug, path}]: the registry
  snapshots       {repo: poller snapshot} for the watched repos
  gh              ui_gh.status()
  alive           session ids whose claude process is still running
  account_labels  {claude command: label}
  slug            session record -> owner/repo (ui_delivery._slug)
  watched         the repos the poller watches (default: those in `snapshots`); `stale` is drawn from them
  repo            only this repo's items (and the repo-less ones: gh_auth)
  settings        {repo: ui_settings.repo_settings}: auto_grind and issue_grind decide pr_ready (merge_ready)
  solo            {repo: bool}: the user owns the repo, so its PRs need no approval

Result: {items, stale}. A repo whose snapshot is missing or stale is in `stale` and contributes no
poller-derived items (pr_ready, a PR's issue number); sessions, panels, grinds, cleanups and the registry
are local state and always count. Item: {key, group, type, repo, at, ...fields}; `key` is stable across
polls, `at` an ISO time or None. group is block | answer | decide | fix | setup | wait; types:
  block   gh_auth {error}
  answer  question {session_id, command, link, round_id, questions, process_alive}
  decide  review_cap {prd_path, panel, round, max_rounds, note}, review_approved {prd_path, panel},
          pr_ready {pr, issue, title, url, reviewer, checks}
  fix     grind_paused {pr, issue, round, reason}, pr_conflict {pr, issue, title, url}, session_failed {session_id, command, link, error},
          needs_cleanup {issue, uncommitted, unpushed}
  setup   repo_unpublished {slug, path}
  wait    limited {session_id, command, account, resets_at, auto_resume}, queued {session_id, command, reason}
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

GROUPS = ("block", "answer", "decide", "fix", "setup", "wait")


def grind_on(settings, issue) -> bool:
    """An issue's grinding switch, else the repo's Auto-grind (also the rule for a PR with no issue)."""
    s = settings or {}
    return (s.get("issue_grind") or {}).get(issue, s.get("auto_grind") is True)


def merge_ready(pr, grind, on: bool, solo: bool) -> bool:
    """Does an open PR get Merge? Not a draft, no conflicts with its base, CI green, GitHub approved it unless the user owns the repo
    (`solo`), and with grinding on its grind is done (stopped from the UI counts)."""
    if not pr or pr.get("draft") or pr.get("ci") != "success" or pr.get("conflict"):
        return False
    if on and (grind or {}).get("state") != "done":
        return False
    return pr.get("review") == "approved" or solo


def _prd_path(artifact: str):
    i = str(artifact).find("docs/prds/")
    return str(artifact)[i:] if i >= 0 else None


def _panel_at(panel_id: str):
    try:  # p-YYYYMMDDTHHMMSSZ-xxxxxx
        return datetime.strptime(panel_id[2:17], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return None


_STAMP = re.compile(r"^\s*(\d{4}-\d\d-\d\dT[\d:.]+(?:Z|[+-]\d\d:\d\d)?) — ")


def split_reason(reason):
    """A grind reason may lead with "<ISO time> — ": (at, text)."""
    m = _STAMP.match(reason) if isinstance(reason, str) else None
    return (m.group(1), reason[m.end() :]) if m else (None, reason)


def _ts(at) -> float:
    try:
        return datetime.fromisoformat(str(at).replace("Z", "+00:00")).timestamp() if at else 0.0
    except ValueError:
        return 0.0


def build(
    *,
    sessions,
    panels,
    grind_index,
    flags,
    repos,
    snapshots,
    gh,
    alive=(),
    account_labels=None,
    slug=lambda rec: str(rec.get("repo") or ""),
    watched=None,
    repo=None,
    settings=None,
    solo=None,
) -> dict:
    items = []

    def add(key, group, typ, at, repo_, **fields):
        items.append({"key": key, "group": group, "type": typ, "repo": repo_, "at": at, **fields})

    snaps = {k.lower(): v for k, v in (snapshots or {}).items()}
    fresh = {k for k, v in snaps.items() if not v.get("stale") and v.get("fetched_at") is not None}
    names = {r["slug"].lower(): r["slug"] for r in repos or []}  # lowercase -> the registered spelling

    if gh and gh.get("ok") is False:
        add("gh_auth", "block", "gh_auth", None, None, error=gh.get("error"))

    # a newer session with the same command in the same repo has taken over a failure
    newest = {}
    for r in sessions or []:
        k = (slug(r), r.get("command"))
        newest[k] = max(newest.get(k, ""), r.get("started_at") or "")
    for r in sessions or []:
        sid, status, where = r.get("id"), r.get("status"), slug(r)
        base = {"session_id": sid, "command": r.get("command")}
        pq = r.get("pending_question")
        if status == "waiting" and isinstance(pq, dict) and pq.get("status") == "pending":
            add(
                f"question:{sid}",
                "answer",
                "question",
                r.get("started_at"),
                where,
                **base,
                link=r.get("link"),
                round_id=pq.get("id"),
                questions=pq.get("questions") or [],
                process_alive=sid in set(alive),
            )
        elif status == "failed" and r.get("panel_role") != "lens":
            if (r.get("started_at") or "") >= newest.get((where, r.get("command")), ""):
                add(
                    f"failed:{sid}",
                    "fix",
                    "session_failed",
                    r.get("ended_at"),
                    where,
                    **base,
                    link=r.get("link"),
                    error=r.get("error"),
                )
        elif status == "limited":
            cmd = r.get("claude_cmd")
            add(
                f"limited:{sid}",
                "wait",
                "limited",
                r.get("started_at"),
                where,
                **base,
                account=(account_labels or {}).get(cmd, cmd),
                resets_at=r.get("limit_resets_at"),
                auto_resume=r.get("auto_resume") is True,
            )
        elif status == "queued":
            add(f"queued:{sid}", "wait", "queued", r.get("started_at"), where, **base, reason=r.get("note"))

    newest_panel = {}  # one panel per artifact: the newest (ids start with a timestamp)
    for p in sorted(panels or [], key=lambda p: p["id"]):
        newest_panel[p["artifact"]] = p
    for p in newest_panel.values():
        prd = _prd_path(p["artifact"])
        if prd is None or p.get("prd_status") == "Approved":
            continue  # not a PRD, or already approved (the panel's job is done)
        where = names.get(str(p["repo"]).lower(), p["repo"])
        if p["state"] == "cap reached":
            add(
                f"review_cap:{p['id']}",
                "decide",
                "review_cap",
                _panel_at(p["id"]),
                where,
                prd_path=prd,
                panel=p["id"],
                round=p["round"],
                max_rounds=p["max_rounds"],
                note=f"{p.get('approved', 0)} of {p.get('total', 0)} lenses approve at round {p['round']}",
            )
        elif p["state"] == "approved":
            add(
                f"review_approved:{p['id']}",
                "decide",
                "review_approved",
                _panel_at(p["id"]),
                where,
                prd_path=prd,
                panel=p["id"],
            )

    for (owner, name, pr), g in sorted(((grind_index or {}).get("pr") or {}).items()):
        where = names.get(f"{owner}/{name}", f"{owner}/{name}")
        if g.get("state") != "paused":
            continue
        data = (snaps.get(where.lower()) or {}).get("data") or {}
        issue = None
        if where.lower() in fresh:
            if not any(p["n"] == pr for p in data.get("open_prs") or []):
                continue  # the PR is closed or merged: nothing left to unpause
            issue = next((i["n"] for i in data.get("issues") or [] if any(p["n"] == pr for p in i["prs"])), None)
        at, reason = split_reason(g.get("reason"))
        add(
            f"grind:{where}#{pr}",
            "fix",
            "grind_paused",
            at,
            where,
            pr=pr,
            issue=issue,
            round=g.get("round"),
            reason=reason,
        )

    for where, by_issue in sorted((flags or {}).items()):
        for n, f in sorted(by_issue.items()):
            add(
                f"cleanup:{where}#{n}",
                "fix",
                "needs_cleanup",
                None,
                where,
                issue=n,
                uncommitted=f.get("uncommitted") or [],
                unpushed=f.get("unpushed") or [],
            )

    for r in repos or []:
        if r["slug"].startswith("local/"):
            add(
                f"unpublished:{r['slug']}",
                "setup",
                "repo_unpublished",
                None,
                r["slug"],
                slug=r["slug"],
                path=r.get("path"),
            )

    for k in sorted(fresh):
        where = names.get(k, k)
        data = snaps[k].get("data") or {}
        by_pr = {p["n"]: i["n"] for i in data.get("issues") or [] for p in i["prs"]}
        owner, _, name = k.partition("/")
        st = next((v for r, v in (settings or {}).items() if r.lower() == k), None)
        alone = next((v for r, v in (solo or {}).items() if r.lower() == k), False)
        for p in data.get("open_prs") or []:
            if p.get("conflict"):
                add(
                    f"pr_conflict:{where}#{p['n']}",
                    "fix",
                    "pr_conflict",
                    None,
                    where,
                    pr=p["n"],
                    issue=by_pr.get(p["n"]),
                    title=p.get("title"),
                    url=p.get("url"),
                )
                continue
            g = ((grind_index or {}).get("pr") or {}).get((owner, name, p["n"]))
            if merge_ready(p, g, grind_on(st, by_pr.get(p["n"])), alone):
                add(
                    f"pr_ready:{where}#{p['n']}",
                    "decide",
                    "pr_ready",
                    None,
                    where,
                    pr=p["n"],
                    issue=by_pr.get(p["n"]),
                    title=p.get("title"),
                    url=p.get("url"),
                    reviewer=p.get("reviewer"),
                    checks=p.get("checks"),
                )

    if repo:
        items = [i for i in items if i["repo"] is None or str(i["repo"]).lower() == repo.lower()]
    order = {g: n for n, g in enumerate(GROUPS)}
    items.sort(key=lambda i: (order[i["group"]], -_ts(i["at"])))
    seen = [repo] if repo else list(snapshots) if watched is None else list(watched)
    return {"items": items, "stale": sorted(k for k in seen if k.lower() not in fresh)}
