#!/usr/bin/env python3
"""Self-check for `aiw refined`. `python3 run-engine/test_refined.py` — exit 0 = green."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
AIW = os.path.join(os.path.dirname(HERE), "bin", "aiw")
sys.path.insert(0, HERE)

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
    subprocess.run(["git", "-C", repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main"], check=True)
    assert run("init", run_dir, "--issue", "7", "--repo", repo).returncode == 0

    # parse(): the happy path, every fallback reason, and explicit overrides.
    h, why = refined.parse(["bug", "refined"], BODY + "\n", repo)
    assert why == "" and h["test_root"] == "tests/" and h["base_branch"] == "main", why
    assert h["acceptance_criteria"] == ["Returns 200 for a valid id", "Corner: unknown id returns 404"]
    assert h["test_cases"][0] == "[acceptance] Returns 200 for a valid id"
    assert "1. In `app/x.py:10`" in h["plan_md"] and "## Test root\ntests/" in h["plan_md"]

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

print("test_refined: ok")
