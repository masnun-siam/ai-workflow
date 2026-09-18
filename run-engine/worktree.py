"""Worktree setup: `route worktree create`.

Phase 2 steps 2-6. Three of those steps have a failure mode that only shows up much
later: a missed gitignored .env surfaces as spurious test failures deep in phase 5,
and a renamed branch or directory breaks phase 4b's gitnexus key and phase 5's push.
Computing both names here is what makes them fixed for the whole run.
"""

from __future__ import annotations

import os
import re
import shutil

from shared import die, load_ledger, print_written, record, run, warn

# Copied into the worktree because `git worktree add` materializes tracked files
# only, and the test stack needs these to exist. Copying too little here is
# invisible until the suite fails for an unrelated-looking reason, so this errs
# toward more rather than less.
SECRET_SUFFIXES = (".env", ".key", ".pem", ".p12", ".crt", ".p8")
SECRET_PREFIXES = (".env.",)

INSTALLS = (
    ("pnpm-lock.yaml", ["pnpm", "install", "--frozen-lockfile"]),
    ("yarn.lock", ["yarn", "install", "--frozen-lockfile"]),
    ("bun.lockb", ["bun", "install"]),
    ("package-lock.json", ["npm", "ci"]),
    ("composer.lock", ["composer", "install", "--no-interaction"]),
    ("go.mod", ["go", "mod", "download"]),
    ("pubspec.yaml", ["flutter", "pub", "get"]),
    ("requirements.txt", ["pip", "install", "-r", "requirements.txt"]),
    ("pyproject.toml", ["pip", "install", "-e", "."]),
)


def slugify(title: str, words: int = 5) -> str:
    parts = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-").split("-")
    return "-".join(p for p in parts if p)[:60].strip("-") or "issue"


def is_secret(path: str) -> bool:
    name = os.path.basename(path)
    return name.endswith(SECRET_SUFFIXES) or name.startswith(SECRET_PREFIXES)


def ignored_secrets(main_checkout: str) -> list[str]:
    """Gitignored files worth copying, from `git status --ignored` — which is what
    the prose already names as the right source to check."""
    proc = run(["git", "status", "--porcelain", "--ignored"], cwd=main_checkout)
    if proc.returncode != 0:
        warn("could not list ignored files; copying nothing into the worktree")
        return []
    out = []
    for line in proc.stdout.splitlines():
        if not line.startswith("!! "):
            continue
        path = line[3:].strip()
        if path.endswith("/"):
            # a whole ignored directory (vendor/, node_modules/) — walk it only for
            # key material, never copy the directory itself
            for root, _dirs, files in os.walk(os.path.join(main_checkout, path)):
                for f in files:
                    full = os.path.join(root, f)
                    if is_secret(full):
                        out.append(os.path.relpath(full, main_checkout))
        elif is_secret(path):
            out.append(path)
    return out


def pick_install(directory: str) -> list[str] | None:
    for lockfile, cmd in INSTALLS:
        if os.path.exists(os.path.join(directory, lockfile)):
            if lockfile == "pubspec.yaml":
                try:
                    with open(os.path.join(directory, lockfile), encoding="utf-8") as fh:
                        if "flutter:" not in fh.read():
                            return ["dart", "pub", "get"]
                except OSError:
                    pass
            return cmd
    return None


def install_dir(repo: str, test_root: str | None) -> str:
    """Install for the platform the plan's test root indicates, not the whole repo —
    unless the repo root is where the lockfile is anyway."""
    if test_root:
        cur = os.path.dirname(os.path.join(repo, test_root.rstrip("/")))
        while cur.startswith(repo) and len(cur) > len(repo):
            if pick_install(cur):
                return cur
            cur = os.path.dirname(cur)
    return repo


def cmd_create(args) -> None:
    ledger = load_ledger(args.run_dir)
    main_checkout = os.path.abspath(args.repo or ledger.context.get("repo") or os.getcwd())
    base = args.base or ledger.context.get("base_branch")
    if not base:
        die(2, "no base branch: pass --base, or record base_branch from the approved plan first")

    issue = ledger.issue
    branch = f"issue-{issue}-{slugify(args.title)}"
    worktree = os.path.abspath(os.path.join(main_checkout, "..", f"wt-issue-{issue}"))

    if os.path.isdir(worktree):
        die(1, f"{worktree} already exists — phase 0's resume path owns it; do not re-create")

    proc = run(["git", "fetch", "origin", base], cwd=main_checkout, timeout=600)
    if proc.returncode != 0:
        die(1, f"git fetch origin {base} failed: " + (proc.stderr or "").strip()[:300])

    proc = run(["git", "worktree", "add", worktree, "-b", branch, f"origin/{base}"],
               cwd=main_checkout, timeout=600)
    if proc.returncode != 0:
        die(1, "git worktree add failed: " + (proc.stderr or "").strip()[:300])

    copied = 0
    for rel in ignored_secrets(main_checkout):
        src, dst = os.path.join(main_checkout, rel), os.path.join(worktree, rel)
        os.makedirs(os.path.dirname(dst) or worktree, exist_ok=True)
        try:
            shutil.copy2(src, dst)
            copied += 1
        except OSError as exc:
            warn(f"could not copy {rel}: {exc}")

    where = install_dir(worktree, ledger.context.get("test_root"))
    install = pick_install(where)
    if install:
        proc = run(install, cwd=where, timeout=1800)
        if proc.returncode != 0:
            warn(" ".join(install) + " failed: " + (proc.stderr or "").strip()[:300])
    else:
        warn("no lockfile found — skipping dependency install")

    # So run-sdet/run-dev's commits never sweep the generated compose override into
    # the PR. `.git` in a worktree is a FILE pointing at the real gitdir, so the path
    # has to come from git — and git reads info/exclude from the COMMON dir, which is
    # why this is asked for rather than assumed. It is never committed either way.
    where = run(["git", "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"],
                cwd=worktree)
    exclude = (where.stdout or "").strip()
    if exclude:
        os.makedirs(os.path.dirname(exclude), exist_ok=True)
        existing = ""
        if os.path.isfile(exclude):
            with open(exclude, encoding="utf-8") as fh:
                existing = fh.read()
        if ".docker-agent.yml" not in existing:
            with open(exclude, "a", encoding="utf-8") as fh:
                fh.write("\n.docker-agent.yml\n")
    else:
        warn("could not locate info/exclude; .docker-agent.yml may reach the PR")

    print(f"copied {copied} gitignored file(s); install: {' '.join(install) if install else 'skipped'}")
    print_written(record(
        args.run_dir, ledger,
        worktree=worktree, branch=branch, main_checkout=main_checkout, repo=worktree,
    ))


def register(sub, add) -> None:
    p = sub.add_parser("worktree", help="create the per-issue worktree")
    ops = p.add_subparsers(dest="op", required=True)
    q = ops.add_parser("create", help="fetch the base, add the worktree, copy secrets, install")
    q.add_argument("run_dir")
    q.add_argument("--title", default="", help="issue title, for the branch slug")
    q.add_argument("--base", help="base branch (default: base_branch from the ledger)")
    q.add_argument("--repo", help="main checkout (default: ledger context, else cwd)")
    q.set_defaults(func=cmd_create)
