#!/usr/bin/env python3
"""Self-check for run-engine/ui_runner.py. `python3 test_ui_runner.py` — exit 0 = green.

Assert-based, no framework, matching test_ui_sessions.py. A fake `claude` shell script
is put first on PATH; env vars FAKE_CLAUDE_MODE / FAKE_CLAUDE_AUTH / FAKE_DIR drive it.
"""

from __future__ import annotations

import contextlib
import fcntl
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ui_runner  # noqa: E402
import ui_sessions  # noqa: E402

passed = 0
ORIG_PATH = os.environ.get("PATH", "")
INIT = '{"type":"system","subtype":"init","session_id":"sess-abc"}'
ASSIST = '{"type":"assistant","message":"hi"}'
RESULT = '{"type":"result","subtype":"success","is_error":false,"total_cost_usd":0.0421}'
RESULT_ERR = '{"type":"result","subtype":"error","is_error":true,"total_cost_usd":0.5}'

FAKE = r"""#!/bin/sh
if [ "$1" = "auth" ]; then
  case "$FAKE_CLAUDE_AUTH" in
    out) echo '{"loggedIn": false}'; exit 1;;
    garbage) echo 'not json at all'; exit 2;;
    *) echo '{"loggedIn": true}'; exit 0;;
  esac
fi
printf '%s\n' "$@" > "$FAKE_DIR/argv"
pwd > "$FAKE_DIR/pwd"
printf '%s' "${AIW_HEADLESS-UNSET}" > "$FAKE_DIR/headless"
echo "$FAKE_CLAUDE_INIT_ENV" > /dev/null
INIT='{"type":"system","subtype":"init","session_id":"'"${FAKE_SID:-sess-abc}"'"}'
RESULT='{"type":"result","subtype":"success","is_error":false,"total_cost_usd":'"${FAKE_COST:-0.0421}"'}'
case "$FAKE_CLAUDE_MODE" in
  normal)
    printf '%s\n' "$INIT" '{"type":"assistant","message":"hi"}' "$RESULT"
    echo "some warning" >&2
    exit 0;;
  crash)
    echo "boom on stderr" >&2
    exit 3;;
  iserror)
    printf '%s\n' "$INIT" '{"type":"result","subtype":"error","is_error":true,"total_cost_usd":0.5}'
    exit 1;;
  junk)
    printf '%s\n' "$INIT" 'this is not json' '[1,2,3]'
    printf '%s' "$RESULT"
    exit 0;;
  sleep|stuck|spawn)
    [ "$FAKE_CLAUDE_MODE" = stuck ] && trap '' TERM
    if [ "$FAKE_CLAUDE_MODE" = spawn ]; then sleep 300 & echo $! > "$FAKE_DIR/gc"; fi
    printf '%s\n' "$INIT"
    while :; do
      if [ -f "$FAKE_DIR/go" ]; then echo '{"type":"assistant","message":"LATE"}'; rm -f "$FAKE_DIR/go"; fi
      sleep 0.2
    done;;
esac
"""


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


def fresh() -> str:
    d = tempfile.mkdtemp()
    os.environ["CLAUDE_PLUGIN_DATA"] = d
    return d


def setup(mode="normal", auth="in"):
    """Fresh data dir + fake claude on PATH. Returns (data_dir, fake_dir, work_dir)."""
    d = fresh()
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
    os.environ["FAKE_CLAUDE_AUTH"] = auth
    for k in ("FAKE_SID", "FAKE_COST"):
        os.environ.pop(k, None)
    return d, fake_dir, tempfile.mkdtemp()


def sdir(sid):
    return ui_sessions.session_dir(sid)


def read(sid, name):
    with open(os.path.join(sdir(sid), name), "rb") as f:
        return f.read()


def wait_for(pred, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("timed out waiting for condition")


def wait_status(sid, statuses, timeout=20.0):
    return wait_for(lambda: (r := ui_sessions.load(sid)) and r["status"] in statuses and r, timeout)


def wait_finished(sid):
    wait_for(lambda: sid not in ui_runner._procs)


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def group_gone(pgid):
    try:
        os.killpg(pgid, 0)
        return False
    except ProcessLookupError:
        return True


def reap(*recs):
    for r in recs:
        pid = r and r.get("pid")
        if pid:
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


def real(p):
    return os.path.realpath(p.strip())


def lines(fake_dir, name):
    with open(os.path.join(fake_dir, name)) as f:
        return f.read()


def no_sessions(d):
    return not os.path.isdir(os.path.join(d, "sessions")) or not os.listdir(os.path.join(d, "sessions"))


def all_sessions():
    return ui_sessions.list_sessions()


# ---- pr-grind headless re-entry (#127) ---------------------------------------
FAKE_GH = r"""#!/bin/sh
echo "$* LOGIN=$LOGIN" >> "$FAKE_DIR/gh.log"
[ "$FAKE_GH_FAIL" = 1 ] && { echo "gh: boom" >&2; exit 1; }
case "$1 $2" in
  "pr view")
    case "$*" in
      *headRefOid*) printf '%s\n' "${FAKE_GH_SHA:-abc}";;
      *) printf '{"state":"%s"}\n' "${FAKE_GH_STATE:-OPEN}";;
    esac;;
  "pr checks") printf '%s\n' "${FAKE_GH_CHECKS:-[]}";;
  api*) printf '%s\n' "$FAKE_GH_REVIEWS" | awk -v l="$LAST" '$1 > l';;
esac
"""
REPO_ROOT = os.path.dirname(HERE)
POLL = os.path.join(REPO_ROOT, "skills", "pr-grind", "scripts", "poll-reviews.sh")
SKILL = os.path.join(REPO_ROOT, "skills", "pr-grind", "SKILL.md")
NOW = datetime(2030, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
THREAD = "https://github.com/o/r/pull/7"
REV_NEW = "2030-06-01T11:00:00Z id=9 state=APPROVED"
SINCE = "2030-06-01T10:00:00Z"
FUTURE = "2030-06-01T13:00:00Z"
PAST = "2030-06-01T11:00:00Z"
BODY = "\n## Round 1\n- notes:  keep   spacing\nnext-poll: inside-body-ignored\n\n"


def prgrind_cases() -> int:
    fails = []
    extra_procs = []

    def pset(mode="normal", auth="in"):
        d, fk, work = setup(mode, auth)
        gh = os.path.join(fk, "bin", "gh")
        with open(gh, "w") as f:
            f.write(FAKE_GH)
        os.chmod(gh, 0o755)
        for k in ("AIW_HEADLESS", "FAKE_GH_FAIL", "FAKE_GH_REVIEWS", "FAKE_GH_CHECKS", "FAKE_GH_SHA"):
            os.environ.pop(k, None)
        os.environ["FAKE_GH_STATE"] = "OPEN"
        return d, fk, work

    def mkpr(d, name="p1", thread=THREAD, body=BODY, **kv):
        h = {"owner": "o", "repo": "r", "number": "7", "thread": thread, "reviewer": "alice",
             "author": "bob", "next-poll": PAST, "poll-since": SINCE, "ci-seen": "abc green"}
        h.update(kv)
        os.makedirs(os.path.join(d, "pr-grind"), exist_ok=True)
        path = os.path.join(d, "pr-grind", name + ".md")
        with open(path, "w") as f:
            f.write("".join(f"{k}: {v}\n" for k, v in h.items() if v is not None) + body)
        return path

    def prior(work, thread=THREAD):
        r = ui_sessions.create(f"/pr-grind {thread}", work)
        return ui_sessions.update(r["id"], status="done")

    def header(path):
        out = {}
        for ln in open(path).read().split("\n"):
            if ln.startswith("## "):
                break
            k, sep, v = ln.partition(": ")
            if sep:
                out.setdefault(k, v)
        return out

    def tick(path, **kw):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            act = ui_runner.prgrind_tick(path, **kw) if "now" in kw else ui_runner.prgrind_tick(path, now=NOW)
        return act, err.getvalue()

    def ts(s):
        return datetime.fromisoformat(s.replace("Z", "+00:00"))

    def lock_free(path):
        with open(path[:-3] + ".lock", "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def ghlog(fk):
        p = os.path.join(fk, "gh.log")
        return open(p).read() if os.path.exists(p) else ""

    def case(fn):
        try:
            fn()
            ok("prgrind: " + fn.__name__)
        except BaseException as e:  # noqa: BLE001 - collect every red, not just the first
            fails.append(fn.__name__)
            print(f"  FAIL prgrind: {fn.__name__}: {type(e).__name__}: {e}")
        finally:
            reap(*all_sessions())
            for p in extra_procs:
                reap({"pid": p.pid})
            extra_procs.clear()

    def due_start():
        d, fk, work = pset()
        path = mkpr(d)
        prior(work)
        act, _ = tick(path)
        assert act == "started", act
        ss = all_sessions()
        assert len(ss) == 2, ss
        cmds = [r for r in ss if r["command"] == f"/pr-grind {THREAD}"]
        assert len(cmds) == 2 and {r["repo"] for r in cmds} == {work}, ss
        assert any(r["link"] == THREAD for r in cmds), ss
        wait_for(lambda: os.path.exists(os.path.join(fk, "headless")))
        wait_for(lambda: lines(fk, "headless") != "")
        assert lines(fk, "headless") == "1"
        wait_for(lambda: os.path.exists(os.path.join(fk, "argv")) and lines(fk, "argv").endswith("\n"))
        a = lines(fk, "argv")
        parts = a.split("\n")
        assert parts[:5] == ui_runner.CLAUDE_ARGS and parts[5] == "--append-system-prompt", parts
        assert ui_runner.REENTRY_PROMPT in a and parts[-2] == f"/pr-grind {THREAD}", parts

    def interactive_unchanged():
        d, fk, work = pset()
        os.environ.pop("AIW_HEADLESS", None)
        rec = ui_runner.start("/run-issue 1", work)
        wait_status(rec["id"], {"done", "failed"})
        assert lines(fk, "argv").split("\n")[:-1] == ui_runner.CLAUDE_ARGS + ["/run-issue 1"]
        assert lines(fk, "headless") == "UNSET"
        assert ui_runner.PRGRIND_HEARTBEAT == 1500

    def heartbeat_rewrite():
        d, fk, work = pset("sleep")
        extra = "paused-note: x\nqueued-push: abc\nci-attempt: 2 — red"
        path = mkpr(d, **{"queued-push": "abc", "ci-attempt": "2 — red"})
        prior(work)
        before = open(path).read()
        act, _ = tick(path)
        assert act == "started", act
        after = open(path).read()
        assert header(path)["next-poll"] != PAST
        assert abs((ts(header(path)["next-poll"]) - (NOW + timedelta(seconds=1500))).total_seconds()) < 2
        assert after.replace(header(path)["next-poll"], PAST, 1) == before
        assert after.split("## Round 1", 1)[1] == before.split("## Round 1", 1)[1]

    def review_trigger():
        d, fk, work = pset()
        os.environ["FAKE_GH_REVIEWS"] = REV_NEW
        path = mkpr(d, **{"next-poll": FUTURE})
        prior(work)
        act, _ = tick(path)
        assert act == "started", act
        assert header(path)["poll-since"] == "2030-06-01T11:00:00Z"
        wait_for(lambda: all(r["status"] != "running" and r["status"] != "starting" for r in all_sessions()))
        wait_for(lambda: not ui_runner._procs)
        act2, _ = tick(path)
        assert act2 != "started", act2

    def ci_trigger():
        d, fk, work = pset()
        path = mkpr(d, **{"next-poll": FUTURE, "ci-seen": "abc pending"})
        prior(work)
        act, _ = tick(path)
        assert act == "started", act
        assert header(path)["ci-seen"] == "abc green", header(path)
        wait_for(lambda: not ui_runner._procs)
        d2, fk2, work2 = pset()
        path2 = mkpr(d2, **{"next-poll": FUTURE, "ci-seen": None})
        prior(work2)
        act, _ = tick(path2)
        assert act == "idle", act
        assert header(path2).get("ci-seen"), "baseline not written"

    def idle_releases():
        d, fk, work = pset()
        path = mkpr(d, **{"next-poll": FUTURE})
        prior(work)
        act, _ = tick(path)
        assert act == "idle", act
        assert len(all_sessions()) == 1
        lock_free(path)

    def poll_once():
        d, fk, work = pset()
        os.environ["FAKE_GH_REVIEWS"] = REV_NEW + "\n2030-06-01T11:30:00Z id=10 state=COMMENTED"
        def run(extra):
            p = subprocess.Popen(["bash", POLL, "o", "r", "7", "alice", SINCE, *extra],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 start_new_session=True)
            extra_procs.append(p)
            return p
        p = run(["reviewer", "once"])
        out, _ = p.communicate(timeout=10)
        assert p.returncode == 0 and "id=9" in out and "id=10" in out, (p.returncode, out)
        os.environ["FAKE_GH_REVIEWS"] = ""
        p = run(["reviewer", "once"])
        out, _ = p.communicate(timeout=10)
        assert p.returncode == 0 and out.strip() == "", out
        os.environ["FAKE_GH_REVIEWS"] = REV_NEW
        p = run([])
        time.sleep(2)
        assert p.poll() is None, "default mode must keep looping"
        os.killpg(p.pid, signal.SIGKILL)

    def tick_all_scan():
        d, fk, work = pset()
        prior(work)
        a = mkpr(d, "a")
        mkpr(d, "b", paused="x")
        mkpr(d, "c", done="y")
        mkpr(d, "d", **{"next-poll": None})
        open(os.path.join(d, "pr-grind", "e.lock"), "w").close()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            res = ui_runner.prgrind_tick_all(now=NOW)
        assert [(p, x) for p, x in res] == [(a, "started")], res

    def timer_catchup():
        d, fk, work = pset()
        mkpr(d)
        prior(work)
        t = ui_runner.start_prgrind_timer(3600)
        assert isinstance(t, threading.Thread) and t.daemon
        wait_for(lambda: len(all_sessions()) >= 2, 10)

    def empty_and_invalid():
        d, fk, work = pset()
        assert ui_runner.prgrind_tick_all(now=NOW) == []
        os.makedirs(os.path.join(d, "pr-grind"))
        empty = os.path.join(d, "pr-grind", "z.md")
        open(empty, "w").close()
        act, err = tick(empty)
        assert act == "invalid" and err.strip(), (act, err)
        for k in ("owner", "repo", "number", "thread"):
            path = mkpr(d, "m" + k, **{k: None})
            prior(work)
            act, err = tick(path)
            assert act == "invalid" and err.strip(), (k, act)
        assert ghlog(fk) == ""
        path = mkpr(d, "nopr", thread="https://github.com/o/r/pull/99")
        n = len(all_sessions())
        act, err = tick(path)
        assert act == "invalid" and err.strip() and len(all_sessions()) == n, (act, err)

    def boundaries():
        d, fk, work = pset()
        prior(work)
        eq = mkpr(d, "eq", **{"next-poll": "2030-06-01T12:00:00Z"})
        assert tick(eq)[0] == "started"
        wait_for(lambda: not ui_runner._procs)
        plus = mkpr(d, "plus", **{"next-poll": "2030-06-01T12:00:00+00:00"})
        assert tick(plus)[0] == "started"
        wait_for(lambda: not ui_runner._procs)
        early = mkpr(d, "early", **{"next-poll": "2030-06-01T12:00:01Z"})
        assert tick(early)[0] == "idle"
        bad = mkpr(d, "bad", **{"next-poll": "not-a-date"})
        act, err = tick(bad)
        assert act == "started" and err.strip(), (act, err)
        assert abs((ts(header(bad)["next-poll"]) - (NOW + timedelta(seconds=1500))).total_seconds()) < 2

    def unresolved_reviewer():
        d, fk, work = pset()
        path = mkpr(d, reviewer="UNRESOLVED", **{"next-poll": FUTURE})
        prior(work)
        assert tick(path)[0] == "idle"
        log = ghlog(fk)
        assert "api" in log and "LOGIN=bob" in log and "!=" in log, log

    def race():
        d, fk, work = pset("sleep")
        path = mkpr(d)
        prior(work)
        bar = threading.Barrier(2)
        out = []
        def go():
            bar.wait()
            out.append(tick(path)[0])
        ts_ = [threading.Thread(target=go) for _ in range(2)]
        [t.start() for t in ts_]
        [t.join(30) for t in ts_]
        assert out.count("started") == 1, out
        assert out.count("locked") + out.count("busy") == 1, out
        assert len(all_sessions()) == 2

    def lock_handoff():
        d, fk, work = pset("sleep")
        path = mkpr(d)
        prior(work)
        assert tick(path)[0] == "started"
        child = [r for r in all_sessions() if r["pid"]][-1]
        lockp = path[:-3] + ".lock"
        with open(lockp, "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                raise AssertionError("lock not held by child")
            except BlockingIOError:
                pass
        assert tick(path)[0] in ("locked", "busy")
        os.killpg(child["pid"], signal.SIGKILL)
        wait_for(lambda: group_gone(child["pid"]), 10)
        lock_free(path)

    def restart_survival():
        d, fk, work = pset("sleep")
        path = mkpr(d)
        prior(work)
        code = ("import sys; sys.path.insert(0, %r); import ui_runner; "
                "print(ui_runner.prgrind_tick(%r))" % (HERE, path))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        assert out.stdout.strip() == "started", (out.stdout, out.stderr)
        kid = [r for r in ui_sessions.list_sessions() if r["pid"]][-1]
        assert not group_gone(kid["pid"]), "child died with its starter"
        assert tick(path)[0] in ("locked", "busy")
        os.killpg(kid["pid"], signal.SIGKILL)
        wait_for(lambda: group_gone(kid["pid"]), 10)
        _ = header(path)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        assert out.stdout.strip() == "started", (out.stdout, out.stderr)

    def busy_and_stale():
        d, fk, work = pset()
        r = prior(work)
        live = subprocess.Popen(["sleep", "300"], start_new_session=True)
        extra_procs.append(live)
        ui_sessions.update(r["id"], status="running", pid=live.pid)
        path = mkpr(d)
        assert tick(path)[0] == "busy"
        dead = subprocess.Popen(["true"], start_new_session=True)
        dead.wait()
        ui_sessions.update(r["id"], status="running", pid=dead.pid)
        assert tick(path)[0] == "started"

    def merged_closed():
        for st, word in (("MERGED", "merged"), ("CLOSED", "closed")):
            d, fk, work = pset()
            os.environ["FAKE_GH_STATE"] = st
            path = mkpr(d)
            prior(work)
            assert tick(path)[0] == "done"
            assert header(path)["done"].endswith(word), header(path)
            assert len(all_sessions()) == 1
            lock_free(path)
            assert tick(path)[0] == "done"
            assert ui_runner.prgrind_tick_all(now=NOW) == []

    def gh_errors():
        d, fk, work = pset()
        os.environ["FAKE_GH_FAIL"] = "1"
        path = mkpr(d)
        prior(work)
        before = open(path).read()
        act, err = tick(path)
        assert act == "error" and err.strip() and open(path).read() == before, (act, err)
        assert len(all_sessions()) == 1
        lock_free(path)
        os.environ.pop("FAKE_GH_FAIL")
        os.environ["FAKE_GH_REVIEWS"] = "gh: HTTP 500 server error"
        path = mkpr(d, "q", **{"next-poll": FUTURE})
        assert tick(path)[0] == "idle" and header(path)["poll-since"] == SINCE
        import ci
        with mock.patch.object(ci, "snapshot", side_effect=RuntimeError("ci boom")):
            path = mkpr(d, "r", **{"next-poll": FUTURE})
            act, err = tick(path)
            assert act == "idle" and "ci boom" in err, (act, err)
            path = mkpr(d, "s")
            assert tick(path)[0] == "started"

    def runner_error():
        d, fk, work = pset(auth="out")
        path = mkpr(d)
        prior(work)
        fds = len(os.listdir("/dev/fd"))
        act, err = tick(path)
        assert act == "error", act
        lock_free(path)
        assert len(os.listdir("/dev/fd")) <= fds, "fd leak"

    def paused():
        d, fk, work = pset()
        path = mkpr(d, paused="ci red")
        before = open(path).read()
        assert tick(path)[0] == "paused"
        assert ghlog(fk) == "" and open(path).read() == before and len(all_sessions()) == 0

    def untrusted_headers():
        d, fk, work = pset()
        prior(work)
        bad = [{"repo": "../../x"}, {"owner": "a/b"}, {"repo": ".."}, {"owner": "o;rm"},
               {"number": "7x"}, {"number": "-1"}, {"thread": "http://github.com/o/r/pull/7"},
               {"thread": "https://x/y z"}, {"thread": "https://x/y\n--evil"}]
        for i, kv in enumerate(bad):
            if "\n" in kv.get("thread", ""):
                path = mkpr(d, f"u{i}")
                txt = open(path).read().replace(f"thread: {THREAD}", "thread: https://x/y\n--evil")
                open(path, "w").write(txt)
            else:
                path = mkpr(d, f"u{i}", **kv)
            act, _ = tick(path)
            assert act == "invalid", (kv, act)
        assert ghlog(fk) == "" and len(all_sessions()) == 1

    def skill_sites():
        text = open(SKILL).read()
        assert "## Headless mode" in text, "no Headless mode section"
        body = text.split("\n---\n", 1)[1]
        blocks, cur = [], []
        for ln in body.split("\n"):
            if not ln.strip() or ln.lstrip().startswith("#") or (cur and (ln[:1].isdigit() or ln.lstrip().startswith("- ")) and not ln.startswith("   ")):
                if cur:
                    blocks.append("\n".join(cur))
                cur = [ln] if ln.strip() and not ln.lstrip().startswith("#") else []
            else:
                cur.append(ln)
        blocks.append("\n".join(cur))
        sites = [b for b in blocks if "ScheduleWakeup(" in b
                 or ("Monitor" in b and any(w in b for w in ("armed", "arming", "arm ")))]
        assert len(sites) >= 8, len(sites)
        bare = [b.strip().split("\n")[0][:70] for b in sites if "headless" not in b.lower()]
        assert not bare, bare
        assert text.count("ScheduleWakeup({delaySeconds: 1500") == 1
        assert text.count("ScheduleWakeup({stop: true})") >= 2

    for fn in (due_start, interactive_unchanged, heartbeat_rewrite, review_trigger, ci_trigger,
               idle_releases, poll_once, tick_all_scan, timer_catchup, empty_and_invalid,
               boundaries, unresolved_reviewer, race, lock_handoff, restart_survival,
               busy_and_stale, merged_closed, gh_errors, runner_error, paused,
               untrusted_headers, skill_sites):
        case(fn)
    os.environ["PATH"] = ORIG_PATH
    if fails:
        print(f"\n{len(fails)} prgrind case(s) FAILED: {', '.join(fails)}")
    return len(fails)


if "--prgrind" in sys.argv:
    sys.exit(1 if prgrind_cases() else 0)


# ---- normal: full run -------------------------------------------------------
d, fk, work = setup("normal")
rec = ui_runner.start("/run-issue 42", work)
sid = rec["id"]
try:
    assert rec["status"] == "running" and rec["pid"], rec
    ok("start returns running record with pid")
    final = wait_status(sid, {"done", "failed"})
    wait_finished(sid)
    final = ui_sessions.load(sid)
    assert read(sid, "stream.jsonl") == (INIT + "\n" + ASSIST + "\n" + RESULT + "\n").encode()
    assert final["session_id"] == "sess-abc" and final["cost"] == 0.0421, final
    assert final["status"] == "done" and final["pid"] and final["ended_at"], final
    ok("normal run: stream bytes, session_id, cost, done, ended_at")
    assert lines(fk, "argv").split("\n")[:-1] == [
        "--print", "--output-format", "stream-json", "--verbose",
        "--dangerously-skip-permissions", "/run-issue 42"], lines(fk, "argv")
    assert ui_runner.CLAUDE_ARGS == ["--print", "--output-format", "stream-json", "--verbose",
                                     "--dangerously-skip-permissions"]
    assert real(lines(fk, "pwd")) == real(work)
    ok("argv exact, cwd is checkout")
    assert b"some warning" in read(sid, "stderr.log")
    assert b"some warning" not in read(sid, "stream.jsonl")
    ok("stderr goes to stderr.log only")
finally:
    reap(rec)

# ---- slug via checkouts.json -----------------------------------------------
d, fk, work = setup("normal")
with open(os.path.join(d, "checkouts.json"), "w") as f:
    json.dump({"my-slug": work}, f)
rec = ui_runner.start("/run-issue 1", "my-slug")
try:
    wait_status(rec["id"], {"done", "failed"})
    assert real(lines(fk, "pwd")) == real(work)
    assert ui_sessions.load(rec["id"])["repo"] == "my-slug"
    ok("checkouts.json slug resolves to path; repo records slug")
finally:
    reap(rec)

# ---- detached ---------------------------------------------------------------
d, fk, work = setup("sleep")
helper = (
    "import sys; sys.path.insert(0, %r); import ui_runner; "
    "r = ui_runner.start('/run-issue 5', %r); print(r['id'], r['pid'])" % (HERE, work)
)
out = subprocess.run([sys.executable, "-c", helper], capture_output=True, text=True, timeout=60)
assert out.returncode == 0, out.stderr
sid, pid = out.stdout.split()
pid = int(pid)
try:
    assert alive(pid), "child died with its starter"
    assert os.getpgid(pid) == pid and os.getsid(pid) == pid
    assert pid != os.getpgrp() and os.getsid(pid) != os.getsid(0)
    open(os.path.join(fk, "go"), "w").close()
    wait_for(lambda: b"LATE" in read(sid, "stream.jsonl"))
    ok("detached: survives starter, own session/group, writes after starter exit land")
finally:
    reap({"pid": pid})

# ---- stop graceful ----------------------------------------------------------
d, fk, work = setup("sleep")
rec = ui_runner.start("/run-issue 6", work)
sid, pid = rec["id"], rec["pid"]
try:
    wait_for(lambda: b"init" in read(sid, "stream.jsonl"))
    t0 = time.time()
    ui_runner.stop(sid)
    assert time.time() - t0 < ui_runner.STOP_GRACE_SECONDS
    assert group_gone(pid)
    r = ui_sessions.load(sid)
    assert r["status"] == "stopped" and r["ended_at"], r
    wait_finished(sid)
    assert ui_sessions.load(sid)["status"] == "stopped"
    ok("stop graceful: group gone, status stopped and sticks")
    again = ui_runner.stop(sid)
    assert again["status"] == "stopped"
    ok("second stop on stopped is a no-op")
finally:
    reap(rec)

# ---- stop SIGKILL path ------------------------------------------------------
assert ui_runner.STOP_GRACE_SECONDS == 10
d, fk, work = setup("stuck")
rec = ui_runner.start("/run-issue 7", work)
sid, pid = rec["id"], rec["pid"]
try:
    wait_for(lambda: b"init" in read(sid, "stream.jsonl"))
    time.sleep(0.5)  # let the shell install its trap
    with mock.patch.object(ui_runner, "STOP_GRACE_SECONDS", 1):
        t0 = time.time()
        ui_runner.stop(sid)
        elapsed = time.time() - t0
    assert elapsed >= 1.0, elapsed
    assert group_gone(pid)
    assert ui_sessions.load(sid)["status"] == "stopped"
    ok("stop escalates to SIGKILL after grace; default grace is 10")
finally:
    reap(rec)

# ---- stop kills whole group -------------------------------------------------
d, fk, work = setup("spawn")
rec = ui_runner.start("/run-issue 8", work)
sid = rec["id"]
try:
    gc = int(wait_for(lambda: os.path.exists(os.path.join(fk, "gc")) and lines(fk, "gc").strip()))
    assert alive(gc)
    with mock.patch.object(ui_runner, "STOP_GRACE_SECONDS", 1):
        ui_runner.stop(sid)
    wait_for(lambda: not alive(gc), 5)
    ok("stop kills grandchild in the group")
finally:
    reap(rec)

# ---- stop idempotent on finished + errors ----------------------------------
d, fk, work = setup()
for st in ("done", "failed", "stopped"):
    r = ui_sessions.create("/x", work)
    r = ui_sessions.update(r["id"], status=st, pid=os.getpid())
    with mock.patch("os.killpg") as kp, mock.patch("os.kill") as k:
        out = ui_runner.stop(r["id"])
        assert not kp.called and not k.called
    assert out["status"] == st
ok("stop on done/failed/stopped sends no signal")
for bad in ("20990101T000000000000Z-deadbeef",):
    try:
        ui_runner.stop(bad)
        raise AssertionError("expected raise")
    except AssertionError:
        raise
    except Exception:
        pass
try:
    ui_runner.stop("../x")
    raise AssertionError("expected ValueError")
except ValueError:
    pass
ok("stop unknown sid raises; invalid sid raises ValueError")

# ---- missing binary ---------------------------------------------------------
d, fk, work = setup()
empty = tempfile.mkdtemp()
os.environ["PATH"] = empty
try:
    with mock.patch.object(subprocess, "Popen") as po:
        try:
            ui_runner.start("/run-issue 9", work)
            raise AssertionError("expected RunnerError")
        except ui_runner.RunnerError as e:
            assert "claude" in str(e) and "PATH" in str(e), e
        assert not po.called
finally:
    os.environ["PATH"] = ORIG_PATH
ss = all_sessions()
assert len(ss) == 1 and ss[0]["status"] == "failed" and ss[0]["error"] \
    and ss[0]["ended_at"] and ss[0]["pid"] is None, ss
ok("missing claude: RunnerError, failed record, no spawn")

# ---- logged out / garbage auth ---------------------------------------------
d, fk, work = setup(auth="out")
try:
    ui_runner.start("/run-issue 9", work)
    raise AssertionError("expected RunnerError")
except ui_runner.RunnerError as e:
    assert "claude auth login" in str(e), e
ss = all_sessions()
assert len(ss) == 1 and ss[0]["status"] == "failed" and ss[0]["error"], ss
assert not os.path.exists(os.path.join(fk, "argv"))
ok("logged out: RunnerError mentions claude auth login, command never ran")

d, fk, work = setup(auth="garbage")
try:
    ui_runner.start("/run-issue 9", work)
    raise AssertionError("expected RunnerError")
except ui_runner.RunnerError:
    pass
ss = all_sessions()
assert len(ss) == 1 and ss[0]["status"] == "failed" and ss[0]["error"], ss
assert not os.path.exists(os.path.join(fk, "argv"))
ok("garbage auth status is not treated as logged in")

# ---- crash / is_error -------------------------------------------------------
d, fk, work = setup("crash")
rec = ui_runner.start("/run-issue 10", work)
try:
    wait_status(rec["id"], {"done", "failed"})
    wait_finished(rec["id"])
    r = ui_sessions.load(rec["id"])
    assert r["status"] == "failed" and "3" in r["error"] and "stderr.log" in r["error"], r
    assert b"boom on stderr" in read(rec["id"], "stderr.log")
    ok("crash: failed, error names exit code 3 and stderr.log")
finally:
    reap(rec)

d, fk, work = setup("iserror")
rec = ui_runner.start("/run-issue 10", work)
try:
    wait_status(rec["id"], {"done", "failed"})
    wait_finished(rec["id"])
    r = ui_sessions.load(rec["id"])
    assert r["status"] == "failed" and r["cost"] == 0.5, r
    ok("result is_error: failed, cost still recorded")
finally:
    reap(rec)

# ---- Popen OSError, no fd leak ---------------------------------------------
d, fk, work = setup()
real_popen = subprocess.Popen


def picky(args, *a, **kw):
    if "--print" in args:
        raise OSError("exec format boom")
    return real_popen(args, *a, **kw)


before = len(os.listdir("/dev/fd"))
with mock.patch.object(subprocess, "Popen", side_effect=picky):
    try:
        ui_runner.start("/run-issue 11", work)
        raise AssertionError("expected RunnerError")
    except ui_runner.RunnerError as e:
        assert "exec format boom" in str(e), e
ss = all_sessions()
assert len(ss) == 1 and ss[0]["status"] == "failed" and "exec format boom" in ss[0]["error"], ss
assert len(os.listdir("/dev/fd")) <= before, "fd leak"
ok("Popen OSError: failed with OS error text, RunnerError, no fd leak")

# ---- bad stream lines -------------------------------------------------------
d, fk, work = setup("junk")
rec = ui_runner.start("/run-issue 12", work)
try:
    wait_status(rec["id"], {"done", "failed"})
    wait_finished(rec["id"])
    r = ui_sessions.load(rec["id"])
    raw = read(rec["id"], "stream.jsonl")
    assert b"this is not json\n[1,2,3]\n" in raw and raw.endswith(RESULT.encode()), raw
    assert r["cost"] == 0.0421 and r["session_id"] == "sess-abc" and r["status"] == "done", r
    ok("bad lines skipped, raw bytes kept, trailing partial result parsed")
finally:
    reap(rec)

# ---- input validation -------------------------------------------------------
d, fk, work = setup()
for bad in ("", "   \n", None, "-p evil", "--help"):
    try:
        ui_runner.start(bad, work)
        raise AssertionError(f"expected ValueError for {bad!r}")
    except ValueError:
        pass
assert no_sessions(d)
ok("empty/None/dash-leading command raises ValueError, no session")
for bad in (os.path.join(work, "nope"), "unknown-slug"):
    try:
        ui_runner.start("/run-issue 1", bad)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
assert no_sessions(d)
ok("bad cwd raises ValueError, no session")

# ---- shell metacharacters ---------------------------------------------------
d, fk, work = setup()
cmd = "/run-issue 1; touch PWNED"
rec = ui_runner.start(cmd, work)
try:
    wait_status(rec["id"], {"done", "failed"})
    assert lines(fk, "argv").split("\n")[-2] == cmd
    assert not os.path.exists(os.path.join(work, "PWNED"))
    assert not os.path.exists(os.path.join(fk, "PWNED"))
    ok("metacharacters are one argv element, no shell")
finally:
    reap(rec)

# ---- concurrency ------------------------------------------------------------
d, fk, work = setup("sleep")
recs = []
try:
    os.environ["FAKE_SID"], os.environ["FAKE_COST"] = "sess-A", "0.1"
    a = ui_runner.start("/run-issue 1", work)
    recs.append(a)
    os.environ["FAKE_SID"], os.environ["FAKE_COST"] = "sess-B", "0.2"
    b = ui_runner.start("/run-issue 2", tempfile.mkdtemp())
    recs.append(b)
    assert a["id"] != b["id"] and a["pid"] != b["pid"]
    assert os.getpgid(a["pid"]) != os.getpgid(b["pid"])
    wait_for(lambda: (ui_sessions.load(a["id"]) or {}).get("session_id") == "sess-A")
    wait_for(lambda: (ui_sessions.load(b["id"]) or {}).get("session_id") == "sess-B")
    assert b"sess-A" in read(a["id"], "stream.jsonl") and b"sess-B" not in read(a["id"], "stream.jsonl")
    assert b"sess-B" in read(b["id"], "stream.jsonl") and b"sess-A" not in read(b["id"], "stream.jsonl")
    ok("two concurrent sessions: distinct pids/pgids, no cross-talk")
finally:
    reap(*recs)

if prgrind_cases():
    sys.exit(1)
print(f"\n{passed} checks passed")
