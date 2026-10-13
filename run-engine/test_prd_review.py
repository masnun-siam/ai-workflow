#!/usr/bin/env python3
"""Self-check for `aiw prd-review` (PRD peer review). `python3 run-engine/test_prd_review.py` — exit 0 = green."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
AIW = os.path.join(os.path.dirname(HERE), "bin", "aiw")
sys.path.insert(0, HERE)

import prd_review as pr  # noqa: E402

PRD = """# PRD — Export

## Requirements
- **FR-1** Admins can **export** the bookings table as CSV.
  - Acceptance: a download starts within 5 seconds.

## Edge cases
None.
"""
LENSES = {
    "critical": {"blocking": True},
    "ceo": {"blocking": False},
    "cto": {"blocking": False},
    "security": {"blocking": False},
}


def finding(
    fid="f1", severity="major", quote="Admins can export the bookings table as CSV.", section="", decision=False
):
    return {
        "id": fid,
        "severity": severity,
        "section": section,
        "quote": quote,
        "problem": "p",
        "fix": "x",
        "needs_decision": decision,
    }


def verdict(lens, findings=(), status="changes", rnd=1, sha=None):
    return {
        "lens": lens,
        "round": rnd,
        "prd_sha256": sha or pr.sha(PRD),
        "verdict": status,
        "findings": list(findings),
    }


def ok(label):
    print("  ok ", label)


REQ = {"round": 1, "prd_sha256": pr.sha(PRD)}

# --- verdict validation: the quote must be in the PRD (whitespace and emphasis ignored), or the section a real heading
assert pr.validate(verdict("critical", [finding()]), PRD, REQ, LENSES) == []
assert (
    pr.validate(verdict("critical", [finding(quote="Admins can **export**   the bookings table")]), PRD, REQ, LENSES)
    == []
)
assert pr.validate(verdict("critical", [finding(quote="", section="Edge cases")]), PRD, REQ, LENSES) == []
errs = pr.validate(verdict("critical", [finding(quote="Users can delete bookings")]), PRD, REQ, LENSES)
assert any("quote" in e for e in errs), errs
errs = pr.validate(verdict("critical", [finding(quote="", section="Rollout")]), PRD, REQ, LENSES)
assert any("heading" in e for e in errs), errs
errs = pr.validate(verdict("critical", [finding(quote="", section="")]), PRD, REQ, LENSES)
assert errs, "a finding with neither quote nor heading is rejected"
ok("validate: quote must be in the PRD (normalised) or section a real heading")

errs = pr.validate(verdict("critical", [finding()], sha="0" * 64), PRD, REQ, LENSES)
assert any("stale" in e for e in errs), errs
assert any("round" in e for e in pr.validate(verdict("critical", rnd=2), PRD, REQ, LENSES))
assert any("lens" in e for e in pr.validate(verdict("marketing"), PRD, REQ, LENSES))
assert any("8" in e for e in pr.validate(verdict("ceo", [finding(f"f{i}") for i in range(9)]), PRD, REQ, LENSES))
assert any("severity" in e for e in pr.validate(verdict("ceo", [finding(severity="huge")]), PRD, REQ, LENSES))
assert any("approve" in e for e in pr.validate(verdict("critical", [finding()], "approve"), PRD, REQ, LENSES))
assert pr.validate(verdict("critical", [finding(severity="minor")], "approve"), PRD, REQ, LENSES) == []
ok("validate: stale hash, wrong round, unknown lens, >8 findings, bad severity, approve-with-major all rejected")


# --- decide: only the blocking lens blocks; decisions go to the user; the cap hands over, never auto-approves
def panel(**over):
    v = {lens: verdict(lens, status="approve") for lens in LENSES}
    v.update(over)
    return v


d = pr.decide(panel(), LENSES, rnd=1, max_rounds=3)
assert d["action"] == "done", d
d = pr.decide(panel(critical=verdict("critical", [finding()])), LENSES, rnd=1, max_rounds=3)
assert d["action"] == "revise" and [f["id"] for f in d["blockers"]] == ["f1"], d
d = pr.decide(panel(critical=verdict("critical", [finding(severity="minor")], "approve")), LENSES, rnd=1, max_rounds=3)
assert d["action"] == "done", "a minor from the blocking lens does not block"
d = pr.decide(panel(critical=verdict("critical", [finding()])), LENSES, rnd=3, max_rounds=3)
assert d["action"] == "ask" and d["reason"] == "cap", d
d = pr.decide(panel(ceo=verdict("ceo", [finding(decision=True)])), LENSES, rnd=1, max_rounds=3)
assert d["action"] == "ask" and d["reason"] == "decision" and len(d["decisions"]) == 1, d
d = pr.decide(panel(cto=verdict("cto", [finding("c1", "blocker")])), LENSES, rnd=1, max_rounds=3)
assert d["action"] == "done", "an advisory lens never blocks"
assert [f["id"] for f in d["advisory_blockers"]] == ["c1"] and d["advisory_blockers"][0]["lens"] == "cto", d
d = pr.decide(panel(security=verdict("security", [finding("s1", "minor")])), LENSES, rnd=1, max_rounds=3)
assert [f["id"] for f in d["advisory"]] == ["s1"] and d["advisory_blockers"] == [], d
try:
    pr.decide({"critical": verdict("critical")}, LENSES, rnd=1, max_rounds=3)
    raise AssertionError("missing verdicts must raise")
except ValueError as exc:
    assert "ceo" in str(exc)
ok("decide: done / revise / ask-cap / ask-decision; advisory blockers surfaced, never blocking; missing verdicts raise")


# --- CLI: open round 1, reject a bad verdict, decide, refuse an unchanged PRD, open round 2, cap and --more
def aiw(*argv):
    p = subprocess.run([AIW, *argv], capture_output=True, text=True)
    return p.returncode, (json.loads(p.stdout) if p.stdout.strip().startswith("{") else p.stdout), p.stderr


with tempfile.TemporaryDirectory() as tmp:
    prd = os.path.join(tmp, "prd.md")
    with open(prd, "w", encoding="utf-8") as fh:
        fh.write(PRD)
    rd = os.path.join(tmp, "review")
    rc, out, err = aiw("prd-review", "next", rd, "--prd", prd)
    assert rc == 0 and out["action"] == "review" and out["round"] == 1, (out, err)
    lenses = out["lenses"]
    assert "critical" in lenses and "ceo" in lenses and "cto" in lenses and "security" in lenses, lenses
    rc, out, _ = aiw("prd-review", "next", rd, "--prd", prd)
    assert rc == 0 and out["action"] == "wait" and set(out["missing"]) == set(lenses), out

    def put(lens, v):
        path = os.path.join(tmp, f"{lens}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(v, fh)
        return aiw("prd-review", "verdict", rd, "--lens", lens, "--file", path)

    rc, _, err = put("critical", verdict("critical", [finding(quote="not in the prd")]))
    assert rc == 5 and "quote" in err, err
    assert put("critical", verdict("critical", [finding()]))[0] == 0
    for lens in lenses:
        if lens != "critical":
            assert put(lens, verdict(lens, status="approve"))[0] == 0
    rc, out, _ = aiw("prd-review", "next", rd, "--prd", prd)
    assert rc == 0 and out["action"] == "revise", out
    rc, out, _ = aiw("prd-review", "next", rd, "--prd", prd)
    assert out["action"] == "revise", "an unchanged PRD gets the same decision, never a new round"

    with open(prd, "a", encoding="utf-8") as fh:
        fh.write("\n- **FR-2** Exports over 10,000 rows are refused with a message.\n")
    prior = os.path.join(tmp, "prior.json")
    with open(prior, "w", encoding="utf-8") as fh:
        json.dump([{"id": "f1", "disposition": "fixed", "reason": "added FR-2"}], fh)
    rc, out, err = aiw("prd-review", "next", rd, "--prd", prd, "--prior", prior)
    assert rc == 0 and out["action"] == "review" and out["round"] == 2, (out, err)
    req2 = json.load(open(os.path.join(rd, "round-2", "request.json")))
    assert req2["prior"][0]["disposition"] == "fixed" and req2["prd_sha256"] != pr.sha(PRD), req2
    rc, _, err = put("ceo", verdict("ceo", status="approve", rnd=1))
    assert rc == 5 and "round" in err, "a verdict for an old round is refused"
ok("CLI: round 1 opens, bad quote refused, revise, unchanged PRD repeats the decision, edit + prior opens round 2")

with tempfile.TemporaryDirectory() as tmp:
    prd = os.path.join(tmp, "prd.md")
    rd = os.path.join(tmp, "review")
    text = PRD
    for rnd in (1, 2, 3):
        with open(prd, "w", encoding="utf-8") as fh:
            fh.write(text)
        rc, out, err = aiw("prd-review", "next", rd, "--prd", prd, "--max-rounds", "3")
        assert out["action"] == "review" and out["round"] == rnd, (rnd, out, err)
        for lens in out["lenses"]:
            v = verdict(lens, [finding()] if lens == "critical" else [], "changes" if lens == "critical" else "approve")
            v["round"], v["prd_sha256"] = rnd, pr.sha(text)
            path = os.path.join(tmp, "v.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(v, fh)
            assert aiw("prd-review", "verdict", rd, "--lens", lens, "--file", path)[0] == 0
        text += f"\n<!-- edit {rnd} -->\n"
    rc, out, _ = aiw("prd-review", "next", rd, "--prd", prd)
    assert out["action"] == "ask" and out["reason"] == "cap", out
    with open(prd, "w", encoding="utf-8") as fh:
        fh.write(text)
    rc, out, _ = aiw("prd-review", "next", rd, "--prd", prd)
    assert out["action"] == "ask" and out["reason"] == "cap", "past the cap, an edit alone opens no round"
    rc, out, _ = aiw("prd-review", "next", rd, "--prd", prd, "--more")
    assert out["action"] == "review" and out["round"] == 4, out
ok("CLI: the cap hands over (ask), an edit alone cannot pass it, --more opens exactly one more round")

print("test_prd_review: ok")
