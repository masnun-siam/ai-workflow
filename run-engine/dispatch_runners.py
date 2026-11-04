"""Lane runners for dispatch_run: herdr tabs, Herdr app tabs or headless UI sessions, one interface. Stdlib only.

    start(lane, prompt, dispatch) -> handle     send(handle, text)     close(handle)
    status(handle) -> (agent, limited_until)    agent: working | idle | blocked | gone
    read(handle) -> text

Every lane session runs with permissions skipped and the dispatch's model and effort; a herdr lane on a
Codex account starts `--kind codex` (FR-13).
"""

from __future__ import annotations

import contextlib
import json
import re
import shlex
import uuid
from datetime import datetime, timedelta

import dispatch
import repo_skills
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


def _settings(settings):
    if settings is None:
        import ui_settings as settings  # noqa: PLC0415 - reads the plugin data dir
    return settings


def account_cmd(d: dict, settings=None) -> str:
    """The dispatch account's command: the saved account with that label, else the Settings default."""
    settings = _settings(settings)
    label = (d.get("settings") or {}).get("account")
    cmds = settings.load()["commands"]
    return next((c["cmd"] for c in cmds if c["label"] == label), None) or settings.default_cmd()


HERDR_CODEX_REFUSAL = (
    "herdr can only start the codex binary; use the headless runner or an account whose command is codex"
)


def herdr_codex_words(cmd: str) -> list:
    """A Codex account command's words after `codex`, split as ui_settings.argv splits; ValueError when
    herdr cannot start it (`herdr agent start --kind codex` runs only the codex binary)."""
    try:
        words = shlex.split(cmd)
    except ValueError:
        words = []
    if not words or words[0] != "codex":
        raise ValueError(HERDR_CODEX_REFUSAL)
    return words[1:]


def codex_args(d: dict, cmd: str, settings=None) -> list:
    """Interactive Codex flags for a lane; a model or effort Codex does not offer is left to Codex's default."""
    import harness_codex  # noqa: PLC0415 - it reads the plugin data dir

    settings = _settings(settings)
    s = d.get("settings") or {}
    flags = harness_codex.model_flags(s.get("model"), s.get("effort"), settings.models_of(cmd))[0]
    return ["--dangerously-bypass-approvals-and-sandbox", *flags]


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

    def __init__(self, workspace, cli=None, settings=None):
        self.workspace = workspace
        self.cli = cli or (lambda argv, timeout=60: run(["herdr", *argv], timeout=timeout))
        self.settings = settings

    def _ok(self, argv, timeout=60):
        p = self.cli(argv, timeout=timeout)
        if p.returncode != 0:
            raise RuntimeError(f"herdr {' '.join(argv[:2])} failed: {(p.stderr or p.stdout or '').strip()[:200]}")
        try:
            return json.loads(p.stdout or "null")
        except ValueError:
            return p.stdout or ""

    def start(self, lane, prompt, d):
        # herdr Claude lanes ignore the account; a Codex account is refused before any tab is made
        settings = _settings(self.settings)
        cmd = account_cmd(d, settings)
        codex = settings.harness_of(cmd) == "codex"
        rest = herdr_codex_words(cmd) if codex else None
        label = lane.get("label") or f"issue-{lane['n']}"
        cwd = checkout(lane["repo"])
        made = self._ok(
            [
                "tab",
                "create",
                *(["--workspace", self.workspace] if self.workspace else []),
                "--cwd",
                cwd,
                "--label",
                label,
                "--no-focus",
            ]
        )
        tab = _find(made, "tab_id")
        pane = _find(made, "pane_id") if not isinstance(made, str) else (made.split() or [""])[-1]
        if not pane:
            raise RuntimeError("herdr tab create returned no pane id")
        name = f"aiw-{d['id']}-{label}"
        kind, args = ("codex", [*rest, *codex_args(d, cmd, settings)]) if codex else ("claude", claude_args(d))
        self._ok(
            ["agent", "start", name, "--kind", kind, "--pane", pane, "--timeout", "120000", "--", *args],
            timeout=150,
        )
        h = {"tab": tab, "pane": pane, "agent": name, "cwd": cwd} | ({"kind": "codex"} if codex else {})
        self.send(h, prompt)
        return h

    def send(self, h, text):
        # resolve first: the repo/plugin spelling changes the length. A handle from before `cwd` was kept
        # resolves against None, which gives the plugin spelling.
        # a Codex lane gets a pointer to the skill file: the inlined body would not fit herdr's send
        prep = repo_skills.codex_pointer if h.get("kind") == "codex" else repo_skills.resolve
        text = prep(text, h.get("cwd"))
        # herdr cuts a long send-text; prompts here stay well under its ~500-character limit
        self._ok(["agent", "prompt", h["agent"], text[:480]])

    def read(self, h) -> str:
        r = self._ok(["pane", "read", h["pane"], "--lines", "200"])
        return r if isinstance(r, str) else (_find(r, "text") or json.dumps(r))

    def _tabs(self):
        return (
            _find(self._ok(["tab", "list", *(["--workspace", self.workspace] if self.workspace else [])]), "tabs") or []
        )

    def status(self, h):
        tabs = self._tabs()
        t = next((t for t in tabs if t.get("tab_id") == h.get("tab")), None)
        if t is None:
            return "gone", None
        s = t.get("agent_status") or "unknown"
        if s in ("idle", "done"):
            text = self.read(h)
            # ponytail: no Codex limit text match; a limited herdr Codex lane shows as stalled (PRD FR-13)
            until = None if h.get("kind") == "codex" else limit_reset(text)
            if until:
                return "idle", until
            tail = "\n".join(text.splitlines()[-3:])
            return ("working" if _MONITORS_RE.search(tail) else "idle"), None  # waits on its own monitors
        return ("blocked" if s == "blocked" else "working"), None

    def close(self, h):
        if h and h.get("tab"):
            try:
                self._ok(["tab", "close", h["tab"]])
            except RuntimeError:  # a tab that is already gone is closed
                if any(t.get("tab_id") == h["tab"] for t in self._tabs()):
                    raise


class HerdrApp:
    """Lanes as tabs of the Herdr desktop app (herdr-app over herdr-core `hc`), in one space. `hc run` with
    herdr.space/herdr.tab labels makes the tab; an unknown tab id becomes a new, unfocused tab. The first
    prompt goes in as the agent's argument, so nothing waits for it to be ready. A Codex account runs its own
    command with the Codex flags and the inlined skill prompt (FR-13)."""

    def __init__(self, space, cli=None, app=None, settings=None):
        self.space = space
        self.cli = cli or (lambda argv, timeout=60: run(["hc", *argv], timeout=timeout))
        self.app = app or (lambda argv, timeout=30: run(["herdr-app", *argv], timeout=timeout))
        self.settings = settings

    def _ok(self, argv, timeout=60):
        p = self.cli(argv, timeout=timeout)
        if p.returncode != 0:
            raise RuntimeError(f"hc {argv[0]} failed: {(p.stderr or p.stdout or '').strip()[:200]}")
        try:
            return json.loads(p.stdout or "null")
        except ValueError:
            return p.stdout or ""

    def start(self, lane, prompt, d):
        settings = _settings(self.settings)
        cmd = account_cmd(d, settings)
        codex = settings.harness_of(cmd) == "codex"
        label = lane.get("label") or f"issue-{lane['n']}"
        cwd = checkout(lane["repo"])
        # built before hc run, so a Codex command not on PATH fails with nothing made
        if codex:
            head, first = [*settings.argv(cmd), *codex_args(d, cmd, settings)], repo_skills.codex_prompt(prompt, cwd)
        else:
            head, first = ["claude", *claude_args(d)], repo_skills.resolve(prompt, cwd)
        tab = f"tb{uuid.uuid4().hex}"
        made = self._ok(
            [
                "run",
                "--bg",
                "--json",
                "--no-parent",
                "--keep",
                "--cwd",
                cwd,
                "--label",
                f"herdr.space={self.space}",
                "--label",
                f"herdr.tab={tab}",
                "--",
                *head,
                first,
            ]
        )
        address = made.get("address") if isinstance(made, dict) else None
        if not address:
            raise RuntimeError("hc run returned no terminal address")
        self.app(["do", "tab.rename", "--id", tab, "--name", label])  # ponytail: a name only; the window may be closed
        return {"terminal": address, "tab": tab, "cwd": cwd} | ({"kind": "codex"} if codex else {})

    def send(self, h, text):
        prep = repo_skills.codex_prompt if h.get("kind") == "codex" else repo_skills.resolve
        self._ok(["send", "--json", h["terminal"], prep(text, h.get("cwd"))])

    def read(self, h) -> str:
        r = self._ok(["read", h["terminal"], "--lines", "200"])
        return r if isinstance(r, str) else (_find(r, "text") or json.dumps(r))

    def status(self, h):
        p = self.cli(["get", "--json", h["terminal"]]) if h else None
        t = json.loads(p.stdout or "null") if p and p.returncode == 0 else None
        if not t or t.get("state") != "live":
            return "gone", None
        s = t.get("status") or "unknown"
        if s in ("idle", "done"):
            text = self.read(h)
            # ponytail: no Codex limit text match; a limited herdr-app Codex lane shows as stalled (PRD FR-13)
            until = None if h.get("kind") == "codex" else limit_reset(text)
            if until:
                return "idle", until
            tail = "\n".join(text.splitlines()[-3:])
            return ("working" if _MONITORS_RE.search(tail) else "idle"), None  # waits on its own monitors
        return ("blocked" if s == "blocked" else "working"), None

    def close(self, h):
        if h and h.get("terminal"):  # its pane, and the tab with it, closes when the agent ends
            p = self.cli(["kill", "--json", h["terminal"]])
            if p.returncode != 0 and self.status(h)[0] != "gone":
                raise RuntimeError(f"hc kill failed: {(p.stderr or p.stdout or '').strip()[:200]}")


def _held(rec: dict) -> bool:
    """A held session (ui_runner.hold) waits for the user. `stopped` stays final: the lane treats it as ever."""
    return bool(rec.get("hold")) and rec.get("status") != "stopped"


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

    def __init__(self, runner=None, sessions=None, settings=None):
        if runner is None:
            import ui_runner as runner  # noqa: PLC0415 - heavy import, only in the server
        if sessions is None:
            import ui_sessions as sessions  # noqa: PLC0415
        if settings is None:
            import ui_settings as settings  # noqa: PLC0415
        self.runner, self.sessions, self.settings = runner, sessions, settings

    def start(self, lane, prompt, d):
        s = d.get("settings") or {}  # ui_runner already passes --dangerously-skip-permissions
        cmd = next((c["cmd"] for c in self.settings.load()["commands"] if c["label"] == s.get("account")), None)
        rec = self.runner.start(
            prompt,
            lane["repo"],
            direct_effort=s.get("effort"),
            model=s.get("model"),
            claude_cmd=cmd,
            gate_questions=True,
        )
        return {"session": rec["id"]}

    def send(self, h, text):
        if _held(self.sessions.load(h["session"]) or {}):  # ui_runner.release delivers it on Resume
            self.sessions.update(h["session"], queued_prompt=text)
            return
        self.runner.send_prompt(h["session"], text)

    def read(self, h) -> str:
        rec = self.sessions.load(h["session"]) or {}
        return rec.get("error") or rec.get("note") or ""  # the transcript is the UI's session view

    def status(self, h):
        rec = self.sessions.load(h["session"]) if h else None
        if not rec:
            return "gone", None
        if _held(rec) or rec.get("status") == "limited":  # limited: ui_runner resumes it at the reset by itself
            return "working", None
        return self._AGENT.get(rec.get("status"), "working"), None

    def close(self, h):
        with contextlib.suppress(FileNotFoundError):  # its record is gone: nothing left to stop
            self.runner.stop(h["session"])  # does nothing to a session that already ended


def for_dispatch(d: dict):
    if d["runner"] == "herdr":
        return Herdr(d.get("workspace"))
    return HerdrApp(d.get("workspace")) if d["runner"] == "herdr-app" else Headless()
