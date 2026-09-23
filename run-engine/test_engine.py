#!/usr/bin/env python3
"""Self-check for the /run-issue engine. `python3 test_engine.py` — exit 0 = green.

Covers the cases where a subtle break would be silent. Deliberately assert-based
with no framework: this file must run anywhere python3 does, with no install step.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import (  # noqa: E402
    Ledger,
    RouteAction,
    Router,
    classify,
    glob_match,
    resolve_review_panel,
    validate_envelope,
)

HERE = os.path.dirname(os.path.abspath(__file__))
ROUTE = os.path.join(HERE, "route.py")
CONFIG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
FULL = CONFIG["modes"]["full"]["stations"]

passed = 0


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


def envelope(station: str, status: str = "passed", **kw) -> dict:
    env = {
        "issue": 41,
        "station": station,
        "status": status,
        "attempt": 1,
        "summary": "x",
        "evidence": {"commands": [{"cmd": "true", "exit": 0}]},
    }
    env.update(kw)
    return env


def ledger_at(station: str) -> Ledger:
    return Ledger(41, FULL, FULL.index(station))


# --- 1. bounce cap boundary -------------------------------------------------
# The cap must be enforced HERE, not by an orchestrator asked to keep a counter.

led = ledger_at("verifier")
router = Router(bounce_cap=2)
bounce = envelope("verifier", "bounce", bounce={"to": "dev", "reason": "broken"})

for attempt in range(2):
    action = router.next(led, bounce)
    assert action.kind == RouteAction.BOUNCE, f"attempt {attempt + 1} should bounce, got {action}"
    led.record_bounce("verifier", "dev")
    led.current_index = FULL.index("verifier")  # verifier re-runs and fails again

action = router.next(led, bounce)
assert action.kind == RouteAction.ESCALATE, f"cap+1 must escalate, got {action}"
assert "cap (2) exceeded" in action.reason, action.reason
ok("bounce cap: 2 bounces allowed, the 3rd escalates")


# --- 2. bounce to a station outside this run's roster -----------------------
# In --lean there is no sdet, and run-dev's prompt still says bounce `to: sdet`.
# That must escalate with the roster named, not blow up on an index lookup.

lean = Ledger(41, CONFIG["modes"]["lean"]["stations"], 2)
action = Router(2).next(lean, envelope("dev", "bounce", bounce={"to": "sdet", "reason": "bad test"}))
assert action.kind == RouteAction.ESCALATE, action
assert "not in this run's roster" in action.reason and "researcher -> planner" in action.reason
ok("bounce to a station outside the roster escalates, naming the roster")


# --- 3. passed on the last station -> done ----------------------------------

assert Router(2).next(ledger_at(FULL[-1]), envelope(FULL[-1])).kind == RouteAction.DONE
assert Router(2).next(ledger_at("sdet"), envelope("sdet")).target == "dev"
ok("passed advances one station; passed on the last station is done")


# --- 4. unknown status raises -----------------------------------------------

for bad in ("approved", "ok", None, ""):
    try:
        Router(2).next(ledger_at("dev"), envelope("dev", bad))
    except ValueError:
        pass
    else:
        raise AssertionError(f"status {bad!r} should have raised")
ok("an unrecognised status raises instead of being silently treated as passed")


# --- 5. (from,to) counter isolation -----------------------------------------
# run-issue keeps the dev and verify budgets separate on purpose. A target-keyed
# counter would merge them: a verifier->dev bounce would spend dev's own budget.

led = ledger_at("verifier")
led.record_bounce("verifier", "dev")
led.record_bounce("verifier", "dev")
assert led.bounce_count("verifier", "dev") == 2
assert led.bounce_count("dev", "sdet") == 0, "dev->sdet must not share verifier->dev's budget"
led.current_index = FULL.index("dev")
action = Router(2).next(led, envelope("dev", "bounce", bounce={"to": "sdet", "reason": "wrong test"}))
assert action.kind == RouteAction.BOUNCE, f"a fresh pair must still be allowed, got {action}"
ok("bounce budgets are per (from,to) pair, never merged")


# --- 6. the test-root guard sees a COMMITTED edit ---------------------------
# This is the bug the guard exists for: run-dev commits its work, so the old
# `git diff --name-only <test-root>` (worktree-vs-index) saw nothing.

with tempfile.TemporaryDirectory() as tmp:
    repo = os.path.join(tmp, "repo")
    run_dir = os.path.join(tmp, "run")
    os.makedirs(os.path.join(repo, "tests"))
    git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t"); git("config", "user.name", "t")
    open(os.path.join(repo, "tests", "a.test.js"), "w").write("expect(1).toBe(2)\n")
    git("add", "-A"); git("commit", "-qm", "sdet: red tests")
    sdet_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    # dev weakens the test AND COMMITS it — invisible to a worktree diff.
    open(os.path.join(repo, "tests", "a.test.js"), "w").write("expect(1).toBe(1)\n")
    git("add", "-A"); git("commit", "-qm", "dev: implement")

    stale = subprocess.run(
        ["git", "diff", "--name-only", "--", "tests"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    assert stale == "", "precondition: the OLD worktree-diff check sees nothing once committed"

    subprocess.run(
        [sys.executable, ROUTE, "init", run_dir, "--issue", "41", "--repo", repo],
        check=True, capture_output=True,
    )
    subprocess.run(
        [sys.executable, ROUTE, "set", run_dir, f"sdet_sha={sdet_sha}", "test_root=tests"],
        check=True, capture_output=True,
    )
    json.dump(envelope("dev"), open(os.path.join(run_dir, "30-build.json"), "w"))
    proc = subprocess.run(
        [sys.executable, ROUTE, "route", run_dir, "30-build.json", "--repo", repo],
        capture_output=True, text=True,
    )
    assert proc.returncode == 6, f"expected exit 6, got {proc.returncode}: {proc.stdout}{proc.stderr}"
    assert "tests/a.test.js" in proc.stderr, proc.stderr

    # The engine routes the bounce itself rather than asking the orchestrator to rewrite
    # dev's envelope — hand-authoring an envelope is exactly what H1 forbids, and the cap
    # has to be consumed or a tampering loop is unbounded.
    assert proc.stdout.strip() == "bounce(sdet)", proc.stdout
    led = json.load(open(os.path.join(run_dir, "run.json")))
    assert led["bounceCounts"].get("dev->sdet") == 1, led["bounceCounts"]
    assert led["stations"][led["currentIndex"]] == "sdet", led["currentIndex"]
ok("test-root guard catches an edit that was COMMITTED (the bug the old check missed)")
ok("...and routes the bounce itself, consuming the cap — no hand-authored envelope")


# --- 7. envelope validation -------------------------------------------------

led = ledger_at("dev")
assert validate_envelope(envelope("dev"), led, CONFIG) == []
assert any("missing required field: summary" in e for e in
           validate_envelope({k: v for k, v in envelope("dev").items() if k != "summary"}, led, CONFIG))
assert any("evidence.commands" in e for e in
           validate_envelope(envelope("dev", evidence={}), led, CONFIG)), "dev must record evidence"
assert validate_envelope(
    {"issue": 41, "station": "verifier", "status": "passed", "attempt": 1,
     "summary": "skipped — no app-url", "evidence": {"skipped": True}}, led, CONFIG
) == [], "an orchestrator-authored skip must pass the evidence gate"
assert any("invalid status" in e for e in validate_envelope(envelope("researcher", "blocked"), led, CONFIG)), \
    "there is no `blocked` status — a station may not invent a fourth human gate"
assert any("bounce.to and bounce.reason" in e for e in
           validate_envelope(envelope("dev", "bounce", bounce={"to": "sdet"}), led, CONFIG))
ok("envelope contract: required fields, evidence gate + skip exemption, 3-status vocabulary")


# --- 8. globs do not let `*` cross a `/` ------------------------------------

assert glob_match("docs/a.md", "docs/*") and not glob_match("docs/a/b.md", "docs/*")
assert glob_match("app/Http/Middleware/Auth.php", "**/{auth,authz,middleware}/**")
assert glob_match("db/migrations/001.sql", "**/migrations/**")
assert glob_match("migrations/001.sql", "**/migrations/**"), "**/ must also match at the root"
assert glob_match("package-lock.json", "*-lock.*") and not glob_match("web/package-lock.json", "*-lock.*")
assert glob_match("src/Permission.ts", "**/*permission*"), "case-insensitive: Laravel Middleware, Next middleware"
ok("glob matching is path-aware: * stops at /, ** does not, braces and classes work")


# --- 9. classifier: a missing graph scores WIDE, not low ---------------------
# If an absent upstream_depth silently scored d1, every PR on a repo without a
# gitnexus index would land `low` and the specialist panel would never fire.

files = ["database/migrations/2026_add_x.php", "app/Http/Middleware/CheckPermission.php"]
known = classify(files, {"upstream_depth": 0, "loc_changed": 50}, CONFIG)
unknown = classify(files, {"loc_changed": 50}, CONFIG)
assert known["blast_radius"] == "d1" and unknown["blast_radius"] == "unknown"
assert unknown["risk_score"] > known["risk_score"], "unknown must not score cheaper than d1"
assert set(unknown["signals"]) == {"auth", "migration", "backend"}, unknown["signals"]
assert classify(["README.md", "docs/x.md"], {}, CONFIG)["ticket_type"] == "docs"
assert classify(["src/a.ts"], {"labels": ["bug"]}, CONFIG)["ticket_type"] == "bugfix"
ok("classifier: signals by path, doc/bugfix typing, unknown blast radius scores wide")


# --- 10. review policy: ordered, deduped, minimum, never the generalist -----

policy = CONFIG["review_policy"]
assert resolve_review_panel({"signals": [], "risk_band": "low"}, policy) == [], "low + no signals = generalist only"
assert resolve_review_panel({"signals": ["auth"], "risk_band": "low"}, policy) == ["security"]
assert resolve_review_panel({"signals": ["auth", "dependency"], "risk_band": "high"}, policy) == [
    "security", "performance"
], "a specialist fired twice appears once, in policy order"
assert policy["generalist"] not in resolve_review_panel(
    {"signals": ["auth", "api-contract"], "risk_band": "high"}, policy
)
ok("review policy: ordered, deduplicated, minimum, generalist never selected")


# --- 11. an envelope wrapped in prose or a fence still parses ----------------
# The agents are LLMs told to return "one JSON object and nothing else". When one adds a
# fence or a preamble anyway, that is a packaging slip, not a contract breach — the shape
# gate still runs. Failing here would re-dispatch a station that did its work correctly.

sys.path.insert(0, HERE)
from shared import extract_json_object  # noqa: E402

body = '{"issue": 1, "station": "dev", "status": "passed"}'
for label, raw in [
    ("bare", body),
    ("fenced", "```json\n" + body + "\n```"),
    ("preamble", "Here is the envelope:\n\n" + body),
    ("both", "Done.\n```json\n" + body + "\n```\nHope that helps."),
    ("brace in a string", '{"summary": "used {curly} braces", "station": "dev"}'),
]:
    got = extract_json_object(raw)
    assert isinstance(got, dict) and got.get("station") == "dev", f"{label}: {got!r}"
assert extract_json_object("no json here at all") is None
assert extract_json_object("{not: valid}") is None
ok("envelope reader recovers a fenced/prose-wrapped object, rejects genuine garbage")



# --- 9. station post-checks -------------------------------------------------
# No stubbing and no network: every case below is refuted by something local — a file
# that is not on disk, a branch with no upstream.

def post_check_repo(tmp):
    """A git repo + an initialised run dir, baton parked on sdet."""
    repo, run_dir = os.path.join(tmp, "repo"), os.path.join(tmp, "run")
    os.makedirs(os.path.join(repo, "tests"))
    def git(*a):
        subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
    git("init", "-q", "-b", "base")
    git("config", "user.email", "a@b"); git("config", "user.name", "a")
    open(os.path.join(repo, "tests", "a.test.js"), "w").write("x\n")
    git("add", "-A"); git("commit", "-qm", "init")
    subprocess.run([sys.executable, ROUTE, "init", run_dir, "--issue", "41", "--repo", repo],
                   check=True, capture_output=True)
    subprocess.run([sys.executable, ROUTE, "set", run_dir, "test_root=tests"],
                   check=True, capture_output=True)
    return repo, run_dir


def route_it(run_dir, repo, name, env):
    json.dump(env, open(os.path.join(run_dir, name), "w"))
    return subprocess.run([sys.executable, ROUTE, "route", run_dir, name, "--repo", repo],
                          capture_output=True, text=True)


SDET_ENV = {
    "issue": 41, "station": "sdet", "status": "passed", "attempt": 1,
    "summary": "6 RED tests authored",
    "evidence": {"commands": [{"cmd": "pytest", "exit": 1, "excerpt": "6 failed"}]},
    "handoff": {"test_files": ["tests/does-not-exist.js"], "red_confirmed": True},
}

with tempfile.TemporaryDirectory() as tmp:
    repo, run_dir = post_check_repo(tmp)

    proc = route_it(run_dir, repo, "20-tests.json", SDET_ENV)
    assert proc.returncode == 7, f"expected exit 7, got {proc.returncode}: {proc.stderr}"
    assert proc.stdout.strip() == "bounce(sdet)", proc.stdout
    assert "does not exist on disk" in proc.stderr, proc.stderr
    led = json.load(open(os.path.join(run_dir, "run.json")))
    assert led["bounceCounts"] == {"sdet->sdet": 1}, led["bounceCounts"]
    ok("a passed envelope refuted by its own post-check self-bounces (exit 7)")

    # cap is 1, so the second failure ADVANCES and is reported at the final gate rather
    # than halting — the same doctrine as every other spent budget in this pipeline.
    proc = route_it(run_dir, repo, "20-tests.json", SDET_ENV)
    assert proc.returncode == 0, f"expected advance, got {proc.returncode}: {proc.stderr}"
    assert proc.stdout.strip() == "advance(dev)", proc.stdout
    led = json.load(open(os.path.join(run_dir, "run.json")))
    assert led["bounceCounts"] == {"sdet->sdet": 1}, "a spent check budget must not keep counting"
    failures = led["context"]["check_failures"]
    assert len(failures) == 1 and failures[0]["station"] == "sdet", failures
    ok("check_bounce_cap exhausted -> advance with check_failures recorded, never a halt")

    # and the self-bounce never spent a REAL budget: dev->sdet is untouched, so a genuine
    # dispute later still has its full allowance.
    assert "dev->sdet" not in led["bounceCounts"]
    ok("a self-bounce cannot spend a real (from, to) bounce budget")

with tempfile.TemporaryDirectory() as tmp:
    repo, run_dir = post_check_repo(tmp)
    subprocess.run([sys.executable, ROUTE, "set", run_dir, "pr_number=88"],
                   check=True, capture_output=True)
    # fixer's branch has no upstream, so the push check cannot run at all. fixer is in
    # FATAL_WHEN_UNRUNNABLE: a check that cannot run IS the finding there.
    fix = {"issue": 41, "station": "fixer", "status": "passed", "attempt": 1,
           "summary": "3 findings applied",
           "evidence": {"commands": [{"cmd": "pytest", "exit": 0, "excerpt": "ok"}]},
           "handoff": {"commits": [], "report": "x"}}
    proc = route_it(run_dir, repo, "60-fix.json", fix)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("escalate:"), proc.stdout
    assert "post-check could not run" in proc.stdout, proc.stdout
    ok("an unrunnable post-check escalates for fixer/reviewer, where it is the finding")

with tempfile.TemporaryDirectory() as tmp:
    repo, run_dir = post_check_repo(tmp)
    # both-mode dispatch: backend PASS, frontend FAIL. The rollup must be FAIL (worst
    # wins) even though the backend block is individually fine — a check that only
    # looked at handoff.verdict would miss a mode-level failure hiding under a green
    # top-level claim.
    both_env = {
        "issue": 41, "station": "verifier", "status": "bounce", "attempt": 1,
        "summary": "backend ok, frontend fails",
        "verdict": "FAIL",
        "modes": {
            "backend": {"verdict": "PASS", "criteria": [{"criterion": "200 on GET /x", "met": True}]},
            "frontend": {"verdict": "FAIL", "criteria": [{"criterion": "empty state renders", "met": False}]},
        },
        "evidence": {"commands": [{"cmd": "curl /x", "exit": 0, "excerpt": "200 ok"}]},
        "handoff": {"verdict": "fail", "criteria": [], "report": "x"},
        "bounce": {"to": "dev", "reason": "frontend empty state",
                   "findings": [{"mode": "frontend", "where": "OrderList", "observed": "crash",
                                 "expected": "empty message"}]},
    }
    proc = route_it(run_dir, repo, "40-verify.json", both_env)
    assert proc.returncode == 0 and proc.stdout.strip() == "bounce(dev)", \
        f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    ok("verifier rollup: one FAILing mode bounces even though the other mode passed")

    # the rollup claim has to match the worst mode's verdict — a station cannot say
    # PASS overall while a mode block says FAIL.
    lying_env = dict(both_env, status="passed", verdict="PASS")
    proc = route_it(run_dir, repo, "40-verify.json", lying_env)
    assert proc.returncode == 7, f"expected exit 7, got {proc.returncode}: {proc.stderr}"
    assert "does not match worst-of-modes" in proc.stderr, proc.stderr
    ok("verifier rollup lying about a FAILing mode self-bounces")

with tempfile.TemporaryDirectory() as tmp:
    repo, run_dir = post_check_repo(tmp)
    # a mode claiming PASS with no criteria[] is refuted per mode, same rule as the
    # flat envelope always enforced — just scoped to the one mode that lied. Fresh
    # repo/run_dir: the verifier->verifier check-bounce cap (1) must not already be
    # spent from an earlier case.
    empty_criteria_env = {
        "issue": 41, "station": "verifier", "status": "passed", "attempt": 1,
        "summary": "backend claims pass with nothing checked",
        "verdict": "PASS",
        "modes": {"backend": {"verdict": "PASS", "criteria": []}},
        "evidence": {"commands": [{"cmd": "curl /x", "exit": 0, "excerpt": "200 ok"}]},
        "handoff": {"verdict": "pass", "criteria": [], "report": "x"},
    }
    proc = route_it(run_dir, repo, "40-verify.json", empty_criteria_env)
    assert proc.returncode == 7, f"expected exit 7, got {proc.returncode}: {proc.stderr}"
    assert "modes.backend" in proc.stderr and "nothing was actually checked" in proc.stderr, proc.stderr
    ok("verifier mode claiming pass with empty criteria[] is refuted")

with tempfile.TemporaryDirectory() as tmp:
    repo, run_dir = post_check_repo(tmp)
    # researcher has no post-check, so it routes exactly as it always did.
    res = {"issue": 41, "station": "researcher", "status": "passed", "attempt": 1,
           "summary": "brief written", "handoff": {"brief": "..."}}
    proc = route_it(run_dir, repo, "00-readiness.json", res)
    assert proc.returncode == 0 and proc.stdout.strip() == "advance(planner)", \
        f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    led = json.load(open(os.path.join(run_dir, "run.json")))
    assert "check_failures" not in led["context"] and "check_notes" not in led["context"]
    ok("a station with no post-check routes exactly as it does today")


# --- 12. exit-6 recovery: git-show fallback for hook-blocked checkout/restore ----
# Issue #26: `git checkout <sdet_sha> -- <paths>` can be blocked by a repo's git safety
# hooks. The exit-6 bullet needs a fallback (`git show <sha>:<path> > /tmp/<file>` + a
# plain write) and route.py's exit-6 stderr should mirror it.

RUN_ISSUE_MD = os.path.join(HERE, "..", "commands", "run-issue.md")


def _exit6_bullet():
    """Slice the exit-6 recovery bullet out of the live markdown file. Raises loudly
    if the bullet cannot be found, rather than silently matching an empty string."""
    text = open(RUN_ISSUE_MD).read()
    start_marker = "**exit 6 — test-ownership violation.**"
    start = text.index(start_marker)  # raises ValueError if the bullet is gone/reflowed
    # bullet ends at the next top-level list item ("   - **" at the same indent)
    end = text.index("\n   - **", start)
    bullet = text[start:end]
    assert bullet.strip(), "exit-6 bullet matched but is empty — bad slice"
    return bullet


bullet = _exit6_bullet()
assert "git show" in bullet, "fallback for hook-blocked git checkout/restore is missing"
import re as _re
assert _re.search(r"<sdet_sha>\s*:", bullet) or _re.search(r"<[a-zA-Z_]*sha>\s*:", bullet), \
    "fallback must reference a sha:path pattern (e.g. <sdet_sha>:<path>)"
assert "/tmp/" in bullet, "fallback must write to a /tmp/ destination"
ok("exit-6 bullet documents a git-show + /tmp fallback for hook-blocked checkout")

checkout_idx = bullet.index("git checkout")
show_idx = bullet.index("git show")
assert checkout_idx < show_idx, "primary `git checkout` instruction must precede the fallback"
ok("primary git-checkout instruction still appears, and precedes the git-show fallback")

normalized_bullet = " ".join(bullet.split())
assert normalized_bullet.rstrip(".").endswith(
    "Never re-dispatch `run-dev` with tampered tests still on disk"
), "the invariant sentence must remain the LAST sentence of the exit-6 bullet"
ok("the 'never re-dispatch run-dev with tampered tests' invariant survives as the last sentence")

assert ("stderr" in bullet), "fallback must reference stderr / paths from stderr"
for wildcard in ["-- .", "--all", " -- *", "-- *"]:
    assert wildcard not in bullet, f"fallback must not use a blanket wildcard ({wildcard!r})"
assert bullet.count("*") == 0, "fallback must not use a bare wildcard"
ok("fallback is scoped to paths from stderr, no blanket wildcard")

full_md = open(RUN_ISSUE_MD).read()
assert full_md.count("git show") == 1, "the git-show fallback text must appear exactly once in run-issue.md"
ok("git-show fallback text appears exactly once in commands/run-issue.md")


# --- 13. exit-6 recovery: unchanged collateral (snapshot before dev edits) -------
# Guards against the doc fix accidentally rewriting sibling bullets or the
# "### Test ownership" section while adding the fallback.

def _normalize(s):
    return " ".join(s.split())


bounce_sdet_bullet_start = full_md.index("**`bounce(sdet)`** — dev disputes a test.")
advance_bullet_start = full_md.index("**`advance(…)`** — green.")
escalate_bullet_start = full_md.index("**`escalate`** — the dev budget is spent.")
test_ownership_start = full_md.index("### Test ownership")
test_ownership_end = full_md.index("### State", test_ownership_start)

EXPECTED_BOUNCE_SDET = _normalize("""
**`bounce(sdet)`** — dev disputes a test. Dispatch `run-sdet` with the findings; it
     amends or rejects and commits. Move `sdet_sha` forward, then re-dispatch `run-dev`.
""")
EXPECTED_ADVANCE = _normalize("""
**`advance(…)`** — green. Continue.
""")
EXPECTED_ESCALATE_PREFIX = _normalize(
    "**`escalate`** — the dev budget is spent. Record"
)
EXPECTED_TEST_OWNERSHIP = _normalize(full_md[test_ownership_start:test_ownership_end])

assert _normalize(full_md[bounce_sdet_bullet_start:advance_bullet_start]) == EXPECTED_BOUNCE_SDET, \
    "the bounce(sdet) bullet must be unchanged by the exit-6 doc fix"
assert _normalize(full_md[advance_bullet_start:escalate_bullet_start]) == EXPECTED_ADVANCE, \
    "the advance(...) bullet must be unchanged by the exit-6 doc fix"
assert _normalize(full_md[escalate_bullet_start:]).startswith(EXPECTED_ESCALATE_PREFIX), \
    "the escalate bullet must be unchanged by the exit-6 doc fix"
assert EXPECTED_TEST_OWNERSHIP == _normalize(full_md[test_ownership_start:test_ownership_end]), \
    "the ### Test ownership section must be unchanged by the exit-6 doc fix"
ok("bounce(sdet)/advance/escalate bullets and ### Test ownership section are unchanged")


# --- 14. exit-6 stderr mirrors the git-show fallback -----------------------------
# Extends the existing exit-6 subprocess scenario (section 6 above) to assert route.py's
# stderr also carries the fallback instruction, and that exit-6 routing itself still
# behaves exactly as it does today (regression guard).

with tempfile.TemporaryDirectory() as tmp:
    repo, run_dir = os.path.join(tmp, "repo"), os.path.join(tmp, "run")
    os.makedirs(os.path.join(repo, "tests"))
    git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t"); git("config", "user.name", "t")
    open(os.path.join(repo, "tests", "a.test.js"), "w").write("expect(1).toBe(2)\n")
    git("add", "-A"); git("commit", "-qm", "sdet: red tests")
    sdet_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    open(os.path.join(repo, "tests", "a.test.js"), "w").write("expect(1).toBe(1)\n")
    git("add", "-A"); git("commit", "-qm", "dev: implement")

    subprocess.run(
        [sys.executable, ROUTE, "init", run_dir, "--issue", "41", "--repo", repo],
        check=True, capture_output=True,
    )
    subprocess.run(
        [sys.executable, ROUTE, "set", run_dir, f"sdet_sha={sdet_sha}", "test_root=tests"],
        check=True, capture_output=True,
    )
    json.dump(envelope("dev"), open(os.path.join(run_dir, "30-build.json"), "w"))
    proc = subprocess.run(
        [sys.executable, ROUTE, "route", run_dir, "30-build.json", "--repo", repo],
        capture_output=True, text=True,
    )
    assert proc.returncode == 6, f"expected exit 6, got {proc.returncode}: {proc.stdout}{proc.stderr}"
    assert proc.stdout.strip() == "bounce(sdet)", proc.stdout
    led = json.load(open(os.path.join(run_dir, "run.json")))
    assert led["bounceCounts"].get("dev->sdet") == 1, led["bounceCounts"]
    assert "tests/a.test.js" in proc.stderr, proc.stderr
    assert f"git checkout {sdet_sha}" in proc.stderr, proc.stderr
    assert "git show" in proc.stderr, "exit-6 stderr must mirror the git-show fallback"
    ok("aiw route's exit-6 stderr mirrors the git-show fallback; exit-6 routing regression holds")


print(f"\n{passed} checks passed")
