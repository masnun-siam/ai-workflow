#!/usr/bin/env python3
"""Deterministic routing CLI for /run-issue — the I/O half of the engine.

Read the run ledger + a station's just-emitted envelope, validate it against the
handoff contract, run the guards, decide the next action, persist, and print the
action. The orchestrator acts on what this prints; it never eyeballs the routing.

Usage:
  route.py init <runDir> --issue N [--mode full|lean] [--repo PATH]
  route.py route <runDir> <artifact.json> [--repo PATH]
  route.py classify <runDir> [--loc N] [--labels a,b] [--depth N] < changed-paths
  route.py resolve-review <runDir>
  route.py set <runDir> key=value [key=value ...]
  route.py paths            # print resolved plugin/data paths as JSON

Exit codes: 0 ok · 2 usage · 3 unreadable artifact · 4 artifact is not a JSON object
            · 5 artifact fails the handoff contract · 6 test-root ownership violation
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import Ledger, RouteAction, Router, classify, resolve_review_panel, validate_envelope  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
GLOBAL_CONFIG = os.path.join(HERE, "config.json")
OVERLAY_NAME = ".run-issue.json"
PLUGIN_ROOT = os.path.dirname(HERE)
# State must outlive a plugin upgrade, which replaces PLUGIN_ROOT wholesale.
DATA_DIR = os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.expanduser(
    "~/.claude/plugins/data/ai-workflow"
)


def die(code: int, message: str):
    sys.stderr.write(message.rstrip() + "\n")
    sys.exit(code)


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


def write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def deep_merge(base: dict, overlay: dict) -> dict:
    """Dicts merge; lists (and scalars) REPLACE.

    Lists replace deliberately: a repo overlay that narrows a signal's globs must
    narrow it, not union with the global defaults and silently widen it.
    """
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(repo: str | None) -> dict:
    config = read_json(GLOBAL_CONFIG)
    if repo:
        overlay_path = os.path.join(repo, OVERLAY_NAME)
        if os.path.isfile(overlay_path):
            config = deep_merge(config, read_json(overlay_path))
    return config


def ledger_path(run_dir: str) -> str:
    return os.path.join(run_dir, "run.json")


def load_ledger(run_dir: str) -> Ledger:
    return Ledger.from_dict(read_json(ledger_path(run_dir)))


def save_ledger(run_dir: str, ledger: Ledger) -> None:
    write_json(ledger_path(run_dir), ledger.to_dict())


# --------------------------------------------------------------------------- guards


def test_root_violations(repo: str, sdet_sha: str, test_root: str) -> list[str]:
    """Files under the approved test root changed since the SDET's commit.

    Deliberately `git diff <sha>..HEAD`, not a worktree diff: run-dev commits its
    work, so a worktree-vs-index check sees nothing once the edit is committed —
    which is exactly how a weakened test used to slip through. This form also
    catches additions and deletions, which a per-file content hash of the SDET's
    declared list would miss.
    """
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{sdet_sha}..HEAD", "--", test_root],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        # A broken sha or missing path is not a violation — say so and let the run
        # continue rather than halting on a guard that could not run.
        sys.stderr.write(f"warning: test-root guard could not run: {proc.stderr.strip()}\n")
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def apply_action(ledger: Ledger, action: RouteAction, station) -> None:
    if action.kind == RouteAction.ADVANCE:
        ledger.advance_to(action.target)
    elif action.kind == RouteAction.BOUNCE:
        ledger.record_bounce(station, action.target)
    elif action.kind == RouteAction.DONE:
        ledger.mark_done()
    elif action.kind == RouteAction.ESCALATE:
        ledger.mark_escalated(action.reason)


def run_dir_for(args) -> str:
    return args.run_dir


# --------------------------------------------------------------------------- commands


def cmd_init(args) -> None:
    config = load_config(args.repo)
    mode = args.mode or config.get("default_mode", "full")
    modes = config.get("modes") or {}
    if mode not in modes:
        die(2, f"unknown mode: {mode} (have: {', '.join(sorted(modes)) or 'none'})")

    stations = modes[mode].get("stations") or config.get("stations") or []
    if os.path.isfile(ledger_path(args.run_dir)):
        die(2, f"run already initialised: {ledger_path(args.run_dir)} — use `resume`, don't re-init")

    ledger = Ledger(args.issue, stations)
    ledger.context["mode"] = mode
    if args.repo:
        ledger.context["repo"] = os.path.abspath(args.repo)
    ledger.trace.append(f"init: mode={mode} roster=" + " -> ".join(stations))
    save_ledger(args.run_dir, ledger)
    print(f"initialised {mode}: " + " -> ".join(stations))


def cmd_route(args) -> None:
    ledger = load_ledger(args.run_dir)
    repo = args.repo or ledger.context.get("repo") or os.getcwd()
    config = load_config(repo)

    envelope = read_json(os.path.join(args.run_dir, args.artifact))
    if not isinstance(envelope, dict):
        die(4, f"artifact is not a JSON object: {args.artifact}")

    errors = validate_envelope(envelope, ledger, config)
    if errors:
        die(5, "invalid artifact: " + "; ".join(errors))

    station = envelope.get("station")
    status = envelope.get("status")

    # Test ownership. The SDET owns the tests it authored; dev makes them pass by
    # writing product code, never by editing the test. Skipped when there is no
    # sdet_sha (lean mode never ran an SDET, so there is no baseline to protect).
    sdet_sha = ledger.context.get("sdet_sha")
    test_root = ledger.context.get("test_root")
    router = Router(config.get("bounce_cap", 2))

    if station == "dev" and status == "passed" and sdet_sha and test_root:
        violations = test_root_violations(repo, sdet_sha, test_root)
        if violations:
            # Route the bounce HERE rather than telling the orchestrator to rewrite the
            # station's envelope. Hand-authoring an envelope is the one thing the contract
            # cannot detect (H1), so the engine must not ask for it — not even to correct a
            # violation. Deciding this here also means the bounce consumes the dev->sdet cap
            # and escalates past it like any other, so tampering cannot loop.
            envelope = {
                **envelope,
                "status": "bounce",
                "summary": "test-ownership violation: " + ", ".join(violations),
                "bounce": {
                    "to": "sdet",
                    "reason": "dev changed SDET-owned test files; reverted",
                    "findings": [{"file": f, "severity": "blocker",
                                  "note": "changed since the SDET commit; the SDET owns this file"}
                                 for f in violations],
                },
            }
            action = router.next(ledger, envelope)
            apply_action(ledger, action, station)
            save_ledger(run_dir_for(args), ledger)
            sys.stderr.write(
                "test-ownership violation: dev changed test-root file(s) since the SDET commit: "
                + ", ".join(violations)
                + f" — revert them (git checkout {sdet_sha} -- <files>) before acting on the "
                "action printed on stdout.\n"
            )
            print(action)
            sys.exit(6)

    action = router.next(ledger, envelope)

    apply_action(ledger, action, station)
    save_ledger(args.run_dir, ledger)
    print(action)


def cmd_classify(args) -> None:
    ledger = load_ledger(args.run_dir)
    repo = args.repo or ledger.context.get("repo") or os.getcwd()
    config = load_config(repo)

    changed = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
    if not changed:
        die(2, "classify reads the changed-file list on stdin, one path per line — got nothing")

    meta = {
        "loc_changed": args.loc,
        "labels": [l.strip() for l in (args.labels or "").split(",") if l.strip()],
    }
    # Absent --depth stays absent, so the classifier reports blast_radius "unknown"
    # and scores it wide. Do not default it to 0.
    if args.depth is not None:
        meta["upstream_depth"] = args.depth

    result = classify(changed, meta, config)
    write_json(os.path.join(args.run_dir, "45-classification.json"), result)
    ledger.record_classification(result)
    save_ledger(args.run_dir, ledger)
    print(json.dumps(result, indent=2))


def cmd_resolve_review(args) -> None:
    ledger = load_ledger(args.run_dir)
    repo = args.repo or ledger.context.get("repo") or os.getcwd()
    config = load_config(repo)

    path = os.path.join(args.run_dir, "45-classification.json")
    classification = read_json(path) if os.path.isfile(path) else (ledger.classification or {})
    if not classification:
        die(2, "no classification to resolve from — run `classify` first")

    panel = resolve_review_panel(classification, config.get("review_policy") or {})
    ledger.record_specialists(panel)
    save_ledger(args.run_dir, ledger)
    for lens in panel:
        print(lens)


def cmd_set(args) -> None:
    ledger = load_ledger(args.run_dir)
    for pair in args.pairs:
        if "=" not in pair:
            die(2, f"expected key=value, got: {pair}")
        key, _, value = pair.partition("=")
        ledger.context[key.strip()] = value
    save_ledger(args.run_dir, ledger)
    print(json.dumps(ledger.context, indent=2))


def cmd_paths(args):
    """Resolve every path the orchestrator prose needs, once, at preflight."""
    out = {
        "plugin_root": PLUGIN_ROOT,
        "data_dir": DATA_DIR,
        "runs_dir": os.path.join(DATA_DIR, "runs"),
        "pr_grind_dir": os.path.join(DATA_DIR, "pr-grind"),
        "channels": os.path.join(DATA_DIR, "channels.json"),
        "config": GLOBAL_CONFIG,
        "dod": os.path.join(PLUGIN_ROOT, "definition-of-done.md"),
        "dor": os.path.join(PLUGIN_ROOT, "definition-of-ready.md"),
        "agents_dir": os.path.join(PLUGIN_ROOT, "agents"),
    }
    for key in ("runs_dir", "pr_grind_dir"):
        os.makedirs(out[key], exist_ok=True)
    print(json.dumps(out, indent=2))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="route.py", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add(name, help_text):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("run_dir")
        p.add_argument("--repo", help="repo/worktree root (default: ledger context, else cwd)")
        return p

    p_init = add("init", "create run.json")
    p_init.add_argument("--issue", type=int, required=True)
    p_init.add_argument("--mode")
    p_init.set_defaults(func=cmd_init)

    p_route = add("route", "validate an envelope and decide the next action")
    p_route.add_argument("artifact", help="artifact filename inside run_dir")
    p_route.set_defaults(func=cmd_route)

    p_cls = add("classify", "score the diff (changed paths on stdin)")
    p_cls.add_argument("--loc", type=int, default=0)
    p_cls.add_argument("--labels", default="")
    p_cls.add_argument("--depth", type=int, default=None, help="gitnexus upstream depth; omit if unknown")
    p_cls.set_defaults(func=cmd_classify)

    p_rr = add("resolve-review", "print the specialist lenses to spawn, one per line")
    p_rr.set_defaults(func=cmd_resolve_review)

    p_set = add("set", "write key=value pairs into ledger context")
    p_set.add_argument("pairs", nargs="+")
    p_set.set_defaults(func=cmd_set)

    p_paths = sub.add_parser("paths", help="print resolved plugin/data paths as JSON")
    p_paths.set_defaults(func=cmd_paths)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except ValueError as exc:
        die(5, str(exc))


if __name__ == "__main__":
    main()
