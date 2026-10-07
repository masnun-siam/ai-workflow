#!/usr/bin/env python3
"""Repo list + session-start validation for the `aiw ui` server (stdlib only).

Every subprocess is an argument list (no shell); repo paths are validated as git
checkouts before they become a session's cwd.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading

import dispatch
import ui_board
import ui_runner
import ui_sessions

NAMED = ("run-issue", "pr-grind", "prd", "intake", "dump", "worklog", "gh-issue")
MAX_PROMPT_CHARS = 32000
_TERMINAL = ("done", "failed", "stopped")
_ORIGIN_RE = re.compile(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")
_ISSUE_RE = re.compile(r"^(?:#|.*/issues/)?(\d+)$")

# ponytail: one global in-process lock, held across start's auth preflight (~30s); per-key locks
# or an flock in the data dir are the upgrade path.
_start_lock = threading.Lock()


def list_repos() -> list:
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
        if family(rec.get("command") or "") == fam and other.get("issue") == link["issue"] and (
            str(other.get("owner")).lower(), str(other.get("repo")).lower()
        ) == (link["owner"].lower(), link["repo"].lower()):
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


def start_session(body: dict):
    repo = body.get("repo")
    if not isinstance(repo, str) or not repo:
        return 400, {"error": "repo is required"}
    issue = body.get("issue")
    try:
        if "issue" in body and (not isinstance(issue, int) or isinstance(issue, bool) or issue < 1):
            raise ValueError("issue must be a positive integer")
        text = _prompt(body)
        if "\x00" in text:
            raise ValueError("prompt must not contain NUL bytes")
        if len(text) > MAX_PROMPT_CHARS:
            raise ValueError(f"prompt too long (max {MAX_PROMPT_CHARS} characters)")
        cwd, slug = resolve_repo(repo)
    except ValueError as exc:
        return 400, {"error": str(exc)}
    fam = family(text)
    if issue is None and fam == "run-issue":
        issue = issue_from_args((text.split(None, 1) + [""])[1])
    link = None
    if slug and issue is not None and "/" in slug:
        owner, _, name = slug.partition("/")
        link = {"owner": owner, "repo": name, "issue": issue}
    with _start_lock:
        if link and fam in ("run-issue", "pr-grind"):
            dup = find_live(fam, link)
            if dup:
                return 409, {
                    "error": f"{fam} already running for {slug}#{issue} (session {dup['id']})",
                    "id": dup["id"],
                    "link": link,
                    "href": f"/api/sessions/{dup['id']}",
                }
        try:
            return 201, ui_runner.start(text, cwd, link)
        except ValueError as exc:
            return 400, {"error": str(exc)}
        except ui_runner.RunnerError as exc:
            return 502, {"error": str(exc)}
