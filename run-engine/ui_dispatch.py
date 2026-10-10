"""Dispatch pipelines for `aiw ui`: run /run-issue over a batch of issues.

The UI twin of the herdr-dispatch skill. Pure scheduling (`advance`, `parse_input`)
sits at the top; the store, `gh` calls and session launches are the I/O edge below.
A pipeline lives in <data_dir>/pipelines/<id>.json; a 5s timer ticks every one.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote_plus, urlsplit

import dispatch
import epic
import ui_board
import ui_notify
import ui_repos
import ui_runner
import ui_sessions
import ui_settings
from shared import atomic_write_text, data_dir, gh_json, warn

MAX_ISSUES = 100
MAIN_TREE_PARALLEL = "main-tree runs go one at a time: use sequential, or run in worktrees"
LIVE = ("running", "waiting", "limited")
BAD = ("failed", "stopped", "skipped")
TERMINAL = ("done", "failed", "stopped", "skipped")
_ID_RE = re.compile(r"p-[0-9]{14}-[0-9a-f]{6}")
_URL_RE = re.compile(r"https?://github\.com/([\w.-]+)/([\w.-]+)/(?:issues|pull)(?:/(\d+))?(?:\?(\S*))?")
_DROP_TOKENS = ("is:issue", "is:open", "is:closed", "state:open")

_lock = threading.RLock()  # guards mutations + ticks; reads go straight to the atomic files


# --------------------------------------------------------------------------- pure core


def parse_input(text: str):
    """-> (slug|None, kind, value). kind: "query" (str) | "issues" (list[int]).

    A search URL carries its own repo and query; numbers / issue URLs give a repo only
    when every URL names the same one. A bare number list returns slug=None (the form's
    repo field supplies it). Raises ValueError on anything unusable.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("paste a GitHub issue search URL or a list of issue numbers")
    urls = _URL_RE.findall(text)
    if urls:
        slugs = {f"{o}/{r}".lower(): f"{o}/{r}" for o, r, _, _ in urls}
        if len(slugs) > 1:
            raise ValueError("all URLs must point at the same repository")
        slug = next(iter(slugs.values()))
        if len(urls) == 1 and not urls[0][2]:
            q = parse_qs(urls[0][3] or "").get("q", [""])[0]
            tokens = [t for t in shlex.split(unquote_plus(q), posix=False)
                      if t.lower() not in _DROP_TOKENS and not t.lower().startswith("sort:")]
            if not tokens:
                raise ValueError("that search matches every open issue — add a filter such as label:ready or in:title ui")
            return slug, "query", " ".join(tokens)
        nums = [int(n) for _, _, n, _ in urls if n]
        if not nums:
            raise ValueError("no issue numbers in the URLs")
        return slug, "issues", dispatch.dedupe(nums)
    return None, "issues", dispatch.dedupe(dispatch.parse_issue_list(re.sub(r"[\s,]+", ",", text)))


def order_of(items: list) -> list[int]:
    """Topological order of the pipeline's issues; ValueError on a dependency cycle."""
    deps = {it["issue"]: list(it["deps"]) for it in items}
    return epic.build_dag(deps)["order"]


def item_state(sess_status, ledger_status):
    """Pipeline-item state from a session's status + the run Ledger's status (None = no ledger). A session that
exited cleanly is only done when its Ledger says so: a run that stopped at preflight leaves none."""
    if sess_status in ("starting", "running"):
        return "running"
    if sess_status in ("waiting", "limited", "failed", "stopped"):
        return sess_status
    if sess_status == "done":
        return "done" if ledger_status == "done" else "failed"
    return None


def advance(pipe: dict, observed: dict):
    """Refresh item states from `observed` {issue: (session_status, ledger_status)}, mark the
    dependents of failed/stopped/skipped items skipped (and un-mark them if the blocker
    recovers), flip the pipeline done/active, and return (issues_to_launch, just_finished)."""
    by = {it["issue"]: it for it in pipe["items"]}
    for n, it in by.items():
        if it.get("session_id") and n in observed:
            st = item_state(*observed[n])
            if st:
                it["state"] = st
                if st == "failed" and observed[n][0] == "done":  # the session ended but the run never completed
                    it["reason"] = {"escalated": "run escalated", None: "run did not start"}.get(observed[n][1], "run ended before finishing")
    for n in order_of(pipe["items"]):
        it = by[n]
        if it["state"] not in ("queued", "skipped") or it.get("reason") == "manual":
            continue
        blocker = next((d for d in it["deps"] if by[d]["state"] in BAD), None)
        if blocker:
            it["state"], it["reason"] = "skipped", f"blocked by #{blocker}"
        elif it["state"] == "skipped":
            it["state"], it["reason"] = "queued", None
    states = [it["state"] for it in pipe["items"]]
    finished = False
    if all(s in TERMINAL for s in states):
        if pipe["status"] == "active":
            pipe["status"], finished = "done", True
    elif pipe["status"] == "done":
        pipe["status"], pipe["notified"] = "active", False
    launch: list[int] = []
    if pipe["status"] == "active":
        cap = 1 if pipe["mode"] == "sequential" else pipe["max"]
        free = cap - sum(1 for s in states if s in LIVE)
        for n in order_of(pipe["items"]):
            if free <= 0:
                break
            if by[n]["state"] == "queued" and all(by[d]["state"] == "done" for d in by[n]["deps"]):
                launch.append(n)
                free -= 1
    return launch, finished


# --------------------------------------------------------------------------- store


def _dir() -> str:
    return os.path.join(data_dir(), "pipelines")


def _path(pid: str) -> str:
    if not isinstance(pid, str) or not _ID_RE.fullmatch(pid):
        raise ValueError(f"invalid pipeline id: {pid!r}")
    return os.path.join(_dir(), pid + ".json")


def load(pid: str):
    try:
        with open(_path(pid), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("items"), list) else None


def save(pipe: dict) -> None:
    os.makedirs(_dir(), exist_ok=True)
    atomic_write_text(_path(pipe["id"]), json.dumps(pipe, indent=2))


def list_all() -> list:
    try:
        names = os.listdir(_dir())
    except FileNotFoundError:
        return []
    out = [p for p in (load(n[:-5]) for n in names if n.endswith(".json") and _ID_RE.fullmatch(n[:-5])) if p]
    return sorted(out, key=lambda p: p["created"], reverse=True)


def summary(pipe: dict) -> dict:
    counts: dict = {}
    for it in pipe["items"]:
        counts[it["state"]] = counts.get(it["state"], 0) + 1
    return {k: pipe[k] for k in ("id", "name", "slug", "mode", "max", "status", "created", "claude_cmd")} | {
        "total": len(pipe["items"]), "counts": counts,
        "issues": [{"issue": it["issue"], "state": it["state"]} for it in pipe["items"]],
    }


def membership() -> dict:
    """{"owner/repo#n": pipeline id} for pipelines that are not finished, for board tags."""
    out = {}
    for p in list_all():
        if p["status"] == "done":
            continue
        for it in p["items"]:
            out[f"{p['slug'].lower()}#{it['issue']}"] = p["id"]
            m = it.get("moved_to")
            if m:
                out[f"{m['owner']}/{m['repo']}#{m['issue']}".lower()] = p["id"]
    return out


def wants_grind() -> set:
    """{"owner/repo#n"} of issues in unfinished pipelines that grind when they finish: the pipeline's own
    flag, else the Settings default (so a pipeline made before the option existed follows the default)."""
    default = ui_settings.load()["auto_grind"]
    return {f"{p['slug'].lower()}#{it['issue']}" for p in list_all()
            if p["status"] != "done" and p.get("auto_grind", default) is True for it in p["items"]}


# --------------------------------------------------------------------------- GitHub edge


def _issue_numbers(slug: str, kind: str, value) -> list[int]:
    if kind == "query":
        data, proc = gh_json(["issue", "list", "--repo", slug, "--search", value, "--state", "open",
                              "--json", "number", "--jq", "[.[].number]", "--limit", str(MAX_ISSUES)])
        if proc.returncode != 0:
            raise ValueError(f"search failed: {(proc.stderr or '').strip()[:200]}")
        return dispatch.dedupe([int(n) for n in (data or [])])
    if len(value) == 1:  # a lone number may be an epic: expand its sub-issues, else it is just that issue
        data, proc = gh_json(["api", f"repos/{slug}/issues/{value[0]}/sub_issues", "--jq", "[.[].number]"])
        if proc.returncode == 0 and data:
            return dispatch.dedupe([int(n) for n in data])
    return value


def _screen(slug: str, numbers: list[int]) -> list[dict]:
    args = SimpleNamespace(slug=slug)
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(lambda n: dispatch._issue_readiness(args, n), numbers))


def _screen_open(slug: str, numbers: list[int]) -> list[dict]:
    """_screen, but refuse issues GitHub could not resolve or that are closed — a typo'd
    number must not become a pipeline item that fails an hour later."""
    rows = _screen(slug, numbers)
    for r in rows:
        if "error" in r:
            raise ValueError(f"#{r['issue']}: {r['error']}")
        if r.get("closed"):
            raise ValueError(f"#{r['issue']} is closed")
    return rows


class NeedsCheckout(Exception):
    """The repo has no registered local clone; `candidates` are clones found on disk for it."""

    def __init__(self, slug: str, candidates: list):
        super().__init__(f"no local clone registered for {slug}")
        self.slug, self.candidates = slug, candidates


def _checkout(repo: str):
    """(path, slug) via ui_repos.resolve_repo; an unregistered owner/repo becomes NeedsCheckout."""
    if ui_repos.is_unregistered_slug(repo):
        raise NeedsCheckout(repo, [c["path"] for c in ui_repos.find_clones(ui_repos.default_roots(), repo)])
    return ui_repos.resolve_repo(repo)


def preview(text: str, repo) -> dict:
    """Resolve + screen the pasted input. ValueError carries a user-facing message."""
    slug, kind, value = parse_input(text)
    cwd, repo_slug = _checkout(slug or repo or "")
    slug = slug or repo_slug
    if not slug or "/" not in slug:
        raise ValueError("could not tell which GitHub repo this is — pick one with an origin remote")
    numbers = _issue_numbers(slug, kind, value)
    if not numbers:
        raise ValueError("no open issues matched")
    if len(numbers) > MAX_ISSUES:
        raise ValueError(f"{len(numbers)} issues — the limit is {MAX_ISSUES}")
    known = set(numbers)
    items = []
    for r in _screen(slug, numbers):
        row = {"issue": r["issue"], "title": r.get("title", "")}
        if "error" in r:
            row |= {"problem": r["error"], "ready": False}
        elif r.get("closed"):
            row |= {"problem": "issue is closed", "ready": False}
        else:
            row |= {"gaps": r["gaps"], "lane": r["mode"], "skip": r["skip_reason"],
                    "deps": [d for d in r["deps"] if d in known],
                    "ext_deps": [d for d in r["deps"] if d not in known],
                    "ready": not r["gaps"] and not r["skip_reason"]}
        items.append(row)
    try:  # execution order, top to bottom: dependencies first, then oldest issue first
        rank = {n: i for i, n in enumerate(epic.build_dag({r["issue"]: r.get("deps", []) for r in items})["order"])}
    except ValueError:  # a cycle is reported by create; just sort by number
        rank = {r["issue"]: r["issue"] for r in items}
    items.sort(key=lambda r: rank[r["issue"]])
    return {"slug": slug, "repo_path": cwd, "items": items}


# --------------------------------------------------------------------------- mutations


def _new_item(row: dict) -> dict:
    return {"issue": row["issue"], "title": row.get("title", ""), "deps": row.get("deps", []),
            "ext_deps": row.get("ext_deps", []), "state": "queued", "session_id": None, "reason": None}


def create(body: dict) -> dict:
    """Build + persist a pipeline from the form. ValueError carries a user-facing message."""
    issues = body.get("issues")
    if not isinstance(issues, list) or not issues or not all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in issues):
        raise ValueError("issues must be a non-empty list of issue numbers")
    if len(issues) > MAX_ISSUES:
        raise ValueError(f"at most {MAX_ISSUES} issues per pipeline")
    mode = body.get("mode", "parallel")
    cap = body.get("max", 2)
    if mode not in ("parallel", "sequential") or not isinstance(cap, int) or isinstance(cap, bool) or not 1 <= cap <= 10:
        raise ValueError("mode must be parallel|sequential and max an integer 1-10")
    worktree = body.get("worktree", True)
    if not isinstance(worktree, bool):
        raise ValueError("worktree must be true or false")
    if not worktree and mode != "sequential":
        raise ValueError(MAIN_TREE_PARALLEL)
    label = body.get("claude_cmd")
    if label is not None and not isinstance(label, str):
        raise ValueError("claude_cmd must be a saved label")
    cwd, slug = _checkout(str(body.get("repo") or ""))
    slug = body.get("slug") or slug
    if not isinstance(slug, str) or "/" not in slug:
        raise ValueError("could not tell which GitHub repo this is")
    nums = dispatch.dedupe(issues)
    known = set(nums)
    rows = _screen_open(slug, nums)
    items = [_new_item({"issue": r["issue"], "title": r.get("title", ""),
                        "deps": [d for d in r.get("deps", []) if d in known and d != r["issue"]],
                        "ext_deps": [d for d in r.get("deps", []) if d not in known]}) for r in rows]
    order_of(items)  # cycle -> ValueError before anything is written
    pid = f"p-{time.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
    name = (body.get("name") or "").strip()[:80] or f"{slug} · {len(items)} issue{'s' * (len(items) != 1)}"
    pipe = {"id": pid, "name": name, "slug": slug, "repo_path": cwd, "mode": mode, "max": cap,
            "claude_cmd": label, "auto_grind": body.get("auto_grind") is True, "worktree": worktree, "status": "active", "created": time.time(), "notified": False, "items": items}
    with _lock:
        save(pipe)
    tick(pid)
    return load(pid)


def _launch(pipe: dict, it: dict) -> None:
    body = {"repo": pipe["repo_path"], "command": "run-issue", "args": str(it["issue"]), "issue": it["issue"]}
    if pipe.get("claude_cmd"):
        body["claude_cmd"] = pipe["claude_cmd"]
    body["worktree"] = pipe.get("worktree", True)
    if "auto_grind" in pipe:  # a pipeline made before the option existed inherits the Settings default
        body["auto_grind"] = pipe["auto_grind"] is True
    status, res = ui_repos.start_session(body)
    if status in (201, 409):  # 409 = a session for this issue is already live: adopt it
        it["session_id"], it["state"], it["reason"] = res["id"], "running", "adopted" if status == 409 else None
    else:
        it["state"], it["reason"] = "failed", f"could not start: {res.get('error', status)}"


def _run_of(owner: str, repo: str, it: dict):
    """(run, (owner, repo, issue)) for a pipeline item. A run-issue that moved the issue to another repo
    leaves its Ledger under the new number: follow `transferred_from` there and remember it on the item."""
    try:
        run = ui_board.load_run(owner, repo, str(it["issue"]))
    except ValueError:
        run = None
    if run or it.get("moved_to") is None and not it.get("session_id"):
        return run, (owner, repo, it["issue"])
    moved = it.get("moved_to")
    if not moved:
        found = ui_board.transferred_run(f"{owner}/{repo}", it["issue"])
        moved = {"owner": found[0], "repo": found[1], "issue": found[2]} if found else None
    if not moved:
        return run, (owner, repo, it["issue"])
    try:
        run = ui_board.load_run(moved["owner"], moved["repo"], str(moved["issue"]))
    except ValueError:
        run = None
    return run, (moved["owner"], moved["repo"], moved["issue"])


def _observe(pipe: dict) -> dict:
    owner, _, repo = pipe["slug"].partition("/")
    out = {}
    for it in pipe["items"]:
        if not it.get("session_id"):
            continue
        try:
            rec = ui_sessions.load(it["session_id"])
        except ValueError:
            rec = None
        run, loc = _run_of(owner, repo, it)
        if loc != (owner, repo, it["issue"]) and it.get("moved_to") != {"owner": loc[0], "repo": loc[1], "issue": loc[2]}:
            it["moved_to"] = {"owner": loc[0], "repo": loc[1], "issue": loc[2]}
            if rec:  # the run page of the new number finds this session through its link
                try:
                    ui_sessions.update(it["session_id"], link=dict(it["moved_to"]))
                except (ValueError, OSError) as exc:
                    warn(f"ui_dispatch: could not relink {it['session_id']}: {exc}")
        out[it["issue"]] = (rec["status"] if rec else "failed", run["status"] if run else None)
    return out


def tick(pid: str) -> None:
    with _lock:
        pipe = load(pid)
        if pipe is None:
            return
        before = json.dumps(pipe, sort_keys=True)
        launch, finished = advance(pipe, _observe(pipe))
        by = {it["issue"]: it for it in pipe["items"]}
        for n in launch:
            _launch(pipe, by[n])
        if finished and not pipe.get("notified"):
            pipe["notified"] = True
            c = summary(pipe)["counts"]
            ui_notify.notify("pipeline", {"id": pid, "repo": pipe["slug"], "command": "pipeline " + pipe["name"] + ": " + ", ".join(
                f"{v} {k}" for k, v in sorted(c.items()))})
        if json.dumps(pipe, sort_keys=True) != before:
            save(pipe)


def tick_all() -> None:
    for p in list_all():
        if p["status"] != "done" or any(it["state"] not in TERMINAL for it in p["items"]):
            try:
                tick(p["id"])
            except Exception as exc:  # one bad pipeline must not stop the others
                warn(f"ui_dispatch tick of {p['id']} failed: {exc}")


def start_timer(interval: float = 5.0) -> threading.Thread:
    def loop():
        while True:
            tick_all()
            time.sleep(interval)
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


def _mutate(pid: str, fn):
    with _lock:
        pipe = load(pid)
        if pipe is None:
            raise NotFound(pid)
        fn(pipe)
        save(pipe)
    tick(pid)
    return load(pid)


def _item(pipe: dict, n) -> dict:
    it = next((i for i in pipe["items"] if i["issue"] == n), None)
    if it is None:
        raise NotFound(f"#{n} is not in this pipeline")
    return it


def retry(pipe: dict, it: dict) -> None:
    if it["state"] not in ("failed", "stopped", "skipped"):
        raise Conflict(f"#{it['issue']} is {it['state']}, nothing to retry")
    sid, it["reason"] = it.get("session_id"), None
    if it["state"] == "stopped" and sid:
        try:
            ui_runner.resume_stopped(sid)
            it["state"] = "running"
            return
        except (FileNotFoundError, ValueError, ui_runner.Conflict, ui_runner.RunnerError, OSError) as exc:
            warn(f"ui_dispatch: resume of {sid} failed ({exc}); starting #{it['issue']} fresh")
    it["state"], it["session_id"] = "queued", None
    if pipe["status"] == "done":
        pipe["status"], pipe["notified"] = "active", False


def act(pid: str, action: str, body: dict | None = None, issue=None) -> dict:
    """Pipeline controls. Raises NotFound / Conflict / ValueError (user-facing messages)."""
    body = body or {}

    def run(pipe):
        if issue is not None:
            it = _item(pipe, issue)
            if action == "retry":
                retry(pipe, it)
            elif action == "skip":
                if it["state"] not in ("queued", "failed", "stopped"):
                    raise Conflict(f"#{issue} is {it['state']}, stop it first")
                it["state"], it["reason"] = "skipped", "manual"
            else:
                raise ValueError("unknown item action")
        elif action == "pause":
            pipe["status"] = "paused" if pipe["status"] == "active" else pipe["status"]
        elif action == "resume":
            was_stopped = pipe["status"] == "stopped"
            if pipe["status"] in ("paused", "stopped"):
                pipe["status"] = "active"
            if was_stopped:
                for it in pipe["items"]:
                    if it["state"] == "stopped":
                        retry(pipe, it)
        elif action == "stop":
            pipe["status"] = "stopped"
            for it in pipe["items"]:
                if it["state"] in LIVE and it.get("session_id"):
                    try:
                        ui_runner.stop(it["session_id"])
                        it["state"] = "stopped"
                    except Exception as exc:
                        warn(f"ui_dispatch: stop of {it['session_id']} failed: {exc}")
        elif action == "update":
            if "max" in body:
                m = body["max"]
                if not isinstance(m, int) or isinstance(m, bool) or not 1 <= m <= 10:
                    raise ValueError("max must be an integer 1-10")
                pipe["max"] = m
            if "mode" in body:
                if body["mode"] not in ("parallel", "sequential"):
                    raise ValueError("mode must be parallel|sequential")
                if body["mode"] == "parallel" and pipe.get("worktree") is False:
                    raise ValueError(MAIN_TREE_PARALLEL)
                pipe["mode"] = body["mode"]
            if body.get("add"):
                add = [n for n in dispatch.dedupe([int(n) for n in body["add"]]) if all(i["issue"] != n for i in pipe["items"])]
                if len(pipe["items"]) + len(add) > MAX_ISSUES:
                    raise ValueError(f"at most {MAX_ISSUES} issues per pipeline")
                known = {i["issue"] for i in pipe["items"]} | set(add)
                new = [_new_item({"issue": r["issue"], "title": r.get("title", ""),
                                  "deps": [d for d in r.get("deps", []) if d in known and d != r["issue"]],
                                  "ext_deps": [d for d in r.get("deps", []) if d not in known]})
                       for r in _screen_open(pipe["slug"], add)]
                items = pipe["items"] + new
                order_of(items)
                pipe["items"] = items
        else:
            raise ValueError("unknown action")

    return _mutate(pid, run)


def delete(pid: str) -> None:
    with _lock:
        pipe = load(pid)
        if pipe is None:
            raise NotFound(pid)
        if any(it["state"] in LIVE for it in pipe["items"]):
            raise Conflict("stop the pipeline before deleting it")
        os.unlink(_path(pid))


# --------------------------------------------------------------------------- detail view


def detail(pid: str, gh_status=None) -> dict | None:
    """The pipeline plus, per issue, its session, Ledger station timeline and PR/CI status."""
    pipe = load(pid)
    if pipe is None:
        return None
    owner, _, repo = pipe["slug"].partition("/")
    rows = []
    for it in pipe["items"]:
        sess = None
        run, (r_owner, r_repo, r_issue) = _run_of(owner, repo, it)
        if it.get("session_id"):
            try:
                rec = ui_sessions.load(it["session_id"])
            except ValueError:
                rec = None
            if rec:
                sess = {k: rec.get(k) for k in ("id", "status", "auto_resume", "error")}
        row = dict(it, session=sess)
        if run:
            row["run"] = {k: run.get(k) for k in ("status", "currentStation", "stations", "totals", "pr", "branch")}
            if gh_status:
                row["gh"] = gh_status(r_owner, r_repo, r_issue, run.get("pr"), run.get("branch"))
        rows.append(row)
    try:
        order = order_of(pipe["items"])
    except ValueError:
        order = [it["issue"] for it in pipe["items"]]
    by = {r["issue"]: r for r in rows}
    return {**{k: pipe[k] for k in ("id", "name", "slug", "mode", "max", "status", "created", "claude_cmd")},
            "auto_grind": pipe.get("auto_grind") is True, "worktree": pipe.get("worktree", True), "items": rows, "order": order,
            "merge_order": [n for n in order if (by[n].get("run") or {}).get("pr")]}
