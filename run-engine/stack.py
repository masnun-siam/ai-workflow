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

import hashlib
import json
import os
import re
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

# The `.break` sentinel that gates a stale-lock reclaim (see acquire_lock)
# only ever needs to exist for the handful of local filesystem calls between
# creating it and removing it — no network I/O, no waiting. If one is ever
# found older than this, its creator crashed mid-break; it's safe to treat
# it as abandoned and clear it rather than wedging every future reclaim.
BREAK_SENTINEL_STALE = 30  # seconds

_LOCK_GUARD = threading.Lock()  # serializes the read-check-write within this process


def compose_project(repo: str, issue: int) -> str:
    """Deterministic Compose project name AND per-project lock key:
    `runissue-<repo-slug>-<digest>-<issue>`. Replaces the old `runissue-<issue>`
    (name-only, no repo component), which made the same issue number in two
    different repos collide on one Compose project. The digest (of the full repo
    path) keeps two repos that happen to share a directory basename from
    colliding too, while the slug keeps `docker compose ls` readable.
    """
    norm = os.path.normpath(repo)
    base = os.path.basename(norm) or "repo"
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-") or "repo"
    digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:8]
    return f"runissue-{slug}-{digest}-{issue}"


def lock_path(project: str) -> str:
    return os.path.join(data_dir(), "locks", f"{project}.lock")


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


def _break_sentinel_path(path: str) -> str:
    return f"{path}.break"


def _reclaim_stale_break_sentinel(break_path: str) -> None:
    """Best-effort: clear a `.break` sentinel abandoned mid-break (its creator
    crashed between creating it and removing it in the `finally` below).

    Tolerant of the file changing or vanishing between the two checks and the
    remove: a fresh mtime read right before removing, plus a swallowed
    FileNotFoundError, means the narrow window here can only ever no-op
    (leave a live sentinel alone) or delete one that's still provably stale
    at the moment of removal — never a sentinel a different contender just
    created out from under us.
    """
    try:
        st = os.stat(break_path)
    except OSError:
        return  # already gone
    if time.time() - st.st_mtime <= BREAK_SENTINEL_STALE:
        return
    try:
        st2 = os.stat(break_path)
        if st2.st_mtime != st.st_mtime:
            return  # replaced since the first check; its new owner is live
        os.remove(break_path)
    except FileNotFoundError:
        pass  # someone else already cleared it — fine
    except OSError:
        pass


def _with_break_sentinel(path: str, action):
    """Run `action` while holding exclusive rights to mutate `path`, gated by
    the `.break` sentinel: only the contender that wins the O_EXCL create of
    `path.break` may touch `path` at all. Returns `action`'s return value if
    it ran, `None` if it did not (sentinel already held elsewhere).

    This is the ONLY way `path` is ever written or removed, by acquire_lock
    or release_lock — a read-check-then-mutate with nothing atomic between
    the two syscalls lets two callers race each other's decisions (round-3
    review found this for release_lock; a second, narrower version of the
    same TOCTOU also turned up between a reclaim's stale-check and its
    `os.remove` racing a concurrent fresh publish, caught by this fix's own
    40-trial race harness). Funnelling every mutation through one sentinel
    closes both: at most one process is ever deciding-and-writing `path` at
    a time, full stop.

    Non-blocking: if the sentinel is already held, someone else is mutating
    `path` right now and will resolve it on their own, so the loser just
    returns instead of waiting — callers retry/back off on the outside.
    """
    break_path = _break_sentinel_path(path)
    try:
        bfd = os.open(break_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        _reclaim_stale_break_sentinel(break_path)  # best-effort unwedge
        return None
    except OSError:
        return None  # can't write the sentinel at all

    os.close(bfd)
    try:
        return action()
    finally:
        try:
            os.remove(break_path)
        except OSError:
            pass


def _write_holder(path: str, holder: dict) -> None:
    """Publish `holder` at `path`, atomically replacing whatever is there
    (or creating it fresh). Only ever called from inside a
    `_with_break_sentinel` action, so nothing else can be reading or writing
    `path` at the same moment — `os.replace` (an atomic rename on the same
    filesystem) then means every reader sees either the old content or the
    new, complete content, never a half-written or empty file."""
    tmp_path = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(holder))
    os.replace(tmp_path, path)


def acquire_lock(run_dir: str, issue: int, repo: str, timeout: int) -> bool:
    """Acquire the stack lock for `repo`+`issue`'s Compose project. Re-entrant: a
    run already holding it (pr-grind's second `stack up`) never blocks on itself.

    Keyed per-project (via `compose_project`), not globally: two unrelated runs —
    different issues, or the same issue number in different repos — never
    contend for the same lock file. Only a second `stack up` racing the *same*
    project still serializes here.

    The real contenders are separate `aiw stack up` OS processes, which share
    nothing but the filesystem — so exclusion has to be an OS-level atomic
    operation, not a process-local `threading.Lock` (that only ever serializes
    threads inside one interpreter). Every decision that could end in writing
    or removing the lock file — "is it free", "is it stale", "publish mine" —
    happens as one unit inside `_with_break_sentinel`, so it can't be
    interleaved with another acquire_lock or release_lock call deciding the
    same thing about the same file at the same time.

    Fails OPEN on an unwritable data dir — a lock that cannot be written must
    not fail the run, it just stops protecting it.
    """
    path = lock_path(compose_project(repo, issue))
    deadline = time.time() + max(timeout, 0)
    while True:
        # Cheap common case, no exclusion needed: we already hold this lock
        # (pr-grind's second `stack up`). A plain read can't race with our
        # own prior write in any way that matters — nobody else ever writes
        # our run_dir as the holder.
        current = _read_holder(path)
        if current is not None and current.get("run_dir") == run_dir:
            return True

        with _LOCK_GUARD:  # still serializes threads within this process
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
            except OSError as exc:
                warn(f"stack lock directory is not writable ({exc}); proceeding unlocked")
                return True

            holder = {"run_dir": run_dir, "issue": issue, "repo": repo, "acquired_at": time.time()}

            def _decide_and_publish(path=path, run_dir=run_dir, holder=holder):
                current = _read_holder(path)
                if current is not None and current.get("run_dir") == run_dir:
                    return True  # became ours between the fast check and the sentinel
                if current is not None and not lock_stale(current, time.time()):
                    return False  # a live holder — not ours to take
                try:
                    _write_holder(path, holder)
                except OSError as exc:
                    warn(f"stack lock file is not writable ({exc}); proceeding unlocked")
                return True

            outcome = _with_break_sentinel(path, _decide_and_publish)
            if outcome:
                return True
            # outcome is None (lost the sentinel to another acquire_lock or
            # release_lock call deciding this same instant) or False (a
            # live, non-stale holder) — either way, back off and retry.
        if time.time() >= deadline:
            return False
        time.sleep(min(LOCK_POLL, max(deadline - time.time(), 0)))


RELEASE_SENTINEL_RETRIES = 3  # bounded attempts to win the sentinel, not to wait out a live holder
RELEASE_SENTINEL_BACKOFF = 0.05  # seconds between attempts; keeps stack down fast


def release_lock(run_dir: str, issue: int, repo: str) -> None:
    """Best-effort: only removes the lockfile when `run_dir` is the recorded
    holder, so a stale/foreign release can never drop another run's lock.
    `issue`/`repo` must match the pair `acquire_lock` was called with — they
    resolve to the same `compose_project` key, hence the same lock file.

    Gated behind the same `.break` sentinel acquire_lock uses for every
    mutation of the lock file. Without it, this is a bare
    read-check-then-remove with nothing atomic between the two syscalls: a
    contender can read the same (stale) holder as this call, win a reclaim
    race, and install its own fresh lock in the gap before this call's
    `os.remove` runs — which then deletes the new lock, not the one this
    call actually meant to release (round-3 review, reproduced 1/40 trials
    with a concurrent release).

    Bounded retry, since `stack down` must never hang: if the sentinel is
    already held, this makes a few short-backoff attempts to win it before
    giving up (round-4 review — a single non-blocking attempt could lose to
    mere contention noise, not just a genuine break-in-progress, and leave
    the lockfile behind with nobody now clearing it; the next contender then
    waits out the full LOCK_GRACE window for nothing). If every attempt still
    loses the sentinel, this returns without doing anything further — never
    fails, never blocks indefinitely.
    """
    path = lock_path(compose_project(repo, issue))

    def _release(path=path, run_dir=run_dir):
        holder = _read_holder(path)
        if holder is not None and holder.get("run_dir") == run_dir:
            try:
                os.remove(path)
            except OSError:
                pass
        return True  # ran to completion — distinguishes from "sentinel not won"

    for attempt in range(RELEASE_SENTINEL_RETRIES):
        if _with_break_sentinel(path, _release) is True:
            return
        if attempt < RELEASE_SENTINEL_RETRIES - 1:
            time.sleep(RELEASE_SENTINEL_BACKOFF)


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


def limits_override(services: list[str], config: dict | None = None) -> dict:
    """One `deploy.resources.limits` entry per service, plus (when `config` is given)
    a `ports: ["0:<container-port>", ...]` entry per service that publishes any —
    forcing the OS to hand out a free host port instead of the declared one, so two
    stacks with the same compose file never collide on a host port. `published_port`
    reads the real, kernel-assigned port back after `up --wait`.

    ponytail: written as JSON into a .yml file — JSON is a YAML subset, so this
    needs no yaml dependency and cannot emit invalid indentation.
    """
    config = config or {}
    out = {}
    for name in services:
        small = is_datastore(name)
        entry = {
            "deploy": {
                "resources": {
                    "limits": {
                        "cpus": "1.0" if small else "1.5",
                        "memory": "768m" if small else "1g",
                    }
                }
            }
        }
        ports = container_ports(config, name)
        if ports:
            entry["ports"] = [f"0:{p}" for p in ports]
        out[name] = entry
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


def container_ports(config: dict, service: str | None) -> list[str]:
    """The container-side ("target") ports a service declares, in declaration
    order. Parses both the short form (`"8080:80"`, bare `"80"`) and the long
    form (`{"target": 80, "published": ...}`). This is the container-port
    argument `docker compose port` needs — once every port is force-published
    to `0` (see `limits_override`), the declared host side is meaningless."""
    if not service:
        return []
    out = []
    for port in (config.get("services") or {}).get(service, {}).get("ports") or []:
        if isinstance(port, str):
            target = port.split(":")[-1].split("/")[0]
            if target:
                out.append(target)
        elif isinstance(port, dict) and port.get("target") is not None:
            out.append(str(port["target"]))
    return out


def resolve_port(compose_prefix: str, repo: str, service: str, container_port: str) -> str | None:
    """The live, kernel-assigned host port bound for `service`'s `container_port`.
    Reads it back via `docker compose port` — the only way to learn what the OS
    actually bound now that every declared port is published to `0`."""
    proc = shell(f"{compose_prefix} port {service} {container_port}", cwd=repo, timeout=30)
    if proc.returncode != 0:
        return None
    out = (proc.stdout or "").strip()
    if ":" not in out:
        return None
    port = out.rsplit(":", 1)[-1].strip()
    return port or None


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


def write_override(repo: str, config: dict) -> bool:
    """Best-effort: a missing override costs resource caps and port isolation,
    not the run. `config` is `compose_config()`'s already-parsed output — no
    second `docker compose config` call needed just to list services."""
    services = list((config.get("services") or {}).keys())
    if not services:
        return False
    with open(os.path.join(repo, ".docker-agent.yml"), "w", encoding="utf-8") as fh:
        json.dump(limits_override(services, config), fh, indent=2)
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
    project = compose_project(repo, ledger.issue)
    if not acquire_lock(args.run_dir, ledger.issue, repo, lock_timeout):
        holder = _read_holder(lock_path(project)) or {}
        who = holder.get("run_dir") or "another run"
        print_written(record(
            args.run_dir, ledger,
            stack="failed", compose_prefix="", test_cmd="", test_cmd_host=runner,
            app_url="none", api_url="none", web_url="none", source_mounted="no",
            tests_unverified=f"stack lock held by {who}; timed out after {lock_timeout}s",
        ))
        # Exit 0 on purpose, same contract as every other degraded stack state.
        return

    config = compose_config(repo, compose_file) or {}
    prefix = f"docker compose -p {project} -f {compose_file}"
    if write_override(repo, config):
        prefix += " -f .docker-agent.yml"

    proc = shell(f"{prefix} up -d --build --wait", cwd=repo, timeout=UP_TIMEOUT)
    if proc.returncode != 0:
        # One retry: a first --build on a cold cache times out often enough that a
        # retry is worth more than a stopped run.
        warn("stack failed to come up; retrying once")
        proc = shell(f"{prefix} up -d --build --wait", cwd=repo, timeout=UP_TIMEOUT)
    if proc.returncode != 0:
        shell(f"{prefix} down -v --remove-orphans", cwd=repo, timeout=UP_TIMEOUT)
        release_lock(args.run_dir, ledger.issue, repo)
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

    app = pick_app_service(config)
    if not app:
        warn("stack is up but no app service could be identified; treating tests as unrunnable")
        shell(f"{prefix} down -v --remove-orphans", cwd=repo, timeout=UP_TIMEOUT)
        release_lock(args.run_dir, ledger.issue, repo)
        print_written(record(
            args.run_dir, ledger, stack="failed", compose_prefix=prefix, test_cmd="",
            test_cmd_host=runner, app_url="none", api_url="none", web_url="none",
            source_mounted="no",
            tests_unverified="no app service found in the test compose file",
        ))
        return

    app_port = container_ports(config, app)
    port = resolve_port(prefix, repo, app, app_port[0]) if app_port else None

    # Best-effort second address for phase 4.5's backend/frontend routing. A single-
    # service repo (the common case) gets api_url=web_url=app_url — the same address,
    # so a mode that asks for either one gets today's behaviour unchanged.
    api_service, web_service = pick_api_web_services(config)
    api_container_port = container_ports(config, api_service)
    web_container_port = container_ports(config, web_service)
    api_port = resolve_port(prefix, repo, api_service, api_container_port[0]) \
        if api_service and api_container_port else port
    web_port = resolve_port(prefix, repo, web_service, web_container_port[0]) \
        if web_service and web_container_port else port

    app_url = f"http://localhost:{port}" if port else "none"
    api_url = f"http://localhost:{api_port}" if api_port else app_url
    web_url = f"http://localhost:{web_port}" if web_port else app_url

    print_written(record(
        args.run_dir, ledger,
        stack="up",
        compose_prefix=prefix,
        compose_project=project,
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
    repo = repo_of(ledger, args.repo)
    prefix = ledger.context.get("compose_prefix")
    if not prefix or ledger.context.get("stack") == "none":
        release_lock(args.run_dir, ledger.issue, repo)
        print("no stack to tear down")
        return
    proc = shell(f"{prefix} down -v --remove-orphans", cwd=repo, timeout=UP_TIMEOUT)
    release_lock(args.run_dir, ledger.issue, repo)
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
