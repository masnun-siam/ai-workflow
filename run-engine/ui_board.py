"""Project and issue-title helpers for the repo picker."""

from __future__ import annotations

import json
import os
import re
import subprocess

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS_PATH = os.path.join(REPO_ROOT, "skills", "worklog", "projects.json")

_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def plausible_repo(owner, repo):
    """False for owner/repo pairs that can't be a real repo (asking `gh` about them only burns its timeout)."""
    return bool(owner and repo and _SLUG_RE.match(owner) and _SLUG_RE.match(repo) and "-issue-" not in repo)


def load_projects() -> dict:
    if not os.path.isfile(PROJECTS_PATH):
        return {}
    with open(PROJECTS_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def known_projects() -> dict:
    """Worklog projects plus every registered checkout."""
    import dispatch

    return {**{slug: slug for slug in dispatch.read_checkouts()}, **load_projects()}


def fetch_title(owner: str, repo: str, issue: int) -> str:
    unavailable = f"Issue #{issue} (title unavailable)"
    try:
        proc = subprocess.run(
            ["gh", "issue", "view", str(issue), "--repo", f"{owner}/{repo}", "--json", "title", "-q", ".title"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return unavailable
    if proc.returncode != 0:
        return unavailable
    title = proc.stdout.strip()
    return title or unavailable
