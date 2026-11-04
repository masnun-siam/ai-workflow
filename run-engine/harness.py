"""Harness registry: one adapter module per harness (claude, codex).

An adapter owns everything harness-specific: the login check, the start/resume argv and the skill text.
The runner picks it from the session's recorded `harness`; a record without one is Claude.
"""

from __future__ import annotations

import harness_claude
import harness_codex
import ui_settings

_ADAPTERS = {"claude": harness_claude, "codex": harness_codex}


class LoginError(Exception):
    """Raised by an adapter's preflight; the message is shown to the user as is."""


def get(harness_id: str):
    try:
        return _ADAPTERS[harness_id]
    except (KeyError, TypeError):
        raise ValueError(f"unknown harness {harness_id!r}") from None


def for_record(rec):
    return get((rec or {}).get("harness") or "claude")


def for_cmd(cmd: str):
    return get(ui_settings.harness_of(cmd))
