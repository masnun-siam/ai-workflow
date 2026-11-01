"""I/O helpers shared by the `aiw` subcommands and the UI server."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import subprocess
import sys
import time

USAGE = 2

HERE = os.path.dirname(os.path.abspath(__file__))
GLOBAL_CONFIG = os.path.join(HERE, "config.json")


def data_dir() -> str:
    """Where plugin state lives, outside the plugin install directory itself so it
    survives a plugin upgrade (which replaces the install directory wholesale).

    Read at call time, not cached at import time — a test that sets
    $CLAUDE_PLUGIN_DATA after this module is imported must still see it honoured.
    """
    return os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.expanduser("~/.claude/plugins/data/ai-workflow")


def die(code: int, message: str):
    sys.stderr.write(message.rstrip() + "\n")
    sys.exit(code)


def warn(message: str) -> None:
    sys.stderr.write("warning: " + message.rstrip() + "\n")


def extract_json_object(raw: str):
    """Return the first balanced top-level {...} that parses, or None."""
    start = raw.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(raw)):
            ch = raw[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = raw.find("{", start + 1)
    return None


def read_json(path: str, missing_code: int = 3):
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except FileNotFoundError:
        die(missing_code, f"cannot read: {path}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Envelopes are written by an LLM told to return "one JSON object and nothing else",
    # and sometimes it isn't: a ```json fence, or a sentence before the brace. Recover the
    # object rather than failing the run over packaging — the CONTRACT is still enforced
    # by validate_envelope, which is the part that matters. Being strict here would only
    # convert a formatting slip into a re-dispatch, and re-dispatching a station that did
    # its work correctly is the expensive kind of strictness.
    obj = extract_json_object(raw)
    if obj is None:
        die(4, f"no JSON object found in: {path}")
    return obj


def write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


@contextlib.contextmanager
def json_lock(path: str):
    """Exclusive flock on `<path>.lock` around a read-modify-write: serialises threads and processes.
    Not re-entrant: never nest it on the same path."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def backup_if_corrupt(path: str) -> None:
    """Move a present-but-unparsable (or non-object) JSON file to `<path>.corrupt-<ts>` so the next write
    does not overwrite it. No-op for a missing or good file."""
    try:
        with open(path, encoding="utf-8") as fh:
            ok = isinstance(json.load(fh), dict)
    except OSError:  # missing or unreadable: nothing to move aside
        return
    except ValueError:
        ok = False
    if not ok:
        dest = f"{path}.corrupt-{int(time.time())}"
        os.replace(path, dest)
        warn(f"{path} is corrupt; moved to {dest}")


def atomic_write_text(path: str, text: str) -> None:
    """tmp file + fsync + os.replace: readers never see a partial file."""
    import tempfile

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_config(repo: str | None = None) -> dict:
    """Global config.json, with `peer_review` overrides from `<data_dir>/config.json` (written by the
    UI's Settings) laid over it key by key, and each lens field by field. `repo` is ignored."""
    cfg = read_json(GLOBAL_CONFIG)
    path = os.path.join(data_dir(), "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            over = json.load(fh).get("peer_review")
    except (OSError, ValueError, AttributeError):  # missing or broken: the shipped defaults stand
        over = None
    if isinstance(over, dict):
        pr = cfg["peer_review"] = {**cfg["peer_review"], **{k: v for k, v in over.items() if k != "lenses"}}
        if isinstance(over.get("lenses"), dict):
            base = pr.get("lenses", {})
            pr["lenses"] = {k: {**v, **(over["lenses"].get(k) or {})} for k, v in base.items()}
    return cfg


# --------------------------------------------------------------------------- process


def run(argv, cwd=None, timeout=None, env=None):
    """Run a command with no shell. Never raises on a nonzero exit — callers decide."""
    try:
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", f"timed out after {timeout}s")


def shell(cmd: str, cwd=None, timeout=None):
    """Run a command STRING through the shell.

    Only for strings the ledger already holds verbatim — `compose_prefix` and
    `test_cmd`. Those are contracts: every station is told to run test_cmd
    "unchanged", so splitting or rewriting it here would make this the one place
    that runs something different from what every station ran.
    """
    try:
        return subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", f"timed out after {timeout}s")


def gh_json(args, cwd=None, timeout=120):
    """`gh <args>`. Returns (value, proc).

    A `--jq` that selects a scalar makes gh print it BARE — `abc123`, not `"abc123"` —
    which is not JSON. Rather than banning --jq or hand-decoding at every call site,
    an unparseable stdout from a SUCCESSFUL command comes back as the stripped string.
    A failed command is always None, so callers can keep testing for that.
    """
    proc = run(["gh", *args], cwd=cwd, timeout=timeout)
    if proc.returncode != 0:
        return None, proc
    raw = (proc.stdout or "").strip()
    try:
        return json.loads(raw or "null"), proc
    except json.JSONDecodeError:
        return (raw or None), proc


# --------------------------------------------------------------------------- gh refs

import re  # noqa: E402


def parse_pr_ref(ref: str, cwd=None) -> tuple[str, str, int]:
    """Accept a PR URL, `owner/repo#123`, `owner/repo 123`, or a bare number.

    A bare number resolves owner/repo from the checkout's remote — the same
    resolution every call site did by hand, in one place.
    """
    ref = (ref or "").strip()
    m = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", ref)
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    m = re.fullmatch(r"([^/\s]+)/([^/#\s]+)[#\s](\d+)", ref)
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    if ref.isdigit():
        slug, proc = gh_json(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], cwd=cwd)
        if isinstance(slug, str) and "/" in slug:
            owner, _, repo = slug.partition("/")
            return owner, repo, int(ref)
        die(USAGE, f"cannot resolve owner/repo for PR {ref}: {(proc.stderr or '').strip()}")
    die(USAGE, f"unrecognised PR reference: {ref!r} (want a URL, owner/repo#N, or N)")
