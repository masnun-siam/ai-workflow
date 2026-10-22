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
