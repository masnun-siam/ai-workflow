#!/usr/bin/env python3
"""E1 guard: the run-issue system stays gone and the imported scripts stay executable.
`python3 test_plugin_text.py` — exit 0 = green. No network."""

from __future__ import annotations

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELF = os.path.relpath(os.path.abspath(__file__), ROOT)
KEPT_VERBS = {"ui", "paths", "ask", "ci", "threads", "grind-mode", "dispatch"}
REMOVED_VERBS = (
    "init|route|precheck|classify|resolve-review|skip-review|set|stack|worktree|maintree|pr|gitnexus"
    "|epic|refined|project-status|review|peer-review"
)
# Allowed to name the old system: the record of what was removed, and the PRD/task list for it.
EXEMPT = {"CHANGELOG.md", "docs/prds/dev-workflow-replacement.md", "docs/tasks/dev-workflow-replacement.md", SELF}
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
    "agents/ holds only away-answerer, peer-reviewer and worklog-runner",
    sorted(os.listdir(os.path.join(ROOT, "agents"))) == ["away-answerer.md", "peer-reviewer.md", "worklog-runner.md"],
)
ANSWERER_TOOLS = {
    "Read",
    "Grep",
    "Glob",
    "Bash(gh issue view:*)",
    "Bash(gh issue list:*)",
    "Bash(gh pr view:*)",
    "Bash(gh pr diff:*)",
    "Bash(gh pr list:*)",
    "Bash(gh pr checks:*)",
    "Bash(git status:*)",
    "Bash(git blame:*)",
}
with open(os.path.join(ROOT, "agents", "away-answerer.md"), encoding="utf-8") as f:
    answerer = f.read()
tools_line = [ln for ln in answerer.splitlines() if ln.startswith("tools:")]
tools = tools_line[0][len("tools:") :].strip().split(", ") if tools_line else []
ok(
    "away-answerer tools line is exactly the read-only allow-list",
    len(tools) == len(ANSWERER_TOOLS) and set(tools) == ANSWERER_TOOLS,
    tools,
)
ok(
    "away-answerer has no write, bare-shell, gh api or git log/show/diff tool",
    not any(
        t in ("Write", "Edit", "NotebookEdit", "Bash", "Bash(gh:*)", "Bash(git:*)")
        or re.search(r"gh api|git (log|show|diff)", t)
        for t in tools
    ),
)
ok("away-answerer runs on opus", "\nmodel: opus\n" in answerer)
ok("commands/ is gone", not os.path.exists(os.path.join(ROOT, "commands")))

# 4. Imported scripts keep their executable bit (skills call them directly). The byte-compare against
# the import commit was dropped: /sync-from-wasensi and the improve loop change these files by design.
for script in ("skills/implement-issue/set-status.sh", "skills/skill-feedback/collect.sh"):
    ok(f"{script} keeps its executable bit", os.access(os.path.join(ROOT, script), os.X_OK))

if fails:
    print(f"{len(fails)} check(s) failed")
    sys.exit(1)
print("all plugin text checks passed")
