"""The skill registry: which plugin skill each UI step runs, and where it runs.

`skill_registry.json`, shipped beside this module, maps every step id (today's wire command
name, so stored sessions re-run unchanged) to `{plugin, skill, runs_in}`. It is the one place a
process skill is named: callers build `/<plugin>:<skill>` through `command`, never by hand.
The file is read and validated on every call (no cache), so an edit takes effect at once and a
test can point `REGISTRY_PATH` elsewhere. Stdlib only and no engine imports, so any module may
import it.
"""

from __future__ import annotations

import json
import os
import re

PLUGINS = ("blubird", "ai-workflow", "ai-workflow-personal")
RUNS_IN = ("docs", "issue", "any")
REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skill_registry.json")
_SKILL_RE = re.compile(r"^[a-z0-9-]+$")


def _check(step: str, e) -> dict:
    """One entry, validated: `{plugin, skill, runs_in}`, else ValueError naming the step."""
    if not isinstance(e, dict):
        raise ValueError(f"registry step {step}: entry is not an object")
    for k in ("plugin", "skill", "runs_in"):
        if k not in e:
            raise ValueError(f"registry step {step}: missing {k}")
    if e["plugin"] not in PLUGINS:
        raise ValueError(f"registry step {step}: unknown plugin {e['plugin']!r}")
    if not isinstance(e["skill"], str) or not _SKILL_RE.match(e["skill"]):
        raise ValueError(f"registry step {step}: bad skill name {e['skill']!r}")
    if e["runs_in"] not in RUNS_IN:
        raise ValueError(f"registry step {step}: unknown runs_in {e['runs_in']!r}")
    return {"plugin": e["plugin"], "skill": e["skill"], "runs_in": e["runs_in"]}


def steps() -> dict:
    """Every step, read from the file and validated: `{id: {plugin, skill, runs_in}}`."""
    try:
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        raise ValueError(f"registry {REGISTRY_PATH}: {exc}") from exc
    raw = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        raise ValueError(f"registry {REGISTRY_PATH}: no steps object")
    return {step: _check(step, e) for step, e in raw.items()}


def entry(step: str) -> dict:
    """The step's entry, else ValueError."""
    e = steps().get(step)
    if e is None:
        raise ValueError(f"unknown step: {step}")
    return e


def _command(e: dict) -> str:
    return f"/{e['plugin']}:{e['skill']}"


def command(step: str) -> str:
    """The slash command the step runs: `/<plugin>:<skill>`."""
    return _command(entry(step))


def view() -> dict:
    """The body of GET /api/registry: every entry plus its derived `command`."""
    return {"steps": {s: {**e, "command": _command(e)} for s, e in steps().items()}}
