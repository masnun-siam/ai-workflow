#!/usr/bin/env python3
"""Self-check for `aiw peer-review`. `python3 run-engine/test_peer_review.py` — exit 0 = green."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
AIW = os.path.join(os.path.dirname(HERE), "bin", "aiw")
sys.path.insert(0, HERE)

import peer_review as pr  # noqa: E402
from shared import load_config  # noqa: E402

PRD = """# PRD — Export

## Requirements
- **FR-1** Admins can **export** the bookings table as CSV.
  - Acceptance: a download starts within 5 seconds.

## Edge cases
None.
"""
LENSES = ["critical", "ceo", "cto", "security"]
QUOTE = "Admins can export the bookings table as CSV."


def finding(fid="f1", severity="major", quote=QUOTE, section="", decision=False, reraises=None, **extra):
    f = {
        "id": fid,
        "severity": severity,
        "section": section,
        "quote": quote,
        "problem": "p",
        "fix": "x",
        "needs_decision": decision,
        **extra,
    }
    if severity != "minor":
        f["reraises"] = reraises
    return f


def verdict(lens, findings=(), status="changes", rnd=1, sha=None):
    return {
        "lens": lens,
        "round": rnd,
        "artifact_sha256": sha or pr.sha(PRD),
        "verdict": status,
        "findings": list(findings),
    }


def ok(label):
    print("  ok ", label)


REQ = {"round": 1, "artifact_sha256": pr.sha(PRD), "lenses": LENSES, "prior": []}

# --- verdict validation: the quote must be in the artifact (whitespace and emphasis ignored), or the section a heading
assert pr.validate(verdict("critical", [finding()]), PRD, REQ) == []
assert pr.validate(verdict("critical", [finding(quote="Admins can **export**   the bookings table")]), PRD, REQ) == []
assert pr.validate(verdict("critical", [finding(quote="", section="Edge cases")]), PRD, REQ) == []
errs = pr.validate(verdict("critical", [finding(quote="Users can delete bookings")]), PRD, REQ)
assert any("quote" in e for e in errs), errs
errs = pr.validate(verdict("critical", [finding(quote="", section="Rollout")]), PRD, REQ)
assert any("heading" in e for e in errs), errs
errs = pr.validate(verdict("critical", [finding(quote="", section="")]), PRD, REQ)
assert errs, "a finding with neither quote nor heading is rejected"
errs = pr.validate(verdict("critical", [finding(quote="the")]), PRD, REQ)
assert any("4 words" in e for e in errs), "a one-word quote proves nothing"
assert pr.validate(verdict("critical", [finding(quote="the bookings table as")]), PRD, REQ) == []
ok("validate: quote must be in the artifact (normalised) or section a real heading")

errs = pr.validate(verdict("critical", [finding()], sha="0" * 64), PRD, REQ)
assert any("stale" in e for e in errs), errs
assert any("round" in e for e in pr.validate(verdict("critical", rnd=2), PRD, REQ))
assert any("lens" in e for e in pr.validate(verdict("marketing"), PRD, REQ))
assert any("lens" in e for e in pr.validate(verdict("qa"), PRD, REQ)), "a lens not on this run's panel is refused"
assert any("8" in e for e in pr.validate(verdict("ceo", [finding(f"f{i}") for i in range(9)]), PRD, REQ))
assert any("severity" in e for e in pr.validate(verdict("ceo", [finding(severity="huge")]), PRD, REQ))
assert any("approve" in e for e in pr.validate(verdict("critical", [finding()], "approve"), PRD, REQ))
assert pr.validate(verdict("critical", [finding(severity="minor")], "approve"), PRD, REQ) == []
ok("validate: stale hash, wrong round, lens off the panel, >8 findings, bad severity, approve-with-major rejected")

# --- re-raises: explicit on every blocker/major, never guessed by the engine
no_key = finding()
del no_key["reraises"]
assert any("reraises" in e for e in pr.validate(verdict("critical", [no_key]), PRD, REQ)), "missing key refused"
assert pr.validate(verdict("critical", [finding(severity="minor")]), PRD, REQ) == [], "a minor needs no reraises"
PRIOR = [
    {"lens": "critical", "id": "c1", "disposition": "dismissed", "reason": "out of scope", "quote": QUOTE},
    {"lens": "critical", "id": "c2", "disposition": "fixed", "reason": "edited", "quote": ""},
    {"lens": "cto", "id": "t1", "disposition": "dismissed", "reason": "no", "quote": QUOTE},
]
REQ2 = {**REQ, "round": 2, "prior": PRIOR}
assert pr.validate(verdict("critical", [finding("n1", reraises="c1")], rnd=2), PRD, REQ2) == []
errs = pr.validate(verdict("critical", [finding("n1", reraises="zz")], rnd=2), PRD, REQ2)
assert any("not one of your findings" in e for e in errs), errs
errs = pr.validate(verdict("critical", [finding("n1", reraises="t1")], rnd=2), PRD, REQ2)
assert any("not one of your findings" in e for e in errs), "a lens cannot re-raise another lens's finding"
errs = pr.validate(verdict("critical", [finding("n1")], rnd=2), PRD, REQ2)
assert any("same quote as dismissed c1" in e for e in errs), "same quote as a dismissed finding, null, no reason"
assert pr.validate(verdict("critical", [finding("n1", distinct_because="a different gap")], rnd=2), PRD, REQ2) == []
assert pr.validate(verdict("ceo", [finding("n1")], rnd=2), PRD, REQ2) == [], "another lens's dismissal is not mine"
DECIDED = [{"lens": "critical", "id": "d1", "disposition": "decided", "reason": "user: CSV only", "quote": QUOTE}]
REQ3 = {**REQ, "round": 2, "prior": DECIDED}
errs = pr.validate(verdict("critical", [finding("n1", reraises="d1")], rnd=2), PRD, REQ3)
assert any("the user decided d1" in e for e in errs), "a reviewer cannot re-block on the user's ruling"
ev = finding("n1", reraises="d1", new_evidence="Admins can export the bookings")
assert pr.validate(verdict("critical", [ev], rnd=2), PRD, REQ3) == [], "new evidence reopens it, as a dispute"
ok("validate: reraises required on blocker/major, names my own prior finding; same dismissed quote needs a reason")


# --- decide: every lens on the panel blocks; decisions and disputes go to the user; the cap hands over
def panel(**over):
    v = {lens: verdict(lens, status="approve") for lens in LENSES}
    v.update(over)
    return v


d = pr.decide(panel(), LENSES, rnd=1, max_rounds=3)
assert d["action"] == "done", d
d = pr.decide(panel(critical=verdict("critical", [finding()])), LENSES, rnd=1, max_rounds=3)
assert d["action"] == "revise" and [f["id"] for f in d["blockers"]] == ["f1"], d
d = pr.decide(panel(cto=verdict("cto", [finding("c1", "blocker")])), LENSES, rnd=1, max_rounds=3)
assert d["action"] == "revise" and d["blockers"][0]["lens"] == "cto", "every picked lens blocks"
d = pr.decide(panel(critical=verdict("critical", [finding(severity="minor")], "approve")), LENSES, rnd=1, max_rounds=3)
assert d["action"] == "done" and [f["id"] for f in d["advisory"]] == ["f1"], "a minor never blocks"
d = pr.decide(panel(critical=verdict("critical", [finding()])), LENSES, rnd=3, max_rounds=3)
assert d["action"] == "ask" and d["reason"] == "cap", d
d = pr.decide(panel(ceo=verdict("ceo", [finding(decision=True)])), LENSES, rnd=1, max_rounds=3)
assert d["action"] == "ask" and d["reason"] == "decision" and len(d["decisions"]) == 1, d
dis = panel(critical=verdict("critical", [finding("n1", reraises="c1")], rnd=2))
d = pr.decide(dis, LENSES, rnd=2, max_rounds=3, prior=PRIOR)
assert d["action"] == "ask" and d["reason"] == "dispute" and d["disputes"][0]["id"] == "n1" and not d["blockers"], d
d = pr.decide(dis, LENSES, rnd=3, max_rounds=3, prior=PRIOR)
assert d["reason"] == "dispute", "a dispute is the user's call even at the cap"
d = pr.decide(panel(critical=verdict("critical", [finding("n2", reraises="c2")], rnd=2)), LENSES, 2, 3, PRIOR)
assert d["action"] == "revise" and not d["disputes"], "re-raising a fixed finding (the fix didn't work) is a revise"
assert "advisory_blockers" not in d
d = pr.decide(panel(critical=verdict("critical", [ev], rnd=2)), LENSES, 2, 3, DECIDED)
assert d["action"] == "ask" and d["reason"] == "dispute" and not d["blockers"], "re-raised ruling goes back to the user"
try:
    pr.decide({"critical": verdict("critical")}, LENSES, rnd=1, max_rounds=3)
    raise AssertionError("missing verdicts must raise")
except ValueError as exc:
    assert "ceo" in str(exc)
ok("decide: every lens blocks; minor advisory; decision and dispute ask; fixed re-raise revises; cap; missing raise")


# --- CLI
def aiw(*argv, env=None, cwd=None):
    p = subprocess.run([AIW, *argv], capture_output=True, text=True, env=env, cwd=cwd)
    return p.returncode, (json.loads(p.stdout) if p.stdout.strip().startswith("{") else p.stdout), p.stderr


def write(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(data if isinstance(data, str) else json.dumps(data))
    return path


with tempfile.TemporaryDirectory() as tmp:
    env = {**os.environ, "CLAUDE_PLUGIN_DATA": tmp}
    rc, a, err = aiw("peer-review", "new", "prd", "--slug", "o/r export", env=env)
    rc2, b, _ = aiw("peer-review", "new", "prd", "--slug", "o/r export", env=env)
    a, b = a.strip(), b.strip()
    assert rc == 0 and a.startswith(os.path.join(tmp, "peer-review", "prd", "o-r-export-")) and os.path.isdir(a), a
    assert rc2 in (0, 1), "the same second can collide; a collision is refused, never reused"
    assert rc2 == 1 or b != a
    rc, out, _ = aiw("peer-review", "new", "custom", "--id", "sess-42", env=env)
    assert rc == 0 and out.strip() == os.path.join(tmp, "peer-review", "custom", "sess-42"), out
    rc, _, err = aiw("peer-review", "new", "custom", "--id", "sess-42", env=env)
    assert rc == 1 and "never reused" in err, err
    assert aiw("peer-review", "new", "custom", "--id", "../x", env=env)[0] == 2
    assert aiw("peer-review", "new", "nope", env=env)[0] == 2
ok("new: a fresh dir per run under <data_dir>/peer-review/<kind>/, never reused; ids are safe names")

with tempfile.TemporaryDirectory() as tmp:
    prd = write(os.path.join(tmp, "prd.md"), PRD)
    rd = os.path.join(tmp, "review")
    rc, _, err = aiw("peer-review", "next", rd, "--artifact", prd)
    assert rc == 2 and "--kind" in err, "round 1 needs the kind"
    rc, _, err = aiw("peer-review", "next", rd, "--artifact", prd, "--kind", "dump", "--lenses", "critical,cto")
    assert rc == 2 and "dump offers" in err and "cto" in err, "a lens the kind doesn't offer is refused"
    rc, out, err = aiw("peer-review", "next", rd, "--artifact", prd, "--kind", "prd")
    assert rc == 0 and out["action"] == "review" and out["lenses"] == ["critical"], (out, err)
    req = json.load(open(os.path.join(rd, "round-1", "request.json")))
    assert req["kind"] == "prd" and req["rubric"] == "doc" and req["lenses"] == ["critical"], req

with tempfile.TemporaryDirectory() as tmp:
    art = write(os.path.join(tmp, "a.md"), PRD)
    rc, out, _ = aiw("peer-review", "next", os.path.join(tmp, "r"), "--artifact", art, "--kind", "custom")
    assert json.load(open(os.path.join(tmp, "r", "round-1", "request.json")))["rubric"] == "change"
cfg = load_config(None)["peer_review"]
assert set(cfg["rubric"]) == {"doc", "change"} and "never adds implementation" in cfg["rubric"]["doc"]
assert "never adds implementation" not in cfg["rubric"]["change"] and "may change code" in cfg["rubric"]["change"]
for kind, spec in cfg["kinds"].items():
    assert spec["rubric"] in cfg["rubric"] and set(spec["offer"]) <= set(cfg["lenses"]), kind
assert (
    set(cfg["kinds"]["custom"]["offer"])
    == set(cfg["lenses"])
    == {
        "critical",
        "ceo",
        "cto",
        "security",
        "qa",
        "ux",
        "performance",
    }
)
assert not any("blocking" in lens for lens in cfg["lenses"].values()), "every picked lens blocks; no per-lens flag"
ok("next: round 1 needs --kind, refuses lenses the kind doesn't offer, records kind + rubric; custom gets change")

with tempfile.TemporaryDirectory() as tmp:
    prd = write(os.path.join(tmp, "prd.md"), PRD)
    rd = os.path.join(tmp, "review")
    rc, out, err = aiw("peer-review", "next", rd, "--artifact", prd, "--kind", "prd", "--lenses", "critical,ceo,cto")
    assert rc == 0 and out["lenses"] == ["critical", "ceo", "cto"], (out, err)
    rc, out, _ = aiw("peer-review", "next", rd, "--artifact", prd)
    assert rc == 0 and out["action"] == "wait" and out["missing"] == ["critical", "ceo", "cto"], out

    def put(lens, v):
        return aiw("peer-review", "verdict", rd, "--lens", lens, "--file", write(os.path.join(tmp, f"{lens}.json"), v))

    rc, _, err = put("critical", verdict("critical", [finding(quote="not in the prd at all")]))
    assert rc == 5 and "quote" in err, err
    p = subprocess.run(  # the reviewer records its own verdict from stdin; the author never transcribes it
        [AIW, "peer-review", "verdict", rd, "--lens", "critical", "--file", "-"],
        input=json.dumps(verdict("critical", [finding("c1")])),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0 and "critical changes" in p.stdout, p.stderr
    assert put("ceo", verdict("ceo", status="approve"))[0] == 0
    assert put("cto", verdict("cto", status="approve"))[0] == 0
    assert not os.path.exists(os.path.join(rd, "round-1", "decision.json")), "no decision before every verdict"
    rc, out, _ = aiw("peer-review", "next", rd, "--artifact", prd)
    assert rc == 0 and out["action"] == "revise", out
    assert json.load(open(os.path.join(rd, "round-1", "decision.json")))["action"] == "revise", "decision recorded"
    rc, out, _ = aiw("peer-review", "next", rd, "--artifact", prd)
    assert out["action"] == "revise", "an unchanged artifact gets the same decision, never a new round"

    with open(prd, "a", encoding="utf-8") as fh:
        fh.write("\n- **FR-2** Exports over 10,000 rows are refused with a message.\n")
    rc, _, err = aiw("peer-review", "next", rd, "--artifact", prd)
    assert rc == 2 and "--prior" in err, "round 1 had findings: opening round 2 needs their dispositions"
    prior = write(
        os.path.join(tmp, "prior.json"),
        [{"lens": "critical", "id": "c1", "disposition": "dismissed", "reason": "out of scope"}],
    )
    rc, out, err = aiw("peer-review", "next", rd, "--artifact", prd, "--prior", prior)
    assert rc == 0 and out["action"] == "review" and out["round"] == 2 and out["lenses"] == ["critical", "ceo", "cto"]
    req2 = json.load(open(os.path.join(rd, "round-2", "request.json")))
    assert req2["prior"][0]["quote"] == QUOTE and req2["kind"] == "prd", "the dismissed quote rides along"
    rc, _, err = put("ceo", verdict("ceo", status="approve", rnd=1))
    assert rc == 5 and "round" in err, "a verdict for an old round is refused"
    sha2 = req2["artifact_sha256"]
    rc, _, err = put("critical", verdict("critical", [finding("c9")], rnd=2, sha=sha2))
    assert rc == 5 and "same quote as dismissed c1" in err, err
    assert put("critical", verdict("critical", [finding("c9", reraises="c1")], rnd=2, sha=sha2))[0] == 0
    assert put("ceo", verdict("ceo", status="approve", rnd=2, sha=sha2))[0] == 0
    assert put("cto", verdict("cto", status="approve", rnd=2, sha=sha2))[0] == 0
    rc, out, _ = aiw("peer-review", "next", rd, "--artifact", prd)
    assert out["action"] == "ask" and out["reason"] == "dispute", out
    assert json.load(open(os.path.join(rd, "round-2", "decision.json")))["reason"] == "dispute"
ok("CLI: panel of 3, bad quote refused, revise + decision.json, prior opens round 2, silent re-raise refused, dispute")

with tempfile.TemporaryDirectory() as tmp:
    env = {**os.environ, "CLAUDE_PLUGIN_DATA": tmp}
    prd = write(os.path.join(tmp, "prd.md"), PRD)
    first = aiw("peer-review", "new", "prd", "--slug", "export", env=env)[1].strip()
    aiw("peer-review", "next", first, "--artifact", prd, "--kind", "prd", env=env)
    os.makedirs(os.path.join(first, "round-3"))
    write(os.path.join(first, "round-3", "request.json"), {"stale": True})  # an old run that went to the cap
    time.sleep(1.1)  # the stamp has 1s resolution
    second = aiw("peer-review", "new", "prd", "--slug", "export", env=env)[1].strip()
    rc, out, err = aiw("peer-review", "next", second, "--artifact", prd, "--kind", "prd", env=env)
    assert second != first and rc == 0 and out["action"] == "review" and out["round"] == 1, (out, err)
ok("a second run on the same slug starts at round 1 (the old fixed-per-slug dir inherited stale rounds)")

assert (
    pr.check_prior([{"lens": "critical", "id": "f1", "disposition": "fixed", "reason": "r"}], {("critical", "f1")})
    == []
)
both = {("critical", "f1"), ("cto", "f1")}
assert any(
    "cto" in e for e in pr.check_prior([{"lens": "critical", "id": "f1", "disposition": "fixed", "reason": "r"}], both)
), "the same id in two lenses needs two dispositions"
assert pr.check_prior([{"lens": "critical", "id": "f1", "disposition": "maybe", "reason": "r"}], {("critical", "f1")})
assert pr.check_prior(
    [{"lens": "critical", "id": "f1", "disposition": "dismissed", "reason": ""}], {("critical", "f1")}
)
assert pr.check_prior({"id": "f1"}, {("critical", "f1")})
ok("check_prior: every prior finding needs {lens, id, disposition fixed|dismissed|decided, reason}")

with tempfile.TemporaryDirectory() as tmp:
    prd = os.path.join(tmp, "prd.md")
    rd = os.path.join(tmp, "review")
    text = PRD
    pri = write(
        os.path.join(tmp, "prior.json"), [{"lens": "critical", "id": "f1", "disposition": "fixed", "reason": "edited"}]
    )
    for rnd in (1, 2, 3):
        write(prd, text)
        rc, out, err = aiw(
            "peer-review", "next", rd, "--artifact", prd, "--kind", "prd", "--max-rounds", "3", "--prior", pri
        )
        assert out["action"] == "review" and out["round"] == rnd, (rnd, out, err)
        v = verdict("critical", [finding(reraises="f1" if rnd > 1 else None)])
        v["round"], v["artifact_sha256"] = rnd, pr.sha(text)
        rc, _, err = aiw("peer-review", "verdict", rd, "--lens", "critical", "--file", write(os.path.join(tmp, "v"), v))
        assert rc == 0, err
        text += f"\n<!-- edit {rnd} -->\n"
    rc, out, _ = aiw("peer-review", "next", rd, "--artifact", prd)
    assert out["action"] == "ask" and out["reason"] == "cap", out
    write(prd, text)
    rc, out, _ = aiw("peer-review", "next", rd, "--artifact", prd)
    assert out["action"] == "ask" and out["reason"] == "cap", "past the cap, an edit alone opens no round"
    rc, out, _ = aiw("peer-review", "next", rd, "--artifact", prd, "--more", "--prior", pri)
    assert out["action"] == "review" and out["round"] == 4, out
ok("CLI: the cap hands over (ask), an edit alone cannot pass it, --more opens exactly one more round")


# --- diff: secrets, binaries and lockfiles never reach a reviewer; long diffs are capped with a note
def git(cwd, *argv):
    subprocess.run(["git", *argv], cwd=cwd, check=True, capture_output=True)


with tempfile.TemporaryDirectory() as repo:
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    write(os.path.join(repo, "app.py"), "x = 1\n")
    write(os.path.join(repo, ".env"), "TOKEN=old\n")
    write(os.path.join(repo, ".gitignore"), "ignored.txt\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    write(os.path.join(repo, "app.py"), "x = 2\n")
    write(os.path.join(repo, ".env"), "TOKEN=sekret-tracked\n")  # a committed .env: tracked, still dropped
    write(os.path.join(repo, "new.py"), "y = 3\n")
    write(os.path.join(repo, "ignored.txt"), "IGNORED-CONTENT\n")
    write(os.path.join(repo, "my_secret.txt"), "hunter2\n")
    write(os.path.join(repo, "creds.pem"), "PEM\n")
    write(os.path.join(repo, "package-lock.json"), '{"lock": 1}\n')
    with open(os.path.join(repo, "logo.png"), "wb") as fh:
        fh.write(b"\x89PNG\0\0PIXELDATA")
    rc, out, err = aiw("peer-review", "diff", "--since", base, "--repo", repo)
    assert rc == 0, err
    assert "x = 2" in out and "y = 3" in out, out
    for leak in ("sekret-tracked", "IGNORED-CONTENT", "hunter2", "PEM", '"lock"', "PIXELDATA"):
        assert leak not in out, (leak, out)
    assert "dropped (secret-like): .env, creds.pem, my_secret.txt" in out, out
    assert "dropped (lockfile): package-lock.json" in out and "dropped (binary): logo.png" in out, out
    rc, out, _ = aiw("peer-review", "diff", "--since", base, "--repo", repo, "--max-lines", "5")
    assert "truncated at 5 lines: partial: app.py; omitted: new.py" in out, out
    rc, _, err = aiw("peer-review", "diff", "--since", "@{u}", "--repo", repo)
    assert rc == 1 and "no upstream" in err, "@{u} with no upstream exits non-zero, never falls back"
    rc, _, err = aiw("peer-review", "diff", "--since", "nope", "--repo", repo)
    assert rc == 1 and "not a commit" in err, err
assert pr._drop_reason("src/id_generator.ts", False) is None and pr._drop_reason("lib/id_utils.py", False) is None
for key in ("id_rsa", "id_rsa.pub", "id_ed25519", "id_ecdsa", "id_dsa"):
    assert pr._drop_reason(f".ssh/{key}", False) == "secret-like", key
ok("diff: tracked .env, secret-named, .gitignored, binary and lockfiles dropped and named; cap notes cut files")

with tempfile.TemporaryDirectory() as tmp:
    rd = os.path.join(tmp, "r")
    os.makedirs(rd)
    write(os.path.join(rd, "ask.md"), "x")
    assert pr.status(rd) == "not run", "the dir always exists (ask.md at spawn): read round state"
    os.makedirs(os.path.join(rd, "round-1"))
    write(os.path.join(rd, "round-1", "request.json"), {})
    assert pr.status(rd) == "unfinished"
    write(os.path.join(rd, "round-1", "decision.json"), {"action": "done"})
    assert pr.status(rd) == "approved"
    write(os.path.join(rd, "round-1", "decision.json"), {"action": "ask", "reason": "cap"})
    assert pr.status(rd) == "cap reached"
    write(os.path.join(rd, "round-1", "decision.json"), {"action": "ask", "reason": "decision"})
    assert pr.status(rd) == "unfinished", "ended while a question was open"
    os.makedirs(os.path.join(rd, "round-2"))
    assert pr.status(rd) == "unfinished", "a newer round with no decision yet"
    assert pr.status(os.path.join(tmp, "missing")) == "not run"
ok("status: not run / unfinished / approved / cap reached, from the last round's decision.json")

offers = pr.offers()
assert offers["default"] == ["critical"] and offers["kinds"]["dump"] == ["critical", "ceo", "qa"], offers
assert pr.check_lenses("prd", ["qa", "critical", "qa"]) == ["qa", "critical"]
for kind, picked in (("dump", ["cto"]), ("run-issue", ["critical"]), ("prd", [])):
    try:
        pr.check_lenses(kind, picked)
        raise AssertionError((kind, picked))
    except ValueError:
        pass
ok("offers / check_lenses: what the UI draws and the server enforces")

print("test_peer_review: ok")
