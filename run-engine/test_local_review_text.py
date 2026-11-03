#!/usr/bin/env python3
"""Skill-text check for Loop mode in /implement-issue step 12. `python3 test_local_review_text.py` — exit 0 = green."""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []


def ok(name, cond, detail=""):
    print(("ok  " if cond else "FAIL ") + name + ("" if cond else f": {detail}"))
    if not cond:
        fails.append(name)


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


skill = read("skills/implement-issue/SKILL.md")
start = skill.index("12. **Review it before pushing.**")
step12 = skill[start : skill.index("\n13. ", start)]
step13 = skill[skill.index("\n13. ") : skill.index("\n14. ")]
step16 = skill[skill.index("\n16. ") :].split("\n## ", 1)[0]

SINGLE = (
    "12. **Review it before pushing.** CI is expensive, so the review runs on the local branch, not after CI. "
    'Run `/pr-review <branch>` (see "Repo skills win") on the committed work. Fix every Critical and Major finding '
    "locally in new commits and re-run the affected checks; fix the rest or say in the pull request why not. "
    "Re-review the new commits the same way until no Critical or Major finding is left.\n"
)
ok("single text unchanged", step12.startswith(SINGLE))

ok("reads aiw local-review", "Run `aiw local-review` once" in step12)
ok("only loop selects Loop", "Only `loop` selects Loop mode" in step12)
ok("mode read once", "The mode is read once" in step12)

for point in (
    "fresh full review of `origin/<base>..HEAD`",
    "`/pr-review <branch>`",
    "every finding of every severity",
    "`new`",
    "`repeat of round <r> #<k>`",
    "even reworded or on a shifted line",
    "a finding that was fixed or answered does not count again",
    "`fixed <sha>`",
    "`answered: <reason>`",
    "No round cap.",
    "`Local review round N: K new findings`",
):
    ok(f"loop: {point}", point in step12)

for point in (
    "`$(git rev-parse --git-path local-review-findings.md)`",
    "never committed",
    "Read it first",
    "A `status: open` log is resumed: the next round is the last round + 1",
    "N counts every round",
    "A `status: done` log, or none, is replaced by a fresh `status: open` log at round 1",
):
    ok(f"log: {point}", point in step12)

for point in (
    "runs none of the repo's checks and pushes nothing",
    "run the affected checks once",
    "as step 9 picks them",
    "the loop goes back to a full review at (1)",
    "step 13 push, once",
):
    ok(f"checks: {point}", point in step12)

MARK = "`Local review: loop, N rounds`"
ok("step 13 marker", MARK in step13 and "`status: done`" in step13)
ok("step 16 marker", MARK in step16)
ok(
    "step 13 allow-listed text kept",
    "the `/pr-review` verdict and what was done with each finding, and a **Learnings**" in step13,
)
ok("step 16 allow-listed text kept", "16. **Report** the pull request link, the `/pr-review` verdict" in step16)

rules = read("skills/sync-from-wasensi/references/generalisation-rules.md")
ok("keep rule", "**Local review loop** (keep)" in rules and "`aiw local-review`" in rules)

ok("no slack ids", not re.search(r"\b[CUW][A-Z0-9]{8,}\b", step12 + step13 + step16))

sys.exit(1 if fails else 0)
