"""UI settings: the named claude commands a run can be launched with (`claude`, `cc masum`, ...).

The plain `claude` command is built in: always first, never removable, but its label is the
user's to rename (stored as `claude_label`). Stored in <data_dir>/ui_settings.json. A command is exec'd directly (no shell): `cc` is only an
interactive-shell alias, so a leading `cc` is rewritten to the `cc-profile` script it points at.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess

import shared

DEFAULT_CMD = "claude"
DEFAULT_VAULT = os.path.join("~", "Documents", "notes")  # the `notes` vault /dump and /prd write to
MAX_COMMANDS = 20


def _path() -> str:
    return os.path.join(shared.data_dir(), "ui_settings.json")


def _stored() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def vault_dir() -> str:
    """Absolute path of the Obsidian vault Flow reads notes from (read-only)."""
    return os.path.expanduser(_stored().get("vault_dir") or DEFAULT_VAULT)


def load() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        data = {}
    alias = data.get("claude_label")
    alias = alias if isinstance(alias, str) and alias.strip() else DEFAULT_CMD
    cmds = [{"label": alias, "cmd": DEFAULT_CMD, "builtin": True}]
    cmds += [{"label": c["label"], "cmd": c["cmd"]} for c in data.get("commands") or []
             if isinstance(c, dict) and isinstance(c.get("label"), str) and isinstance(c.get("cmd"), str)
             and c["label"] != alias]
    default = data.get("default")
    return {"commands": cmds, "default": default if any(c["label"] == default for c in cmds) else alias,
            "auto_grind": data.get("auto_grind") is True, "vault_dir": vault_dir()}


def argv(cmd: str) -> list:
    """Absolute argv prefix for a command string; ValueError if it is empty or not on PATH."""
    if not isinstance(cmd, str) or "\x00" in cmd:
        raise ValueError("command must be a string")
    try:
        toks = shlex.split(cmd)
    except ValueError as e:
        raise ValueError(f"cannot parse command: {e}") from None
    if not toks:
        raise ValueError("command must not be empty")
    if toks[0] == "cc":
        toks[0] = "cc-profile"
    exe = shutil.which(toks[0])
    if exe is None:
        raise ValueError(f"{toks[0]!r} not found on PATH")
    return [exe, *toks[1:]]


def validate(body) -> dict:
    """Return the cleaned settings dict, or raise ValueError."""
    if not isinstance(body, dict) or not isinstance(body.get("commands"), list):
        raise ValueError("commands must be a list")
    if len(body["commands"]) > MAX_COMMANDS:
        raise ValueError(f"at most {MAX_COMMANDS} commands")
    builtin = [c for c in body["commands"] if isinstance(c, dict) and c.get("builtin") is True]
    if len(builtin) > 1:
        raise ValueError("only one built-in command")
    alias = builtin[0].get("label") if builtin else DEFAULT_CMD
    if not isinstance(alias, str) or not alias.strip() or len(alias) > 40:
        raise ValueError("label must be a non-empty string of at most 40 characters")
    alias = alias.strip()
    cmds, seen = [], {alias}
    for c in body["commands"]:
        if isinstance(c, dict) and c.get("builtin") is True:
            continue  # its command is always `claude`; only the label is editable
        label = c.get("label") if isinstance(c, dict) else None
        cmd = c.get("cmd") if isinstance(c, dict) else None
        if not isinstance(label, str) or not label.strip() or len(label) > 40:
            raise ValueError("label must be a non-empty string of at most 40 characters")
        label = label.strip()
        if label in seen:
            raise ValueError(f"duplicate label: {label!r}")
        seen.add(label)
        if not isinstance(cmd, str) or len(cmd) > 200:
            raise ValueError("cmd must be a string of at most 200 characters")
        argv(cmd)
        cmds.append({"label": label, "cmd": cmd.strip()})
    default = body.get("default")
    if default is not None and default not in seen:
        raise ValueError("default must be one of the labels")
    vault = body.get("vault_dir", _stored().get("vault_dir"))  # a save that omits it keeps the stored one
    if vault is not None:
        if not isinstance(vault, str) or "\x00" in vault or len(vault) > 500:
            raise ValueError("vault_dir must be a path of at most 500 characters")
        vault = vault.strip() or None
        if vault and not os.path.isabs(os.path.expanduser(vault)):
            raise ValueError("vault_dir must be an absolute path (or start with ~)")
    return {"claude_label": alias, "commands": cmds, "default": None if default == alias else default,
            "auto_grind": body.get("auto_grind") is True, "vault_dir": vault}


def save(body) -> dict:
    shared.atomic_write_text(_path(), json.dumps(validate(body), indent=2))
    return load()


def default_cmd() -> str:
    s = load()
    return next((c["cmd"] for c in s["commands"] if c["label"] == s["default"]), DEFAULT_CMD)


def check_login(cmd: str) -> dict:
    """Run `<cmd> auth status --json`; {"ok": bool, "message": str}. Never raises."""
    try:
        p = subprocess.run([*argv(cmd), "auth", "status", "--json"], capture_output=True,
                           text=True, timeout=30)
        status = json.loads(p.stdout)
    except (ValueError, subprocess.TimeoutExpired, OSError) as e:
        return {"ok": False, "message": f"auth status check failed: {e}"}
    if not isinstance(status, dict) or status.get("loggedIn") is not True:
        return {"ok": False, "message": "not logged in"}
    who = status.get("email") or status.get("account") or ""
    return {"ok": True, "message": f"logged in {who}".strip()}


def config_dir(cmd: str) -> str:
    """Claude config dir an account command runs under (cc-profile <p> -> ~/.claude-profiles/<p>)."""
    toks = shlex.split(cmd)
    if toks[:1] in (["cc"], ["cc-profile"]) and len(toks) > 1:
        return os.path.expanduser(f"~/.claude-profiles/{toks[1]}")
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
