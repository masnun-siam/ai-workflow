"""Repo skills win: which copy of a plugin skill a session runs, and how to recognise one.

A repo that keeps `<cwd>/.claude/skills/<name>/SKILL.md` runs its own copy as `/<name>`;
otherwise the plugin's `/ai-workflow:<name>` runs. `resolve` rewrites every plugin skill
command in a prompt to the copy that will run in `cwd`; `parse`/`is_skill` recognise a stored
command as a skill in either spelling.
"""

from __future__ import annotations

import os
import re

PLUGIN = "ai-workflow"
_SKILLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")
_COMMAND_RE = re.compile(r"^/(?:[\w-]+:)?([\w-]+)(?:\s+(.*))?$", re.DOTALL)


def names() -> set:
    """The plugin's skill names: folders under its skills/ that hold a SKILL.md. Listed per call."""
    try:
        entries = os.listdir(_SKILLS_DIR)
    except OSError:
        return set()
    return {e for e in entries if os.path.isfile(os.path.join(_SKILLS_DIR, e, "SKILL.md"))}


def has_copy(cwd, name: str) -> bool:
    """True when `<cwd>/.claude/skills/<name>/SKILL.md` is a readable file (symlinks followed)."""
    try:
        p = os.path.join(cwd, ".claude", "skills", name, "SKILL.md")
        return os.path.isfile(p) and os.access(p, os.R_OK)
    except (OSError, TypeError, ValueError):
        return False


def resolve(text, cwd):
    """Rewrite each plugin skill command in text to `/<name>` (repo copy) or `/ai-workflow:<name>`."""
    if not isinstance(text, str) or not text:
        return text
    known = sorted(names(), key=len, reverse=True)
    if not known:
        return text
    # A slash command stands after start/space/opening quote or bracket, and ends at end/space/
    # closing punctuation, or a `.`/`:` not followed by a word character (so not `/x.md`, `/x:y`).
    pattern = re.compile(
        r"(?<![^\s(\[\"'`])/(?:" + PLUGIN + r":)?(" + "|".join(map(re.escape, known)) + r")"
        r"(?=$|[\s,;!?)\]\"'`]|[.:](?!\w))"
    )
    copies: dict = {}

    def spell(m):
        name = m.group(1)
        if name not in copies:
            copies[name] = has_copy(cwd, name)
        return f"/{name}" if copies[name] else f"/{PLUGIN}:{name}"

    return pattern.sub(spell, text)


def parse(command):
    """(name, rest) for `/<name> …` or `/<prefix>:<name> …` at the start of command, else None."""
    m = _COMMAND_RE.match(command.lstrip()) if isinstance(command, str) else None
    return (m.group(1), m.group(2) or "") if m else None


def is_skill(command, name: str, arg=None) -> bool:
    """True when command is skill `name` in either spelling and, if arg is given, its rest is arg."""
    p = parse(command)
    return bool(p) and p[0] == name and (arg is None or p[1].strip() == arg)
