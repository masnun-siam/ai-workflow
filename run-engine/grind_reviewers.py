"""`aiw grind-reviewers --pr <url>`: who a PR's grind asks, from Settings and channels.json. Stdlib only.

One answer for grind start, the dispatch preview and /pr-grind, so the skip decision and the mentions agree:
{path: "slack" | "github" | None, channel, mentions, logins, unlogged, skip}. No network call.
"""

from __future__ import annotations

import json
import re
import sys

import dispatch
import ui_settings

NO_REVIEWER = "no Slack channel or reviewer, its lanes skip grinding"


def _empty(skip=None) -> dict:
    return {"path": None, "channel": None, "mentions": [], "logins": [], "unlogged": [], "skip": skip}


def _settings(strict: bool) -> dict:
    """ui_settings.load()'s shape; a missing file stays missing (load() would write the migration)."""
    try:
        with open(ui_settings._path(), encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        return {"reviewers": [], "active_reviewers": [], "repos": {}}
    except OSError as e:
        if strict:
            raise ValueError(f"cannot read ui_settings.json: {e}") from None
        raw = None
    if strict:
        try:
            data = json.loads(raw)
        except ValueError as e:
            raise ValueError(f"cannot read ui_settings.json: {e}") from None
        if not isinstance(data, dict):
            raise ValueError("cannot read ui_settings.json: not an object")
    return ui_settings.load()  # lenient, and runs the one-time migration


def _find(d, repo: str):
    """d's value under repo, ignoring case (None when absent)."""
    return next((v for k, v in (d if isinstance(d, dict) else {}).items() if k.lower() == repo.lower()), None)


def resolve(repo: str, strict: bool = False) -> dict:
    return _resolve(repo, _settings(strict), ui_settings._channels_json())


def _resolve(repo: str, s: dict, ch: dict) -> dict:
    r = _find(s["repos"], repo)
    mapped = _find(ch.get("channels"), repo)
    if r is None and not mapped and _find(dispatch.read_checkouts(), repo) is None:
        return _empty()
    r = r or {}
    stored = r.get("slack_channel") or ""
    if r.get("channel_invalid"):
        return _empty(f"invalid Slack channel {stored}, pick a channel in Settings")
    path = "slack" if stored or mapped else "github"
    ids = r["reviewers"] if r.get("reviewers") is not None else s["active_reviewers"]
    revs = [x for x in s["reviewers"] if x["id"] in ids]
    mentions = [x["slack_id"] for x in revs if x["slack_id"]]
    logins = [x["github_login"] for x in revs if x["github_login"]]
    if (path == "slack" and not mentions and not ch.get("bot_uid")) or (path == "github" and not logins):
        return _empty(NO_REVIEWER)
    unlogged = [x["slack_id"] for x in revs if x["slack_id"] and not x["github_login"]] if path == "slack" else []
    return {
        "path": path,
        "channel": stored or None,
        "mentions": mentions,
        "logins": logins,
        "unlogged": unlogged,
        "skip": None,
    }


def resolve_pr(pr_url, strict: bool = False) -> dict:
    m = re.search(r"github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)", pr_url or "")
    return resolve(m.group(1), strict) if m else _empty()


def settings_view(settings: dict) -> dict:
    """GET /api/settings: load() plus the read-only bot_label and each repo's resolver path."""
    ch = ui_settings._channels_json()
    label = ch.get("bot_label")
    repos = {slug: {**r, "path": _resolve(slug, settings, ch)["path"]} for slug, r in settings["repos"].items()}
    return {**settings, "repos": repos, "bot_label": label if isinstance(label, str) and label else None}


def cmd_grind_reviewers(args) -> None:
    try:
        out = resolve_pr(args.pr, strict=True)
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    print(json.dumps(out))


def register(sub, add) -> None:
    p = sub.add_parser("grind-reviewers", help="print a PR's grind path, channel and reviewers as JSON")
    p.add_argument("--pr", required=True, help="PR url")
    p.set_defaults(func=cmd_grind_reviewers)
