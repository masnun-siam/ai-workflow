"""Roster resolution for `aiw dispatch plan`.

Pure logic only — parsing, DoR screening, lane detection, dedup, skip checks —
lives at the top, exactly as `epic.py` separates its DAG math from its I/O.
This PR (B1) resolves the roster and reports readiness; it does not dispatch
any station (that's PR-B2's `dispatch start`).
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
# ("Summary", "Context / Affected Code", ...) so an issue this plugin's own
# tooling generates screens ready rather than reporting permanent gaps.
DOR_ITEMS = [
    ("Problem & why", r"problem\s*&?\s*why|problem\s+and\s+why|summary"),
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
    """"lean" if a `lean` label (case-insensitive) is present, else "full"."""
    return "lean" if any((l or "").strip().lower() == "lean" for l in labels or []) else "full"


# --------------------------------------------------------------------------- skip detection

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402


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


def _looks_like_checkout(path: str, slug: str) -> bool:
    """True only if `path` is an actual git checkout, and (best-effort) its
    `origin` remote plausibly matches `slug`. Guards against auto-registering
    a bogus path (e.g. an empty tmpdir run with `--slug totally/bogus`) into
    checkouts.json — a mapping that would otherwise persist permanently."""
    try:
        proc = subprocess.run(
            ["git", "-C", path, "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=10,
        )
    except OSError:
        return False
    if proc.returncode != 0 or proc.stdout.strip() != "true":
        return False
    remote = subprocess.run(
        ["git", "-C", path, "remote", "get-url", "origin"],
        capture_output=True, text=True, timeout=10,
    )
    if remote.returncode == 0 and slug.lower() not in (remote.stdout or "").strip().lower():
        return False  # a real git checkout, but of something else
    return True


# --------------------------------------------------------------------------- cmd_plan (I/O)

from shared import die, gh_json  # noqa: E402


def _resolve_issue_numbers(args) -> list[int]:
    """Resolve the roster from exactly one of --issues/--query/--project+--status/--epic."""
    modes_given = [
        bool(args.issues),
        bool(args.query),
        bool(args.project is not None or args.status is not None),
        bool(args.epic is not None),
    ]
    if sum(modes_given) != 1:
        die(2, "exactly one of --issues, --query, --project/--status, or --epic is required")

    if args.issues:
        return dedupe(parse_issue_list(args.issues))

    if args.query:
        data, proc = gh_json(
            ["issue", "list", "--repo", args.slug, "--search", args.query,
             "--json", "number", "--jq", "[.[].number]", "--limit", "1000"]
        )
        if proc.returncode != 0:
            die(1, f"--query failed: {(proc.stderr or '').strip()[:200]}")
        return dedupe([int(n) for n in (data or [])])

    if args.project is not None or args.status is not None:
        if args.project is None or args.status is None:
            die(2, "--project and --status must be given together")
        return dedupe(_project_issue_numbers(args.slug, args.project, args.status))

    # --epic
    linked, proc = gh_json(
        ["api", f"repos/{args.slug}/issues/{args.epic}/sub_issues", "--jq", "[.[].number]"],
    )
    if proc.returncode != 0:
        die(1, f"could not read #{args.epic}'s sub-issues: "
               f"{(proc.stderr or '').strip()[:200]}")
    return dedupe([int(n) for n in (linked or [])])


PROJECT_ITEMS_QUERY = """
query($o:String!,$n:Int!){ organization(login:$o){ projectV2(number:$n){
  items(first:100){ nodes{ content{ ... on Issue{ number } }
    fieldValueByName(name:"Status"){ ... on ProjectV2ItemFieldSingleSelectValue{ name } } } } } } }
"""

# Same repo-owned board shape, tried when the org query above finds nothing —
# a project can be owned by a user account rather than an organization.
PROJECT_ITEMS_QUERY_USER = PROJECT_ITEMS_QUERY.replace("organization", "user")


def _project_issue_numbers(slug: str, number: int, status: str) -> list[int]:
    owner = slug.partition("/")[0]
    for query in (PROJECT_ITEMS_QUERY, PROJECT_ITEMS_QUERY_USER):
        data, proc = gh_json(["api", "graphql", "-f", f"query={query}",
                              "-f", f"o={owner}", "-F", f"n={number}"])
        if proc.returncode != 0:
            continue
        root = ((data or {}).get("data") or {})
        holder = root.get("organization") or root.get("user")
        items = (((holder or {}).get("projectV2") or {}).get("items") or {}).get("nodes") or []
        if items:
            out = []
            for item in items:
                field = item.get("fieldValueByName") or {}
                if (field.get("name") or "").strip().lower() != status.strip().lower():
                    continue
                content = item.get("content") or {}
                if content.get("number") is not None:
                    out.append(int(content["number"]))
            return out
    return []


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
    pr_data, proc = gh_json([
        "pr", "list", "--repo", slug, "--state", "open",
        "--json", "number", "--limit", "1000",
    ])
    if proc.returncode != 0:
        return None, (proc.stderr or "").strip()[:200] or "gh pr list failed"
    open_numbers = {n.get("number") for n in (pr_data or []) if isinstance(n, dict)}
    return any(n in open_numbers for n in linked_numbers), None


def _issue_readiness(args, number: int) -> dict:
    """Fetch one issue's body/labels/state/linked-PRs and screen it. A resolution
    failure (bad number, gh error) is reported, not raised — the rest of the
    roster must still be screened. A closed issue is reported as closed rather
    than silently screening ready or silently vanishing from the report."""
    data, proc = gh_json([
        "issue", "view", str(number), "--repo", args.slug,
        "--json", "body,labels,state,closedByPullRequestsReferences",
    ])
    if proc.returncode != 0:
        return {"issue": number, "error": (proc.stderr or "").strip()[:200] or "gh issue view failed"}

    state = (data.get("state") or "").upper() if isinstance(data, dict) else ""
    if state == "CLOSED":
        return {"issue": number, "closed": True}

    body = data.get("body") if isinstance(data, dict) else None
    labels = [l.get("name", "") for l in (data.get("labels") or [])] if isinstance(data, dict) else []
    gaps = dor_gaps(body)
    mode = lane_mode(labels)

    linked = data.get("closedByPullRequestsReferences") or [] if isinstance(data, dict) else []
    linked_numbers = [p.get("number") for p in linked if isinstance(p, dict) and p.get("number") is not None]
    has_open_pr, pr_error = _has_open_linked_pr(args.slug, linked_numbers)
    if pr_error:
        return {"issue": number, "error": f"could not check open PRs: {pr_error}"}

    run_json_path = _ledger_path(run_dir_for(os.path.join(data_dir(), "runs"), args.slug, number))
    reason = skip_reason(run_json_path, has_open_pr)

    return {"issue": number, "gaps": gaps, "mode": mode, "skip_reason": reason}


def cmd_plan(args) -> None:
    numbers = _resolve_issue_numbers(args)

    # First use of this checkout for this repo: register it once, and only
    # if it's actually a git checkout of (plausibly) this slug.
    checkouts = read_checkouts()
    if args.slug not in checkouts:
        candidate = os.path.abspath(args.repo or os.getcwd())
        if _looks_like_checkout(candidate, args.slug):
            register_checkout(args.slug, candidate)

    if not numbers:
        print("nothing to dispatch")
        return

    for number in numbers:
        report = _issue_readiness(args, number)
        if "error" in report:
            print(f"#{number}: could not resolve ({report['error']})")
            continue
        if report.get("closed"):
            print(f"#{number}: closed  SKIP: issue is closed")
            continue
        ready = not report["gaps"]
        status = "ready" if ready else f"not ready: {'; '.join(report['gaps'])}"
        line = f"#{number}: {status}  lane={report['mode']}"
        if report["skip_reason"]:
            line += f"  SKIP: {report['skip_reason']}"
        print(line)


def register(sub, add) -> None:
    p = sub.add_parser("dispatch", help="resolve a roster and screen it before dispatching")
    ops = p.add_subparsers(dest="op", required=True)

    q = ops.add_parser("plan", help="resolve a roster, run the DoR screen, and report")
    q.add_argument("--slug", required=True, help="owner/repo")
    q.add_argument("--repo", help="checkout path to register in checkouts.json (default: cwd)")
    q.add_argument("--issues", help="comma-separated issue numbers")
    q.add_argument("--query", help="search query passed to `gh issue list --search`")
    q.add_argument("--project", type=int, help="Projects v2 board number")
    q.add_argument("--status", help="Projects v2 Status column name")
    q.add_argument("--epic", type=int, help="parent issue number; resolves its sub-issues")
    q.set_defaults(func=cmd_plan)
