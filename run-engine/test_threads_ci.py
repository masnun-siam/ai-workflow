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

print(f"\n{passed} checks passed")
