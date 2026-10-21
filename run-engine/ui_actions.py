"""Writes from the UI's card drawer: comment on, close or reopen an issue, merge a PR, read and save a PRD.

Every GitHub call is one `gh` invocation with argv (no shell). A failed call raises RuntimeError with
gh's message, which the server maps to 502. Merge always uses a merge commit (`--merge`), never squash;
the UI warns before merging a PR whose CI is not green or that has no approval, but does not block it.

A PRD save writes `docs/prds/<slug>.md` in the repo's checkout and commits only that file on the
checkout's current branch. It does not push.
"""

from __future__ import annotations

import hashlib
import os
import re

from shared import gh_json, run
from ui_issue import valid

MAX_COMMENT = 65536  # GitHub's comment body limit
MAX_PRD = 512 * 1024
_PRD = re.compile(r"docs/prds/[A-Za-z0-9][A-Za-z0-9._-]*\.md")


class Conflict(Exception):
    """The file changed since the caller read it (HTTP 409)."""


def _sha(raw: bytes) -> str:
    """git's blob hash of the content."""
    return hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()


def _ids(owner, repo, n):
    if not valid(str(owner), str(repo), str(n)):
        raise ValueError("bad issue id")
    return f"{owner}/{repo}", str(n)


def _gh(args, runner):
    out, proc = runner(args)
    if out is None and proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "gh failed").strip()[:300])
    return out


def comment(owner, repo, n, text, runner=gh_json) -> dict:
    """A comment on an issue or a PR (both are issues to the REST API)."""
    slug, n = _ids(owner, repo, n)
    if not isinstance(text, str) or not text.strip():
        raise ValueError("comment text is required")
    if len(text) > MAX_COMMENT:
        raise ValueError(f"comment is longer than {MAX_COMMENT} characters")
    out = _gh(["api", f"repos/{slug}/issues/{n}/comments", "-f", f"body={text}"], runner)
    return {"ok": True, "url": (out or {}).get("html_url") if isinstance(out, dict) else None}


def set_state(owner, repo, n, state, reason=None, runner=gh_json) -> dict:
    """Close (completed | not_planned) or reopen an issue."""
    slug, n = _ids(owner, repo, n)
    if state == "open":
        _gh(["issue", "reopen", n, "-R", slug], runner)
    elif state == "closed":
        why = {"completed": "completed", "not_planned": "not planned", None: "completed"}.get(reason)
        if why is None:
            raise ValueError("reason must be completed or not_planned")
        _gh(["issue", "close", n, "-R", slug, "--reason", why], runner)
    else:
        raise ValueError("state must be open or closed")
    return {"ok": True, "state": state}


def merge(owner, repo, n, runner=gh_json) -> dict:
    slug, n = _ids(owner, repo, n)
    _gh(["pr", "merge", n, "-R", slug, "--merge"], runner)
    return {"ok": True}


def _prd_path(checkout: str, rel) -> str:
    if not isinstance(rel, str) or not _PRD.fullmatch(rel):
        raise ValueError("path must be docs/prds/<name>.md")
    path = os.path.join(checkout, rel)
    if not os.path.isfile(path):
        raise ValueError(f"{rel} not found")
    return path


def _branch(checkout: str) -> str:
    return (run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=checkout).stdout or "").strip()


def read_prd(checkout: str, rel) -> dict:
    with open(_prd_path(checkout, rel), "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")  # as text mode reads it
    return {"path": rel, "text": text, "sha": _sha(raw), "branch": _branch(checkout)}


def save_prd(checkout: str, rel, text, base_sha=None) -> dict:
    """Write the PRD and commit only that file (`git commit -- <path>`), leaving anything else staged alone.
    base_sha (the `sha` of the read the edit started from): Conflict when the file has changed since."""
    path = _prd_path(checkout, rel)
    if not isinstance(text, str):
        raise ValueError("text is required")
    if base_sha is not None and not isinstance(base_sha, str):
        raise ValueError("base_sha must be a string")
    if len(text.encode("utf-8")) > MAX_PRD:
        raise ValueError("PRD is too large")
    with open(path, "rb") as f:
        raw = f.read()
    if base_sha is not None and base_sha != _sha(raw):
        raise Conflict("changed on disk")
    if raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n") == text:
        return {"ok": True, "committed": False, "branch": _branch(checkout), "sha": _sha(raw)}
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    slug = os.path.basename(rel)[:-3]
    proc = run(["git", "commit", "-m", f"docs(prd): edit {slug} from aiw ui", "--", rel], cwd=checkout)
    if proc.returncode != 0:
        raise RuntimeError(f"saved, but git commit failed: {(proc.stderr or proc.stdout).strip()[:300]}")
    sha = (run(["git", "rev-parse", "--short", "HEAD"], cwd=checkout).stdout or "").strip()
    with open(path, "rb") as f:
        new = _sha(f.read())
    return {"ok": True, "committed": True, "branch": _branch(checkout), "commit": sha, "sha": new}


def open_children(snapshot: dict, epic: int) -> list:
    """Open child issues of an epic in the poller snapshot: parent is the epic, or listed as its sub-issue."""
    issues = (snapshot.get("data") or {}).get("issues") or []
    ep = next((i for i in issues if i["n"] == epic), None)
    subs = set(ep["sub_issues"]) if ep else set()
    return sorted(i["n"] for i in issues if i["n"] != epic and (i["parent"] == epic or i["n"] in subs))


def close_epic(owner, repo, epic, children, runner=gh_json) -> dict:
    """Close every open child (as completed) and then the epic. Stops at the first failure, saying what closed."""
    _ids(owner, repo, epic)
    closed = []
    for n in [*children, int(epic)]:
        try:
            set_state(owner, repo, n, "closed", "completed", runner)
        except RuntimeError as e:
            done = ", ".join(f"#{x}" for x in closed) or "nothing"
            raise RuntimeError(f"closing #{n} failed ({e}); closed so far: {done}") from None
        closed.append(n)
    return {"ok": True, "closed": closed}
