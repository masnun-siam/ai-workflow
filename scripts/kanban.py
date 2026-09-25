#!/usr/bin/env python3
"""Generate a standalone kanban.html showing every Issue's /run-issue progress.

See docs: CONTEXT.md (Run/Ledger/Station/Board/Card vocabulary), issue #57/#58.
"""

from __future__ import annotations

import html
import json
import os
import re
import subprocess

STATIONS = ["researcher", "planner", "sdet", "dev", "verifier", "reviewer", "fixer", "done"]

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS_PATH = os.path.join(REPO_ROOT, "skills", "worklog", "projects.json")
OUTPUT_PATH = os.path.join(REPO_ROOT, "kanban.html")

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
        card = {
            "owner": owner,
            "repo": repo,
            "project": projects.get(f"{owner}/{repo}", f"{owner}/{repo}"),
            "issue": ledger["issue"],
            "title": fetch_title(owner, repo, ledger["issue"]),
            "escalated": ledger["status"] == "escalated",
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


# --------------------------------------------------------------------------- I/O edges
# Untested thin wrappers around the pure core above (per the agreed seam).


def data_dir() -> str:
    """Mirrors run-engine/shared.py::data_dir() — where run.json Ledgers live."""
    return os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.expanduser(
        "~/.claude/plugins/data/ai-workflow"
    )


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


def render_html(board: dict) -> str:
    columns_html = "\n".join(_column_html(column) for column in board["columns"])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>/run-issue Board</title>
<style>
  :root {{ --bg:#0f1115; --panel:#171a21; --panel2:#1e222b; --border:#2a2f3a;
    --text:#e6e8ec; --text-dim:#9aa2b1; --accent:#5b8def; --escalated:#e5484d; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
  h1 {{ font-size:18px; padding:16px 20px 0; margin:0; color:var(--text-dim); font-weight:600; }}
  .board {{ padding:16px 20px; overflow-x:auto; }}
  .columns {{ display:flex; gap:12px; min-width:max-content; }}
  .column {{ width:220px; flex-shrink:0; background:var(--panel);
    border:1px solid var(--border); border-radius:8px; padding:8px; }}
  .column h3 {{ font-size:12px; text-transform:uppercase; letter-spacing:.6px;
    color:var(--text-dim); margin:4px 4px 10px; display:flex; justify-content:space-between; }}
  .card {{ background:var(--panel2); border:1px solid var(--border); border-radius:6px;
    padding:10px; margin-bottom:8px; }}
  .card .project {{ font-size:10px; color:var(--text-dim); text-transform:uppercase; letter-spacing:.4px; }}
  .card .issue {{ font-size:11px; color:var(--accent); font-family:ui-monospace,monospace; margin:2px 0; }}
  .card .title {{ font-size:13px; line-height:1.35; }}
  .badge-escalated {{ display:inline-flex; margin-top:6px; background:rgba(229,72,77,.15);
    color:var(--escalated); border:1px solid rgba(229,72,77,.4); border-radius:4px;
    padding:1px 6px; font-size:10px; font-weight:700; text-transform:uppercase; }}
</style>
</head>
<body>
<h1>/run-issue Board</h1>
<div class="board"><div class="columns">
{columns_html}
</div></div>
</body>
</html>
"""


def _column_html(column: dict) -> str:
    cards_html = "\n".join(_card_html(card) for card in column["cards"])
    return f"""  <div class="column">
    <h3>{html.escape(column["key"])} <span>{len(column["cards"])}</span></h3>
    {cards_html}
  </div>"""


def _card_html(card: dict) -> str:
    badge = '<div class="badge-escalated">Escalated</div>' if card["escalated"] else ""
    return f"""    <div class="card">
      <div class="project">{html.escape(card["project"])}</div>
      <div class="issue">#{card["issue"]}</div>
      <div class="title">{html.escape(card["title"])}</div>
      {badge}
    </div>"""


def main() -> None:
    board = build_board(scan_records(), load_projects(), fetch_title)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as fh:
        fh.write(render_html(board))
    print(f"wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
