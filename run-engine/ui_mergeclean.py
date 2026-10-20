"""Merge-detect cleanup (FR-20): remove a merged issue's worktree and local branch when safe.

implement-issue works in `<repo>/.worktrees/<n>-<slug>` on branch `issue-<n>-<slug>`. After a merge:
`check` says what removal would lose (None = nothing), `clean` removes it (only under `.worktrees/`,
never the main checkout), `on_merged` runs both after a fresh poll and returns the flagged ones
`{issue: {uncommitted: [paths], unpushed: [shas]}}` (these become the cards' `needs_cleanup`).
A missing worktree counts as clean: only the local branch is deleted. Remote branches are never touched.
"""

from __future__ import annotations

import os
import re

from shared import run, warn


def _git(cwd: str, *args: str):
    return run(["git", "-C", cwd, *args], timeout=60)


def _worktrees(checkout: str) -> list:
    """[{path, branch}] of worktrees under <checkout>/.worktrees/ (realpath'd), main checkout excluded."""
    root = os.path.realpath(os.path.join(checkout, ".worktrees")) + os.sep
    out, cur = [], {}
    for ln in (_git(checkout, "worktree", "list", "--porcelain").stdout or "").split("\n") + [""]:
        if ln.startswith("worktree "):
            cur = {"path": os.path.realpath(ln[9:])}
        elif ln.startswith("branch refs/heads/"):
            cur["branch"] = ln[18:]
        elif not ln and cur.get("path", "").startswith(root):
            out.append(cur)
            cur = {}
        elif not ln:
            cur = {}
    return out


def _plan(checkout: str, issue: int):
    """(worktree path | None, branch | None) for the issue."""
    pre = f"issue-{issue}-"
    wt = next(
        (
            w
            for w in _worktrees(checkout)
            if os.path.basename(w["path"]).startswith(f"{issue}-") or (w.get("branch") or "").startswith(pre)
        ),
        None,
    )
    branch = wt.get("branch") if wt else None
    if not branch:
        refs = (_git(checkout, "for-each-ref", "--format=%(refname:short)", f"refs/heads/{pre}*").stdout or "").split()
        branch = refs[0] if refs else None
    return (wt["path"] if wt else None), branch


def check(checkout: str, issue: int):
    """None when removal loses nothing, else {uncommitted: [paths], unpushed: [shas]}."""
    wt, branch = _plan(checkout, issue)
    uncommitted, unpushed = [], []
    if wt and os.path.isdir(wt):
        for ln in (_git(wt, "status", "--porcelain").stdout or "").split("\n"):
            if ln.strip():
                uncommitted.append(ln[3:].strip().strip('"'))
    if branch:
        unpushed = (_git(checkout, "rev-list", branch, "--not", "--remotes").stdout or "").split()
    return {"uncommitted": uncommitted, "unpushed": unpushed} if uncommitted or unpushed else None


def clean(checkout: str, issue: int, confirm: bool = False) -> dict:
    """{removed: [...], flagged: None | {...}}. Flagged work is only discarded with confirm=True."""
    flagged = check(checkout, issue)
    if flagged and not confirm:
        return {"removed": [], "flagged": flagged}
    wt, branch = _plan(checkout, issue)
    removed = []
    root = os.path.realpath(os.path.join(checkout, ".worktrees")) + os.sep
    if wt and os.path.isdir(wt) and wt.startswith(root):  # never outside .worktrees/, never the main checkout
        if _git(checkout, "worktree", "remove", "--force", wt).returncode == 0:
            removed.append(wt)
        else:
            warn(f"mergeclean: could not remove worktree {wt}")
    if branch and re.fullmatch(rf"issue-{issue}-.+", branch):
        head = (_git(checkout, "symbolic-ref", "--short", "-q", "HEAD").stdout or "").strip()
        if branch != head and _git(checkout, "branch", "-D", branch).returncode == 0:
            removed.append(branch)
    return {"removed": removed, "flagged": None}


def on_merged(repo: str, merged_issues, checkout: str | None = None) -> dict:
    """Clean each merged issue that is safe; returns {issue: flags} for those that are not."""
    if checkout is None:
        from dispatch import read_checkouts

        checkout = read_checkouts().get(repo)
    if not isinstance(checkout, str) or not os.path.isdir(checkout):
        return {}
    flagged = {}
    for n in merged_issues:
        try:
            res = clean(checkout, int(n), confirm=False)
        except Exception as exc:  # noqa: BLE001 - one issue must not stop the rest
            warn(f"mergeclean {repo}#{n}: {type(exc).__name__}: {exc}")
            continue
        if res["flagged"]:
            flagged[int(n)] = res["flagged"]
    return flagged
