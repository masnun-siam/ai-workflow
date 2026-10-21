"""Board poller: one `gh api graphql` call per repo per poll, last result kept in memory (FR-17).

`snapshot(repo)` never touches GitHub: it returns `{data, stale, fetched_at, error, retry_at}` from memory.
`error` says why the last poll failed ("rate limited" or gh's message), None after a good one;
`retry_at` is the end of a rate-limit pause, else None.
`poll(repo)` does the single GraphQL call. Cadence is 60 s, or 15 s while any PR's CI is pending.
A rate-limit response keeps the last data, marks it stale and pauses fetching for 600 s.
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
         "blocked_by": [{"n": int, "state": "OPEN" | "CLOSED"}],   # all blockers; filter on state
         "prs": [{"n": int, "url": str, "draft": bool, "state": "OPEN"|"CLOSED"|"MERGED",
                  "merged_at": str | None, "head": str, "ci": "success"|"failure"|"pending"|"none"}]}
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
MERGED_DAYS = 7

_PR = "number url isDraft state mergedAt headRefName reviewDecision statusCheckRollup { state }"
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
        subIssues(first: 50) {{ nodes {{ number }} }}
        blockedBy(first: 20) {{ nodes {{ number state }} }}
        closedByPullRequestsReferences(first: 5, includeClosedPrs: true) {{ nodes {{ {_PR} }} }}
      }}
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
}}
"""

_REVIEW = {"APPROVED": "approved", "CHANGES_REQUESTED": "changes_requested", "REVIEW_REQUIRED": "review_required"}
_CI = {"SUCCESS": "success", "FAILURE": "failure", "ERROR": "failure", "PENDING": "pending", "EXPECTED": "pending"}


def empty() -> dict:
    return {"issues": [], "merged": [], "open_prs": []}


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
        "ci": ci,
        "review": _REVIEW.get(n.get("reviewDecision") or "", "none"),  # no review rule on the repo: none
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
    return {"issues": issues, "merged": merged, "open_prs": open_prs}


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
        self._state: dict = {}  # repo -> {data, stale, fetched_at, error, next_due, paused_until}

    def _entry(self, repo: str) -> dict:
        return self._state.setdefault(
            repo,
            {"data": empty(), "stale": True, "fetched_at": None, "error": None, "next_due": 0.0, "paused_until": 0.0},
        )

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

    def due(self, repo: str) -> bool:
        with self._lock:
            e = self._entry(repo)
            return self.clock() >= max(e["next_due"], e["paused_until"])

    def poll(self, repo: str) -> dict:
        """One gh call (none while rate-limit paused). Returns the snapshot afterwards."""
        with self._lock:
            e = self._entry(repo)
            paused = self.clock() < e["paused_until"]
            prev = e["data"]
        if paused:
            return self.snapshot(repo)
        owner, _, name = repo.partition("/")
        proc = self.runner(
            ["gh", "api", "graphql", "-f", f"query={QUERY}", "-F", f"owner={owner}", "-F", f"name={name}"]
        )
        data = None
        if _rate_limited(proc):
            with self._lock:
                e["stale"], e["error"], e["paused_until"] = True, "rate limited", self.clock() + RATE_LIMIT_PAUSE
            print(f"ui_poller: rate limit on {repo}, pausing {RATE_LIMIT_PAUSE}s", file=sys.stderr)
        else:
            try:
                resp = json.loads(proc.stdout or "")
                if proc.returncode != 0 or resp.get("errors"):
                    raise ValueError(str(resp.get("errors") or proc.stderr)[:200])
                data = normalize(resp)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                print(f"ui_poller: {repo}: {exc}", file=sys.stderr)
                with self._lock:
                    e["stale"], e["error"] = True, str(exc)[:200] or type(exc).__name__
        with self._lock:
            now = self.clock()
            if data is not None:
                pending = any(p["ci"] == "pending" for i in data["issues"] for p in i["prs"] if p["state"] == "OPEN")
                pending = pending or any(p["ci"] == "pending" for p in data["open_prs"])
                e.update(data=data, stale=False, fetched_at=now, error=None)
                e["next_due"] = now + (FAST_POLL_SECONDS if pending else POLL_SECONDS)
            elif now >= e["paused_until"]:
                e["next_due"] = now + POLL_SECONDS
        snap = self.snapshot(repo)
        if data is not None and self.on_fresh:
            try:
                self.on_fresh(repo, snap, prev)
            except Exception as exc:  # noqa: BLE001 - a hook must not stop polling
                print(f"ui_poller: on_fresh {repo}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return snap

    def start(self, repos, tick: float = 5.0) -> threading.Thread:
        """Daemon thread: every `tick` s poll each repo of `repos()` (callable -> slugs) that is due."""

        def loop():
            while True:
                for repo in list(repos()):
                    if self.due(repo):
                        self.poll(repo)
                time.sleep(tick)

        t = threading.Thread(target=loop, daemon=True)
        t.start()
        return t


_default = Poller()
snapshot = _default.snapshot
poll = _default.poll
