"""Plain-assert checks for repo_skills.py."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import repo_skills as rs  # noqa: E402

passed = 0


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


def copy(cwd: str, name: str) -> str:
    d = os.path.join(cwd, ".claude", "skills", name)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "SKILL.md")


# --------------------------------------------------------------------------- names

n = rs.names()
assert {"implement-issue", "pr-grind", "verifier-locally"} <= n and "day" not in n, n
ok("names() lists the plugin's skill folders")

with tempfile.TemporaryDirectory() as tmp:
    # ----------------------------------------------------------------------- FR-1 which copy
    have, none = os.path.join(tmp, "have"), os.path.join(tmp, "none")
    os.makedirs(none)
    open(copy(have, "implement-issue"), "w").close()
    for src in ("/implement-issue 12", "/ai-workflow:implement-issue 12"):
        assert rs.resolve(src, have) == "/implement-issue 12"
        assert rs.resolve(src, none) == "/ai-workflow:implement-issue 12"
    ok("a readable SKILL.md picks /<name>, else /ai-workflow:<name>, from either spelling")

    os.symlink(os.path.join(tmp, "missing"), copy(have, "pr-review"))
    copy(have, "pr-grind")  # folder only, no SKILL.md
    target = os.path.join(tmp, "real.md")
    open(target, "w").close()
    os.symlink(target, copy(have, "create-prd"))
    assert not rs.has_copy(have, "pr-review"), "broken symlink"
    assert not rs.has_copy(have, "pr-grind"), "folder without SKILL.md"
    assert rs.has_copy(have, "create-prd"), "symlink to a valid file"
    assert not rs.has_copy(None, "pr-review")
    assert not rs.has_copy(os.path.join(tmp, "gone"), "implement-issue")
    assert rs.resolve("/implement-issue 1", None) == "/ai-workflow:implement-issue 1"
    assert rs.resolve("/implement-issue 1", os.path.join(tmp, "gone")) == "/ai-workflow:implement-issue 1"
    ok("broken symlink, empty folder, None and missing cwd count as no copy; never raises")

    # ----------------------------------------------------------------------- FR-2 rewrite
    open(copy(have, "verifier-locally"), "w").close()
    t = "Final QA for #3: run /ai-workflow:verifier-locally against the branch"
    assert rs.resolve(t, have) == "Final QA for #3: run /verifier-locally against the branch"
    ok("inline mentions are rewritten")

    t = "/implement-issue 4 then /pr-review"
    assert rs.resolve(t, have) == "/implement-issue 4 then /ai-workflow:pr-review"
    ok("two skills in one text: one with a copy, one without")

    for keep in (
        "/pr-review-strict",
        "/verifier-locally/SKILL.md",
        "/create-prd.md",
        "/pr-grind:x",
        "/day 3",
        "docs/pr-review/x",
        "https://github.com/o/pr-review/pull/1",
        "see docs/implement-issue and https://x/ai-workflow:implement-issue",
    ):
        assert rs.resolve(keep, have) == keep, keep
        assert rs.resolve(keep, none) == keep, keep
    ok("near-misses, non-plugin names, paths and URLs are left alone")

    for src, want in (
        ("`/create-prd`", "`/create-prd`"),
        ("(/pr-review)", "(/ai-workflow:pr-review)"),
        ("[/pr-review]", "[/ai-workflow:pr-review]"),
        ('"/pr-review"', '"/ai-workflow:pr-review"'),
        ("'/pr-review'", "'/ai-workflow:pr-review'"),
        ("then run /pr-review.", "then run /ai-workflow:pr-review."),
        ("run /pr-review:", "run /ai-workflow:pr-review:"),
        ("/pr-review, then", "/ai-workflow:pr-review, then"),
        (
            "/pr-review; /pr-review! /pr-review?",
            "/ai-workflow:pr-review; /ai-workflow:pr-review! /ai-workflow:pr-review?",
        ),
        ("`/ai-workflow:create-prd`", "`/create-prd`"),
    ):
        assert rs.resolve(src, have) == want, (src, rs.resolve(src, have))
    ok("bracketed, quoted and punctuated commands are rewritten")

    for t in ("/implement-issue 4 then /ai-workflow:pr-review. (/verifier-locally)", "/pr-grind T"):
        for cwd in (have, none):
            once = rs.resolve(t, cwd)
            assert rs.resolve(once, cwd) == once
    ok("resolve is idempotent")

    assert rs.resolve("", have) == "" and rs.resolve(None, have) is None and rs.resolve(5, have) == 5
    ok("empty and non-string text is returned unchanged")

# --------------------------------------------------------------------------- parse / is_skill

assert rs.parse("/pr-grind https://x") == ("pr-grind", "https://x")
assert rs.parse("/ai-workflow:pr-grind https://x") == ("pr-grind", "https://x")
assert rs.parse("/refine-issues") == ("refine-issues", "")
assert rs.parse("/day log\nmore") == ("day", "log\nmore")
assert rs.parse("plain text") is None and rs.parse("") is None and rs.parse(None) is None
ok("parse gives (name, rest) for either spelling, any name, else None")

assert rs.is_skill("/ai-workflow:pr-grind T", "pr-grind", "T")
assert rs.is_skill("/pr-grind T ", "pr-grind", "T")
assert not rs.is_skill("/pr-grind T --channel C", "pr-grind", "T")
assert rs.is_skill("/pr-grind T --channel C", "pr-grind")
assert not rs.is_skill("/pr-review 3", "pr-grind")
assert not rs.is_skill("plain text", "pr-grind")
assert rs.is_skill("/refine-issues", "refine-issues", "")
ok("is_skill matches name and, when given, the exact argument")

print(f"{passed} passed")
