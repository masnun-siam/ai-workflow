"""Review grinding from the UI: start a pr-grind loop for a finished run, queue it under a cap,
pause/resume it, and tell the board and ntfy what state each loop is in. Stdlib only.

State lives where pr-grind already keeps it: <pr_grind_dir>/<owner>-<repo>-<pr>.md (headers
`paused:` / `done:`, one `## Round n` heading per round). The UI adds one store of its own,
grind_requests.json: grinds asked for (button or auto-start) that have not been started yet.
Re-entering an existing loop is ui_runner.prgrind_tick's job, not this module's.
"""

from __future__ import annotations

import glob
import json
import os
import re
import threading
import time
from datetime import datetime, timezone

import shared
import ui_board
import ui_dispatch
import ui_notify
import ui_repos
import ui_runner
import ui_sessions
from shared import warn

_lock = threading.Lock()
_PR = re.compile(r"/pull/(\d+)")
_REQUESTS = "grind_requests.json"
_NOTIFIED = "grind_notified.json"


def _store(name: str) -> str:
    return os.path.join(shared.data_dir(), name)


def _load(name: str, default):
    try:
        with open(_store(name), encoding="utf-8") as f:
            v = json.load(f)
    except (OSError, ValueError):
        return default
    return v if isinstance(v, type(default)) else default


def _save(name: str, value) -> None:
    shared.atomic_write_text(_store(name), json.dumps(value))


def _iso(dt=None) -> str:
    return ui_runner._iso(dt or datetime.now(timezone.utc))


def _pr_number(url):
    m = _PR.search(url or "")
    return int(m.group(1)) if m else None


def _state_files():
    """(path, header) for every valid pr-grind state file."""
    for path in glob.glob(os.path.join(ui_runner._prgrind_dir(), "*.md")):
        try:
            h = ui_runner._header(path)
        except OSError:
            continue
        if ui_runner._valid(h):
            yield path, h


def index() -> dict:
    """One scan for a whole board: {"pr": {(owner, repo, pr): {state, round}}, "issue": {(owner, repo, issue): state}}.
    state is queued | running | idle | paused | done."""
    sessions = ui_sessions.list_sessions()
    live = {r.get("command") for r in sessions if ui_runner._live(r)}
    by_pr, by_issue = {}, {}
    for path, h in _state_files():
        if "done" in h:
            st = "done"
        elif "paused" in h:
            st = "paused"
        elif f"/pr-grind {h['thread']}" in live:
            st = "running"
        else:
            st = "idle"
        rounds = sum(1 for ln in ui_runner._read_lines(path) if ln.startswith("## Round "))
        by_pr[(h["owner"].lower(), h["repo"].lower(), int(h["number"]))] = (
            {"state": st, "round": rounds, "reason": h["paused"]} if st == "paused" else {"state": st, "round": rounds})
    for r in sessions:  # the first-grind session runs before any state file exists
        link = r.get("link")
        if isinstance(link, dict) and str(r.get("command", "")).startswith(ui_runner.GRIND_PREFIX) and ui_runner._live(r):
            by_issue[(str(link.get("owner")).lower(), str(link.get("repo")).lower(), link.get("issue"))] = "running"
    for q in _load(_REQUESTS, []):
        by_issue.setdefault((q["owner"].lower(), q["repo"].lower(), q["issue"]), "queued")
    return {"pr": by_pr, "issue": by_issue}


def for_card(idx: dict, owner: str, repo: str, issue: int, pr_url) -> dict | None:
    """{state, round} for one run, or None when it was never grinded."""
    pr = _pr_number(pr_url)
    found = idx["pr"].get((owner.lower(), repo.lower(), pr)) if pr else None
    if found:
        return found
    st = idx["issue"].get((owner.lower(), repo.lower(), issue))
    return {"state": st, "round": 0} if st else None


def _finished_run(owner: str, repo: str, issue: int) -> dict:
    run = ui_board.load_run(owner, repo, str(issue))
    if not run or run.get("status") != "done":
        raise ValueError("the run has not finished")
    if not run.get("pr"):
        raise ValueError("this run has no PR to grind")
    return run


def _spawn(q: dict) -> None:
    owner, repo, issue = q["owner"], q["repo"], q["issue"]
    run = _finished_run(owner, repo, issue)
    slug = f"{owner}/{repo}"
    cwd, _ = ui_repos.resolve_repo(slug)
    run_dir = shared.run_dir_for(os.path.join(shared.data_dir(), "runs"), slug, issue)
    acct = next((r["claude_cmd"] for r in ui_sessions.list_sessions()
                 if r.get("claude_cmd") and isinstance(r.get("link"), dict)
                 and (str(r["link"].get("owner")).lower(), str(r["link"].get("repo")).lower(), r["link"].get("issue"))
                 == (owner.lower(), repo.lower(), issue)), None)
    text = (f"{ui_runner.GRIND_PREFIX}{run['pr']} ({slug}#{issue}). This is the one session that does "
            f"/run-issue phase 10, and nothing else of that command. Run dir: {run_dir}. Bring the stack back with "
            f"`aiw stack up \"{run_dir}\"` as phase 10 describes, dispatch the ai-workflow:run-grinder agent in open mode "
            f"with the PR URL and {slug}, run `aiw set \"{run_dir}\" grind_thread=<thread url>`, then invoke the "
            f"ai-workflow:pr-grind skill with that thread URL in this session. If the run's context already has "
            f"grind_thread, skip the trigger post and go straight to the skill.")
    ui_runner.start(text, cwd, {"owner": owner, "repo": repo, "issue": issue}, gate_questions=True, claude_cmd=acct)


def drain() -> dict:
    """Start queued grinds while under the cap. {(owner, repo, issue): error} for those that could not start."""
    errors, keep = {}, []
    with _lock:
        for q in _load(_REQUESTS, []):
            if ui_runner.grind_live() >= ui_runner.MAX_GRINDS:
                keep.append(q)
                continue
            try:
                _spawn(q)
            except (ValueError, ui_runner.RunnerError) as e:
                errors[(q["owner"], q["repo"], q["issue"])] = str(e)
                warn(f"grind: could not start {q['owner']}/{q['repo']}#{q['issue']}: {e}")
        _save(_REQUESTS, keep)
    return errors


def _enqueue(owner: str, repo: str, issue: int) -> None:
    with _lock:
        reqs = _load(_REQUESTS, [])
        if not any((q["owner"], q["repo"], q["issue"]) == (owner, repo, issue) for q in reqs):
            _save(_REQUESTS, reqs + [{"owner": owner, "repo": repo, "issue": issue}])


def request(owner: str, repo: str, issue: int) -> tuple[int, dict]:
    """The Start grinding button. 201 started, 202 queued behind the cap, 4xx/5xx with {"error"}."""
    try:
        run = _finished_run(owner, repo, issue)
    except ValueError as e:
        return 409, {"error": str(e)}
    cur = for_card(index(), owner, repo, issue, run["pr"])
    if cur:
        return 409, {"error": f"this PR is already {cur['state']}"}
    _enqueue(owner, repo, issue)
    err = drain().get((owner, repo, issue))
    if err:
        return 502, {"error": err}
    cur = for_card(index(), owner, repo, issue, run["pr"])
    return (201 if cur and cur["state"] == "running" else 202), {"state": cur["state"] if cur else "queued"}


def control(owner: str, repo: str, issue: int, action: str) -> tuple[int, dict]:
    """Pause or resume a loop through the `paused:` header pr-grind already honours."""
    run = ui_board.load_run(owner, repo, str(issue))
    pr = _pr_number(run and run.get("pr"))
    path = os.path.join(ui_runner._prgrind_dir(), f"{owner}-{repo}-{pr}.md") if pr else None
    if not path or not os.path.isfile(path):
        return 404, {"error": "no grind for this run"}
    h = ui_runner._header(path)
    if "done" in h:
        return 409, {"error": "this grind is finished"}
    if action == "pause":
        ui_runner._set_header(path, "paused", f"{_iso()} — paused from the UI")
    else:
        ui_runner._set_header(path, "paused", None)
        ui_runner._set_header(path, "next-poll", _iso())  # the next tick re-enters at once
    return 200, {"state": "paused" if action == "pause" else "idle"}


def _grind_sessions(owner: str, repo: str, issue: int) -> list:
    """The run's grind sessions, newest first: /pr-grind rounds, then the first-grind session."""
    out = [r for r in ui_sessions.list_sessions()
           if isinstance(r.get("link"), dict) and str(r["link"].get("owner")).lower() == owner.lower()
           and str(r["link"].get("repo")).lower() == repo.lower() and r["link"].get("issue") == issue
           and str(r.get("command", "")).startswith(("/pr-grind ", ui_runner.GRIND_PREFIX))]
    return sorted(out, key=lambda r: not str(r["command"]).startswith("/pr-grind "))


def last_message(owner: str, repo: str, issue: int, limit: int = 6000) -> str | None:
    """What the newest grind session said last (its final result text): the question behind a pause."""
    for rec in _grind_sessions(owner, repo, issue)[:1]:
        text = None
        try:
            with open(os.path.join(ui_sessions.session_dir(rec["id"]), "stream.jsonl"), encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"type":"result"' in line.replace(" ", ""):
                        try:
                            ev = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(ev, dict) and isinstance(ev.get("result"), str):
                            text = ev["result"]
        except OSError:
            return None
        return text[:limit] if text else None
    return None


def reply(owner: str, repo: str, issue: int, text) -> tuple[int, dict]:
    """Answer a paused grind: resume its newest session with the owner's decision, then clear the pause."""
    if not isinstance(text, str) or not text.strip():
        return 400, {"error": "reply must be a non-empty string"}
    run = ui_board.load_run(owner, repo, str(issue))
    pr = _pr_number(run and run.get("pr"))
    path = os.path.join(ui_runner._prgrind_dir(), f"{owner}-{repo}-{pr}.md") if pr else None
    if not path or not os.path.isfile(path):
        return 404, {"error": "no grind for this run"}
    if "paused" not in ui_runner._header(path):
        return 409, {"error": "this grind is not paused"}
    target = next((r for r in _grind_sessions(owner, repo, issue) if r.get("session_id")
                   and r.get("status") in ("done", "failed", "stopped")), None)
    if not target:
        return 409, {"error": "no finished grind session to reply to; use Resume instead"}
    try:
        ui_runner.send_prompt(target["id"], f"Human decision on the paused grind (PR #{pr}): {text.strip()}")
    except ValueError as e:
        return 400, {"error": str(e)}
    except (ui_runner.Conflict, ui_runner.RunnerError, OSError) as e:
        return 409, {"error": str(e)}
    ui_runner._set_header(path, "paused", None)
    return 200, {"state": "running"}


def rerun_ci(owner: str, repo: str, issue: int) -> tuple[int, dict]:
    """Rerun the failed jobs of the PR head's latest CI run: the usual way out of a grind that paused on red CI."""
    run = ui_board.load_run(owner, repo, str(issue))
    pr = _pr_number(run and run.get("pr"))
    if not pr:
        return 404, {"error": "this run has no PR"}
    slug = f"{owner}/{repo}"
    head, _ = shared.gh_json(["pr", "view", str(pr), "-R", slug, "--json", "headRefOid"], timeout=30)
    sha = head.get("headRefOid") if isinstance(head, dict) else None
    runs, _ = shared.gh_json(["run", "list", "-R", slug, "--commit", sha or "", "--json", "databaseId,status,conclusion", "-L", "10"], timeout=30)
    if not sha or not isinstance(runs, list):
        return 502, {"error": "could not read the PR's CI runs from GitHub"}
    if any(r.get("status") != "completed" for r in runs):
        return 409, {"error": "CI is still running at the head commit"}
    failed = next((r for r in runs if r.get("conclusion") in ("failure", "cancelled", "timed_out")), None)
    if not failed:
        return 409, {"error": "no failed CI run at the head commit"}
    p = shared.run(["gh", "run", "rerun", str(failed["databaseId"]), "--failed", "-R", slug], timeout=60)
    if p.returncode != 0:
        return 502, {"error": ((p.stderr or p.stdout or "gh run rerun failed").strip().splitlines() or ["gh run rerun failed"])[-1]}
    return 200, {"run": failed["databaseId"]}


def autostart() -> None:
    """Queue a grind for each finished run whose session asked for auto_grind and has none yet."""
    wants = ui_dispatch.wants_grind()
    for rec in ui_sessions.list_sessions():
        link = rec.get("link")
        if rec.get("status") != "done" or not isinstance(link, dict):
            continue
        if rec.get("auto_grind") is None:  # started before the option existed: follow its pipeline
            if not str(rec.get("command", "")).startswith("/run-issue") or \
                    f"{link.get('owner')}/{link.get('repo')}#{link.get('issue')}".lower() not in wants:
                continue
        elif rec.get("auto_grind") is not True:
            continue
        try:
            run = ui_board.load_run(link["owner"], link["repo"], str(link["issue"]))
        except (KeyError, ValueError):
            continue
        if not run or run.get("status") != "done" or not run.get("pr"):
            continue  # not finished (or no PR): keep the flag, a resumed run may still get there
        if for_card(index(), link["owner"], link["repo"], link["issue"], run["pr"]) is None:
            _enqueue(link["owner"], link["repo"], link["issue"])
        ui_sessions.update(rec["id"], auto_grind=False)


def notify_changes() -> None:
    """ntfy when a loop pauses or finishes. The first scan only records what already exists."""
    keys = {}
    for _, h in _state_files():
        base = f"{h['owner']}/{h['repo']}#{h['number']}"
        if "done" in h:
            keys[f"{base}:done"] = ("grind-done", h, h["done"])
        elif "paused" in h:
            keys[f"{base}:paused:{h['paused']}"] = ("grind-paused", h, h["paused"])
    seen = _load(_NOTIFIED, [])
    if not os.path.exists(_store(_NOTIFIED)):
        _save(_NOTIFIED, sorted(keys))
        return
    fresh = [k for k in keys if k not in seen]
    if not fresh:
        return
    for k in fresh:
        event, h, note = keys[k]
        link = {"owner": h["owner"], "repo": h["repo"]}
        issue = ui_board.issue_for_pr(f"https://github.com/{h['owner']}/{h['repo']}/pull/{h['number']}")
        if issue:
            link["issue"] = issue
        ui_notify.notify(event, {"id": k, "link": link, "repo": f"{h['owner']}/{h['repo']}",
                                 "command": f"/pr-grind {h['thread']}", "note": note})
    _save(_NOTIFIED, sorted(set(seen) | set(fresh)))


def tick() -> None:
    for step in (autostart, drain, notify_changes):
        try:
            step()
        except Exception as e:  # noqa: BLE001 - one broken step must not stop the timer
            warn(f"grind tick: {step.__name__}: {type(e).__name__}: {e}")


def start_timer(interval: float = 30.0) -> threading.Thread:
    def loop():
        while True:
            tick()
            time.sleep(interval)
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t
