"""I/O helpers shared by route.py and the mechanical subcommands.

route.py is the router; the modules beside it (stack, worktree, ghops, gitnexus)
are the mechanical phases that used to live as prose in commands/run-issue.md.
Everything they have in common — reading the ledger, writing it back, running a
subprocess, talking to `gh` — lives here so there is exactly one of each.

Exit-code doctrine for the mechanical subcommands: 0 ok · 1 the operation failed
· 2 usage. This is NOT `route route`'s vocabulary (0/2/3/4/5/6/7), which is the
only one that means "Teardown and report". Best-effort subcommands never exit
nonzero at all — see warn_only().
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

OK, FAILED, USAGE = 0, 1, 2


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
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


# --------------------------------------------------------------------------- ledger


def ledger_path(run_dir: str) -> str:
    return os.path.join(run_dir, "run.json")


def load_ledger(run_dir: str):
    from engine import Ledger

    return Ledger.from_dict(read_json(ledger_path(run_dir)))


def save_ledger(run_dir: str, ledger) -> None:
    write_json(ledger_path(run_dir), ledger.to_dict())


def record(run_dir: str, ledger, **pairs) -> dict:
    """Write context keys and persist. The subcommands call this instead of asking
    the orchestrator to follow up with `route set` — a step in prose is a step that
    gets skipped, and every key written here is load-bearing for a later phase."""
    written = {k: v for k, v in pairs.items() if v is not None}
    ledger.context.update(written)
    save_ledger(run_dir, ledger)
    return written


def print_written(written: dict) -> None:
    for key in sorted(written):
        print(f"{key}={written[key]}")


def repo_of(ledger, override: str | None = None) -> str:
    return override or ledger.context.get("repo") or os.getcwd()


# --------------------------------------------------------------------------- process


def run(argv, cwd=None, timeout=None, env=None):
    """Run a command with no shell. Never raises on a nonzero exit — callers decide."""
    try:
        return subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env
        )
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
        return subprocess.run(
            cmd, cwd=cwd, shell=True, capture_output=True, text=True, timeout=timeout
        )
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
