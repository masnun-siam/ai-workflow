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

for k in ("`learned: <slack id>=<login>`",):
    ok(f"header key {k}", k in keys)
ok(
    "UNRESOLVED rule",
    "`UNRESOLVED` while any id in `unlogged:` has no `learned:` line" in keys and "first login of `reviewers:`" in keys,
)
ok(
    "learning: one login per id, earliest first, then rail 3",
    "learns exactly one login per grind" in rev
    and "earliest-mentioned unresolved id" in rev
    and "learning stops" in rev
    and "goes through\n  rail 3" in rev,
)
ok(
    "set ignores case, copilot mapping",
    "ignoring case" in rev and "`copilot-pull-request-reviewer[bot]`" in rev,
)
ok(
    "seed rule",
    "no `reviewers:` line" in rev
    and "`reviewer:` (unless `UNRESOLVED`)" in rev
    and "resolver's current `logins`" in rev,
)
rail3 = skill[skill.index("3. **Third-party human comment**") : skill.index("4. **Owner asked to hold**")]
ok(
    "rail 3 uses reviewers: set",
    "`reviewers:`" in rail3
    and "ignoring case" in rail3
    and "copilot-pull-request-reviewer[bot]" in rail3
    and "the\n   reviewer nor" not in rail3,
)
ok(
    "Step 7 Monitor watches reviewers: and re-arms",
    "header's `reviewers:` list as `<login>`" in step7
    and "`not-author`" in step7
    and "`UNRESOLVED`" in step7
    and "TaskStop" in step7,
)
front = skill[: skill.index("\n---\n", 4)]
ok("TaskStop allowed", "TaskStop" in front.split("allowed-tools:")[1].splitlines()[0])
step1 = section("\n## Step 1")
ok("Step 1 reads every reviewer", "any login in `reviewers:`" in step1 and "**per reviewer**" in step1)
step2 = section("\n## Step 2")
ok(
    "Step 2 first approval, human only approval",
    "from any reviewer in the set" in step2
    and "A human's review counts only as an approval" in step2
    and "never closes a deep grind" in step2
    and "closes without a recheck" in step2
    and "fixed (or rebutted) and pushed" in step2,
)

d = tempfile.mkdtemp()
path = os.path.join(d, "o-r-1.md")
open(path, "w").write(
    "owner: o\nrepo: r\nnumber: 1\nreviewer: UNRESOLVED\nreviewers: a,b\nlearned: U1=gsm-masum\nreviewers-last: U1,U2\nunlogged: U1,U3\n"
    "reviewers-kept: no active reviewer\nrequest-failed: bob — not a collaborator\n\n## Round 1\n"
)
h = ui_runner._header(path)
ok("no paused/done", "paused" not in h and "done" not in h, str(h))
ui_runner._set_header(path, "reviewers", "a,b,c")
ui_runner._set_header(path, "reviewer", "gsm-masum")
t = open(path).read()
ok(
    "set_header keeps the other lines",
    all(
        x in t
        for x in (
            "reviewers: a,b,c\n",
            "reviewer: gsm-masum\n",
            "learned: U1=gsm-masum",
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
