#!/usr/bin/env python3
"""`aiw` — the deterministic CLI behind /run-issue; the I/O half of the engine.

Invoked as `aiw` (plugin bin/). NOT as `route`: that is the macOS/BSD/net-tools network
command, and on a default macOS PATH /sbin shadows the plugin bin, so `route paths` ran
/sbin/route, printed a usage error to stderr, and exited 0 — an unresolved path that looked
like a success.

Read the run ledger + a station's just-emitted envelope, validate it against the
handoff contract, run the guards, decide the next action, persist, and print the
action. The orchestrator acts on what this prints; it never eyeballs the routing.

Usage:
  aiw init <runDir> --issue N [--mode full|lean] [--repo PATH]
  aiw route <runDir> <artifact.json> [--repo PATH]
  aiw classify <runDir> [--loc N] [--labels a,b] [--depth N] < changed-paths
  aiw resolve-review <runDir>
  aiw set <runDir> key=value [key=value ...]
  aiw paths            # print resolved plugin/data paths as JSON

Mechanical subcommands (the phases that used to be prose in commands/run-issue.md):
  aiw stack up|down|rebuild|status <runDir>
  aiw worktree create <runDir> --title "<issue title>"
  aiw threads list|resolve <pr-ref|node-id...>
  aiw pr open <runDir> --body-file <file> [--draft]
  aiw ci status <pr-ref> [--watch]
  aiw gitnexus sync|index|clean <repo> [--run-dir <runDir>]
  aiw project-status <owner/repo> <issue> "<status>"
  aiw precheck <runDir> <station>      # sdet | reviewer | fixer

Exit codes for `route`: 0 ok · 2 usage · 3 unreadable artifact · 4 artifact is not a
JSON object · 5 artifact fails the handoff contract · 6 test-root ownership violation · 7 a station
post-check refuted a `passed` envelope and the bounce has been routed.
THAT vocabulary is the only one that means "Teardown and report".

The mechanical subcommands use a different, smaller one: 0 ok · 1 the operation
failed · 2 usage. `project-status`, `gitnexus` and `stack down` are best-effort and
NEVER exit nonzero — the orchestrator's standing reflex is that nonzero stops a run,
and a board with the wrong column name must not be able to trigger it.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import Ledger, RouteAction, Router, classify, resolve_review_panel, validate_envelope  # noqa: E402
import checks as checks_mod  # noqa: E402
import ci  # noqa: E402
import dispatch  # noqa: E402
import epic  # noqa: E402
import gitnexus  # noqa: E402
import pr  # noqa: E402
import project  # noqa: E402
import stack  # noqa: E402
import threads  # noqa: E402
import worktree  # noqa: E402
from shared import (  # noqa: E402
    GLOBAL_CONFIG,
    OVERLAY_NAME,
    data_dir,
    deep_merge,
    die,
    ledger_path,
    load_config,
    load_ledger,
    read_json,
    save_ledger,
    write_json,
)

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(HERE)


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

    # Post-checks. The station said what happened; this asks something with no
    # incentive to pass. It runs HERE, inside `route route`, so the orchestrator's
    # call sites do not change and cannot skip it.
    if status == "passed":
        result = checks_mod.run_post_check(station, ledger, envelope, repo, config)
        if result is not None and result.unrunnable:
            if station in checks_mod.FATAL_WHEN_UNRUNNABLE:
                # For these two the check failing to run IS the finding: a fixer whose
                # threads cannot be read is exactly the state the check exists for.
                action = RouteAction(
                    RouteAction.ESCALATE,
                    reason=f"{station} post-check could not run: {result.reason}",
                )
                apply_action(ledger, action, station)
                save_ledger(args.run_dir, ledger)
                print(action)
                sys.exit(0)
            note = f"{station}: {result.reason}"
            ledger.context.setdefault("check_notes", []).append(note)
            sys.stderr.write(f"note: {station} post-check could not run: {result.reason}\n")
        elif result is not None and not result.ok:
            cap = config.get("check_bounce_cap", 1)
            # Keyed "<station>-><station>", which no real bounce can produce, so the
            # budget can never merge with a genuine one. record_bounce sets
            # current_index to the target — the same station — so it re-dispatches in
            # place. No new ledger field, no Router change, no new status.
            if ledger.bounce_count(station, station) + 1 > cap:
                # Cap exhausted ADVANCES rather than halting: existing doctrine is that a
                # spent budget opens a draft PR and reports at the final gate rather than
                # stopping mid-flow. This adds no fourth human gate.
                ledger.context.setdefault("check_failures", []).append(
                    {"station": station, "reason": result.reason}
                )
                sys.stderr.write(
                    f"post-check failed again for {station} (cap {cap} spent): {result.reason}"
                    " — advancing; this is reported at the final gate.\n"
                )
            else:
                envelope = {
                    **envelope,
                    "status": "bounce",
                    "summary": f"post-check failed: {result.reason}",
                    "bounce": {"to": station, "reason": result.reason},
                }
                action = router.next(ledger, envelope)
                apply_action(ledger, action, station)
                save_ledger(args.run_dir, ledger)
                sys.stderr.write(f"{station} post-check failed: {result.reason}\n")
                print(action)
                sys.exit(7)

    action = router.next(ledger, envelope)

    apply_action(ledger, action, station)
    save_ledger(args.run_dir, ledger)
    print(action)


def cmd_precheck(args) -> None:
    """The pre-guards. Unlike the post-checks these cannot live inside `route route` —
    the engine only ever sees a station AFTER it ran. So the orchestrator calls this
    before dispatching, and the station name is the argument."""
    ledger = load_ledger(args.run_dir)
    repo = args.repo or ledger.context.get("repo") or os.getcwd()
    config = load_config(repo)
    fn = checks_mod.PRE_CHECKS.get(args.station)
    if fn is None:
        print(f"no pre-guard for {args.station}")
        return
    result = fn(ledger, None, repo, config)
    if result.unrunnable:
        print(f"unrunnable: {result.reason}")
        return
    if not result.ok:
        die(1, f"pre-guard failed for {args.station}: {result.reason}")
    print(f"{args.station}: ok")


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
    dd = data_dir()
    out = {
        "plugin_root": PLUGIN_ROOT,
        "data_dir": dd,
        "runs_dir": os.path.join(dd, "runs"),
        "pr_grind_dir": os.path.join(dd, "pr-grind"),
        "channels": os.path.join(dd, "channels.json"),
        "checkouts": dispatch.checkouts_path(),
        "config": GLOBAL_CONFIG,
        "dod": os.path.join(PLUGIN_ROOT, "definition-of-done.md"),
        "dor": os.path.join(PLUGIN_ROOT, "definition-of-ready.md"),
        "agents_dir": os.path.join(PLUGIN_ROOT, "agents"),
    }
    for key in ("runs_dir", "pr_grind_dir"):
        os.makedirs(out[key], exist_ok=True)
    print(json.dumps(out, indent=2))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="aiw", description=__doc__)
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

    p_pre = add("precheck", "run a station's pre-guard before dispatching it")
    p_pre.add_argument("station")
    p_pre.set_defaults(func=cmd_precheck)

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

    # The mechanical phases. Each module owns its own argparse wiring so adding one
    # is a file plus a line, not a surgery on this function.
    for module in (stack, worktree, threads, pr, ci, gitnexus, project, epic, dispatch):
        module.register(sub, add)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except ValueError as exc:
        die(5, str(exc))


if __name__ == "__main__":
    main()
