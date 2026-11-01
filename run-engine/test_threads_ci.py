"""Plain-assert checks for threads.py and ci.py."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ci  # noqa: E402
import threads  # noqa: E402

passed = 0


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


# --------------------------------------------------------------------------- threads

THREADS = [
    {"node_id": "PRRT_a", "is_resolved": False, "comment_id": 111, "url": "u1"},
    {"node_id": "PRRT_b", "is_resolved": True, "comment_id": 222, "url": "u2"},
]
assert threads.thread_for_comment(THREADS, 222)["node_id"] == "PRRT_b"
assert threads.thread_for_comment(THREADS, "111")["node_id"] == "PRRT_a"
assert threads.thread_for_comment(THREADS, 999) is None
assert threads.thread_for_comment(THREADS, None) is None
ok("a review thread is matched by its first comment's REST id, string or int")

# --------------------------------------------------------------------------- ci

assert ci.state_of([{"bucket": "pass"}, {"bucket": "fail"}, {"bucket": "pending"}]) == "pending", (
    "a still-running check is not a verdict"
)
assert ci.state_of([{"bucket": "pass"}, {"bucket": "fail"}]) == "red"
assert ci.state_of([{"bucket": "pass"}, {"bucket": "skipping"}]) == "green"
assert ci.state_of([]) == "green"
assert ci.run_id_of("https://github.com/o/r/actions/runs/123456/job/99") == "123456"
assert ci.run_id_of("https://example.test/nothing") == ""
assert ci.run_id_of(None) == ""
ok("ci state puts pending ahead of failing, and the run id comes out of the check link")

import subprocess  # noqa: E402
import types  # noqa: E402


def fake_gh(checks_proc):
    def gh(args, **kw):
        if args[1] == "view":
            return "abc", None
        return None, checks_proc

    return gh


real_gh = ci.gh_json
ci.gh_json = fake_gh(subprocess.CompletedProcess([], 1, "", "API rate limit exceeded"))
snap = ci.snapshot("o", "r", 1)
assert snap["state"] == "error" and "rate limit" in snap["note"], snap
ci.gh_json = fake_gh(subprocess.CompletedProcess([], 1, "", "no checks reported on the branch"))
assert ci.snapshot("o", "r", 1)["state"] == "green"
ci.gh_json = fake_gh(subprocess.CompletedProcess([], 8, '[{"name":"a","bucket":"fail","link":""}]', ""))
assert ci.snapshot("o", "r", 1)["state"] == "red"
ok("snapshot: gh failure is error, no checks is green, nonzero exit with JSON is read")

seq = iter([{"state": "error", "failing": []}, {"state": "green", "failing": []}])
calls = []
real = (ci.snapshot, ci.time.sleep)
ci.snapshot = lambda *a: next(seq)
ci.time.sleep = lambda n: calls.append(n)
try:
    ci.cmd_status(types.SimpleNamespace(pr="o/r#1", watch=True, timeout=1200))
finally:
    ci.snapshot, ci.time.sleep = real
    ci.gh_json = real_gh
assert len(calls) == 1
ok("cmd_status --watch keeps polling through error")

print(f"\n{passed} checks passed")
