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
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ci  # noqa: E402
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
assert stack.published_port(CONFIG, "laravel.test") == "8080"
assert stack.source_is_mounted(CONFIG, "laravel.test", "/repo") is True
assert stack.source_is_mounted(CONFIG, "laravel.test", "/elsewhere") is False
assert stack.pick_app_service({"services": {"postgres": {"image": "postgres"}}}) == "postgres"
ok("app service, published port and source mount are read off `compose config`")

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
    assert epic_json["max_stacks"] == 1, "one stack by default — `-p` does not namespace ports"
ok("epic split links by database id with -F, skips what is linked, and caps stacks at 1")

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

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        run_dir = os.path.join(d, "run")
        assert stack.acquire_lock(run_dir, 7, "o/r", 5) is True
        holder = json.load(open(stack.lock_path()))
        assert holder["run_dir"] == run_dir and holder["issue"] == 7 and holder["repo"] == "o/r"
        assert isinstance(holder["acquired_at"], (int, float))
ok("acquire_lock on a free lock writes run_dir/issue/repo/acquired_at and returns True")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        run_dir = os.path.join(d, "run")
        assert stack.acquire_lock(run_dir, 7, "o/r", 5) is True
        stack.release_lock(run_dir)
        assert not os.path.isfile(stack.lock_path())
ok("release_lock by the holding run_dir removes the lockfile")

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
        assert stack.acquire_lock(run_dir_a, 1, "o/r", 5) is True
        assert stack.acquire_lock(run_dir_b, 2, "o/r", 0) is False
        holder = json.load(open(stack.lock_path()))
        assert holder["run_dir"] == run_dir_a, "the first holder must still be recorded"
        stack.release_lock(run_dir_a)
        assert stack.acquire_lock(run_dir_b, 2, "o/r", 0) is True
ok("a second acquire for a different run_dir returns False without disturbing the first "
   "holder, and succeeds cleanly once the first releases")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        os.makedirs(os.path.dirname(stack.lock_path()), exist_ok=True)
        open(stack.lock_path(), "w").close()  # zero bytes
        assert stack.acquire_lock(os.path.join(d, "run"), 7, "o/r", 0) is True
ok("a zero-byte lockfile is treated as free/reclaimable, not a crash")

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        os.makedirs(os.path.dirname(stack.lock_path()), exist_ok=True)
        with open(stack.lock_path(), "w", encoding="utf-8") as fh:
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
    fresh = {"run_dir": run_dir, "acquired_at": now - stack.LOCK_GRACE + 5}
    old = {"run_dir": run_dir, "acquired_at": now - stack.LOCK_GRACE - 5}
    assert stack.lock_stale(fresh, now) is False, "not stale until past the grace"
    assert stack.lock_stale(old, now) is True, "done/escalated past the grace is reclaimed"
ok("a done/escalated holder is reclaimed only once past LOCK_GRACE")

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
        assert stack.acquire_lock(os.path.join(d, "other"), 2, "o/r", 0) is False
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

with tempfile.TemporaryDirectory() as d:
    with env_var("CLAUDE_PLUGIN_DATA", os.path.join(d, "data")):
        results = [None] * 8

        def _worker(i):
            rd = os.path.join(d, f"run{i}")
            os.makedirs(rd)
            with open(os.path.join(rd, "run.json"), "w", encoding="utf-8") as fh:
                json.dump(Ledger(i, ["dev"]).to_dict(), fh)
            results[i] = stack.acquire_lock(rd, i, "o/r", 0)

        pool = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
        for t in pool:
            t.start()
        for t in pool:
            t.join()
        assert results.count(True) == 1, results
ok("N simultaneous acquires produce exactly one winner")

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
        assert stack.acquire_lock(holder_run, 1, "o/r", 5) is True
        stack.release_lock(os.path.join(d, "impostor"))
        assert os.path.isfile(stack.lock_path())
        assert json.load(open(stack.lock_path()))["run_dir"] == holder_run
ok("release_lock from a non-holder run_dir does not remove another run's lockfile")

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
    assert not os.path.isfile(os.path.join(data_d, "stack.lock"))
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
    with open(os.path.join(other_run, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(Ledger(23, ["dev"]).to_dict(), fh)

    data_d = os.path.join(d, "data")
    os.makedirs(data_d)
    with open(os.path.join(data_d, "stack.lock"), "w", encoding="utf-8") as fh:
        json.dump({"run_dir": other_run, "issue": 23, "repo": repo, "acquired_at": time.time()}, fh)

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
    assert json.load(open(os.path.join(data_d, "stack.lock")))["run_dir"] == other_run
ok("`stack up` behind a non-stale foreign lock with --lock-timeout 0 degrades to stack=failed "
   "naming the holder, keeps test_cmd_host, exits 0, and never invokes Docker")

with tempfile.TemporaryDirectory() as d:
    run_dir = os.path.join(d, "run")
    os.makedirs(run_dir)
    ledger = Ledger(24, ["dev"])
    ledger.context.update(stack="up", compose_prefix="true")
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(ledger.to_dict(), fh)
    data_d = os.path.join(d, "data")
    os.makedirs(data_d)
    with open(os.path.join(data_d, "stack.lock"), "w", encoding="utf-8") as fh:
        json.dump({"run_dir": run_dir, "issue": 24, "repo": "o/r", "acquired_at": time.time()}, fh)
    env = dict(os.environ, CLAUDE_PLUGIN_DATA=data_d)
    proc = subprocess.run([sys.executable, ROUTE, "stack", "down", run_dir],
                          capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    assert not os.path.isfile(os.path.join(data_d, "stack.lock"))
ok("`stack down` releases the lock after a successful teardown, exit 0")

with tempfile.TemporaryDirectory() as d:
    run_dir = os.path.join(d, "run")
    os.makedirs(run_dir)
    ledger = Ledger(25, ["dev"])
    ledger.context.update(stack="up", compose_prefix="false")
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(ledger.to_dict(), fh)
    data_d = os.path.join(d, "data")
    os.makedirs(data_d)
    with open(os.path.join(data_d, "stack.lock"), "w", encoding="utf-8") as fh:
        json.dump({"run_dir": run_dir, "issue": 25, "repo": "o/r", "acquired_at": time.time()}, fh)
    env = dict(os.environ, CLAUDE_PLUGIN_DATA=data_d)
    proc = subprocess.run([sys.executable, ROUTE, "stack", "down", run_dir],
                          capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    assert not os.path.isfile(os.path.join(data_d, "stack.lock")), \
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

        assert not os.path.isfile(stack.lock_path()), "the up-failed branch must release the lock"
        ctx = json.load(open(os.path.join(run_dir, "run.json")))["context"]
        assert ctx["stack"] == "failed"
ok("cmd_up's up-failed branch releases the stack lock")

print(f"\n{passed} checks passed")
