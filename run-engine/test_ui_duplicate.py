#!/usr/bin/env python3
"""Self-check for run-engine/ui_duplicate.py with a fake `jev` on PATH. `python3 test_ui_duplicate.py` — exit 0 = green."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()

import jev  # noqa: E402
import ui_duplicate  # noqa: E402
import ui_settings  # noqa: E402

bin_dir, work = tempfile.mkdtemp(), tempfile.mkdtemp()
fake, log, answer = os.path.join(bin_dir, "jev"), os.path.join(work, "calls"), os.path.join(work, "answer")


def stub(body: str | None = None) -> None:
    """A jev that logs its argv and prints the answer file (or runs `body`)."""
    with open(fake, "w") as f:
        f.write(f'#!/bin/sh\ncat >/dev/null\necho "$@" >> {log}\n' + (body or f"cat {answer}") + "\n")
    os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)


def pick(key: str, p: float) -> None:
    with open(answer, "w") as f:
        json.dump({"choice": key, "probabilities": {key: p, "none": round(1 - p, 2)}}, f)


def calls() -> list:
    return open(log).read().splitlines() if os.path.exists(log) else []


def reset() -> None:
    jev._cache = {}
    if os.path.exists(log):
        os.remove(log)


def snap(issues, **kw) -> dict:
    return {"data": {"issues": issues, "open_prs": [], "closed_epics": []}, "stale": False, "fetched_at": 1, **kw}


def issue(n: int, title: str) -> dict:
    return {"n": n, "title": title, "labels": [], "parent": None, "sub_issues": []}


def checkout(prds: dict) -> str:
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "docs", "prds"))
    for i, (slug, title) in enumerate(prds.items()):
        path = os.path.join(d, "docs", "prds", f"{slug}.md")
        with open(path, "w") as f:
            f.write(f"# PRD — {title}\n\n**Status:** Approved · **Slug:** `{slug}`\n")
        os.utime(path, (1000 + i, 1000 + i))
    return d


old_path = os.environ.get("PATH", "")
os.environ["PATH"] = bin_dir + ":/usr/bin:/bin"  # never the real PATH: a real jev must not run
TEXT = "Add dark mode to the settings page"
empty = checkout({})
dark = snap([issue(12, "Dark mode support")])
stub()

for bad in ("", "  ", None, 5):
    try:
        ui_duplicate.check("o/r", bad, dark, empty)
        raise AssertionError(bad)
    except ValueError:
        pass

# 19 characters runs no check, 20 does
reset()
pick("issue-12", 0.7)
r = ui_duplicate.check("o/r", "x" * 19, dark, empty)
assert r == {"match": None, "confidence": 0.0, "why": "too short to check"} and not calls(), r
assert ui_duplicate.check("o/r", "  " + "x" * 20 + "  ", dark, empty)["match"] and len(calls()) == 1

# an issue match, with a url built from the slug and number
reset()
r = ui_duplicate.check("o/r", TEXT, dark, empty)
assert r["match"] == {
    "kind": "issue",
    "n": 12,
    "title": "Dark mode support",
    "url": "https://github.com/o/r/issues/12",
}, r
assert r["confidence"] == 0.7 and r["why"] == "looks like the same request"

# 0.59 is no match, 0.6 is
reset()
pick("issue-12", 0.59)
r = ui_duplicate.check("o/r", TEXT, dark, empty)
assert r["match"] is None and r["why"] == "no likely duplicate" and r["confidence"] == 0.59, r
reset()
pick("issue-12", 0.6)
assert ui_duplicate.check("o/r", TEXT, dark, empty)["match"]

reset()
pick("none", 0.9)
r = ui_duplicate.check("o/r", TEXT, dark, empty)
assert r["match"] is None and r["why"] == "no likely duplicate", r

# a PRD match: the Features link, a repo-relative path, no absolute path
reset()
pick("prd-0", 0.8)
co = checkout({"x": "Dark mode"})
r = ui_duplicate.check("o/r", TEXT, snap([]), co)
assert r["match"] == {"kind": "prd", "path": "docs/prds/x.md", "title": "Dark mode", "url": "#/features/x?repo=o/r"}, r
assert co not in json.dumps(r)

# option cap: 100 issues + 160 PRDs -> 254 options, the oldest PRDs dropped, titles cut to 120
reset()
pick("none", 0.9)
many = [issue(n, "t" * 200 if n == 1 else f"issue {n}") for n in range(1, 131)]
co = checkout({f"p{i:03}": f"prd {i}" for i in range(160)})
ui_duplicate.check("o/r", TEXT, snap(many), co)
argv = calls()[0]
assert argv.count("--option") == 254, argv.count("--option")
assert "=prd 159" in argv and "=prd 7 " in argv + " " and "=prd 6 " not in argv + " ", "153 newest kept"
assert "issue 101" not in argv and "t" * 121 not in argv and "t" * 120 in argv

# not loaded yet: the stub never runs
reset()
assert ui_duplicate.check("o/r", TEXT, snap([issue(1, "a")], stale=True), empty)["why"] == "issues not loaded yet"
assert ui_duplicate.check("o/r", TEXT, snap([issue(1, "a")], fetched_at=None), empty)["why"] == "issues not loaded yet"
assert not calls()

assert ui_duplicate.check("o/r", TEXT, snap([]), empty)["why"] == "nothing to compare with"

# off: even a cached input never runs jev
reset()
pick("issue-12", 0.7)
assert ui_duplicate.check("o/r", TEXT, dark, empty)["match"] and len(calls()) == 1
ui_settings.save({"use_jev": False})
r = ui_duplicate.check("o/r", TEXT, dark, empty)
assert r["why"] == "jev is off" and len(calls()) == 1, r
ui_settings.save({"use_jev": True})

# failures never raise
reset()
os.environ["PATH"] = tempfile.mkdtemp()
assert ui_duplicate.check("o/r", TEXT, dark, empty)["why"] == "jev is not installed"
os.environ["PATH"] = bin_dir + ":/usr/bin:/bin"
stub("exit 3")
assert ui_duplicate.check("o/r", TEXT, dark, empty)["why"] == "jev failed (exit 3)"
stub()
pick("issue-999", 0.9)
assert ui_duplicate.check("o/r", TEXT, dark, empty)["why"] == "jev gave an unreadable answer"

reset()
jev._window_calls = jev.CEILING
jev._window_start = jev._now()
r = ui_duplicate.check("o/r", TEXT, dark, empty)
assert r["why"] == "jev's hourly limit is reached", r

os.environ["PATH"] = old_path
print("ok ui_duplicate")
