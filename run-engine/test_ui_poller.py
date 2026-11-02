#!/usr/bin/env python3
"""Self-check for run-engine/ui_poller.py. `python3 test_ui_poller.py` — exit 0 = green."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui_poller  # noqa: E402

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def ts(days):
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(n, state="OPEN", draft=False, ci="SUCCESS", merged=None):
    return {
        "number": n,
        "url": f"https://github.com/o/r/pull/{n}",
        "isDraft": draft,
        "state": state,
        "mergedAt": merged,
        "headRefName": f"issue-{n}",
        "headRefOid": f"sha{n}",
        "statusCheckRollup": {"state": ci} if ci else None,
    }


def issue(n, labels=(), parent=None, subs=(), blockers=(), prs=()):
    return {
        "number": n,
        "title": f"issue {n}",
        "state": "OPEN",
        "labels": {"nodes": [{"name": x} for x in labels]},
        "parent": {"number": parent} if parent else None,
        "subIssues": {"nodes": [{"number": s} for s in subs]},
        "blockedBy": {"nodes": [{"number": b, "state": s} for b, s in blockers]},
        "closedByPullRequestsReferences": {"nodes": list(prs)},
    }


def fixture(ci="SUCCESS", open_ci="PENDING"):
    nodes = [
        issue(1, ["epic", "prd-x"], subs=[2, 3]),
        issue(2, ["refined", "priority:high"], parent=1, blockers=[(3, "OPEN"), (9, "CLOSED")]),
        issue(3, ["refined"], parent=1, prs=[pr(30, draft=True, ci=ci), pr(29, state="CLOSED", ci=None)]),
    ]
    nodes += [issue(n) for n in range(4, 21)]  # 20 open issues
    return {
        "data": {
            "repository": {
                "issues": {"nodes": nodes},
                "mergedPrs": {
                    "nodes": [
                        {
                            "number": 40,
                            "title": "recent",
                            "url": "u40",
                            "mergedAt": ts(2),
                            "headRefName": "issue-5-a",
                            "headRefOid": "abc",
                            "closingIssuesReferences": {"nodes": [{"number": 5, "parent": {"number": 1}}]},
                        },
                        {
                            "number": 41,
                            "title": "old",
                            "url": "u41",
                            "mergedAt": ts(9),
                            "headRefName": "b",
                            "closingIssuesReferences": {"nodes": []},
                        },
                    ]
                },
                "openPrs": {"nodes": [dict(pr(50, ci=open_ci), title="PRD x")]},
            }
        }
    }


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def probe_answer(stamp, remaining=4000, reset="2099-01-01T00:00:00Z"):
    return {
        "data": {
            "repository": {"issues": {"totalCount": 1, "nodes": [{"updatedAt": stamp}]}},
            "rateLimit": {"cost": 1, "remaining": remaining, "resetAt": reset},
        }
    }


def runner_for(responses, calls, probes=None, probe_calls=None):
    """`responses` answer the full query (recorded in `calls`), `probes` the probe (in `probe_calls`).
    No `probes`: every probe answers differently, so every poll does the full fetch."""
    probe_calls = [] if probe_calls is None else probe_calls

    def runner(argv):
        if f"query={ui_poller.PROBE}" in argv:
            probe_calls.append(argv)
            seq = probes or [probe_answer(str(len(probe_calls)))]
            r = seq[min(len(probe_calls), len(seq)) - 1]
        else:
            calls.append(argv)
            r = responses[min(len(calls), len(responses)) - 1]
        out, err, code = r if isinstance(r, tuple) else (json.dumps(r), "", 0)
        return subprocess.CompletedProcess(argv, code, out, err)

    return runner


# issue paging: QUERY page one, then ISSUES_PAGE until the list ends or MAX_ISSUE_PAGES
def paged(first_next, page_next, fail=False):
    def runner(argv):
        page = f"query={ui_poller.ISSUES_PAGE}" in argv
        if f"query={ui_poller.PROBE}" in argv:
            r = probe_answer("1")
        elif page:
            if fail:
                return subprocess.CompletedProcess(argv, 1, "", "boom")
            n = 100 + 10 * len(pages)
            pages.append(argv)
            nodes = [issue(m) for m in range(n, n + 2)]
            r = {
                "data": {
                    "repository": {
                        "issues": {"pageInfo": {"hasNextPage": page_next, "endCursor": f"c{n}"}, "nodes": nodes}
                    }
                }
            }
        else:
            r = fixture()
            r["data"]["repository"]["issues"]["pageInfo"] = {"hasNextPage": first_next, "endCursor": "c0"}
        return subprocess.CompletedProcess(argv, 0, json.dumps(r), "")

    pages = []
    return runner, pages


runner, pages = paged(True, False)
sn = ui_poller.Poller(runner, Clock()).poll("o/r")
assert len(pages) == 1 and "after=c0" in pages[0] and not sn["stale"]
assert len(sn["data"]["issues"]) == 22 and sn["data"]["issues_truncated"] is False
runner, pages = paged(True, True)
sn = ui_poller.Poller(runner, Clock()).poll("o/r")
assert len(pages) == ui_poller.MAX_ISSUE_PAGES - 1 and sn["data"]["issues_truncated"] is True
runner, pages = paged(True, False, fail=True)
sn = ui_poller.Poller(runner, Clock()).poll("o/r")
assert sn["stale"] and sn["data"]["issues"] == []

# normalize
d = ui_poller.normalize(fixture(), NOW)
assert len(d["issues"]) == 20
i2, i3 = d["issues"][1], d["issues"][2]
assert i2["priority"] == "high" and i2["parent"] == 1
assert i2["blocked_by"] == [{"n": 3, "state": "OPEN"}, {"n": 9, "state": "CLOSED"}]
assert d["issues"][0]["sub_issues"] == [2, 3]
assert (
    [p["state"] for p in i3["prs"]] == ["OPEN", "CLOSED"] and i3["prs"][0]["draft"] and i3["prs"][0]["ci"] == "success"
)
assert i3["prs"][1]["ci"] == "none"
assert d["merged"] == [
    {
        "n": 40,
        "title": "recent",
        "url": "u40",
        "merged_at": ts(2),
        "head": "issue-5-a",
        "closes": [5],
        "epic": 1,
        "sha": "abc",
    }
]  # the 9-day-old merge is dropped
assert d["open_prs"][0]["ci"] == "pending" and d["open_prs"][0]["title"] == "PRD x"

# review decision on every PR; the approving reviewer and the check count on open PRs
assert "reviewDecision" in ui_poller.QUERY and i3["prs"][0]["review"] == "none"
assert d["open_prs"][0]["review"] == "none" and d["open_prs"][0]["reviewer"] is None and d["open_prs"][0]["checks"] == 0
f = fixture()
f["data"]["repository"]["openPrs"]["nodes"][0].update(
    reviewDecision="APPROVED",
    latestOpinionatedReviews={
        "nodes": [
            {"state": "CHANGES_REQUESTED", "author": {"login": "amy"}},
            {"state": "APPROVED", "author": {"login": "bob"}},
        ]
    },
    checks={"contexts": {"totalCount": 4}},
)
f["data"]["repository"]["issues"]["nodes"][2]["closedByPullRequestsReferences"]["nodes"][0]["reviewDecision"] = (
    "CHANGES_REQUESTED"
)
f["data"]["repository"]["issues"]["nodes"][2]["closedByPullRequestsReferences"]["nodes"][1]["reviewDecision"] = (
    "REVIEW_REQUIRED"
)
d2 = ui_poller.normalize(f, NOW)
op = d2["open_prs"][0]
assert (op["review"], op["reviewer"], op["checks"]) == ("approved", "bob", 4)
assert (op["approved"], op["changes_requested"]) == (False, True), "one changes-request blocks the approval"
f["data"]["repository"]["openPrs"]["nodes"][0].update(
    reviewDecision=None, latestOpinionatedReviews={"nodes": [{"state": "APPROVED", "author": {"login": "bob"}}]}
)
op3 = ui_poller.normalize(f, NOW)["open_prs"][0]
assert (op3["review"], op3["approved"], op3["changes_requested"]) == ("none", True, False)
assert op3["threads_open"] == 0 and "reviewThreads" in ui_poller.QUERY
f["data"]["repository"]["openPrs"]["nodes"][0]["reviewThreads"] = {
    "nodes": [
        {"isResolved": True, "isOutdated": False},
        {"isResolved": False, "isOutdated": True},
        {"isResolved": False, "isOutdated": False},
        {"isResolved": False, "isOutdated": False},
    ]
}
assert ui_poller.normalize(f, NOW)["open_prs"][0]["threads_open"] == 2  # resolved and outdated do not count
assert [p["review"] for p in d2["issues"][2]["prs"]] == ["changes_requested", "review_required"]
# conflict: only GitHub's CONFLICTING (UNKNOWN while it computes, MERGEABLE) is a conflict
assert "mergeable" in ui_poller.QUERY and op["conflict"] is False
f["data"]["repository"]["openPrs"]["nodes"][0]["mergeable"] = "CONFLICTING"
f["data"]["repository"]["issues"]["nodes"][2]["closedByPullRequestsReferences"]["nodes"][0]["mergeable"] = "UNKNOWN"
d3 = ui_poller.normalize(f, NOW)
assert d3["open_prs"][0]["conflict"] is True and d3["issues"][2]["prs"][0]["conflict"] is False

# one full call per poll (the probe changed), cadence 60s, before first fetch is stale+empty
clock, calls = Clock(), []
fresh = []
p = ui_poller.Poller(runner_for([fixture("SUCCESS", "SUCCESS")], calls), clock, on_fresh=lambda *a: fresh.append(a))
s = p.snapshot("o/r")
assert s["stale"] and s["fetched_at"] is None and s["data"] == ui_poller.empty() and not calls
assert p.due("o/r")
s = p.poll("o/r")
assert len(calls) == 1 and "graphql" in calls[0] and "owner=o" in calls[0] and "name=r" in calls[0]
assert not s["stale"] and s["fetched_at"] == 1000.0 and len(s["data"]["issues"]) == 20
assert len(fresh) == 1 and fresh[0][0] == "o/r" and fresh[0][2] == ui_poller.empty()
assert not p.due("o/r")
clock.t += 59
assert not p.due("o/r")
clock.t += 1
assert p.due("o/r")

# pending CI (open PR 50 pending in the fixture) -> 15s
clock2, calls2 = Clock(), []
p2 = ui_poller.Poller(runner_for([fixture()], calls2), clock2)
p2.poll("o/r")
clock2.t += 14
assert not p2.due("o/r")
clock2.t += 1
assert p2.due("o/r")

# rate limit: keep data, stale, pause 600s, no gh call while paused
clock3, calls3 = Clock(), []
p3 = ui_poller.Poller(runner_for([fixture(), ("", "GraphQL: API rate limit exceeded", 1), fixture()], calls3), clock3)
p3.poll("o/r")
clock3.t += 60
s = p3.poll("o/r")
assert s["stale"] and len(s["data"]["issues"]) == 20 and len(calls3) == 2
assert s["error"] == "rate limited" and s["retry_at"] == clock3.t + 600
clock3.t += 599
assert not p3.due("o/r")
p3.poll("o/r")
assert len(calls3) == 2  # paused: no call
clock3.t += 1
assert p3.due("o/r")
s = p3.poll("o/r")
assert len(calls3) == 3 and not s["stale"] and s["error"] is None and s["retry_at"] is None

# a payload that merely mentions "rate limit" (an issue title) is fresh data, not a pause
f = fixture()
f["data"]["repository"]["issues"]["nodes"][3]["title"] = "keep status under GitHub's rate limit"
calls5 = []
s = ui_poller.Poller(runner_for([f], calls5), Clock()).poll("o/r")
assert not s["stale"] and len(s["data"]["issues"]) == 20, s["stale"]
# a RATE_LIMITED GraphQL error pauses
s = ui_poller.Poller(
    runner_for([({"errors": [{"type": "RATE_LIMITED", "message": "x"}]}), fixture()], []), Clock()
).poll("o/r")
assert s["stale"]

# garbage response: stale, last data kept
clock4, calls4 = Clock(), []
p4 = ui_poller.Poller(runner_for([fixture(), ("not json", "", 0)], calls4), clock4)
p4.poll("o/r")
clock4.t += 60
s = p4.poll("o/r")
assert s["stale"] and len(s["data"]["issues"]) == 20
assert s["error"] and s["retry_at"] is None  # gh's failure text, shown on the board's stale banner

# PRs into a non-default branch (staging): GitHub does not link "Closes #n", so the body and branch do
f = fixture()
f["data"]["repository"]["openPrs"]["nodes"] = [
    dict(
        pr(60, ci="SUCCESS"),
        title="fix",
        body="Closes #6\n\nmore",
        headRefName="feat-x",
        closingIssuesReferences={"nodes": []},
    ),
    dict(
        pr(61, draft=True, ci="PENDING"),
        title="wip",
        body="",
        headRefName="issue-7-thing",
        closingIssuesReferences={"nodes": []},
    ),
]
f["data"]["repository"]["issues"]["nodes"][7]["parent"] = {"number": 1}  # issue 8, an epic child
f["data"]["repository"]["mergedPrs"]["nodes"].append(
    {
        "number": 62,
        "title": "m",
        "url": "u62",
        "mergedAt": ts(1),
        "headRefName": "x",
        "body": "Fixes #8",
        "closingIssuesReferences": {"nodes": []},
    }
)
d = ui_poller.normalize(f, now=NOW)
by = {i["n"]: i for i in d["issues"]}
assert [p["n"] for p in by[6]["prs"]] == [60] and by[6]["prs"][0]["state"] == "OPEN", by[6]["prs"]
assert [(p["n"], p["draft"]) for p in by[7]["prs"]] == [(61, True)], "branch issue-7-… links the draft PR"
assert by[7]["prs"][0]["sha"] == "sha61", "the head commit rides along for the dispatch gate"
assert [(p["n"], p["state"]) for p in by[8]["prs"]] == [(62, "MERGED")]
m62 = next(m for m in d["merged"] if m["n"] == 62)
assert m62["closes"] == [8] and m62["epic"] == 1, m62
assert [p["n"] for p in d["open_prs"]] == [60, 61] and "state" not in d["open_prs"][0]
print("ok  PRs into staging link to their issue by body keyword and issue-<n> branch")

# probe: an unchanged answer skips the full query (data stays fresh), a changed one, full=True or FULL_EVERY fetch
clock6, calls6, probes6 = Clock(), [], []
same = probe_answer("t1")
p6 = ui_poller.Poller(
    runner_for([fixture("SUCCESS", "SUCCESS")], calls6, [same, same, same, probe_answer("t2"), same], probes6), clock6
)
p6.poll("o/r")
assert (len(probes6), len(calls6)) == (1, 1)  # first poll: probe + full
clock6.t += 60
s = p6.poll("o/r")
assert (len(probes6), len(calls6)) == (2, 1) and not s["stale"] and s["fetched_at"] == clock6.t
assert len(s["data"]["issues"]) == 20
s = p6.poll("o/r", full=True)
assert (len(probes6), len(calls6)) == (3, 2)  # Refresh / after a write
p6.poll("o/r")
assert (len(probes6), len(calls6)) == (4, 3)  # probe answer changed
clock6.t += ui_poller.FULL_EVERY
p6.poll("o/r")
assert (len(probes6), len(calls6)) == (5, 4)  # same answer, but the full fetch is due
assert "rateLimit" in ui_poller.QUERY and "rateLimit" in ui_poller.PROBE
print("ok  probe skips the full query when nothing changed")

# cold repo (nobody viewing, no live session): due every COLD_POLL_SECONDS, not every 60 s
clock7 = Clock()
p7 = ui_poller.Poller(runner_for([fixture("SUCCESS", "SUCCESS")], []), clock7)
p7.poll("o/r")
clock7.t += 60
assert p7.due("o/r") and not p7.due("o/r", hot=False)
clock7.t += ui_poller.COLD_POLL_SECONDS - 60
assert p7.due("o/r", hot=False)
print("ok  cold repos poll every COLD_POLL_SECONDS")

# low budget: slow every repo to COLD_POLL_SECONDS; a rate limit then pauses until the reported reset
clock8, calls8 = Clock(), []
reset = datetime.fromtimestamp(clock8.t + 1800, timezone.utc).isoformat()
low = probe_answer("t1", remaining=ui_poller.LOW_BUDGET - 1, reset=reset)
p8 = ui_poller.Poller(runner_for([fixture(), ("", "GraphQL: API rate limit exceeded", 1)], calls8, [low]), clock8)
p8.poll("o/r")  # fixture has pending CI: would be 15 s
clock8.t += 15
assert not p8.due("o/r")
clock8.t += ui_poller.COLD_POLL_SECONDS - 15
assert p8.due("o/r")
s = p8.poll("o/r", full=True)
assert s["error"] == "rate limited" and s["retry_at"] == clock8.t - ui_poller.COLD_POLL_SECONDS + 1800
# budget fine (secondary limit): the fixed RATE_LIMIT_PAUSE
clock9 = Clock()
p9 = ui_poller.Poller(runner_for([fixture(), ("", "GraphQL: API rate limit exceeded", 1)], []), clock9)
p9.poll("o/r")
clock9.t += 60
assert p9.poll("o/r")["retry_at"] == clock9.t + ui_poller.RATE_LIMIT_PAUSE
print("ok  low budget slows polling, a rate limit waits for the reset")

# the poller thread survives a raising pass (and shared.supervised_loop keeps ticking)
import threading  # noqa: E402
import time  # noqa: E402

seen = []


def flaky_repos():
    seen.append(1)
    if len(seen) == 1:
        raise RuntimeError("boom")
    return []


t = ui_poller.Poller(runner_for([], [])).start(flaky_repos, tick=0.01)
assert isinstance(t, threading.Thread) and t.daemon
deadline = time.time() + 10
while len(seen) < 2 and time.time() < deadline:
    time.sleep(0.01)
assert len(seen) >= 2 and t.is_alive(), seen
print("ok  poller survives a raising pass")
print("ok")
