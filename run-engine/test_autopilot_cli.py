#!/usr/bin/env python3
"""Self-check for `aiw autopilot`. `python3 run-engine/test_autopilot_cli.py` — exit 0 = green."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
AIW = os.path.join(os.path.dirname(HERE), "bin", "aiw")
d = tempfile.mkdtemp()
env = {**os.environ, "CLAUDE_PLUGIN_DATA": d}


def aiw(*a):
    return subprocess.run([AIW, "autopilot", *a], env=env, capture_output=True, text=True)


def stored():
    with open(os.path.join(d, "ui_settings.json")) as f:
        return json.load(f)["autopilot"]


assert aiw("o/r", "12", "on").returncode == 0 and stored() == {"o/r": [12]}
assert aiw("o/r", "12", "off").returncode == 0 and stored() == {"o/r": []}
for args in (("o/r", "abc", "on"), ("nope", "12", "on"), ("o/r", "0", "on")):
    p = aiw(*args)
    assert p.returncode != 0 and len(p.stderr.strip().splitlines()) == 1, (args, p.stderr)
print("autopilot cli: 5 checks passed")

# aiw grind-mode prints the stored mode (deep by default), which /pr-grind reads each round
mode = subprocess.run([AIW, "grind-mode"], env=env, capture_output=True, text=True)
assert mode.returncode == 0 and mode.stdout.strip() == "deep", mode
with open(os.path.join(d, "ui_settings.json")) as f:
    data = json.load(f)
with open(os.path.join(d, "ui_settings.json"), "w") as f:
    json.dump({**data, "grind_mode": "simple"}, f)
assert subprocess.run([AIW, "grind-mode"], env=env, capture_output=True, text=True).stdout.strip() == "simple"
