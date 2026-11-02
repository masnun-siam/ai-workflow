#!/usr/bin/env python3
"""Self-check for run-engine/dispatch_cli.py. `python3 test_dispatch_cli.py` — exit 0 = green. No network."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
data = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = data
import dispatch_cli as dc  # noqa: E402
import dispatch_run as dr  # noqa: E402


def cp(out="", code=0):
    return subprocess.CompletedProcess([], code, out, "err" if code else "")


# --- parse_epic
assert dc.parse_epic("o/r#12") == ("o/r", 12)
assert dc.parse_epic("12", gh=lambda a: cp("me/x\n")) == ("me/x", 12)
for bad in ("o/r", "#12", "12; rm", ""):
    try:
        dc.parse_epic(bad, gh=lambda a: cp("me/x"))
        raise AssertionError(f"accepted {bad!r}")
    except ValueError:
        pass
print("  ok  parse_epic")


# --- children_from: open only, deps inside, open blockers outside, refined label, cross-repo
def node(n, repo="o/r", state="OPEN", labels=("refined",), blockers=()):
    return {
        "number": n,
        "title": f"t{n}",
        "state": state,
        "repository": {"nameWithOwner": repo},
        "labels": {"nodes": [{"name": x} for x in labels]},
        "blockedBy": {"nodes": [{"number": b, "state": s, "repository": {"nameWithOwner": r}} for r, b, s in blockers]},
    }


# --- resolve follows subIssues cursors; a child with 30 labels still reads refined
def paged_gh(argv):
    after = next((a.split("=", 1)[1] for a in argv if a.startswith("after=")), None)
    lo = {None: 0, "c1": 100}[after]
    nodes = [
        node(m, labels=[f"l{k}" for k in range(24)] + ["refined"] + ["x"] * 5)
        for m in range(lo + 1, lo + (101 if lo == 0 else 51))
    ]
    sub = {"pageInfo": {"hasNextPage": lo == 0, "endCursor": "c1"}, "nodes": nodes}
    return cp(json.dumps({"data": {"repository": {"issue": {"title": "E", "subIssues": sub}}}}))


big = dc.resolve("o/r#1", paged_gh)
assert len(big["children"]) == 150 and all(c["refined"] for c in big["children"])
try:
    dc.resolve(
        "o/r#1",
        lambda a: cp(
            json.dumps(
                {
                    "data": {
                        "repository": {
                            "issue": {
                                "title": "E",
                                "subIssues": {"pageInfo": {"hasNextPage": True, "endCursor": "c"}, "nodes": []},
                            }
                        }
                    }
                }
            )
        ),
    )
    raise AssertionError("endless paging accepted")
except ValueError as e:
    assert "too many" in str(e)
print("  ok  resolve paging")


resp = {
    "data": {
        "repository": {
            "issue": {
                "title": "Epic",
                "subIssues": {
                    "nodes": [
                        node(
                            3,
                            blockers=[
                                ("o/r", 2, "OPEN"),
                                ("o/r", 1, "CLOSED"),
                                ("x/y", 9, "OPEN"),
                                ("x/y", 8, "CLOSED"),
                            ],
                        ),
                        node(2),
                        node(1, state="CLOSED"),
                        node(4, repo="o/web", labels=(), blockers=[("o/r", 3, "OPEN")]),
                    ]
                },
            }
        }
    }
}
title, kids, outside = dc.children_from(resp)
assert title == "Epic"
assert [(c["repo"], c["n"], c["refined"], c["deps"]) for c in kids] == [
    ("o/r", 2, True, []),
    ("o/r", 3, True, ["o/r#2"]),
    ("o/web", 4, False, ["o/r#3"]),
], kids
assert outside == {"o/r#3": ["x/y#9"]}
try:
    dc.children_from({"data": {"repository": {"issue": None}}})
    raise AssertionError("missing epic accepted")
except ValueError:
    pass
print("  ok  children_from")

d0 = dr.create("o/r#50", "headless", {"grind": "off"}, [])
# --- parse_issues, issues_from, resolve_issues, preview and start for an issue list
assert dc.parse_issues(["O/R#3", "o/r#1"]) == ("O/R", [3, 1])
for bad in ([], ["o/r#1"] * 31, ["12"], ["o/r"], ["o/r#1", "x/y#2"], ["o/r#1; rm"]):
    try:
        dc.parse_issues(bad)
        raise AssertionError(f"accepted {bad!r}")
    except ValueError:
        pass
iresp = {
    "data": {
        "repository": {
            "i0": node(
                3, blockers=[("o/r", 2, "OPEN"), ("o/r", 1, "CLOSED"), ("x/y", 9, "OPEN"), ("x/y", 8, "CLOSED")]
            ),
            "i1": node(2, labels=()),
            "i2": node(1, state="CLOSED"),
        }
    }
}
refs = ["o/r#3", "o/r#2", "o/r#1"]
ikids, ioutside, iclosed = dc.issues_from(iresp, refs)
assert [(c["n"], c["refined"], c["deps"]) for c in ikids] == [(2, False, []), (3, True, ["o/r#2"])], ikids
assert ioutside == {"o/r#3": ["x/y#9"]} and iclosed == ["o/r#1"]
try:
    dc.issues_from({"data": {"repository": {"i0": None}}}, ["o/r#7"])
    raise AssertionError("not-found accepted")
except ValueError as e:
    assert "o/r#7" in str(e)
gh_calls = []


def gh_issues(argv):
    gh_calls.append(argv)
    return cp(json.dumps(iresp))


ri = dc.resolve_issues(refs, gh_issues)
assert len(gh_calls) == 1 and "i2: issue(number: 1)" in gh_calls[0][3]
assert ri["epic"] is None and ri["issues"] == ["o/r#2", "o/r#3"] and ri["closed"] == ["o/r#1"]
assert ri["title"] == "Small changes: #2, #3"
w = dc.preview(ri, {"grind": "off"}, "headless")
assert w["epic"] is None and w["issues"] == ri["issues"] and w["title"] == ri["title"]
assert "o/r#2: needs refine" in w["warnings"]
assert "o/r#3: blocked by open x/y#9 outside the pick" in w["warnings"]
assert "o/r#1: closed, left out" in w["warnings"]
di = dc.start(None, "headless", dr.check_settings({**dr.DEFAULTS, "grind": "off"}), gh=gh_issues, issues=refs)
assert di["epic"] is None and di["issues"] == ["o/r#2", "o/r#3"]
assert not any("git/refs" in " ".join(c) for c in gh_calls)
try:
    dc.start(
        None,
        "headless",
        dr.check_settings(dict(dr.DEFAULTS)),
        gh=lambda a: cp(json.dumps({"data": {"repository": {"i0": node(1, state="CLOSED")}}})),
        issues=["o/r#1"],
    )
    raise AssertionError("all-closed accepted")
except ValueError as e:
    assert str(e) == "none of the picked issues is open"
assert dc.summary(di)["issues"] == ["o/r#2", "o/r#3"] and dc.summary(dr.load(d0["id"]))["issues"] is None
print("  ok  issue list")

# --- preview warnings: checkout, slack channel, outside blockers, unrefined
r = {"epic": "o/r#1", "title": "Epic", "children": kids, "outside": outside}
w = dc.preview(r, {"grind": "full"}, "herdr")["warnings"]
assert "o/web#4: needs refine" in w
assert "o/r#3: blocked by open x/y#9 outside the epic" in w
assert "o/r: no local checkout registered (aiw ui -> Repositories)" in w
assert "o/r: no Slack channel or reviewer, its lanes skip grinding" in w
with open(os.path.join(data, "channels.json"), "w") as f:
    json.dump({"channels": {"o/r": "C1"}}, f)
assert dc.channel("o/r") == "" and dc.channel("o/web") is None
assert dc.reviewer("o/web") is None, "no reviewer set"
dc.ui_settings.save({"repos": {"o/web": {"reviewer": "copilot"}, "o/r": {"reviewer": "bob"}}})
assert dc.reviewer("o/web") == "copilot", "no Slack channel: the reviewer"
assert dc.reviewer("o/r") is None, "Slack wins"
assert not [x for x in dc.preview(r, {"grind": "full"}, "herdr")["warnings"] if x.startswith("o/web: no Slack")]
w = dc.preview(r, {"grind": "off"}, "headless")["warnings"]
assert not [x for x in w if "Slack" in x or "checkout" in x]
print("  ok  preview")

# --- feature branch: exists -> nothing; missing -> cut from the default branch
calls = []


def gh_fb(missing):
    def gh(argv):
        calls.append(argv)
        if argv[1].startswith("repos/o/r/git/ref/heads/"):
            return cp(code=1 if missing else 0)
        if argv[0] == "repo":
            return cp("main\n")
        if argv[1] == "repos/o/r/commits/main":
            return cp("abc123\n")
        return cp("{}")

    return gh


assert dc.ensure_feature_branch("o/r", "feature/x", gh_fb(False)) is False and len(calls) == 1
assert dc.ensure_feature_branch("o/r", "feature/x", gh_fb(True)) is True
assert calls[-1] == ["api", "repos/o/r/git/refs", "-f", "ref=refs/heads/feature/x", "-f", "sha=abc123"]
print("  ok  feature branch")

# --- base branch: branch_sha, Preview warning, Start refusal, cut point
refs_ = {"repos/o/a/git/ref/heads/staging": "sha-staging", "repos/o/b/git/ref/heads/main": "sha-main"}
calls = []


def gh_base(argv):
    calls.append(argv)
    if argv[0] == "api" and argv[1] in refs_:
        return cp(refs_[argv[1]] + "\n")
    return cp("{}") if argv[1].endswith("/git/refs") else cp("", 1)


assert dc.branch_sha("o/a", "staging", gh_base) == "sha-staging"
assert dc.branch_sha("o/b", "staging", gh_base) is None
assert dc.missing_base(["o/b", "o/a"], "", gh_base) == []
two = {
    "epic": "o/a#1",
    "title": "E",
    "children": [{"repo": "o/a", "n": 2, "refined": True}, {"repo": "o/b", "n": 3, "refined": True}],
    "outside": {},
    "closed": [],
}
calls.clear()
assert (
    "o/b: base branch staging does not exist"
    in dc.preview(two, {"grind": "off", "base_branch": "staging"}, "headless", gh_base)["warnings"]
)
assert not [
    x
    for x in dc.preview(two, {"grind": "off", "base_branch": "staging"}, "headless", gh_base)["warnings"]
    if "o/a:" in x
]
calls.clear()
assert not [x for x in dc.preview(two, {"grind": "off"}, "headless", gh_base)["warnings"] if "base branch" in x]
assert calls == []
st = dr.check_settings({**dr.DEFAULTS, "grind": "off", "base_branch": "staging", "feature_branch": "feat/x"})
real_resolve = dc.resolve
dc.resolve = lambda epic, gh=None: two
before = len(dr.list_all())
calls.clear()
try:
    dc.start("o/a#1", "headless", st, gh=gh_base)
    raise AssertionError("started with a missing base")
except ValueError as e:
    assert str(e) == "o/b: base branch staging does not exist", e
assert not [c for c in calls if "git/refs" in c[1]] and len(dr.list_all()) == before
refs_["repos/o/b/git/ref/heads/staging"] = "sha-b"
refs_["repos/o/a/git/ref/heads/staging"] = "sha-staging"
for old in dr.list_all():
    old["state"] = "done"
    dr.save(old)
calls.clear()
dc.start("o/a#1", "headless", st, gh=gh_base)
made = [c for c in calls if c[1].endswith("/git/refs")]
assert [c[-1] for c in made] == ["sha=sha-staging", "sha=sha-b"], made
assert not [c for c in calls if c[0] == "repo" or "/commits/" in c[1]]
refs_["repos/o/a/git/ref/heads/feat/x"] = "x"
refs_["repos/o/b/git/ref/heads/feat/x"] = "x"
for old in dr.list_all():
    old["state"] = "done"
    dr.save(old)
calls.clear()
dc.start("o/a#1", "headless", st, gh=gh_base)
assert not [c for c in calls if c[1].endswith("/git/refs")]
dc.resolve = real_resolve
print("  ok  base branch")

# --- grind_mode: the owning dispatch decides, else Settings
d = dr.create("o/r#1", "headless", {"grind": "simple"}, [{"repo": "o/r", "n": 5, "refined": True}])
d["lanes"]["o/r#5"]["pr"] = 77
dr.save(d)
assert dc.grind_mode("https://github.com/O/R/pull/77") == "simple"
assert dc.grind_mode("https://github.com/o/r/pull/78") == "deep" == dc.grind_mode(None)
dr.set_settings(d["id"], grind="full")
assert dc.grind_mode("https://github.com/o/r/pull/77") == "deep"
print("  ok  grind_mode")

# --- watch: returns on an attention event, ignores plain progress until timeout
clock = [100.0]
dd = dr.load(d["id"])
dd["events"] = [{"at": 150, "lane": "o/r#5", "kind": "stage", "text": "queued -> implementing"}]
dr.save(dd)
new, state = dc.watch(
    d["id"],
    120,
    timeout=30,
    sleep=lambda s: clock.__setitem__(0, clock[0] + s),
    clock=lambda: clock[0],
    ui_up=lambda: True,
)
assert [e["kind"] for e in new] == ["stage"] and clock[0] >= 130  # timed out with progress only
dd["events"].append({"at": 160, "lane": "o/r#5", "kind": "needs_you", "text": "waiting on you"})
dr.save(dd)
new, _ = dc.watch(d["id"], 150, timeout=999, sleep=lambda s: None, clock=lambda: 0, ui_up=lambda: True)
assert [e["kind"] for e in new] == ["needs_you"]
# a dead UI port restarts the server, at most once per 60 s
starts = []
clock = [0]
dc.watch(
    d["id"],
    400,
    timeout=130,
    sleep=lambda s: clock.__setitem__(0, clock[0] + s),
    clock=lambda: clock[0],
    ui_up=lambda: False,
    start=lambda: starts.append(clock[0]),
)
assert len(starts) == 3 and starts[1] - starts[0] >= 60, starts
starts.clear()
clock[0] = 0
dc.watch(
    d["id"],
    400,
    timeout=130,
    sleep=lambda s: clock.__setitem__(0, clock[0] + s),
    clock=lambda: clock[0],
    ui_up=lambda: True,
    start=lambda: starts.append(1),
)
assert not starts
print("  ok  watch")

# --- the CLI end to end on a record: set, lane by number, pause, show, ls, errors exit 5
AIW = [sys.executable, os.path.join(HERE, "route.py")]


def aiw(*a):
    return subprocess.run([*AIW, "dispatch", *a], capture_output=True, text=True, env=os.environ)


assert aiw("set", d["id"], "max=3", "auto_merge=on", "grind=simple").returncode == 0
s = dr.load(d["id"])["settings"]
assert (s["max"], s["auto_merge"], s["grind"]) == (3, True, "simple")
assert aiw("set", d["id"], "ci=defer").returncode == 0
assert json.loads(aiw("show", d["id"]).stdout)["settings"]["ci"] == "defer"
assert aiw("set", d["id"], "ci=bogus").returncode == 5
assert aiw("plan", "1", "--ci", "bogus").returncode == 2  # argparse rejects it
assert aiw("set", d["id"], "bogus=1").returncode == 5
assert aiw("set", d["id"], "base_branch=x").returncode == 5  # #504 refusal, through the CLI
_p = argparse.ArgumentParser()
dc.register(_p.add_subparsers(dest="cmd"), None)


def _parse(*x):
    return _p.parse_args(["dispatch", "plan", "o/r#1", *x])


assert dc._settings(_parse("--base-branch", "staging"))["base_branch"] == "staging"
assert dc._settings(_parse())["base_branch"] is None
try:
    dc._settings(_parse("--base-branch", "a b"))
    raise AssertionError("invalid base name accepted")
except ValueError:
    pass
assert aiw("set", d["id"], "max=99").returncode == 5
assert aiw("lane", d["id"], "5", "hold").returncode == 0 and dr.load(d["id"])["lanes"]["o/r#5"]["hold_merge"]
assert aiw("lane", d["id"], "6", "hold").returncode == 5
assert aiw("pause", d["id"]).returncode == 0 and dr.load(d["id"])["state"] == "paused"
assert json.loads(aiw("show", d["id"]).stdout)["lanes"][0]["n"] == 5
assert d["id"] in aiw("ls").stdout
assert aiw("show", "000000000000").returncode == 5
assert aiw("end", d["id"], "open-pr").returncode == 5  # no feature branch
print("  ok  cli")
# --- readiness (FR-5)
import time  # noqa: E402

import ui_settings  # noqa: E402

rbin = tempfile.mkdtemp()
rlog = os.path.join(rbin, "calls.log")
rsleep = os.path.join(rbin, "sleep")
with open(os.path.join(rbin, "jev"), "w") as f:
    f.write(
        f"#!/bin/sh\nb=$(cat)\necho x >> {rlog}\n[ -f {rsleep} ] && sleep 3\n"
        'case "$b" in *thin*) echo \'{"score": 1.0, "confidence": 0.9}\';; *) echo \'{"score": 2.0, "confidence": 0.9}\';; esac\n'
    )
os.chmod(os.path.join(rbin, "jev"), 0o755)
real_path = os.environ["PATH"]
os.environ["PATH"] = rbin + ":/usr/bin:/bin"


def kid(n, refined=True):
    return {"repo": "o/r", "n": n, "title": f"t{n}", "refined": refined, "deps": []}


def logged():
    return len(open(rlog).read().splitlines()) if os.path.exists(rlog) else 0


def rprev(kids, bodies):
    return dc.preview(
        {"epic": "o/r#1", "title": "E", "children": kids, "outside": {}, "bodies": bodies},
        {"grind": "off"},
        "headless",
        lambda a: cp("sha"),
    )


r2 = rprev([kid(2), kid(3), kid(4, False)], {"o/r#2": "thin issue", "o/r#3": "a full issue", "o/r#4": "x"})
assert "o/r#2: may be underspecified (jev 2/5)" in r2["warnings"], r2["warnings"]
assert [x["readiness"] for x in r2["lanes"]] == [2, 3, None]
assert "o/r#2" in [k for w in r2["waves"] for k in w] and "thin issue" not in json.dumps(r2)
assert not [w for w in r2["warnings"] if "unavailable" in w] and logged() == 2
r3 = rprev([kid(3)], {"o/r#3": None})
assert "Readiness unavailable for o/r#3" in r3["warnings"] and r3["lanes"][0]["readiness"] is None
dc.READINESS_WAIT_S = 1
open(rsleep, "w").close()
t = time.time()
r4 = rprev([kid(2), kid(3)], {"o/r#2": "a", "o/r#3": "b"})
assert time.time() - t < 3 and [w for w in r4["warnings"] if "eadiness" in w] == [
    "Readiness unavailable for o/r#2, o/r#3"
]
assert [x["readiness"] for x in r4["lanes"]] == [None, None]
os.remove(rsleep)
dc.READINESS_WAIT_S = 8
os.remove(rlog)
many = [kid(n) for n in range(1, 32)]
r5 = rprev(many, {f"o/r#{n}": f"body {n}" for n in range(1, 32)})
assert logged() == 30 and [w for w in r5["warnings"] if "unavailable" in w] == ["Readiness unavailable for o/r#31"]
os.remove(rlog)
ui_settings.save({"use_jev": False})
r6 = rprev([kid(2)], {"o/r#2": "thin"})
assert not [w for w in r6["warnings"] if "eadiness" in w] and r6["lanes"][0]["readiness"] is None and logged() == 0
ui_settings.save({"use_jev": True})
os.environ["PATH"] = tempfile.mkdtemp() + ":/usr/bin:/bin"  # jev missing
assert not [w for w in rprev([kid(2)], {"o/r#2": "thin"})["warnings"] if "eadiness" in w]
os.environ["PATH"] = real_path

# bodies are requested only on demand and stay out of the children
qs = []


def gh_body(a):
    q = next(x for x in a if x.startswith("query="))
    qs.append(q)
    node = {
        "number": 2,
        "title": "t",
        "body": "SECRET",
        "state": "OPEN",
        "repository": {"nameWithOwner": "o/r"},
        "labels": {"nodes": []},
        "blockedBy": {"nodes": []},
    }
    if "subIssues" in q:
        return cp(json.dumps({"data": {"repository": {"issue": {"title": "E", "subIssues": {"nodes": [node]}}}}}))
    return cp(json.dumps({"data": {"repository": {"i0": node}}}))


for fn, arg in ((dc.resolve, "o/r#1"), (dc.resolve_issues, ["o/r#2"])):
    with_b, without = fn(arg, gh_body, bodies=True), fn(arg, gh_body)
    assert "body" in qs[-2] and "body" not in qs[-1] and "bodies" not in without
    assert with_b["bodies"] == {"o/r#2": "SECRET"} and not any("body" in c for c in with_b["children"])
seen = {}
real_resolve_ = dc.resolve
dc.resolve = lambda epic, gh=None, bodies=False: (
    seen.update(bodies=bodies) or {"epic": epic, "title": "", "children": [], "outside": {}}
)
import contextlib  # noqa: E402
import io  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    dc.cmd_plan(_parse())
assert seen == {"bodies": True}
dc.resolve = real_resolve_
print("  ok  readiness")

# --- an owned epic exits non-zero with the message, no traceback (#714)
import route  # noqa: E402

_start = dc.start
dc.start = lambda *a, **kw: (_ for _ in ()).throw(dr.Conflict("o/r#5 is already a lane of dispatch abc", id="abc"))
err = io.StringIO()
try:
    with contextlib.redirect_stderr(err):
        route.main(["dispatch", "start", "o/r#1"])
    raise AssertionError("conflict did not exit")
except SystemExit as e:
    assert e.code not in (0, None), e.code
assert "already a lane of dispatch abc" in err.getvalue() and "Traceback" not in err.getvalue(), err.getvalue()
dc.start = _start
print("  ok  conflict exit")
# --- doctor (#741)
_up, _snaps = dc.ui_running, dc._snapshots
dd = dr.create("o/r#1", "headless", {}, [{"repo": "o/r", "n": 1, "deps": [], "title": "a"}])
dc.ui_running, dc._snapshots = (lambda *a: False), (lambda: {})
out = io.StringIO()
try:
    with contextlib.redirect_stdout(out):
        dc.cmd_doctor(argparse.Namespace(id=dd["id"]))
    raise AssertionError("dead server did not exit non-zero")
except SystemExit as e:
    assert e.code == 1
assert "dead server" in out.getvalue(), out.getvalue()
dc.ui_running, dc._snapshots = (lambda *a: True), (lambda: {"o/r": {"stale": True, "error": "boom"}})
out = io.StringIO()
try:
    with contextlib.redirect_stdout(out):
        dc.cmd_doctor(argparse.Namespace(id=None))
    raise AssertionError("stale snapshot did not exit non-zero")
except SystemExit as e:
    assert e.code == 1
assert "stale poll snapshot for o/r: boom" in out.getvalue(), out.getvalue()
dc._snapshots = lambda: {"o/r": {"stale": False, "error": None}}
out = io.StringIO()
with contextlib.redirect_stdout(out):
    dc.cmd_doctor(argparse.Namespace(id=dd["id"]))  # healthy: no exit
assert out.getvalue().strip().endswith("ok"), out.getvalue()
dc.ui_running, dc._snapshots = _up, _snaps
print("  ok  doctor")
print("dispatch_cli: all green")
