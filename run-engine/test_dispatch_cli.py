#!/usr/bin/env python3
"""Self-check for run-engine/dispatch_cli.py. `python3 test_dispatch_cli.py` — exit 0 = green. No network."""

from __future__ import annotations

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
assert "o/r: no Slack channel, its lanes skip grinding" in w
with open(os.path.join(data, "channels.json"), "w") as f:
    json.dump({"channels": {"o/r": "C1"}}, f)
assert dc.channel("o/r") == "" and dc.channel("o/web") is None
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
calls.clear()
dc.start("o/a#1", "headless", st, gh=gh_base)
made = [c for c in calls if c[1].endswith("/git/refs")]
assert [c[-1] for c in made] == ["sha=sha-staging", "sha=sha-b"], made
assert not [c for c in calls if c[0] == "repo" or "/commits/" in c[1]]
refs_["repos/o/a/git/ref/heads/feat/x"] = "x"
refs_["repos/o/b/git/ref/heads/feat/x"] = "x"
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
    d["id"], 120, timeout=30, sleep=lambda s: clock.__setitem__(0, clock[0] + s), clock=lambda: clock[0]
)
assert [e["kind"] for e in new] == ["stage"] and clock[0] >= 130  # timed out with progress only
dd["events"].append({"at": 160, "lane": "o/r#5", "kind": "needs_you", "text": "waiting on you"})
dr.save(dd)
new, _ = dc.watch(d["id"], 150, timeout=999, sleep=lambda s: None, clock=lambda: 0)
assert [e["kind"] for e in new] == ["needs_you"]
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
assert aiw("set", d["id"], "max=99").returncode == 5
assert aiw("lane", d["id"], "5", "hold").returncode == 0 and dr.load(d["id"])["lanes"]["o/r#5"]["hold_merge"]
assert aiw("lane", d["id"], "6", "hold").returncode == 5
assert aiw("pause", d["id"]).returncode == 0 and dr.load(d["id"])["state"] == "paused"
assert json.loads(aiw("show", d["id"]).stdout)["lanes"][0]["n"] == 5
assert d["id"] in aiw("ls").stdout
assert aiw("show", "000000000000").returncode == 5
assert aiw("end", d["id"], "open-pr").returncode == 5  # no feature branch
print("  ok  cli")
print("dispatch_cli: all green")
