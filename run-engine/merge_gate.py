"""The review-side preconditions of a merge, in one place (dispatch `_gate`, Inbox/board `merge_ready`).

`blockers(pr, solo)` takes a PR dict with `draft, conflict, approved, changes_requested, threads_open` (the poller computes
the last two once) and returns why it may not merge, or None. Order: draft, conflict, changes requested,
unresolved review threads, no approving review (skipped when `solo`: nobody can approve a PR on your own repo; changes requested still block).
CI mode and the grind check are not here: they belong to the callers.
"""

from __future__ import annotations


def blockers(pr: dict, solo) -> str | None:
    if pr.get("draft"):
        return "PR is a draft"
    if pr.get("conflict"):
        return "PR has a merge conflict"
    if pr.get("changes_requested"):
        return "changes requested"
    if pr.get("threads_open"):
        return "unresolved review threads"
    if not pr.get("approved") and not solo:
        return "no approving review"
    return None
