#!/usr/bin/env python3
"""Skill-text check for the grind reviewers in skills/pr-grind/SKILL.md. `python3 test_grind_reviewers_text.py` — exit 0 = green."""

from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()
import ui_runner  # noqa: E402

fails = []


def ok(name, cond, detail=""):
    print(("ok  " if cond else "FAIL ") + name + ("" if cond else f": {detail}"))
    if not cond:
        fails.append(name)


def section(title):
    start = skill.index(title)
    end = skill.find("\n## ", start + 1)
    return skill[start : end if end != -1 else len(skill)]


skill = open(os.path.join(os.path.dirname(HERE), "skills", "pr-grind", "SKILL.md"), encoding="utf-8").read()

ok("Reviewers section before Step 0", 0 <= skill.find("\n## Reviewers\n") < skill.find("\n## Step 0"))
rev = section("\n## Reviewers\n")
ok("resolver call", "aiw grind-reviewers --pr" in rev)
ok("pinned rule", "--reviewer" in rev and "resolver is never run" in rev)
ok("drops PR author", "PR author" in rev)
ok("one <@id> per id", "one `<@id>` per id" in rev and "`<@id1> <@id2> recheck`" in rev and "bot_uid" in rev)
ok("other logins still requested", "the other logins are still" in rev)
ok("previous set when every request fails", "Every request of the new set failed" in rev and "`reviewers-last:`" in rev)
ok(
    "every login re-requested each recheck",
    "Every current login is requested at start and again at every recheck" in rev,
)
ok("header adds unlogged ids", "to `unlogged:`" in rev and "resolver's `unlogged`" in rev)
ok("mid-grind keeps previous set", "reviewers-kept: <reason>" in rev)

step0 = section("\n## Step 0")
ok("Step 0 stops on skip before any post", "Reviewers" in step0 and "no state file, no post" in step0)
ok(
    "--channel ignores only the invalid-channel skip",
    'starts with "invalid Slack channel"' in rev and "still stops" in rev,
)
ok("restart reuses the thread", "never open a new one" in step0)
step7 = section("\n## Step 7")
ok("Step 7 reads reviewers before retrigger", step7.find("Reviewers") < step7.find("retrigger"))

keys = skill[skill.index("Header keys") : skill.index("\n## Reviewers\n")]
for k in (
    "`reviewers: <login>,<login>`",
    "`unlogged: <slack id>,<slack id>`",
    "`reviewers-last: <id>,<id>`",
    "`reviewers-kept: <reason>`",
    "`request-failed: <login> — <error>`",
):
    ok(f"header key {k}", k in keys)
ok("unlogged comma-separated, no spaces", "comma-separated, no spaces, deduped, in" in keys)

d = tempfile.mkdtemp()
path = os.path.join(d, "o-r-1.md")
open(path, "w").write(
    "owner: o\nrepo: r\nnumber: 1\nreviewers: a,b\nreviewers-last: U1,U2\nunlogged: U1,U3\n"
    "reviewers-kept: no active reviewer\nrequest-failed: bob — not a collaborator\n\n## Round 1\n"
)
h = ui_runner._header(path)
ok("no paused/done", "paused" not in h and "done" not in h, str(h))
ui_runner._set_header(path, "reviewers", "a,b,c")
t = open(path).read()
ok(
    "set_header keeps the other lines",
    all(
        x in t
        for x in (
            "reviewers: a,b,c\n",
            "reviewers-last: U1,U2",
            "unlogged: U1,U3",
            "reviewers-kept: no active reviewer",
            "request-failed: bob — not a collaborator",
        )
    )
    and "reviewers: a,b\n" not in t,
    t,
)

sys.exit(1 if fails else 0)
