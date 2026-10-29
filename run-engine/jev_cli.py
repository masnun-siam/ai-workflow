"""`aiw jev ci-hint|finding-hint --file <path>`: advisory jev hints for /pr-grind. Stdlib only.

Prints JSON and always exits 0 once the arguments parse. The text comes from a file and goes to jev on stdin,
never argv. `none` is never a jev option: it marks a call that gave no answer, with probability 0.
These points are never cached or counted (see jev.CACHED).
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import jev
import shared

CI_QUESTION = "Is this failing CI log an infrastructure flake, or a real failure caused by the change?"
CI_OPTIONS = {
    "flaky": "infrastructure flake: runner died, timeout with no test output, network or registry error, 429 or 503 from a mirror",
    "real": "real failure: assertion, lint, type or build error",
}
FINDING_QUESTION = "Should this code review finding be fixed, or rebutted as wrong?"
FINDING_OPTIONS = {
    "fix": "the finding is valid or might be: change the code",
    "rebut": "the finding is wrong: handled elsewhere in the diff, would break a passing test, or rests on a false premise",
}
MAX_FINDINGS = 20
WORKERS = 4


def _none(status: str) -> dict:
    return {"hint": "none", "probability": 0, "status": status}


def _hint(point: str, question: str, options: dict, text: str) -> dict:
    s = jev.status()
    if s != "ok":
        return _none(s)
    if not text.strip():
        return _none("failed")
    r = jev.ask(point, "choice", question, text, options=options)
    if r["status"] == "ok":
        return {"hint": r["choice"], "probability": round(r["p"], 2), "status": "ok"}
    return _none(r["status"] if r["status"] in ("off", "missing") else "failed")


def ci_hint(text: str) -> dict:
    # slice the tail first: jev.ask keeps the head, and failures print at the end
    return _hint("ci-hint", CI_QUESTION, CI_OPTIONS, text[-jev.MAX_CHARS :])


def finding_hints(findings: list) -> list:
    items = [f if isinstance(f, dict) else {} for f in findings[:MAX_FINDINGS]]
    keys = [f["id"] if f.get("id") is not None else f"#{i}" for i, f in enumerate(items, 1)]
    texts = [f["text"] if isinstance(f.get("text"), str) else "" for f in items]
    with ThreadPoolExecutor(WORKERS) as pool:
        hints = pool.map(lambda t: _hint("finding-hint", FINDING_QUESTION, FINDING_OPTIONS, t), texts)
        return [{"id": k, **h} for k, h in zip(keys, hints)]


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def cmd_ci_hint(args) -> None:
    try:
        result = ci_hint(_read(args.file))
    except Exception as exc:  # noqa: BLE001 - advisory verb: never exit non-zero
        shared.warn(f"jev ci-hint: {type(exc).__name__}")
        result = _none("failed")
    print(json.dumps(result))


def cmd_finding_hint(args) -> None:
    try:
        try:
            data = json.loads(_read(args.file))
        except ValueError:
            data = []
        result = finding_hints(data) if isinstance(data, list) else []
    except Exception as exc:  # noqa: BLE001 - advisory verb: never exit non-zero
        shared.warn(f"jev finding-hint: {type(exc).__name__}")
        result = []
    print(json.dumps(result))


def register(sub, add) -> None:
    p = sub.add_parser("jev", help="advisory jev hints for /pr-grind (JSON, always exit 0)")
    ops = p.add_subparsers(dest="op", required=True)
    for name, func, what in (
        ("ci-hint", cmd_ci_hint, "flaky or real, for a failing CI log"),
        ("finding-hint", cmd_finding_hint, "fix or rebut, for a JSON list of {id, text} findings"),
    ):
        q = ops.add_parser(name, help=what)
        q.add_argument("--file", required=True, help="file holding the text")
        q.set_defaults(func=func)
