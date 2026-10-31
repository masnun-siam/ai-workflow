"""The Claude account a piece of work was created on, so the steps after it run on that account too.

The create box starts a session with `pin_account`. That session writes a PRD or files one issue, and what it made
is read from its stream. A later session that asks for no account, on that PRD, its epic, its issues or their PRs,
runs on the pinned session's account: every start passes through ui_runner.start, which asks `account_for`.
"""

from __future__ import annotations

import json
import os
import re
import time

import dispatch
import ui_planning
import ui_sessions
import ui_settings

SNAPSHOT = None  # repo slug -> poller snapshot, set by ui_server
PINNED_TTL = 5.0  # seconds: the planning poll asks for every repo, and listing reads every session

_PRD = re.compile(r"docs/prds/([\w.-]+)\.md")
_ISSUE_URL = re.compile(r"/issues/(\d+)")
_PR_URL = re.compile(r"/pull/(\d+)")
_ISSUE_ARGS = re.compile(r"/\S+\s+((?:#?\d+[\s,]+)*#?\d+)(?=\s|$)")

_made_cache: dict = {}  # sid -> (stream size, PRD stems, issue numbers)
_pinned_cache: tuple = (0.0, [])


def _pinned() -> list:
    """Pinned sessions, oldest first: the first to claim a PRD or an issue is the one that made it."""
    global _pinned_cache
    now = time.monotonic()
    if now - _pinned_cache[0] >= PINNED_TTL:
        _pinned_cache = (
            now,
            [r for r in reversed(ui_sessions.list_sessions()) if r.get("pin_account") and r.get("claude_cmd")],
        )
    return _pinned_cache[1]


def _blocks(line: str) -> list:
    try:
        content = json.loads(line).get("message", {}).get("content")
    except (ValueError, AttributeError):
        return []
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _made(rec: dict) -> tuple:
    """(PRD stems written, issue numbers filed) by this session, from its stream. A PRD it only read does not count."""
    path = os.path.join(ui_sessions.session_dir(rec["id"]), "stream.jsonl")
    try:
        size = os.path.getsize(path)
        cached = _made_cache.get(rec["id"])
        if cached and cached[0] == size:
            return cached[1], cached[2]
        prds, issues, filing = set(), set(), set()
        with open(path, errors="replace") as f:
            for line in f:
                if "docs/prds/" not in line and "tool_result" not in line and "gh issue create" not in line:
                    continue
                for b in _blocks(line):
                    args = b.get("input") if isinstance(b.get("input"), dict) else {}
                    if b.get("type") == "tool_use" and b.get("name") == "Write":
                        prds.update(_PRD.findall(str(args.get("file_path", ""))))
                    elif b.get("type") == "tool_use" and "gh issue create" in str(args.get("command", "")):
                        filing.add(b.get("id"))
                    elif b.get("type") == "tool_result" and b.get("tool_use_id") in filing:
                        issues.update(int(n) for n in _ISSUE_URL.findall(str(b.get("content", ""))))
    except OSError:
        return set(), set()
    _made_cache[rec["id"]] = (size, prds, issues)
    return prds, issues


def _slug(repo: str) -> str:
    """The registered slug of a slug or a checkout path, lower-cased so the two forms compare."""
    real = os.path.realpath(repo) if os.path.isabs(repo) else None
    for slug, path in dispatch.read_checkouts().items():
        if slug == repo or (real and os.path.realpath(path) == real):
            return slug.lower()
    return repo.lower()


def _issues(snap: dict, text: str, link) -> set:
    """The issue numbers a session is about: its link, its arguments, and the issues of a PR it names."""
    out = set()
    if isinstance(link, dict) and isinstance(link.get("issue"), int):
        out.add(link["issue"])
    args = _ISSUE_ARGS.match(text)
    if args:
        out.update(int(n) for n in re.findall(r"\d+", args.group(1)))
    prs = {int(n) for n in _PR_URL.findall(text)} | out
    data = snap.get("data") or {}
    for i in data.get("issues") or []:
        if prs & {p.get("n") for p in i.get("prs") or []}:
            out.add(i["n"])
    for m in data.get("merged") or []:
        if m.get("n") in prs:
            out.update(m.get("closes") or [])
    return out


def _family(repo: str, stem: str, snap: dict) -> set:
    """A PRD's epic and child issues, open and closed."""
    checkout = dispatch.read_checkouts().get(repo)
    if not checkout or not (snap.get("data") or {}):
        return set()
    for p in ui_planning.build(repo, checkout, snap, None)["prds"]:
        if os.path.splitext(os.path.basename(p["path"]))[0] == stem:
            kids = [c["n"] for c in p.get("children") or []] + [c["n"] for c in p.get("closed_children") or []]
            return {*kids, *([p["epic"]] if p.get("epic") else [])}
    return set()


def _snapshot(slug: str) -> dict:
    try:
        return (SNAPSHOT(slug) if SNAPSHOT else None) or {}
    except (KeyError, ValueError):
        return {}


def account_for(cwd: str, text: str, link=None):
    """The account command of the pinned session that made this work, or None. Never in the way of a start."""
    pinned = _pinned()
    if not pinned:
        return None
    try:
        slug = _slug(cwd)
        mine = [r for r in pinned if _slug(r["repo"]) == slug]
        if not mine:
            return None
        repo = next((s for s in dispatch.read_checkouts() if s.lower() == slug), slug)
        snap, prds = _snapshot(repo), set(_PRD.findall(text))
        issues = _issues(snap, text, link)
        for r in mine:
            made_prds, made_issues = _made(r)
            hit = (
                made_prds & prds
                or made_issues & issues
                or any(issues & _family(repo, s, snap) for s in made_prds if issues)
            )
            if hit:
                return (
                    r["claude_cmd"] if r["claude_cmd"] in {c["cmd"] for c in ui_settings.load()["commands"]} else None
                )
    except (OSError, ValueError, KeyError, TypeError) as e:
        from shared import warn  # noqa: PLC0415

        warn(f"account lookup for {cwd}: {e}")
    return None


def prd_label(cwd: str, stem: str):
    """The account label a PRD's work runs on, for the UI; None for the Settings default."""
    if not _pinned():
        return None
    cmd = account_for(cwd, f"docs/prds/{stem}.md")
    return next((c["label"] for c in ui_settings.load()["commands"] if c["cmd"] == cmd), None)
