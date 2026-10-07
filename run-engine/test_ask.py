#!/usr/bin/env python3
"""Self-check for `aiw ask` (issue #118). `python3 run-engine/test_ask.py` — exit 0 = green.

Assert-based, no framework, matching test_ui_runner.py (whose checks run at import, so its
fake-`claude` shim pattern is copied here, not imported). Modes: `aiwask` runs the real
bin/aiw ask with $FAKE_ASK_JSON; `aiwaskfail` claims it ran but never calls it.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AIW = os.path.join(ROOT, "bin", "aiw")
sys.path.insert(0, HERE)

import route  # noqa: E402
import ui_runner  # noqa: E402
import ui_server  # noqa: E402
import ui_sessions  # noqa: E402

passed = 0
failed = 0
ORIG_PATH = os.environ.get("PATH", "")
INIT = '{"type":"system","subtype":"init","session_id":"sess-abc"}'
APPROVE = "Approve and start (Recommended)"

FAKE = r"""#!/bin/sh
if [ "$1" = "auth" ]; then echo '{"loggedIn": true}'; exit 0; fi
printf '%s\n' "$@" > "$FAKE_DIR/argv"
env > "$FAKE_DIR/env"
INIT='{"type":"system","subtype":"init","session_id":"sess-abc"}'
RESULT='{"type":"result","subtype":"success","is_error":false,"total_cost_usd":0.01}'
TOOL='{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"aiw ask --json '"'"'{}'"'"'"}}]}}'
case "$FAKE_CLAUDE_MODE" in
  normal)
    printf '%s\n' "$INIT" '{"type":"assistant","message":"hi"}' "$RESULT"; exit 0;;
  aiwask)
    "$FAKE_AIW" ask --json "$FAKE_ASK_JSON" > "$FAKE_DIR/ask_out" 2> "$FAKE_DIR/ask_err"
    printf '%s\n' "$INIT" "$TOOL" "$RESULT"; exit 0;;
  aiwaskfail)
    printf '%s\n' "$INIT" "$TOOL" "$RESULT"; exit 0;;
esac
"""


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


def check(fn):
    """Run one check; a failure is reported, not fatal, so RED shows the whole picture."""
    global failed
    try:
        fn()
    except BaseException as e:  # noqa: BLE001 - SystemExit from argparse must count as failure
        failed += 1
        print(f"  FAIL {fn.__name__}: {type(e).__name__}: {e}")
        if not isinstance(e, AssertionError):
            traceback.print_exc(limit=2)


def setup(mode="normal"):
    """Fresh data dir + fake claude on PATH. Returns (fake_dir, work_dir)."""
    os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()
    fake_dir = tempfile.mkdtemp()
    bindir = os.path.join(fake_dir, "bin")
    os.mkdir(bindir)
    exe = os.path.join(bindir, "claude")
    with open(exe, "w") as f:
        f.write(FAKE)
    os.chmod(exe, 0o755)
    os.environ["PATH"] = bindir + os.pathsep + ORIG_PATH
    os.environ["FAKE_DIR"] = fake_dir
    os.environ["FAKE_CLAUDE_MODE"] = mode
    os.environ["FAKE_AIW"] = AIW
    os.environ["FAKE_ASK_JSON"] = json.dumps(GATE1)
    return fake_dir, tempfile.mkdtemp()


def wait_for(pred, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("timed out waiting for condition")


def wait_status(sid, statuses):
    return wait_for(lambda: (r := ui_sessions.load(sid)) and r["status"] in statuses and r)


def wait_finished(sid):
    wait_for(lambda: sid not in ui_runner._procs)


def lines(fk, name):
    with open(os.path.join(fk, name)) as f:
        return f.read()


GATE1 = {"questions": [{"header": "Gate 1", "question": "Approve the plan?", "multiSelect": False,
                        "options": [{"label": APPROVE, "description": "go"},
                                    {"label": "Revise", "description": "rework"},
                                    {"label": "Abort", "description": "stop"}]}]}


def ask(sid, args=(), stdin=None, env_extra=None, drop=()):
    env = {**os.environ, "AIW_UI_SESSION": sid or "", **(env_extra or {})}
    for k in drop:
        env.pop(k, None)
    return subprocess.run([AIW, "ask", *args], input=stdin, capture_output=True, text=True,
                          env=env, timeout=60)


def new_sid():
    os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()
    return ui_sessions.create("/run-issue 1", tempfile.mkdtemp())["id"]


def meta_bytes(sid):
    with open(os.path.join(ui_sessions.session_dir(sid), "meta.json"), "rb") as f:
        return f.read()


def rid_of(out):
    m = re.match(r"RECORDED (q-[0-9a-z]+)", out)
    assert m, out
    return m.group(1)


def assert_gate1_round(pq):
    assert pq["id"].startswith("q-") and pq["status"] == "pending", pq
    assert [o["label"] for o in pq["questions"][0]["options"]] == [APPROVE, "Revise", "Abort"], pq
    assert pq["questions"][0]["recommended"] == APPROVE and pq["allowFreeText"] is True, pq


# ---- CLI behaviour ------------------------------------------------------------
def t_ask_json():
    sid = new_sid()
    p = ask(sid, ["--json", json.dumps(GATE1)])
    assert p.returncode == 0, (p.returncode, p.stderr)
    assert p.stdout.startswith("RECORDED q-") and "End your turn immediately" in p.stdout, p.stdout
    r = ui_sessions.load(sid)
    assert r["status"] == "waiting", r
    assert_gate1_round(r["pending_question"])
    assert rid_of(p.stdout) == r["pending_question"]["id"]
    ok("aiw ask --json records a Gate 1 round, status waiting, tells model to end turn")


def t_ask_stdin():
    sid = new_sid()
    p = ask(sid, [], stdin=json.dumps(GATE1))
    assert p.returncode == 0, (p.returncode, p.stderr)
    r = ui_sessions.load(sid)
    assert r["status"] == "waiting"
    assert_gate1_round(r["pending_question"])
    ok("aiw ask via stdin records the same round")


def t_gate_twice_and_idempotent():
    sid = new_sid()
    first = rid_of(ask(sid, ["--json", json.dumps(GATE1)]).stdout)
    again = ask(sid, ["--json", json.dumps(GATE1)])
    before = json.dumps(ui_sessions.load(sid)["pending_question"], sort_keys=True)
    assert again.returncode == 0 and rid_of(again.stdout) == first, again
    assert json.dumps(ui_sessions.load(sid)["pending_question"], sort_keys=True) == before
    assert ui_sessions.claim_answer(sid, first) is not None
    second = rid_of(ask(sid, ["--json", json.dumps(GATE1)]).stdout)
    assert second != first
    assert ui_sessions.load(sid)["pending_question"]["id"] == second
    ok("pending ask is idempotent; every new ask after an answer gets a new round id")


def t_not_ui_session():
    sid = new_sid()
    before = meta_bytes(sid)
    p = ask(sid, ["--json", json.dumps(GATE1)], drop=("AIW_UI_SESSION",))
    assert p.returncode != 0 and "AskUserQuestion" in p.stderr, (p.returncode, p.stderr)
    assert meta_bytes(sid) == before
    ok("AIW_UI_SESSION unset: nonzero, names AskUserQuestion, nothing written")


def t_headless_irrelevant():
    for val in (None, "0", "1", ""):
        sid = new_sid()
        env = {} if val is None else {"AIW_HEADLESS": val}
        p = ask(sid, ["--json", json.dumps(GATE1)], env_extra=env, drop=("AIW_HEADLESS",) if val is None else ())
        assert p.returncode == 0 and ui_sessions.load(sid)["status"] == "waiting", (val, p.returncode, p.stderr)
    ok("AIW_HEADLESS absent or any value is ignored when AIW_UI_SESSION is valid")


def t_bad_session():
    good = new_sid()
    assert ask(good, ["--json", json.dumps(GATE1)]).returncode == 0  # control: a valid session works
    ui_sessions.update(good, status="done", pending_question=None)
    unknown = "20200101T000000000000Z-deadbeef"
    for val in (None, "../x", unknown):
        p = ask(val, ["--json", json.dumps(GATE1)], drop=("AIW_UI_SESSION",) if val is None else ())
        assert p.returncode != 0, (val, p.stdout)
        assert not os.path.exists(ui_sessions.session_dir(unknown)) if val == unknown else True
    sessions = ui_sessions.list_sessions()
    assert all(s.get("pending_question") is None for s in sessions), sessions
    ok("AIW_UI_SESSION missing/malformed/unknown: nonzero, nothing written")


def t_bad_input():
    q_ok = GATE1["questions"][0]
    bad = ["{not json", json.dumps({}), json.dumps({"questions": []}), json.dumps({"questions": "x"}),
           json.dumps({"questions": [{**q_ok, "options": []}]}),
           json.dumps({"questions": [{**q_ok, "options": [{"label": "A"}, {"label": "A"}]}]})]
    for payload in bad:
        sid = new_sid()
        before = meta_bytes(sid)
        p = ask(sid, ["--json", payload])
        assert p.returncode == 5, (payload, p.returncode, p.stderr)
        assert meta_bytes(sid) == before and ui_sessions.load(sid)["pending_question"] is None
    ok("bad input: exit 5, record unchanged, no round")


def t_registration():
    try:
        route.main(["ask", "--help"])
    except SystemExit as e:
        assert e.code in (0, None), e.code
        return ok("route.main(['ask','--help']) exits 0")
    raise AssertionError("--help did not exit")


# ---- runner env/argv + end to end ---------------------------------------------
PROMPT_MARK = "Headless run: ask via aiw ask"


def env_has(fk, sid, prompt=True):
    env = lines(fk, "env").split("\n")
    assert f"AIW_UI_SESSION={sid}" in env and not any(e.startswith("AIW_HEADLESS=") for e in env), env
    assert any(e.startswith("CLAUDE_PLUGIN_DATA=") for e in env), env
    argv = lines(fk, "argv").split("\n")
    assert ("--append-system-prompt" in argv) == prompt, argv
    if prompt:
        assert PROMPT_MARK in argv[argv.index("--append-system-prompt") + 1], argv


def t_spawn_env_argv():
    assert "--append-system-prompt" not in ui_runner.CLAUDE_ARGS, ui_runner.CLAUDE_ARGS
    fk, work = setup("normal")
    sid = ui_runner.start("/run-issue 1", work)["id"]
    wait_status(sid, {"done", "failed"})
    wait_finished(sid)
    env_has(fk, sid, prompt=False)
    assert lines(fk, "argv").split("\n")[:-1] == ui_runner.CLAUDE_ARGS + ["/run-issue 1"]
    sid = ui_runner.start("/run-issue 1", work, gate_questions=True)["id"]
    wait_status(sid, {"done", "failed"})
    wait_finished(sid)
    env_has(fk, sid)
    ui_runner.resume(sid, "ans")
    wait_finished(sid)
    env_has(fk, sid)
    assert lines(fk, "argv").split("\n")[:-1] == (
        ui_runner.CLAUDE_ARGS + ["--append-system-prompt", ui_runner.HEADLESS_PROMPT, "--resume", "sess-abc", "ans"])
    ok("spawn: AIW_UI_SESSION set, AIW_HEADLESS not; prompt only on resume / gate_questions start")


def e2e(answers, resume_mode):
    fk, work = setup("aiwask")
    rec = ui_runner.start("/run-issue 1", work, gate_questions=True)
    sid = rec["id"]
    wait_status(sid, {"waiting", "failed", "done"})
    wait_finished(sid)
    r = ui_sessions.load(sid)
    assert r["status"] == "waiting", r
    env_has(fk, sid)
    first = r["pending_question"]["id"]
    assert_gate1_round(r["pending_question"])
    os.environ["FAKE_CLAUDE_MODE"] = resume_mode

    def req(method, path, body):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        c.request(method, path, body=json.dumps(body), headers={"Content-Type": "application/json"})
        resp = c.getresponse()
        resp.read()
        c.close()
        return resp.status

    srv = ui_server._Server(("127.0.0.1", 0), ui_server._Handler, (), lambda *_: "t")
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        s = req("POST", f"/api/sessions/{sid}/answer", {"round_id": first, "answers": answers})
    finally:
        srv.shutdown()
    assert s == 200, s
    wait_status(sid, {"waiting", "done", "failed"})
    wait_finished(sid)
    env_has(fk, sid)
    text = f"Answer to {first}: " + json.dumps(answers, ensure_ascii=False, separators=(",", ":"))
    assert lines(fk, "argv").split("\n")[:-1] == ui_runner.CLAUDE_ARGS + [
        "--append-system-prompt", ui_runner.HEADLESS_PROMPT, "--resume", "sess-abc", text]
    return sid, first, work


def t_e2e_approve():
    sid, first, _ = e2e({"0": {"labels": [APPROVE]}}, "normal")
    r = ui_sessions.load(sid)
    assert r["status"] == "done" and r["pending_question"] is None, r
    ok("e2e Gate 1 approve: env+argv on start/resume, exact answer text, ends done")


def t_e2e_revise_free_text():
    sid, first, _ = e2e({"0": {"other": "drop task 3"}}, "aiwask")
    assert "drop task 3" in lines(os.environ["FAKE_DIR"], "argv")
    r = ui_sessions.load(sid)
    assert r["status"] == "waiting" and r["pending_question"]["id"] != first, r
    ok("Revise with free text resumes with the text and re-asks under a new round id")


def t_e2e_abort():
    fk, work = setup("aiwask")
    run_json = os.path.join(work, "run.json")
    with open(run_json, "w") as f:
        f.write('{"ledger": "untouched"}')
    with open(run_json, "rb") as f:
        before = f.read()
    os.environ["FAKE_CLAUDE_MODE"] = "aiwask"
    rec = ui_runner.start("/run-issue 1", work, gate_questions=True)
    sid = rec["id"]
    wait_status(sid, {"waiting", "failed", "done"})
    wait_finished(sid)
    rid = ui_sessions.load(sid)["pending_question"]["id"]
    os.environ["FAKE_CLAUDE_MODE"] = "normal"
    ui_sessions.claim_answer(sid, rid)
    ui_runner.resume(sid, f'Answer to {rid}: {{"0":{{"labels":["Abort"]}}}}')
    wait_status(sid, {"done", "failed", "waiting"})
    wait_finished(sid)
    assert ui_sessions.load(sid)["status"] == "done"
    with open(run_json, "rb") as f:
        assert f.read() == before
    ok("Abort: resume exits without asking, session done, run.json untouched")


def t_missing_record():
    fk, work = setup("aiwaskfail")
    sid = ui_runner.start("/run-issue 1", work, gate_questions=True)["id"]
    wait_status(sid, {"done", "failed", "waiting"})
    wait_finished(sid)
    r = ui_sessions.load(sid)
    assert r["status"] == "failed", r
    assert "aiw ask" in r["error"] and "no question" in r["error"], r
    ok("aiw ask tool_use with nothing recorded: session failed, not done")


def t_interactive_unchanged():
    fk, work = setup("normal")
    sid = ui_runner.start("/run-issue 1", work)["id"]
    wait_status(sid, {"done", "failed", "waiting"})
    wait_finished(sid)
    assert ui_sessions.load(sid)["status"] == "done"
    ok("clean run without aiw ask still ends done")


# ---- commands/run-issue.md structure ------------------------------------------
with open(os.path.join(ROOT, "commands", "run-issue.md")) as _f:
    DOC = _f.read()


def blocks():
    """Paragraphs, further split at list-item starts, whitespace-normalised."""
    out = []
    for para in re.split(r"\n\s*\n", DOC):
        for item in re.split(r"\n(?=\s*(?:\d+\.|-)\s)", para):
            out.append(" ".join(item.split()))
    return out


SITES = {
    "Gate 1 (phase 1)": "Then gate with `AskUserQuestion`",
    "Gate 2a (phase 7)": "**Confirmed, continue**, **Hold here**",
    "epic step 3": "GATE 1 — the decomposition",
    "epic step 4 per-child": "Fire exactly one",
    "epic step 6 closer": "then gates as phase 7 does",
}


def headless_branch(b):
    return "aiw ask" in b and re.search(r"headless", b, re.I) and re.search(r"end (your|the) turn", b, re.I)


def t_doc_sites():
    bs = blocks()
    for name, anchor in SITES.items():
        hits = [b for b in bs if anchor in b]
        assert len(hits) == 1, (name, len(hits))
        assert headless_branch(hits[0]), f"{name}: no same-paragraph headless `aiw ask` + end-turn branch"
    ok("all 5 gate sites carry a same-paragraph headless aiw ask + end-turn branch")


def t_doc_no_unbranched_ask():
    bs = [b for b in blocks() if "AskUserQuestion" in b and not b.startswith("allowed-tools:")
          and "allowed-tools:" not in b]
    bare = [b[:70] for b in bs if "aiw ask" not in b]
    assert len(bs) >= 5 and not bare, bare
    ok("no AskUserQuestion paragraph lacks an aiw ask branch")


def t_doc_permissions():
    front = DOC.split("---")[1]
    allowed = next(line for line in front.splitlines() if line.startswith("allowed-tools:"))
    assert "AskUserQuestion" in allowed and "Bash(aiw:*)" in allowed
    cmds = re.findall(r"`((?:\w[^`]*?)?aiw ask[^`]*)`|^\s*((?:\S.*?)?aiw ask.*)$", DOC, re.M)
    examples = [a or b for a, b in cmds if "--json" in (a or b) or "<<" in (a or b)]
    assert examples, "no example aiw ask command in run-issue.md"
    assert all(e.strip().startswith("aiw ") for e in examples), examples
    assert not re.search(r"\|\s*aiw ask", DOC)
    ok("example aiw ask starts with `aiw `, no pipe prefix; allowed-tools keeps both")


for _fn in (t_ask_json, t_ask_stdin, t_gate_twice_and_idempotent, t_not_ui_session, t_headless_irrelevant, t_bad_session,
            t_bad_input, t_registration, t_spawn_env_argv, t_e2e_approve, t_e2e_revise_free_text, t_e2e_abort,
            t_missing_record, t_interactive_unchanged, t_doc_sites, t_doc_no_unbranched_ask,
            t_doc_permissions):
    check(_fn)

print(f"\n{passed} checks passed, {failed} failed")
sys.exit(1 if failed else 0)
