"""UI settings: the named claude commands a run can be launched with (`claude`, `cc masum`, ...).

Stored in <data_dir>/ui_settings.json. A command is exec'd directly (no shell): `cc` is only an
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
MAX_COMMANDS = 20


def _path() -> str:
    return os.path.join(shared.data_dir(), "ui_settings.json")


def load() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("commands"), list):
        return {"commands": [], "default": None}
    cmds = [{"label": c["label"], "cmd": c["cmd"]} for c in data["commands"]
            if isinstance(c, dict) and isinstance(c.get("label"), str) and isinstance(c.get("cmd"), str)]
    default = data.get("default")
    return {"commands": cmds, "default": default if any(c["label"] == default for c in cmds) else None}


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
    cmds, seen = [], set()
    for c in body["commands"]:
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
    return {"commands": cmds, "default": default}


def save(body) -> dict:
    clean = validate(body)
    shared.atomic_write_text(_path(), json.dumps(clean, indent=2))
    return clean


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
