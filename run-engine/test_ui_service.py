#!/usr/bin/env python3
"""Self-check for run-engine/ui_service.py. `python3 test_ui_service.py` — exit 0 = green."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

data = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = data

import ui_service  # noqa: E402

# The plist runs the launcher, which runs a login zsh that execs this plugin's `aiw ui`.
d = ui_service.plist_dict("/x/aiw-ui-launcher", "/My Repos/ai-workflow", "/x/ui.err.log")
assert d["Label"] == ui_service.LABEL
assert d["ProgramArguments"][:3] == ["/x/aiw-ui-launcher", "/bin/zsh", "-lc"]
assert d["ProgramArguments"][3] == "exec '/My Repos/ai-workflow/bin/aiw' ui", d["ProgramArguments"]  # quoted path
assert d["KeepAlive"] and d["RunAtLoad"] and d["StandardErrorPath"] == "/x/ui.err.log"

# The launcher lives in the data dir, never inside the plugin (a plugin update must not replace it).
assert ui_service.launcher_path().startswith(data)

# An existing launcher is never rebuilt: rebuilding changes its identity and drops the grant.
path = os.path.join(data, "bin", "aiw-ui-launcher")
os.makedirs(os.path.dirname(path))
open(path, "w").close()
calls = []
assert ui_service.build_launcher(path, run=lambda *a, **k: calls.append(a)) is False
assert calls == []
os.remove(path)

# When a compiler is present, the real launcher builds, spawns its command and passes its exit code.
if shutil.which("cc") and sys.platform == "darwin":
    assert ui_service.build_launcher(path) is True
    assert subprocess.run([path, "/bin/sh", "-c", "exit 7"]).returncode == 7
    out = subprocess.run([path, "/bin/echo", "hi"], capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout == "hi\n"
    assert subprocess.run([path], capture_output=True).returncode == 64  # no command

print("test_ui_service: ok")
