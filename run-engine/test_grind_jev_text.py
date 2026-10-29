#!/usr/bin/env python3
"""Skill-text check for the jev hints in skills/pr-grind/SKILL.md. `python3 test_grind_jev_text.py` — exit 0 = green."""

from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()
import ui_runner  # noqa: E402

fails = []


def ok(name, cond, detail=""):
    print(("ok  " if cond else "FAIL ") + name + ("" if cond else f": {detail}"))
    if not cond:
        fails.append(name)


skill = open(os.path.join(os.path.dirname(HERE), "skills", "pr-grind", "SKILL.md"), encoding="utf-8").read()
CI = "`jev-ci-hint: <check name> <flaky|real|none> (<p>) — session: <fixed|flake-rerun|rerun-denied|cannot-fix>`"
FI = "`jev-finding-hint: <comment id or #n> <fix|rebut|none> (<p>) — session: <fix|rebut>`"
ok("ci-hint format", CI in skill)
ok("finding-hint format", FI in skill)
for ln in skill.splitlines():
    if "jev-ci-hint:" in ln or "jev-finding-hint:" in ln:
        ok(
            "format line not a reserved header",
            not ln.strip().strip("`- ").startswith(("paused:", "done:", "## Round ")),
        )
cmds = [ln for ln in skill.splitlines() if "aiw jev ci-hint" in ln or "aiw jev finding-hint" in ln]
ok("both verbs called", len(cmds) == 2, str(len(cmds)))
for ln in cmds:
    ok(
        "safe call shape",
        all(t in ln for t in ("mktemp -d", '--file "$t/', '> "$t/', 'rm -rf "$t"'))
        and not any(t in ln for t in ("echo", "<<", "--text", "printf")),
        ln,
    )
ok("advisory x2", skill.count("advisory") >= 2)
ok("never paste x2", skill.count("Never paste") == 2)
ok("rail 2 rule kept", "If unsure which, it is real" in skill)

d = tempfile.mkdtemp()
path = os.path.join(d, "o-r-1.md")
open(path, "w").write(
    "owner: o\nrepo: r\nnumber: 1\nci-attempt: abc — flake-rerun\n"
    "jev-ci-hint: ui / build real (0.83) — session: flake-rerun\n\n## Round 1\n"
    "jev-finding-hint: 11 fix (0.9) — session: fix\njev-finding-hint: #2 none (0) — session: rebut\n"
)
h = ui_runner._header(path)
ok("no paused/done", "paused" not in h and "done" not in h, str(h))
ok("ci-attempt unchanged", h.get("ci-attempt") == "abc — flake-rerun")
ok("one round", sum(1 for ln in open(path) if ln.startswith("## Round ")) == 1)
ui_runner._set_header(path, "ci-attempt", "abc — fixed → def")
t = open(path).read()
ok(
    "set_header keeps jev line",
    "jev-ci-hint: ui / build real (0.83) — session: flake-rerun" in t and "ci-attempt: abc — fixed → def" in t,
)

sys.exit(1 if fails else 0)
