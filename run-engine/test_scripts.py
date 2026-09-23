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

# --------------------------------------------------------------------------- issue #29: rerun-denied CI fallback (doc invariants)
#
# agents/run-ci.md, commands/run-issue.md and skills/pr-grind/SKILL.md are the source of
# truth; these are drift-pinned to the literal text in those files (never hand-copied),
# following the GH_ISSUE_MD pattern above.

RUN_CI_MD = os.path.join(HERE, "..", "agents", "run-ci.md")
RUN_ISSUE_MD = os.path.join(HERE, "..", "commands", "run-issue.md")
PR_GRIND_SKILL_MD = os.path.join(HERE, "..", "skills", "pr-grind", "SKILL.md")

with open(RUN_CI_MD, encoding="utf-8") as fh:
    run_ci_text = fh.read()
with open(RUN_ISSUE_MD, encoding="utf-8") as fh:
    run_issue_text = fh.read()
with open(PR_GRIND_SKILL_MD, encoding="utf-8") as fh:
    pr_grind_text = fh.read()

# run-ci.md's outcome enum line, e.g. "outcome: fixed | flake-rerun | cannot-fix"
outcome_line = next(
    line for line in run_ci_text.splitlines() if line.strip().startswith("outcome:")
)
outcome_tokens = [t.strip() for t in outcome_line.split(":", 1)[1].split("|")]
assert "rerun-denied" in outcome_tokens, outcome_tokens
assert set(outcome_tokens) >= {"fixed", "flake-rerun", "cannot-fix", "rerun-denied"}, outcome_tokens
ok("run-ci.md's outcome enum contains rerun-denied alongside fixed|flake-rerun|cannot-fix")

# Every outcome token parsed from run-ci.md must be branched on (mentioned) in both
# run-issue.md phase 8.5 and SKILL.md rail 2's CI-red handling.
for token in outcome_tokens:
    assert token in run_issue_text, f"run-issue.md never branches on outcome {token!r}"
    assert token in pr_grind_text, f"SKILL.md never branches on outcome {token!r}"
ok("every outcome token parsed from run-ci.md is branched on in both run-issue.md phase 8.5 and SKILL.md rail 2")

# Both rails' fallback uses git commit --allow-empty with an identical retrigger
# message, compared across files rather than hand-copied.
def _allow_empty_commit_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if "--allow-empty" in line]

run_issue_allow_empty = _allow_empty_commit_lines(run_issue_text)
pr_grind_allow_empty = _allow_empty_commit_lines(pr_grind_text)
assert run_issue_allow_empty, "run-issue.md documents no --allow-empty fallback"
assert pr_grind_allow_empty, "SKILL.md documents no --allow-empty fallback"


def _retrigger_message(lines: list[str]) -> str:
    for line in lines:
        m = re.search(r'-m\s+"([^"]+)"', line)
        if m:
            return m.group(1)
    raise AssertionError(f"no -m \"...\" message found in {lines}")


run_issue_msg = _retrigger_message(run_issue_allow_empty)
pr_grind_msg = _retrigger_message(pr_grind_allow_empty)
assert run_issue_msg == pr_grind_msg, (run_issue_msg, pr_grind_msg)
ok("both rails' fallback uses git commit --allow-empty with an identical retrigger message")

# The retrigger commit message marks it as a CI retrigger and names the reason.
assert "retrigger" in run_issue_msg.lower() and "ci" in run_issue_msg.lower(), run_issue_msg
assert re.search(r"rerun denied|denied", run_issue_msg.lower()), run_issue_msg
ok("retrigger commit message marks it as CI retrigger and names the reason")

# Neither rail's fallback mentions gh run rerun/cancel/workflow run around the fallback
# text — the fallback path is git-only. (The pre-existing rerun/cancel/workflow-run
# mentions elsewhere in these docs, for run-ci's own permitted use, are untouched; this
# checks the fallback description itself never reintroduces an Actions write command.)
for label, lines in (("run-issue.md", run_issue_allow_empty), ("SKILL.md", pr_grind_allow_empty)):
    for line in lines:
        assert "gh run rerun" not in line, (label, line)
        assert "gh run cancel" not in line, (label, line)
        assert "gh workflow run" not in line, (label, line)
ok("neither rail's fallback line mentions gh run rerun/cancel/workflow run — git-only")

# run-ci.md contains no --allow-empty and no commit instruction on the flake path —
# run-ci diagnoses, the orchestrator commits.
flake_section_start = run_ci_text.index("**Infra flake**")
real_failure_start = run_ci_text.index("**Real failure**")
flake_section = run_ci_text[flake_section_start:real_failure_start]
assert "--allow-empty" not in flake_section, flake_section
assert "git commit" not in flake_section, flake_section
ok("run-ci.md contains no --allow-empty and no commit instruction on the flake path")

# run-issue.md's fleet-wide policy paragraph still states run-ci is the only agent
# permitted Actions write commands.
assert "`run-ci` is the only agent that may run GitHub Actions write commands." in run_issue_text
ok("run-issue.md's fleet-wide policy paragraph still states run-ci is the only agent permitted Actions write commands")

# Both rails gate the fallback on the existing ci-attempt:<sha> budget; no second
# budget key introduced.
assert "ci-attempt" in run_issue_text
assert "ci-attempt" in pr_grind_text
for label, text in (("run-issue.md", run_issue_text), ("SKILL.md", pr_grind_text)):
    for bad in ("retrigger-attempt", "fallback-attempt", "rerun-denied-attempt"):
        assert bad not in text, (label, bad)
ok("both rails gate the fallback on the existing ci-attempt:<sha> budget; no second budget key introduced")

# run-issue.md phase 8.5 records ci-attempt in the ledger (net-new).
phase_85_start = run_issue_text.index("## 8.5 CI gate")
phase_86_start = run_issue_text.index("## 9.1 Dump the run into the notes vault")
phase_85_text = run_issue_text[phase_85_start:phase_86_start]
assert "ci-attempt" in phase_85_text, "phase 8.5 never records ci-attempt in the ledger"
ok("run-issue.md phase 8.5 records ci-attempt in the ledger")

# Both rails document a retrigger-commit guard via `git log -1 --pretty=%s`.
assert "git log -1 --pretty=%s" in run_issue_text, "run-issue.md documents no retrigger-commit guard"
assert "git log -1 --pretty=%s" in pr_grind_text, "SKILL.md documents no retrigger-commit guard"
ok("both rails document a retrigger-commit guard via git log -1 --pretty=%s marker check")

# Both rails document the push-refused path falling through to the existing outcome.
assert "push" in phase_85_text.lower() and ("fall" in phase_85_text.lower() or "RED —" in phase_85_text)
rail2_start = pr_grind_text.index("2. **CI red**")
rail3_start = pr_grind_text.index("3. **Third-party human comment**")
rail2_text = pr_grind_text[rail2_start:rail3_start]
assert "push" in rail2_text.lower()
ok("both rails document the push-refused path falling through to the existing outcome")

# The --allow-empty line sits inside the rerun-denied branch only; cannot-fix branch
# unchanged (no --allow-empty anywhere near the cannot-fix wording in either rail).
cannot_fix_idx = rail2_text.index("`outcome: cannot-fix`")
cannot_fix_tail = rail2_text[cannot_fix_idx: cannot_fix_idx + 200]
assert "--allow-empty" not in cannot_fix_tail, cannot_fix_tail
ok("the --allow-empty line sits inside the rerun-denied branch only; cannot-fix branch unchanged")

# run-ci.md keeps "If you cannot tell which it is, it is a real failure" verbatim.
assert "If you cannot tell which it is, it is a **real failure**." in run_ci_text
ok('run-ci.md keeps "If you cannot tell which it is, it is a real failure" verbatim')

# SKILL.md still contains the run-fixer-never-while-red sentence verbatim.
assert "`run-fixer` is still **never** dispatched while CI is red" in pr_grind_text
ok("SKILL.md still contains the run-fixer-never-while-red sentence verbatim")

print(f"\n{passed} checks passed")
