#!/usr/bin/env python3
"""Repo skills win (FR-5, FR-6): every hand-off between plugin skills points to the guide's
"Repo skills win" rule, and every skill that reads a guide or hands off reads "Repository settings".
`python3 test_repo_skills_text.py` — exit 0 = green. No network."""

from __future__ import annotations

import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUIDE = "guides/engineering-workflow.md"
POINTER = "Repo skills win"
# The one hand-off that keeps its exact text: /flow parses dump's last line byte for byte.
DUMP_EXEMPT = "→ next: /create-prd <feature-folder>"
EXEMPT_SKILLS = ("sync-from-wasensi", "skill-feedback")  # PRD non-goal: their text is not touched.
# Plain mentions, not hand-offs: matched as exact substrings of the line, never by line number.
ALLOWED = (
    # A skill about itself: front matter, headings, usage and its own re-entry prompts.
    "Triggers: /dump, dump this.",
    "# /dump — Structured Capture",
    "a human-invoked `/dump`",
    "and `/dump` should place content",
    "because `/flow` parses it to start the next stage",
    "/dump (optional) → /create-prd → approval → /create-tasks → /refine-issues → dispatch",
    "Use whenever the user says /flow,",
    "# /flow — Idea",
    "`/flow` holds the user's place",
    "`/flow <raw idea",
    "say `/flow <that argument>` resumes",
    "Also runnable by hand: /peer-review reviews",
    "Use whenever the user says /peer-review,",
    "# /peer-review: a reviewer panel",
    "`/peer-review [--lenses <lens,lens>] [<artifact>]`, or from the UI: `/ai-workflow:peer-review --root",
    "or invokes /pr-grind.",
    "when a human re-invokes `/pr-grind`",
    'prompt: "/pr-grind $ARGUMENTS"',
    "/pr-grind <thread url>`. No bot mention",
    "resumes only on a human `/pr-grind <thread url>`",
    "or invokes /release-pr",
    "<data_dir>/release-pr/",
    # Commit formats of the "Improve this skill" sections.
    "`chore: update /create-prd skill",
    "`chore: update /pr-review skill",
    "`chore: update /verifier-locally skill",
    # Who owns or wrote something: no skill is run.
    "are worked out by `/refine-issues` against the current code",
    "`/refine-issues` later writes",
    "Find the epic `/create-prd` created on approval",
    "`docs/prds/` belongs to `/create-prd`",
    "is filed as a problem statement, not as raw text. `/create-prd`",
    "tells `/create-prd` this `PRD.md` is only a seed",
    "(WHAT/WHY/HOW, written by `/refine-issues`)",
    "as the `/verifier-locally` trap says",
    "the `/pr-review` verdict and what was done with each finding, and a **Learnings**",
    "every comment and `/pr-review` finding is handled",
    "(`/skill-feedback reconcile` finds it by that heading)",
    "16. **Report** the pull request link, the `/pr-review` verdict",
    "for what was already known. `/create-tasks`",
    "(`/implement-issue` moves it later)",
    "hand off to /pr-grind.",  # release-pr description; the hand-off itself is in Step 6
    "If a `/pr-grind` loop is running on it",
    "fixing belongs to `/implement-issue`",
    "leave the fix to `/implement-issue`.",
    "install them first (`/implement-issue` step 3)",
    # pr-review points at /implement-issue steps to read, not a skill to run.
    "(`/implement-issue` step 12) has no CI yet: the `/verifier-locally` results stand in for it",
    "Follow `/implement-issue`",
    "prepare it as `/implement-issue` step 3 says",
    "follow-up issue (`/implement-issue` step 8)",
    "5. **Review again, push, get CI green.** `/implement-issue` steps 12 to 14",
    "as `/implement-issue` step 14 says",
    "as `/implement-issue` steps 15 and 16 say",
    # Guides describing the process: the stages table, who creates what, the skills table.
    "| 1. Product requirements |",
    "| 2. Tasks |",
    "| 3. Refined issues |",
    "draft first, reviewed with `/pr-review`, ready when CI is green",
    "`/implement-issue <epic>` picks the lowest-numbered Ready issue",
    "| `/implement-issue` |",
    "| 5. Local verification |",
    "| 6. Review |",
    "- `/create-tasks` splits an approved PRD",
    "`/refine-issues` fills it and adds the `refined` label",
    "Created by `/create-prd` when the PRD is approved; `/create-tasks` creates it only if it is missing.",
    "`/refine-issues` moves a refin",
    "`/implement-issue` moves the rest from Backlog",
    "The issue body is corrected later by `/refine-issues`.",
    "dump's `→ next: /create-prd <folder>`, which flow reads byte for byte",
    "Used by people and by the `/pr-review` skill.",
    "its `/verifier-locally` results stand in.",
    # guides/skills.md: the table of skills.
    "| `/create-prd` |",
    "| `/create-tasks` |",
    "| `/refine-issues` |",
    "| `/implement-issue` |",
    "| `/verifier-locally` |",
    "| `/pr-review` |",
    "| `/skill-feedback` |",
    "| `/docs-updater` |",
    "| `/sync-from-wasensi` |",
)
fails = []


def ok(name, cond, detail=""):
    print(("ok  " if cond else "FAIL ") + name + ("" if cond else f": {detail}"))
    if not cond:
        fails.append(name)


def text(f):
    with open(os.path.join(ROOT, f), encoding="utf-8") as fh:
        return fh.read()


def hits(files, rx):
    return [(f, i, ln) for f in files for i, ln in enumerate(text(f).split("\n"), 1) if rx.search(ln)]


names = sorted(
    d for d in os.listdir(os.path.join(ROOT, "skills")) if os.path.isfile(os.path.join(ROOT, "skills", d, "SKILL.md"))
)
alt = "|".join(map(re.escape, names))
# `/<name>`, `/ai-workflow:<name>` or `ai-workflow:<name>`; not a path like `skills/<name>/`.
mention = re.compile(rf"(?:(?<![\w.-])/(?:ai-workflow:)?|(?<![\w/.-])ai-workflow:)(?:{alt})(?![\w-])")
skill_files = sorted(
    os.path.relpath(f, ROOT)
    for f in glob.glob(os.path.join(ROOT, "skills", "**", "*.md"), recursive=True)
    if not os.path.relpath(f, ROOT).startswith(tuple(f"skills/{s}/" for s in EXEMPT_SKILLS))
)
files = skill_files + sorted(os.path.relpath(f, ROOT) for f in glob.glob(os.path.join(ROOT, "guides", "*.md")))


# 1. Every hand-off names the skill and points to the rule; plain mentions are allow-listed.
def bare(ln):
    """The line with every allow-listed plain mention cut out."""
    for a in ALLOWED:
        ln = ln.replace(a, "")
    return ln


bad = [
    f"{f}:{i}"
    for f, i, ln in hits(files, mention)
    if POINTER not in ln and DUMP_EXEMPT not in ln and mention.search(bare(ln))
]
ok('every hand-off line points to "Repo skills win" or is an allow-listed plain mention', not bad, bad)
ok("dump keeps its exempt hand-off line", f"| `{DUMP_EXEMPT}`" in text("skills/dump/SKILL.md"))
unused = [a for a in ALLOWED if not any(a in text(f) for f in files)]
ok("every allow-list entry still matches a line", not unused, unused)

# 2. The guide states the rule inside "Repository settings".
g = text(GUIDE)
section = g.split("## Repository settings", 1)[-1].split("\n## ", 1)[0]
ok('the guide has "### Repo skills win" inside "## Repository settings"', "\n### Repo skills win\n" in section)
for point in (
    "<repo root>/.claude/skills/<name>/SKILL.md",
    "run `/<name>`",
    "`/ai-workflow:<name>`",
    "`peer-reviewer`",
    "`worklog-runner`",
    "→ next: /create-prd",
):
    ok(f"the rule says {point}", point in section.split("### Repo skills win", 1)[-1].split("\n### ", 1)[0])

# 3. Every skill that reads a plugin guide or template, or hands off, reads "Repository settings".
reads = re.compile(r"\.\./\.\./(guides|templates)/")
for name in names:
    if name in EXEMPT_SKILLS:
        continue
    body = text(f"skills/{name}/SKILL.md")
    hands_off = any(POINTER in ln or DUMP_EXEMPT in ln for ln in body.split("\n") if mention.search(ln))
    if reads.search(body) or hands_off:
        ok(f'{name} reads "Repository settings"', '"Repository settings"' in body)

if fails:
    print(f"{len(fails)} check(s) failed")
    sys.exit(1)
print("all repo-skills text checks passed")
