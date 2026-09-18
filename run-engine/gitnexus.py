"""GitNexus index: `route gitnexus sync|index|clean`.

The same three-step fallback ladder was written out in three places. GitNexus is
best-effort everywhere it appears in this pipeline — grep and gh still work without
it — so this never exits nonzero either.
"""

from __future__ import annotations

import os

from shared import load_ledger, record, run, warn

TIMEOUT = 900


def _runner(repo: str) -> list[str] | None:
    return ["node", ".gitnexus/run.cjs"] if os.path.isfile(os.path.join(repo, ".gitnexus", "run.cjs")) else None


def analyze(repo: str) -> tuple[bool, str]:
    runner = _runner(repo)
    if runner:
        proc = run([*runner, "analyze"], cwd=repo, timeout=TIMEOUT)
        if proc.returncode == 0:
            return True, os.path.basename(repo.rstrip("/"))
    # No runner, or the local one failed: the first `npx gitnexus analyze` is also
    # what GENERATES .gitnexus/run.cjs, so this is the bootstrap path too.
    proc = run(["npx", "gitnexus", "analyze"], cwd=repo, timeout=TIMEOUT)
    if proc.returncode == 0:
        return True, os.path.basename(repo.rstrip("/"))
    return False, (proc.stderr or proc.stdout or "gitnexus unavailable").strip().splitlines()[-1][:160]


def cmd_run(args) -> None:
    repo = os.path.abspath(args.repo)
    if args.op == "clean":
        runner = _runner(repo)
        if runner:
            run([*runner, "clean", "--force"], cwd=repo, timeout=TIMEOUT)
        print("cleaned")
        return

    if args.op == "sync":
        runner = _runner(repo)
        if runner:
            status = run([*runner, "status"], cwd=repo, timeout=300)
            if status.returncode == 0 and "stale" not in status.stdout.lower() \
               and "missing" not in status.stdout.lower():
                print("index is current")
                if args.run_dir:
                    record(args.run_dir, load_ledger(args.run_dir),
                           gitnexus=os.path.basename(repo.rstrip("/")))
                return

    ok, detail = analyze(repo)
    if ok:
        print(f"indexed {detail}")
    else:
        # One line and move on. Never block the run on gitnexus.
        warn(f"gitnexus unavailable — this run continues grep-only: {detail}")
    if args.run_dir:
        record(args.run_dir, load_ledger(args.run_dir), gitnexus=detail if ok else "none")


def register(sub, add) -> None:
    p = sub.add_parser("gitnexus", help="sync, index or clean the gitnexus graph (best-effort)")
    p.add_argument("op", choices=["sync", "index", "clean"])
    p.add_argument("repo", help="repo or worktree root")
    p.add_argument("--run-dir", help="also record gitnexus=<key|none> in this run's ledger")
    p.set_defaults(func=cmd_run)
