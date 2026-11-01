#!/usr/bin/env python3
"""Self-check for run-engine/ui_panel.py + POST /api/review. `python3 test_ui_panel.py` — exit 0 = green.

Sessions are fakes: ui_runner.start/resume are replaced by functions that create real session records, and
the test finishes a session by writing its stream and status, as the runner's follower would.
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

data_dir = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = data_dir

import ui_notify  # noqa: E402

ui_notify.send_mac = lambda *a, **k: None  # the fan-out would show a real banner
import peer_review  # noqa: E402
import ui_panel  # noqa: E402
import ui_runner  # noqa: E402
import ui_server  # noqa: E402
import ui_sessions  # noqa: E402

repo = tempfile.mkdtemp()
artifact = os.path.join(repo, "prd.md")
open(artifact, "w").write("# PRD\n")
starts, resumes = [], []


def fake_start(cmd, cwd, link=None, **kw):
    sid = ui_sessions.create(cmd, cwd, link)["id"]
    ui_sessions.update(sid, status="running", session_id="c-" + sid[-8:], cwd_path=cwd)
    starts.append((sid, cmd, kw))
    return ui_sessions.load(sid)


def fake_resume(sid, text):
    resumes.append((sid, text))
    return ui_sessions.update(sid, status="running")


def finish(sid, text="", status="done"):
    if text:
        with open(os.path.join(ui_sessions.session_dir(sid), "stream.jsonl"), "a") as fh:
            fh.write(json.dumps({"type": "result", "is_error": False, "result": text}) + "\n")
    ui_sessions.update(sid, status=status)


def root():
    sid = fake_start("do the work", repo)["id"]
    finish(sid, "done")
    starts.clear()
    return sid


def lens_sids(panel):
    return peer_review.load_panel(panel)["lens_sessions"]


srv = ui_server._Server(("127.0.0.1", 0), ui_server._Handler, ())
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]


def post(path, body):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("POST", path, json.dumps(body), {"Content-Type": "application/json"})
    r = c.getresponse()
    out = json.loads(r.read() or b"{}")
    c.close()
    return r.status, out


passed = 0


def ok(label):
    global passed
    passed += 1
    print("  ok ", label)


try:
    with mock.patch.object(ui_runner, "start", fake_start), mock.patch.object(ui_runner, "resume", fake_resume):
        # ---- 3 lenses linked to the root; verdicts relayed; re-review after the root revises; approved
        r = root()
        s, b = post(
            "/api/review", {"repo": repo, "artifact": artifact, "lenses": ["critical", "cto", "qa"], "root_session": r}
        )
        assert s == 200, (s, b)
        P = b["panel"]
        assert len(starts) == 3 and all(
            k["agent"] == "ai-workflow:peer-reviewer" and k["model"] == "opus" for *_, k in starts
        )
        assert all("round 1" in c and artifact in c and "Verdict: approve" in c for _, c, _ in starts), starts
        cfg = ui_panel.peer_review._policy()["lenses"]
        assert all(cfg[lens]["prompt"] in c for (_, c, k), lens in zip(starts, ["critical", "cto", "qa"])), (
            "lens config prompt in each session prompt"
        )
        sids = lens_sids(P)
        assert set(sids) == {"critical", "cto", "qa"}
        assert ui_sessions.load(r)["panel"] == P and ui_sessions.load(sids["cto"])["panel_role"] == "lens"
        assert ui_server._public(ui_sessions.load(r))["peer_review"]["total"] == 3
        assert ui_server._public(ui_sessions.load(sids["cto"]))["peer_review"]["lens"] == "cto"
        ok("POST /api/review: three lens sessions (opus, peer-reviewer) linked to the root; public status on both")

        finish(sids["critical"], "ok\nVerdict: approve")
        ui_panel.tick()
        assert peer_review.read_verdict(P, "critical") == "approve" and not resumes, "one tick relays the verdict"
        finish(sids["cto"], "needs X\nVerdict: changes")
        finish(sids["qa"], "needs Y, no verdict line")
        ui_panel.tick()
        assert peer_review.panel_status(P)["round"] == 2 and len(resumes) == 1, resumes
        rsid, text = resumes[0]
        assert rsid == r and "needs X" in text and "needs Y" in text and "revise the artifact in place" in text, text
        ui_panel.tick()
        assert len(resumes) == 1, "root still revising: nothing more happens"
        finish(r, "revised")
        ui_panel.tick()
        assert [x for x, _ in resumes[1:]] == list(sids.values()) and all(
            "revised since" in t and "round 2" in t for _, t in resumes[1:]
        )
        ok("verdicts reach the root within a tick; after it revises each lens gets a re-review request")

        for lens in sids:
            finish(sids[lens], "Verdict: approve")
        ui_panel.tick()
        st = peer_review.panel_status(P)
        assert st["state"] == "approved" and st["approved"] == 3 and len(resumes) == 4, st
        ok("round 2 all approve -> panel approved, root not resumed")

        # ---- cap
        r = root()
        P = ui_panel.start(repo, artifact, ["critical"], root_session=r)
        for rnd in range(1, 6):
            finish(lens_sids(P)["critical"], "Verdict: changes")
            ui_panel.tick()
            if rnd < 5:
                finish(r, "revised")
                ui_panel.tick()
        st = peer_review.panel_status(P)
        assert st["state"] == "cap reached" and st["round"] == 5 and st["lenses"]["critical"] == "changes", st
        n = len(resumes)
        ui_panel.tick()
        assert len(resumes) == n
        ok("round 5 with changes -> cap reached, nothing resumed")

        # ---- more rounds: only at the cap; raises this panel's limit and hands the root the last verdicts
        assert peer_review.panel_status(P)["max_rounds"] == 5
        for bad in (0, 6, "1", True, None):
            assert post(f"/api/review/{P}/rounds", {"add": bad})[0] == 400, bad
        assert post("/api/review/p-20200101T000000Z-aaaaaa/rounds", {"add": 1})[0] == 404
        n = len(resumes)
        s, b = post(f"/api/review/{P}/rounds", {"add": 2})
        assert s == 200 and (b["max_rounds"], b["round"], b["state"]) == (7, 6, "running"), b
        assert len(resumes) == n + 1 and resumes[-1][0] == r and "round 5 verdicts" in resumes[-1][1], resumes[-1]
        assert post(f"/api/review/{P}/rounds", {"add": 1})[0] == 409, "no longer at the cap"
        finish(r, "revised")
        ui_panel.tick()
        finish(lens_sids(P)["critical"], "Verdict: approve")
        ui_panel.tick()
        assert peer_review.panel_status(P)["state"] == "approved"
        ok("POST /api/review/<panel>/rounds: 400 bad add, 404 unknown, 409 unless capped; resumes the relay loop")

        # ---- failed lens: 409 unless failed; rerun / drop
        r = root()
        P = ui_panel.start(repo, artifact, ["critical", "cto"], root_session=r)
        sids = lens_sids(P)
        for lens in ("critical", "cto"):
            for act in ("rerun", "drop"):
                assert post(f"/api/review/{P}/lens", {"lens": lens, "action": act})[0] == 409
        assert post(f"/api/review/{P}/lens", {"lens": "ux", "action": "drop"})[0] == 400
        assert post(f"/api/review/{P}/lens", {"lens": "cto", "action": "nope"})[0] == 400
        assert post("/api/review/p-20200101T000000Z-aaaaaa/lens", {"lens": "cto", "action": "drop"})[0] == 404
        finish(sids["critical"], "Verdict: approve")
        finish(sids["cto"], status="failed")
        ui_panel.tick()
        st = peer_review.panel_status(P)
        assert st["lenses"]["cto"] == "failed" and st["state"] == "running", st
        starts.clear()
        assert post(f"/api/review/{P}/lens", {"lens": "cto", "action": "rerun"})[0] == 200
        assert len(starts) == 1 and lens_sids(P)["cto"] != sids["cto"]
        assert peer_review.panel_status(P)["lenses"]["cto"] == "waiting"
        finish(lens_sids(P)["cto"], status="failed")
        ui_panel.tick()
        assert post(f"/api/review/{P}/lens", {"lens": "cto", "action": "drop"})[0] == 200
        ui_panel.tick()
        assert peer_review.panel_status(P)["state"] == "approved" and peer_review.panel_status(P)["total"] == 1
        ok(
            "lens rerun/drop: 409 for a lens that is not failed, 400 unknown, 404 unknown panel; drop lets the round finish"
        )

        # ---- artifact deleted
        r = root()
        art2 = os.path.join(repo, "gone.md")
        open(art2, "w").write("x")
        P = ui_panel.start(repo, art2, ["critical"], root_session=r)
        os.unlink(art2)
        ui_panel.tick()
        st = peer_review.panel_status(P)
        assert st["state"] == "failed" and st["reason"] == "artifact deleted", st
        ok("deleting the artifact stops the panel on the next tick")

        # ---- no root: a fresh headless root runs the skill; after_root waits for the root's turn
        starts.clear()
        s, b = post("/api/review", {"repo": repo, "artifact": artifact, "lenses": ["qa"]})
        P = b["panel"]
        assert s == 200 and starts[0][1] == f"/ai-workflow:peer-review --root {P} {artifact}", starts
        assert peer_review.load_panel(P)["root_session"] == starts[0][0] and len(starts) == 2
        r = root()
        P = ui_panel.start(repo, artifact, ["qa"], root_session=r, after_root=True)
        ui_sessions.update(r, status="running")
        starts.clear()
        ui_panel.tick()
        assert not starts
        finish(r, "wrote it")
        ui_panel.tick()
        assert len(starts) == 1
        ok(
            "no root_session -> fresh root with the peer-review --root command; after_root starts lenses when the root ends"
        )

        # ---- validation
        for body in (
            {"repo": repo, "artifact": artifact, "lenses": []},
            {"repo": repo, "artifact": artifact},
            {"repo": repo, "artifact": artifact, "lenses": ["nope"]},
            {"repo": repo, "artifact": artifact + "x", "lenses": ["qa"]},
            {"repo": repo, "artifact": artifact, "lenses": ["qa"], "root_session": "zzz"},
        ):
            assert post("/api/review", body)[0] == 400, body

    ok("POST /api/review: no/unknown lenses, missing artifact, unknown root -> 400")

    # ---- a held root or lens session is not continued; the panel carries on after Resume
    with mock.patch.object(ui_runner, "start", fake_start), mock.patch.object(ui_runner, "resume", fake_resume):
        r = root()
        pid = ui_panel.start(repo, artifact, ["qa", "cto"], r)
        ls = lens_sids(pid)
        mine = lambda: [x[0] for x in resumes if x[0] == r or x[0] in ls.values()]  # noqa: E731
        finish(ls["qa"], "Verdict: changes")
        finish(ls["cto"], "Verdict: changes")
        ui_sessions.update(r, hold=True)
        resumes.clear()
        ui_panel.tick()
        p = peer_review.load_panel(pid)
        assert mine() == [] and p["phase"] == "lenses" and p["round"] == 1 and p["state"] == "running", p
        ui_sessions.update(r, hold=None)
        ui_panel.tick()
        assert mine() == [r] and peer_review.load_panel(pid)["phase"] == "root"
        ok("held root: no next round, phase unchanged; after Resume the round goes ahead")

        finish(r, "revised")
        ui_sessions.update(ls["qa"], hold=True)
        resumes.clear()
        ui_panel.tick()
        p = peer_review.load_panel(pid)
        assert mine() == [] and p["phase"] == "root" and p["failed"] == [], p  # cto waits for qa too
        ui_sessions.update(ls["qa"], hold=None)
        ui_panel.tick()
        assert sorted(mine()) == sorted(ls.values()) and peer_review.load_panel(pid)["phase"] == "lenses"
        ok("held lens: no lens resumed, none failed; after Resume they all start together")

        finish(ls["qa"], "Verdict: approve")
        finish(ls["cto"], "Verdict: approve")
        ui_sessions.update(ls["qa"], hold=True)
        ui_panel.tick()
        p = peer_review.load_panel(pid)
        assert peer_review.read_verdict(pid, "qa") is None and p["failed"] == [] and p["state"] == "running", p
        ui_sessions.update(ls["qa"], hold=None)
        ui_panel.tick()
        assert peer_review.load_panel(pid)["state"] == "approved"
        ok("held lens in the round: not failed, the round waits for it")

    # ---- ui_runner.start passes --agent / --model
    with (
        mock.patch.object(ui_runner, "_preflight", return_value=["claude"]),
        mock.patch.object(ui_runner, "_spawn") as sp,
    ):
        ui_runner.start("go", repo, agent="ai-workflow:peer-reviewer", model="opus")
    argv = sp.call_args[0][1]
    assert (
        argv[argv.index("--agent") + 1] == "ai-workflow:peer-reviewer"
        and argv[argv.index("--model") + 1] == "opus"
        and argv[-1] == "go"
    )
    ok("ui_runner.start: --agent and --model reach claude's argv")
finally:
    srv.shutdown()
    srv.server_close()
    shutil.rmtree(data_dir, ignore_errors=True)
    shutil.rmtree(repo, ignore_errors=True)

print(f"test_ui_panel: {passed} checks passed")
