#!/usr/bin/env python3
"""Self-check for run-engine/ui_runner.py. `python3 test_ui_runner.py` — exit 0 = green.

Assert-based, no framework, matching test_ui_sessions.py. A fake `claude` shell script
is put first on PATH; env vars FAKE_CLAUDE_MODE / FAKE_CLAUDE_AUTH / FAKE_DIR drive it.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
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
      if [ -f "$FAKE_DIR/finish" ]; then
        if grep -q err "$FAKE_DIR/finish"; then
          printf '%s\n' '{"type":"result","subtype":"error","is_error":true,"total_cost_usd":0.5}'; exit 1
        fi
        printf '%s\n' "$RESULT"; exit 0
      fi
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


def meta_bytes(sid):
    return read(sid, "meta.json")


def mk(status, pid, stream=None, **kw):
    """Build a session record directly: status/pid + optional raw stream.jsonl text."""
    r = ui_sessions.create("/x", tempfile.mkdtemp())
    r = ui_sessions.update(r["id"], status=status, pid=pid, **kw)
    if stream is not None:
        with open(os.path.join(sdir(r["id"]), "stream.jsonl"), "w") as f:
            f.write(stream)
    return r["id"]


def dead_pid():
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def detached(work):
    helper = (
        "import sys; sys.path.insert(0, %r); import ui_runner; "
        "r = ui_runner.start('/run-issue 5', %r); print(r['id'], r['pid'])" % (HERE, work)
    )
    out = subprocess.run([sys.executable, "-c", helper], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    sid, pid = out.stdout.split()
    return sid, int(pid)


def restart_cases():
    import threading
    OLD = "Thu Jan  1 00:00:00 1970"
    S = INIT + "\n"

    # live re-attach, success
    d, fk, work = setup("sleep")
    ui_runner._procs.clear()
    sid, pid = detached(work)
    try:
        assert "pid_started" in ui_sessions.load(sid)
        ui_runner.reconcile()
        assert sid in ui_runner._procs and ui_runner._procs[sid] is None
        open(os.path.join(fk, "go"), "w").close()
        wait_for(lambda: b"LATE" in read(sid, "stream.jsonl"))
        with open(os.path.join(fk, "finish"), "w") as f:
            f.write("ok")
        r = wait_status(sid, {"done", "failed"})
        assert r["status"] == "done" and r["cost"] == 0.0421 and r["session_id"] == "sess-abc" \
            and r["ended_at"], r
        ok("live re-attach: LATE lands, finish -> done with cost/session_id/ended_at")
    finally:
        reap({"pid": pid})

    # live re-attach, error; plus idempotent reconcile
    d, fk, work = setup("sleep")
    ui_runner._procs.clear()
    sid, pid = detached(work)
    try:
        ui_runner.reconcile()
        n = threading.active_count()
        ui_runner.reconcile()
        assert threading.active_count() == n and list(ui_runner._procs).count(sid) == 1
        ok("reconcile twice re-attaches a live session once")
        with open(os.path.join(fk, "finish"), "w") as f:
            f.write("err")
        r = wait_status(sid, {"done", "failed"})
        assert r["status"] == "failed" and r["cost"] == 0.5, r
        ok("live re-attach ending in is_error -> failed, cost 0.5")
    finally:
        reap({"pid": pid})

    # stop() on re-attached session sticks
    d, fk, work = setup("sleep")
    ui_runner._procs.clear()
    sid, pid = detached(work)
    try:
        ui_runner.reconcile()
        assert ui_runner._procs[sid] is None
        ui_runner.stop(sid)
        assert group_gone(pid) and ui_sessions.load(sid)["status"] == "stopped"
        wait_finished(sid)
        time.sleep(0.5)
        assert ui_sessions.load(sid)["status"] == "stopped"
        ok("stop on re-attached session: stopped and stays stopped")
    finally:
        reap({"pid": pid})

    # dead pid cases
    d, fk, work = setup()
    ui_runner._procs.clear()
    base = threading.active_count()
    a = mk("running", dead_pid(), S + ASSIST + "\n" + RESULT + "\n", pid_started=OLD)
    b = mk("running", dead_pid(), S + RESULT_ERR + "\n", pid_started=OLD)
    ui_runner.reconcile()
    ra, rb = ui_sessions.load(a), ui_sessions.load(b)
    assert ra["status"] == "done" and ra["ended_at"] and ra["cost"] == 0.0421, ra
    assert rb["status"] == "failed" and "stderr.log" in rb["error"] \
        and "exit code None" not in rb["error"], rb
    assert a not in ui_runner._procs and b not in ui_runner._procs
    assert threading.active_count() == base
    ended = ra["ended_at"]
    ui_runner.reconcile()
    assert ui_sessions.load(a)["ended_at"] == ended
    ok("dead pid: done / failed from stream, no _procs entry, no thread, ended_at stable")

    # empty / null / junk
    cases = {"empty": "", "junk": "garbage\n[1,2,3]\n42\n", "missing": None}
    ids = {k: mk("running", dead_pid(), v, pid_started=OLD) for k, v in cases.items()}
    ui_runner.reconcile()
    for k, i in ids.items():
        assert ui_sessions.load(i)["status"] == "failed", (k, ui_sessions.load(i))
    ok("dead pid with empty/missing/junk stream -> failed")

    # trailing partial result
    i = mk("running", dead_pid(), S + RESULT, pid_started=OLD)
    ui_runner.reconcile()
    assert ui_sessions.load(i)["status"] == "done"
    ok("dead pid, RESULT without trailing newline -> done")

    # last result wins
    i = mk("running", dead_pid(), S + RESULT_ERR + "\n" + RESULT + "\n", pid_started=OLD)
    j = mk("running", dead_pid(), S + RESULT + "\n" + RESULT_ERR + "\n", pid_started=OLD)
    ui_runner.reconcile()
    assert ui_sessions.load(i)["status"] == "done" and ui_sessions.load(j)["status"] == "failed"
    ok("several results: last wins")

    # starting with no pid
    i = mk("starting", None)
    ui_runner.reconcile()
    r = ui_sessions.load(i)
    assert r["status"] == "failed" and "never started" in r["error"] and r["ended_at"], r
    ok("starting with pid None -> failed, never started")

    # recycled pid / legacy record: no signals, not re-attached
    i = mk("running", os.getpid(), S + RESULT + "\n", pid_started=OLD)
    j = mk("running", os.getpid(), S + RESULT_ERR + "\n")
    with mock.patch("os.kill") as k, mock.patch("os.killpg") as kg:
        ui_runner.reconcile()
        assert not k.called and not kg.called
    assert i not in ui_runner._procs and j not in ui_runner._procs
    assert ui_sessions.load(i)["status"] == "done" and ui_sessions.load(j)["status"] == "failed"
    ok("recycled pid and legacy (no pid_started) closed from stream, no signal")

    # waiting and terminal untouched
    w1 = mk("waiting", None)
    w2 = mk("waiting", os.getpid())
    t = [mk(st, os.getpid(), S + RESULT + "\n", pid_started=OLD) for st in ("done", "failed", "stopped")]
    before = {x: meta_bytes(x) for x in [w1, w2] + t}
    with mock.patch("subprocess.run", side_effect=AssertionError("ps called")), \
            mock.patch("os.kill") as k, mock.patch("os.killpg") as kg:
        ui_runner.reconcile()
        assert not k.called and not kg.called
    assert before == {x: meta_bytes(x) for x in before}
    ok("waiting and terminal records byte-identical, no ps/signal")

    # history order unchanged
    ids_before = [r["id"] for r in ui_sessions.list_sessions()]
    mk("running", dead_pid(), S + RESULT + "\n", pid_started=OLD)
    ids_before = [r["id"] for r in ui_sessions.list_sessions()]
    ui_runner.reconcile()
    assert [r["id"] for r in ui_sessions.list_sessions()] == ids_before
    ok("list_sessions ids/order unchanged by reconcile")

    # session owned by this process skipped
    i = mk("running", dead_pid(), S + RESULT + "\n", pid_started=OLD)
    fake = mock.Mock()
    ui_runner._procs[i] = fake
    n = threading.active_count()
    ui_runner.reconcile()
    assert ui_runner._procs[i] is fake and ui_sessions.load(i)["status"] == "running"
    assert threading.active_count() == n
    ui_runner._procs.pop(i)
    ok("session already in _procs is skipped")

    # error paths: corrupt meta, update raising, ps failing
    d, fk, work = setup()
    ui_runner._procs.clear()
    bad = mk("running", dead_pid(), S + RESULT + "\n", pid_started=OLD)
    with open(os.path.join(sdir(bad), "meta.json"), "w") as f:
        f.write("{not json")
    x = mk("running", dead_pid(), S + RESULT + "\n", pid_started=OLD)
    y = mk("running", dead_pid(), S + RESULT + "\n", pid_started=OLD)
    ui_runner.reconcile()
    assert ui_sessions.load(x)["status"] == "done" and ui_sessions.load(y)["status"] == "done"
    ok("corrupt meta.json skipped, others processed")

    x = mk("running", dead_pid(), S + RESULT + "\n", pid_started=OLD)
    y = mk("running", dead_pid(), S + RESULT + "\n", pid_started=OLD)
    real_update = ui_sessions.update

    def flaky(s, **kw):
        if s == x:
            raise OSError("disk boom")
        return real_update(s, **kw)

    with mock.patch.object(ui_sessions, "update", side_effect=flaky):
        ui_runner.reconcile()
    assert ui_sessions.load(y)["status"] == "done" and ui_sessions.load(x)["status"] == "running"
    ok("update raising for one session: others still closed")

    x = mk("running", os.getpid(), S + RESULT + "\n", pid_started=OLD)
    with mock.patch("subprocess.run", side_effect=OSError("no ps")):
        ui_runner.reconcile()
    assert ui_sessions.load(x)["status"] == "done" and x not in ui_runner._procs
    ok("ps missing: treated as not owned, closed from stream, no crash")


if "--restart" in sys.argv:
    restart_cases()
    print(f"\n{passed} restart checks passed")
    sys.exit(0)

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
    assert isinstance(final.get("pid_started"), str) and final["pid_started"], final
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

restart_cases()

print(f"\n{passed} checks passed")
