"""The Claude adapter: today's `claude --print --output-format stream-json` behaviour behind the harness contract."""

from __future__ import annotations

import json
import subprocess

import repo_skills
import ui_settings

ID = "claude"
HEADLESS_PROMPT = (
    "Headless run: ask via aiw ask, never AskUserQuestion. Gate questions go through "
    "`aiw ask --json '<AskUserQuestion input>'`; then end your turn. "
    "Never call ScheduleWakeup: a pending wakeup keeps this process alive, and the UI cannot take "
    "an answer until it exits."
)
CLAUDE_ARGS = ["--print", "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions"]


def preflight(cmd: str) -> list:
    """argv prefix of cmd, after checking it is logged in; raises harness.LoginError with the user message."""
    from harness import LoginError  # noqa: PLC0415 - harness imports this module

    try:
        exe = ui_settings.argv(cmd)
    except ValueError as e:
        raise LoginError(
            f"claude command {cmd!r} unusable: {e}"
            if cmd != ui_settings.DEFAULT_CMD
            else "claude CLI not found on PATH"
        ) from None
    login_msg = (
        f"claude CLI is not logged in, run `{cmd} auth login`"
        if cmd != ui_settings.DEFAULT_CMD
        else "claude CLI is not logged in, run `claude auth login`"
    )
    try:
        p = subprocess.run([*exe, "auth", "status", "--json"], capture_output=True, text=True, timeout=30)
        status = json.loads(p.stdout)
    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        raise LoginError(f"{login_msg} (auth status check failed: {e})") from None
    if not isinstance(status, dict) or status.get("loggedIn") is not True:
        raise LoginError(login_msg)
    return exe


def check_login(cmd: str) -> dict:
    """Run `<cmd> auth status --json`; {"ok": bool, "message": str}. Never raises."""
    try:
        p = subprocess.run(
            [*ui_settings.argv(cmd), "auth", "status", "--json"], capture_output=True, text=True, timeout=30
        )
        status = json.loads(p.stdout)
    except (ValueError, subprocess.TimeoutExpired, OSError) as e:
        return {"ok": False, "message": f"auth status check failed: {e}"}
    if not isinstance(status, dict) or status.get("loggedIn") is not True:
        return {"ok": False, "message": "not logged in"}
    who = status.get("email") or status.get("account") or ""
    return {"ok": True, "message": f"logged in {who}".strip()}


def _base_args(allowed_tools) -> list:
    """The permission bypass, unless there is an allow-list (one comma-joined value: the flag is variadic)."""
    if not allowed_tools:
        return CLAUDE_ARGS
    safe = [a for a in CLAUDE_ARGS if a != "--dangerously-skip-permissions"]
    return [*safe, "--allowedTools", ",".join(allowed_tools)]


def _run_flags(run_model, run_effort) -> list:
    return [*(["--model", run_model] if run_model else []), *(["--effort", run_effort] if run_effort else [])]


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
    """(argv, sent_prompt) for a fresh start. effort/model: direct (dispatch, lenses); run_*: the Start dialog's."""
    allowed_tools = allowed_tools or (rec or {}).get("allowed_tools")
    argv = [
        *exe,
        *_base_args(allowed_tools),
        *(["--append-system-prompt", "\n\n".join(instructions)] if instructions else []),
        *(["--effort", effort] if effort else []),
        *(["--agent", agent] if agent else []),
        *(["--model", model] if model else []),
        *_run_flags(run_model, run_effort),
        prompt,
    ]
    return argv, prompt


def resume_argv(exe, session_id, prompt, *, rec):
    """(argv, sent_prompt) continuing session_id; the direct --agent/--model are not re-added."""
    argv = [
        *exe,
        *_base_args(rec.get("allowed_tools")),
        "--append-system-prompt",
        HEADLESS_PROMPT,
        *_run_flags(rec.get("run_model"), rec.get("run_effort")),
        "--resume",
        session_id,
        prompt,
    ]
    return argv, prompt


def skill_text(text, cwd) -> str:
    return repo_skills.resolve(text, cwd)
