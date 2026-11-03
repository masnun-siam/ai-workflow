#!/usr/bin/env python3
"""Self-check for run-engine/install_skills.py. `python3 test_install_skills.py` — exit 0 = green. No network.
HOME and CLAUDE_PLUGIN_DATA are temp dirs: the real ~ and data dir are never touched."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
AIW = os.path.join(os.path.dirname(HERE), "bin", "aiw")
sys.path.insert(0, HERE)
HOME = tempfile.mkdtemp()
DATA = tempfile.mkdtemp()
os.environ["HOME"] = HOME
os.environ["CLAUDE_PLUGIN_DATA"] = DATA
import install_skills as ins  # noqa: E402
import repo_skills  # noqa: E402

REAL_SKILLS = repo_skills._SKILLS_DIR
LINKS = os.path.join(HOME, ".agents", "skills")
RECORD = os.path.join(DATA, "install_skills.json")
fails = []


def ok(name, cond, detail=""):
    print(("ok  " if cond else "FAIL ") + name + ("" if cond else f": {detail}"))
    if not cond:
        fails.append(name)


def plugin(*names):
    """A fake plugin skills/ folder holding `names`, made current."""
    d = os.path.join(tempfile.mkdtemp(), "skills")
    for n in names:
        os.makedirs(os.path.join(d, n))
        open(os.path.join(d, n, "SKILL.md"), "w").close()
    repo_skills._SKILLS_DIR = d
    return d


def reset():
    shutil.rmtree(os.path.join(HOME, ".agents"), ignore_errors=True)
    for f in os.listdir(DATA):
        os.remove(os.path.join(DATA, f))


def run(remove=False):
    return ins.run("codex", remove)


def rec():
    try:
        with open(RECORD, encoding="utf-8") as f:
            return json.load(f).get("codex")
    except FileNotFoundError:
        return None


def link(n):
    return os.path.join(LINKS, n)


def target(n):
    p = link(n)
    return os.readlink(p) if os.path.islink(p) else None


def user_dir(n):
    os.makedirs(link(n), exist_ok=True)
    with open(os.path.join(link(n), "mine.txt"), "w") as f:
        f.write("keep")


def kept(n):
    return os.path.isdir(link(n)) and not os.path.islink(link(n)) and os.path.isfile(os.path.join(link(n), "mine.txt"))


# 1. fresh run: folder created, three links recorded
reset()
p1 = plugin("a", "b", "c")
out = run()
ok("fresh: ~/.agents/skills created", os.path.isdir(LINKS))
ok("fresh: links point at the plugin", all(target(n) == os.path.join(p1, n) for n in "abc"), out)
ok("fresh: record lists the 3 links", rec() == [link(n) for n in "abc"], rec())
ok("fresh: summary", out[-1] == "3 linked, 0 repointed, 0 removed, 0 unchanged, 0 skipped", out)

# 2. rerun changes nothing
before = rec()
out = run()
ok("rerun: unchanged", out[:3] == ["unchanged a", "unchanged b", "unchanged c"] and "3 unchanged" in out[-1], out)
ok("rerun: record identical", rec() == before)

# 3. a user folder is skipped, never recorded, survives --remove
reset()
plugin("a", "b", "c")
user_dir("b")
out = run()
ok("user dir: kept", kept("b"))
ok("user dir: reported skipped", any(x.startswith(f"skipped {link('b')}: already exists") for x in out), out)
ok("user dir: not recorded, others linked", rec() == [link("a"), link("c")], rec())
run(remove=True)
ok("user dir: --remove leaves it", kept("b") and not os.path.lexists(link("a")))

# 4. an unrecorded symlink is skipped, not repointed
reset()
plugin("a", "b", "c")
os.makedirs(LINKS)
os.symlink("/elsewhere", link("c"))
out = run()
ok("foreign link: untouched", target("c") == "/elsewhere" and link("c") not in rec(), out)
ok("foreign link: skipped", "1 skipped" in out[-1], out)

# 5. plugin moves: every recorded link repointed
reset()
plugin("a", "b", "c")
run()
before = rec()
p2 = plugin("a", "b", "c")
out = run()
ok("moved: repointed", all(target(n) == os.path.join(p2, n) for n in "abc") and "3 repointed" in out[-1], out)
ok("moved: record unchanged", rec() == before)

# 6. skill removed from the plugin is unlinked; a new one is linked
os.remove(os.path.join(p2, "b", "SKILL.md"))
os.makedirs(os.path.join(p2, "d"))
open(os.path.join(p2, "d", "SKILL.md"), "w").close()
out = run()
ok("removed skill: link deleted", not os.path.lexists(link("b")) and "removed b" in out, out)
ok("added skill: linked", target("d") == os.path.join(p2, "d") and "linked d" in out, out)
ok("record follows", sorted(rec()) == [link(n) for n in "acd"], rec())

# 7. recorded link replaced by a real folder: skipped and dropped, by rerun and --remove
reset()
plugin("a", "b", "c")
run()
os.unlink(link("b"))
user_dir("b")
out = run()
ok(
    "replaced: kept on rerun",
    kept("b") and any(x == f"skipped {link('b')}: no longer a symlink, left untouched" for x in out),
    out,
)
ok("replaced: dropped from record", link("b") not in rec())
reset()
plugin("a", "b", "c")
run()
os.unlink(link("b"))
user_dir("b")
out = run(remove=True)
ok("replaced: --remove skips it", kept("b") and any(x.startswith(f"skipped {link('b')}: no longer") for x in out), out)
ok(
    "replaced: --remove removes the rest",
    not os.path.lexists(link("a")) and not os.path.lexists(link("c")) and rec() == [],
)

# 8. a user-deleted recorded link is recreated; --remove drops a vanished path silently
reset()
plugin("a", "b", "c")
run()
os.unlink(link("a"))
out = run()
ok("vanished: recreated", target("a") is not None and "linked a" in out and link("a") in rec(), out)
os.unlink(link("a"))
out = run(remove=True)
ok("vanished: --remove drops it silently", rec() == [] and not any("a" == x.split()[-1] for x in out[:-1]), out)

# 9. --remove deletes only recorded symlinks; second --remove has nothing
reset()
plugin("a", "b")
os.makedirs(LINKS)
os.symlink("/elsewhere", link("x"))
run()
out = run(remove=True)
ok("--remove: recorded gone", not os.path.lexists(link("a")) and not os.path.lexists(link("b")), out)
ok("--remove: unrecorded and folder stay", os.path.islink(link("x")) and os.path.isdir(LINKS))
ok("--remove: record empty", rec() == [])
ok("--remove again: nothing recorded", run(remove=True) == ["nothing recorded to remove"])

# 10. partial failure: record lists exactly the links on disk; the verb exits 1
reset()
plugin("a", "b", "c")
real_symlink, calls = os.symlink, []


def flaky(src, dst):
    calls.append(dst)
    if len(calls) == 3:
        raise OSError("disk full")
    real_symlink(src, dst)


os.symlink = flaky
try:
    ins.cmd_install_skills(type("A", (), {"harness": "codex", "remove": False})())
    code = 0
except SystemExit as e:
    code = e.code
finally:
    os.symlink = real_symlink
on_disk = sorted(link(n) for n in os.listdir(LINKS) if os.path.islink(link(n)))
ok("partial: exit 1", code == 1, code)
ok("partial: record == disk", rec() == on_disk and len(on_disk) == 2, (rec(), on_disk))

# 11. a user-repointed recorded symlink is repointed back
reset()
p = plugin("a")
run()
os.unlink(link("a"))
os.symlink("/elsewhere", link("a"))
out = run()
ok("user-repointed: repointed", target("a") == os.path.join(p, "a") and "repointed a" in out, out)

# 12. corrupt record: moved aside, existing links treated as foreign
reset()
plugin("a", "b")
run()
with open(RECORD, "w") as f:
    f.write("{not json")
err = io.StringIO()
sys.stderr, real_err = err, sys.stderr
try:
    out = run()
finally:
    sys.stderr = real_err
ok(
    "corrupt: moved aside",
    any(f.startswith("install_skills.json.corrupt-") for f in os.listdir(DATA)),
    os.listdir(DATA),
)
ok("corrupt: links skipped, none created", "2 skipped" in out[-1] and "0 linked" in out[-1] and rec() is None, out)

# 13. CLI through bin/aiw, against the real plugin skills
reset()
env = {**os.environ, "HOME": HOME, "CLAUDE_PLUGIN_DATA": DATA}


def aiw(*args):
    return subprocess.run([AIW, *args], capture_output=True, text=True, env=env)


repo_skills._SKILLS_DIR = REAL_SKILLS
real = repo_skills.names()
r = aiw("install-skills", "--harness", "codex")
ok("cli: exit 0", r.returncode == 0, r.stderr)
ok("cli: every plugin skill linked", real and all(target(n) == os.path.join(REAL_SKILLS, n) for n in real), r.stdout)
r = aiw("install-skills", "--harness", "codex", "--remove")
ok("cli: --remove", r.returncode == 0 and not any(os.path.lexists(link(n)) for n in real), r.stdout)
ok("cli: --harness required", aiw("install-skills").returncode != 0)
ok("cli: --harness opencode rejected", aiw("install-skills", "--harness", "opencode").returncode != 0)
ok("cli: --help lists it", "install-skills" in aiw("--help").stdout)

shutil.rmtree(HOME, ignore_errors=True)
shutil.rmtree(DATA, ignore_errors=True)
if fails:
    print(f"{len(fails)} failed: {fails}")
    sys.exit(1)
print("all passed")
