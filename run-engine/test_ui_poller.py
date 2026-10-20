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


def runner_for(responses, calls):
    def runner(argv):
        calls.append(argv)
        r = responses[min(len(calls), len(responses)) - 1]
        out, err, code = r if isinstance(r, tuple) else (json.dumps(r), "", 0)
        return subprocess.CompletedProcess(argv, code, out, err)

    return runner


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
    {"n": 40, "title": "recent", "url": "u40", "merged_at": ts(2), "head": "issue-5-a", "closes": [5], "epic": 1}
]  # the 9-day-old merge is dropped
assert d["open_prs"][0]["ci"] == "pending" and d["open_prs"][0]["title"] == "PRD x"

# one call per poll, cadence 60s, before first fetch is stale+empty
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
clock3.t += 599
assert not p3.due("o/r")
p3.poll("o/r")
assert len(calls3) == 2  # paused: no call
clock3.t += 1
assert p3.due("o/r")
s = p3.poll("o/r")
assert len(calls3) == 3 and not s["stale"]

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
print("ok")
