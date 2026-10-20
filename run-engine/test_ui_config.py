"""ui_config: notify settings keep secrets server-side and ui.json at 0600; peer-review overrides
lay over the shipped config; repos can be removed and their remotes checked."""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

tmp = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = tmp
for k in ("SERVER", "TOPIC", "TOKEN", "USER", "PASSWORD"):
    os.environ.pop(f"AIW_NTFY_{k}", None)
import dispatch  # noqa: E402
import peer_review  # noqa: E402
import ui_config  # noqa: E402
import ui_notify  # noqa: E402

pub = ui_config.save_notify(
    {"server": "https://ntfy.sh", "topic": "t1", "token": "sekret", "public_url": "https://mac.ts.net"}
)
assert pub["token_set"] and "sekret" not in json.dumps(pub), "the token never comes back"
assert os.stat(os.path.join(tmp, "ui.json")).st_mode & 0o777 == 0o600
assert ui_notify.load_config()["ntfy"]["token"] == "sekret", "ui_notify accepts the file"
pub = ui_config.save_notify({"topic": "t2", "token": None})
assert pub["topic"] == "t2" and pub["token_set"], "an unsent secret is kept"
pub = ui_config.save_notify({"token": ""})
assert not pub["token_set"], '"" clears it'
for bad in ({"server": "ftp://x"}, {"public_url": "javascript:x"}, {"topic": "a\nb"}):
    try:
        ui_config.save_notify(bad)
        raise AssertionError(bad)
    except ValueError:
        pass
print("ok  notify: secrets stay server-side, kept unless sent, cleared by empty; ui.json 0600; bad URLs refused")

base = ui_config.review_public()
assert not base["overridden"] and base["max_rounds"] == base["shipped"]["max_rounds"]
lens = next(iter(base["lenses"]))
r = ui_config.save_review({"max_rounds": 3, "default_lenses": [lens], "lenses": {lens: "Be terse."}})
assert r["overridden"] and r["max_rounds"] == 3 and r["lenses"][lens] == "Be terse."
import shared  # noqa: E402

full = shared.load_config()["peer_review"]["lenses"][lens]
assert full["prompt"] == "Be terse." and full["focus"], "the lens keeps its shipped focus"
assert peer_review.offers()["max_rounds"] == 3, "the panel uses the override"
other = [k for k in base["lenses"] if k != lens][0]
assert r["lenses"][other] == base["shipped"]["lenses"][other], "unedited prompts still come from the shipped file"
for bad in (
    {"max_rounds": 0, "default_lenses": [lens]},
    {"max_rounds": 3, "default_lenses": []},
    {"max_rounds": 3, "default_lenses": [lens], "lenses": {"nope": "x"}},
):
    try:
        ui_config.save_review(bad)
        raise AssertionError(bad)
    except ValueError:
        pass
with open(os.path.join(tmp, "config.json"), "w") as f:
    f.write("{broken")
assert peer_review.offers()["max_rounds"] == base["shipped"]["max_rounds"], "a broken override falls back"
assert not ui_config.save_review({"reset": True})["overridden"]
print("ok  peer review: overrides lay over the shipped config, validated, reset; a broken file falls back")

dispatch.register_checkout("o/a", "/p/a")
dispatch.register_checkout("local/b", "/p/b")
dispatch.register_checkout("o/gone", "/p/c")


def runner(args, timeout=None):
    if args[2] == "o/gone":
        return None, subprocess.CompletedProcess(
            args, 1, "", "GraphQL: Could not resolve to a Repository with the name 'o/gone'."
        )
    return {"nameWithOwner": args[2]}, subprocess.CompletedProcess(args, 0, "", "")


assert ui_config.check_repos(runner) == {
    "o/a": None,
    "local/b": "no GitHub remote",
    "o/gone": "GraphQL: Could not resolve to a Repository with the name 'o/gone'.",
}
assert ui_config.remove_repo("o/gone") == {"ok": True} and "o/gone" not in dispatch.read_checkouts()
try:
    ui_config.remove_repo("o/gone")
    raise AssertionError("removed twice")
except ValueError:
    pass
print("ok  repos: remote check per repo, remove unregisters (twice is an error)")
