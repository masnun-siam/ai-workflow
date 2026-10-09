"""`aiw refined` — take the plan straight from a refined issue body, skipping researcher + planner.

A `refined` issue (filed by /gh-issue or /jira-to-gh) already carries Acceptance Criteria and a
numbered How — the planner's own starting point. When the label AND the body both check out, this
writes the two envelopes those stations would have produced (researcher as an orchestrator skip,
planner synthesized from the body) so the run routes them like any other. Exit 1 with a reason
means "not actually refined": the orchestrator runs phases 0.5 and 1 as usual.

Deterministic on purpose: zero tokens, and anything it cannot parse falls back to the planner.
"""

from __future__ import annotations

import os
import re
import subprocess

from shared import die, load_ledger, write_json

SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
BULLET_RE = re.compile(r"^\s*[-*]\s+(?:\[[ xX]\]\s+)?(.+?)\s*$", re.MULTILINE)
STEP_RE = re.compile(r"^\s*\d+\.\s+\S", re.MULTILINE)
FIELD_RE = r"^\s*[-*]?\s*\**{}\**\s*:\s*`?([^`\s]+)`?\s*$"
CONVENTIONAL_ROOTS = ("tests", "test", "__tests__", "spec")


def sections(body: str) -> dict[str, str]:
    """`## Heading` -> section text, keyed by the lower-cased heading."""
    out: dict[str, str] = {}
    marks = list(SECTION_RE.finditer(body))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        out[m.group(1).strip().lower()] = body[m.end():end].strip()
    return out


def field(text: str, name: str) -> str | None:
    m = re.search(FIELD_RE.format(re.escape(name)), text, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else None


def safe_rel(path: str) -> bool:
    norm = os.path.normpath(path)
    return not os.path.isabs(norm) and norm != ".." and not norm.startswith("../")


def detect_test_root(repo: str) -> str | None:
    # ponytail: only the single-conventional-dir case; a monorepo or odd layout states `Test root:` in How.
    found = [d for d in CONVENTIONAL_ROOTS if os.path.isdir(os.path.join(repo, d))]
    return found[0] + "/" if len(found) == 1 else None


def default_branch(repo: str) -> str | None:
    proc = subprocess.run(
        ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        cwd=repo, capture_output=True, text=True,
    )
    ref = proc.stdout.strip()
    return ref.split("/", 1)[1] if proc.returncode == 0 and "/" in ref else None


def parse(labels: list[str], body: str, repo: str) -> tuple[dict | None, str]:
    """(handoff, "") when refined, else (None, reason)."""
    if "refined" not in {lab.strip().lower() for lab in labels}:
        return None, "no `refined` label"
    secs = sections(body)
    ac = [b for b in BULLET_RE.findall(secs.get("acceptance criteria", "")) if b]
    if not ac:
        return None, "`## Acceptance Criteria` is missing or has no bullet items"
    how = secs.get("how", "")
    if not STEP_RE.search(how):
        return None, "`## How` is missing or has no numbered steps"
    if re.search(r"\[[^\]\n]*placeholder[^\]\n]*\]|\[TBD\]|\[TODO\]", body, re.IGNORECASE):
        return None, "body still contains a [bracketed placeholder]"

    test_root = field(how, "Test root") or detect_test_root(repo)
    if not test_root:
        return None, "no `Test root:` line in How and no single conventional test dir (tests/, test/, __tests__/, spec/)"
    if not safe_rel(test_root):
        return None, f"test root {test_root!r} is not a repo-relative path"
    base = field(how, "Base branch") or default_branch(repo)
    if not base:
        return None, "no `Base branch:` line in How and origin/HEAD is unset"

    test_cases = [f"[acceptance] {c}" for c in ac]
    plan_md = "\n".join([
        "## Test root", test_root, "",
        "## PR base branch", base, "",
        "## Test cases", *[f"- {c}" for c in test_cases], "",
        "## Implementation approach", how, "",
        "## Risks / open questions",
        "- Plan taken verbatim from the refined issue body; run-planner did not run, so no "
        "drift between the How section and the current code was checked.",
    ])
    return {
        "plan_md": plan_md, "test_root": test_root, "base_branch": base,
        "test_cases": test_cases, "acceptance_criteria": ac,
    }, ""


def cmd_refined(args) -> None:
    ledger = load_ledger(args.run_dir)
    repo = args.repo or ledger.context.get("repo") or os.getcwd()
    with open(args.body_file, encoding="utf-8") as fh:
        body = fh.read()
    handoff, reason = parse(args.labels.split(","), body, repo)
    if handoff is None:
        die(1, f"not refined: {reason}")
    skip = "skipped — refined issue, plan taken from the issue body"
    write_json(os.path.join(args.run_dir, "00-readiness.json"), {
        "issue": ledger.issue, "station": "researcher", "status": "passed", "attempt": 1,
        "summary": skip, "evidence": {"skipped": True},
        "handoff": {"brief": "", "gaps": [], "assumptions": []},
    })
    write_json(os.path.join(args.run_dir, "10-plan.json"), {
        "issue": ledger.issue, "station": "planner", "status": "passed", "attempt": 1,
        "summary": skip, "evidence": {"skipped": True}, "handoff": handoff,
    })
    print(f"refined: test_root={handoff['test_root']} base_branch={handoff['base_branch']} "
          f"acceptance_criteria={len(handoff['acceptance_criteria'])}")


def register(sub, add) -> None:
    p = add("refined", "write researcher+planner envelopes from a refined issue body; exit 1 if not refined")
    p.add_argument("--labels", default="", help="comma-separated issue labels")
    p.add_argument("--body-file", required=True, help="file holding the issue body")
    p.set_defaults(func=cmd_refined)
