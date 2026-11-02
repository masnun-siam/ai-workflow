#!/usr/bin/env python3
"""Skill/doc lint: skills, docs and `aiw` verbs must not drift apart in mechanical ways.
`python3 test_skill_lint.py` — exit 0 = green. No network. Each rule is a `check_*` function
returning problems, fed a bad string once (negative case) and the real tree once."""

from __future__ import annotations

import glob
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Paths docs/skills name that live in the user's repo, not this one.
TARGET_REPO_DOCS = {
    "docs/faq.md",
    "docs/architecture.md",
    "docs/README.md",
    "docs/development.md",
    "docs/templates/faq.md",
}
fails = []


def ok(name, cond, detail=""):
    print(("ok  " if cond else "FAIL ") + name + ("" if cond else f": {detail}"))
    if not cond:
        fails.append(name)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def rel(*parts):
    return os.path.join(ROOT, *parts)


def check_skill_refs(text, skill_dir):
    """`../../x` resolved from the skill folder must exist."""
    return [
        p for p in re.findall(r"(?<![\w.])\.\./\.\./[\w./-]*\w", text) if not os.path.exists(os.path.join(skill_dir, p))
    ]


def check_doc_paths(text, root=ROOT):
    """Backticked `docs/<file>` must exist here, unless it is a target-repo path."""
    found = re.findall(r"`(docs/[\w./-]*\w\.\w+)`", text)
    return [p for p in found if p not in TARGET_REPO_DOCS and not os.path.exists(os.path.join(root, p))]


def check_aiw_verbs(text, verbs):
    """`aiw <verb>` inside backticks or a fenced block must be a real verb."""
    bad, fenced = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        spans = [line] if fenced else re.findall(r"`([^`]*)`", line)
        for span in spans:
            bad += [v for v in re.findall(r"\baiw ([a-z][\w-]*)", span) if v not in verbs]
    return bad


def hint_flags(skill_md):
    m = re.search(r"^argument-hint:(.*)$", skill_md, re.M)
    return set(re.findall(r"--[a-z][a-z-]+", m.group(1))) if m else set()


def check_flags_documented(flags, reference):
    return sorted(f for f in flags if f not in reference)


def check_row_flags(row, hint, body):
    """Flags in a REFERENCE command row must be in the skill's argument-hint or body."""
    return sorted(f for f in set(re.findall(r"--[a-z][a-z-]+", row)) if f not in hint and f not in body)


def check_slack(text):
    # a user id has a digit (UNRESOLVED does not); your-team.slack.com is the install doc's placeholder
    return re.findall(r"\bU(?=[A-Z]*\d)[A-Z0-9]{9,11}\b|(?<![\w.-])(?!your-team\.)[\w.-]+\.slack\.com", text)


def tracked(*globs):
    out = []
    for g in globs:
        out += glob.glob(rel(g), recursive=True)
    return sorted(f for f in out if os.path.isfile(f))


# --- negative cases: every rule must catch a deliberately bad string ---
ok(
    "neg: ../../ ref to a missing file",
    check_skill_refs("see `../../guides/nope.md`", rel("skills", "x")) == ["../../guides/nope.md"],
)
ok("neg: docs/ path that does not exist", check_doc_paths("see `docs/nope.md`") == ["docs/nope.md"])
ok("neg: docs/ target-repo path is allowed", check_doc_paths("see `docs/faq.md`") == [])
ok("neg: unknown aiw verb", check_aiw_verbs("run `aiw frobnicate`", {"ui"}) == ["frobnicate"])
ok("neg: aiw verb in prose is ignored", check_aiw_verbs("an open aiw tab", {"ui"}) == [])
ok(
    "neg: argument-hint flag missing from REFERENCE",
    check_flags_documented(hint_flags("argument-hint: [--zap]"), "no flags") == ["--zap"],
)
ok("neg: REFERENCE row flag missing from skill", check_row_flags("`x [--since d]`", set(), "body") == ["--since"])
ok("neg: slack user id", check_slack("ping U01ABCDEF23") == ["U01ABCDEF23"])
ok("neg: slack host", check_slack("https://x.slack.com/archives") == ["x.slack.com"])

# --- the real tree ---
helptext = subprocess.run(
    [sys.executable, rel("run-engine", "route.py"), "--help"], capture_output=True, text=True
).stdout
m = re.search(r"\{([^}]*)\}", helptext)
verbs = set(m.group(1).split(",")) if m else set()
ok("route.py --help lists verbs", bool(verbs))

bad = []
for skill_md in tracked("skills/*/SKILL.md"):
    skill_dir = os.path.dirname(skill_md)
    for f in [skill_md] + tracked(f"skills/{os.path.basename(skill_dir)}/references/*.md"):
        bad += [f"{os.path.relpath(f, ROOT)}: {p}" for p in check_skill_refs(read(f), skill_dir)]
ok("every ../../ reference in skills resolves", not bad, bad)

bad = []
for f in tracked("docs/*.md", "CLAUDE.md", "CONTEXT.md", "README.md"):
    bad += [f"{os.path.relpath(f, ROOT)}: {p}" for p in check_doc_paths(read(f))]
ok("every docs/ file named in docs, CLAUDE, CONTEXT, README exists", not bad, bad)

bad = []
for f in tracked("skills/**/*.md", "docs/*.md", "guides/*.md", "CLAUDE.md", "README.md"):
    bad += [f"{os.path.relpath(f, ROOT)}: aiw {v}" for v in check_aiw_verbs(read(f), verbs)]
ok("every `aiw <verb>` is a real verb", not bad, bad)

reference = read(rel("docs", "REFERENCE.md"))
skills = {os.path.basename(os.path.dirname(f)): read(f) for f in tracked("skills/*/SKILL.md")}
bad = [f"{name}: {f}" for name, md in skills.items() for f in check_flags_documented(hint_flags(md), reference)]
ok("every argument-hint flag appears in REFERENCE", not bad, bad)

bad = []
for line in reference.split("\n"):
    r = re.match(r"\| `/ai-workflow:([\w-]+)([^`]*)`", line)
    if r and r.group(1) in skills:
        md = skills[r.group(1)]
        bad += [f"{r.group(1)}: {f}" for f in check_row_flags(line, hint_flags(md), md)]
ok("every REFERENCE command-row flag is in the skill", not bad, bad)

bad = []
for f in tracked("skills/**/*", "guides/*", "templates/*", "agents/*", "docs/*.md", "CLAUDE.md"):
    try:
        bad += [f"{os.path.relpath(f, ROOT)}: {s}" for s in check_slack(read(f))]
    except UnicodeDecodeError:
        pass
ok("no Slack user id or workspace host", not bad, bad)

if fails:
    print(f"\n{len(fails)} failed")
    sys.exit(1)
