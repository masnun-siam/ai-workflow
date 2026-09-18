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
assert set(unknown["signals"]) == {"auth", "migration"}, unknown["signals"]
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
from route import extract_json_object  # noqa: E402

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


print(f"\n{passed} checks passed")
