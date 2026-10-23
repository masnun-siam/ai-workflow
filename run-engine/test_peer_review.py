"""Self-check for the peer-review panel store. `python3 run-engine/test_peer_review.py` — exit 0 = green."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import peer_review as pr  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def ok(label):
    print("  ok ", label)


pdata = tempfile.mkdtemp()  # before any config read: the user's own data dir must not leak in
os.environ["CLAUDE_PLUGIN_DATA"] = pdata
offers = pr.offers()
assert (
    offers["max_rounds"] == 5
    and offers["default"] == ["critical"]
    and offers["kinds"]["dump"] == ["critical", "ceo", "qa"]
), offers
assert pr.check_lenses("create-prd", ["qa", "critical", "qa"]) == ["qa", "critical"]
for kind, picked in (("dump", ["cto"]), ("implement-issue", ["critical"]), ("create-prd", [])):
    try:
        pr.check_lenses(kind, picked)
        raise AssertionError((kind, picked))
    except ValueError:
        pass
ok("offers / check_lenses: what the UI draws and the server enforces")

# --- lens-session panels (task 32) ---
art = os.path.join(pdata, "prd.md")
write(art, "# PRD")
P = pr.new_panel("o/r", art, ["critical", "cto", "qa"], "root-sid")
st = pr.panel_status(P)
assert st["approved"] == 0 and st["total"] == 3 and st["round"] == 1 and st["state"] == "running", st
assert pr.record_verdict(P, "critical", "fine.\nVerdict: approve") == "approve"
assert pr.advance(P) == "wait" and pr.record_verdict(P, "cto", "**Verdict: approve**") == "approve"
assert pr.advance(P) == "wait", "advances only after all 3 reported"
assert pr.record_verdict(P, "qa", "Verdict: Approve\n") == "approve"
assert pr.advance(P) == "approved" and pr.panel_status(P)["state"] == "approved" and pr.panel_status(P)["approved"] == 3
assert open(os.path.join(pr.panel_dir(P), "round-1", "qa.md")).read().startswith("Verdict"), "fallback verdict file"
ok("panel: waits for all 3 lenses, approved when all 3 say approve")

P = pr.new_panel("o/r", art, ["critical", "cto", "qa"], None)
for rnd in range(1, 6):
    pr.record_verdict(P, "critical", "Verdict: approve")
    pr.record_verdict(P, "cto", "no verdict line here")  # counts as changes
    pr.record_verdict(P, "qa", "Verdict: changes")
    assert pr.read_verdict(P, "cto") == "changes"
    want = "next" if rnd < 5 else "cap reached"
    assert pr.advance(P) == want and pr.panel_status(P)["round"] == (rnd + (rnd < 5)), (rnd, pr.panel_status(P))
st = pr.panel_status(P)
assert st["state"] == "cap reached" and st["round"] == 5 and st["approved"] == 1, st
assert pr.read_verdict(P, "qa") == "changes", "last verdicts kept for display"
assert pr.advance(P) == "cap reached", "nothing auto-approves"
ok("panel: round 5 with a changes verdict -> cap reached, last verdicts kept")

P = pr.new_panel("o/r", art, ["critical", "cto"], None)
pr.record_verdict(P, "critical", "Verdict: approve")
pr.mark_failed(P, "cto")
st = pr.panel_status(P)
assert st["lenses"]["cto"] == "failed" and pr.advance(P) == "wait", st
pr.drop_lens(P, "cto")
st = pr.panel_status(P)
assert st["total"] == 1 and pr.advance(P) == "approved", st
P = pr.new_panel("o/r", art, ["critical"], None)
pr.drop_lens(P, "critical")
assert pr.advance(P) == "failed" and pr.panel_status(P)["state"] == "failed"
for bad in ("../x", "p-1"):
    try:
        pr.panel_dir(bad)
        raise AssertionError(bad)
    except ValueError:
        pass
ok("panel: a failed lens shows failed; dropping it lets the round finish on the rest; ids are validated")

shutil.rmtree(pdata, ignore_errors=True)
print("test_peer_review: ok")
