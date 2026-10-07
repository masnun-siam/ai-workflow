"""Board data: pure core plus I/O edges (CONTEXT.md Board/Card)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading

from shared import data_dir, extract_json_object, run_dir_for

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
            "note": (context.get("blocked_on") or "")[:200],
            "updated": rec["mtime"],
        }
        columns[station].append(card)

    for cards in columns.values():
        cards.sort(key=lambda c: c["updated"], reverse=True)

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


def run_timeline(stations, current_index, status, trace):
    """Pure core: Ledger fields -> ([{name, status, bounces}], currentStation, totals).

    A station after the current one is `bounced` if the trace shows it already ran
    (advance->X, or the source of a bounce->) and so will run again; else `pending`.
    """
    reached, bounces, total_bounces = set(), {}, 0
    for entry in trace:
        if entry.startswith("advance->"):
            reached.add(entry[len("advance->") :])
        elif entry.startswith("bounce->"):
            src, _, _ = entry[len("bounce->") :].rsplit("#", 1)[0].partition("->")
            reached.add(src)
            bounces[src] = bounces.get(src, 0) + 1
            total_bounces += 1
    done = status == "done"
    rows = []
    for i, name in enumerate(stations):
        if done or i < current_index:
            st = "done"
        elif i == current_index:
            st = status
        else:
            st = "bounced" if name in reached else "pending"
        rows.append({"name": name, "status": st, "bounces": bounces.get(name, 0)})
    current = None if done or not 0 <= current_index < len(stations) else stations[current_index]
    totals = {
        "stations": len(rows),
        "done": sum(r["status"] == "done" for r in rows),
        "bounces": total_bounces,
    }
    return rows, current, totals


_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def plausible_repo(owner, repo):
    """False for owner/repo pairs guessed from a ledger dir name that can't be a real repo.

    `_guess_owner_repo_from_dir_name` falls back to a first-dash split, which yields
    things like `masnun/siam-ai-workflow-issue-108.lean-misinit`; asking `gh` about those
    only burns its 30 s timeout.
    """
    return bool(owner and repo and _SLUG_RE.match(owner) and _SLUG_RE.match(repo) and "-issue-" not in repo)


def memoize_title_fetcher(fetch_title, pool=None):
    """Wrap a (owner, repo, issue) -> title function with an in-memory cache.

    A live server polls every few seconds; re-running `gh issue view` per Issue on
    every poll would be slow and rate-limit-risky. Titles rarely change, so cache
    for the life of the server process.

    With a `pool` (concurrent.futures executor) a cache miss returns None immediately
    and the title is filled in by a later call once the pool has fetched it, so a cold
    /board.json never waits on `gh`. Without one the fetch is synchronous.
    Implausible owner/repo pairs are never fetched and stay None.
    """
    cache: dict = {}
    pending: set = set()
    lock = threading.Lock()

    def fill(key):
        try:
            title = fetch_title(*key)
        except Exception:
            title = None
        with lock:
            if title is not None:
                cache[key] = title
            pending.discard(key)

    def cached(owner, repo, issue):
        if not plausible_repo(owner, repo):
            return None
        key = (owner, repo, issue)
        with lock:
            if key in cache:
                return cache[key]
            if pool is None:
                start = True
            else:
                start = key not in pending
                if start:
                    pending.add(key)
        if pool is None:
            cache[key] = fetch_title(*key)
            return cache[key]
        if start:
            pool.submit(fill, key)
        return None

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


_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_ISSUE_RE = re.compile(r"[1-9][0-9]{0,8}")


def _read_part(path):
    """Read-only, lenient JSON object read -> (obj, error). Never exits, unlike shared.read_json."""
    name = os.path.basename(path)
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        try:
            obj = json.loads(raw)
        except ValueError:
            if name != "10-plan.json":
                raise
            obj = extract_json_object(raw)
    except (OSError, ValueError):
        return None, f"{name}: unreadable"
    if not isinstance(obj, dict):
        return None, f"{name}: invalid JSON"
    return obj, None


def _https_url(value):
    """Only https URLs reach the browser as links (the ledger is a file, not a trust boundary we own)."""
    return value if isinstance(value, str) and value.startswith("https://") else None


def load_run(owner: str, repo: str, n: str, runs_dir=None):
    """One run from the Ledger: dict, or None if absent. ValueError on an unsafe segment."""
    if not (_NAME_RE.fullmatch(owner) and _NAME_RE.fullmatch(repo) and _ISSUE_RE.fullmatch(n)):
        raise ValueError("bad run id")
    runs_dir = runs_dir or os.path.join(data_dir(), "runs")
    run_dir = run_dir_for(runs_dir, f"{owner}/{repo}", int(n))
    run_json = os.path.join(run_dir, "run.json")
    if not os.path.isfile(run_json):
        return None
    errors = {}
    body = {"owner": owner, "repo": repo, "issue": int(n), "status": None, "currentStation": None,
            "stations": [], "trace": [], "plan": None, "pr": None, "branch": None, "title": None,
            "totals": {"stations": 0, "done": 0, "bounces": 0}, "errors": errors,
            "updated": os.path.getmtime(run_json)}
    data, err = _read_part(run_json)
    if data is not None:
        from engine import Ledger

        try:
            led = Ledger.from_dict(data)
        except (TypeError, ValueError, AttributeError):
            err = "run.json: invalid ledger"
        else:
            rows, current, totals = run_timeline(led.stations, led.current_index, led.status, led.trace)
            body.update(status=led.status, currentStation=current, stations=rows, trace=led.trace, totals=totals)
            context = data.get("context") if isinstance(data.get("context"), dict) else {}
            body.update(pr=_https_url(context.get("pr")), branch=context.get("branch") if isinstance(context.get("branch"), str) else None)
    if err:
        errors["ledger"] = err
    plan_path = os.path.join(run_dir, "10-plan.json")
    if os.path.isfile(plan_path):
        env, err = _read_part(plan_path)
        if err:
            errors["plan"] = err
        else:
            handoff = env.get("handoff")
            plan = handoff.get("plan_md") if isinstance(handoff, dict) else None
            body["plan"] = plan if isinstance(plan, str) else None
    return body


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
