"""Warn when a typed capture already has an open issue or PRD, with the `jev` CLI. Stdlib only.

POST /api/duplicate {"repo", "text"} -> {"match": {kind, n|path, title, url} | null, "confidence", "why"}.
Options are the poller's newest 100 open issues, then the repo's PRDs (the Features list), then "none".
A match needs a pick at MIN_CONFIDENCE or more; its title and url come from our own records, never from jev.
"""

from __future__ import annotations

import os
from urllib.parse import quote

import jev
import ui_planning
import ui_route

MIN_CHARS = 20
MIN_CONFIDENCE = 0.6
MAX_OPTIONS = 254  # jev takes 255 options; one is "none"
MAX_ISSUES = 100
TITLE_CHARS = 120
QUESTION = "Which existing open issue or PRD already asks for the same change as this request?"
NONE = "None of these: no listed issue or PRD covers this request"
NOT_OK = {**ui_route.NOT_OK, "capped": "jev's hourly limit is reached"}


def _none(why: str, confidence: float = 0.0) -> dict:
    return {"match": None, "confidence": confidence, "why": why}


def _mtime(p: dict) -> float:
    try:
        return os.path.getmtime(p["abs_path"])
    except OSError:
        return 0.0


def check(repo: str, text, snap: dict, checkout: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text is required")
    t = text.strip()
    if len(t) < MIN_CHARS:
        return _none("too short to check")
    st = jev.status()
    if st != "ok":
        return _none(NOT_OK[st])
    if snap.get("stale", True) or snap.get("fetched_at") is None:
        return _none("issues not loaded yet")
    issues = ((snap.get("data") or {}).get("issues") or [])[:MAX_ISSUES]
    prds = sorted(ui_planning.build(repo, checkout, snap, None)["prds"], key=_mtime, reverse=True)
    prds = prds[: MAX_OPTIONS - 1 - len(issues)]
    if not issues and not prds:
        return _none("nothing to compare with")
    options = {f"issue-{i['n']}": i["title"][:TITLE_CHARS] for i in issues}
    options.update({f"prd-{k}": p["title"][:TITLE_CHARS] for k, p in enumerate(prds)})
    options["none"] = NONE
    r = jev.ask("duplicate", "choice", QUESTION, t, options=options)
    if r["status"] != "ok":
        return _none(NOT_OK[r["status"]].format(**r))
    key, conf = r["choice"], r["p"]
    if key not in options:
        return _none("jev gave an unreadable answer")
    if key == "none" or conf < MIN_CONFIDENCE:
        return _none("no likely duplicate", conf)
    if key.startswith("issue-"):
        i = next(i for i in issues if f"issue-{i['n']}" == key)
        match = {"kind": "issue", "n": i["n"], "title": i["title"], "url": f"https://github.com/{repo}/issues/{i['n']}"}
    else:
        p = prds[int(key[4:])]
        url = f"#/features/{quote(p['slug'], safe='')}?repo={repo}"
        match = {"kind": "prd", "path": p["path"], "title": p["title"], "url": url}
    return {"match": match, "confidence": conf, "why": "looks like the same request"}
