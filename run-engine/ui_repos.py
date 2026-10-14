#!/usr/bin/env python3
"""Repo list + session-start validation for the `aiw ui` server (stdlib only).

Every subprocess is an argument list (no shell); repo paths are validated as git
checkouts before they become a session's cwd.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time

import dispatch
import peer_review as peer_review_mod
import ui_board
import ui_flows
import ui_runner
import ui_sessions
import ui_settings
import ui_vault

NAMED = (
    "run-issue",
    "pr-grind",
    "create-prd",
    "intake",
    "dump",
    "worklog",
    "gh-issue",
    "create-tasks",
    "refine-issues",
    "fix-blockers",
    "pr-review",
    "pr-fix-comments",
    "issue-to-pr",
    "day",
)
MAX_PROMPT_CHARS = 32000
BATCH_MAX = 3  # sessions of one batch (a worklog date range) running at once
_TERMINAL = ("done", "failed", "stopped")
_ORIGIN_RE = re.compile(r"github\.com(?::\d+)?[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")  # (?::\d+): ssh.github.com:443
_ISSUE_RE = re.compile(r"^(?:#|.*/issues/)?(\d+)$")
_ISSUE_URL_RE = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)/issues/(\d+)")

# ponytail: one global in-process lock, held across start's auth preflight (~30s); per-key locks
# or an flock in the data dir are the upgrade path.
_start_lock = threading.Lock()


def promote_local() -> None:
    """A local/<name> repo (made by Create repo) that has since got a GitHub origin is re-registered
    under its real owner/repo, so GitHub steps work without the user touching the registry."""
    for slug, path in list(dispatch.read_checkouts().items()):
        if slug.startswith("local/") and isinstance(path, str) and os.path.isdir(path):
            new = origin_slug(path)
            if new:
                dispatch.rename_checkout(slug, new)  # no-op when that name is already another checkout


def origin_slug(path: str):
    """owner/repo of a checkout's GitHub origin, or None."""
    m = _ORIGIN_RE.search(_git(path, "remote", "get-url", "origin"))
    return f"{m.group(1)}/{m.group(2)}" if m else None


def list_repos() -> list:
    promote_local()
    try:
        projects = ui_board.load_projects()
    except (OSError, ValueError):
        projects = {}
    if not isinstance(projects, dict):
        projects = {}
    repos = []
    for slug, path in dispatch.read_checkouts().items():
        if not isinstance(path, str):
            continue
        name = projects.get(slug)
        repos.append({"slug": slug, "name": name if isinstance(name, str) else slug, "path": path})
    return sorted(repos, key=lambda r: r["slug"])


_PICK = "on run argv\nPOSIX path of (choose folder default location (POSIX file (item 1 of argv)))\nend run"


def browse_folder(start):
    """Open the macOS folder dialog on this machine; the chosen absolute path, or None if cancelled."""
    start = start if isinstance(start, str) and os.path.isdir(start) else os.path.expanduser("~")
    try:
        r = subprocess.run(["osascript", "-e", _PICK, start], capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = r.stdout.strip()
    return (out.rstrip("/") or "/") if r.returncode == 0 and out else None


def _git(real: str, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", real, *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def validate_repo(path: str) -> str:
    """Return the git toplevel of `path`; ValueError if it is not an absolute path into a git checkout."""
    if os.path.isabs(path) and ".." not in path.split(os.sep):
        real = os.path.realpath(path)
        if os.path.isdir(real):
            top = _git(real, "rev-parse", "--show-toplevel")
            if top:
                return top
    raise ValueError(f"not a git repository: {path}")


_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SCAN_SKIP = {"node_modules", "vendor", "venv", "dist", "build", "target", "Library", "Applications"}


def is_unregistered_slug(repo: str) -> bool:
    """True for an owner/repo string with no registered clone. Only callers that take slugs
    (Dispatch) ask this; resolve_repo keeps treating unknown strings as paths."""
    return (
        bool(_SLUG_RE.match(repo))
        and not os.path.isabs(repo)
        and not any(k.lower() == repo.lower() for k in dispatch.read_checkouts())
    )


def default_roots() -> list:
    """Existing folders where people usually keep clones; the Settings scan starts here."""
    home = os.path.expanduser("~")
    cands = [
        os.path.join(home, p)
        for p in ("Documents/Projects", "Projects", "Developer", "code", "work", "dev", "src", "Documents")
    ]
    return [p for p in cands if os.path.isdir(p)]


def _origin_slug(top: str):
    m = _ORIGIN_RE.search(_git(top, "remote", "get-url", "origin"))
    return f"{m.group(1)}/{m.group(2)}" if m else None


def find_clones(roots, slug=None, max_depth: int = 4, budget_s: float = 4.0) -> list:
    """[{"slug", "path"}] for git clones (a real .git directory, so worktrees are skipped) under
    `roots` that have a GitHub origin; only those matching `slug` when given. Depth- and
    time-bounded: this runs inside a request."""
    deadline = time.monotonic() + budget_s
    want = slug.lower() if slug else None
    out, seen = [], set()  # seen: overlapping roots (Documents and Documents/Projects) must not repeat a clone
    for root in roots:
        root = os.path.realpath(root)
        base = root.count(os.sep)
        for dirpath, dirs, _files in os.walk(root):
            if time.monotonic() > deadline:
                return out
            if os.path.isdir(os.path.join(dirpath, ".git")):
                found = _origin_slug(dirpath) if dirpath not in seen else None
                seen.add(dirpath)
                if found and (want is None or found.lower() == want):
                    out.append({"slug": found, "path": dirpath})
                dirs[:] = []  # do not descend into a clone
                continue
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _SCAN_SKIP]
            if dirpath.count(os.sep) - base >= max_depth:
                dirs[:] = []
    return out


def register(slug: str, path: str) -> str:
    """Record `path` as the clone of `slug` after checking its origin really is that repo."""
    if not isinstance(slug, str) or not _SLUG_RE.match(slug):
        raise ValueError("slug must look like owner/repo")
    if not isinstance(path, str):
        raise ValueError("path must be a string")
    top = validate_repo(path.strip())
    found = _origin_slug(top)
    if not found or found.lower() != slug.lower():
        raise ValueError(f"that folder's origin is {found or 'not a GitHub repo'}, not {slug}")
    dispatch.register_checkout(slug, top)
    return top


def scan_and_register(roots) -> dict:
    """Register every clone found under `roots` that is not already known. Where one repo has
    several clones the first found wins; the rest are reported, not registered."""
    known = {k.lower() for k in dispatch.read_checkouts()}
    added, duplicates, added_keys = [], [], set()
    for c in find_clones(roots, budget_s=20.0):
        key = c["slug"].lower()
        if key not in known:
            dispatch.register_checkout(c["slug"], c["path"])
            known.add(key)
            added_keys.add(key)
            added.append(c)
        elif key in added_keys:
            duplicates.append(c)
    return {"added": added, "duplicates": duplicates}


def resolve_repo(repo: str):
    """(cwd, slug-or-None) for a registered slug or a manual absolute path."""
    checkouts = {k: v for k, v in dispatch.read_checkouts().items() if isinstance(v, str)}
    slug = next((k for k in checkouts if k.lower() == repo.lower()), None)  # slugs are case-insensitive on GitHub
    if slug:
        return validate_repo(checkouts[slug]), slug
    top = validate_repo(repo)
    for slug, path in checkouts.items():
        if os.path.realpath(path) == os.path.realpath(top):
            return top, slug
    m = _ORIGIN_RE.search(_git(top, "remote", "get-url", "origin"))
    return top, (f"{m.group(1)}/{m.group(2)}" if m else None)


def build_command(cmd, args: str) -> str:
    if cmd in NAMED:
        return f"/{cmd} {args}".rstrip()
    raise ValueError(f"unknown command: {cmd}")


def family(text: str):
    first = text.lstrip().split(None, 1)[0] if text.strip() else ""
    return first[1:].split(":")[-1] if first.startswith("/") else None


def issue_from_args(rest: str):
    toks = rest.split()
    m = _ISSUE_RE.match(toks[0]) if toks else None
    return int(m.group(1)) if m else None


def find_live(fam: str, link: dict):
    for rec in ui_sessions.list_sessions():
        other = rec.get("link")
        if rec.get("status") in _TERMINAL or not isinstance(other, dict):
            continue
        if rec.get("pid") and ui_runner._group_gone(rec["pid"], None):
            continue  # crashed record: process group is gone
        if (
            family(rec.get("command") or "") == fam
            and other.get("issue") == link["issue"]
            and (str(other.get("owner")).lower(), str(other.get("repo")).lower())
            == (link["owner"].lower(), link["repo"].lower())
        ):
            return rec
    return None


def _prompt(body: dict) -> str:
    cmd, text, args = body.get("command"), body.get("text"), body.get("args", "")
    if (cmd is None) == (text is None):
        raise ValueError("exactly one of command or text is required")
    if not isinstance(args, str):
        raise ValueError("args must be a string")
    if cmd is not None:
        return build_command(cmd, args)
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    if "\x00" in text:
        raise ValueError("text must not contain NUL bytes")
    if text.lstrip().startswith("-"):
        raise ValueError("text must not start with '-'")
    return text


def _custom_review(text: str, cwd: str, lenses: list) -> tuple[str, str]:
    """A fresh review dir holding the prompt verbatim as ask.md, and the prompt with one line asking for the review.

    The line is not a gate (the session skips permissions and could ignore it); the session's
    peer_review post-check reads the dir's round state to show whether the review ran.
    """
    name = f"ui-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{secrets.token_hex(3)}"
    review_dir = peer_review_mod.make_dir("custom", name)
    with open(os.path.join(review_dir, "ask.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    sha = _git(cwd, "rev-parse", "HEAD")
    since = f" --since {sha}" if sha else ""
    line = f"When the work is done, run the ai-workflow:peer-review skill with --dir {review_dir} --lenses {','.join(lenses)}{since}."
    return f"{text}\n\n{line}", review_dir


def _remember(slug, cwd) -> None:
    """Register a manually entered checkout so it shows in the repo list next time."""
    if not slug or any(k.lower() == slug.lower() for k in dispatch.read_checkouts()):
        return
    try:
        dispatch.register_checkout(slug, cwd)
    except OSError as exc:
        print(f"ui_repos: could not register checkout {slug}: {exc}", file=sys.stderr)


_GITHUB_COMMANDS = (
    "create-tasks",
    "run-issue",
    "pr-grind",
    "pr-review",
    "pr-fix-comments",
    "gh-issue",
    "issue-to-pr",
    "refine-issues",
)


def _vault_hint(folder) -> str:
    """What a no-repo session is told: where it is, and where the idea was suggested to go."""
    where = (
        f"The suggested vault folder is {folder} (it may not exist yet: create it if the user confirms)."
        if folder
        else "No vault folder was chosen: pick one under 05-Work/<Project>/<Feature> from 05-Work/Index.md."
    )
    return (
        "\n\nThis is a new idea with no code repo yet; you are running in the notes vault. "
        + where
        + " Confirm the folder with the user before writing anything."
    )


def start_session(body: dict):
    repo = body.get("repo")
    if repo is not None and not isinstance(repo, str):
        return 400, {"error": "repo must be a string"}
    issue = body.get("issue")
    try:
        if "issue" in body and (not isinstance(issue, int) or isinstance(issue, bool) or issue < 1):
            raise ValueError("issue must be a positive integer")
        text = _prompt(body)
        if "\x00" in text:
            raise ValueError("prompt must not contain NUL bytes")
        if len(text) > MAX_PROMPT_CHARS:
            raise ValueError(f"prompt too long (max {MAX_PROMPT_CHARS} characters)")
        url = _ISSUE_URL_RE.search(text)
        url_slug = f"{url.group(1)}/{url.group(2)}" if url else None
        # the issue URL names the repo: prefer its registered checkout over the picked one
        if url_slug and any(k.lower() == url_slug.lower() for k in dispatch.read_checkouts()):
            repo = url_slug
        if body.get("no_repo") is True:  # a new idea: no code yet, so it runs in the notes vault
            fam0 = "custom" if body.get("text") is not None else family(text)
            if fam0 not in (*ui_vault.NO_REPO_COMMANDS, "custom"):
                raise ValueError(
                    f"{fam0} needs a repo; only create-prd, dump, intake and a custom prompt run without one"
                )
            cwd, slug = ui_vault.vault(), None
            if not os.path.isdir(cwd):
                raise ValueError(f"the notes vault folder does not exist: {cwd} (set it in Settings)")
        elif not repo:
            raise ValueError(
                "repo is required" + (f" (no local checkout registered for {url_slug})" if url_slug else "")
            )
        else:
            cwd, slug = resolve_repo(repo)
            if slug and slug.startswith("local/") and family(text) in _GITHUB_COMMANDS:
                taken = origin_slug(cwd)  # set means promote_local found that name already registered
                raise ValueError(
                    f"{slug}'s origin {taken} is already registered to another checkout: remove one, then run {family(text)}"
                    if taken
                    else f"{slug} has no GitHub remote yet: add one (git remote add origin …), then run {family(text)}"
                )
    except ValueError as exc:
        return 400, {"error": str(exc)}
    claude_cmd = body.get("claude_cmd")  # a saved label; raw command strings are never accepted
    if claude_cmd is not None:
        saved = {c["label"]: c["cmd"] for c in ui_settings.load()["commands"]}
        if not isinstance(claude_cmd, str) or claude_cmd not in saved:
            return 400, {"error": "claude_cmd must be a label saved in Settings"}
        claude_cmd = saved[claude_cmd]
    worktree = body.get("worktree", True)
    if not isinstance(worktree, bool):
        return 400, {"error": "worktree must be true or false"}
    review = body.get("review", True)
    if not isinstance(review, bool):
        return 400, {"error": "review must be true or false"}
    no_repo = body.get("no_repo") is True
    vault_folder = body.get("vault_folder")
    if vault_folder is not None and not ui_vault.valid_folder(vault_folder):
        return 400, {"error": "vault_folder must be 05-Work/<Project>/<Feature>"}
    batch = body.get("batch")
    if batch is not None and not (isinstance(batch, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", batch)):
        return 400, {"error": "batch must be a short id (letters, digits, - and _)"}
    flow_id = body.get("flow_id")
    if flow_id is not None and (not isinstance(flow_id, str) or ui_flows.load(flow_id) is None):
        return 400, {"error": "flow_id must name an existing flow"}
    peer_review = body.get("peer_review")
    if peer_review is not None and not (
        isinstance(peer_review, list) and peer_review and all(isinstance(x, str) for x in peer_review)
    ):
        return 400, {"error": "peer_review must be a non-empty list of lens names"}
    fam = family(text)
    kind = "custom" if body.get("text") is not None else fam
    if no_repo:
        text += _vault_hint(vault_folder)
        if fam == "create-prd" and "--to" not in text:
            text += " --to obsidian"  # no repo to write docs/prds/ into; Create repo copies it there later
    lenses = None
    if peer_review is not None:
        try:
            lenses = peer_review_mod.check_lenses(kind, peer_review)
        except ValueError as exc:
            return 400, {"error": str(exc)}
        if kind != "custom":
            text += " --review " + ",".join(lenses)
    if fam == "run-issue" and not review:
        text += " --no-review"
    if fam == "run-issue" and not worktree:
        grind = body.get("auto_grind", ui_settings.load()["auto_grind"]) is True
        text += " --no-worktree" + (" --grind" if grind else "")  # main tree: grind in-session to keep holding it
    if issue is None and fam == "run-issue":
        issue = issue_from_args((text.split(None, 1) + [""])[1])
    link = None
    url = _ISSUE_URL_RE.search(text)  # the URL names the real repo; the checkout may be a different one
    if url and int(url.group(3)) == issue:
        link = {"owner": url.group(1), "repo": url.group(2), "issue": issue}
    elif slug and issue is not None and "/" in slug:
        owner, _, name = slug.partition("/")
        link = {"owner": owner, "repo": name, "issue": issue}
    with _start_lock:
        if link and fam in ("run-issue", "pr-grind"):
            dup = find_live(fam, link)
            if dup:
                return 409, {
                    "error": f"{fam} already running for {link['owner']}/{link['repo']}#{issue} (session {dup['id']})",
                    "id": dup["id"],
                    "link": link,
                    "href": f"/api/sessions/{dup['id']}",
                }
        review_dir = None
        if lenses and kind == "custom":
            text, review_dir = _custom_review(text, cwd, lenses)
        try:
            res = ui_runner.start(
                text,
                cwd,
                link,
                claude_cmd=claude_cmd,
                gate_questions=True,
                flow_id=flow_id,
                **({"batch": (batch, BATCH_MAX)} if batch else {}),
            )
            if review_dir:
                res = ui_sessions.update(res["id"], peer_review_dir=review_dir)  # the post-check reads it
            if no_repo:
                res = ui_sessions.update(res["id"], no_repo=True, vault_folder=vault_folder)
            if fam == "run-issue" and link and body.get("auto_grind", ui_settings.load()["auto_grind"]) is True:
                res = ui_sessions.update(
                    res["id"], auto_grind=True
                )  # ui_grind.autostart queues it when the run finishes
            _remember(slug, cwd)
            return 201, res
        except (ValueError, ui_runner.RunnerError) as exc:
            if review_dir:
                shutil.rmtree(review_dir, ignore_errors=True)
            return (400 if isinstance(exc, ValueError) else 502), {"error": str(exc)}
