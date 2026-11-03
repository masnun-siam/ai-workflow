"""Repo skills win: which copy of a plugin skill a session runs, and how to recognise one.

A repo that keeps `<cwd>/.claude/skills/<name>/SKILL.md` runs its own copy as `/<name>`;
otherwise the plugin's `/ai-workflow:<name>` runs. `resolve` rewrites every plugin skill
command in a prompt to the copy that will run in `cwd`; `parse`/`is_skill` recognise a stored
command as a skill in either spelling. `codex_prompt` inlines that copy's SKILL.md for a Codex
session, which has no plugin namespace.
"""

from __future__ import annotations

import json
import os
import re

PLUGIN = "ai-workflow"
PERSONAL_PLUGIN = "ai-workflow-personal"
PERSONAL = ("dump", "worklog", "sync-from-wasensi")  # skills that live in the personal plugin
_SKILLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")
_COMMAND_RE = re.compile(r"^/(?:[\w-]+:)?([\w-]+)(?:\s+(.*))?$", re.DOTALL)


def names() -> set:
    """The plugin's skill names: folders under its skills/ that hold a SKILL.md. Listed per call."""
    try:
        entries = os.listdir(_SKILLS_DIR)
    except OSError:
        return set()
    return {e for e in entries if os.path.isfile(os.path.join(_SKILLS_DIR, e, "SKILL.md"))}


def _installed_plugins() -> dict:
    """The `plugins` map of installed_plugins.json; unreadable or malformed means empty."""
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    try:
        with open(os.path.join(cfg, "plugins", "installed_plugins.json"), encoding="utf-8") as f:
            plugins = json.load(f).get("plugins")
    except (OSError, ValueError, AttributeError):
        return {}
    return plugins if isinstance(plugins, dict) else {}


def personal_plugin_installed() -> bool:
    """True when installed_plugins.json lists a plugin keyed `ai-workflow-personal@…`; unreadable means no."""
    return any(str(k).startswith(PERSONAL_PLUGIN + "@") for k in _installed_plugins())


def _personal_plugin_dir():
    """The personal plugin's `installPath` (first entry of its `ai-workflow-personal@…` key), else None."""
    for k, v in _installed_plugins().items():
        if str(k).startswith(PERSONAL_PLUGIN + "@"):
            p = v[0].get("installPath") if isinstance(v, list) and v and isinstance(v[0], dict) else None
            return p if isinstance(p, str) and p else None
    return None


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
    known = sorted(names() | set(PERSONAL), key=len, reverse=True)
    # A slash command stands after start/space/opening quote or bracket, and ends at end/space/
    # closing punctuation, or a `.`/`:` not followed by a word character (so not `/x.md`, `/x:y`).
    pattern = re.compile(
        r"(?<![^\s(\[\"'`])/(?:" + PLUGIN + r"(?:-personal)?:)?(" + "|".join(map(re.escape, known)) + r")"
        r"(?=$|[\s,;!?)\]\"'`]|[.:](?!\w))"
    )
    copies: dict = {}
    personal = personal_plugin_installed()

    def spell(m):
        name = m.group(1)
        if name in PERSONAL:  # never fall back to a team command that does not exist
            return f"/{PERSONAL_PLUGIN}:{name}" if personal else m.group(0)
        if name not in copies:
            copies[name] = has_copy(cwd, name)
        return f"/{name}" if copies[name] else f"/{PLUGIN}:{name}"

    return pattern.sub(spell, text)


_SPELLED_RE = re.compile(r"^/(?:(" + PLUGIN + r"(?:-personal)?):)?([\w-]+)(?:\s+(.*))?$", re.DOTALL)


def _skill_body(path: str) -> str:
    """SKILL.md text without its leading `---` frontmatter block (kept whole when unclosed)."""
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    if lines[0].rstrip("\r") == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r") == "---"), None)
        if end is not None:
            lines = lines[end + 1 :]
    return "\n".join(lines).strip("\r\n")


def codex_prompt(text, cwd):
    """The prompt a Codex session gets for text: the resolved skill's SKILL.md inlined with its base
    directory and arguments, as Claude Code builds it; any other text is `resolve(text, cwd)`."""
    r = resolve(text, cwd)
    m = _SPELLED_RE.match(r.lstrip()) if isinstance(r, str) and r else None
    if not m:
        return r
    prefix, name, args = m.groups()
    # resolve's spelling says which copy runs: no prefix = repo copy, ai-workflow: = this plugin.
    if not prefix and name in names() and name not in PERSONAL and has_copy(cwd, name):
        folder = os.path.join(cwd, ".claude", "skills", name)
    elif prefix == PLUGIN and name in names() and name not in PERSONAL:
        folder = os.path.join(_SKILLS_DIR, name)
    elif prefix == PERSONAL_PLUGIN and name in PERSONAL and (home := _personal_plugin_dir()):
        folder = os.path.join(home, "skills", name)
    else:
        return r
    try:
        body = _skill_body(os.path.join(folder, "SKILL.md"))
    except (OSError, UnicodeDecodeError):
        return r
    args = (args or "").strip()
    return f"Base directory for this skill: {folder}\n\n{body}" + (f"\n\nARGUMENTS: {args}" if args else "")


def parse(command):
    """(name, rest) for `/<name> …` or `/<prefix>:<name> …` at the start of command, else None."""
    m = _COMMAND_RE.match(command.lstrip()) if isinstance(command, str) else None
    return (m.group(1), m.group(2) or "") if m else None


def is_skill(command, name: str, arg=None) -> bool:
    """True when command is skill `name` in either spelling and, if arg is given, its rest is arg."""
    p = parse(command)
    return bool(p) and p[0] == name and (arg is None or p[1].strip() == arg)
