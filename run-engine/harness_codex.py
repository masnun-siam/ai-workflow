"""The Codex adapter: `codex exec --json` behind the harness contract. The parser maps one line to UI events
(the `ui_events` shapes, plus `session_id` and `limit`)."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess

import repo_skills
import ui_settings
from ui_events import _n

ID = "codex"
CUMULATIVE_USAGE = True  # `turn.completed` usage covers the whole thread, not one run
BYPASS_FLAG = "--dangerously-bypass-approvals-and-sandbox"
_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Claude Code tool names the skills use, told to Codex on every fresh start that carries instructions.
TOOL_MAPPING = (
    "Claude Code tool names in skills map as follows: AskUserQuestion → `aiw ask`; a slash command for a plugin "
    "skill → read `<plugin>/skills/<name>/SKILL.md` (or the repo copy at `.claude/skills/<name>/SKILL.md` when it "
    "exists) and follow it; Agent/subagent or SendMessage → do the work yourself in this session; "
    "ScheduleWakeup/Monitor → write the state the skill asks for and end the turn."
).replace("<plugin>", _PLUGIN_DIR)

# Copied from ui_runner._LIMIT_RE so the parser does not import the runner. G1 replaces it.
LIMIT_RE = re.compile(r"usage limit|limit reached|rate.?limit|hit your limit", re.I)

CODEX_EFFORTS = ("low", "medium", "high", "xhigh")  # the `codex` entry of ui_settings.HARNESSES
EFFORT_KEY = "model_reasoning_effort"
NOTE_MAX = 80  # characters of an unsupported value echoed in the note
_UNSET = (None, "", "default")


def _login(cmd: str):
    """(exe, None) when logged in, else (None, the user message). Only the exit code of `login status` is read."""
    try:
        exe = ui_settings.argv(cmd)
    except ValueError as e:
        return None, ("codex CLI not found on PATH" if cmd == "codex" else f"codex command {cmd!r} unusable: {e}")
    msg = f"codex CLI is not logged in, run `{cmd} login`"
    try:
        p = subprocess.run([*exe, "login", "status"], capture_output=True, text=True, errors="replace", timeout=30)
    except (subprocess.TimeoutExpired, OSError) as e:
        return None, f"{msg} (login status check failed: {e})"
    if p.returncode == 0:
        return exe, None
    said = next((ln.strip() for out in (p.stderr, p.stdout) for ln in (out or "").splitlines() if ln.strip()), None)
    return None, f"{msg} ({said})" if said else msg


def preflight(cmd: str) -> list:
    """argv prefix of cmd, after checking it is logged in; raises harness.LoginError with the user message."""
    from harness import LoginError  # noqa: PLC0415 - harness imports this module

    exe, msg = _login(cmd)
    if msg:
        raise LoginError(msg)
    return exe


def check_login(cmd: str) -> dict:
    """{"ok": bool, "message": str} for Settings' check; never raises."""
    _, msg = _login(cmd)
    return {"ok": False, "message": msg} if msg else {"ok": True, "message": "logged in"}


def model_flags(model, effort, models) -> tuple:
    """(flags, notes): a model saved on the account and a Codex effort become flags; any other value falls back
    to Codex's default with a note. Only listed values ever reach argv."""
    flags, notes = [], []
    if model not in _UNSET:
        if model in models:
            flags.append(f"--model={model}")
        else:
            notes.append(f"`{str(model)[:NOTE_MAX]}` is not a Codex model; ran on Codex's default")
    if effort not in _UNSET:
        if effort in CODEX_EFFORTS:
            flags += ["-c", f"{EFFORT_KEY}={effort}"]
        else:
            notes.append(f"`{str(effort)[:NOTE_MAX]}` is not a Codex effort; ran on Codex's default")
    return flags, notes


def _rec_flags(rec, model=None, effort=None, run_model=None, run_effort=None) -> tuple:
    """model_flags for a session: a direct value (given, else recorded) wins over the user's pick (given, else
    recorded); models of the account it runs on."""
    rec = rec or {}
    return model_flags(
        model or rec.get("direct_model") or run_model or rec.get("run_model"),
        effort or rec.get("direct_effort") or run_effort or rec.get("run_effort"),
        ui_settings.models_of(rec["claude_cmd"]) if rec.get("claude_cmd") else [],
    )


def run_note(rec):
    """The fallback note for the session record, None when nothing fell back."""
    return "; ".join(_rec_flags(rec)[1]) or None


def start_argv(
    exe,
    prompt,
    *,
    instructions=(),
    agent=None,
    model=None,
    effort=None,
    run_model=None,
    run_effort=None,
    allowed_tools=None,
    rec=None,
):
    """(argv, sent_prompt) for a fresh start. Codex has no system prompt flag: instructions and the tool-name
    mapping lead the first prompt. agent/allowed_tools are #881's."""
    sent = "\n\n".join([*instructions, TOOL_MAPPING, prompt]) if instructions else prompt
    flags = _rec_flags(rec, model, effort, run_model, run_effort)[0]
    return [*exe, "exec", "--json", BYPASS_FLAG, "--skip-git-repo-check", *flags, sent], sent


def resume_argv(exe, session_id, prompt, *, rec):
    """(argv, sent_prompt) continuing thread session_id with prompt alone (the first prompt carried the rest)."""
    flags = _rec_flags(rec)[0]
    return [*exe, "exec", "resume", "--json", BYPASS_FLAG, "--skip-git-repo-check", *flags, session_id, prompt], prompt


def skill_text(text, cwd) -> str:
    return repo_skills.codex_prompt(text, cwd)


def resume_command(cmd, path, session_id):
    """The "resume in terminal" command; every word quoted. A leading `cc` stays: the user's shell has the alias."""
    if not path or not session_id:
        return None
    words = " ".join(shlex.quote(w) for w in shlex.split(cmd))
    return f"cd {shlex.quote(path)} && {words} resume {shlex.quote(session_id)}"


def parse_line(line) -> list:
    try:
        ev = json.loads(line)
    except ValueError:  # includes UnicodeDecodeError
        return []
    if not isinstance(ev, dict):
        return []
    kind = ev.get("type")
    if kind == "thread.started":
        tid = ev.get("thread_id")
        return [{"kind": "session_id", "id": tid, "model": None}] if isinstance(tid, str) else []
    if kind == "item.completed":
        return _item(ev.get("item"))
    if kind == "turn.completed":
        return [{"kind": "result", "cost": None, "is_error": False, "text": None, "tokens": _tokens(ev.get("usage"))}]
    if kind == "turn.failed":
        err = ev.get("error")
        return _failed(err.get("message") if isinstance(err, dict) else None)
    if kind == "error":
        return _failed(ev.get("message"))
    return []


def _item(item) -> list:
    if not isinstance(item, dict) or not isinstance(item.get("type"), str):
        return []
    if item["type"] == "agent_message":
        return [{"kind": "text", "text": item["text"]}] if isinstance(item.get("text"), str) else []
    if item["type"] == "command_execution":
        cmd = item.get("command")
        return [{"kind": "tool", "name": "Bash", "input": {"command": cmd}}] if isinstance(cmd, str) else []
    return [{"kind": "tool", "name": item["type"], "input": item}]


def _tokens(usage):
    """OpenAI usage: `input_tokens` is the whole prompt, `cached_input_tokens` the cached part of it,
    which is what `ui_events.tokens_of` means by input and cached. PROVISIONAL until the real fixture."""
    if not isinstance(usage, dict):
        return None
    tokens = {
        "input": _n(usage.get("input_tokens")),
        "cached": _n(usage.get("cached_input_tokens")),
        "output": _n(usage.get("output_tokens")),
    }
    return tokens if any(tokens.values()) else None


def _failed(message) -> list:
    text = message if isinstance(message, str) else None
    out = [{"kind": "result", "cost": None, "is_error": True, "text": text, "tokens": None}]
    if text and LIMIT_RE.search(text):
        out.append({"kind": "limit", "resets_at": None, "type": None, "info": None})
    return out
