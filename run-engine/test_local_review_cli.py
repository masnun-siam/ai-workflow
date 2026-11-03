#!/usr/bin/env python3
"""Self-check for `aiw local-review`. `python3 run-engine/test_local_review_cli.py` — exit 0 = green."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
AIW = os.path.join(os.path.dirname(HERE), "bin", "aiw")
d = tempfile.mkdtemp()
env = {**os.environ, "CLAUDE_PLUGIN_DATA": d}
path = os.path.join(d, "ui_settings.json")


def run():
    return subprocess.run([AIW, "local-review"], env=env, capture_output=True, text=True)


# aiw local-review prints the stored mode (single by default), which /implement-issue reads at step 12
r = run()
assert r.returncode == 0 and r.stdout == "single\n", r
with open(path, "w") as f:
    json.dump({"review_mode": "loop"}, f)
r = run()
assert r.returncode == 0 and r.stdout == "loop\n", r  # no restart: read on every call
for raw in ("{broken", json.dumps({"review_mode": "fast"}), json.dumps({"review_mode": True}), "[1]"):
    with open(path, "w") as f:
        f.write(raw)
    r = run()
    assert r.returncode == 0 and r.stdout == "single\n", (raw, r)
print("local-review cli: 6 checks passed")
