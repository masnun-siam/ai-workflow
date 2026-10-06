"""Board data: pure core plus I/O edges (CONTEXT.md Board/Card)."""

from __future__ import annotations

import json
import os
import re
import subprocess

from shared import data_dir

STATIONS = ["researcher", "planner", "sdet", "dev", "verifier", "reviewer", "fixer", "done"]

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS_PATH = os.path.join(REPO_ROOT, "skills", "worklog", "projects.json")

_GITHUB_URL_RE = re.compile(r"github\.com/([^/\s]+)/([^/\s]+)/(?:pull|issues)/(\d+)")


def build_board(records, projects, fetch_title):
    """Pure core: records -> Board. No filesystem or `gh` I/O in here.

    records: list of {"ledger": dict, "mtime": float, "dir_name": str}
    projects: {"owner/repo": "Human Name"} mapping (skills/worklog/projects.json)
    fetch_title: (owner, repo, issue) -> str
    """
    columns = {station: [] for station in STATIONS}

    resolved = [
        (rec, *_resolve_owner_repo(rec["ledger"], rec["dir_name"], projects)) for rec in records
    ]
    latest = {}
    for rec, owner, repo in resolved:
        key = (owner, repo, rec["ledger"]["issue"])
        if key not in latest or rec["mtime"] > latest[key][0]["mtime"]:
            latest[key] = (rec, owner, repo)

    for rec, owner, repo in latest.values():
        ledger = rec["ledger"]
        # "done" is a Ledger status, not an entry in stations[] (which stops at the last
        # real station, e.g. fixer) — route it to the done column explicitly.
        station = "done" if ledger["status"] == "done" else ledger["stations"][ledger["currentIndex"]]
        context = ledger.get("context", {})
        card = {
            "owner": owner,
            "repo": repo,
            "project": projects.get(f"{owner}/{repo}", f"{owner}/{repo}"),
            "issue": ledger["issue"],
            "title": fetch_title(owner, repo, ledger["issue"]),
            "escalated": ledger["status"] == "escalated",
            "trace": ledger.get("trace") or [],
            "bounceCounts": ledger.get("bounceCounts") or {},
            "classification": ledger.get("classification"),
            "pr": context.get("pr"),
            "branch": context.get("branch"),
            "base_branch": context.get("base_branch"),
            "ci": context.get("ci"),
        }
        columns[station].append(card)

    return {"columns": [{"key": station, "cards": columns[station]} for station in STATIONS]}


def _resolve_owner_repo(ledger, dir_name, projects):
    context = ledger.get("context", {})
    for key in ("pr", "plan_comment"):
        url = context.get(key)
        if url:
            match = _GITHUB_URL_RE.search(url)
            if match:
                return match.group(1), match.group(2)
    return _guess_owner_repo_from_dir_name(dir_name, ledger["issue"], projects)


def _guess_owner_repo_from_dir_name(dir_name, issue, projects):
    suffix = f"-issue-{issue}"
    prefix = dir_name[: -len(suffix)] if dir_name.endswith(suffix) else dir_name
    for slug in projects:
        owner, _, repo = slug.partition("/")
        if prefix == f"{owner}-{repo}":
            return owner, repo
    owner, _, repo = prefix.partition("-")
    return owner, repo


def memoize_title_fetcher(fetch_title):
    """Wrap a (owner, repo, issue) -> title function with an in-memory cache.

    A live server polls every few seconds; re-running `gh issue view` per Issue on
    every poll would be slow and rate-limit-risky. Titles rarely change, so cache
    for the life of the server process.
    """
    cache: dict = {}

    def cached(owner, repo, issue):
        key = (owner, repo, issue)
        if key not in cache:
            cache[key] = fetch_title(owner, repo, issue)
        return cache[key]

    return cached


# --------------------------------------------------------------------------- I/O edges
# Thin I/O wrappers around the pure core above (per the agreed seam).


def scan_records() -> list:
    runs_dir = os.path.join(data_dir(), "runs")
    records = []
    if not os.path.isdir(runs_dir):
        return records
    for dir_name in os.listdir(runs_dir):
        run_json = os.path.join(runs_dir, dir_name, "run.json")
        if not os.path.isfile(run_json):
            continue
        with open(run_json, encoding="utf-8") as fh:
            ledger = json.load(fh)
        records.append({"ledger": ledger, "mtime": os.path.getmtime(run_json), "dir_name": dir_name})
    return records


def load_projects() -> dict:
    if not os.path.isfile(PROJECTS_PATH):
        return {}
    with open(PROJECTS_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def fetch_title(owner: str, repo: str, issue: int) -> str:
    # A number-only fallback ("Issue #N") is explicitly out per the spec, so a failed
    # `gh` call still says why rather than looking like an untitled Card.
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
