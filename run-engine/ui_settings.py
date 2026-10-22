"""UI settings: the named claude commands a run can be launched with (`claude`, `cc masum`, ...).

The plain `claude` command is built in: always first, never removable, but its label is the
user's to rename (stored as `claude_label`). Stored in <data_dir>/ui_settings.json. A command is exec'd directly (no shell): `cc` is only an
interactive-shell alias, so a leading `cc` is rewritten to the `cc-profile` script it points at.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess

import dispatch
import shared

DEFAULT_CMD = "claude"
DEFAULT_VAULT = os.path.join("~", "Documents", "notes")  # the `notes` vault /dump and /create-prd write to
MAX_COMMANDS = 20
DEFAULT_CAP = 2
SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
GRIND_MODES = ("deep", "simple")  # simple: /pr-grind stops once the PR is approved


def _path() -> str:
    return os.path.join(shared.data_dir(), "ui_settings.json")


def _stored() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def grind_mode() -> str:
    """deep (the default) or simple, for every /pr-grind loop; the skill reads it each round (`aiw grind-mode`)."""
    m = _stored().get("grind_mode")
    return m if m in GRIND_MODES else "deep"


def vault_dir() -> str:
    """Absolute path of the Obsidian vault Flow reads notes from (read-only)."""
    return os.path.expanduser(_stored().get("vault_dir") or DEFAULT_VAULT)


def _repo(d) -> dict:
    d = d if isinstance(d, dict) else {}
    cap = d.get("autopilot_cap")
    ch = d.get("slack_channel")
    return {
        "auto_grind": d.get("auto_grind") is True,
        "autopilot_cap": cap if type(cap) is int and 1 <= cap <= 5 else DEFAULT_CAP,
        "slack_channel": ch if isinstance(ch, str) else "",
    }


def _epics(v) -> list:
    return sorted({e for e in v if type(e) is int and e > 0}) if isinstance(v, list) else []


def _migrate(data: dict) -> dict:
    """Drop the legacy global auto_grind, seeding it onto every registered repo once."""
    if "auto_grind" not in data:
        return data
    legacy = data.pop("auto_grind") is True
    repos = data["repos"] = dict(data.get("repos") or {})
    for slug in dispatch.read_checkouts():
        repos.setdefault(slug, {"auto_grind": legacy})
    try:
        shared.atomic_write_text(_path(), json.dumps(data, indent=2))
    except OSError:
        pass
    return data


def repo_settings(slug: str) -> dict:
    """Per-repo settings with defaults, plus its autopilot epic list."""
    d = _migrate(_stored())
    return {
        **_repo((d.get("repos") or {}).get(slug)),
        "autopilot": _epics((d.get("autopilot") or {}).get(slug)),
        "issue_grind": _issue_grind().get(str(slug).lower(), {}),
    }


def _issue_grind_path() -> str:
    # its own file: save() rewrites ui_settings.json from the Settings form, which never sends these
    return os.path.join(shared.data_dir(), "issue_grind.json")


def _issue_grind() -> dict:
    """{owner/repo lowercased: {issue: bool}}: issues whose grinding was switched in the UI."""
    try:
        with open(_issue_grind_path(), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        k: {int(n): v for n, v in m.items() if str(n).isdigit() and isinstance(v, bool)}
        for k, m in raw.items()
        if isinstance(m, dict)
    }


def set_issue_grind(slug: str, issue: int, on: bool) -> dict:
    """Switch one issue's grinding; the other issues keep following the repo's auto_grind."""
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise ValueError("repo must be owner/repo")
    if type(issue) is not int or issue < 1 or type(on) is not bool:
        raise ValueError("issue must be a number and on must be true or false")
    all_ = _issue_grind()
    all_.setdefault(slug.lower(), {})[issue] = on
    shared.atomic_write_text(_issue_grind_path(), json.dumps(all_, indent=2))
    return all_[slug.lower()]


def set_autopilot(slug: str, epic: int, on: bool) -> list:
    """Add or remove an epic from a repo's autopilot list; returns the new list."""
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise ValueError("repo must be owner/repo")
    if type(epic) is not int or epic < 1:
        raise ValueError("epic must be a number")
    d = _migrate(_stored())
    ap = d["autopilot"] = dict(d.get("autopilot") or {})
    epics = set(_epics(ap.get(slug)))
    epics.add(epic) if on else epics.discard(epic)
    ap[slug] = sorted(epics)
    shared.atomic_write_text(_path(), json.dumps(d, indent=2))
    return ap[slug]


def load() -> dict:
    data = _migrate(_stored())
    stored_repos = data.get("repos") if isinstance(data.get("repos"), dict) else {}
    registered = dispatch.read_checkouts()
    slugs = [*registered, *(k for k in stored_repos if k not in registered)]
    ap = data.get("autopilot") if isinstance(data.get("autopilot"), dict) else {}
    alias = data.get("claude_label")
    alias = alias if isinstance(alias, str) and alias.strip() else DEFAULT_CMD
    cmds = [{"label": alias, "cmd": DEFAULT_CMD, "builtin": True}]
    cmds += [
        {"label": c["label"], "cmd": c["cmd"]}
        for c in data.get("commands") or []
        if isinstance(c, dict)
        and isinstance(c.get("label"), str)
        and isinstance(c.get("cmd"), str)
        and c["label"] != alias
    ]
    default = data.get("default")
    return {
        "commands": cmds,
        "default": default if any(c["label"] == default for c in cmds) else alias,
        "repos": {k: _repo(stored_repos.get(k)) for k in slugs},
        "autopilot": {k: _epics(v) for k, v in ap.items()},
        "vault_dir": vault_dir(),
        "grind_mode": grind_mode(),
    }


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
    if isinstance(body, dict) and "commands" not in body:  # a partial save (a board's per-repo PUT) keeps the rest
        cur = load()
        body = {"commands": cur["commands"], "default": cur["default"], **body}
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
    mode = body.get("grind_mode", grind_mode())  # a save that omits it keeps the stored one
    if mode not in GRIND_MODES:
        raise ValueError("grind_mode must be deep or simple")
    stored = _migrate(_stored())
    sent = body.get("repos", {})
    if not isinstance(sent, dict):
        raise ValueError("repos must be an object")
    repos = {**(stored.get("repos") or {}), **sent}  # an entry replaces that repo's; the others stay
    clean_repos = {}
    for slug, r in repos.items():
        if not SLUG_RE.match(str(slug)) or not isinstance(r, dict):
            raise ValueError("repos must map owner/repo to an object")
        cap = r.get("autopilot_cap", DEFAULT_CAP)
        if type(cap) is not int or not 1 <= cap <= 5:
            raise ValueError("autopilot_cap must be an integer from 1 to 5")
        ch = r.get("slack_channel", "")
        if not isinstance(ch, str) or len(ch) > 100:
            raise ValueError("slack_channel must be a string of at most 100 characters")
        clean_repos[slug] = {
            "auto_grind": r.get("auto_grind") is True,
            "autopilot_cap": cap,
            "slack_channel": ch.strip(),
        }
    autopilot = body.get("autopilot", stored.get("autopilot") or {})
    if not isinstance(autopilot, dict) or not all(
        SLUG_RE.match(str(k)) and isinstance(v, list) and all(type(e) is int and e > 0 for e in v)
        for k, v in autopilot.items()
    ):
        raise ValueError("autopilot must map owner/repo to a list of epic numbers")
    return {
        "claude_label": alias,
        "commands": cmds,
        "default": None if default == alias else default,
        "repos": clean_repos,
        "autopilot": {k: _epics(v) for k, v in autopilot.items()},
        "vault_dir": vault,
        "grind_mode": mode,
    }


def save(body) -> dict:
    shared.atomic_write_text(_path(), json.dumps(validate(body), indent=2))
    return load()


def default_cmd() -> str:
    s = load()
    return next((c["cmd"] for c in s["commands"] if c["label"] == s["default"]), DEFAULT_CMD)


def check_login(cmd: str) -> dict:
    """Run `<cmd> auth status --json`; {"ok": bool, "message": str}. Never raises."""
    try:
        p = subprocess.run([*argv(cmd), "auth", "status", "--json"], capture_output=True, text=True, timeout=30)
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
