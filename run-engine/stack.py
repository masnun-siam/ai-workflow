"""The per-issue test stack: `route stack up|down|rebuild|status`.

Phase 2.5 of commands/run-issue.md used to describe all of this in eighty lines of
English. It is entirely mechanical — the outcome is decided by what is on disk and
what Docker says — so it belongs here, where it runs the same way every time and
where the ledger keys it produces cannot be forgotten.

This module is the ONLY owner of the container contract. checks.py's run_suite()
calls status() rather than probing compose itself, and pr-grind calls up()/down()
rather than re-deriving them from the ledger.
"""

from __future__ import annotations

import json
import os
import threading
import time

from shared import data_dir, die, load_ledger, print_written, record, repo_of, run, shell, warn

UP_TIMEOUT = 600  # seconds; the prose's `timeout: 600000` in milliseconds

# --------------------------------------------------------------------------- lock
#
# One stack at a time per host: a compose stack eats real CPU/memory, and two
# runs (or pr-grind rebuilding while a second `up` fires) can peg the machine
# the same way an uncapped stack once did. The lock is ledger-based, not
# pid-based — a short-lived `aiw stack up` process's own pid dies the instant
# the command returns, so pid-liveness would misfire on every healthy lock
# whose owning run is still very much alive.

LOCK_TIMEOUT = 900  # default --lock-timeout, seconds
LOCK_POLL = 5  # seconds between retries while waiting for the lock
LOCK_GRACE = 2 * UP_TIMEOUT  # a holder is only reclaimed once clearly abandoned

_LOCK_GUARD = threading.Lock()  # serializes the read-check-write within this process


def lock_path() -> str:
    return os.path.join(data_dir(), "stack.lock")


def _read_holder(path: str) -> dict | None:
    """None means free: no file, empty file, or a file that isn't valid JSON.
    None of those are a crash — a lock file is advisory, not a database."""
    data = _json_file(path)
    return data if isinstance(data, dict) else None


def lock_stale(holder: dict, now: float) -> bool:
    """True when the holder is provably finished or too old to trust.

    Reclaimed immediately once the holder's ledger status is "done" or
    "escalated" — that run is never coming back to call `stack down`. A
    holder still "running" (or whose ledger cannot be read at all) is only
    reclaimed once LOCK_GRACE has passed, bounding the crash case (a run
    that dies without ever updating its ledger again) without waiting
    forever.
    """
    run_dir = holder.get("run_dir")
    acquired_at = holder.get("acquired_at")
    if not run_dir or not isinstance(acquired_at, (int, float)):
        return True
    ledger_file = os.path.join(run_dir, "run.json")
    try:
        with open(ledger_file, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        warn(f"stack lock holder {run_dir} has no run.json; reclaiming")
        return True
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        warn(f"stack lock holder {run_dir} has an unreadable run.json; reclaiming")
        return True
    status = data.get("status") if isinstance(data, dict) else None
    if status in ("done", "escalated"):
        return True
    return (now - acquired_at) > LOCK_GRACE


def acquire_lock(run_dir: str, issue: int, repo: str, timeout: int) -> bool:
    """Acquire the single stack lock for `run_dir`. Re-entrant: a run already
    holding it (pr-grind's second `stack up`) never blocks on itself.

    The real contenders are separate `aiw stack up` OS processes, which share
    nothing but the filesystem — so exclusion has to be an OS-level atomic
    operation, not a process-local `threading.Lock` (that only ever serializes
    threads inside one interpreter). `os.open(..., O_CREAT | O_EXCL)` is the
    stdlib primitive that is atomic across processes: it fails with
    FileExistsError if the file is already there, at the OS level, so at most
    one contender's create can win a given instant.

    Fails OPEN on an unwritable data dir — a lock that cannot be written must
    not fail the run, it just stops protecting it.
    """
    path = lock_path()
    deadline = time.time() + max(timeout, 0)
    while True:
        with _LOCK_GUARD:  # still serializes threads within this process
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
            except OSError as exc:
                warn(f"stack lock directory is not writable ({exc}); proceeding unlocked")
                return True

            holder = {"run_dir": run_dir, "issue": issue, "repo": repo, "acquired_at": time.time()}
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                fd = None
            except OSError as exc:
                warn(f"stack lock file is not writable ({exc}); proceeding unlocked")
                return True

            if fd is not None:
                # We created the file — nobody else could have, atomically.
                try:
                    os.write(fd, json.dumps(holder).encode("utf-8"))
                finally:
                    os.close(fd)
                return True

            # The file already existed. Either it's ours (re-entrant), or it's
            # someone else's and possibly stale/abandoned — reclaim by atomic
            # replace so a concurrent reader never sees a half-written holder.
            existing = _read_holder(path)
            if existing is not None and existing.get("run_dir") == run_dir:
                return True
            if existing is None or lock_stale(existing, time.time()):
                tmp = f"{path}.{os.getpid()}.tmp"
                try:
                    with open(tmp, "w", encoding="utf-8") as fh:
                        json.dump(holder, fh)
                    os.replace(tmp, path)
                    return True
                except OSError as exc:
                    warn(f"stack lock file is not writable ({exc}); proceeding unlocked")
                    return True
                finally:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
        if time.time() >= deadline:
            return False
        time.sleep(min(LOCK_POLL, max(deadline - time.time(), 0)))


def release_lock(run_dir: str) -> None:
    """Best-effort: only removes the lockfile when `run_dir` is the recorded
    holder, so a stale/foreign release can never drop another run's lock."""
    path = lock_path()
    holder = _read_holder(path)
    if holder is not None and holder.get("run_dir") == run_dir:
        try:
            os.remove(path)
        except OSError:
            pass

COMPOSE_CANDIDATES = (
    "docker-compose.test.yml",
    "docker-compose.test.yaml",
    "compose.test.yml",
    "compose.test.yaml",
    "docker/docker-compose.test.yml",
    "docker/docker-compose.test.yaml",
)

# A datastore gets a smaller share than the app, and anything unrecognised is
# treated as a datastore: under-provisioning a sidecar is recoverable, and the
# failure this file exists to prevent is one container eating the host.
DATASTORE_HINTS = (
    "postgres", "pgsql", "mysql", "mariadb", "redis", "mongo", "elastic",
    "rabbit", "memcach", "minio", "mailhog", "mailpit", "meilisearch",
    "clickhouse", "kafka", "zookeeper", "selenium", "chrome",
)
APP_HINTS = ("app", "web", "php", "api", "laravel", "node", "server", "backend", "frontend")
API_HINTS = ("api", "php", "laravel", "backend", "server")
WEB_HINTS = ("web", "node", "frontend", "next", "react", "vite")


# --------------------------------------------------------------------------- pure


def package_dirs(repo: str, test_root: str | None) -> list[str]:
    """Where to look for a runner: the test root's own package first, then the repo.

    A monorepo installs for the platform the plan's test root indicates, not the
    whole repo — so the runner is detected the same way.
    """
    dirs = []
    if test_root:
        cur = os.path.dirname(os.path.join(repo, test_root.rstrip("/")))
        while cur.startswith(repo) and len(cur) > len(repo):
            dirs.append(cur)
            cur = os.path.dirname(cur)
    dirs.append(repo)
    seen, out = set(), []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _json_file(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def detect_host_runner(repo: str, test_root: str | None = None) -> str | None:
    """The suite command as it runs on the host. Recorded ALWAYS, Docker or not —
    phase 10's pr-grind runs hours after Teardown and has nothing else to use."""
    for d in package_dirs(repo, test_root):
        has = lambda *p: os.path.exists(os.path.join(d, *p))  # noqa: E731

        pkg = _json_file(os.path.join(d, "package.json"))
        if pkg is not None and (pkg.get("scripts") or {}).get("test"):
            if has("pnpm-lock.yaml"):
                return "pnpm test"
            if has("yarn.lock"):
                return "yarn test"
            if has("bun.lockb"):
                return "bun test"
            return "npm test"

        composer = _json_file(os.path.join(d, "composer.json"))
        if composer is not None:
            if (composer.get("scripts") or {}).get("test"):
                return "composer test"
            if has("artisan"):
                return "php artisan test"
            if has("vendor", "bin", "pest"):
                return "vendor/bin/pest"
            if has("phpunit.xml") or has("phpunit.xml.dist"):
                return "vendor/bin/phpunit"

        if has("pytest.ini") or has("tox.ini") or has("pyproject.toml") or has("setup.cfg"):
            return "pytest"
        if has("go.mod"):
            return "go test ./..."
        if has("pubspec.yaml"):
            pub = ""
            try:
                with open(os.path.join(d, "pubspec.yaml"), encoding="utf-8") as fh:
                    pub = fh.read()
            except OSError:
                pass
            return "flutter test" if "flutter:" in pub else "dart test"
    return None


def cap_workers(cmd: str) -> str:
    """Stop the runner spawning one worker per core — the single biggest CPU driver
    observed on a prior run. Only caps runners named directly in the command; a
    `npm test` that hides vitest behind a script cannot be capped from out here."""
    low = cmd.lower()
    if "--parallel" in low and "--processes" not in low:
        return cmd + " --processes=2"
    if ("vitest" in low or "jest" in low) and "--maxworkers" not in low:
        return cmd + " --maxWorkers=2"
    return cmd


def find_compose_file(repo: str, test_root: str | None = None) -> str | None:
    for d in package_dirs(repo, test_root):
        for name in COMPOSE_CANDIDATES:
            path = os.path.join(d, name)
            if os.path.isfile(path):
                return os.path.relpath(path, repo)
    return None


def is_datastore(name: str) -> bool:
    low = name.lower()
    return any(hint in low for hint in DATASTORE_HINTS)


def limits_override(services: list[str]) -> dict:
    """One `deploy.resources.limits` entry per service. Compose v2 honours these
    outside swarm mode.

    ponytail: written as JSON into a .yml file — JSON is a YAML subset, so this
    needs no yaml dependency and cannot emit invalid indentation.
    """
    out = {}
    for name in services:
        small = is_datastore(name)
        out[name] = {
            "deploy": {
                "resources": {
                    "limits": {
                        "cpus": "1.0" if small else "1.5",
                        "memory": "768m" if small else "1g",
                    }
                }
            }
        }
    return {"services": out}


def pick_app_service(config: dict) -> str | None:
    """The service the suite runs in: something that builds, preferring an app-ish
    name, and never a datastore."""
    services = config.get("services") or {}
    if not services:
        return None
    buildable = [n for n, s in services.items() if s.get("build") and not is_datastore(n)]
    pool = buildable or [n for n in services if not is_datastore(n)] or list(services)
    for hint in APP_HINTS:
        for name in pool:
            if hint in name.lower():
                return name
    return pool[0]


def pick_api_web_services(config: dict) -> tuple[str | None, str | None]:
    """When the compose file exposes two distinct buildable app services, tell them
    apart by name so phase 4.5 can address the API and the web app separately.

    Returns (api_service, web_service), either or both None. Deliberately silent
    (not a fallback to `app`) when there is only one buildable service — that case
    is `app_url` alone, unchanged, so a single-service repo sees no new behaviour.
    """
    services = config.get("services") or {}
    buildable = [n for n, s in services.items() if s.get("build") and not is_datastore(n)]
    if len(buildable) < 2:
        return None, None

    def first_match(hints):
        for hint in hints:
            for name in buildable:
                if hint in name.lower():
                    return name
        return None

    api = first_match(API_HINTS)
    web = first_match(WEB_HINTS)
    if api and web and api != web:
        return api, web
    return None, None


def source_is_mounted(config: dict, app: str, repo: str) -> bool:
    """True when the worktree is bind-mounted into the app container, i.e. code
    changes are live and no rebuild is ever needed this run."""
    repo = os.path.realpath(repo)
    for vol in (config.get("services") or {}).get(app, {}).get("volumes") or []:
        if isinstance(vol, str):
            src = vol.split(":", 1)[0]
        elif vol.get("type") == "bind":
            src = vol.get("source") or ""
        else:
            continue
        if not src:
            continue
        src = os.path.realpath(os.path.join(repo, os.path.expanduser(src)))
        if src == repo or src.startswith(repo + os.sep):
            return True
    return False


def published_port(config: dict, app: str) -> str | None:
    for port in (config.get("services") or {}).get(app, {}).get("ports") or []:
        if isinstance(port, str):
            parts = port.split(":")
            if len(parts) >= 2:
                return parts[-2]
        elif port.get("published"):
            return str(port["published"])
    return None


def build_test_cmd(compose_prefix: str, app: str, runner: str) -> str:
    """`exec` against the already-running container, never `run` — a `run` spawns a
    second container per invocation and (without --rm) leaks them."""
    return f"{compose_prefix} exec -T {app} {cap_workers(runner)}"


# --------------------------------------------------------------------------- I/O


def compose_config(repo: str, compose_file: str) -> dict | None:
    proc = run(["docker", "compose", "-f", compose_file, "config", "--format", "json"], cwd=repo)
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def write_override(repo: str, compose_file: str) -> bool:
    """Best-effort: a missing override costs resource caps, not the run."""
    proc = run(["docker", "compose", "-f", compose_file, "config", "--services"], cwd=repo)
    if proc.returncode != 0:
        warn("could not list compose services; continuing without resource limits")
        return False
    services = [s.strip() for s in proc.stdout.splitlines() if s.strip()]
    if not services:
        return False
    with open(os.path.join(repo, ".docker-agent.yml"), "w", encoding="utf-8") as fh:
        json.dump(limits_override(services), fh, indent=2)
        fh.write("\n")
    return True


def cmd_up(args) -> None:
    """Records `app_url` as always. `api_url`/`web_url` are the same address on a
    single-service stack; they split apart only when `pick_api_web_services` finds
    two distinct buildable app services — phase 4.5 is the only reader of the split."""
    ledger = load_ledger(args.run_dir)
    repo = repo_of(ledger, args.repo)
    test_root = ledger.context.get("test_root")

    runner = detect_host_runner(repo, test_root)
    if not runner:
        warn("no host test runner detected — stations will be told there is none")

    compose_file = find_compose_file(repo, test_root)
    if not compose_file or not runner:
        # Not a degraded state: most repos have no test compose file, and the run is
        # expected to work exactly as well on them.
        print_written(record(
            args.run_dir, ledger,
            stack="none", test_cmd_host=runner or "", test_cmd=runner or "",
            # source_mounted=yes with no stack is not a claim about a mount: it is what
            # makes `stack rebuild` a no-op, so no phase has to special-case "no Docker".
            app_url="none", api_url="none", web_url="none",
            source_mounted="yes", compose_prefix="",
            tests_unverified="" if runner else "no test runner detected on the host",
        ))
        return

    lock_timeout = getattr(args, "lock_timeout", LOCK_TIMEOUT)
    if not acquire_lock(args.run_dir, ledger.issue, repo, lock_timeout):
        holder = _read_holder(lock_path()) or {}
        who = holder.get("run_dir") or "another run"
        print_written(record(
            args.run_dir, ledger,
            stack="failed", compose_prefix="", test_cmd="", test_cmd_host=runner,
            app_url="none", api_url="none", web_url="none", source_mounted="no",
            tests_unverified=f"stack lock held by {who}; timed out after {lock_timeout}s",
        ))
        # Exit 0 on purpose, same contract as every other degraded stack state.
        return

    prefix = f"docker compose -p runissue-{ledger.issue} -f {compose_file}"
    if write_override(repo, compose_file):
        prefix += " -f .docker-agent.yml"

    proc = shell(f"{prefix} up -d --build --wait", cwd=repo, timeout=UP_TIMEOUT)
    if proc.returncode != 0:
        # One retry: a first --build on a cold cache times out often enough that a
        # retry is worth more than a stopped run.
        warn("stack failed to come up; retrying once")
        proc = shell(f"{prefix} up -d --build --wait", cwd=repo, timeout=UP_TIMEOUT)
    if proc.returncode != 0:
        shell(f"{prefix} down -v --remove-orphans", cwd=repo, timeout=UP_TIMEOUT)
        release_lock(args.run_dir)
        reason = (proc.stderr or proc.stdout or "unknown").strip().splitlines()
        print_written(record(
            args.run_dir, ledger,
            stack="failed", compose_prefix=prefix, test_cmd="", test_cmd_host=runner,
            app_url="none", api_url="none", web_url="none", source_mounted="no",
            tests_unverified="docker stack would not come up: " + (reason[-1] if reason else "?"),
        ))
        # Exit 0 on purpose: a stack that will not come up is a documented run state
        # that every station knows how to report, not a failure of this command.
        return

    config = compose_config(repo, compose_file) or {}
    app = pick_app_service(config)
    if not app:
        warn("stack is up but no app service could be identified; treating tests as unrunnable")
        print_written(record(
            args.run_dir, ledger, stack="failed", compose_prefix=prefix, test_cmd="",
            test_cmd_host=runner, app_url="none", api_url="none", web_url="none",
            source_mounted="no",
            tests_unverified="no app service found in the test compose file",
        ))
        return

    port = published_port(config, app)

    # Best-effort second address for phase 4.5's backend/frontend routing. A single-
    # service repo (the common case) gets api_url=web_url=app_url — the same address,
    # so a mode that asks for either one gets today's behaviour unchanged.
    api_service, web_service = pick_api_web_services(config)
    app_url = f"http://localhost:{port}" if port else "none"
    api_port = published_port(config, api_service) if api_service else port
    web_port = published_port(config, web_service) if web_service else port
    api_url = f"http://localhost:{api_port}" if api_port else app_url
    web_url = f"http://localhost:{web_port}" if web_port else app_url

    print_written(record(
        args.run_dir, ledger,
        stack="up",
        compose_prefix=prefix,
        app_service=app,
        test_cmd=build_test_cmd(prefix, app, runner),
        test_cmd_host=runner,
        source_mounted="yes" if source_is_mounted(config, app, repo) else "no",
        app_url=app_url,
        api_url=api_url,
        web_url=web_url,
        tests_unverified="",
    ))


def cmd_down(args) -> None:
    """Teardown. Best-effort by contract — always exits 0, so it can be called from
    every exit path without any of them having to guard it."""
    ledger = load_ledger(args.run_dir)
    prefix = ledger.context.get("compose_prefix")
    if not prefix or ledger.context.get("stack") == "none":
        release_lock(args.run_dir)
        print("no stack to tear down")
        return
    proc = shell(f"{prefix} down -v --remove-orphans", cwd=repo_of(ledger, args.repo), timeout=UP_TIMEOUT)
    release_lock(args.run_dir)
    if proc.returncode != 0:
        warn("teardown failed: " + (proc.stderr or "").strip()[:200])
        return
    print("stack down")


def app_healthy(ledger, repo: str) -> tuple[bool, str]:
    """Is the app container actually running? A green suite from a dead or stale
    container is the failure mode source_mounted only tiptoes around."""
    prefix = ledger.context.get("compose_prefix")
    app = ledger.context.get("app_service")
    if not prefix or not app:
        return False, "no stack recorded"
    proc = shell(f"{prefix} ps --format json {app}", cwd=repo, timeout=60)
    if proc.returncode != 0:
        return False, "compose ps failed: " + (proc.stderr or "").strip()[:120]
    rows = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows.extend(parsed if isinstance(parsed, list) else [parsed])
    if not rows:
        return False, f"service {app} is not running"
    row = rows[0]
    state = (row.get("State") or "").lower()
    health = (row.get("Health") or "").lower()
    if state != "running":
        return False, f"service {app} is {state or 'unknown'}"
    if health and health not in ("healthy", "none"):
        return False, f"service {app} is {health}"
    return True, f"service {app} is running"


def cmd_status(args) -> None:
    ledger = load_ledger(args.run_dir)
    if ledger.context.get("stack") != "up":
        print(f"stack={ledger.context.get('stack') or 'unknown'}")
        return
    ok, reason = app_healthy(ledger, repo_of(ledger, args.repo))
    print(("healthy: " if ok else "unhealthy: ") + reason)
    if not ok:
        raise SystemExit(1)


def cmd_rebuild(args) -> None:
    """The three identical 'if source_mounted: no, rebuild then re-run test_cmd'
    blocks in phases 4, 7 and 8. No-ops when the source is mounted, so the
    condition stops being the orchestrator's to remember."""
    ledger = load_ledger(args.run_dir)
    repo = repo_of(ledger, args.repo)
    if ledger.context.get("stack") != "up":
        print("no stack to rebuild")
        return
    if ledger.context.get("source_mounted") == "yes":
        print("source is mounted — no rebuild needed")
        return
    prefix = ledger.context["compose_prefix"]
    app = ledger.context.get("app_service") or ""
    proc = shell(f"{prefix} up -d --build --wait {app}".rstrip(), cwd=repo, timeout=UP_TIMEOUT)
    if proc.returncode != 0:
        die(1, "rebuild failed: " + (proc.stderr or proc.stdout or "").strip()[:300])
    print(f"rebuilt {app}")


def register(sub, add) -> None:
    p = sub.add_parser("stack", help="bring the per-issue test stack up, down, or check it")
    ops = p.add_subparsers(dest="op", required=True)
    for name, fn, helptext in (
        ("up", cmd_up, "detect, start and record the test stack"),
        ("down", cmd_down, "tear it down (best-effort, always exits 0)"),
        ("rebuild", cmd_rebuild, "rebuild the app image when the source is not mounted"),
        ("status", cmd_status, "report whether the app service is healthy"),
    ):
        q = ops.add_parser(name, help=helptext)
        q.add_argument("run_dir")
        q.add_argument("--repo", help="repo/worktree root (default: ledger context, else cwd)")
        if name == "up":
            q.add_argument(
                "--lock-timeout", type=int, default=LOCK_TIMEOUT, dest="lock_timeout",
                help="seconds to wait for the stack lock before degrading (default: 900)",
            )
        q.set_defaults(func=fn)
