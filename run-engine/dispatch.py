"""Roster resolution and DoR screening for the `aiw ui` dispatch page.

Pure logic only — parsing, DoR screening, lane detection, dedup, skip checks —
lives at the top, exactly as `epic.py` separates its DAG math from its I/O.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------- roster


def parse_issue_list(raw: str) -> list[int]:
    """Comma-separated issue numbers, tolerant of `#` prefixes, whitespace, and
    repeated separators. Raises ValueError on empty or non-numeric input rather
    than silently dropping the bad token — a typo'd issue number must not
    quietly vanish from the roster."""
    tokens = [t.strip().lstrip("#") for t in (raw or "").split(",")]
    tokens = [t for t in tokens if t]
    if not tokens:
        raise ValueError(f"no issue numbers found in: {raw!r}")
    out = []
    for t in tokens:
        if not t.isdigit():
            raise ValueError(f"not a valid issue number: {t!r}")
        out.append(int(t))
    return out


def dedupe(issue_numbers: list[int]) -> list[int]:
    """Drop repeats, first occurrence wins, order preserved."""
    seen = set()
    out = []
    for n in issue_numbers:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


# --------------------------------------------------------------------------- DoR pre-screen

# Mirrors the six numbered items in definition-of-ready.md. Each entry is
# (label, heading-pattern-words) — the pattern tolerates #/##/### markers,
# case, and trailing text after the heading (e.g. "(draft)"). Also matches
# the literal section headings `commands/gh-issue.md` actually emits
# ("Why", "Context / Affected Code", ...) so an issue this plugin's own
# tooling generates screens ready rather than reporting permanent gaps.
# "Summary" is still accepted for older issues and /intake bodies.
DOR_ITEMS = [
    ("Problem & why", r"problem\s*&?\s*why|problem\s+and\s+why|^why\b|summary"),
    ("Scope", r"scope"),
    ("Acceptance criteria", r"acceptance\s+criteria"),
    ("Affected surface", r"affected\s+surface|affected\s+code"),
    ("Non-functional constraints", r"non-?functional\s+constraints"),
    ("Dependencies / blockers", r"dependencies\s*/?\s*blockers|dependencies\s+and\s+blockers"),
]


def _section_bodies(body: str) -> dict:
    """Map each markdown heading line to the non-empty text beneath it, up to
    the next heading. Only headings that have at least one non-blank line of
    content register a body."""
    lines = body.splitlines()
    heading_re = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
    sections: dict[str, str] = {}
    current_title = None
    current_lines: list[str] = []

    def flush():
        if current_title is not None:
            text = "\n".join(current_lines).strip()
            sections[current_title] = text

    for line in lines:
        m = heading_re.match(line)
        if m:
            flush()
            current_title = m.group(1).strip()
            current_lines = []
        elif current_title is not None:
            current_lines.append(line)
    flush()
    return sections


def dor_gaps(body: str | None) -> list[str]:
    """Mechanical Definition-of-Ready screen. Returns the human-readable gap
    labels for items not satisfied. Never raises — a None/empty body simply
    reports every item as a gap."""
    sections = _section_bodies(body or "")
    gaps = []
    for label, pattern in DOR_ITEMS:
        matched_text = None
        for title, text in sections.items():
            if not re.search(pattern, title, re.I):
                continue
            if text:
                matched_text = text
                break
            # This heading matches but has no prose directly beneath it (e.g.
            # a parent heading like "## Scope" followed immediately by
            # "### In scope" / "### Out of scope" subsections) — keep
            # scanning for another matching heading that does have content
            # before calling it a gap.
        if not matched_text:
            gaps.append(f"{label}: missing or empty")
    return gaps


# --------------------------------------------------------------------------- lane mode


def lane_mode(labels: list[str]) -> str:
    """ "lean" if a `lean` label (case-insensitive) is present, else "full"."""
    return "lean" if any((lab or "").strip().lower() == "lean" for lab in labels or []) else "full"


# --------------------------------------------------------------------------- skip detection

import json  # noqa: E402
import os  # noqa: E402


def skip_reason(run_json_path: str | None, has_open_pr: bool) -> str | None:
    """A reason to skip dispatching this issue, or None to proceed.

    "running" and an open PR are both skip reasons; "done"/"escalated" are
    NOT — those are re-runnable. A missing/corrupt/unreadable run.json is
    treated as no existing run — never raises, mirrors stack.py's
    _read_holder/_json_file fail-soft pattern."""
    if has_open_pr:
        return "an open PR already exists for this issue"
    if run_json_path:
        try:
            with open(run_json_path, encoding="utf-8") as fh:
                raw = fh.read()
        except OSError:
            raw = None
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict) and data.get("status") == "running":
                return "a run is already in progress (status=running)"
    return None


# --------------------------------------------------------------------------- checkouts.json registry

from shared import data_dir, run_dir_for  # noqa: E402
from shared import ledger_path as _ledger_path  # noqa: E402
from stack import _write_holder  # noqa: E402


def checkouts_path() -> str:
    return os.path.join(data_dir(), "checkouts.json")


def read_checkouts() -> dict:
    """{} for a missing, zero-byte, or non-JSON file — the registry is
    best-effort bookkeeping, not load-bearing state."""
    path = checkouts_path()
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def register_checkout(slug: str, path: str) -> None:
    """Atomically add slug -> path to the registry. Writes only the slug/path
    pair given — never os.environ, never .env content."""
    out_path = checkouts_path()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    current = read_checkouts()
    current[slug] = path
    # Reuse stack.py's tmp-file + os.replace atomic-write pattern rather than
    # re-implementing it (it already includes threading.get_ident() in the
    # tmp filename for disambiguation, which a hand-rolled copy here lacked).
    _write_holder(out_path, current)


from shared import gh_json  # noqa: E402


def _has_open_linked_pr(slug: str, linked_numbers: list[int]) -> tuple[bool | None, str | None]:
    """Whether any of `linked_numbers` (this issue's closedByPullRequestsReferences
    PR numbers) is currently open. Returns (None, error) on a `gh` failure rather
    than silently defaulting to False — a silent failure here would flip from
    "skip everything" to "double-dispatch everything", which is worse.

    `gh pr list --search "linked:<n>"` is NOT a valid GitHub search qualifier —
    `gh` silently ignores it and returns every open PR in the repo, so this
    deliberately does NOT use --search at all."""
    if not linked_numbers:
        return False, None
    pr_data, proc = gh_json(
        [
            "pr",
            "list",
            "--repo",
            slug,
            "--state",
            "open",
            "--json",
            "number",
            "--limit",
            "1000",
        ]
    )
    if proc.returncode != 0:
        return None, (proc.stderr or "").strip()[:200] or "gh pr list failed"
    open_numbers = {n.get("number") for n in (pr_data or []) if isinstance(n, dict)}
    return any(n in open_numbers for n in linked_numbers), None


def _issue_readiness(args, number: int) -> dict:
    """Fetch one issue's body/labels/state/linked-PRs and screen it. A resolution
    failure (bad number, gh error) is reported, not raised — the rest of the
    roster must still be screened. A closed issue is reported as closed rather
    than silently screening ready or silently vanishing from the report."""
    data, proc = gh_json(
        [
            "issue",
            "view",
            str(number),
            "--repo",
            args.slug,
            "--json",
            "title,body,labels,state,closedByPullRequestsReferences",
        ]
    )
    if proc.returncode != 0:
        return {"issue": number, "error": (proc.stderr or "").strip()[:200] or "gh issue view failed"}

    state = (data.get("state") or "").upper() if isinstance(data, dict) else ""
    if state == "CLOSED":
        return {"issue": number, "closed": True, "title": data.get("title") or ""}

    body = data.get("body") if isinstance(data, dict) else None
    labels = [lab.get("name", "") for lab in (data.get("labels") or [])] if isinstance(data, dict) else []
    gaps = dor_gaps(body)
    mode = lane_mode(labels)

    linked = data.get("closedByPullRequestsReferences") or [] if isinstance(data, dict) else []
    linked_numbers = [p.get("number") for p in linked if isinstance(p, dict) and p.get("number") is not None]
    has_open_pr, pr_error = _has_open_linked_pr(args.slug, linked_numbers)
    if pr_error:
        return {"issue": number, "error": f"could not check open PRs: {pr_error}"}

    run_json_path = _ledger_path(run_dir_for(os.path.join(data_dir(), "runs"), args.slug, number))
    reason = skip_reason(run_json_path, has_open_pr)

    from epic import parse_depends  # local: epic imports shared, dispatch is imported early

    return {
        "issue": number,
        "gaps": gaps,
        "mode": mode,
        "skip_reason": reason,
        "title": data.get("title") or "",
        "deps": parse_depends(body),
    }
