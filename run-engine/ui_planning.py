"""Planning board data (FR-15): PRD files + poller snapshot + panel state -> the /api/planning response.

Each `docs/prds/*.md` in the checkout is a card. Status comes from the header line
(`**Status:** Draft · ... · **Slug:** `x``, templates/prd.md). A PRD's epic is the open issue labelled
`epic` and `prd-<slug>` (guides/engineering-workflow.md); its children are the issues whose parent is
the epic (or listed in its sub_issues), plus any issue labelled `prd-<slug>`.

Card: {slug, title, status, path, abs_path, column, pr, epic, issues, refined, unrefined, children, panel}.
`children` is [{n, title, refined}] of its open child issues; `closed_children` is [{n, title}] of its closed ones.
`unrefined` lists the child issue numbers not yet labelled `refined`. `column` is one of
draft | in_review | approved | tasks_filed | refined | done. `done` is an Approved PRD with no open child
whose epic is closed, or open with sub-issues that are all closed. `pr` is {n, url} for an In review PRD (an open PR
whose branch or title mentions the slug; heuristic), else None. `panels` maps slug -> a panel id or an
already-built panel_status dict.
"""

from __future__ import annotations

import glob
import os
import re

import peer_review

_STATUS = re.compile(r"\*\*Status:\*\*\s*([A-Za-z ]+?)\s*(?:·|\||$)", re.M)
_SLUG = re.compile(r"\*\*Slug:\*\*\s*`?([A-Za-z0-9._-]+)`?")
_TITLE = re.compile(r"^#\s+(?:PRD\s*[—–:-]\s*)?(.+?)\s*$", re.M)
_STATUSES = {"draft": "Draft", "in review": "In review", "approved": "Approved"}


def _parse(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(4000)
    except OSError:
        return None
    stem = os.path.splitext(os.path.basename(path))[0]
    st, slug, title = _STATUS.search(head), _SLUG.search(head), _TITLE.search(head)
    return {
        "slug": slug.group(1) if slug else stem,
        "title": title.group(1) if title else stem,
        "status": _STATUSES.get(st.group(1).strip().lower(), "Draft") if st else "Draft",
    }


def _panel(panels, slug):
    p = (panels or {}).get(slug)
    if isinstance(p, str):
        try:
            # id and root_session let the card link the root and post lens actions
            return {
                **peer_review.panel_status(p),
                "id": p,
                "root_session": peer_review.load_panel(p).get("root_session"),
            }
        except (OSError, ValueError, KeyError):
            return None
    return p if isinstance(p, dict) else None


def build(repo: str, checkout_path: str, snapshot: dict, panels: dict | None) -> dict:
    data = snapshot.get("data") or {}
    issues = data.get("issues") or []
    prs = data.get("open_prs") or []
    closed_epics = data.get("closed_epics") or []
    out = []
    for path in sorted(glob.glob(os.path.join(checkout_path or "", "docs", "prds", "*.md"))):
        meta = _parse(path)
        if not meta:
            continue
        slug, label = meta["slug"], f"prd-{meta['slug']}"
        epic = next((i for i in issues if "epic" in i["labels"] and label in i["labels"]), None)
        kids = [
            i
            for i in issues
            if i is not epic
            and (
                (epic and (i["parent"] == epic["n"] or i["n"] in epic["sub_issues"]))
                or ("epic" not in i["labels"] and label in i["labels"])
            )
        ]
        refined = sum("refined" in i["labels"] for i in kids)
        done_epic = epic or next((e for e in closed_epics if label in e["labels"]), None)
        closed = (done_epic or {}).get("closed_subs") or []
        pr = None
        if meta["status"] == "In review":
            hit = next((p for p in prs if slug in (p.get("head") or "") or slug in (p.get("title") or "")), None)
            pr = {"n": hit["n"], "url": hit["url"]} if hit else None
        if meta["status"] == "Draft":
            column = "draft"
        elif meta["status"] == "In review":
            column = "in_review"
        elif kids:
            column = "refined" if refined == len(kids) else "tasks_filed"
        elif (epic and epic["sub_issues"]) or (not epic and any(label in e["labels"] for e in closed_epics)):
            column = "done"
        else:
            column = "approved"
        out.append(
            {
                **meta,
                "path": os.path.relpath(path, checkout_path),
                "abs_path": os.path.abspath(path),  # POST /api/review wants the absolute artifact path
                "column": column,
                "pr": pr,
                "epic": epic["n"] if epic else None,
                "issues": len(kids),
                "refined": refined,
                "unrefined": sorted(i["n"] for i in kids if "refined" not in i["labels"]),
                "closed_children": sorted(closed, key=lambda c: c["n"]),
                "children": sorted(
                    ({"n": i["n"], "title": i["title"], "refined": "refined" in i["labels"]} for i in kids),
                    key=lambda c: c["n"],
                ),
                "panel": _panel(panels, slug),
            }
        )
    return {"repo": repo, "stale": snapshot.get("stale", True), "fetched_at": snapshot.get("fetched_at"), "prds": out}
