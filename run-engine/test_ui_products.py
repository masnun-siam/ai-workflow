#!/usr/bin/env python3
"""Self-check for run-engine/ui_products.py and GET|POST /api/products (issue #929).

`python3 test_ui_products.py` — exit 0 = green. Assert-based, no framework, no network.
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

data_dir = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = data_dir

import dispatch  # noqa: E402
import ui_products  # noqa: E402
import ui_repos  # noqa: E402
import ui_server  # noqa: E402

PRODUCTS = os.path.join(data_dir, "products.json")
CHECKOUTS = os.path.join(data_dir, "checkouts.json")
passed = 0


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


def git_repo(path, slug=None):
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", path], check=True)
    if slug:
        subprocess.run(["git", "-C", path, "remote", "add", "origin", f"https://github.com/{slug}.git"], check=True)
    return os.path.realpath(path)


def write_map(path, repos):
    os.makedirs(os.path.join(path, ".blubird"), exist_ok=True)
    with open(os.path.join(path, ".blubird", "repos.json"), "w") as f:
        f.write(repos if isinstance(repos, str) else json.dumps({"repos": repos}))


def entry(name, repo, path, role="code"):
    return {"name": name, "role": role, "repo": repo, "path": path}


def reset():
    for f in (PRODUCTS, CHECKOUTS):
        if os.path.exists(f):
            os.remove(f)


def raises(fn, *needles):
    try:
        fn()
    except ValueError as e:
        for n in needles:
            assert n in str(e), (n, str(e))
        return str(e)
    raise AssertionError("no ValueError")


def snapshot():
    return {f: open(f).read() if os.path.exists(f) else None for f in (PRODUCTS, CHECKOUTS)}


root = os.path.realpath(tempfile.mkdtemp())

try:
    # read_map: valid and every invalid shape
    d = os.path.join(root, "maps")
    os.makedirs(d)
    raises(lambda: ui_products.read_map(d), "no .blubird/repos.json")
    for bad, why in (
        ("{nope", "not valid JSON"),
        ("[]", "JSON object"),
        ('{"repos": []}', "non-empty"),
        ('{"repos": {}}', "non-empty"),
        ('{"repos": [1]}', "not an object"),
        (json.dumps({"repos": [entry("a", "o/a", ".") | {"repo": "nope"}]}), "owner/name"),
    ):
        write_map(d, bad)
        raises(lambda: ui_products.read_map(d), why)
    for k in ("name", "role", "repo", "path"):
        e = entry("a", "o/a", ".")
        del e[k]
        write_map(d, [e])
        raises(lambda: ui_products.read_map(d), f"`{k}`")
    write_map(d, "{}")
    with open(os.path.join(d, ".blubird", "repos.json"), "wb") as f:
        f.write(b"\xff")
    raises(lambda: ui_products.read_map(d), "not valid UTF-8")
    write_map(d, [entry("a", "o/a", ".")])
    assert ui_products.read_map(d) == [entry("a", "o/a", ".")]
    ok("read_map: valid map and each invalid shape")

    # monorepo
    mono = git_repo(os.path.join(root, "mono"), "o/mono")
    write_map(mono, [{"name": "mono", "role": "plugin", "repo": "o/mono", "path": "."}])
    row = ui_products.register(mono)
    assert row["docs_repo"] == "o/mono" and row["path"] == mono
    assert row["repos"] == [{"name": "mono", "role": "plugin", "repo": "o/mono", "path": mono, "cloned": True}], row
    assert dispatch.read_checkouts() == {"o/mono": mono}
    ok("monorepo: one product of one cloned repo")

    # docs repo with two code repos, one at ../api (outside the docs folder)
    reset()
    prod = os.path.join(root, "prod")
    docs = git_repo(os.path.join(prod, "docs"), "o/docs")
    api = git_repo(os.path.join(prod, "api"), "o/api")
    web = git_repo(os.path.join(docs, "web"), "o/web")
    write_map(docs, [entry("api", "o/api", "../api"), entry("web", "o/web", "web")])
    row = ui_products.register(docs)
    assert json.load(open(PRODUCTS)) == {"o/docs": docs}
    assert [(r["repo"], r["path"], r["cloned"]) for r in row["repos"]] == [("o/api", api, True), ("o/web", web, True)]
    assert ui_products.list_products() == [row]
    assert dispatch.read_checkouts() == {"o/docs": docs, "o/api": api, "o/web": web}
    ok("register: docs repo + two code repos, ../api resolved, all in checkouts")

    before = snapshot()
    assert ui_products.register(docs) == row and snapshot() == before
    co = dispatch.read_checkouts()
    co["O/API"] = co.pop("o/api")
    with open(CHECKOUTS, "w") as f:
        json.dump(co, f)
    ui_products.register(docs)
    assert [k for k in dispatch.read_checkouts() if k.lower() == "o/api"] == ["O/API"]
    assert dispatch.rename_checkout("O/API", "o/api")
    ok("register twice is idempotent, even with a slug stored in another case")

    shutil.rmtree(api)
    rows = ui_products.list_products()
    assert [(r["repo"], r["cloned"]) for r in rows[0]["repos"]] == [("o/api", False), ("o/web", True)]
    ok("deleted clone lists cloned: false")

    # sync picks up the re-clone, then does nothing
    git_repo(api, "o/api")
    dispatch.remove_checkout("o/api")
    ui_products.sync()
    assert dispatch.read_checkouts()["o/api"] == api
    no_git = AssertionError("no git work")
    with mock.patch.object(ui_repos, "register", side_effect=no_git), mock.patch("subprocess.run", side_effect=no_git):
        ui_products.sync()
        ui_products.list_products()
    ok("sync: registers a new clone; second call does no git work")

    # product_of
    assert ui_products.product_of("O/DOCS")["docs_repo"] == "o/docs"
    assert ui_products.product_of("o/WEB")["docs_repo"] == "o/docs"
    assert ui_products.product_of("x/y") is None
    ok("product_of: by docs repo or listed repo, any case; None when unknown")

    # register refused: a code repo already registered elsewhere
    reset()
    other_web = git_repo(os.path.join(root, "elsewhere", "web"), "o/web")
    dispatch.register_checkout("o/web", other_web)
    before = snapshot()
    raises(lambda: ui_products.register(docs), other_web, web)
    assert snapshot() == before
    ok("register: code repo registered at another path is refused, nothing written")

    # register refused: clone with another origin, a repo mapped twice, a "." entry for another repo;
    # non-string path; non-git path; no origin
    reset()
    write_map(docs, [entry("api", "o/other", "../api")])
    raises(lambda: ui_products.register(docs), "not o/other")
    assert not os.path.exists(PRODUCTS)
    raises(lambda: ui_products.register(None), "string")
    reset()
    write_map(docs, [entry("a1", "o/api", "../api"), entry("a2", "o/api", "web")])
    raises(lambda: ui_products.register(docs), "mapped to both", api, web)
    write_map(docs, [entry("d", "o/docs", "web")])
    raises(lambda: ui_products.register(docs), "mapped to both", docs, web)
    write_map(docs, [entry("z", "o/zzz", ".")])
    raises(lambda: ui_products.register(docs), "points at the docs repo")
    assert not os.path.exists(PRODUCTS) and not os.path.exists(CHECKOUTS)
    raises(lambda: ui_products.register(os.path.join(root, "maps")), "not a git repository")
    noorigin = git_repo(os.path.join(root, "noorigin"))
    write_map(noorigin, [entry("a", "o/a", ".")])
    raises(lambda: ui_products.register(noorigin), "no GitHub origin")
    for bad in ("{nope", '{"repos": []}'):
        write_map(docs, bad)
        raises(lambda: ui_products.register(docs))
    shutil.rmtree(os.path.join(docs, ".blubird"))
    raises(lambda: ui_products.register(docs), "no .blubird/repos.json")
    assert not os.path.exists(PRODUCTS)
    ok("register: bad origin, bad path, no origin, bad or missing map store nothing")

    # a missing clone is skipped by register, later picked up by sync; sync skips bad entries
    reset()
    write_map(docs, [entry("api", "o/api", "../api"), entry("web", "o/web", "web"), entry("x", "o/x", "../x")])
    xs = os.path.join(prod, "x")
    ui_products.register(docs)
    assert "o/x" not in dispatch.read_checkouts()
    git_repo(xs, "o/x")
    dispatch.remove_checkout("o/web")
    subprocess.run(["git", "-C", web, "remote", "set-url", "origin", "https://github.com/o/notweb.git"], check=True)
    ui_products.sync()
    co = dispatch.read_checkouts()
    assert co.get("o/x") == os.path.realpath(xs) and "o/web" not in co, co
    ok("sync: new clone registered, entry with another origin skipped")

    # a product whose map breaks lists an error row and sync skips it (a NUL path is a broken map too)
    write_map(docs, [entry("n", "o/n", "x\0y")])
    assert "`path`" in ui_products.list_products()[0]["error"]
    with open(os.path.join(docs, ".blubird", "repos.json"), "w") as f:
        f.write("{broken")
    dispatch.remove_checkout("o/x")
    rows = ui_products.list_products()
    assert rows[0]["repos"] == [] and "not valid JSON" in rows[0]["error"], rows
    assert ui_products.product_of("o/docs") is None
    ui_products.sync()
    assert "o/x" not in dispatch.read_checkouts()
    os.remove(PRODUCTS)
    ui_products.sync()
    ok("broken map: error row, not synced; missing products.json: sync is a no-op")

    # conflicts: two products list o/shared; o/mono is docs of one and code repo of another
    reset()
    write_map(docs, [entry("shared", "o/shared", "../shared"), entry("mono", "o/mono", "../../mono")])
    write_map(mono, [{"name": "mono", "role": "plugin", "repo": "o/mono", "path": "."}, entry("s", "o/shared", "s")])
    ui_products.register(docs)
    assert ui_products.register(mono)["docs_repo"] == "o/mono"  # not o/docs, which also lists o/mono
    by = {p["docs_repo"]: {r["repo"]: r.get("conflict") for r in p["repos"]} for p in ui_products.list_products()}
    assert by == {
        "o/docs": {"o/shared": "o/mono", "o/mono": "o/mono"},
        "o/mono": {"o/mono": "o/docs", "o/shared": "o/docs"},
    }, by
    ok("conflict on rows listed by two products, docs-repo-as-code-repo included")

    # sync skips a repo registered at a different path (it is already known)
    dispatch.register_checkout("o/shared", other_web)
    git_repo(os.path.join(prod, "shared"), "o/shared")
    ui_products.sync()
    assert dispatch.read_checkouts()["o/shared"] == other_web
    ok("sync: a repo registered at another path is left alone")

    # mapped
    assert ui_products.mapped(mono) and not ui_products.mapped(noorigin + "/nope")
    dr = os.path.join(root, "dr")
    os.makedirs(os.path.join(dr, ".blubird"))
    assert not ui_products.mapped(dr)
    open(os.path.join(dr, ".blubird", "docs-repo"), "w").close()
    assert ui_products.mapped(dr) and ui_products.mapped(None) is False
    ok("mapped: repos.json or docs-repo; False otherwise, never raises")

    # routes
    reset()
    srv = ui_server._Server(("127.0.0.1", 0), ui_server._Handler, ())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]

    def call(method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        raw = json.dumps(body).encode() if body is not None else b""
        c.request(
            method, path, body=raw or None, headers={"Host": f"127.0.0.1:{port}", "Content-Length": str(len(raw))}
        )
        r = c.getresponse()
        out = json.loads(r.read())
        c.close()
        return r.status, out

    assert call("GET", "/api/products") == (200, [])
    for b in ({}, {"path": 3}, {"path": os.path.join(root, "maps")}, {"path": noorigin + "/nope"}):
        assert call("POST", "/api/products", b)[0] == 400, b
    write_map(docs, "{nope")
    st, out = call("POST", "/api/products", {"path": docs})
    assert st == 400 and "not valid JSON" in out["error"], out
    dispatch.register_checkout("o/api", other_web)
    write_map(docs, [entry("api", "o/api", "../api")])
    st, out = call("POST", "/api/products", {"path": docs})
    assert st == 400 and other_web in out["error"] and not os.path.exists(PRODUCTS), out
    dispatch.remove_checkout("o/api")
    st, out = call("POST", "/api/products", {"path": docs})
    assert st == 200 and out["docs_repo"] == "o/docs" and out["repos"][0]["cloned"] is True, out
    assert call("GET", "/api/products") == (200, [out])
    srv.shutdown()
    ok("routes: GET [] then the product; POST 400 cases and 200")
finally:
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(data_dir, ignore_errors=True)

print(f"{passed} passed")
