#!/usr/bin/env python3
"""Self-check for `aiw refined`. `python3 run-engine/test_refined.py` — exit 0 = green."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
AIW = os.path.join(os.path.dirname(HERE), "bin", "aiw")
sys.path.insert(0, HERE)

import dispatch  # noqa: E402
import refined  # noqa: E402

BODY = """## What
Do the thing.

## Acceptance Criteria
- [ ] Returns 200 for a valid id
- [ ] Corner: unknown id returns 404

## How
1. In `app/x.py:10`, add the handler.
2. Verify: `pytest tests/`.

## Notes
none
"""


def run(*argv):
    return subprocess.run([AIW, *argv], capture_output=True, text=True)


with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as tmp:
    run_dir = os.path.join(tmp, "run")
    os.makedirs(os.path.join(repo, "tests"))
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(
        ["git", "-C", repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main"], check=True
    )
    assert run("init", run_dir, "--issue", "7", "--repo", repo).returncode == 0

    # parse(): the happy path, every fallback reason, and explicit overrides.
    h, why = refined.parse(["bug", "refined"], BODY + "\n", repo)
    assert why == "" and h["test_root"] == "tests/" and h["base_branch"] == "main", why
    assert h["acceptance_criteria"] == ["Returns 200 for a valid id", "Corner: unknown id returns 404"]
    assert h["test_cases"][0] == "[acceptance] Returns 200 for a valid id"
    assert "1. In `app/x.py:10`" in h["plan_md"] and "## Test root\ntests/" in h["plan_md"]

    numbered = BODY.replace("- [ ] Returns", "1. Returns").replace("- [ ] Corner", "2. Corner")
    assert refined.parse(["refined"], numbered, repo)[0]["acceptance_criteria"] == h["acceptance_criteria"]
    assert refined.parse(["bug"], BODY, repo)[1] == "no `refined` label"
    assert "Acceptance" in refined.parse(["refined"], BODY.replace("- [ ] ", "").replace("- ", ""), repo)[1]
    assert "How" in refined.parse(["refined"], BODY.replace("1. ", "").replace("2. ", ""), repo)[1]
    assert "placeholder" in refined.parse(["refined"], BODY + "[placeholder: owner]", repo)[1]

    os.makedirs(os.path.join(repo, "spec"))  # two conventional roots -> ambiguous
    assert "Test root" in refined.parse(["refined"], BODY, repo)[1]
    body2 = BODY.replace("2. Verify", "Test root: `pkg/tests/`\nBase branch: develop\n2. Verify")
    h, why = refined.parse(["refined"], body2, repo)
    assert why == "" and h["test_root"] == "pkg/tests/" and h["base_branch"] == "develop", why
    assert "not a repo-relative" in refined.parse(["refined"], body2.replace("pkg/tests/", "../x"), repo)[1]

    # CLI: not refined -> exit 1, nothing written; refined -> both envelopes route cleanly.
    body_file = os.path.join(tmp, "body.md")
    with open(body_file, "w") as fh:
        fh.write(body2)
    p = run("refined", run_dir, "--labels", "bug", "--body-file", body_file)
    assert p.returncode == 1 and "not refined" in p.stderr, p.stderr
    assert not os.path.exists(os.path.join(run_dir, "10-plan.json"))

    p = run("refined", run_dir, "--labels", "refined,bug", "--body-file", body_file)
    assert p.returncode == 0 and "test_root=pkg/tests/" in p.stdout, p.stderr
    with open(os.path.join(run_dir, "10-plan.json")) as fh:
        plan = json.load(fh)
    assert plan["station"] == "planner" and plan["issue"] == 7 and plan["evidence"]["skipped"]
    for artifact in ("00-readiness.json", "10-plan.json"):
        p = run("route", run_dir, artifact)
        assert p.returncode == 0, (artifact, p.stdout, p.stderr)

# Contract: a body built from the section list /gh-issue actually emits must parse as refined,
# so its issues take the fast path instead of silently falling back to the planner.
GH_ISSUE_MD = os.path.join(HERE, "..", "commands", "gh-issue.md")
with open(GH_ISSUE_MD, encoding="utf-8") as fh:
    sections_line = next(line for line in fh if line.strip().startswith("- Body sections:"))
names = re.findall(r"\*\*([^*]+)\*\*", sections_line)
assert {"Acceptance Criteria", "How"} <= set(names), names
# The fast path also needs the literal field names refined.field() looks for in How.
assert "Test root:" in sections_line and "Base branch:" in sections_line, sections_line
filled = {
    "Acceptance Criteria": "- [ ] Creates a product\n- [ ] Corner: duplicate SKU returns 422",
    "How": "1. Add the migration, see [the PRD](https://github.com/o/r/blob/master/docs/prd/p.md).\n"
    "2. Verify: `php artisan test`.\nTest root: tests/Feature/\nBase branch: develop",
    "Notes": "Task 2 of [docs/tasks/p.md](https://github.com/o/r/blob/master/docs/tasks/p.md)",
}
contract = "\n\n".join(f"## {n}\n{filled.get(n, 'Some text.')}" for n in names)
with tempfile.TemporaryDirectory() as repo:
    h, why = refined.parse(["refined"], contract, repo)
    assert why == "" and h["test_root"] == "tests/Feature/" and h["base_branch"] == "develop", why
    assert h["acceptance_criteria"] == ["Creates a product", "Corner: duplicate SKU returns 422"]
    # Hyperlink trap: a linked field value yields the link text, not the markdown.
    linked = contract.replace(
        "Test root: tests/Feature/", "Test root: [tests/Feature/](https://github.com/o/r/tree/master/tests/Feature)"
    )
    h, why = refined.parse(["refined"], linked, repo)
    assert why == "" and h["test_root"] == "tests/Feature/", (why, h and h["test_root"])

# The refine-issues template, filled in, is a refined issue; left unfilled, it is not.
with open(os.path.join(HERE, "..", "skills", "refine-issues", "templates", "issue.md"), encoding="utf-8") as fh:
    TPL = fh.read()
with tempfile.TemporaryDirectory() as repo:
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(
        ["git", "-C", repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main"], check=True
    )
    filled = re.sub(r"<[^>\n]+>", "x", TPL).replace("Test root: x", "Test root: tests/")
    h, why = refined.parse(["refined"], filled, repo)
    assert why == "" and h["test_root"] == "tests/" and h["base_branch"] == "main", why
    assert dispatch.dor_gaps(filled) == [], f"filled refine-issues template has DoR gaps: {dispatch.dor_gaps(filled)}"
    h, why = refined.parse(["refined"], TPL, repo)
    assert h is None and "placeholder" in why, f"unfilled refine-issues template must not pass: {why!r}"
    unset_base = filled.replace("Test root: tests/", "Test root: tests/\nBase branch: <branch>")
    assert "`Base branch:` is still a <placeholder>" == refined.parse(["refined"], unset_base, repo)[1]
print("ok  refine-issues template passes aiw refined and the DoR only when filled in")

print("test_refined: ok")
