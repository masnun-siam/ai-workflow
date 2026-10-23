"""Board poller: a 1-point GraphQL probe per repo per poll, the full query only when it saw a change (FR-17).

`snapshot(repo)` never touches GitHub: it returns `{data, stale, fetched_at, error, retry_at}` from memory.
`error` says why the last poll failed ("rate limited" or gh's message), None after a good one;
`retry_at` is the end of a rate-limit pause, else None.
`poll(repo)` runs PROBE (newest issue/PR update, open PRs' CI, mergeable and review state). The full QUERY
(about 6 points) follows only when the probe's answer changed, on `poll(repo, full=True)`, and at least every
FULL_EVERY s (what the probe cannot see: the 7-day merged window, edits that leave updatedAt alone).
Cadence is 60 s, or 15 s while any PR's CI is pending; COLD_POLL_SECONDS for a repo nobody is viewing
(`start`'s `hot`), and for every repo while the token's GraphQL budget, shared with the agents, is under
LOW_BUDGET points (read from each response's `rateLimit`, free) until it resets.
A rate-limit response keeps the last data, marks it stale and pauses fetching until the budget's reset
(when it was low), else for 600 s (a secondary limit).
Any other failure keeps the last data and marks it stale (retry on the normal cadence).
Never written back to GitHub; read-only.

Snapshot `data` schema (all lists, never None; `data` is the empty shape before the first fetch,
with `stale: True, fetched_at: None`):

    {
      "issues": [   # OPEN issues only (epics included: an epic has "epic" in labels), newest first
        {"n": int, "title": str, "state": "OPEN", "labels": [str],
         "priority": str | None,          # x of a `priority:<x>` label
         "parent": int | None,            # epic / parent issue number
         "sub_issues": [int],
         "closed_subs": [{"n": int, "title": str}],   # its closed sub-issues (an epic's finished children)
         "blocked_by": [{"n": int, "state": "OPEN" | "CLOSED"}],   # all blockers; filter on state
         "prs": [{"n": int, "url": str, "draft": bool, "state": "OPEN"|"CLOSED"|"MERGED",
                  "merged_at": str | None, "head": str, "ci": "success"|"failure"|"pending"|"none",
                  "conflict": bool, "sha": str | None}]}  # GitHub says the PR conflicts with its base
      ],
      "merged": [   # PRs merged in the last 7 days, newest first
        {"n": int, "title": str, "url": str, "merged_at": str, "head": str,
         "closes": [int],                 # issues the PR closed
         "epic": int | None}              # parent of the first closed issue
      ],
      "open_prs": [  # every open PR (to match PRD pull requests that close no issue)
        {"n": int, "title": str, "url": str, "draft": bool, "head": str, "ci": ..., "review": ...,
         "reviewer": str | None,          # login of the newest approving review
         "checks": int}                   # status checks that ran
      ],
      "closed_epics": [  # the 50 most recently updated CLOSED issues labelled `epic` (a PRD's Done column)
        {"n": int, "labels": [str], "closed_subs": [{"n": int, "title": str}]}
      ]
    }

Ceilings (ponytail): first 100 open issues, 50 sub-issues / 20 blockers / 5 PRs per issue, 50 merged
and 50 open PRs; add cursor paging if a repo outgrows them (it would break the one-call rule).
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

from shared import run

POLL_SECONDS = 60
FAST_POLL_SECONDS = 15  # any PR's CI still pending
RATE_LIMIT_PAUSE = 600
COLD_POLL_SECONDS = 600  # nobody viewing the repo, or the budget is low
FULL_EVERY = 600  # full fetch at least this often, even when the probe saw no change
LOW_BUDGET = 1000  # GraphQL points left of the hourly 5000
MERGED_DAYS = 7

_PR = "number url isDraft state mergedAt headRefName headRefOid reviewDecision mergeable statusCheckRollup { state }"
# open PRs also carry who approved and how many checks ran (the Inbox's "ready to merge" line)
_PR_OPEN = (
    _PR
    + " latestOpinionatedReviews(first: 5) { nodes { state author { login } } }"
    + " checks: statusCheckRollup { contexts(first: 1) { totalCount } }"
)
QUERY = f"""
query($owner: String!, $name: String!) {{
  repository(owner: $owner, name: $name) {{
    issues(states: OPEN, first: 100, orderBy: {{field: CREATED_AT, direction: DESC}}) {{
      nodes {{
        number title state
        labels(first: 20) {{ nodes {{ name }} }}
        parent {{ number }}
        subIssues(first: 50) {{ nodes {{ number title state }} }}
        blockedBy(first: 20) {{ nodes {{ number state }} }}
        closedByPullRequestsReferences(first: 5, includeClosedPrs: true) {{ nodes {{ {_PR} }} }}
      }}
    }}
    closedEpics: issues(states: CLOSED, labels: ["epic"], first: 50, orderBy: {{field: UPDATED_AT, direction: DESC}}) {{
      nodes {{ number labels(first: 20) {{ nodes {{ name }} }} subIssues(first: 50) {{ nodes {{ number title state }} }} }}
    }}
    mergedPrs: pullRequests(states: MERGED, first: 50, orderBy: {{field: UPDATED_AT, direction: DESC}}) {{
      nodes {{
        number title url mergedAt headRefName body
        closingIssuesReferences(first: 10) {{ nodes {{ number parent {{ number }} }} }}
      }}
    }}
    openPrs: pullRequests(states: OPEN, first: 50, orderBy: {{field: UPDATED_AT, direction: DESC}}) {{
      nodes {{ title body {_PR_OPEN} closingIssuesReferences(first: 10) {{ nodes {{ number }} }} }}
    }}
  }}
  rateLimit {{ cost remaining resetAt }}
}}
"""
# what changes when the board would: any issue or PR touched, an open PR's CI, conflict or review state
PROBE = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    issues(first: 1, orderBy: {field: UPDATED_AT, direction: DESC}) { totalCount nodes { updatedAt } }
    pullRequests(first: 1, orderBy: {field: UPDATED_AT, direction: DESC}) { totalCount nodes { updatedAt } }
    openPrs: pullRequests(states: OPEN, first: 50) {
      nodes { number mergeable reviewDecision statusCheckRollup { state } }
    }
  }
  rateLimit { cost remaining resetAt }
}
"""

_REVIEW = {"APPROVED": "approved", "CHANGES_REQUESTED": "changes_requested", "REVIEW_REQUIRED": "review_required"}
_CI = {"SUCCESS": "success", "FAILURE": "failure", "ERROR": "failure", "PENDING": "pending", "EXPECTED": "pending"}


def empty() -> dict:
    return {"issues": [], "merged": [], "open_prs": [], "closed_epics": []}


def _closed_subs(issue) -> list:
    """[{n, title}] of an issue's closed sub-issues (an epic's finished children)."""
    return [
        {"n": s["number"], "title": s.get("title") or ""}
        for s in _nodes(issue.get("subIssues"))
        if s.get("state") == "CLOSED"
    ]


def _nodes(x) -> list:
    return [n for n in ((x or {}).get("nodes") or []) if isinstance(n, dict)]


def _pr(n: dict) -> dict:
    ci = _CI.get(((n.get("statusCheckRollup") or {}).get("state") or "").upper(), "none")
    return {
        "n": n["number"],
        "url": n.get("url"),
        "draft": bool(n.get("isDraft")),
        "state": n.get("state"),
        "merged_at": n.get("mergedAt"),
        "head": n.get("headRefName"),
        "sha": n.get("headRefOid"),
        "ci": ci,
        "review": _REVIEW.get(n.get("reviewDecision") or "", "none"),  # no review rule on the repo: none
        "conflict": n.get("mergeable") == "CONFLICTING",  # UNKNOWN while GitHub computes it: not a conflict
    }


def _open_extra(n: dict) -> dict:
    """reviewer (login of the newest approval, else None) and checks (how many ran) of an open PR."""
    ok = [r for r in _nodes(n.get("latestOpinionatedReviews")) if r.get("state") == "APPROVED"]
    ctx = ((n.get("checks") or {}).get("contexts") or {}).get("totalCount")
    return {"reviewer": ((ok[-1].get("author") or {}).get("login") if ok else None), "checks": ctx or 0}


# GitHub links "Closes #n" to the issue only when the PR targets the default branch. A repo whose PRs go
# to staging gets no link, so the board also reads the keyword in the body and an `issue-<n>-` branch.
_CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#(\d+)\b", re.I)
_BRANCH = re.compile(r"^issue-(\d+)(?:-|$)")


def _refs(p: dict) -> list:
    """Issue numbers a PR is for: GitHub's closing links, closing keywords in its body, its branch name."""
    out = [c["number"] for c in _nodes(p.get("closingIssuesReferences"))]
    out += [int(n) for n in _CLOSES.findall(p.get("body") or "")]
    m = _BRANCH.match(p.get("headRefName") or "")
    if m:
        out.append(int(m.group(1)))
    return list(dict.fromkeys(out))


def _parse_ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize(response: dict, now: datetime | None = None) -> dict:
    """GraphQL response -> snapshot data (schema in the module docstring)."""
    repo = ((response or {}).get("data") or {}).get("repository")
    if not isinstance(repo, dict):
        raise ValueError("no repository in the GraphQL response")
    now = now or datetime.now(timezone.utc)
    issues = []
    for i in _nodes(repo.get("issues")):
        labels = [x["name"] for x in _nodes(i.get("labels")) if x.get("name")]
        prio = next((x.split(":", 1)[1].strip() for x in labels if x.lower().startswith("priority:")), None)
        issues.append(
            {
                "n": i["number"],
                "title": i.get("title") or "",
                "state": i.get("state") or "OPEN",
                "labels": labels,
                "priority": prio or None,
                "parent": (i.get("parent") or {}).get("number"),
                "sub_issues": [s["number"] for s in _nodes(i.get("subIssues"))],
                "closed_subs": _closed_subs(i),
                "blocked_by": [{"n": b["number"], "state": b.get("state")} for b in _nodes(i.get("blockedBy"))],
                "prs": [_pr(p) for p in _nodes(i.get("closedByPullRequestsReferences"))],
            }
        )
    cutoff = now - timedelta(days=MERGED_DAYS)
    merged = []
    for p in _nodes(repo.get("mergedPrs")):
        at = _parse_ts(p.get("mergedAt"))
        if not at or at < cutoff:
            continue
        linked = {c["number"]: c for c in _nodes(p.get("closingIssuesReferences"))}
        closes = _refs(p)
        parent = (linked.get(closes[0], {}).get("parent") or {}).get("number") if closes else None
        if closes and parent is None:  # not linked by GitHub: the issue, still open, names its epic
            parent = next((i["parent"] for i in issues if i["n"] == closes[0]), None)
        merged.append(
            {
                "n": p["number"],
                "title": p.get("title") or "",
                "url": p.get("url"),
                "merged_at": p["mergedAt"],
                "head": p.get("headRefName"),
                "closes": closes,
                "epic": parent,
            }
        )
    by_n = {i["n"]: i for i in issues}
    open_prs = []
    for node in _nodes(repo.get("openPrs")):
        pr = {**_pr(node), "state": "OPEN"}
        extra = _open_extra(node)
        for n in _refs(node):  # attach to its issue when GitHub did not
            if n in by_n and not any(x["n"] == pr["n"] for x in by_n[n]["prs"]):
                by_n[n]["prs"].append(dict(pr))
        open_prs.append(
            {k: v for k, v in pr.items() if k not in ("merged_at", "state")}
            | {"title": node.get("title") or ""}
            | extra
        )
    for m in merged:  # a PR merged into a non-default branch leaves its issue open: mark it merged there
        for n in m["closes"]:
            if n in by_n and not any(x["n"] == m["n"] for x in by_n[n]["prs"]):
                by_n[n]["prs"].append(
                    {
                        "n": m["n"],
                        "url": m["url"],
                        "draft": False,
                        "state": "MERGED",
                        "merged_at": m["merged_at"],
                        "head": m["head"],
                        "ci": "success",
                        "review": "none",
                    }
                )
    closed_epics = [
        {
            "n": e["number"],
            "labels": [x["name"] for x in _nodes(e.get("labels")) if x.get("name")],
            "closed_subs": _closed_subs(e),
        }
        for e in _nodes(repo.get("closedEpics"))
    ]
    return {"issues": issues, "merged": merged, "open_prs": open_prs, "closed_epics": closed_epics}


def _rate_limited(proc) -> bool:
    """gh's error output or a RATE_LIMITED GraphQL error, never the payload: titles can say "rate limit"."""
    if "rate limit" in (proc.stderr or "").lower():
        return True
    try:
        errors = json.loads(proc.stdout or "").get("errors") or []
    except (ValueError, AttributeError):
        return False
    return any(isinstance(e, dict) and e.get("type") == "RATE_LIMITED" for e in errors)


def _gh(argv):
    return run(argv, timeout=60)


class Poller:
    def __init__(self, runner=_gh, clock=time.time, on_fresh=None):
        self.runner, self.clock, self.on_fresh = runner, clock, on_fresh
        self._lock = threading.Lock()
        self._state: dict = {}  # repo -> {data, stale, fetched_at, error, next_due, paused_until, last, full_at, probe}
        self._budget = {"remaining": None, "reset_at": 0.0}  # the token's GraphQL points, from the last response

    def _entry(self, repo: str) -> dict:
        return self._state.setdefault(
            repo,
            {
                "data": empty(),
                "stale": True,
                "fetched_at": None,
                "error": None,
                "next_due": 0.0,
                "paused_until": 0.0,
                "last": 0.0,  # last poll attempt
                "full_at": 0.0,  # last full fetch
                "probe": None,  # the probe's answer at the last full fetch
            },
        )

    def _low(self) -> bool:
        b = self._budget
        return b["remaining"] is not None and b["remaining"] < LOW_BUDGET and self.clock() < b["reset_at"]

    def snapshot(self, repo: str) -> dict:
        """From memory; never waits on GitHub."""
        with self._lock:
            e = self._entry(repo)
            paused = e["paused_until"] if self.clock() < e["paused_until"] else None
            return {
                "data": e["data"],
                "stale": e["stale"],
                "fetched_at": e["fetched_at"],
                "error": e["error"],
                "retry_at": paused,
            }

    def due(self, repo: str, hot: bool = True) -> bool:
        """`hot`: someone is viewing the repo or a session runs on it; a cold one polls every COLD_POLL_SECONDS."""
        with self._lock:
            e = self._entry(repo)
            cold = 0.0 if hot else e["last"] + COLD_POLL_SECONDS
            return self.clock() >= max(e["next_due"], e["paused_until"], cold)

    def _call(self, repo: str, query: str):
        """One `gh api graphql`. The response, or None after recording why (a rate limit pauses the repo)."""
        owner, _, name = repo.partition("/")
        proc = self.runner(
            ["gh", "api", "graphql", "-f", f"query={query}", "-F", f"owner={owner}", "-F", f"name={name}"]
        )
        e = self._entry(repo)
        if _rate_limited(proc):
            with self._lock:
                now = self.clock()
                reset = self._budget["reset_at"]
                e["stale"], e["error"] = True, "rate limited"
                e["paused_until"] = reset if self._low() and reset > now else now + RATE_LIMIT_PAUSE
            print(f"ui_poller: rate limit on {repo}, paused until {e['paused_until']:.0f}", file=sys.stderr)
            return None
        try:
            resp = json.loads(proc.stdout or "")
            if proc.returncode != 0 or resp.get("errors"):
                raise ValueError(str(resp.get("errors") or proc.stderr)[:200])
        except (ValueError, AttributeError) as exc:
            print(f"ui_poller: {repo}: {exc}", file=sys.stderr)
            with self._lock:
                e["stale"], e["error"] = True, str(exc)[:200] or type(exc).__name__
            return None
        rl = (resp.get("data") or {}).get("rateLimit") or {}
        at = _parse_ts(rl.get("resetAt"))
        if isinstance(rl.get("remaining"), int) and at:
            with self._lock:
                self._budget = {"remaining": rl["remaining"], "reset_at": at.timestamp()}
        return resp

    def poll(self, repo: str, full: bool = False) -> dict:
        """The probe, then the full query when needed (none while rate-limit paused). Returns the snapshot.
        `full`: fetch everything even when the probe saw no change (the board's Refresh, after a write)."""
        with self._lock:
            e = self._entry(repo)
            now = self.clock()
            paused = now < e["paused_until"]
            prev = e["data"]
            if not paused:
                e["last"] = now
        if paused:
            return self.snapshot(repo)
        data, fresh = None, False
        probe = self._call(repo, PROBE)
        if probe is not None:
            answer = json.dumps((probe.get("data") or {}).get("repository"), sort_keys=True)
            with self._lock:
                full = full or answer != e["probe"] or self.clock() - e["full_at"] >= FULL_EVERY
            if not full:
                fresh = True  # nothing changed: the data in memory is current
            else:
                resp = self._call(repo, QUERY)
                if resp is not None:
                    try:
                        data = normalize(resp)
                    except (ValueError, KeyError, TypeError, AttributeError) as exc:
                        print(f"ui_poller: {repo}: {exc}", file=sys.stderr)
                        with self._lock:
                            e["stale"], e["error"] = True, str(exc)[:200] or type(exc).__name__
                    else:
                        fresh = True
                        with self._lock:
                            e.update(data=data, full_at=self.clock(), probe=answer)
        with self._lock:
            now = self.clock()
            if fresh:
                d = e["data"]
                pending = any(p["ci"] == "pending" for i in d["issues"] for p in i["prs"] if p["state"] == "OPEN")
                pending = pending or any(p["ci"] == "pending" for p in d["open_prs"])
                e.update(stale=False, fetched_at=now, error=None)
                wait = FAST_POLL_SECONDS if pending else POLL_SECONDS
                e["next_due"] = now + (max(wait, COLD_POLL_SECONDS) if self._low() else wait)
            elif now >= e["paused_until"]:
                e["next_due"] = now + POLL_SECONDS
        snap = self.snapshot(repo)
        if fresh and self.on_fresh:
            try:
                self.on_fresh(repo, snap, prev)
            except Exception as exc:  # noqa: BLE001 - a hook must not stop polling
                print(f"ui_poller: on_fresh {repo}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return snap

    def start(self, repos, tick: float = 5.0, hot=None) -> threading.Thread:
        """Daemon thread: every `tick` s poll each repo of `repos()` (callable -> slugs) that is due.
        `hot()` (callable -> slugs) names the repos on the normal cadence; the rest are cold. None: all hot."""

        def loop():
            while True:
                warm = hot() if hot else None
                for repo in list(repos()):
                    if self.due(repo, warm is None or repo in warm):
                        self.poll(repo)
                time.sleep(tick)

        t = threading.Thread(target=loop, daemon=True)
        t.start()
        return t


_default = Poller()
snapshot = _default.snapshot
poll = _default.poll
