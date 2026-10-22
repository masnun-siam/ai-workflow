#!/usr/bin/env python3
"""Self-check for `aiw grind-mode`. `python3 run-engine/test_grind_mode_cli.py` — exit 0 = green."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
AIW = os.path.join(os.path.dirname(HERE), "bin", "aiw")
d = tempfile.mkdtemp()
env = {**os.environ, "CLAUDE_PLUGIN_DATA": d}


# aiw grind-mode prints the stored mode (deep by default), which /pr-grind reads each round
mode = subprocess.run([AIW, "grind-mode"], env=env, capture_output=True, text=True)
assert mode.returncode == 0 and mode.stdout.strip() == "deep", mode
with open(os.path.join(d, "ui_settings.json"), "w") as f:
    json.dump({"grind_mode": "simple"}, f)
assert subprocess.run([AIW, "grind-mode"], env=env, capture_output=True, text=True).stdout.strip() == "simple"
print("grind-mode cli: 2 checks passed")
