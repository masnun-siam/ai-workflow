#!/usr/bin/env python3
"""E1 guard: the run-issue system stays gone and the dev-workflow import stays faithful.
`python3 test_plugin_text.py` — exit 0 = green. No network; the source comparison is skipped
when the Shahria-skills checkout is absent (CI)."""

from __future__ import annotations

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELF = os.path.relpath(os.path.abspath(__file__), ROOT)
SRC = os.path.expanduser("~/Documents/Projects/Personal/Shahria-skills")
IMPORT_COMMIT = "0a487c6"
KEPT_VERBS = {"ui", "paths", "ask", "ci", "threads"}
REMOVED_VERBS = (
    "init|route|precheck|classify|resolve-review|skip-review|set|stack|worktree|maintree|pr|gitnexus"
    "|epic|refined|project-status|review|peer-review"
)
# Allowed to name the old system: the record of what was removed, and the PRD/task list for it.
EXEMPT = {"CHANGELOG.md", "docs/prds/dev-workflow-replacement.md", "docs/tasks/dev-workflow-replacement.md", SELF}
# FR-2: the only edits allowed against the source, as (file, source text, our text).
SUBS = [
    ("guides/skills.md", "/dev-workflow:<name>", "/ai-workflow:<name>"),
    ("guides/skills.md", "~/Documents/Projects/Personal/Shahria-skills", "~/Documents/Projects/Personal/ai-workflow"),
    ("skills/sync-from-wasensi/SKILL.md", "this dev-workflow plugin", "this ai-workflow plugin"),
    (
        "skills/sync-from-wasensi/references/generalisation-rules.md",
        "~/Documents/Projects/Personal/Shahria-skills",
        "~/Documents/Projects/Personal/ai-workflow",
    ),
]

fails = []


def ok(name, cond, detail=""):
    print(("ok  " if cond else "FAIL ") + name + ("" if cond else f": {detail}"))
    if not cond:
        fails.append(name)


def repo_files():
    out = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split("\n")
    return [f for f in out if f and os.path.isfile(os.path.join(ROOT, f)) and "/vendor/" not in f]


def text(f):
    try:
        with open(os.path.join(ROOT, f), encoding="utf-8") as fh:
            return fh.read()
    except UnicodeDecodeError:
        return ""


def hits(files, pattern):
    rx = re.compile(pattern)
    return [f"{f}:{i}" for f in files for i, ln in enumerate(text(f).split("\n"), 1) if rx.search(ln)]


# 1. aiw --help lists exactly the kept verbs.
helptext = subprocess.run(
    [sys.executable, os.path.join(ROOT, "run-engine", "route.py"), "--help"], capture_output=True, text=True
).stdout
m = re.search(r"\{([^}]*)\}", helptext)
verbs = set(m.group(1).split(",")) if m else set()
ok("aiw --help lists only the kept verbs", verbs == KEPT_VERBS, sorted(verbs))

files = [f for f in repo_files() if f not in EXEMPT]

# 2. No run-issue names anywhere outside the exempt record.
bad = hits(files, r"run-issue|run\.json|run-fixer|run-specialist")
ok("no run-issue, run.json, run-fixer or run-specialist outside CHANGELOG/PRD/task list", not bad, bad[:10])

# 3. Kept and imported text names no deleted agent, removed verb, dev-workflow prefix or Shahria-skills.
prose = [f for f in files if f.endswith(".md") or f.startswith(("skills/", "agents/", "guides/", "templates/"))]
agents = r"run-(planner|researcher|sdet|dev|verifier|reviewer|ci|grinder|lessons|laravel-review)\b|gh-issue-factchecker"
bad = hits(prose, agents + rf"|\baiw ({REMOVED_VERBS})\b|/dev-workflow:|Shahria-skills")
ok("kept files name no deleted agent, removed aiw verb, /dev-workflow: or Shahria-skills", not bad, bad[:10])
ok(
    "agents/ holds only peer-reviewer and worklog-runner",
    sorted(os.listdir(os.path.join(ROOT, "agents"))) == ["peer-reviewer.md", "worklog-runner.md"],
)
ok("commands/ is gone", not os.path.exists(os.path.join(ROOT, "commands")))

# 4. Imported files match the source at the import commit, apart from the FR-2 substitutions.
if os.path.isdir(os.path.join(SRC, ".git")):
    names = subprocess.run(
        ["git", "-C", SRC, "ls-tree", "-r", "--name-only", IMPORT_COMMIT], capture_output=True, text=True, check=True
    ).stdout.split()
    diffs = []
    for f in (n for n in names if n.startswith(("guides/", "templates/", "skills/"))):
        want = subprocess.run(["git", "-C", SRC, "show", f"{IMPORT_COMMIT}:{f}"], capture_output=True, text=True).stdout
        for sf, a, b in SUBS:
            if sf == f:
                want = want.replace(a, b)
        if text(f) != want:
            diffs.append(f)
    ok("imported files match the source apart from FR-2 substitutions", not diffs, diffs)
    ok(
        "set-status.sh keeps its executable bit",
        os.access(os.path.join(ROOT, "skills/implement-issue/set-status.sh"), os.X_OK),
    )
else:
    print("skip source comparison: Shahria-skills checkout absent")

if fails:
    print(f"{len(fails)} check(s) failed")
    sys.exit(1)
print("all plugin text checks passed")
