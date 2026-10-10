"""Tests for ui_options: plain asserts, run with `python3 test_ui_options.py`."""
import json
import os
import subprocess
import sys
import tempfile

os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ui_options as o  # noqa: E402
import ui_sessions  # noqa: E402
from shared import data_dir, run_dir_for  # noqa: E402


def raises(fn, *a):
    try:
        fn(*a)
    except ValueError:
        return True
    return False


assert raises(o.validate, {})
assert raises(o.validate, {"review": True})
assert raises(o.validate, {"auto_grind": "no"})
assert o.validate({"review": False, "auto_grind": True, "junk": 1}) == {"review": False, "auto_grind": True}
print("  ok  validate: review can only go off, auto_grind is a bool, unknown keys dropped")

assert o.skip_review("o", "r", 5) == "not_started"
run_dir = run_dir_for(os.path.join(data_dir(), "runs"), "o/r", 5)
route = os.path.join(os.path.dirname(os.path.abspath(__file__)), "route.py")
subprocess.run([sys.executable, route, "init", run_dir, "--issue", "5", "--mode", "default"], check=True, capture_output=True)
assert o.skip_review("o", "r", 5) == "applied"
assert o.skip_review("o", "r", 5) == "unchanged"
late = run_dir_for(os.path.join(data_dir(), "runs"), "o/r", 6)
subprocess.run([sys.executable, route, "init", late, "--issue", "6", "--mode", "default"], check=True, capture_output=True)
led = json.load(open(os.path.join(late, "run.json")))
led["currentIndex"] = led["stations"].index("reviewer")
json.dump(led, open(os.path.join(late, "run.json"), "w"))
assert o.skip_review("o", "r", 6) == "too_late"
print("  ok  skip_review: not_started / applied / unchanged / too_late")

rec = ui_sessions.create("/run-issue 5", "/x", {"owner": "o", "repo": "r", "issue": 5})
assert o.session_of("o", "r", 5)["id"] == rec["id"] and o.session_of("o", "r", 9) is None
assert o.apply("o", "r", 5, {"auto_grind": False}) == {"auto_grind": "applied"}
assert ui_sessions.load(rec["id"])["auto_grind"] is False
assert o.apply("o", "r", 9, {"auto_grind": False}) == {"auto_grind": "no_session"}
assert o.apply("o", "r", 5, {"review": False, "auto_grind": True}, session_id=rec["id"]) == {"review": "unchanged", "auto_grind": "applied"}
print("  ok  apply: explicit auto_grind on the newest run-issue session, per-field outcome")
