"""Round selection for `pr-grind`'s Step 1: `route review pick`.

pr-grind's Step 1 used to say "more than one review in the round -> take the
newest only". That rule silently discarded a genuine finding when a reviewer's
comment-carrying `COMMENTED` review was followed within seconds by a second,
empty `APPROVED` rubber stamp (a re-run of the bot, a stray click, GitHub's own
"dismiss and re-review" flow) landing on the SAME commit — newest-wins picked
the empty stamp and threw the findings away. This module narrows the rule: a
"round" is still resolved to one verdict, but a comment-carrying review beats a
same-commit, same-window rubber stamp; only across different commits or
different rounds does plain newest-wins still apply.

Pure and stdlib-only: no `gh` call lives here, only the decision. The caller
(`SKILL.md` Step 1) supplies `gh api .../reviews` and `.../comments` output.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime

import shared

_VERDICT_RE = re.compile(r"Verdict:.*?\d+\s*blocker.*?\d+\s*should-fix", re.IGNORECASE | re.DOTALL)

_EPOCH = datetime.min


def _ts(value) -> datetime | None:
    """Tolerant ISO8601 parse. `fromisoformat` only accepts a bare trailing `Z`
    from Python 3.11 on; this repo pins 3.10+, so rewrite it first."""
    if not isinstance(value, str) or not value:
        return None
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _has_verdict(body) -> bool:
    return bool(_VERDICT_RE.search(body or ""))


def _comment_counts(comments) -> dict:
    counts: dict = {}
    for c in comments or []:
        rid = (c or {}).get("pull_request_review_id")
        if rid is None:
            continue
        counts[rid] = counts.get(rid, 0) + 1
    return counts


def pick(reviews, comments, window: int = 60) -> dict:
    comment_counts = _comment_counts(comments)
    if not reviews:
        return {"selected": None, "superseded": [], "reason": "no reviews", "comment_counts": comment_counts}

    def ts_or_epoch(r):
        return _ts(r.get("submitted_at")) or _EPOCH

    newest = max(reviews, key=ts_or_epoch)
    newest_ts = ts_or_epoch(newest)
    newest_commit = newest.get("commit_id")

    group = [
        r for r in reviews
        if r.get("commit_id") == newest_commit
        and abs((ts_or_epoch(r) - newest_ts).total_seconds()) <= window
    ]

    with_comments = [r for r in group if comment_counts.get(r.get("id"), 0) > 0]
    if with_comments:
        selected = max(with_comments, key=ts_or_epoch)
        reason = "newest comment-carrying review in the round beats a same-commit rubber stamp"
    else:
        with_verdict = [r for r in group if _has_verdict(r.get("body"))]
        if with_verdict:
            selected = max(with_verdict, key=ts_or_epoch)
            reason = "newest verdict-carrying review in the round"
        else:
            selected = max(group, key=ts_or_epoch)
            reason = "newest review in the round"

    superseded = [r.get("id") for r in reviews if r is not selected]
    return {"selected": selected.get("id"), "superseded": superseded, "reason": reason, "comment_counts": comment_counts}


def cmd_pick(args) -> None:
    reviews = _load(args.reviews)
    comments = _load(args.comments)
    print(json.dumps(pick(reviews, comments, window=args.window), indent=2))


def _load(path: str):
    raw = sys.stdin.read() if path == "-" else _read_file(path)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        shared.die(shared.FAILED, f"not valid JSON: {path}")


def _read_file(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        shared.die(shared.FAILED, f"cannot read {path}: {exc.strerror or exc}")


def register(sub, add) -> None:
    p = sub.add_parser("review", help="pick this round's review from a batch")
    ops = p.add_subparsers(dest="op", required=True)
    q = ops.add_parser("pick", help="select the review that carries the round's verdict")
    q.add_argument("--reviews", required=True, help="path to `gh api .../reviews` JSON, or -")
    q.add_argument("--comments", required=True, help="path to `gh api .../comments` JSON, or -")
    q.add_argument("--window", type=int, default=60, help="seconds around the newest review's timestamp treated as one round")
    q.set_defaults(func=cmd_pick)
