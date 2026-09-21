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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ci  # noqa: E402
import epic  # noqa: E402
import project  # noqa: E402
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

print(f"\n{passed} checks passed")
