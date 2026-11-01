"""Plain-assert checks for shared.data_dir() and the dispatch checkouts.json registry."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dispatch  # noqa: E402
import shared  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROUTE = os.path.join(HERE, "route.py")

passed = 0


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


@contextlib.contextmanager
def env_var(key, value):
    old = os.environ.get(key)
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old


with env_var("CLAUDE_PLUGIN_DATA", "/tmp/aiw-test-data-dir-xyz"):
    assert shared.data_dir() == "/tmp/aiw-test-data-dir-xyz"
with env_var("CLAUDE_PLUGIN_DATA", None):
    assert shared.data_dir() == os.path.expanduser("~/.claude/plugins/data/ai-workflow")
ok("data_dir() honours $CLAUDE_PLUGIN_DATA and falls back to the default, read at call time")

with tempfile.TemporaryDirectory() as d:
    dd = os.path.join(d, "data")
    env = dict(os.environ, CLAUDE_PLUGIN_DATA=dd)
    proc = subprocess.run([sys.executable, ROUTE, "paths"], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["data_dir"] == dd
    assert list(out)[0] == "plugin_root" and not {"runs_dir", "config", "dod", "dor", "agents_dir"} & set(out)
    assert out["pr_grind_dir"] == os.path.join(dd, "pr-grind")
    assert out["channels"] == os.path.join(dd, "channels.json")
ok("aiw paths prints unchanged data_dir/pr_grind_dir/channels after the shared.data_dir() extraction")

# --------------------------------------------------------------------------- dispatch: checkouts.json registry

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        assert dispatch.checkouts_path() == os.path.join(shared.data_dir(), "checkouts.json")
ok("checkouts_path() reuses shared.data_dir() rather than re-deriving it")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        assert dispatch.read_checkouts() == {}
        os.makedirs(os.path.dirname(dispatch.checkouts_path()), exist_ok=True)
        open(dispatch.checkouts_path(), "w").close()  # zero bytes
        assert dispatch.read_checkouts() == {}
        with open(dispatch.checkouts_path(), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        assert dispatch.read_checkouts() == {}
ok("the registry read function returns {} for a missing/zero-byte/non-JSON file")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        dispatch.register_checkout("o-r-issue-12", "/checkouts/o-r-issue-12")
        assert dispatch.read_checkouts() == {"o-r-issue-12": "/checkouts/o-r-issue-12"}
ok("a registration write followed by a read round-trips the slug->path mapping")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        dispatch.register_checkout("o-r-issue-1", "/c/1")
        # After any successful write, the file on disk is immediately valid JSON —
        # never a truncated fragment from a non-atomic write.
        with open(dispatch.checkouts_path(), encoding="utf-8") as fh:
            json.loads(fh.read())
        dispatch.register_checkout("o-r-issue-2", "/c/2")
        with open(dispatch.checkouts_path(), encoding="utf-8") as fh:
            data = json.loads(fh.read())
        assert data == {"o-r-issue-1": "/c/1", "o-r-issue-2": "/c/2"}
ok("registration writes are atomic: the file is always valid JSON immediately after a write")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        os.environ["AIW_TEST_SECRET_TOKEN"] = "shh-do-not-leak-me"
        try:
            dispatch.register_checkout("o-r-issue-9", "/c/9")
        finally:
            os.environ.pop("AIW_TEST_SECRET_TOKEN", None)
        with open(dispatch.checkouts_path(), encoding="utf-8") as fh:
            raw = fh.read()
        assert "shh-do-not-leak-me" not in raw
        assert ".env" not in raw
        # Exact equality on the parsed registry, not substring-matching against
        # arbitrary live os.environ values (any env var set to a single char
        # appearing in the JSON would false-trip a substring loop).
        assert json.loads(raw) == {"o-r-issue-9": "/c/9"}
ok("registry content is only slug->path pairs; no os.environ value or .env-shaped content lands in it")


with tempfile.TemporaryDirectory() as d:
    dd = os.path.join(d, "data")
    env = dict(os.environ, CLAUDE_PLUGIN_DATA=dd)
    proc = subprocess.run([sys.executable, ROUTE, "paths"], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["checkouts"] == os.path.join(dd, "checkouts.json")
    assert out["data_dir"] == dd
    assert list(out)[0] == "plugin_root" and not {"runs_dir", "config", "dod", "dor", "agents_dir"} & set(out)
    assert out["pr_grind_dir"] == os.path.join(dd, "pr-grind")
    assert out["channels"] == os.path.join(dd, "channels.json")
ok("aiw paths prints a checkouts key and its other existing keys are unchanged")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        ts = [threading.Thread(target=dispatch.register_checkout, args=(f"o/r{i}", f"/p{i}")) for i in range(20)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert len(dispatch.read_checkouts()) == 20
ok("register_checkout: 20 concurrent registrations all land")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        os.makedirs(shared.data_dir())
        with open(dispatch.checkouts_path(), "w") as fh:
            fh.write("{broken")
        dispatch.register_checkout("o/r", "/p")
        assert dispatch.read_checkouts() == {"o/r": "/p"}
        assert [n for n in os.listdir(shared.data_dir()) if n.startswith("checkouts.json.corrupt-")]
ok("register_checkout sets a corrupt registry aside instead of wiping it silently")

print(f"\n{passed} checks passed")
