"""Lane runners for dispatch_run: herdr tabs or headless UI sessions, one interface. Stdlib only.

    start(lane, prompt, dispatch) -> handle     send(handle, text)     close(handle)
    status(handle) -> (agent, limited_until)    agent: working | idle | blocked | gone
    read(handle) -> text

Every lane session runs with --dangerously-skip-permissions and the dispatch's model and effort.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

import dispatch
from shared import run

# Claude's usage-limit line, e.g. "5-hour limit reached ∙ resets 3pm" or "Your limit will reset at 3:30pm"
_LIMIT_RE = re.compile(r"usage limit|limit reached|hit your limit", re.I)
_RESET_RE = re.compile(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d\d))?\s*(am|pm)", re.I)
LIMIT_FALLBACK_SECONDS = 900  # no reset time in the text: look again in 15 min
_MONITORS_RE = re.compile(r"\d+ (monitor|shell)")


def limit_reset(text: str, now: datetime | None = None):
    """Epoch of the reset named in a usage-limit message in `text` (local time), else None."""
    tail = "\n".join((text or "").splitlines()[-15:])
    if not _LIMIT_RE.search(tail):
        return None
    now = now or datetime.now()
    m = _RESET_RE.search(tail)
    if not m:
        return (now + timedelta(seconds=LIMIT_FALLBACK_SECONDS)).timestamp()
    h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
    at = now.replace(hour=h, minute=int(m.group(2) or 0), second=0, microsecond=0)
    return (at if at > now else at + timedelta(days=1)).timestamp()


def claude_args(d: dict) -> list:
    s = d.get("settings") or {}
    return [
        "--dangerously-skip-permissions",
        *(["--model", s["model"]] if s.get("model") else []),
        *(["--effort", s["effort"]] if s.get("effort") else []),
    ]


def checkout(repo: str) -> str:
    path = next((p for k, p in dispatch.read_checkouts().items() if k.lower() == repo.lower()), None)
    if not isinstance(path, str):
        raise ValueError(f"no local checkout registered for {repo}")
    return path


def _find(obj, name):
    """First value of key `name` anywhere in parsed JSON."""
    if isinstance(obj, dict):
        if name in obj:
            return obj[name]
        obj = list(obj.values())
    if isinstance(obj, list):
        for v in obj:
            r = _find(v, name)
            if r is not None:
                return r
    return None


class Herdr:
    """Lanes as herdr tabs in one workspace. ponytail: herdr's JSON shapes are read loosely (`_find`);
    pin them with a fixture once herdr documents its API."""

    def __init__(self, workspace, cli=None):
        self.workspace = workspace
        self.cli = cli or (lambda argv, timeout=60: run(["herdr", *argv], timeout=timeout))

    def _ok(self, argv, timeout=60):
        p = self.cli(argv, timeout=timeout)
        if p.returncode != 0:
            raise RuntimeError(f"herdr {' '.join(argv[:2])} failed: {(p.stderr or p.stdout or '').strip()[:200]}")
        try:
            return json.loads(p.stdout or "null")
        except ValueError:
            return p.stdout or ""

    def start(self, lane, prompt, d):
        label = f"issue-{lane['n']}"
        made = self._ok(
            [
                "tab",
                "create",
                *(["--workspace", self.workspace] if self.workspace else []),
                "--cwd",
                checkout(lane["repo"]),
                "--label",
                label,
                "--no-focus",
            ]
        )
        tab = _find(made, "tab_id")
        pane = _find(made, "pane_id") if not isinstance(made, str) else (made.split() or [""])[-1]
        if not pane:
            raise RuntimeError("herdr tab create returned no pane id")
        name = f"aiw-{d['id']}-{lane['n']}"
        self._ok(
            ["agent", "start", name, "--kind", "claude", "--pane", pane, "--timeout", "120000", "--", *claude_args(d)],
            timeout=150,
        )
        h = {"tab": tab, "pane": pane, "agent": name}
        self.send(h, prompt)
        return h

    def send(self, h, text):
        # herdr cuts a long send-text; prompts here stay well under its ~500-character limit
        self._ok(["agent", "prompt", h["agent"], text[:480]])

    def read(self, h) -> str:
        r = self._ok(["pane", "read", h["pane"], "--lines", "200"])
        return r if isinstance(r, str) else (_find(r, "text") or json.dumps(r))

    def status(self, h):
        tabs = (
            _find(self._ok(["tab", "list", *(["--workspace", self.workspace] if self.workspace else [])]), "tabs") or []
        )
        t = next((t for t in tabs if t.get("tab_id") == h.get("tab")), None)
        if t is None:
            return "gone", None
        s = t.get("agent_status") or "unknown"
        if s in ("idle", "done"):
            text = self.read(h)
            until = limit_reset(text)
            if until:
                return "idle", until
            tail = "\n".join(text.splitlines()[-3:])
            return ("working" if _MONITORS_RE.search(tail) else "idle"), None  # waits on its own monitors
        return ("blocked" if s == "blocked" else "working"), None

    def close(self, h):
        if h and h.get("tab"):
            self._ok(["tab", "close", h["tab"]])


class Headless:
    """Lanes as headless UI sessions (ui_runner): each turn is a process; send resumes or queues."""

    _AGENT = {
        "starting": "working",
        "running": "working",
        "queued": "working",
        "waiting": "blocked",
        "done": "idle",
        "stopped": "idle",
        "failed": "gone",
    }

    def __init__(self, runner=None, sessions=None):
        if runner is None:
            import ui_runner as runner  # noqa: PLC0415 - heavy import, only in the server
        if sessions is None:
            import ui_sessions as sessions  # noqa: PLC0415
        self.runner, self.sessions = runner, sessions

    def start(self, lane, prompt, d):
        s = d.get("settings") or {}  # ui_runner already passes --dangerously-skip-permissions
        effort = ["--effort", s["effort"]] if s.get("effort") else []
        rec = self.runner.start(prompt, lane["repo"], extra_args=effort, model=s.get("model"), gate_questions=True)
        return {"session": rec["id"]}

    def send(self, h, text):
        self.runner.send_prompt(h["session"], text)

    def read(self, h) -> str:
        rec = self.sessions.load(h["session"]) or {}
        return rec.get("error") or rec.get("note") or ""  # the transcript is the UI's session view

    def status(self, h):
        rec = self.sessions.load(h["session"]) if h else None
        if not rec:
            return "gone", None
        if rec.get("status") == "limited":  # ui_runner resumes it at the reset by itself
            return "working", None
        return self._AGENT.get(rec.get("status"), "working"), None

    def close(self, h):
        return None  # a headless session ends with its turn; nothing stays open


def for_dispatch(d: dict):
    return Herdr(d.get("workspace")) if d["runner"] == "herdr" else Headless()
