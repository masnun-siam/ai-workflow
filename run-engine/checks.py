"""Station post-checks: compute the verdict instead of believing it.

`config.json` says it in writing — the envelope's evidence gate is a "cooperative
completeness check, not fabrication-proof". So `run-fixer` can report `passed` with
three review threads still open and nothing pushed, and the run advances.

Every check here answers its station's central claim from something with no incentive
to pass: an exit code, a git object, a GitHub API response, a file on disk. The pattern
is not new to this repo — `route.py:test_root_violations` already does exactly this for
one case. This generalises it into a station-keyed table.

I/O half, like route.py. engine.py stays pure.

What a check CANNOT do: catch a station that fabricated an artifact the check then
reads back. It catches the omitted pass, the unresolved thread, the unpushed commit,
the green suite claimed as red. Authenticity still comes from H1/H2.
"""

from __future__ import annotations

import os
import re

import stack as stack_mod
import threads as threads_mod
from engine import resolve_review_panel
from shared import gh_json, run, shell

SUITE_TIMEOUT = 900


class CheckResult:
    __slots__ = ("ok", "reason", "unrunnable")

    def __init__(self, ok: bool, reason: str = "", unrunnable: bool = False):
        self.ok = ok
        self.reason = reason
        self.unrunnable = unrunnable

    def __repr__(self):
        kind = "unrunnable" if self.unrunnable else ("ok" if self.ok else "FAIL")
        return f"<CheckResult {kind}: {self.reason}>"


def passed(reason: str = "") -> CheckResult:
    return CheckResult(True, reason)


def failed(reason: str) -> CheckResult:
    return CheckResult(False, reason)


def unrunnable(reason: str) -> CheckResult:
    return CheckResult(True, reason, unrunnable=True)


# --------------------------------------------------------------------------- the suite


def run_suite(ledger, repo: str):
    """Run the run's own `test_cmd`. Returns (exit_code, reason); exit_code None means
    the suite could not be run at all, which is NOT the same as a failure.

    The only place a check ever runs tests, so the container contract lives in exactly
    one function. `test_cmd_host` is never used here: it executes outside the stack's
    database and services, so it fails spuriously in exactly the repos the Docker path
    exists for. `test_cmd` is the contract; `test_cmd_host` is a record.
    """
    state = ledger.context.get("stack")
    cmd = ledger.context.get("test_cmd")
    if state in ("failed", "none") and not cmd:
        return None, f"no runner (stack={state})"
    if not cmd:
        return None, "no test_cmd recorded"
    if state == "up":
        # stack.py owns the probe. A green suite out of a dead or stale container is
        # the failure mode `source_mounted` only tiptoes around; this makes it
        # checkable rather than assumed.
        healthy, why = stack_mod.app_healthy(ledger, repo)
        if not healthy:
            return None, why
    proc = shell(cmd, cwd=repo, timeout=SUITE_TIMEOUT)
    if proc.returncode == 124:
        return None, f"suite timed out after {SUITE_TIMEOUT}s"
    lines = (proc.stdout or proc.stderr or "").strip().splitlines()
    return proc.returncode, (lines[-1][:200] if lines else "")


def _git(repo: str, *argv):
    return run(["git", *argv], cwd=repo)


def _handoff(envelope) -> dict:
    h = envelope.get("handoff")
    return h if isinstance(h, dict) else {}


# --------------------------------------------------------------------------- checks


def check_sdet_post(ledger, envelope, repo, config) -> CheckResult:
    """The SDET's whole claim is `red_confirmed`. A suite that is green cannot have
    proved anything red."""
    handoff = _handoff(envelope)
    test_root = (ledger.context.get("test_root") or "").rstrip("/")

    files = handoff.get("test_files") or []
    if not files:
        return failed("no handoff.test_files[] — the SDET reported passing with no tests named")
    for rel in files:
        if not os.path.exists(os.path.join(repo, rel)):
            return failed(f"handoff names a test file that does not exist on disk: {rel}")
        if test_root and not os.path.normpath(rel).startswith(os.path.normpath(test_root)):
            return failed(f"test file outside the approved test root {test_root}: {rel}")

    code, detail = run_suite(ledger, repo)
    if code is None:
        # Non-fatal: a missing runner is already a first-class state everywhere else in
        # this pipeline (stack: failed), and a station that says so is not lying.
        return unrunnable(f"could not verify RED: {detail}")
    if code == 0:
        return failed("the suite is GREEN — there is no red to prove")
    return passed()

# KNOWN HOLE, deliberate: this inverts the WHOLE suite, with no known-red baseline. A
# repo whose suite is already red for unrelated reasons passes check_sdet_post trivially.
# The alternative is wf's known-red baseline, deferred until this actually bites — a
# baseline that is itself wrong is worse than no baseline, and the SDET's tests are
# reviewed by a human at Gate 1 anyway.


def check_dev_post(ledger, envelope, repo, config) -> CheckResult:
    """Dev claims a commit, a file list, and a green suite. All three are checkable."""
    handoff = _handoff(envelope)
    sha = handoff.get("commit")
    if sha:
        if _git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
            return failed(f"handoff.commit does not resolve to a commit in this repo: {sha}")

    base = ledger.context.get("sdet_sha")
    if not base:
        merge_base = _git(repo, "merge-base", f"origin/{ledger.context.get('base_branch')}", "HEAD")
        base = merge_base.stdout.strip() if merge_base.returncode == 0 else None
    if base:
        diff = _git(repo, "diff", "--name-only", f"{base}..HEAD")
        if diff.returncode == 0:
            test_root = (ledger.context.get("test_root") or "").rstrip("/")
            claimed = {os.path.normpath(f) for f in (handoff.get("files_changed") or [])}
            actual = {os.path.normpath(f) for f in diff.stdout.split() if f.strip()}
            # The test root is the ownership guard's business, not this one's — it has
            # already run and exited 6 if anything there moved.
            if test_root:
                actual = {f for f in actual if not f.startswith(os.path.normpath(test_root))}
            undeclared = sorted(actual - claimed)
            if undeclared:
                return failed(
                    "changed files missing from handoff.files_changed[]: " + ", ".join(undeclared[:8])
                )

    code, detail = run_suite(ledger, repo)
    if code is None:
        return unrunnable(f"could not verify the suite: {detail}")
    if code != 0:
        return failed(f"dev reported passed but the suite exits {code}: {detail}")
    return passed()


PATH_RE = re.compile(r"[\w./-]+\.(?:png|jpg|jpeg|gif|webp|mp4|webm|har|json|txt|log|zip|trace)")


def check_verifier_post(ledger, envelope, repo, config) -> CheckResult:
    """The verifier's verdict has to agree with its own criteria, and any artifact it
    says it captured has to exist. That second half is what catches an observation
    nobody made."""
    handoff = _handoff(envelope)
    verdict = (handoff.get("verdict") or "").lower()
    if verdict in ("unverifiable", "skipped") or (envelope.get("evidence") or {}).get("skipped"):
        # run-verifier.md maps UNVERIFIABLE to passed BY DESIGN — a verifier that cannot
        # see the app must never hold the run hostage.
        return passed("unverifiable/skipped is a designed pass")

    criteria = handoff.get("criteria") or []
    if verdict == "pass":
        unmet = [c.get("criterion") for c in criteria if isinstance(c, dict) and not c.get("met")]
        if unmet:
            return failed("verdict is pass but these criteria are not met: " + "; ".join(
                str(u)[:60] for u in unmet[:5]))
        if not criteria:
            return failed("verdict is pass with no criteria[] — nothing was actually checked")

    text = " ".join(
        str(c.get("excerpt", "")) for c in ((envelope.get("evidence") or {}).get("commands") or [])
        if isinstance(c, dict)
    )
    for candidate in set(PATH_RE.findall(text)):
        if "/" not in candidate:
            continue  # a bare filename in prose is not a claim that a file exists
        if not os.path.isabs(candidate) and not os.path.exists(os.path.join(repo, candidate)):
            if not os.path.exists(candidate):
                return failed(f"evidence names an artifact that is not on disk: {candidate}")
    return passed()


def check_reviewer_post(ledger, envelope, repo, config) -> CheckResult:
    """The review has to exist on the PR, and the panel has to be the one policy chose."""
    handoff = _handoff(envelope)

    expected = resolve_review_panel(ledger.classification or {}, config.get("review_policy") or {})
    claimed = handoff.get("panel")
    if claimed is not None and sorted(claimed) != sorted(expected):
        return failed(
            f"handoff.panel {sorted(claimed)} is not the policy panel {sorted(expected)}"
        )

    url = handoff.get("review_url") or ""
    m = re.search(r"#pullrequestreview-(\d+)", url)
    pr = ledger.context.get("pr_number")
    if not m or not pr:
        return unrunnable("no review id in handoff.review_url, or no pr_number in the ledger")
    slug, _ = gh_json(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], cwd=repo)
    if not isinstance(slug, str) or "/" not in slug:
        return unrunnable("could not resolve owner/repo from the checkout")
    review, proc = gh_json(["api", f"repos/{slug}/pulls/{pr}/reviews/{m.group(1)}"], cwd=repo)
    if not isinstance(review, dict) or not review.get("id"):
        return failed(f"review {m.group(1)} does not exist on PR #{pr}")

    # Deliberately NOT an exact comment-count == sum(counts_by_severity) equality. A
    # reviewer that lists its nits in the review body rather than as inline comments is
    # behaving correctly, and a check that bounced an opus reviewer for that would fire
    # on ordinary runs until everyone learned to ignore it. What is checked is that a
    # review claiming findings is not empty.
    counts = handoff.get("counts_by_severity") or {}
    total = sum(v for v in counts.values() if isinstance(v, int))
    if total > 0 and not (review.get("body") or "").strip():
        comments, _ = gh_json(["api", f"repos/{slug}/pulls/{pr}/reviews/{m.group(1)}/comments"], cwd=repo)
        if not comments:
            return failed(f"review claims {total} findings but has no body and no comments")
    return passed()


def check_fixer_post(ledger, envelope, repo, config) -> CheckResult:
    """The motivating case: fixer reports `passed` with threads open and nothing pushed."""
    handoff = _handoff(envelope)

    head = _git(repo, "rev-parse", "HEAD")
    upstream = _git(repo, "rev-parse", "@{u}")
    if head.returncode != 0 or upstream.returncode != 0:
        return unrunnable("no upstream to compare against — the branch is not pushed anywhere")
    if head.stdout.strip() != upstream.stdout.strip():
        return failed("local HEAD is ahead of the remote — the push never happened")
    for sha in handoff.get("commits") or []:
        if _git(repo, "merge-base", "--is-ancestor", sha, "@{u}").returncode != 0:
            return failed(f"handoff.commits names {sha}, which is not on the remote branch")

    pr = ledger.context.get("pr_number")
    if not pr:
        return unrunnable("no pr_number in the ledger")
    slug, _ = gh_json(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], cwd=repo)
    if not isinstance(slug, str) or "/" not in slug:
        return unrunnable("could not resolve owner/repo from the checkout")
    owner, _, name = slug.partition("/")
    try:
        open_threads = [t for t in threads_mod.list_threads(owner, name, int(pr), cwd=repo)
                        if not t["is_resolved"]]
    except SystemExit:
        return unrunnable("could not read the PR's review threads")

    # Every thread still open has to be one the fixer explicitly handed onward. This is
    # slightly stronger than "threads that were open when fixer started", and simpler:
    # there is no snapshot to take, and a thread opened mid-pass that nobody handled is
    # exactly as unfinished as one that was there all along.
    declared = set()
    for key in ("needs_confirmation", "needs_test_root_fix", "needs_new_file"):
        for item in handoff.get(key) or []:
            if isinstance(item, dict):
                declared.add(item.get("thread_node_id"))
                declared.add(item.get("thread_url"))
    orphaned = [t for t in open_threads if t["node_id"] not in declared and t["url"] not in declared]
    if orphaned:
        return failed(
            f"{len(orphaned)} review thread(s) still open and not handed onward: "
            + ", ".join(t["url"] or t["node_id"] for t in orphaned[:5])
        )
    return passed()


# --------------------------------------------------------------------------- pre-guards


def check_sdet_pre(ledger, envelope, repo, config) -> CheckResult:
    proc = _git(repo, "status", "--porcelain")
    if proc.returncode != 0:
        return unrunnable("git status failed")
    if proc.stdout.strip():
        return failed("worktree is dirty before the SDET runs: " + proc.stdout.strip()[:200])
    return passed()


def _pr_is_open(ledger, repo) -> CheckResult:
    pr = ledger.context.get("pr_number")
    if not pr:
        return unrunnable("no pr_number in the ledger")
    state, proc = gh_json(["pr", "view", str(pr), "--json", "state", "-q", ".state"], cwd=repo)
    if state is None:
        return unrunnable("could not read the PR: " + (proc.stderr or "").strip()[:120])
    if str(state).upper() != "OPEN":
        return failed(f"PR #{pr} is {state}, not OPEN")
    return passed()


def check_reviewer_pre(ledger, envelope, repo, config) -> CheckResult:
    return _pr_is_open(ledger, repo)


def check_fixer_pre(ledger, envelope, repo, config) -> CheckResult:
    return _pr_is_open(ledger, repo)


# Data, not code: adding a station is a line here.
POST_CHECKS = {
    "sdet": check_sdet_post,
    "dev": check_dev_post,
    "verifier": check_verifier_post,
    "reviewer": check_reviewer_post,
    "fixer": check_fixer_post,
}

# Deliberately only three. A pre-check that restates what the ledger already knows is
# noise that trains you to ignore the ones that matter.
PRE_CHECKS = {
    "sdet": check_sdet_pre,
    "reviewer": check_reviewer_pre,
    "fixer": check_fixer_pre,
}

# For these two, a check that cannot run is itself the finding: `fixer` claiming success
# with unreadable threads, and `reviewer` claiming a review nobody can fetch, are exactly
# the states the checks exist for. Everywhere else, an unrunnable check is a note.
FATAL_WHEN_UNRUNNABLE = {"fixer", "reviewer"}


def run_post_check(station: str, ledger, envelope, repo: str, config: dict) -> CheckResult | None:
    checks_cfg = config.get("checks") or {}
    if not checks_cfg.get("enabled", True) or station in (checks_cfg.get("skip") or []):
        return None
    fn = POST_CHECKS.get(station)
    return fn(ledger, envelope, repo, config) if fn else None
