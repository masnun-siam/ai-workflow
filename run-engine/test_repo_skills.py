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

# ----------------------------------------------------------------------- personal plugin
with tempfile.TemporaryDirectory() as cfg:
    old = os.environ.get("CLAUDE_CONFIG_DIR")
    os.environ["CLAUDE_CONFIG_DIR"] = cfg
    try:
        assert not rs.personal_plugin_installed(), "no file"
        assert (
            rs.resolve("/dump x", None) == "/dump x"
            and rs.resolve("/ai-workflow:worklog", None) == "/ai-workflow:worklog"
        )
        os.makedirs(os.path.join(cfg, "plugins"))
        f = os.path.join(cfg, "plugins", "installed_plugins.json")
        for bad in ("not json", "[]", '{"plugins": []}', '{"plugins": {"ai-workflow@m": []}}'):
            open(f, "w").write(bad)
            assert not rs.personal_plugin_installed(), bad
        ok("missing, unreadable or foreign plugin file means not installed; commands left unchanged")
        open(f, "w").write('{"version": 2, "plugins": {"ai-workflow-personal@m": [{}]}}')
        assert rs.personal_plugin_installed()
        for src in ("/dump x", "/ai-workflow:dump x", "/ai-workflow-personal:dump x"):
            assert rs.resolve(src, None) == "/ai-workflow-personal:dump x", src
        assert (
            rs.resolve("/sync-from-wasensi and /worklog today", None)
            == "/ai-workflow-personal:sync-from-wasensi and /ai-workflow-personal:worklog today"
        )
        assert rs.resolve("/pr-review 1", None) == "/ai-workflow:pr-review 1"
        ok("installed: dump, worklog and sync-from-wasensi run as /ai-workflow-personal:<name>")
    finally:
        os.environ.pop("CLAUDE_CONFIG_DIR", None) if old is None else os.environ.__setitem__("CLAUDE_CONFIG_DIR", old)

# ----------------------------------------------------------------------- codex_prompt
BASE = "Base directory for this skill: "

with tempfile.TemporaryDirectory() as tmp:
    have, none = os.path.join(tmp, "have"), os.path.join(tmp, "none")
    os.makedirs(none)
    p = rs.codex_prompt("/implement-issue 12", none)
    assert p.startswith(BASE + os.path.join(rs._SKILLS_DIR, "implement-issue") + "\n\n# Implement an issue\n"), p[:200]
    assert p.endswith("\n\nARGUMENTS: 12") and "argument-hint:" not in p and "name: implement-issue" not in p
    ok("plugin copy: base directory, body without frontmatter, ARGUMENTS last")

    open(copy(have, "implement-issue"), "w").write("---\nname: implement-issue\n---\n\nREPO COPY BODY\n")
    p = rs.codex_prompt("/implement-issue 12", have)
    want = BASE + os.path.join(have, ".claude", "skills", "implement-issue") + "\n\nREPO COPY BODY\n\nARGUMENTS: 12"
    assert p == want, p
    assert rs.resolve("/implement-issue 12", have) == "/implement-issue 12"
    ok("repo copy wins; the stored command keeps the repo spelling")

    for cwd in (have, none):
        a = rs.codex_prompt("/implement-issue 12", cwd)
        assert (
            a
            == rs.codex_prompt("/ai-workflow:implement-issue 12", cwd)
            == rs.codex_prompt("  \n/implement-issue 12", cwd)
        )
    assert rs.codex_prompt("/implement-issue 12\nsecond line", have).endswith("ARGUMENTS: 12\nsecond line")
    assert (
        rs.codex_prompt("/implement-issue", have)
        == BASE + os.path.join(have, ".claude", "skills", "implement-issue") + "\n\nREPO COPY BODY"
    )
    assert rs.codex_prompt("/implement-issue 3 then /pr-review", have).endswith(
        "ARGUMENTS: 3 then /ai-workflow:pr-review"
    )
    ok("both spellings and leading space agree; multi-line, empty and resolved arguments")

    for raw, body in (
        ("no frontmatter\n---\nrule\n", "no frontmatter\n---\nrule"),
        ("---\nname: x\nunclosed\n", "---\nname: x\nunclosed"),
        ("---\nname: x\n---\nabove\n\n---\n\nbelow\n", "above\n\n---\n\nbelow"),
    ):
        open(copy(have, "create-prd"), "w").write(raw)
        assert rs.codex_prompt("/create-prd", have).endswith("\n\n" + body), raw
    ok("frontmatter: none, unclosed and a later --- rule are kept")

    copy(have, "pr-grind")  # folder only: plugin copy runs
    assert rs.codex_prompt("/pr-grind 1", have).startswith(BASE + os.path.join(rs._SKILLS_DIR, "pr-grind"))
    for t in ("/frobnicate 1", "plain text", "Final QA for #3: run /ai-workflow:verifier-locally", BASE + "x"):
        for cwd in (have, none, None, os.path.join(tmp, "gone")):
            assert rs.codex_prompt(t, cwd) == rs.resolve(t, cwd), (t, cwd)
    assert rs.codex_prompt(None, have) is None and rs.codex_prompt("", have) == "" and rs.codex_prompt(5, have) == 5
    assert rs.codex_prompt("/implement-issue 1", None).startswith(
        BASE + os.path.join(rs._SKILLS_DIR, "implement-issue")
    )
    old_dir = rs._SKILLS_DIR
    rs._SKILLS_DIR = os.path.join(tmp, "plugin")
    try:
        os.makedirs(os.path.join(rs._SKILLS_DIR, "pr-review"))
        open(os.path.join(rs._SKILLS_DIR, "pr-review", "SKILL.md"), "wb").write(b"\xff\xfe bad")  # not UTF-8
        assert rs.codex_prompt("/pr-review 1", none) == "/ai-workflow:pr-review 1"
        assert rs.codex_prompt("/frobnicate 1", none) == "/frobnicate 1"
    finally:
        rs._SKILLS_DIR = old_dir
    ok("unknown skill, plain text, inline mention, unreadable SKILL.md, None/empty/non-string: resolve's text")

with tempfile.TemporaryDirectory() as cfg:
    old = os.environ.get("CLAUDE_CONFIG_DIR")
    os.environ["CLAUDE_CONFIG_DIR"] = cfg
    try:
        repo, home = os.path.join(cfg, "repo"), os.path.join(cfg, "personal")
        open(copy(repo, "dump"), "w").write("REPO DUMP")
        for cwd in (None, repo):
            assert rs.codex_prompt("/dump x", cwd) == "/dump x", "not installed"
            assert rs.codex_prompt("/ai-workflow:dump x", cwd) == "/ai-workflow:dump x"
        os.makedirs(os.path.join(cfg, "plugins"))
        f = os.path.join(cfg, "plugins", "installed_plugins.json")
        for bad in (
            "not json",
            '{"plugins": {"ai-workflow-personal@m": [{}]}}',
            '{"plugins": {"ai-workflow-personal@m": [{"installPath": 5}]}}',
            '{"plugins": {"ai-workflow-personal@m": [{"installPath": "%s"}]}}' % home,
        ):
            open(f, "w").write(bad)
            for src in ("/dump x", "/ai-workflow:dump x"):
                assert rs.codex_prompt(src, repo) == rs.resolve(src, repo), (bad, src)
                assert not rs.codex_prompt(src, repo).startswith(BASE), (bad, src)
        os.makedirs(os.path.join(home, "skills", "dump"))
        open(os.path.join(home, "skills", "dump", "SKILL.md"), "w").write("---\nname: dump\n---\nPERSONAL DUMP\n")
        for cwd in (None, repo):
            want = BASE + os.path.join(home, "skills", "dump") + "\n\nPERSONAL DUMP\n\nARGUMENTS: x"
            assert rs.codex_prompt("/dump x", cwd) == want, rs.codex_prompt("/dump x", cwd)
        assert rs.codex_prompt("/pr-review 1", None).startswith(BASE + os.path.join(rs._SKILLS_DIR, "pr-review"))
        ok("personal skills come from the installed personal plugin only, else plain text")
    finally:
        os.environ.pop("CLAUDE_CONFIG_DIR", None) if old is None else os.environ.__setitem__("CLAUDE_CONFIG_DIR", old)

# ----------------------------------------------------------------------- codex_pointer
READ = "Read the skill file "
with tempfile.TemporaryDirectory() as tmp:
    have, none = os.path.join(tmp, "have"), os.path.join(tmp, "none")
    os.makedirs(none)
    folder = os.path.join(rs._SKILLS_DIR, "implement-issue")
    p = rs.codex_pointer("/ai-workflow:implement-issue 12", none)
    assert p == f"{READ}{folder}/SKILL.md and follow it; paths in it are relative to it. ARGUMENTS: 12", p
    assert p.count(folder) == 1 and not rs.codex_pointer("/implement-issue", none).count("ARGUMENTS")
    open(copy(have, "implement-issue"), "w").write("REPO COPY\n")
    p = rs.codex_pointer("/implement-issue 12", have)
    assert p.startswith(READ + os.path.join(have, ".claude", "skills", "implement-issue", "SKILL.md")), p
    assert rs.codex_pointer("/implement-issue 3 then /pr-review", none).endswith(
        "ARGUMENTS: 3 then /ai-workflow:pr-review"
    )
    for text in ("plain text /pr-review", "/no-such-skill 1", "", None):
        assert rs.codex_pointer(text, have) == rs.resolve(text, have), text
    copy(have, "pr-grind")  # a repo folder with no SKILL.md: the plugin copy
    assert rs.codex_pointer("/pr-grind 1", have).startswith(READ + os.path.join(rs._SKILLS_DIR, "pr-grind"))
    ok("codex_pointer: plugin and repo copy, arguments last or none, other text is resolve's")

print(f"{passed} passed")
