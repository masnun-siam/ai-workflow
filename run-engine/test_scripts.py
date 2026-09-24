#!/usr/bin/env python3
"""Self-check for the mechanical subcommands. `python3 test_scripts.py` — exit 0 = green.

Same shape as test_engine.py: assert-based, no framework, no install step. These
modules do I/O, so what is covered here is the DECISIONS inside them — which runner,
which app service, which limits, which option name — plus the promise that the
best-effort subcommands cannot stop a run. Nothing here touches Docker or the network.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ci  # noqa: E402
import dispatch  # noqa: E402
import epic  # noqa: E402
import project  # noqa: E402
import review  # noqa: E402
import shared  # noqa: E402
import stack  # noqa: E402
import threads  # noqa: E402
import worktree  # noqa: E402
from engine import Ledger  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROUTE = os.path.join(HERE, "route.py")

passed = 0


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


def write(root: str, rel: str, body: str = "{}") -> None:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path) or root, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


# --------------------------------------------------------------------------- runner

with tempfile.TemporaryDirectory() as d:
    write(d, "package.json", json.dumps({"scripts": {"test": "vitest run"}}))
    write(d, "package-lock.json")
    assert stack.detect_host_runner(d) == "npm test"
    write(d, "pnpm-lock.yaml", "")
    assert stack.detect_host_runner(d) == "pnpm test"
ok("host runner follows the lockfile, not the package manager you'd guess")

with tempfile.TemporaryDirectory() as d:
    write(d, "composer.json", json.dumps({"require": {}}))
    write(d, "artisan", "")
    assert stack.detect_host_runner(d) == "php artisan test"
    write(d, "composer.json", json.dumps({"scripts": {"test": "pest"}}))
    assert stack.detect_host_runner(d) == "composer test"
ok("php runner prefers a declared composer script over artisan")

with tempfile.TemporaryDirectory() as d:
    # monorepo: the test root's own package wins over the repo root
    write(d, "go.mod", "module x")
    write(d, "apps/web/package.json", json.dumps({"scripts": {"test": "vitest"}}))
    write(d, "apps/web/package-lock.json")
    assert stack.detect_host_runner(d, "apps/web/tests") == "npm test"
    assert stack.detect_host_runner(d) == "go test ./..."
ok("monorepo runner is detected for the test root's package, not the whole repo")

assert stack.cap_workers("vendor/bin/pest --parallel") == "vendor/bin/pest --parallel --processes=2"
assert stack.cap_workers("npx vitest run") == "npx vitest run --maxWorkers=2"
assert stack.cap_workers("npx vitest --maxWorkers=4") == "npx vitest --maxWorkers=4"
assert stack.cap_workers("pytest") == "pytest"
ok("worker caps are applied once, and never override one already set")

# --------------------------------------------------------------------------- compose

override = stack.limits_override(["app", "postgres", "redis", "queue"])["services"]
assert override["app"]["deploy"]["resources"]["limits"] == {"cpus": "1.5", "memory": "1g"}
assert override["postgres"]["deploy"]["resources"]["limits"] == {"cpus": "1.0", "memory": "768m"}
assert override["redis"]["deploy"]["resources"]["limits"]["memory"] == "768m"
# unrecognised service is treated as a datastore's sibling app share, not unlimited
assert override["queue"]["deploy"]["resources"]["limits"]["cpus"] == "1.5"
assert json.loads(json.dumps(override)), "the override must be JSON, which is valid YAML"
ok("limits override gives the app more than a datastore and never omits a service")

CONFIG = {
    "services": {
        "postgres": {"image": "postgres:16"},
        "laravel.test": {"build": {"context": "."}, "ports": [{"published": "8080", "target": 80}],
                         "volumes": [{"type": "bind", "source": "/repo", "target": "/var/www"}]},
        "redis": {"image": "redis"},
    }
}
assert stack.pick_app_service(CONFIG) == "laravel.test"
assert stack.container_ports(CONFIG, "laravel.test") == ["80"]
assert stack.container_ports(CONFIG, "postgres") == []
assert stack.container_ports(CONFIG, None) == []
assert stack.source_is_mounted(CONFIG, "laravel.test", "/repo") is True
assert stack.source_is_mounted(CONFIG, "laravel.test", "/elsewhere") is False
assert stack.pick_app_service({"services": {"postgres": {"image": "postgres"}}}) == "postgres"
ok("app service, container port and source mount are read off `compose config`")

MULTI_PORT_CONFIG = {
    "services": {
        "app": {"build": {"context": "."}, "ports": ["8080:80", "9000:9090/tcp"]},
    }
}
assert stack.container_ports(MULTI_PORT_CONFIG, "app") == ["80", "9090"], \
    "both published ports must resolve, not just the first"
ok("container_ports resolves every published port for a service, not just the first")

with_ports_override = stack.limits_override(["app", "postgres"], MULTI_PORT_CONFIG)["services"]
assert with_ports_override["app"]["ports"] == ["0:80", "0:9090"], \
    "every declared port is force-published to 0 so a second stack can't collide on it"
assert "ports" not in with_ports_override["postgres"], \
    "a service with no declared ports gets no ports override at all"
ok("limits_override force-publishes every declared port to an OS-chosen host port")

assert stack.build_test_cmd("docker compose -p runissue-9 -f c.yml", "app", "npx vitest") == \
    "docker compose -p runissue-9 -f c.yml exec -T app npx vitest --maxWorkers=2"
ok("test_cmd execs against the running container with the worker cap applied")

# --------------------------------------------------------------------------- api/web split

MONOREPO = {
    "services": {
        "postgres": {"image": "postgres:16"},
        "api": {"build": {"context": "./api"}, "ports": [{"published": "8000", "target": 80}]},
        "web": {"build": {"context": "./web"}, "ports": [{"published": "3000", "target": 3000}]},
    }
}
assert stack.pick_api_web_services(MONOREPO) == ("api", "web")
assert stack.pick_api_web_services(CONFIG) == (None, None), \
    "a single buildable app service must not be split — app_url alone covers it"
assert stack.pick_api_web_services({"services": {"postgres": {"image": "postgres"}}}) == (None, None)
ok("two distinct buildable services split into (api, web); one service never does")

# --------------------------------------------------------------------------- stack=none

with tempfile.TemporaryDirectory() as d:
    repo, run_dir = os.path.join(d, "repo"), os.path.join(d, "run")
    os.makedirs(repo)
    write(repo, "go.mod", "module x")
    ledger = Ledger(7, ["dev"])
    ledger.context["repo"] = repo
    os.makedirs(run_dir)
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(ledger.to_dict(), fh)

    proc = subprocess.run([sys.executable, ROUTE, "stack", "up", run_dir],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    ctx = json.load(open(os.path.join(run_dir, "run.json")))["context"]
    assert ctx["stack"] == "none"
    assert ctx["test_cmd"] == ctx["test_cmd_host"] == "go test ./..."
    assert ctx["app_url"] == "none"

    # Teardown on a repo that never had a stack is a no-op, not an error — it is
    # called from every exit path and none of them guards it.
    down = subprocess.run([sys.executable, ROUTE, "stack", "down", run_dir],
                          capture_output=True, text=True)
    assert down.returncode == 0, down.stderr
    rebuild = subprocess.run([sys.executable, ROUTE, "stack", "rebuild", run_dir],
                             capture_output=True, text=True)
    assert rebuild.returncode == 0, rebuild.stderr
ok("no compose file -> stack=none, test_cmd==test_cmd_host, and teardown still exits 0")

# --------------------------------------------------------------------------- threads

THREADS = [
    {"node_id": "PRRT_a", "is_resolved": False, "comment_id": 111, "url": "u1"},
    {"node_id": "PRRT_b", "is_resolved": True, "comment_id": 222, "url": "u2"},
]
assert threads.thread_for_comment(THREADS, 222)["node_id"] == "PRRT_b"
assert threads.thread_for_comment(THREADS, "111")["node_id"] == "PRRT_a"
assert threads.thread_for_comment(THREADS, 999) is None
assert threads.thread_for_comment(THREADS, None) is None
ok("a review thread is matched by its first comment's REST id, string or int")

# --------------------------------------------------------------------------- ci

assert ci.state_of([{"bucket": "pass"}, {"bucket": "fail"}, {"bucket": "pending"}]) == "pending", \
    "a still-running check is not a verdict"
assert ci.state_of([{"bucket": "pass"}, {"bucket": "fail"}]) == "red"
assert ci.state_of([{"bucket": "pass"}, {"bucket": "skipping"}]) == "green"
assert ci.state_of([]) == "green"
assert ci.run_id_of("https://github.com/o/r/actions/runs/123456/job/99") == "123456"
assert ci.run_id_of("https://example.test/nothing") == ""
assert ci.run_id_of(None) == ""
ok("ci state puts pending ahead of failing, and the run id comes out of the check link")

# --------------------------------------------------------------------------- project

OPTIONS = [{"id": "o1", "name": "Todo"}, {"id": "o2", "name": "On Review"},
           {"id": "o3", "name": "In Progress"}]
assert project.match_option(OPTIONS, "Todo")["id"] == "o1"
# neither string contains the other, which is why a plain substring test is not enough
assert project.match_option(OPTIONS, "In Review")["id"] == "o2"
assert project.match_option(OPTIONS, "In Progress")["id"] == "o3"
assert project.match_option(OPTIONS, "Blocked") is None
assert project.match_option(OPTIONS, "In") is None, "a filler-only target must not match everything"
ok("project status matches the exact option, then the best significant-word overlap")

# --------------------------------------------------------------------------- epic board

VIEWS = [{"id": "V1", "name": "Board"}, {"id": "V2", "name": "Epic #42 — Billing"}]
assert project.find_view(VIEWS, "Epic #42 — Billing")["id"] == "V2"
assert project.find_view(VIEWS, "Epic #43 — Other") is None
assert project.find_view([], "Epic #42 — Billing") is None
ok("an existing epic board is found by name, so a resume never creates a second")

assert project.board_name(42, "Billing overhaul") == "Epic #42 — Billing overhaul"
assert project.board_name(42, "x" * 200).startswith("Epic #42 — ")
assert len(project.board_name(42, "x" * 200)) <= 80, "view names must stay readable"
ok("board names are derived from the parent and bounded in length")

# project-board exits 0 even with a malformed slug (no `/`)
env = dict(os.environ, PATH="/nonexistent")
proc = subprocess.run([sys.executable, ROUTE, "project-board", "no-slash", "42", "--title", "x"],
                      capture_output=True, text=True, env=env)
assert proc.returncode == 0, f"project-board must exit 0 on bad slug, got {proc.returncode}: {proc.stderr}"
ok("project-board exits 0 on malformed slug with gh unavailable")

# --------------------------------------------------------------------------- worktree

assert worktree.slugify("Fix the N+1 in OrderController!") == "fix-the-n-1-in-ordercontroller"
assert worktree.slugify("") == "issue"
assert worktree.is_secret("storage/oauth-private.key")
assert worktree.is_secret(".env.local") and worktree.is_secret("app/.env")
assert not worktree.is_secret("src/keyboard.ts")
ok("branch slug and the gitignored-secret filter behave on the awkward names")

with tempfile.TemporaryDirectory() as d:
    write(d, "composer.lock", "")
    assert worktree.pick_install(d) == ["composer", "install", "--no-interaction"]
    write(d, "pnpm-lock.yaml", "")
    assert worktree.pick_install(d)[0] == "pnpm", "lockfile order decides, not the filesystem's"
ok("install command is chosen by lockfile precedence")

# --------------------------------------------------------------------------- best-effort

with tempfile.TemporaryDirectory() as d:
    env = dict(os.environ, PATH="/nonexistent")
    for argv in (["project-status", "o/r", "1", "In Review"],
                 ["gitnexus", "sync", d]):
        proc = subprocess.run([sys.executable, ROUTE, *argv], capture_output=True, text=True, env=env)
        assert proc.returncode == 0, f"{argv} exited {proc.returncode}: {proc.stderr}"
ok("best-effort subcommands exit 0 even with gh/node missing from PATH")

# --------------------------------------------------------------------------- epic DAG

assert epic.parse_depends("Some body\n\nDepends on: #12, #13\n") == [12, 13]
assert epic.parse_depends("depends on: #7") == [7], "the header is case-insensitive"
assert epic.parse_depends("No dependency line here") == []
assert epic.parse_depends("Depends on: none") == []
assert epic.parse_depends("Depends on: #9, #9") == [9], "duplicates collapse"
assert epic.parse_depends(None) == []
assert epic.parse_depends(
    "Depends on: #4 in passing\n\n## Dependencies\nDepends on: #12, #13\n"
) == [4, 12, 13], "every Depends on line is unioned — the first does not win"
ok("Depends on: parses to sorted unique issue numbers, absent means []")

dag = epic.build_dag({10: [], 11: [10], 12: [10], 13: [11, 12]})
assert dag["order"] == [10, 11, 12, 13], dag["order"]
assert dag["deps"]["13"] == [11, 12]
ok("build_dag topologically orders a diamond deterministically")

for bad, needle in [
    ({10: [99]}, "not in this epic"),
    ({10: [10]}, "itself"),
    ({10: [11], 11: [10]}, "cycle"),
    ({10: [11], 11: [12], 12: [10]}, "cycle"),
]:
    try:
        epic.build_dag(bad)
        raise AssertionError(f"expected ValueError for {bad}")
    except ValueError as exc:
        assert needle in str(exc), f"{bad}: {exc}"
ok("build_dag rejects foreign edges, self-edges and cycles of any length")

# --------------------------------------------------------------------------- epic readiness

DAG = epic.build_dag({10: [], 11: [10], 12: []})


def state(status="running", pr=False, stack_up=False, needs_stack=False):
    return {"status": status, "pr": pr, "stack_up": stack_up, "needs_stack": needs_stack}


s = {10: state(), 11: state(), 12: state()}
assert epic.ready(DAG, s, max_stacks=2) == [10, 12], "11 waits: #10 has no PR yet"
ok("a child waits until every dependency has reached PR open")

s[10] = state(pr=True)
assert epic.ready(DAG, s, max_stacks=2) == [10, 11, 12]
ok("a dependency reaching PR open releases its dependents")

s = {10: state(status="done", pr=True), 11: state(), 12: state(status="escalated")}
assert epic.ready(DAG, s, max_stacks=2) == [11], "done and escalated children are not ready"
ok("only children whose own run is still running are ready")

# Stack budget, ISOLATED from the dependency rule. #10 must carry pr=True in every case
# below, or #11 is excluded because its dependency has no PR yet and the assertion passes
# for a reason that has nothing to do with the budget it is named for.
s = {10: state(pr=True, stack_up=True), 11: state(needs_stack=True), 12: state(stack_up=True)}
assert epic.ready(DAG, s, max_stacks=2) == [10, 12], "11 needs a stack, both slots taken"
ok("a child needing a stack parks when the budget is spent")

s = {10: state(pr=True, stack_up=True), 11: state(needs_stack=True), 12: state()}
assert epic.ready(DAG, s, max_stacks=2) == [10, 11, 12], "one slot free, 11 takes it"
ok("a freed stack slot releases exactly one parked child")

s = {10: state(pr=True, needs_stack=True), 11: state(needs_stack=True), 12: state(needs_stack=True)}
assert epic.ready(DAG, s, max_stacks=0) == [], "no budget at all"
assert epic.ready(DAG, s, max_stacks=1) == [10], "the budget is a hard cap, not a hint"
assert epic.ready(DAG, s, max_stacks=2) == [10, 11], "#12 is third in line for two slots"
ok("the stack budget is a hard cap counted across the whole epic")

# --------------------------------------------------------------------------- epic child_state

with tempfile.TemporaryDirectory() as tmp:
    run_dir = os.path.join(tmp, "o-r-issue-10")
    os.makedirs(run_dir)
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump({"issue": 10, "stations": ["dev"], "currentIndex": 0, "bounceCounts": {},
                   "status": "running", "trace": [], "context": {"stack": "failed"},
                   "classification": None, "specialists": []}, fh)
    st = epic.child_state(tmp, "o/r", 10)
    assert st["needs_stack"] is False, st
ok("a child whose stack failed to come up does not hold a budget slot")

# --------------------------------------------------------------------------- epic CLI

with tempfile.TemporaryDirectory() as tmp:
    epic_dir = os.path.join(tmp, "epic")
    os.makedirs(epic_dir)
    with open(os.path.join(epic_dir, "epic.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "parent": 42, "slug": "o/r", "children": [10, 11],
            "dag": {"order": [10, 11], "deps": {"10": [], "11": [10]}},
            "max_stacks": 2,
        }, fh)

    runs = os.path.join(tmp, "runs")
    for issue, ctx in ((10, {"pr": "https://x/1"}), (11, {})):
        d = os.path.join(runs, f"o-r-issue-{issue}")
        os.makedirs(d)
        with open(os.path.join(d, "run.json"), "w", encoding="utf-8") as fh:
            json.dump({"issue": issue, "stations": ["dev"], "currentIndex": 0,
                       "bounceCounts": {}, "status": "running", "trace": [],
                       "context": ctx, "classification": None, "specialists": []}, fh)

    proc = subprocess.run(
        [sys.executable, ROUTE, "epic", "next", epic_dir, "--runs-dir", runs],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout)
    assert got["ready"] == [10, 11], got
ok("aiw epic next reads every child ledger and prints who may advance")

with tempfile.TemporaryDirectory() as tmp:
    epic_dir, runs, repo = os.path.join(tmp, "e"), os.path.join(tmp, "runs"), os.path.join(tmp, "repo")
    os.makedirs(epic_dir); os.makedirs(repo)
    with open(os.path.join(epic_dir, "epic.json"), "w", encoding="utf-8") as fh:
        json.dump({"parent": 42, "slug": "o/r", "children": [10, 11],
                   "dag": {"order": [10, 11], "deps": {"10": [], "11": [10]}},
                   "max_stacks": 2}, fh)

    proc = subprocess.run(
        [sys.executable, ROUTE, "epic", "init", epic_dir, "--runs-dir", runs, "--repo", repo],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    for issue in (10, 11):
        led = json.load(open(os.path.join(runs, f"o-r-issue-{issue}", "run.json")))
        assert led["issue"] == issue and led["status"] == "running", led
    # The edge itself is recorded on the child. Setting base_branch from it is the
    # orchestrator's job at Epic mode step 4 — this only checks the edge survived init.
    led11 = json.load(open(os.path.join(runs, "o-r-issue-11", "run.json")))
    assert led11["context"]["depends_on"] == "10", led11["context"]

    # re-running must not clobber a ledger that already exists
    again = subprocess.run(
        [sys.executable, ROUTE, "epic", "init", epic_dir, "--runs-dir", runs, "--repo", repo],
        capture_output=True, text=True,
    )
    assert again.returncode == 0, again.stderr
    assert "already" in again.stdout.lower(), again.stdout
ok("aiw epic init creates one ledger per child, records edges, and is idempotent")

# --------------------------------------------------------------------------- epic --lean-children

LEAN_STATIONS = ["researcher", "planner", "dev", "reviewer", "fixer"]
FULL_STATIONS = ["researcher", "planner", "sdet", "dev", "verifier", "reviewer", "fixer"]


def run_epic_init(children_deps: dict, lean_children: str | None, mode: str | None):
    """One fresh epic.json/runs dir per call, `epic init` run once, ledgers returned."""
    tmp = tempfile.mkdtemp()
    epic_dir, runs, repo = (os.path.join(tmp, "e"), os.path.join(tmp, "runs"),
                             os.path.join(tmp, "repo"))
    os.makedirs(epic_dir); os.makedirs(repo)
    order = sorted(children_deps, key=lambda c: (len(children_deps[c]), c))
    with open(os.path.join(epic_dir, "epic.json"), "w", encoding="utf-8") as fh:
        json.dump({"parent": 99, "slug": "o/r", "children": list(children_deps),
                   "dag": {"order": order,
                           "deps": {str(k): v for k, v in children_deps.items()}},
                   "max_stacks": 2}, fh)
    argv = [sys.executable, ROUTE, "epic", "init", epic_dir, "--runs-dir", runs, "--repo", repo]
    if mode:
        argv += ["--mode", mode]
    if lean_children is not None:
        argv += ["--lean-children", lean_children]
    proc = subprocess.run(argv, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    ledgers = {
        c: json.load(open(os.path.join(runs, f"o-r-issue-{c}", "run.json")))
        for c in children_deps
        if os.path.isfile(os.path.join(runs, f"o-r-issue-{c}", "run.json"))
    }
    return runs, ledgers, proc


_, leds, _ = run_epic_init({11: [], 12: [], 13: []}, "11,13", None)
assert leds[11]["stations"] == LEAN_STATIONS, leds[11]["stations"]
assert leds[13]["stations"] == LEAN_STATIONS, leds[13]["stations"]
assert leds[12]["stations"] == FULL_STATIONS, leds[12]["stations"]
ok("--lean-children puts only the named children on the lean roster, others stay full")

_, leds, _ = run_epic_init({11: [], 12: [], 13: []}, None, None)
assert all(leds[c]["stations"] == FULL_STATIONS for c in (11, 12, 13)), leds
ok("omitting --lean-children is a no-op: every child gets the full roster as before")

_, leds, _ = run_epic_init({11: [], 12: []}, "11,12", "lean")
assert all(leds[c]["stations"] == LEAN_STATIONS for c in (11, 12)), leds
ok("--lean-children combined with --mode lean: all children lean, no crash")

# The ordering bug this whole feature exists to guard against: a lean child must still
# get context.epic / context.depends_on wired exactly as a full child would.
_, leds, _ = run_epic_init({10: [], 11: [10]}, "11", None)
assert leds[11]["stations"] == LEAN_STATIONS, leds[11]["stations"]
assert leds[11]["context"]["depends_on"] == "10", leds[11]["context"]
assert leds[11]["context"]["epic"] == "99", leds[11]["context"]
assert leds[10]["context"]["epic"] == "99", leds[10]["context"]
ok("a lean child still receives context.epic and context.depends_on, same as a full child")

for lc in ("", None):
    _, leds, _ = run_epic_init({11: [], 12: []}, lc, None)
    assert all(leds[c]["stations"] == FULL_STATIONS for c in (11, 12)), (lc, leds)
ok("--lean-children '' and omitting the flag both mean no lean children")

_, leds, _ = run_epic_init({11: [], 12: []}, "11,999", None)
assert leds[11]["stations"] == LEAN_STATIONS, leds[11]["stations"]
assert leds[12]["stations"] == FULL_STATIONS, leds[12]["stations"]
assert set(leds) == {11, 12}, "999 is not a child of this epic — no phantom run dir"
ok("a --lean-children entry naming no child of this epic is silently ignored")

_, leds, _ = run_epic_init({11: [], 12: []}, "abc,11", None)
assert leds[11]["stations"] == LEAN_STATIONS, leds[11]["stations"]
assert leds[12]["stations"] == FULL_STATIONS, leds[12]["stations"]
ok("a non-numeric --lean-children entry is skipped, not fatal; the valid entry is honoured")

with tempfile.TemporaryDirectory() as tmp:
    epic_dir, runs, repo = (os.path.join(tmp, "e"), os.path.join(tmp, "runs"),
                             os.path.join(tmp, "repo"))
    os.makedirs(epic_dir); os.makedirs(repo)
    with open(os.path.join(epic_dir, "epic.json"), "w", encoding="utf-8") as fh:
        json.dump({"parent": 99, "slug": "o/r", "children": [11, 12],
                   "dag": {"order": [11, 12], "deps": {"11": [], "12": []}},
                   "max_stacks": 2}, fh)

    first = subprocess.run(
        [sys.executable, ROUTE, "epic", "init", epic_dir, "--runs-dir", runs,
         "--repo", repo, "--lean-children", "11"],
        capture_output=True, text=True,
    )
    assert first.returncode == 0, first.stderr
    led11 = json.load(open(os.path.join(runs, "o-r-issue-11", "run.json")))
    assert led11["stations"] == LEAN_STATIONS, led11["stations"]

    # Re-running WITHOUT --lean-children must not flip #11 back to full: an
    # already-initialised child is skipped before the roster is ever recomputed.
    again = subprocess.run(
        [sys.executable, ROUTE, "epic", "init", epic_dir, "--runs-dir", runs, "--repo", repo],
        capture_output=True, text=True,
    )
    assert again.returncode == 0, again.stderr
    assert "already" in again.stdout.lower(), again.stdout
    led11_again = json.load(open(os.path.join(runs, "o-r-issue-11", "run.json")))
    assert led11_again["stations"] == LEAN_STATIONS, led11_again["stations"]
ok("re-running epic init over an already-initialised child never flips lean back to full")

# `gh` is the only thing between `epic split` and GitHub, so the split tests drive a stub
# that records its argv. What matters is not that gh was called but WITH WHAT: the
# sub-issues endpoint takes a database id as an integer, and `-f` with an issue number
# 422s on every child while `split` still exits 0 — a parent with no sub-issues, which
# run-issue then runs as one ordinary issue.
GH_STUB = r"""#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
cfg = json.load(open(os.environ["GH_STUB_CFG"]))
with open(os.environ["GH_STUB_LOG"], "a") as fh:
    fh.write(" ".join(argv) + "\n")
if argv[0] == "issue" and argv[1] == "view":
    print(cfg["bodies"].get(argv[2], ""))
elif argv[1].endswith("/sub_issues") and any(a.startswith("-F") or a.startswith("-f") for a in argv):
    sys.exit(cfg.get("link_exit", 0))
elif argv[1].endswith("/sub_issues"):
    print(json.dumps(cfg.get("linked", [])))
else:  # repos/o/r/issues/<n> --jq .id
    print(9000 + int(argv[1].rsplit("/", 1)[1]))
"""


def gh_stub(tmp, **cfg):
    """A `gh` on PATH that answers from `cfg`. Returns (env, log path)."""
    bindir = os.path.join(tmp, "bin")
    os.makedirs(bindir, exist_ok=True)
    stub = os.path.join(bindir, "gh")
    write(bindir, "gh", GH_STUB)
    os.chmod(stub, 0o755)
    cfg_path, log = os.path.join(tmp, "cfg.json"), os.path.join(tmp, "gh.log")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    return dict(os.environ, PATH=bindir + os.pathsep + os.environ["PATH"],
                GH_STUB_CFG=cfg_path, GH_STUB_LOG=log), log


def split(tmp, env, children="10,11,12"):
    epic_dir = os.path.join(tmp, "e")
    os.makedirs(epic_dir, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, ROUTE, "epic", "split", epic_dir,
         "--parent", "42", "--slug", "o/r", "--children", children],
        capture_output=True, text=True, env=env,
    )
    return proc, os.path.join(epic_dir, "epic.json")


with tempfile.TemporaryDirectory() as tmp:
    env, log = gh_stub(tmp, linked=[11], bodies={
        "10": "no deps", "11": "Depends on: #10", "12": "Depends on: #10"})
    proc, path = split(tmp, env)
    assert proc.returncode == 0, proc.stderr
    logged = open(log).read()
    assert "-F sub_issue_id=9010" in logged and "-F sub_issue_id=9012" in logged, logged
    assert "sub_issue_id=10" not in logged, "the ISSUE NUMBER was sent where the id belongs"
    assert "-f sub_issue_id" not in logged, "-f sends a string; the field must be an integer"
    assert "sub_issue_id=9011" not in logged, "#11 was already linked and must be skipped"
    epic_json = json.load(open(path))
    assert epic_json["dag"]["order"] == [10, 11, 12], epic_json
    assert epic_json["max_stacks"] == 3, \
        "default raised now that stack.py keys Compose projects and ports per (repo, issue)"
ok("epic split links by database id with -F, skips what is linked, and defaults stacks to 3")

with tempfile.TemporaryDirectory() as tmp:
    env, _ = gh_stub(tmp, bodies={"10": "", "11": "", "12": "Depends on: #41"})
    proc, path = split(tmp, env)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "not in this epic" in proc.stderr, proc.stderr
    assert not os.path.isfile(path), "a foreign edge must not produce an epic.json"
ok("epic split refuses an edge pointing outside the epic instead of dropping it")

with tempfile.TemporaryDirectory() as tmp:
    env, _ = gh_stub(tmp, bodies={})
    proc, path = split(tmp, env, children="")
    assert proc.returncode != 0 and not os.path.isfile(path), proc.stdout
ok("epic split refuses an empty child list rather than writing an epic nothing runs")

with tempfile.TemporaryDirectory() as tmp:
    env, _ = gh_stub(tmp, link_exit=1, bodies={"10": "", "11": "", "12": ""})
    proc, path = split(tmp, env)
    assert proc.returncode == 1, proc.stdout
    assert not os.path.isfile(path), "a link failure must not leave a valid-looking epic.json"
ok("a sub-issue link failure kills the split rather than warning past it")

proc = subprocess.run([sys.executable, ROUTE, "epic", "next", "/nonexistent"],
                      capture_output=True, text=True)
assert proc.returncode == 2 and "runs-dir" in proc.stderr, proc.stderr
ok("epic next requires --runs-dir instead of advertising a default it does not have")

with tempfile.TemporaryDirectory() as tmp:
    epic_dir = os.path.join(tmp, "e")
    os.makedirs(epic_dir)
    env = dict(os.environ, PATH="/nonexistent")
    proc = subprocess.run(
        [sys.executable, ROUTE, "epic", "split", epic_dir,
         "--parent", "42", "--slug", "o/r", "--children", "10,11"],
        capture_output=True, text=True, env=env,
    )
    assert proc.returncode != 0, "gh is unreachable — split must not report success"
    assert not os.path.isfile(os.path.join(epic_dir, "epic.json")), \
        "a failed gh call must not produce a DAG, wrong or otherwise"
ok("aiw epic split dies rather than recording an empty dependency list when gh fails")

# --------------------------------------------------------------------------- data_dir()

import contextlib  # noqa: E402


@contextlib.contextmanager
def env_var(key, value):
    old = os.environ.get(key)
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old


with env_var("CLAUDE_PLUGIN_DATA", "/tmp/aiw-test-data-dir-xyz"):
    assert shared.data_dir() == "/tmp/aiw-test-data-dir-xyz"
with env_var("CLAUDE_PLUGIN_DATA", None):
    assert shared.data_dir() == os.path.expanduser("~/.claude/plugins/data/ai-workflow")
ok("data_dir() honours $CLAUDE_PLUGIN_DATA and falls back to the default, read at call time")

with tempfile.TemporaryDirectory() as d:
    dd = os.path.join(d, "data")
    env = dict(os.environ, CLAUDE_PLUGIN_DATA=dd)
    proc = subprocess.run([sys.executable, ROUTE, "paths"], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["data_dir"] == dd
    assert out["runs_dir"] == os.path.join(dd, "runs")
    assert out["pr_grind_dir"] == os.path.join(dd, "pr-grind")
    assert out["channels"] == os.path.join(dd, "channels.json")
ok("aiw paths prints unchanged data_dir/runs_dir/pr_grind_dir/channels after the shared.data_dir() extraction")

# --------------------------------------------------------------------------- stack lock primitives

assert stack.compose_project("/repos/a", 5) != stack.compose_project("/repos/b", 5), \
    "same issue number, different repos, must be different projects"
assert stack.compose_project("/repos/a", 5) != stack.compose_project("/repos/a", 6), \
    "different issues in the same repo must be different projects"
assert stack.compose_project("/repos/a", 5) == stack.compose_project("/repos/a", 5), \
    "deterministic: the same (repo, issue) always yields the same project"
assert re.fullmatch(r"[a-z0-9-]+", stack.compose_project("/Repos/My App!", 5)), \
    "a project name must be Compose-safe regardless of what's in the repo path"
ok("compose_project keys uniquely on (repo, issue) and is always Compose-safe")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        run_dir = os.path.join(d, "run")
        project = stack.compose_project("o/r", 7)
        assert stack.acquire_lock(run_dir, 7, "o/r", 5) is True
        holder = json.load(open(stack.lock_path(project)))
        assert holder["run_dir"] == run_dir and holder["issue"] == 7 and holder["repo"] == "o/r"
        assert isinstance(holder["acquired_at"], (int, float))
ok("acquire_lock on a free lock writes run_dir/issue/repo/acquired_at and returns True")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        run_dir = os.path.join(d, "run")
        project = stack.compose_project("o/r", 7)
        assert stack.acquire_lock(run_dir, 7, "o/r", 5) is True
        stack.release_lock(run_dir, 7, "o/r")
        assert not os.path.isfile(stack.lock_path(project))
ok("release_lock by the holding run_dir removes the lockfile")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        run_a, run_b = os.path.join(d, "a"), os.path.join(d, "b")
        assert stack.acquire_lock(run_a, 5, "/repos/x", 5) is True
        assert stack.acquire_lock(run_b, 5, "/repos/y", 0) is True, \
            "same issue number in a different repo must not contend"
        assert stack.acquire_lock(run_b, 6, "/repos/x", 0) is True, \
            "a different issue in the same repo must not contend"
ok("acquire_lock never blocks across different (repo, issue) projects")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        run_dir = os.path.join(d, "run")
        assert stack.acquire_lock(run_dir, 7, "o/r", 5) is True
        assert stack.acquire_lock(run_dir, 7, "o/r", 0) is True, "same run_dir must not self-block"
ok("acquire_lock is re-entrant for the same run_dir (pr-grind's second `stack up`)")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        run_dir_a, run_dir_b = os.path.join(d, "a"), os.path.join(d, "b")
        os.makedirs(run_dir_a)
        with open(os.path.join(run_dir_a, "run.json"), "w", encoding="utf-8") as fh:
            json.dump(Ledger(1, ["dev"]).to_dict(), fh)
        project = stack.compose_project("o/r", 1)
        assert stack.acquire_lock(run_dir_a, 1, "o/r", 5) is True
        assert stack.acquire_lock(run_dir_b, 1, "o/r", 0) is False
        holder = json.load(open(stack.lock_path(project)))
        assert holder["run_dir"] == run_dir_a, "the first holder must still be recorded"
        stack.release_lock(run_dir_a, 1, "o/r")
        assert stack.acquire_lock(run_dir_b, 1, "o/r", 0) is True
ok("a second acquire for a different run_dir returns False without disturbing the first "
   "holder, and succeeds cleanly once the first releases")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        project = stack.compose_project("o/r", 7)
        os.makedirs(os.path.dirname(stack.lock_path(project)), exist_ok=True)
        open(stack.lock_path(project), "w").close()  # zero bytes
        assert stack.acquire_lock(os.path.join(d, "run"), 7, "o/r", 0) is True
ok("a zero-byte lockfile is treated as free/reclaimable, not a crash")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        project = stack.compose_project("o/r", 7)
        os.makedirs(os.path.dirname(stack.lock_path(project)), exist_ok=True)
        with open(stack.lock_path(project), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        assert stack.acquire_lock(os.path.join(d, "run"), 7, "o/r", 0) is True
ok("a corrupt non-JSON lockfile is reclaimed rather than raising")

assert stack.lock_stale({}, time.time()) is True
assert stack.lock_stale({"run_dir": None, "acquired_at": time.time()}, time.time()) is True
ok("a holder record missing run_dir is treated as stale")

with tempfile.TemporaryDirectory() as d:
    gone = os.path.join(d, "never-created")
    assert stack.lock_stale({"run_dir": gone, "acquired_at": time.time()}, time.time()) is True
ok("a holder whose run.json is gone is reclaimed immediately (with a warning)")

with tempfile.TemporaryDirectory() as d:
    run_dir = os.path.join(d, "run")
    os.makedirs(run_dir)
    ledger = Ledger(9, ["dev"])
    ledger.mark_done()
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(ledger.to_dict(), fh)
    now = time.time()
    # A holder whose run reached "done" is never coming back to call `stack
    # down` — it is reclaimed the moment that's known, not after LOCK_GRACE
    # (LOCK_GRACE outlives the default --lock-timeout, so gating a done/
    # escalated holder on it would starve every contender for nothing).
    fresh = {"run_dir": run_dir, "acquired_at": now}
    assert stack.lock_stale(fresh, now) is True, "done is reclaimed immediately, not grace-gated"

    escalated = Ledger(10, ["dev"])
    escalated.mark_escalated("test")
    esc_run = os.path.join(d, "esc-run")
    os.makedirs(esc_run)
    with open(os.path.join(esc_run, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(escalated.to_dict(), fh)
    assert stack.lock_stale({"run_dir": esc_run, "acquired_at": now}, now) is True, \
        "escalated is reclaimed immediately, not grace-gated"
ok("a done/escalated holder is reclaimed immediately regardless of LOCK_GRACE")

with tempfile.TemporaryDirectory() as d:
    run_dir = os.path.join(d, "run")
    os.makedirs(run_dir)
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(Ledger(9, ["dev"]).to_dict(), fh)  # status still "running"
    now = time.time()
    just_under = {"run_dir": run_dir, "acquired_at": now - stack.LOCK_GRACE + 1}
    just_over = {"run_dir": run_dir, "acquired_at": now - stack.LOCK_GRACE - 1}
    assert stack.lock_stale(just_under, now) is False
    assert stack.lock_stale(just_over, now) is True
ok("staleness grace: just under LOCK_GRACE is not stale, just over is (now injected, no sleep)")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        holder_run = os.path.join(d, "holder")
        os.makedirs(holder_run)
        with open(os.path.join(holder_run, "run.json"), "w", encoding="utf-8") as fh:
            json.dump(Ledger(1, ["dev"]).to_dict(), fh)
        assert stack.acquire_lock(holder_run, 1, "o/r", 5) is True
        started = time.time()
        assert stack.acquire_lock(os.path.join(d, "other"), 1, "o/r", 0) is False
        assert time.time() - started < 1, "--lock-timeout 0 must try once and never wait"
ok("--lock-timeout 0 tries once and never waits")

import argparse as _argparse  # noqa: E402

_parser = _argparse.ArgumentParser()
_sub = _parser.add_subparsers(dest="cmd")


def _add(name, help_text):
    p = _sub.add_parser(name)
    p.add_argument("run_dir")
    p.add_argument("--repo")
    return p


stack.register(_sub, _add)
_ns = _parser.parse_args(["stack", "up", "/tmp/x"])
assert _ns.lock_timeout == 900
ok("--lock-timeout exists on the `up` subparser with default 900")

# The helper script a race spawns as a subprocess. Written to a real temp
# dir (not into run-engine/, which is the repo's own test root) so a killed
# race-test process can never leave an untracked file behind for a later
# `/run-issue` run's dirty-worktree guard to trip over.
RACE_TMP = tempfile.mkdtemp(prefix="aiw-race-")
RACER = os.path.join(RACE_TMP, "_race_acquire_lock_helper.py")
write(RACE_TMP, os.path.basename(RACER), f"""\
import json, os, sys, time
sys.path.insert(0, {HERE!r})
import stack

run_dir, start_at = sys.argv[1], float(sys.argv[2])
os.makedirs(run_dir, exist_ok=True)
with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as fh:
    json.dump({{"status": "running"}}, fh)
while time.time() < start_at:
    pass
print("True" if stack.acquire_lock(run_dir, 0, "o/r", 0) else "False")
""")

# The release-side racer for the release_lock blocker (round-3 review): a
# separate subprocess that calls release_lock(run_dir) at the same shared
# start timestamp the acquire contenders use, so it hits the sentinel gate
# concurrently with them instead of running safely before/after the race.
RELEASER = os.path.join(RACE_TMP, "_race_release_lock_helper.py")
write(RACE_TMP, os.path.basename(RELEASER), f"""\
import sys, time
sys.path.insert(0, {HERE!r})
import stack

run_dir, start_at = sys.argv[1], float(sys.argv[2])
while time.time() < start_at:
    pass
stack.release_lock(run_dir, 0, "o/r")
""")


def _race(d: str, data_d: str, n: int = 12) -> list[str]:
    """Spawn `n` separate `python3` processes — the actual shape of N `aiw
    stack up` invocations racing for the same lockfile, unlike an in-process
    threading.Thread version, which would only ever exercise the
    process-local threading.Lock and pass even with no cross-process
    exclusion at all. A single shared start timestamp, not just "spawned
    close together": every contender spin-waits up to it so they hit
    acquire_lock() concurrently instead of arriving staggered."""
    env = dict(os.environ, CLAUDE_PLUGIN_DATA=data_d)
    start_at = time.time() + 0.5
    procs = [
        subprocess.Popen(
            [sys.executable, RACER, os.path.join(d, f"run{i}"), str(start_at)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        )
        for i in range(n)
    ]
    outs = [p.communicate()[0].strip() for p in procs]
    assert all(o in ("True", "False") for o in outs), outs
    return outs


def _race_with_release(d: str, data_d: str, holder_run: str, n: int = 10) -> list[str]:
    """Same shape as `_race`, plus one more subprocess: the stale holder
    itself calling `release_lock()` at the same shared start timestamp as
    the N contenders trying to reclaim its (stale) lock. This is the exact
    interleaving the round-3 review flagged — Teardown calls `stack down`
    (release_lock) at precisely the moment a holder's ledger goes terminal,
    which is also the instant lock_stale() starts telling contenders to
    reclaim."""
    env = dict(os.environ, CLAUDE_PLUGIN_DATA=data_d)
    start_at = time.time() + 0.5
    procs = [
        subprocess.Popen(
            [sys.executable, RACER, os.path.join(d, f"run{i}"), str(start_at)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        )
        for i in range(n)
    ]
    releaser = subprocess.Popen(
        [sys.executable, RELEASER, holder_run, str(start_at)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )
    outs = [p.communicate()[0].strip() for p in procs]
    releaser.communicate()
    assert all(o in ("True", "False") for o in outs), outs
    return outs


def _plant_stale_holder(data_d: str, status: str, acquired_at: float) -> None:
    """Pre-plant a stale stack.lock, pointing at its own holder run.json, so
    a race hits the reclaim branch instead of the cold "no lockfile yet"
    branch O_EXCL alone already protects."""
    os.makedirs(data_d, exist_ok=True)
    holder_run = os.path.join(data_d, "stale-holder")
    os.makedirs(holder_run, exist_ok=True)
    with open(os.path.join(holder_run, "run.json"), "w", encoding="utf-8") as fh:
        json.dump({"status": status}, fh)
    lock_file = os.path.join(data_d, "locks", f"{stack.compose_project('o/r', 0)}.lock")
    os.makedirs(os.path.dirname(lock_file), exist_ok=True)
    with open(lock_file, "w", encoding="utf-8") as fh:
        json.dump(
            {"run_dir": holder_run, "issue": 0, "repo": "o/r", "acquired_at": acquired_at}, fh
        )


try:
    with tempfile.TemporaryDirectory() as d:
        outs = _race(d, os.path.join(d, "data"))
        assert outs.count("True") == 1, outs
    ok("N concurrent `aiw stack up`-shaped subprocesses racing for the same lockfile "
       "produce exactly one winner")

    # The reclaim path: every contender independently reads the same stale
    # holder and independently agrees it's stale — the read-check-write race
    # the round-2 review found (5-10 winners per trial before the fix).
    for label, status, acquired_at in (
        ("status=done", "done", time.time()),
        ("grace-expired status=running", "running", time.time() - stack.LOCK_GRACE - 1),
    ):
        with tempfile.TemporaryDirectory() as d:
            data_d = os.path.join(d, "data")
            _plant_stale_holder(data_d, status, acquired_at)
            outs = _race(d, data_d)
            assert outs.count("True") == 1, (label, outs)
        ok(f"N concurrent processes racing to reclaim a stale lock ({label}) "
           "produce exactly one winner")

    # The release_lock blocker (round-3 review): a stale holder calling
    # release_lock() concurrently with N contenders reclaiming that same
    # stale lock must never let two of them believe they hold it. 40 trials,
    # matching the reviewer's own reproduction count. Zero winners in a
    # given trial is not a bug to flag here — with --lock-timeout 0 every
    # contender tries exactly once, so it's an expected (if unlucky) outcome
    # when the concurrent release wins the decision for that instant; a real
    # caller uses the default 900s timeout and simply retries. Only *more
    # than one* "True" is the actual double-holder this test exists to catch.
    double_holder_events = 0
    for _trial in range(40):
        with tempfile.TemporaryDirectory() as d:
            data_d = os.path.join(d, "data")
            _plant_stale_holder(data_d, "done", time.time())
            holder_run = os.path.join(data_d, "stale-holder")
            outs = _race_with_release(d, data_d, holder_run)
            if outs.count("True") > 1:
                double_holder_events += 1
    assert double_holder_events == 0, f"{double_holder_events}/40 trials produced a double-holder"
    ok("release_lock() called by a stale holder concurrently with N contenders reclaiming its lock "
       "never produces a double-holder (40 trials, 10 contenders each)")
finally:
    shutil.rmtree(RACE_TMP, ignore_errors=True)

with tempfile.TemporaryDirectory() as d:
    blocker = os.path.join(d, "blocker")
    open(blocker, "w").close()  # a FILE sitting where a directory is expected
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(blocker, "sub")):
        import io as _io

        buf = _io.StringIO()
        with contextlib.redirect_stderr(buf):
            got = stack.acquire_lock(os.path.join(d, "run"), 1, "o/r", 0)
        assert got is True, "an unwritable data dir must fail OPEN, not fail the run"
        assert "warning" in buf.getvalue().lower()
ok("an unwritable data dir warns and proceeds unlocked instead of failing the run")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        holder_run = os.path.join(d, "holder")
        project = stack.compose_project("o/r", 1)
        assert stack.acquire_lock(holder_run, 1, "o/r", 5) is True
        stack.release_lock(os.path.join(d, "impostor"), 1, "o/r")
        assert os.path.isfile(stack.lock_path(project))
        assert json.load(open(stack.lock_path(project)))["run_dir"] == holder_run
ok("release_lock from a non-holder run_dir does not remove another run's lockfile")

with tempfile.TemporaryDirectory() as d:
    # Round-4 review: release_lock losing the sentinel to transient
    # contention (not an actual break-in-progress) must retry through it
    # rather than silently no-op'ing and leaving the lockfile behind.
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        holder_run = os.path.join(d, "holder")
        project = stack.compose_project("o/r", 1)
        assert stack.acquire_lock(holder_run, 1, "o/r", 5) is True
        break_path = stack.lock_path(project) + ".break"
        bfd = os.open(break_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(bfd)

        def _release_sentinel_shortly():
            time.sleep(0.03)
            os.remove(break_path)

        orig_retries, orig_backoff = stack.RELEASE_SENTINEL_RETRIES, stack.RELEASE_SENTINEL_BACKOFF
        stack.RELEASE_SENTINEL_RETRIES, stack.RELEASE_SENTINEL_BACKOFF = 5, 0.02
        t = threading.Thread(target=_release_sentinel_shortly)
        t.start()
        try:
            stack.release_lock(holder_run, 1, "o/r")
        finally:
            t.join()
            stack.RELEASE_SENTINEL_RETRIES, stack.RELEASE_SENTINEL_BACKOFF = orig_retries, orig_backoff
        assert not os.path.isfile(stack.lock_path(project)), \
            "release_lock must retry through transient sentinel contention, not no-op"
ok("release_lock retries through transient `.break` sentinel contention instead of "
   "silently no-op'ing (round-4 regression)")

with tempfile.TemporaryDirectory() as d:
    # The other half: if the sentinel stays held for the whole retry window
    # (a genuine break in progress), release_lock must still give up
    # gracefully — never hang, never raise — leaving the lock for whoever
    # is actually clearing it.
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        holder_run = os.path.join(d, "holder")
        project = stack.compose_project("o/r", 1)
        assert stack.acquire_lock(holder_run, 1, "o/r", 5) is True
        break_path = stack.lock_path(project) + ".break"
        bfd = os.open(break_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(bfd)

        orig_retries, orig_backoff = stack.RELEASE_SENTINEL_RETRIES, stack.RELEASE_SENTINEL_BACKOFF
        stack.RELEASE_SENTINEL_RETRIES, stack.RELEASE_SENTINEL_BACKOFF = 3, 0.01
        try:
            started = time.time()
            stack.release_lock(holder_run, 1, "o/r")  # must not raise or hang
            assert time.time() - started < 1, "release_lock must give up quickly, not wedge"
        finally:
            os.remove(break_path)
            stack.RELEASE_SENTINEL_RETRIES, stack.RELEASE_SENTINEL_BACKOFF = orig_retries, orig_backoff
        assert os.path.isfile(stack.lock_path(project)), \
            "the lock must survive when every retry loses the sentinel to a live holder"
ok("release_lock gives up gracefully (never hangs, exits cleanly) when the `.break` sentinel "
   "stays held for the entire retry window")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        # Plant a stale holder so acquire_lock has to walk the sentinel-gated
        # reclaim branch (a cold "no lockfile yet" acquire never touches the
        # `.break` sentinel at all), then plant an orphaned `.break` sentinel
        # of its own — the crash-recovery case: the previous reclaimer died
        # between creating the sentinel and removing it in its `finally`.
        holder_run = os.path.join(d, "holder")
        os.makedirs(holder_run)
        ledger = Ledger(3, ["dev"])
        ledger.mark_done()
        with open(os.path.join(holder_run, "run.json"), "w", encoding="utf-8") as fh:
            json.dump(ledger.to_dict(), fh)
        project = stack.compose_project("o/r", 7)
        os.makedirs(os.path.dirname(stack.lock_path(project)), exist_ok=True)
        with open(stack.lock_path(project), "w", encoding="utf-8") as fh:
            json.dump({"run_dir": holder_run, "issue": 3, "repo": "o/r", "acquired_at": time.time()}, fh)
        break_path = stack.lock_path(project) + ".break"
        open(break_path, "w").close()
        old = time.time() - stack.BREAK_SENTINEL_STALE - 5
        os.utime(break_path, (old, old))

        orig_poll = stack.LOCK_POLL
        stack.LOCK_POLL = 0.05  # this test's own reclaim-then-retry loop, not the race harness
        try:
            started = time.time()
            assert stack.acquire_lock(os.path.join(d, "run"), 7, "o/r", 5) is True
            assert time.time() - started < 2, \
                "an abandoned .break sentinel must be reclaimed promptly, not wedge the full timeout"
        finally:
            stack.LOCK_POLL = orig_poll
        assert not os.path.exists(break_path), "the abandoned sentinel itself is cleared, not left behind"
ok("an abandoned `.break` sentinel older than BREAK_SENTINEL_STALE is reclaimed during a stale-lock "
   "acquire (crash-recovery path), instead of wedging every future reclaim")

# --------------------------------------------------------------------------- stack lock, via the CLI

with tempfile.TemporaryDirectory() as d:
    repo, run_dir = os.path.join(d, "repo"), os.path.join(d, "run")
    os.makedirs(repo)
    write(repo, "go.mod", "module x")
    ledger = Ledger(21, ["dev"])
    ledger.context["repo"] = repo
    os.makedirs(run_dir)
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(ledger.to_dict(), fh)
    data_d = os.path.join(d, "data")
    env = dict(os.environ, CLAUDE_PLUGIN_DATA=data_d)
    proc = subprocess.run([sys.executable, ROUTE, "stack", "up", run_dir],
                          capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    ctx = json.load(open(os.path.join(run_dir, "run.json")))["context"]
    assert ctx["stack"] == "none"
    assert not os.path.isdir(os.path.join(data_d, "locks"))
ok("`stack up` with no compose file records stack=none and creates no lockfile")

with tempfile.TemporaryDirectory() as d:
    repo, run_dir, other_run = os.path.join(d, "repo"), os.path.join(d, "run"), os.path.join(d, "other")
    os.makedirs(repo)
    os.makedirs(run_dir)
    os.makedirs(other_run)
    write(repo, "docker-compose.test.yml", "services: {}\n")
    write(repo, "go.mod", "module x")
    ledger = Ledger(22, ["dev"])
    ledger.context["repo"] = repo
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(ledger.to_dict(), fh)
    # Same issue number (22) as run_dir, so it's the same Compose project and must
    # still block — a per-project lock must keep protecting a project against a
    # concurrent double-`up` even though it no longer blocks unrelated projects.
    with open(os.path.join(other_run, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(Ledger(22, ["dev"]).to_dict(), fh)

    data_d = os.path.join(d, "data")
    project = stack.compose_project(repo, 22)
    lock_file = os.path.join(data_d, "locks", f"{project}.lock")
    os.makedirs(os.path.dirname(lock_file))
    with open(lock_file, "w", encoding="utf-8") as fh:
        json.dump({"run_dir": other_run, "issue": 22, "repo": repo, "acquired_at": time.time()}, fh)

    # PATH is emptied: if this ever shells out to docker, the process would fail
    # loudly with "command not found" instead of quietly degrading.
    env = dict(os.environ, CLAUDE_PLUGIN_DATA=data_d, PATH="/nonexistent")
    proc = subprocess.run(
        [sys.executable, ROUTE, "stack", "up", run_dir, "--lock-timeout", "0"],
        capture_output=True, text=True, env=env,
    )
    assert proc.returncode == 0, proc.stderr
    ctx = json.load(open(os.path.join(run_dir, "run.json")))["context"]
    assert ctx["stack"] == "failed"
    assert other_run in ctx["tests_unverified"]
    assert ctx["test_cmd_host"] == "go test ./..."
    assert json.load(open(lock_file))["run_dir"] == other_run
ok("`stack up` behind a non-stale foreign lock on the SAME project, with --lock-timeout 0, "
   "degrades to stack=failed naming the holder, keeps test_cmd_host, exits 0, and never "
   "invokes Docker")

with tempfile.TemporaryDirectory() as d:
    repo, run_dir, other_run = os.path.join(d, "repo"), os.path.join(d, "run"), os.path.join(d, "other")
    os.makedirs(repo)
    os.makedirs(run_dir)
    write(repo, "docker-compose.test.yml", "services: {}\n")
    write(repo, "go.mod", "module x")
    ledger = Ledger(28, ["dev"])
    ledger.context["repo"] = repo
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(ledger.to_dict(), fh)

    data_d = os.path.join(d, "data")
    # A live (non-stale) lock for a DIFFERENT issue in the SAME repo must not block
    # this run at all — the whole point of per-project keying.
    other_project = stack.compose_project(repo, 29)
    other_lock = os.path.join(data_d, "locks", f"{other_project}.lock")
    os.makedirs(os.path.dirname(other_lock))
    with open(other_lock, "w", encoding="utf-8") as fh:
        json.dump({"run_dir": other_run, "issue": 29, "repo": repo, "acquired_at": time.time()}, fh)

    env = dict(os.environ, CLAUDE_PLUGIN_DATA=data_d, PATH="/nonexistent")
    proc = subprocess.run(
        [sys.executable, ROUTE, "stack", "up", run_dir, "--lock-timeout", "0"],
        capture_output=True, text=True, env=env,
    )
    assert proc.returncode == 0, proc.stderr
    ctx = json.load(open(os.path.join(run_dir, "run.json")))["context"]
    assert ctx["stack"] != "failed" or "lock held by" not in ctx.get("tests_unverified", ""), \
        "a live lock on an unrelated project must never be treated as a blocker"
    assert json.load(open(other_lock))["run_dir"] == other_run, \
        "the unrelated project's own lock must be left untouched"
ok("`stack up` is never blocked by a live lock belonging to a different issue in the same repo")

with tempfile.TemporaryDirectory() as d:
    run_dir, repo = os.path.join(d, "run"), os.path.join(d, "repo")
    os.makedirs(run_dir)
    os.makedirs(repo)
    ledger = Ledger(24, ["dev"])
    ledger.context.update(stack="up", compose_prefix="true", repo=repo)
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(ledger.to_dict(), fh)
    data_d = os.path.join(d, "data")
    project = stack.compose_project(repo, 24)
    lock_file = os.path.join(data_d, "locks", f"{project}.lock")
    os.makedirs(os.path.dirname(lock_file))
    with open(lock_file, "w", encoding="utf-8") as fh:
        json.dump({"run_dir": run_dir, "issue": 24, "repo": repo, "acquired_at": time.time()}, fh)
    env = dict(os.environ, CLAUDE_PLUGIN_DATA=data_d)
    proc = subprocess.run([sys.executable, ROUTE, "stack", "down", run_dir],
                          capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    assert not os.path.isfile(lock_file)
ok("`stack down` releases the lock after a successful teardown, exit 0")

with tempfile.TemporaryDirectory() as d:
    run_dir, repo = os.path.join(d, "run"), os.path.join(d, "repo")
    os.makedirs(run_dir)
    os.makedirs(repo)
    ledger = Ledger(25, ["dev"])
    ledger.context.update(stack="up", compose_prefix="false", repo=repo)
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(ledger.to_dict(), fh)
    data_d = os.path.join(d, "data")
    project = stack.compose_project(repo, 25)
    lock_file = os.path.join(data_d, "locks", f"{project}.lock")
    os.makedirs(os.path.dirname(lock_file))
    with open(lock_file, "w", encoding="utf-8") as fh:
        json.dump({"run_dir": run_dir, "issue": 25, "repo": repo, "acquired_at": time.time()}, fh)
    env = dict(os.environ, CLAUDE_PLUGIN_DATA=data_d)
    proc = subprocess.run([sys.executable, ROUTE, "stack", "down", run_dir],
                          capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    assert not os.path.isfile(lock_file), \
        "the lock must release even when teardown fails"
ok("`stack down` releases the lock even when compose teardown fails, still exits 0")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        repo, run_dir = os.path.join(d, "repo"), os.path.join(d, "run")
        os.makedirs(repo)
        os.makedirs(run_dir)
        write(repo, "docker-compose.test.yml", "services: {}\n")
        write(repo, "go.mod", "module x")
        ledger = Ledger(26, ["dev"])
        ledger.context["repo"] = repo
        with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as fh:
            json.dump(ledger.to_dict(), fh)

        class _Args:
            pass

        args = _Args()
        args.run_dir, args.repo = run_dir, None

        real_shell, real_write_override = stack.shell, stack.write_override
        stack.write_override = lambda *a, **k: False
        stack.shell = lambda *a, **k: subprocess.CompletedProcess([], 1, "", "boom")
        try:
            stack.cmd_up(args)
        finally:
            stack.shell, stack.write_override = real_shell, real_write_override

        project = stack.compose_project(repo, 26)
        assert not os.path.isfile(stack.lock_path(project)), \
            "the up-failed branch must release the lock"
        ctx = json.load(open(os.path.join(run_dir, "run.json")))["context"]
        assert ctx["stack"] == "failed"
ok("cmd_up's up-failed branch releases the stack lock")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        repo, run_dir = os.path.join(d, "repo"), os.path.join(d, "run")
        os.makedirs(repo)
        os.makedirs(run_dir)
        write(repo, "docker-compose.test.yml", "services: {}\n")
        write(repo, "go.mod", "module x")
        ledger = Ledger(27, ["dev"])
        ledger.context["repo"] = repo
        with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as fh:
            json.dump(ledger.to_dict(), fh)

        class _Args:
            pass

        args = _Args()
        args.run_dir, args.repo = run_dir, None

        shell_calls = []

        def _fake_shell(cmd, **kw):
            shell_calls.append(cmd)
            return subprocess.CompletedProcess([], 0, "", "")

        real_shell = stack.shell
        real_compose_config = stack.compose_config
        real_write_override = stack.write_override
        stack.shell = _fake_shell
        stack.compose_config = lambda *a, **k: {"services": {}}  # no app service found
        stack.write_override = lambda *a, **k: False
        try:
            stack.cmd_up(args)
        finally:
            stack.shell = real_shell
            stack.compose_config = real_compose_config
            stack.write_override = real_write_override

        project = stack.compose_project(repo, 27)
        assert not os.path.isfile(stack.lock_path(project)), \
            "the no-app-service branch must release the lock"
        assert any("down -v --remove-orphans" in c for c in shell_calls), \
            "the no-app-service branch must tear down the stack it just brought up"
        ctx = json.load(open(os.path.join(run_dir, "run.json")))["context"]
        assert ctx["stack"] == "failed"
        assert "no app service" in ctx["tests_unverified"]
ok("cmd_up's no-app-service branch tears the stack down and releases the lock "
   "(closed leak, stack.py:594-602)")

_real_shell = stack.shell
stack.shell = lambda cmd, **kw: subprocess.CompletedProcess([], 0, "0.0.0.0:34521\n", "")
try:
    assert stack.resolve_port("docker compose -p x -f c.yml", "/repo", "app", "80") == "34521"
finally:
    stack.shell = _real_shell

stack.shell = lambda cmd, **kw: subprocess.CompletedProcess([], 1, "", "no such service")
try:
    assert stack.resolve_port("docker compose -p x -f c.yml", "/repo", "app", "80") is None
finally:
    stack.shell = _real_shell
ok("resolve_port reads the live kernel-assigned port back from `docker compose port`, "
   "None when the lookup fails")

# --------------------------------------------------------------------------- dispatch: roster

assert dispatch.parse_issue_list("12,13,14") == [12, 13, 14]
ok("--issues 12,13,14 resolves in input order")

assert dispatch.parse_issue_list("#12, 13 ,#14") == [12, 13, 14]
ok("--issues parses # prefixes, spaces and repeated separators")

for bad in ("", ",,"):
    try:
        dispatch.parse_issue_list(bad)
        raise AssertionError(f"expected error for {bad!r}")
    except ValueError:
        pass
ok("--issues \"\" and \",,\" raise, distinct from a valid-but-empty roster")

for bad in ("abc", "-5"):
    try:
        dispatch.parse_issue_list(bad)
        raise AssertionError(f"expected error for {bad!r}")
    except ValueError:
        pass
ok("--issues abc / -5 raise with no partial parse")

assert dispatch.dedupe([12, 13, 12, 14, 13]) == [12, 13, 14]
ok("dedupe drops repeats, first occurrence wins, order stable")

# --------------------------------------------------------------------------- dispatch: DoR pre-screen

READY_BODY = """\
## Problem & why
Users cannot export data, which blocks their monthly report.

## Scope
In scope: CSV export. Out of scope: PDF export.

## Acceptance Criteria
- [ ] Given a user, when they click export, then a CSV downloads.

## Affected surface
`app/Http/Controllers/ExportController.php`

## Non-functional Constraints
None

## Dependencies / blockers
None
"""
assert dispatch.dor_gaps(READY_BODY) == []
ok("a body with all six DoR sections filled screens ready with zero gaps")

assert len(dispatch.dor_gaps(None)) == 6
assert len(dispatch.dor_gaps("")) == 6
ok("a None or empty body reports all six DoR items as gaps and never raises")

MISSING_SCOPE = READY_BODY.replace(
    "## Scope\nIn scope: CSV export. Out of scope: PDF export.\n\n", ""
)
gaps = dispatch.dor_gaps(MISSING_SCOPE)
assert len(gaps) == 1 and "scope" in gaps[0].lower(), gaps
ok("a body missing exactly one section names that specific gap")

for heading in ("### Acceptance Criteria", "## acceptance criteria", "## Acceptance criteria (draft)"):
    body = READY_BODY.replace("## Acceptance Criteria", heading)
    gaps = dispatch.dor_gaps(body)
    assert not any("acceptance" in g.lower() for g in gaps), (heading, gaps)
ok("heading variants (#/##/###, case, trailing text) all match Acceptance Criteria")

EMPTY_HEADING = READY_BODY.replace(
    "## Acceptance Criteria\n- [ ] Given a user, when they click export, then a CSV downloads.\n\n",
    "## Acceptance Criteria\n\n",
)
gaps = dispatch.dor_gaps(EMPTY_HEADING)
assert any("acceptance" in g.lower() for g in gaps), gaps
ok("a heading present with no content beneath it counts as a gap")

assert dispatch.dor_gaps(READY_BODY) == [], "literal 'None' under Non-functional Constraints satisfies it"
ok("'None' as the literal body under Non-functional Constraints satisfies that item")

# Regression for blocker 2 (PR #19 review): DOR_ITEMS' patterns must match the
# literal section headings commands/gh-issue.md actually emits, not just the
# generic definition-of-ready.md wording — otherwise every issue this
# plugin's own tooling produces reports permanent DoR gaps. Pin the two
# vocabularies together by parsing the real "Body sections:" line out of
# gh-issue.md itself, rather than hand-copying it here where it could drift.
GH_ISSUE_MD = os.path.join(HERE, "..", "commands", "gh-issue.md")
with open(GH_ISSUE_MD, encoding="utf-8") as fh:
    body_sections_line = next(
        line for line in fh if line.strip().startswith("- Body sections:")
    )
section_names = re.findall(r"\*\*([^*]+)\*\*", body_sections_line)
assert "Summary" in section_names and "Non-functional Constraints" in section_names, section_names
gh_issue_body = "\n\n".join(f"## {name}\nSome real content for {name}." for name in section_names)
assert dispatch.dor_gaps(gh_issue_body) == [], dispatch.dor_gaps(gh_issue_body)
ok("a body built from gh-issue.md's own literal section headings screens ready with zero gaps")

# Regression for issue #39: gh-issue.md must define an "Implementation Guide"
# section, placed after Acceptance Criteria and before Non-functional
# Constraints, without becoming a DoR item.
assert "Implementation Guide" in section_names, section_names
ok("Implementation Guide is present in gh-issue.md's Body sections list")

assert (
    section_names.index("Acceptance Criteria")
    < section_names.index("Implementation Guide")
    < section_names.index("Non-functional Constraints")
), section_names
ok("Implementation Guide is ordered after Acceptance Criteria and before Non-functional Constraints")

assert not any(re.search(pattern, "Implementation Guide", re.I) for _, pattern in dispatch.DOR_ITEMS), [
    label for label, pattern in dispatch.DOR_ITEMS if re.search(pattern, "Implementation Guide", re.I)
]
ok("no DOR_ITEMS pattern matches the Implementation Guide heading, keeping it a non-DoR section")

# --------------------------------------------------------------------------- dispatch: lane mode

assert dispatch.lane_mode(["lean"]) == "lean"
assert dispatch.lane_mode(["bug"]) == "full"
ok("an issue carrying the lean label resolves lean; one without it resolves full")

assert dispatch.lane_mode(["Lean"]) == "lean"
assert dispatch.lane_mode(["LEAN"]) == "lean"
ok("Lean/LEAN label text still resolves lean, case-insensitive")

assert dispatch.lane_mode(["bug", "lean", "p1"]) == "lean"
ok("an issue carrying lean plus other labels still resolves lean")

# --------------------------------------------------------------------------- dispatch: skip detection

with tempfile.TemporaryDirectory() as d:
    running = os.path.join(d, "running.json")
    write(d, "running.json", json.dumps({"status": "running"}))
    assert dispatch.skip_reason(running, False) is not None
ok("a run.json at status=running is a skip reason")

with tempfile.TemporaryDirectory() as d:
    for status in ("done", "escalated"):
        p = os.path.join(d, f"{status}.json")
        write(d, f"{status}.json", json.dumps({"status": status}))
        assert dispatch.skip_reason(p, False) is None, status
ok("a run.json at status=done or escalated is NOT a skip reason (re-runnable)")

with tempfile.TemporaryDirectory() as d:
    zero = os.path.join(d, "zero.json")
    write(d, "zero.json", "")
    corrupt = os.path.join(d, "corrupt.json")
    write(d, "corrupt.json", "{not json")
    assert dispatch.skip_reason(zero, False) is None
    assert dispatch.skip_reason(corrupt, False) is None
    assert dispatch.skip_reason(os.path.join(d, "missing.json"), False) is None
    assert dispatch.skip_reason(None, False) is None
ok("a corrupt, zero-byte, missing, or None run.json path is treated as no-existing-run, never raises")

assert dispatch.skip_reason(None, True) is not None
assert dispatch.skip_reason(os.path.join("/tmp", "does-not-exist.json"), True) is not None
ok("has_open_pr=True is a skip reason regardless of run.json state")

# --------------------------------------------------------------------------- dispatch: checkouts.json registry

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        assert dispatch.checkouts_path() == os.path.join(shared.data_dir(), "checkouts.json")
ok("checkouts_path() reuses shared.data_dir() rather than re-deriving it")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        assert dispatch.read_checkouts() == {}
        os.makedirs(os.path.dirname(dispatch.checkouts_path()), exist_ok=True)
        open(dispatch.checkouts_path(), "w").close()  # zero bytes
        assert dispatch.read_checkouts() == {}
        with open(dispatch.checkouts_path(), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        assert dispatch.read_checkouts() == {}
ok("the registry read function returns {} for a missing/zero-byte/non-JSON file")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        dispatch.register_checkout("o-r-issue-12", "/checkouts/o-r-issue-12")
        assert dispatch.read_checkouts() == {"o-r-issue-12": "/checkouts/o-r-issue-12"}
ok("a registration write followed by a read round-trips the slug->path mapping")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        dispatch.register_checkout("o-r-issue-1", "/c/1")
        # After any successful write, the file on disk is immediately valid JSON —
        # never a truncated fragment from a non-atomic write.
        with open(dispatch.checkouts_path(), encoding="utf-8") as fh:
            json.loads(fh.read())
        dispatch.register_checkout("o-r-issue-2", "/c/2")
        with open(dispatch.checkouts_path(), encoding="utf-8") as fh:
            data = json.loads(fh.read())
        assert data == {"o-r-issue-1": "/c/1", "o-r-issue-2": "/c/2"}
ok("registration writes are atomic: the file is always valid JSON immediately after a write")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        os.environ["AIW_TEST_SECRET_TOKEN"] = "shh-do-not-leak-me"
        try:
            dispatch.register_checkout("o-r-issue-9", "/c/9")
        finally:
            os.environ.pop("AIW_TEST_SECRET_TOKEN", None)
        with open(dispatch.checkouts_path(), encoding="utf-8") as fh:
            raw = fh.read()
        assert "shh-do-not-leak-me" not in raw
        assert ".env" not in raw
        # Exact equality on the parsed registry, not substring-matching against
        # arbitrary live os.environ values (any env var set to a single char
        # appearing in the JSON would false-trip a substring loop).
        assert json.loads(raw) == {"o-r-issue-9": "/c/9"}
ok("registry content is only slug->path pairs; no os.environ value or .env-shaped content lands in it")

# --------------------------------------------------------------------------- dispatch: CLI wiring (RED until run-dev updates route.py)

proc = subprocess.run([sys.executable, ROUTE, "dispatch", "plan", "--help"],
                      capture_output=True, text=True)
assert proc.returncode == 0, proc.stderr
ok("aiw dispatch plan --help exits 0 once dispatch is registered in route.py")

with tempfile.TemporaryDirectory() as d:
    dd = os.path.join(d, "data")
    env = dict(os.environ, CLAUDE_PLUGIN_DATA=dd)
    proc = subprocess.run([sys.executable, ROUTE, "paths"], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["checkouts"] == os.path.join(dd, "checkouts.json")
    assert out["data_dir"] == dd
    assert out["runs_dir"] == os.path.join(dd, "runs")
    assert out["pr_grind_dir"] == os.path.join(dd, "pr-grind")
    assert out["channels"] == os.path.join(dd, "channels.json")
ok("aiw paths prints a checkouts key and its other existing keys are unchanged")

# --------------------------------------------------------------------------- review: pick() (issue #24, RED until review.py exists)


def _review(review_id, commit_id, submitted_at, state="COMMENTED", body=""):
    return {
        "id": review_id,
        "commit_id": commit_id,
        "submitted_at": submitted_at,
        "state": state,
        "body": body,
    }


def _comment(review_id):
    return {"pull_request_review_id": review_id}


result = review.pick(
    reviews=[
        _review(1, "sha1", "2026-09-23T10:00:00", state="COMMENTED", body="fix this"),
        _review(2, "sha1", "2026-09-23T10:00:40", state="APPROVED", body="looks good"),
    ],
    comments=[_comment(1), _comment(1), _comment(1), _comment(1)],
)
assert result["selected"] == 1
assert result["superseded"] == [2]
ok("older COMMENTED review with 4 inline comments beats a newer rubber-stamp APPROVED review, same commit within window")

result = review.pick(
    reviews=[
        _review(1, "sha1", "2026-09-23T10:00:00", state="APPROVED", body="looks good"),
        _review(2, "sha1", "2026-09-23T10:00:40", state="COMMENTED", body="fix this"),
    ],
    comments=[_comment(2), _comment(2)],
)
assert result["selected"] == 2
assert result["superseded"] == [1]
ok("order reversed: comment-carrying review still wins over the rubber stamp")

result = review.pick(
    reviews=[
        _review(1, "sha1", "2026-09-23T10:00:00", state="COMMENTED", body="fix this"),
        _review(2, "sha1", "2026-09-23T10:00:40", state="COMMENTED", body="fix that too"),
    ],
    comments=[_comment(1), _comment(2)],
)
assert result["selected"] == 2
assert result["superseded"] == [1]
ok("both reviews carry inline comments: newest still wins (existing behavior unchanged)")

result = review.pick(
    reviews=[
        _review(1, "shaOLD", "2026-09-23T09:00:00", state="COMMENTED", body="fix this"),
        _review(2, "shaNEW", "2026-09-23T10:00:00", state="APPROVED", body="looks good"),
    ],
    comments=[_comment(1), _comment(1)],
)
assert result["selected"] == 2
assert result["superseded"] == [1]
ok("different commit_ids: newest wins even though the older commit's review carries the comments")

result = review.pick(
    reviews=[_review(1, "sha1", "2026-09-23T10:00:00", state="APPROVED", body="looks good")],
    comments=[],
)
assert result["selected"] == 1
assert result["superseded"] == []
ok("single review in the batch: it is selected, superseded is empty")

with tempfile.TemporaryDirectory() as d:
    reviews_path = os.path.join(d, "reviews.json")
    comments_path = os.path.join(d, "comments.json")
    with open(reviews_path, "w", encoding="utf-8") as fh:
        json.dump([
            _review(1, "sha1", "2026-09-23T10:00:00", state="COMMENTED", body="fix this"),
            _review(2, "sha1", "2026-09-23T10:00:40", state="APPROVED", body="looks good"),
        ], fh)
    with open(comments_path, "w", encoding="utf-8") as fh:
        json.dump([_comment(1), _comment(1)], fh)
    proc = subprocess.run(
        [sys.executable, ROUTE, "review", "pick", "--reviews", reviews_path, "--comments", comments_path],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert "selected" in out and "superseded" in out and "comment_counts" in out
ok("aiw review pick exits 0 and prints JSON with selected/superseded/comment_counts")

result = review.pick(
    reviews=[
        _review(1, "sha1", "2026-09-23T10:00:00", state="COMMENTED", body="fix this"),
        _review(2, "sha1", "2026-09-23T10:01:00", state="APPROVED", body="looks good"),
    ],
    comments=[_comment(1)],
)
assert result["selected"] == 1
ok("gap exactly at the 60s window edge is treated as inside the window")

result = review.pick(
    reviews=[
        _review(1, "sha1", "2026-09-23T10:00:00", state="COMMENTED", body="fix this"),
        _review(2, "sha1", "2026-09-23T10:01:01", state="APPROVED", body="looks good"),
    ],
    comments=[_comment(1)],
)
assert result["selected"] == 2
ok("gap of 61s on the same commit is outside the window, newest wins")

result = review.pick(
    reviews=[
        _review(1, "sha1", "2026-09-23T10:00:00", state="COMMENTED", body="fix this"),
        _review(2, "sha1", "2026-09-23T10:01:30", state="APPROVED", body="looks good"),
    ],
    comments=[_comment(1)],
)
assert result["selected"] == 2
ok("gap of 90s on the same commit is outside the window, newest wins")

result = review.pick(
    reviews=[
        _review(1, "sha1", "2026-09-23T10:00:00Z", state="COMMENTED", body="fix this"),
        _review(2, "sha1", "2026-09-23T10:00:40Z", state="APPROVED", body="looks good"),
    ],
    comments=[_comment(1)],
)
assert result["selected"] == 1
ok("GitHub Z-suffixed timestamps parse correctly")

result = review.pick(
    reviews=[
        _review(1, "sha1", "2026-09-23T10:00:00", state="APPROVED", body="looks good"),
        _review(2, "sha1", "2026-09-23T10:00:20", state="COMMENTED", body="fix this"),
        _review(3, "sha1", "2026-09-23T10:00:40", state="APPROVED", body="looks good"),
    ],
    comments=[_comment(2), _comment(2)],
)
assert result["selected"] == 2
assert sorted(result["superseded"]) == [1, 3]
ok("three reviews same commit in window, two zero-comment stamps and one with comments: comment-carrying wins, both stamps superseded")

result = review.pick(
    reviews=[
        _review(1, "sha1", "2026-09-23T10:00:00", state="COMMENTED", body="**Verdict: 2 blocker, 0 should-fix**"),
        _review(2, "sha1", "2026-09-23T10:00:40", state="APPROVED", body="looks good"),
    ],
    comments=[],
)
assert result["selected"] == 1
assert result["superseded"] == [2]
ok("no review carries inline comments: older verdict-carrying review is selected over the generic newer body")

result = review.pick(reviews=[], comments=[])
assert result["selected"] is None
assert result["superseded"] == []
ok("empty reviews list: selected is None, superseded is empty, no exception")

result = review.pick(
    reviews=[
        _review(1, "sha1", "2026-09-23T10:00:00", state="APPROVED", body="looks good"),
        _review(2, "sha1", "2026-09-23T10:00:40", state="APPROVED", body="looks good"),
    ],
    comments=[],
)
assert result["selected"] == 2
assert result["superseded"] == [1]
ok("reviews present but comments list empty: falls back to newest-wins, no exception")

result = review.pick(
    reviews=[
        {"id": 1, "state": "APPROVED", "body": "looks good"},
        {"id": 2, "commit_id": None, "submitted_at": None, "state": "COMMENTED", "body": "fix this"},
    ],
    comments=[_comment(2)],
)
assert isinstance(result["selected"], int)
non_selected = {1, 2} - {result["selected"]}
assert set(result["superseded"]) == non_selected
ok("review dicts missing/null commit_id and submitted_at: no KeyError/TypeError, every non-selected review still in superseded[]")

result = review.pick(
    reviews=[
        _review(1, "sha1", "2026-09-23T10:00:00Z", state="APPROVED", body="looks good"),
        _review(2, "sha1", "not-a-timestamp", state="APPROVED", body="looks good"),
    ],
    comments=[],
)
assert result["selected"] == 1
assert result["superseded"] == [2]
ok("unparseable submitted_at does not raise; that review is not treated as newest and is still superseded")

result = review.pick(
    reviews=[
        _review(1, "sha1", "2026-09-23T10:00:00", state="COMMENTED", body="fix this"),
        _review(2, "sha1", "2026-09-23T10:00:40", state="APPROVED", body="looks good"),
    ],
    comments=[{"pull_request_review_id": None}, {"pull_request_review_id": 999}],
)
assert result["comment_counts"].get(1, 0) == 0
assert result["comment_counts"].get(2, 0) == 0
ok("inline comments with null or foreign pull_request_review_id are not counted toward any review")

proc = subprocess.run(
    [sys.executable, ROUTE, "review", "pick", "--reviews", "/nonexistent/reviews.json", "--comments", "/nonexistent/comments.json"],
    capture_output=True, text=True,
)
assert proc.returncode != 0
assert "Traceback" not in proc.stderr
assert len([l for l in proc.stderr.splitlines() if l.strip()]) <= 1
ok("aiw review pick with a missing file exits nonzero with a one-line message, no Python traceback")

with tempfile.TemporaryDirectory() as d:
    reviews_path = os.path.join(d, "reviews.json")
    comments_path = os.path.join(d, "comments.json")
    with open(reviews_path, "w", encoding="utf-8") as fh:
        fh.write("not json{{{")
    with open(comments_path, "w", encoding="utf-8") as fh:
        fh.write("[]")
    proc = subprocess.run(
        [sys.executable, ROUTE, "review", "pick", "--reviews", reviews_path, "--comments", comments_path],
        capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "Traceback" not in proc.stderr
ok("aiw review pick with non-JSON input exits nonzero with a one-line message, no Python traceback")

with tempfile.TemporaryDirectory() as d:
    reviews_path = os.path.join(d, "reviews.json")
    comments_path = os.path.join(d, "comments.json")
    with open(reviews_path, "w", encoding="utf-8") as fh:
        fh.write('[{"id":1')
    with open(comments_path, "w", encoding="utf-8") as fh:
        fh.write("[]")
    proc = subprocess.run(
        [sys.executable, ROUTE, "review", "pick", "--reviews", reviews_path, "--comments", comments_path],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
ok("aiw review pick with a truncated JSON array exits code 1, no Python traceback (guards against a partial-dict recovery fallback that would feed pick() string keys)")

with tempfile.TemporaryDirectory() as d:
    reviews_dir = os.path.join(d, "reviews.json")
    os.makedirs(reviews_dir)
    comments_path = os.path.join(d, "comments.json")
    with open(comments_path, "w", encoding="utf-8") as fh:
        fh.write("[]")
    proc = subprocess.run(
        [sys.executable, ROUTE, "review", "pick", "--reviews", reviews_dir, "--comments", comments_path],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
ok("aiw review pick with a directory passed as --reviews exits code 1, no Python traceback (guards against an uncaught IsADirectoryError)")

with open(os.path.join(HERE, "..", "skills", "pr-grind", "SKILL.md"), encoding="utf-8") as fh:
    skill_text = fh.read()
assert "aiw review pick" in skill_text
assert "take the newest only" not in skill_text
ok("skills/pr-grind/SKILL.md Step 1 references `aiw review pick` and no longer states bare 'take the newest only' as the whole rule")

# --------------------------------------------------------------------------- gh-issue always decomposes before creating any issue (issue #38)

with open(os.path.join(HERE, "..", "commands", "gh-issue.md"), encoding="utf-8") as fh:
    gh_issue_text = fh.read()
assert "3.5. **Decompose.**" in gh_issue_text, "expected the renamed step heading '3.5. **Decompose.**'"
assert "Epic check" not in gh_issue_text, "old 'Epic check' heading text must be gone"
ok("commands/gh-issue.md step 3.5 is headed 'Decompose.' and no longer says 'Epic check'")

for choice in ("Create as shown", "Let me edit the list", "File as one issue instead"):
    assert choice in gh_issue_text, f"missing AskUserQuestion choice label: {choice!r}"
ok("commands/gh-issue.md contains all three AskUserQuestion choice labels verbatim")

epic_section_start = gh_issue_text.index("### 4-EPIC")
epic_section_end_match = re.search(r"^### (?!4-EPIC)", gh_issue_text[epic_section_start + 1:], re.MULTILINE)
epic_section_end = (
    epic_section_start + 1 + epic_section_end_match.start()
    if epic_section_end_match
    else len(gh_issue_text)
)
epic_section = gh_issue_text[epic_section_start:epic_section_end]
assert "Retry the missing ones" in epic_section, "4-EPIC section missing 'Retry the missing ones'"
assert "Stop here" in epic_section, "4-EPIC section missing 'Stop here'"
ok("commands/gh-issue.md's 4-EPIC section covers both 'Retry the missing ones' and 'Stop here'")

epic_section_flat = " ".join(epic_section.split())
assert "the parent and children 1..k-1" in epic_section_flat and "URLs" in epic_section_flat, \
    "4-EPIC section's partial-failure report must describe naming created issues (parent + children 1..k-1) with URLs"
assert "which are missing" in epic_section_flat and "by planned title" in epic_section_flat, \
    "4-EPIC section's partial-failure report must describe naming missing issues (k..N) by planned title"
ok("commands/gh-issue.md's 4-EPIC section's partial-failure report describes both created (parent+children, URLs) and missing (by planned title) issues")

with open(os.path.join(HERE, "..", "README.md"), encoding="utf-8") as fh:
    readme_text = fh.read()
assert "splits a large brief" not in readme_text, "README.md must no longer describe gh-issue as splitting a large brief"
ok("README.md no longer contains 'splits a large brief'")

with open(os.path.join(HERE, "..", "docs", "HOW-IT-WORKS.md"), encoding="utf-8") as fh:
    how_it_works_text = fh.read()
assert "can split a large brief" not in how_it_works_text, "HOW-IT-WORKS.md must no longer say 'can split a large brief'"
assert "For work too big for one pull request" not in how_it_works_text, "HOW-IT-WORKS.md must no longer say 'For work too big for one pull request'"
ok("docs/HOW-IT-WORKS.md no longer contains 'can split a large brief' or 'For work too big for one pull request'")

# --------------------------------------------------------------------------- checks.suite_timeout / run_suite timeout override (issue #25)

import checks  # noqa: E402
import route  # noqa: E402


class _FakeLedger:
    """A ledger stand-in carrying only what run_suite reads: .context."""

    def __init__(self, **context):
        self.context = context


def _stub_shell(calls):
    def fake(cmd, cwd=None, timeout=None, **kw):
        calls.append({"cmd": cmd, "cwd": cwd, "timeout": timeout})
        return subprocess.CompletedProcess([], 0, "ok\n", "")
    return fake


real_checks_shell = checks.shell

try:
    calls = []
    checks.shell = _stub_shell(calls)
    ledger = _FakeLedger(stack="none", test_cmd="pytest")
    code, detail = checks.run_suite(ledger, "/repo")
    assert code == 0 and detail == "ok"
    assert calls[-1]["timeout"] == 900
    assert checks.suite_timeout({}) == 900
finally:
    checks.shell = real_checks_shell
ok("suite_timeout with no overlay resolves to 900, and run_suite's shell call receives it")

try:
    with tempfile.TemporaryDirectory() as d:
        write(d, ".run-issue.json", json.dumps({"checks": {"suite_timeout": 2400}}))
        config = route.load_config(d)
        assert checks.suite_timeout(config) == 2400

        calls = []
        checks.shell = _stub_shell(calls)
        ledger = _FakeLedger(stack="none", test_cmd="pytest")
        checks.run_suite(ledger, "/repo", config=config)
        assert calls[-1]["timeout"] == 2400
finally:
    checks.shell = real_checks_shell
ok("an overlay {checks: {suite_timeout: 2400}} deep-merges via route.load_config and reaches shell")

try:
    def _timeout_shell(cmd, cwd=None, timeout=None, **kw):
        return subprocess.CompletedProcess([], 124, "", "")
    checks.shell = _timeout_shell
    with tempfile.TemporaryDirectory() as d:
        write(d, ".run-issue.json", json.dumps({"checks": {"suite_timeout": 2400}}))
        config = route.load_config(d)
    ledger = _FakeLedger(stack="none", test_cmd="pytest")
    code, detail = checks.run_suite(ledger, "/repo", config=config)
    assert code is None
    assert detail == "suite timed out after 2400s", detail
    assert "900" not in detail
finally:
    checks.shell = real_checks_shell
ok("the timeout message names the overridden 2400s, never the literal 900")

try:
    calls = []
    checks.shell = _stub_shell(calls)
    ledger = _FakeLedger(stack="none", test_cmd="pytest")
    code, detail = checks.run_suite(ledger, "/repo")
    assert code == 0
    assert detail == "ok"
finally:
    checks.shell = real_checks_shell
ok("happy path is unchanged: returncode 0 returns (0, last output line truncated to 200 chars)")

for value in (1, 0, -5):
    import io as _io2

    buf = _io2.StringIO()
    with contextlib.redirect_stderr(buf):
        resolved = checks.suite_timeout({"checks": {"suite_timeout": value}})
    if value == 1:
        assert resolved == 1, f"{value} -> {resolved}"
    else:
        assert resolved == 900, f"{value} -> {resolved}"
        assert str(value) in buf.getvalue(), buf.getvalue()
        assert "900" in buf.getvalue(), buf.getvalue()
ok("boundary: 1 is accepted; 0 and -5 are rejected with a stderr warning and fall back to 900")

for value in 1, 0, -5:
    calls = []
    checks.shell = _stub_shell(calls)
    try:
        with tempfile.TemporaryDirectory() as d:
            write(d, ".run-issue.json", json.dumps({"checks": {"suite_timeout": value}}))
            config = route.load_config(d)
        ledger = _FakeLedger(stack="none", test_cmd="pytest")
        checks.run_suite(ledger, "/repo", config=config)
        assert calls[-1]["timeout"] == (1 if value == 1 else 900), (value, calls[-1])
    finally:
        checks.shell = real_checks_shell
ok("suite_timeout=1 reaches shell as 1; 0 and -5 never reach shell — 900 does instead")

for bad in ("900", 900.5, 900.0, None, [], {}, True, False):
    buf = _io.StringIO()
    with contextlib.redirect_stderr(buf):
        resolved = checks.suite_timeout({"checks": {"suite_timeout": bad}})
    assert resolved == 900, f"{bad!r} -> {resolved}"
    assert "900" in buf.getvalue(), (bad, buf.getvalue())
ok("non-integer values, and bool True/False (an int subclass), are rejected and fall back to 900")

for checks_value in (None, {}, "absent"):
    config = {} if checks_value == "absent" else {"checks": checks_value}
    assert checks.suite_timeout(config) == 900, (checks_value, checks.suite_timeout(config))
ok("checks absent, checks: {} and checks: null all resolve to 900 without raising")

ledger = _FakeLedger(stack="failed", test_cmd=None)
code, detail = checks.run_suite(ledger, "/repo", config={"checks": {"suite_timeout": 2400}})
assert code is None and detail == "no runner (stack=failed)", detail

ledger = _FakeLedger(stack="none", test_cmd=None)
code, detail = checks.run_suite(ledger, "/repo", config={"checks": {"suite_timeout": 2400}})
assert code is None and detail == "no runner (stack=none)", detail
ok("run_suite's pre-shell bail-outs (no runner / no test_cmd) are unaffected by a suite_timeout override")

try:
    def _timeout_shell(cmd, cwd=None, timeout=None, **kw):
        return subprocess.CompletedProcess([], 124, "", "")
    checks.shell = _timeout_shell
    ledger = _FakeLedger(stack="none", test_cmd="pytest")
    envelope = {"handoff": {"test_files": ["run-engine/test_scripts.py"], "red_confirmed": True}}
    ledger.context["test_root"] = "run-engine"
    config = {"checks": {"suite_timeout": 2400}}
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "run-engine"))
        write(d, "run-engine/test_scripts.py", "")
        result = checks.check_sdet_post(ledger, envelope, d, config)
    assert result.unrunnable is True
    assert result.reason == "could not verify RED: suite timed out after 2400s", result.reason
finally:
    checks.shell = real_checks_shell
ok("check_sdet_post still wraps as 'could not verify RED: suite timed out after 2400s' with an override")

try:
    def _timeout_shell(cmd, cwd=None, timeout=None, **kw):
        return subprocess.CompletedProcess([], 124, "", "")
    checks.shell = _timeout_shell
    ledger = _FakeLedger(stack="none", test_cmd="pytest")
    envelope = {"handoff": {}}
    config = {"checks": {"suite_timeout": 2400}}
    with tempfile.TemporaryDirectory() as d:
        result = checks.check_dev_post(ledger, envelope, d, config)
    assert result.unrunnable is True
    assert result.reason == "could not verify the suite: suite timed out after 2400s", result.reason
finally:
    checks.shell = real_checks_shell
ok("check_dev_post still wraps as 'could not verify the suite: suite timed out after 2400s' with an override")

with tempfile.TemporaryDirectory() as d:
    write(d, ".run-issue.json", json.dumps({"checks": {"suite_timeout": 2400}}))
    config = route.load_config(d)
    assert config["checks"]["enabled"] is True, config["checks"]
    assert config["checks"]["skip"] == [], config["checks"]
    assert config["checks"]["suite_timeout"] == 2400, config["checks"]
ok("an overlay setting only suite_timeout keeps checks.enabled True and checks.skip []")

# --------------------------------------------------------------------------- test_cmd override (issue #27)
#
# `.run-issue.json` top-level `test_cmd` pins `cmd_up`'s recorded `test_cmd`, taking
# precedence over both the derived value and any prior ledger value. Read via a
# `stack.read_test_cmd_override(repo)` helper (per the approved plan). None of this
# The assertions below were written RED-first, against a not-yet-implemented
# `stack.read_test_cmd_override(repo)`; they now pass against the landed
# implementation.


class _Args:
    pass


def _up_args(run_dir, repo=None):
    a = _Args()
    a.run_dir, a.repo = run_dir, repo
    return a


def _seed_run(d, issue, repo_rel="repo", run_rel="run", extra_context=None):
    repo, run_dir = os.path.join(d, repo_rel), os.path.join(d, run_rel)
    os.makedirs(repo, exist_ok=True)
    os.makedirs(run_dir, exist_ok=True)
    ledger = Ledger(issue, ["dev"])
    ledger.context["repo"] = repo
    if extra_context:
        ledger.context.update(extra_context)
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(ledger.to_dict(), fh)
    return repo, run_dir


# -- override-reader helper: '' with no overlay, override string with one ----------

with tempfile.TemporaryDirectory() as d:
    assert stack.read_test_cmd_override(d) == "", \
        "no .run-issue.json at all must read back as absent, not raise"
    write(d, ".run-issue.json", json.dumps({"test_cmd": "php artisan test --configuration=x.xml"}))
    assert stack.read_test_cmd_override(d) == "php artisan test --configuration=x.xml"
ok("stack.read_test_cmd_override reads the top-level .run-issue.json test_cmd key, "
   "'' when there is none")

# -- null / blank / non-string values are all treated as absent --------------------

for bad_value in (None, "", "   ", 5, ["php", "artisan", "test"], {"cmd": "x"}, True):
    with tempfile.TemporaryDirectory() as d:
        write(d, ".run-issue.json", json.dumps({"test_cmd": bad_value}))
        assert stack.read_test_cmd_override(d) == "", \
            f"test_cmd={bad_value!r} must read back as absent, not crash or leak through"
ok("null, blank/whitespace-only, and non-string test_cmd overlay values are all "
   "treated as absent, no crash")

# -- no overlay, no compose file: unchanged derivation ------------------------------

with tempfile.TemporaryDirectory() as d:
    repo, run_dir = _seed_run(d, 30)
    write(repo, "go.mod", "module x")
    proc = subprocess.run([sys.executable, ROUTE, "stack", "up", run_dir],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    ctx = json.load(open(os.path.join(run_dir, "run.json")))["context"]
    assert ctx["test_cmd"] == ctx["test_cmd_host"] == "go test ./..."
ok("no overlay, no compose file: test_cmd == test_cmd_host == derived host runner "
   "(existing behavior unchanged)")

# -- overlay on the no-compose-file path: test_cmd is the override, test_cmd_host derived

with tempfile.TemporaryDirectory() as d:
    repo, run_dir = _seed_run(d, 31)
    write(repo, "go.mod", "module x")
    write(repo, ".run-issue.json", json.dumps({"test_cmd": "go test -run TestFoo ./..."}))
    proc = subprocess.run([sys.executable, ROUTE, "stack", "up", run_dir],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    ctx = json.load(open(os.path.join(run_dir, "run.json")))["context"]
    assert ctx["test_cmd"] == "go test -run TestFoo ./...", ctx["test_cmd"]
    assert ctx["test_cmd_host"] == "go test ./...", \
        "the override must not leak into test_cmd_host, which stays the raw derivation"
ok("overlay test_cmd on the no-compose-file path is recorded verbatim; test_cmd_host "
   "stays derived")

# -- overlay on the full success path: override wins over build_test_cmd -----------

with tempfile.TemporaryDirectory() as d:
    repo, run_dir = _seed_run(d, 32)
    write(repo, "docker-compose.test.yml", "services: {}\n")
    write(repo, "go.mod", "module x")
    write(repo, ".run-issue.json", json.dumps({"test_cmd": "custom exec cmd"}))
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):

        def _fake_shell(cmd, **kw):
            return subprocess.CompletedProcess([], 0, "", "")

        real_shell = stack.shell
        real_compose_config = stack.compose_config
        real_write_override = stack.write_override
        stack.shell = _fake_shell
        stack.compose_config = lambda *a, **k: {"services": {"app": {"build": {"context": "."}}}}
        stack.write_override = lambda *a, **k: False
        try:
            stack.cmd_up(_up_args(run_dir))
        finally:
            stack.shell = real_shell
            stack.compose_config = real_compose_config
            stack.write_override = real_write_override
    ctx = json.load(open(os.path.join(run_dir, "run.json")))["context"]
    assert ctx["stack"] == "up", ctx
    assert ctx["test_cmd"] == "custom exec cmd", \
        f"override must win over build_test_cmd's derivation, got {ctx['test_cmd']!r}"
ok("overlay test_cmd on the full success path is recorded instead of the "
   "build_test_cmd-derived command")

# -- two consecutive `stack up` calls with the same override still honor it --------

with tempfile.TemporaryDirectory() as d:
    repo, run_dir = _seed_run(d, 33)
    write(repo, "go.mod", "module x")
    write(repo, ".run-issue.json", json.dumps({"test_cmd": "go test -short ./..."}))
    for _ in range(2):
        proc = subprocess.run([sys.executable, ROUTE, "stack", "up", run_dir],
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        ctx = json.load(open(os.path.join(run_dir, "run.json")))["context"]
        assert ctx["test_cmd"] == "go test -short ./...", ctx["test_cmd"]
ok("two consecutive `stack up` calls with an override both record it, not just the first")

# -- degraded paths preserve a prior test_cmd instead of overwriting it with "" ----

with tempfile.TemporaryDirectory() as d:
    # lock-held path, no override, prior test_cmd already recorded.
    repo, run_dir, other_run = os.path.join(d, "repo"), os.path.join(d, "run"), os.path.join(d, "other")
    os.makedirs(repo)
    os.makedirs(run_dir)
    os.makedirs(other_run)
    write(repo, "docker-compose.test.yml", "services: {}\n")
    write(repo, "go.mod", "module x")
    ledger = Ledger(34, ["dev"])
    ledger.context.update(repo=repo, test_cmd="preexisting --configuration=x.xml")
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(ledger.to_dict(), fh)
    with open(os.path.join(other_run, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(Ledger(34, ["dev"]).to_dict(), fh)

    data_d = os.path.join(d, "data")
    project = stack.compose_project(repo, 34)
    lock_file = os.path.join(data_d, "locks", f"{project}.lock")
    os.makedirs(os.path.dirname(lock_file))
    with open(lock_file, "w", encoding="utf-8") as fh:
        json.dump({"run_dir": other_run, "issue": 34, "repo": repo, "acquired_at": time.time()}, fh)

    env = dict(os.environ, CLAUDE_PLUGIN_DATA=data_d, PATH="/nonexistent")
    proc = subprocess.run(
        [sys.executable, ROUTE, "stack", "up", run_dir, "--lock-timeout", "0"],
        capture_output=True, text=True, env=env,
    )
    assert proc.returncode == 0, proc.stderr
    ctx = json.load(open(os.path.join(run_dir, "run.json")))["context"]
    assert ctx["stack"] == "failed"
    assert ctx["test_cmd"] == "preexisting --configuration=x.xml", \
        f"lock-held degraded path must preserve the prior test_cmd, got {ctx['test_cmd']!r}"
ok("cmd_up's lock-held degraded path preserves a prior test_cmd instead of erasing it")

with tempfile.TemporaryDirectory() as d:
    # up-failed path, no override, prior test_cmd already recorded.
    repo, run_dir = os.path.join(d, "repo"), os.path.join(d, "run")
    os.makedirs(repo)
    os.makedirs(run_dir)
    write(repo, "docker-compose.test.yml", "services: {}\n")
    write(repo, "go.mod", "module x")
    ledger = Ledger(35, ["dev"])
    ledger.context.update(repo=repo, test_cmd="preexisting --configuration=x.xml")
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(ledger.to_dict(), fh)

    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        real_shell, real_write_override = stack.shell, stack.write_override
        stack.write_override = lambda *a, **k: False
        stack.shell = lambda *a, **k: subprocess.CompletedProcess([], 1, "", "boom")
        try:
            stack.cmd_up(_up_args(run_dir))
        finally:
            stack.shell, stack.write_override = real_shell, real_write_override
    ctx = json.load(open(os.path.join(run_dir, "run.json")))["context"]
    assert ctx["stack"] == "failed"
    assert ctx["test_cmd"] == "preexisting --configuration=x.xml", \
        f"up-failed degraded path must preserve the prior test_cmd, got {ctx['test_cmd']!r}"
ok("cmd_up's up-failed degraded path preserves a prior test_cmd instead of erasing it")

with tempfile.TemporaryDirectory() as d:
    # no-app-service path, no override, prior test_cmd already recorded.
    repo, run_dir = os.path.join(d, "repo"), os.path.join(d, "run")
    os.makedirs(repo)
    os.makedirs(run_dir)
    write(repo, "docker-compose.test.yml", "services: {}\n")
    write(repo, "go.mod", "module x")
    ledger = Ledger(36, ["dev"])
    ledger.context.update(repo=repo, test_cmd="preexisting --configuration=x.xml")
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(ledger.to_dict(), fh)

    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        real_shell = stack.shell
        real_compose_config = stack.compose_config
        real_write_override = stack.write_override
        stack.shell = lambda cmd, **kw: subprocess.CompletedProcess([], 0, "", "")
        stack.compose_config = lambda *a, **k: {"services": {}}  # no app service found
        stack.write_override = lambda *a, **k: False
        try:
            stack.cmd_up(_up_args(run_dir))
        finally:
            stack.shell = real_shell
            stack.compose_config = real_compose_config
            stack.write_override = real_write_override
    ctx = json.load(open(os.path.join(run_dir, "run.json")))["context"]
    assert ctx["stack"] == "failed"
    assert ctx["test_cmd"] == "preexisting --configuration=x.xml", \
        f"no-app-service degraded path must preserve the prior test_cmd, got {ctx['test_cmd']!r}"
ok("cmd_up's no-app-service degraded path preserves a prior test_cmd instead of erasing it")

# -- degraded path on a fresh ledger (no prior, no override) still records '' ------

with tempfile.TemporaryDirectory() as d:
    repo, run_dir = os.path.join(d, "repo"), os.path.join(d, "run")
    os.makedirs(repo)
    os.makedirs(run_dir)
    write(repo, "docker-compose.test.yml", "services: {}\n")
    write(repo, "go.mod", "module x")
    ledger = Ledger(37, ["dev"])
    ledger.context["repo"] = repo
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(ledger.to_dict(), fh)

    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        real_shell, real_write_override = stack.shell, stack.write_override
        stack.write_override = lambda *a, **k: False
        stack.shell = lambda *a, **k: subprocess.CompletedProcess([], 1, "", "boom")
        try:
            stack.cmd_up(_up_args(run_dir))
        finally:
            stack.shell, stack.write_override = real_shell, real_write_override
    ctx = json.load(open(os.path.join(run_dir, "run.json")))["context"]
    assert ctx["stack"] == "failed"
    assert ctx["test_cmd"] == "", ctx["test_cmd"]
ok("a degraded path with no prior test_cmd and no override still records '' "
   "(nothing to preserve, no regression to a stale value either)")

# -- override + a different prior value on a degraded path: override wins ----------

with tempfile.TemporaryDirectory() as d:
    repo, run_dir = os.path.join(d, "repo"), os.path.join(d, "run")
    os.makedirs(repo)
    os.makedirs(run_dir)
    write(repo, "docker-compose.test.yml", "services: {}\n")
    write(repo, "go.mod", "module x")
    write(repo, ".run-issue.json", json.dumps({"test_cmd": "the override wins"}))
    ledger = Ledger(38, ["dev"])
    ledger.context.update(repo=repo, test_cmd="a stale prior value")
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(ledger.to_dict(), fh)

    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        real_shell, real_write_override = stack.shell, stack.write_override
        stack.write_override = lambda *a, **k: False
        stack.shell = lambda *a, **k: subprocess.CompletedProcess([], 1, "", "boom")
        try:
            stack.cmd_up(_up_args(run_dir))
        finally:
            stack.shell, stack.write_override = real_shell, real_write_override
    ctx = json.load(open(os.path.join(run_dir, "run.json")))["context"]
    assert ctx["test_cmd"] == "the override wins", ctx["test_cmd"]
ok("an override on a degraded path wins over both the derived value and the prior "
   "ledger value")

# -- malformed .run-issue.json: `stack up` still exits 0, derives test_cmd, warns --

with tempfile.TemporaryDirectory() as d:
    repo, run_dir = _seed_run(d, 39)
    write(repo, "go.mod", "module x")
    write(repo, ".run-issue.json", "{ not valid json")
    proc = subprocess.run([sys.executable, ROUTE, "stack", "up", run_dir],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    ctx = json.load(open(os.path.join(run_dir, "run.json")))["context"]
    assert ctx["test_cmd"] == "go test ./...", \
        "a malformed overlay must fall back to the derived test_cmd, not crash the run"
    assert proc.stderr.strip() != "", "a malformed overlay must warn on stderr"
ok("a malformed .run-issue.json leaves `stack up` exiting 0 with a derived test_cmd, "
   "warning on stderr")

# --------------------------------------------------------------------------- run_suite: stack=failed is unconditionally unrunnable

ledger = _FakeLedger(stack="failed", test_cmd="php artisan test --configuration=x.xml")
shell_calls = []
real_checks_shell = checks.shell
checks.shell = _stub_shell(shell_calls)
try:
    code, detail = checks.run_suite(ledger, "/repo")
finally:
    checks.shell = real_checks_shell
assert code is None, \
    "stack=failed with a non-empty test_cmd must still be unrunnable, never a real exit code"
assert not shell_calls, "stack=failed must never shell out, override test_cmd or not"
ok("run_suite treats stack=failed as unconditionally unrunnable, even with a non-empty "
   "test_cmd left over from a prior successful run")

# -- regression guard: stack=none with a non-empty test_cmd still runs (host runner) --

ledger = _FakeLedger(stack="none", test_cmd="go test ./...")
shell_calls = []
checks.shell = _stub_shell(shell_calls)
try:
    code, detail = checks.run_suite(ledger, "/repo")
finally:
    checks.shell = real_checks_shell
assert code == 0 and detail == "ok", (code, detail)
assert shell_calls and shell_calls[0]["cmd"] == "go test ./...", \
    "the new stack=failed guard must not swallow the legitimate stack=none host-runner case"
ok("run_suite with stack=none and a non-empty test_cmd still runs it — the new "
   "stack=failed guard must not catch this legitimate host-runner case")

print(f"\n{passed} checks passed")
