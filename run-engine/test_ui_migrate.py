#!/usr/bin/env python3
"""Self-check for run-engine/ui_migrate.py. `python3 test_ui_migrate.py` — exit 0 = green."""

import io
import contextlib
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui_migrate

d = tempfile.mkdtemp()
old = ["runs", "pipelines", "flows", "maintree", "locks"]
old_files = ["gh-status.json", "titles.json", "grind_requests.json", "grind_notified.json"]
kept = ["sessions", "pr-grind", "peer-review"]
kept_files = ["ui_settings.json", "checkouts.json", "afk.json", "ui.json", "channels.json"]
for n in old + kept:
    os.makedirs(os.path.join(d, n, "sub"))
    open(os.path.join(d, n, "sub", "f"), "w").write("x")
for n in old_files + kept_files:
    open(os.path.join(d, n), "w").write("{}")

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    removed = ui_migrate.clear_old_data(d)
assert sorted(os.path.basename(p) for p in removed) == sorted(old + old_files), removed
assert not any(os.path.exists(os.path.join(d, n)) for n in old + old_files)
assert all(os.path.exists(os.path.join(d, n)) for n in kept + kept_files)
assert all(n in buf.getvalue() for n in old + old_files)
assert os.path.exists(os.path.join(d, ui_migrate.MARKER))
print("  ok  first start removes the old paths, logs each, keeps the rest")

os.makedirs(os.path.join(d, "runs"))  # reappears after the marker: never touched again
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    assert ui_migrate.clear_old_data(d) == []
assert buf.getvalue() == "" and os.path.isdir(os.path.join(d, "runs"))
print("  ok  second start removes and logs nothing")

e = os.path.join(tempfile.mkdtemp(), "fresh")  # data dir that does not exist yet
with contextlib.redirect_stdout(io.StringIO()):
    assert ui_migrate.clear_old_data(e) == []
assert os.path.exists(os.path.join(e, ui_migrate.MARKER))
print("  ok  fresh data dir just gets the marker")

g = tempfile.mkdtemp()
open(os.path.join(g, "titles.json"), "w").write("{}")
real_remove = os.remove


def _deny(p):
    raise PermissionError(13, "denied", p)


os.remove = _deny
try:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
        removed = ui_migrate.clear_old_data(g)
finally:
    os.remove = real_remove
assert removed == [] and os.path.exists(os.path.join(g, "titles.json"))
assert os.path.exists(os.path.join(g, ui_migrate.MARKER))
print("  ok  an unremovable old path warns, startup carries on, marker still written")
