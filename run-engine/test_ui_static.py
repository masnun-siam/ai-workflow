#!/usr/bin/env python3
"""Self-check for static serving in run-engine/ui_server.py (issue #109).
`python3 test_ui_static.py` — exit 0 = green. Assert-based, like test_ui_server.py.
"""

from __future__ import annotations

import http.client
import mimetypes
import os
import pathlib
import re
import shutil
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ui_server

passed = 0
REPO = os.path.dirname(HERE)
STATIC = os.path.join(HERE, "ui_static")
VENDOR = os.path.join(STATIC, "vendor")


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ok  {label}")


def boom(*_a, **_k):
    raise AssertionError("fetch_title must not be called")


def req(port, path, host=None, origin=None):
    host = f"127.0.0.1:{port}" if host is None else host
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
    if host:
        c.putheader("Host", host)
    if origin is not None:
        c.putheader("Origin", origin)
    c.endheaders()
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, r, body


def read(p):
    with open(p, "rb") as f:
        return f.read()


srv = ui_server._Server(("127.0.0.1", 0), ui_server._Handler, (), boom)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
tmp = tempfile.mkdtemp()
real_static = getattr(ui_server, "STATIC_DIR", None)
SHELL = sys.argv[1:3] == ["--view", "shell"]
LAUNCHER = sys.argv[1:3] == ["--view", "launcher"]
LAUNCHER_ALL = sys.argv[1:3] == ["--view", "launcher-all"]
BOARD = sys.argv[1:3] == ["--view", "board"]

NODE_JS = r"""
const { parseRoute, waitingInfo, headerBadge, sessionList, poll } = await import(process.env.APP_URL);
const assert = (await import('node:assert')).strict;
const out = (n) => console.log('ok ' + n);
const tick = () => new Promise((r) => setImmediate(r));
out('import without document does not throw');

const nm = (h) => parseRoute(h).name;
assert.equal(nm('#/'), 'board');
const run = parseRoute('#/run/acme/web/42');
assert.equal(run.name, 'run');
assert.deepEqual({ ...run.params }, { owner: 'acme', repo: 'web', n: 42 });
const ans = parseRoute('#/answer/abc123');
assert.equal(ans.name, 'answer');
assert.equal(ans.params.session, 'abc123');
assert.equal(nm('#/new'), 'new');
assert.equal(nm('#/sessions'), 'sessions');
out('parseRoute normal routes');

assert.equal(nm(''), 'board');
assert.equal(nm('#'), 'board');
out('parseRoute empty hash is board');

for (const h of ['#/run/acme/web', '#/run/acme/web/0', '#/run/acme/web/-1', '#/run/acme/web/4x',
  '#/run/a/b/1/extra', '#/answer/', '#/bogus']) assert.equal(nm(h), 'notfound', h);
out('parseRoute boundary routes are notfound');

assert.equal(nm('#/sessions/'), 'sessions');
assert.equal(parseRoute('#/answer/a%20b').params.session, 'a b');
assert.equal(nm('#/answer/%E0%A4%A'), 'notfound');
out('parseRoute trailing slash, decoding, malformed escape');

const mk = (id, status) => (status === undefined ? { id } : { id, status });
const list = [mk('a', 'running'), mk('b', 'waiting'), mk('c', 'done'), mk('d', 'waiting')];
assert.deepEqual({ ...waitingInfo(list) }, { count: 2, firstId: 'b' });
out('waitingInfo counts waiting, first in API order');
assert.deepEqual({ ...waitingInfo([]) }, { count: 0, firstId: null });
assert.equal(waitingInfo([mk('x'), mk('y')]).count, 0);
out('waitingInfo empty and missing status');
for (const bad of [null, {}, { sessions: 5 }, 'str', undefined]) assert.equal(waitingInfo(bad).count, 0);
assert.deepEqual({ ...waitingInfo({ sessions: list }) }, { count: 2, firstId: 'b' });
out('waitingInfo non-array bodies and {sessions:[]}');

assert.deepEqual({ ...headerBadge(true, list) }, { kind: 'offline', count: 0, href: null });
assert.deepEqual({ ...headerBadge(true, null) }, { kind: 'offline', count: 0, href: null });
assert.deepEqual({ ...headerBadge(false, list) }, { kind: 'waiting', count: 2, href: '#/answer/b' });
assert.equal(headerBadge(false, [mk('a b', 'waiting')]).href, '#/answer/a%20b');
assert.deepEqual({ ...headerBadge(false, [mk('a', 'running')]) }, { kind: 'idle', count: 0, href: null });
assert.deepEqual({ ...headerBadge(false, []) }, { kind: 'idle', count: 0, href: null });
assert.equal(headerBadge(false, null), null);
assert.equal(headerBadge(false, undefined), null);
assert.deepEqual(sessionList({ sessions: list }), list);
assert.equal(sessionList('x'), null);
out('headerBadge offline, waiting, idle, pre-response');

// poll harness
const doc = { hidden: false, ls: {}, addEventListener(t, f) { (this.ls[t] ||= []).push(f); },
  removeEventListener(t, f) { this.ls[t] = (this.ls[t] || []).filter((x) => x !== f); } };
const fire = (t) => (doc.ls[t] || []).slice().forEach((f) => f());
globalThis.document = doc;
let timers = [], tid = 0, calls = [], pend = [];
globalThis.setTimeout = (fn, ms) => { const t = { id: ++tid, fn, ms }; timers.push(t); return t.id; };
globalThis.clearTimeout = (id) => { timers = timers.filter((t) => t.id !== id); };
globalThis.fetch = (u) => { calls.push(u); return new Promise((res, rej) => pend.push({ res, rej })); };
const resp = (ok, status, body) => ({ ok, status, json: async () => { if (body instanceof Error) throw body; return body; } });
const results = [];
const stop = poll('/api/sessions', 1000, (r) => results.push(r));
assert.equal(calls.length, 1); assert.equal(calls[0], '/api/sessions');
assert.equal(timers.length, 0);
await tick();
assert.equal(timers.length, 0, 'no overlap while request in flight');
pend.shift().res(resp(true, 200, [1]));
await tick();
assert.deepEqual(results.at(-1), { ok: true, data: [1] });
assert.equal(timers.length, 1);
out('poll fetches immediately, schedules after settle');

timers.shift().fn();
assert.equal(calls.length, 2);
assert.equal(timers.length, 0);
doc.hidden = true;
pend.shift().res(resp(true, 200, []));
await tick();
assert.equal(timers.length, 0, 'nothing scheduled while hidden');
out('poll schedules nothing while hidden');

doc.hidden = false; fire('visibilitychange');
assert.equal(calls.length, 3, 'visible fetches immediately');
pend.shift().res(resp(true, 200, []));
await tick();
assert.equal(timers.length, 1);
doc.hidden = true; fire('visibilitychange');
assert.equal(timers.length, 0, 'hidden clears pending timer');
doc.hidden = false; fire('visibilitychange');
assert.equal(calls.length, 4);
pend.shift().res(resp(true, 200, []));
await tick();
assert.equal(timers.length, 1, 'schedule resumed');
out('poll visibilitychange clears and resumes');

// errors
timers.shift().fn(); pend.shift().rej(new Error('net')); await tick();
assert.equal(results.at(-1).ok, false); assert.equal(timers.length, 1);
timers.shift().fn(); pend.shift().res(resp(false, 404, {})); await tick();
assert.equal(results.at(-1).ok, false); assert.equal(timers.length, 1);
timers.shift().fn(); pend.shift().res(resp(true, 200, new SyntaxError('bad'))); await tick();
assert.equal(results.at(-1).ok, false); assert.equal(timers.length, 1);
timers.shift().fn(); pend.shift().res(resp(true, 200, [2])); await tick();
assert.deepEqual(results.at(-1), { ok: true, data: [2] });
assert.equal(timers.length, 1);
out('poll reports failures as ok:false, keeps polling, recovers');

const n = calls.length;
stop();
assert.equal(timers.length, 0);
assert.equal((doc.ls.visibilitychange || []).length, 0);
doc.hidden = false; fire('visibilitychange');
await tick();
assert.equal(calls.length, n);
out('poll stop clears timer and listener');
"""


def shell_checks():
    import subprocess

    index = read(os.path.join(STATIC, "index.html")).decode()
    s, r, body = req(port, "/")
    assert s == 200 and body.decode() == index
    assert 'name="viewport"' in index and '<div id="app">' in index
    assert re.search(r'<script[^>]*type="module"[^>]*src="/static/app\.js"', index), "app.js script"
    assert re.search(r'<link[^>]*rel="stylesheet"[^>]*href="/static/app\.css"', index), "app.css link"
    assert not re.search(r'(?:src|href)="https?://', index), "no external origins"
    ok("index.html links app.js/app.css, no CDN")

    for name, t in (("app.js", "text/javascript"), ("app.css", "text/css")):
        s, r, _ = req(port, f"/static/{name}")
        assert s == 200 and r.getheader("Content-Type", "").startswith(t), (name, s)
    ok("app.js/app.css served with correct types")

    js = read(os.path.join(STATIC, "app.js")).decode()
    css = read(os.path.join(STATIC, "app.css")).decode()
    specs = re.findall(r"""(?:^|\n)\s*import\b[^'"]*?from\s*['"]([^'"]+)['"]""", js)
    assert specs, "no imports found"
    assert set(specs) <= {"./vendor/preact.mjs", "./vendor/htm.mjs", "./launcher.js", "./board.js"}, specs
    assert not re.search(r"https?://", js), "no absolute URLs"
    pre = read(os.path.join(VENDOR, "preact.mjs")).decode()
    exports = re.search(r"export\s*\{([^}]*)\}", pre).group(1)
    names = {x.split(" as ")[-1].strip() for x in exports.split(",")}
    for m in re.finditer(r"import\s*\{([^}]*)\}\s*from\s*['\"]\./vendor/preact\.mjs", js):
        for n in m.group(1).split(","):
            n = n.strip().split(" as ")[0].strip()
            assert n in names, f"{n} not exported by preact.mjs"
    ok("app.js imports only vendored modules, real names")

    for t, src in (("app.js", js), ("app.css", css)):
        assert "console.log" not in src and "debugger" not in src, t
    ok("no console.log/debugger")

    assert "#0e1116" in css.lower() and "#5eead4" in css.lower()
    assert re.search(r"--[\w-]*(?:waiting|amber)[\w-]*\s*:", css), "amber variable"
    assert re.search(r"flex-wrap\s*:\s*wrap", css)
    heights = [int(x) for x in re.findall(r"min-height\s*:\s*(\d+)px", css)]
    assert heights and max(heights) >= 44, heights
    for m in re.finditer(r"(?<![\w-])(?:min-)?width\s*:\s*(\d+)px", css):
        assert int(m.group(1)) <= 390, m.group(0)
    ok("css palette, wrapping header, tap targets, no wide fixed widths")

    assert "/api/sessions" in js
    ok("app.js fetches /api/sessions")

    if not shutil.which("node"):
        print("note: node not found, skipping shell logic checks")
        return
    env = dict(os.environ, APP_URL=pathlib.Path(os.path.join(STATIC, "app.js")).as_uri())
    p = subprocess.run(["node", "--input-type=module", "-e", NODE_JS], env=env,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr[-1500:]
    for line in p.stdout.splitlines():
        if line.startswith("ok "):
            ok(line[3:])


BOARD_JS = r"""
const B = await import(process.env.BOARD_URL);
const { parseRoute } = await import(process.env.APP_URL);
const assert = (await import('node:assert')).strict;
const out = (n) => console.log('ok ' + n);
const { cardTitle, runHref, matchSession, cardChips, formatCost, filterColumns, repoOptions, boardChanged } = B;
const card = { owner: 'acme', repo: 'web', issue: 42 };
const S = (owner, repo, issue, status, extra = {}) => ({ id: owner + repo + issue, link: { owner, repo, issue }, status, ...extra });

const a = S('acme', 'web', 42, 'running'), b = S('acme', 'web', '42', 'stopped');
assert.equal(matchSession(card, [a, b]), a);
assert.equal(matchSession(card, [S('acme', 'web2', 42, 'running'), S('acme', 'web', 4, 'running')]), null);
for (const bad of [null, undefined, [], [{ id: 1, link: null }], [{ id: 1, link: 'x' }], [null], [S('acme', 'web', 43, 'running')]])
  assert.equal(matchSession(card, bad), null);
out('matchSession join and corners');

assert.deepEqual(cardChips(card, 'dev', S('a', 'b', 1, 'running')), ['running']);
assert.deepEqual(cardChips(card, 'dev', S('a', 'b', 1, 'waiting')), ['waiting']);
assert.deepEqual(cardChips(card, 'dev', S('a', 'b', 1, 'stopped')), ['stopped']);
assert.deepEqual(cardChips({ ...card, escalated: true }, 'dev', null), ['waiting']);
assert.deepEqual(cardChips(card, 'done', S('a', 'b', 1, 'running')), ['merged']);
assert.deepEqual(cardChips({ ...card, escalated: true }, 'done', null), ['merged']);
assert.deepEqual(cardChips(card, 'dev', S('a', 'b', 1, 'running', { resumed_fresh: true })), ['running', 'resumed fresh']);
assert.deepEqual(cardChips(card, 'dev', null), []);
assert.deepEqual(cardChips(card, 'done', null), ['merged']);
for (const st of ['done', 'failed', 'starting', undefined]) assert.deepEqual(cardChips(card, 'dev', S('a', 'b', 1, st)), []);
assert.deepEqual(cardChips(card, 'dev', S('a', 'b', 1, 'done', { resumed_fresh: true })), ['resumed fresh']);
out('cardChips');

assert.equal(formatCost(0.4213), '$0.42'); assert.equal(formatCost(0), '$0.00');
assert.equal(formatCost(null), ''); assert.equal(formatCost(undefined), '');
out('formatCost');

assert.equal(runHref(card), '#/run/acme/web/42');
assert.deepEqual({ ...parseRoute(runHref(card)).params }, { owner: 'acme', repo: 'web', n: 42 });
const odd = { owner: 'a b', repo: 'r', issue: 1 };
assert.equal(runHref(odd), '#/run/a%20b/r/1');
assert.equal(parseRoute(runHref(odd)).params.owner, 'a b');
out('runHref');

const cols = [{ key: 'dev', cards: [card, { owner: 'z', repo: 'q', issue: 1 }] }, { key: 'done', cards: [] }];
const f = filterColumns(cols, 'acme/web');
assert.deepEqual(f.map((c) => c.key), ['dev', 'done']);
assert.deepEqual(f[0].cards, [card]); assert.deepEqual(f[1].cards, []);
assert.deepEqual(filterColumns(cols, ''), cols);
assert.deepEqual(filterColumns(cols, 'gone/repo').map((c) => c.cards.length), [0, 0]);
assert.deepEqual(repoOptions(cols, ''), ['acme/web', 'z/q']);
assert.ok(repoOptions(cols, 'gone/repo').includes('gone/repo'));
out('filterColumns, repoOptions');

for (const t of ['', null, undefined]) assert.equal(cardTitle({ issue: 7, title: t }), '#7');
assert.equal(cardTitle({ issue: 7 }), '#7'); assert.equal(cardTitle({ issue: 7, title: 'Hi' }), 'Hi');
out('cardTitle');

const d = { columns: [] };
assert.equal(boardChanged(JSON.stringify(d), d), false);
assert.equal(boardChanged(JSON.stringify(d), { columns: [1] }), true);
out('boardChanged');
"""


def mkrun(base, name, ledger):
    import json

    d = os.path.join(base, "runs", name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "run.json"), "w") as f:
        json.dump(ledger, f)


def board_checks():
    import json
    import subprocess

    import ui_board

    js_path = os.path.join(STATIC, "board.js")
    assert os.path.isfile(js_path), "ui_static/board.js missing"
    s, r, body = req(port, "/static/board.js")
    assert s == 200 and r.getheader("Content-Type", "").startswith("text/javascript"), s
    assert body == read(js_path)
    ok("board.js served")

    data = os.path.join(tmp, "plugindata")
    old_env, old_fetch = os.environ.get("CLAUDE_PLUGIN_DATA"), srv.fetch_title
    os.environ["CLAUDE_PLUGIN_DATA"] = data
    srv.fetch_title = lambda o, r_, i: "A title"
    try:
        def board():
            s, _, b = req(port, "/board.json")
            assert s == 200
            return json.loads(b)

        def where(bd, issue):
            return [c["key"] for c in bd["columns"] if any(x["issue"] == issue for x in c["cards"])]

        bd = board()
        assert [c["key"] for c in bd["columns"]] == ui_board.STATIONS
        assert all(c["cards"] == [] for c in bd["columns"])
        ok("empty board has every column")

        led = {"issue": 42, "stations": ["researcher", "planner", "sdet", "dev"], "currentIndex": 1,
               "bounceCounts": {}, "status": "in_progress", "trace": [], "specialists": [],
               "classification": None, "context": {"pr": "https://github.com/acme/web/pull/9"}}
        mkrun(data, "acme-web-issue-42", led)
        bd = board()
        assert where(bd, 42) == ["planner"], where(bd, 42)
        c = next(x for c in bd["columns"] for x in c["cards"])
        assert (c["owner"], c["repo"], c["issue"]) == ("acme", "web", 42)
        led["currentIndex"] = 3
        mkrun(data, "acme-web-issue-42", led)
        assert where(board(), 42) == ["dev"]
        ok("card moves between columns without caching")

        led["status"] = "done"
        mkrun(data, "acme-web-issue-42", led)
        assert where(board(), 42) == ["done"]
        led["status"] = "escalated"
        mkrun(data, "acme-web-issue-42", led)
        bd = board()
        assert where(bd, 42) == ["dev"]
        assert next(x for c in bd["columns"] for x in c["cards"])["escalated"] is True
        ok("done and escalated placement")

        srv.fetch_title = lambda o, r_, i: ""
        mkrun(data, "acme-web-issue-43", dict(led, issue=43, status="in_progress"))
        bd = board()
        assert next(x for c in bd["columns"] for x in c["cards"] if x["issue"] == 43)["title"] == ""
        ok("empty title passes through")
    finally:
        srv.fetch_title = old_fetch
        if old_env is None:
            os.environ.pop("CLAUDE_PLUGIN_DATA", None)
        else:
            os.environ["CLAUDE_PLUGIN_DATA"] = old_env

    js = read(js_path).decode()
    css = read(os.path.join(STATIC, "app.css")).decode()
    app = read(os.path.join(STATIC, "app.js")).decode()
    specs = re.findall(r"""(?:^|\n)\s*import\b[^'"]*?from\s*['"]([^'"]+)['"]""", js)
    assert specs and set(specs) <= {"./vendor/preact.mjs", "./vendor/htm.mjs", "./app.js"}, specs
    pre = read(os.path.join(VENDOR, "preact.mjs")).decode()
    exports = re.search(r"export\s*\{([^}]*)\}", pre).group(1)
    names = {x.split(" as ")[-1].strip() for x in exports.split(",")}
    for m in re.finditer(r"import\s*\{([^}]*)\}\s*from\s*['\"]\./vendor/preact\.mjs", js):
        for n in m.group(1).split(","):
            assert n.strip().split(" as ")[0].strip() in names, n
    assert not re.search(r"https?://", js) and "console.log" not in js and "debugger" not in js
    ok("board.js imports and hygiene")

    assert re.search(r"poll\(\s*['\"]/board\.json['\"]\s*,\s*3000", js) and "fetch(" not in js
    assert re.search(r"ok\s*\)\s*return|!\s*\w+\.ok", js), "onResult must ignore ok:false"
    ok("board.js polls /board.json every 3s via poll")

    assert re.search(r"import\s*\{[^}]*\bBoard\b[^}]*\}\s*from\s*['\"]\./board\.js['\"]", app)
    assert "Runs will appear here." not in app
    ok("app.js renders Board")

    assert "display: grid" in css or "display:grid" in css
    assert re.search(r"minmax\(\s*250px|min-width\s*:\s*250px", css)
    assert re.search(r"scroll-snap-type\s*:\s*x", css) and "scroll-snap-align" in css
    assert re.search(r"overflow-x\s*:\s*(auto|scroll)", css)
    for m in re.finditer(r"(?<![\w-])(?:min-)?width\s*:\s*(\d+)px", css.replace("250px", "0px")):
        assert int(m.group(1)) <= 390, m.group(0)
    assert not re.search(r"@media[^{]*min-width", css)
    ok("board css")

    if not shutil.which("node"):
        print("note: node not found, skipping board logic checks")
        return
    env = dict(os.environ, APP_URL=pathlib.Path(os.path.join(STATIC, "app.js")).as_uri(),
               BOARD_URL=pathlib.Path(js_path).as_uri())
    p = subprocess.run(["node", "--input-type=module", "-e", BOARD_JS], env=env,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr[-1500:]
    for line in p.stdout.splitlines():
        if line.startswith("ok "):
            ok(line[3:])


LAUNCHER_JS = r"""
const L = await import(process.env.LAUNCHER_URL);
const fix = JSON.parse(process.env.LAUNCHER_FIX);
const assert = (await import('node:assert')).strict;
const out = (n) => console.log('ok ' + n);
const tick = () => new Promise((r) => setImmediate(r));
const { repoOptions, argIssue, validate, buildBody, outcome, sessionHref, loadLastRepo, saveLastRepo, makeSubmitter, Launcher } = L;
out('import without document/localStorage does not throw');
const plain = (x) => JSON.parse(JSON.stringify(x));

// repoOptions
const opts = repoOptions(fix.repos);
assert.equal(opts.length, 1); assert.equal(opts[0].value, 'o/r');
out('repoOptions from real /api/repos body');
for (const bad of [null, undefined, {}, { repos: 5 }, [], { repos: [{ name: 'x' }, { slug: 'a/b' }, null] }])
  assert.deepEqual(plain(repoOptions(bad)), [], JSON.stringify(bad));
out('repoOptions empty/malformed -> []');

// buildBody
assert.deepEqual(plain(buildBody({ repo: 'o/r', command: 'run-issue', args: ' 7 ' })), { repo: 'o/r', command: 'run-issue', args: '7' });
for (const a of ['#12', 'https://github.com/o/r/pull/12'])
  assert.deepEqual(plain(buildBody({ repo: 'o/r', command: 'pr-grind', args: a })), { repo: 'o/r', command: 'pr-grind', args: a, issue: 12 });
out('buildBody trims; pr-grind adds issue');

// argIssue
for (const a of ['7', '#7', 'https://github.com/o/r/issues/7']) assert.equal(argIssue('run-issue', a), 7, a);
for (const a of ['12', '#12', 'https://github.com/o/r/pull/12']) assert.equal(argIssue('pr-grind', a), 12, a);
out('argIssue accepted forms');
for (const a of ['0', '-1', '7.5', '7x', '', 'abc']) { assert.equal(argIssue('run-issue', a), null, a); assert.equal(argIssue('pr-grind', a), null, a); }
assert.equal(argIssue('pr-grind', 'https://github.com/o/r/issues/7'), null);
assert.equal(argIssue('run-issue', 'https://github.com/o/r/pull/7'), null);
out('argIssue boundary -> null');

// outcome / sessionHref
assert.deepEqual(plain(outcome(201, { id: 'x', link: { owner: 'o', repo: 'r', issue: 7 } })), { kind: 'open', href: '#/run/o/r/7' });
assert.deepEqual(plain(outcome(201, { id: 'x', link: null })), { kind: 'open', href: '#/sessions' });
out('outcome 201');
for (const l of [{ owner: 'o', repo: 'r', issue: 0 }, { owner: 'o', repo: 'r', issue: '7' }, { repo: 'r', issue: 7 }, { owner: 'o', issue: 7 }, null, undefined])
  assert.equal(sessionHref({ link: l }), '#/sessions', JSON.stringify(l));
assert.equal(sessionHref({ link: { owner: 'a b', repo: 'c/d', issue: 3 } }), '#/run/a%20b/c%2Fd/3');
out('sessionHref fallback and percent-encoding');
const o400 = outcome(400, fix.bad_repo);
assert.equal(o400.kind, 'repo'); assert.ok(o400.message.startsWith('not a git repository'), o400.message);
out('outcome 400 not a git repository (real body)');
const o409 = outcome(409, fix.dup);
assert.equal(o409.kind, 'duplicate'); assert.equal(o409.message, fix.dup.error); assert.equal(o409.href, '#/run/o/r/7');
assert.ok(!o409.href.includes('/api/'));
out('outcome 409 duplicate (real body) links to UI route');
for (const [st, b] of [[413, { error: 'too big' }], [502, { error: 'bad gw' }], [400, { error: 'other' }]]) {
  const r = outcome(st, b); assert.equal(r.kind, 'error'); assert.equal(r.message, b.error);
}
for (const [st, b] of [[502, null], [413, 'not json'], [500, {}], [400, undefined]]) {
  const r = outcome(st, b); assert.equal(r.kind, 'error'); assert.equal(r.message, `Request failed (HTTP ${st})`);
}
out('outcome other errors never throw');

// validate
for (const c of ['run-issue', 'pr-grind']) for (const a of ['', '   ', '\n']) {
  const e = validate({ repo: 'o/r', command: c, args: a }); assert.ok(e && e.args, `${c} ${JSON.stringify(a)}`);
}
assert.ok(validate({ repo: '', path: '', command: 'run-issue', args: '7' }).repo);
assert.ok(validate({ repo: '', path: '  ', manual: true, command: 'run-issue', args: '7' }).repo);
out('validate empty args/repo');

// storage
const bad = { getItem() { throw new Error('x'); }, setItem() { throw new Error('x'); } };
assert.equal(loadLastRepo(bad), null); assert.equal(loadLastRepo(undefined), null);
saveLastRepo(bad, 'o/r'); saveLastRepo(undefined, 'o/r');
const mem = {}; const good = { getItem: (k) => mem[k] ?? null, setItem: (k, v) => { mem[k] = v; } };
saveLastRepo(good, 'o/r'); assert.equal(loadLastRepo(good), 'o/r');
out('storage helpers tolerate failure, round-trip');

// submitter
let calls = 0, pend = [];
const fetchStub = () => { calls++; return new Promise((res) => pend.push(res)); };
const submit = makeSubmitter(fetchStub);
const b = { repo: 'o/r', command: 'run-issue', args: '7' };
const p1 = submit(b); const p2 = submit(b);
assert.equal(calls, 1);
pend.shift()({ status: 201, json: async () => ({ id: 'x', link: null }) });
await p1; await p2.catch(() => {}); await tick();
assert.equal(calls, 1);
const p3 = submit(b); assert.equal(calls, 2);
pend.shift()({ status: 201, json: async () => ({}) }); await p3;
out('submitter single-flight, re-allowed after settle');
const rej = makeSubmitter(() => Promise.reject(new Error('net')));
const rr = await rej(b);
assert.equal(rr.kind, 'error'); assert.match(rr.message, /could not reach the aiw server/);
out('network failure -> generic error, no throw');

// render tree
const base = { repos: opts, repo: 'o/r', manual: false, path: '', command: 'run-issue', args: '', pending: false, errors: {}, result: null };
const render = (st) => new Launcher({}).render({}, { ...base, ...st });
const nodes = [];
const walk = (n) => { if (n == null || typeof n === 'boolean') return; if (Array.isArray(n)) return n.forEach(walk);
  if (typeof n !== 'object') return; nodes.push(n); walk(n.props && n.props.children); };
const text = (n) => (n == null || typeof n === 'boolean') ? '' : Array.isArray(n) ? n.map(text).join('') : typeof n === 'object' ? text(n.props && n.props.children) : String(n);
const find = (t, root) => { nodes.length = 0; walk(root); return nodes.filter((n) => n.type === t); };
let tree = render({});
assert.equal(find('select', tree).length, 1);
const radios = find('input', tree).filter((i) => i.props.type === 'radio');
assert.deepEqual(radios.map((r) => r.props.value).sort(), ['dump', 'gh-issue', 'intake', 'pr-grind', 'prd', 'run-issue', 'worklog']);
const lab = (t) => find('label', render({ command: t })).map((l) => text(l)).join('|');
assert.match(lab('run-issue'), /issue/i); assert.match(lab('pr-grind'), /PR|pull/i);
assert.notEqual(lab('run-issue'), lab('pr-grind'));
out('render: repo select, seven command radios, command-specific args label');
const fs = find('fieldset', tree); assert.ok(fs.length >= 1); assert.ok(find('legend', fs[0]).length === 1);
tree = render({});
const labelFor = new Set(find('label', tree).map((l) => l.props.htmlFor ?? l.props['for']));
for (const c of [...find('input', tree).filter((i) => i.props.type !== 'radio' && i.props.type !== 'submit'), ...find('select', tree)])
  assert.ok(c.props.id && labelFor.has(c.props.id), 'control without label: ' + c.props.id);
out('render: a11y labels and fieldset/legend');
const noRepos = render({ repos: [], repo: '' });
assert.ok(find('input', noRepos).some((i) => i.props.type === 'text' && /path/i.test(String(i.props.id || i.props.name || ''))), 'manual path input shown');
out('render: empty repo list shows manual path input');
assert.ok(find('button', render({ pending: true })).some((bt) => bt.props.disabled));
assert.ok(!find('button', render({ pending: false })).some((bt) => bt.props.disabled));
out('render: pending disables submit');
const al = find('div', render({ errors: { args: 'enter an issue number' } })).concat(find('p', render({ errors: { args: 'enter an issue number' } })));
assert.ok(al.some((n) => n.props.role === 'alert' && /enter an issue number/.test(text(n))));
out('render: args error has role=alert');
let fetched = 0; globalThis.fetch = async () => { fetched++; return { status: 201, json: async () => ({}) }; };
const inst = new Launcher({}); inst.state = { ...base, args: '  ' };
let prevented = false;
await inst.onSubmit({ preventDefault() { prevented = true; } }); await tick();
assert.ok(prevented); assert.equal(fetched, 0);
out('submit with empty args does not fetch');
const t3 = render({ manual: true, path: '/tmp/x', errors: {}, result: { kind: 'repo', message: fix.bad_repo.error } });
const al3 = nodes.length && find('p', t3).concat(find('div', t3)).filter((n) => n.props.role === 'alert');
assert.ok(al3.some((n) => text(n).startsWith('not a git repository')));
const pathIn = find('input', t3).find((i) => /path/i.test(String(i.props.id)));
assert.ok(pathIn && pathIn.props['aria-invalid']);
assert.ok(al3.some((n) => n.props.id && n.props.id === pathIn.props['aria-describedby']));
out('render: repo error alert tied to path input');
const t4 = render({ result: { kind: 'duplicate', message: fix.dup.error, href: '#/run/o/r/7' } });
const al4 = find('div', t4).concat(find('p', t4)).filter((n) => n.props.role === 'alert');
assert.ok(al4.length);
assert.ok(find('a', al4[0]).some((a) => a.props.href === '#/run/o/r/7'));
out('render: duplicate alert links to run view');
"""


_fixture_dirs: list[str] = []


def _launcher_fixture():
    import json
    import subprocess

    data = tempfile.mkdtemp()
    repo = os.path.realpath(tempfile.mkdtemp())
    plain = os.path.realpath(tempfile.mkdtemp())
    _fixture_dirs.extend([data, repo, plain])
    os.environ["CLAUDE_PLUGIN_DATA"] = data
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    with open(os.path.join(data, "checkouts.json"), "w") as f:
        json.dump({"o/r": repo}, f)

    def call(method, path, obj=None):
        h = f"127.0.0.1:{port}"
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        c.putheader("Host", h)
        body = json.dumps(obj).encode() if obj is not None else None
        if body is not None:
            c.putheader("Origin", f"http://{h}")
            c.putheader("Content-Type", "application/json")
            c.putheader("Content-Length", str(len(body)))
        c.endheaders()
        if body is not None:
            c.send(body)
        r = c.getresponse()
        d = r.read()
        c.close()
        return r.status, r, json.loads(d)

    return repo, plain, call


def launcher_checks():
    import json
    import subprocess

    repo, plain, call = _launcher_fixture()
    import ui_sessions

    s, r, repos = call("GET", "/api/repos")
    assert s == 200 and repos["repos"][0]["slug"] == "o/r", (s, repos)
    s, r, bad = call("POST", "/api/sessions", {"repo": plain, "command": "run-issue", "args": "7"})
    assert s == 400 and bad["error"].startswith("not a git repository"), (s, bad)
    rec = ui_sessions.create("/run-issue 7", repo, link={"owner": "o", "repo": "r", "issue": 7})
    ui_sessions.update(rec["id"], status="running")
    s, r, dup = call("POST", "/api/sessions", {"repo": "o/r", "command": "run-issue", "args": "7"})
    assert s == 409 and dup["link"]["issue"] == 7 and dup["id"] == rec["id"], (s, dup)
    ok("real server: /api/repos, 400 non-git, 409 duplicate bodies captured")

    lp = os.path.join(STATIC, "launcher.js")
    assert os.path.exists(lp), "launcher.js missing"
    js = read(lp).decode()
    specs = re.findall(r"""(?:^|\n)\s*import\b[^'"]*?from\s*['"]([^'"]+)['"]""", js)
    assert specs and set(specs) <= {"./vendor/preact.mjs", "./vendor/htm.mjs"}, specs
    assert not re.search(r"console\.log|debugger|https?://", js)
    ok("launcher.js imports only vendored modules, no debug/absolute URLs")
    s, r, _ = req(port, "/static/launcher.js")
    assert s == 200 and r.getheader("Content-Type", "").startswith("text/javascript"), s
    ok("launcher.js served as text/javascript")

    css = read(os.path.join(STATIC, "app.css")).decode()
    for m in re.finditer(r"(?<![\w-])(?:min-)?width\s*:\s*(\d+)px", css):
        assert int(m.group(1)) <= 390, m.group(0)
    assert re.search(r"(?:input|select|button|textarea)[^{}]*\{[^}]*min-height\s*:\s*(?:4[4-9]|[5-9]\d)px", css), "form controls need min-height >= 44px"
    ok("css: no wide fixed widths, form controls >= 44px")

    if not shutil.which("node"):
        print("note: node not found, skipping launcher logic checks")
        return
    env = dict(os.environ, LAUNCHER_URL=pathlib.Path(lp).as_uri(),
               LAUNCHER_FIX=json.dumps({"repos": repos, "bad_repo": bad, "dup": dup}))
    p = subprocess.run(["node", "--input-type=module", "-e", LAUNCHER_JS], env=env,
                       capture_output=True, text=True, timeout=60)
    for line in p.stdout.splitlines():
        if line.startswith("ok "):
            ok(line[3:])
    assert p.returncode == 0, p.stderr[-1500:]


if LAUNCHER:
    try:
        launcher_checks()
    finally:
        srv.shutdown()
        for d in _fixture_dirs:
            shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{passed} checks passed")
    sys.exit(0)


LAUNCHER_ALL_JS = r"""
const L = await import(process.env.LAUNCHER_URL);
const fix = JSON.parse(process.env.LAUNCHER_FIX);
const assert = (await import('node:assert')).strict;
const out = (n) => console.log('ok ' + n);
const tick = () => new Promise((r) => setImmediate(r));
const plain = (x) => JSON.parse(JSON.stringify(x));
const { validate, buildBody, makeSubmitter, Launcher } = L;
const ALL = ['dump', 'gh-issue', 'intake', 'pr-grind', 'prd', 'run-issue', 'worklog'];
assert.equal(typeof L.validateCustom, 'function', 'validateCustom export');
assert.equal(typeof L.buildCustomBody, 'function', 'buildCustomBody export');

const base = { repos: [{ value: 'o/r', label: 'o/r' }], repo: 'o/r', manual: false, path: '', command: 'run-issue', args: '', text: '', pending: false, errors: {}, result: null };
const render = (st) => new Launcher({}).render({}, { ...base, ...st });
const nodes = [];
const walk = (n) => { if (n == null || typeof n === 'boolean') return; if (Array.isArray(n)) return n.forEach(walk);
  if (typeof n !== 'object') return; nodes.push(n); walk(n.props && n.props.children); };
const text = (n) => (n == null || typeof n === 'boolean') ? '' : Array.isArray(n) ? n.map(text).join('') : typeof n === 'object' ? text(n.props && n.props.children) : String(n);
const find = (t, root) => { nodes.length = 0; walk(root); return nodes.filter((n) => n.type === t); };
const alerts = (t) => find('p', t).concat(find('div', t)).filter((n) => n.props.role === 'alert');

let tree = render({});
const fs = find('fieldset', tree);
const radios = find('input', fs[0]).filter((i) => i.props.type === 'radio');
assert.deepEqual(radios.map((r) => r.props.value).sort(), ALL);
out('seven command radios');
const hint = (c) => find('label', render({ command: c })).map((l) => text(l)).join('|');
const hints = ALL.map(hint);
assert.ok(hints.every((h) => h.length > 0)); assert.equal(new Set(hints).size, 7, 'hints pairwise distinct');
assert.match(hint('run-issue'), /issue/i); assert.match(hint('pr-grind'), /PR|pull/i);
out('per-command hints distinct');

for (const c of ['prd', 'intake', 'dump', 'worklog', 'gh-issue']) {
  const b = plain(buildBody({ repo: 'o/r', command: c, args: '  some text ' }));
  assert.deepEqual(b, { repo: 'o/r', command: c, args: 'some text' }, c);
}
assert.deepEqual(plain(buildBody({ repo: 'o/r', command: 'pr-grind', args: '#12' })), { repo: 'o/r', command: 'pr-grind', args: '#12', issue: 12 });
out('buildBody for new commands has no issue key');
assert.equal(validate({ repo: 'o/r', command: 'worklog', args: '' }), null);
for (const c of ALL.filter((c) => c !== 'worklog')) for (const a of ['', '  ', '\n']) {
  const e = validate({ repo: 'o/r', command: c, args: a }); assert.ok(e && e.args, c + JSON.stringify(a));
}
out('worklog args optional, others required');

tree = render({});
const ta = find('textarea', tree);
assert.equal(ta.length, 1); assert.equal(ta[0].props.id, 'custom');
assert.ok(find('label', tree).some((l) => (l.props.htmlFor ?? l.props['for']) === 'custom'));
assert.ok(find('button', tree).some((b) => text(b).trim() === 'Run in selected repo'));
assert.match(text(tree), /skip-permissions/i);
out('custom box: textarea, label, button, skip-permissions note');

assert.deepEqual(plain(L.buildCustomBody({ repo: 'o/r', text: '/pr-fix-comments 42' })), { repo: 'o/r', text: '/pr-fix-comments 42' });
assert.equal(L.buildCustomBody({ repo: 'o/r', text: '  /pr-fix-comments 42\n' }).text, '/pr-fix-comments 42');
assert.equal(L.buildCustomBody({ repo: 'o/r', text: ' a\nb \n' }).text, 'a\nb');
out('buildCustomBody exact shape, outer trim only');
for (const t of ['', '   ', '\n\t', null, undefined]) {
  const e = L.validateCustom({ repo: 'o/r', text: t }); assert.ok(e && typeof e.text === 'string' && e.text, JSON.stringify(t));
}
assert.equal(L.validateCustom({ repo: 'o/r', text: '/x' }), null);
assert.ok(L.validateCustom({ repo: '', path: '', text: '/x' }).repo);
assert.ok(L.validateCustom({ repo: '', path: ' ', manual: true, text: '/x' }).repo);
out('validateCustom empty text / repo');

let fetched = 0; globalThis.fetch = async () => { fetched++; return { status: 201, json: async () => ({}) }; };
const inst = new Launcher({}); inst.state = { ...base, text: ' \n' };
let prevented = false;
await inst.onCustom({ preventDefault() { prevented = true; } }); await tick();
assert.ok(prevented); assert.equal(fetched, 0);
const et = render({ errors: { text: 'enter a command' } });
const ea = alerts(et).find((n) => /enter a command/.test(text(n)));
assert.ok(ea && ea.props.id === 'custom-error');
const ta2 = find('textarea', et)[0];
assert.ok(ta2.props['aria-invalid']); assert.equal(ta2.props['aria-describedby'], 'custom-error');
out('empty custom submit blocked, error tied to textarea');

// single flight across both forms
let calls = 0, pend = [];
globalThis.fetch = (...a) => { calls++; return new Promise((res) => pend.push(res)); };
const sf = new Launcher({}); sf.state = { ...base, args: '7', text: '/pr-fix-comments 42' };
sf.setState = (p) => { sf.state = { ...sf.state, ...(typeof p === 'function' ? p(sf.state) : p) }; };
const named = sf.onSubmit({ preventDefault() {} }); await tick();
await sf.onCustom({ preventDefault() {} }); await tick();
assert.equal(calls, 1, 'custom must not fetch while named pending');
assert.ok(sf.state.pending);
const btns = find('button', new Launcher({}).render({}, sf.state));
assert.ok(btns.length >= 2 && btns.every((b) => b.props.disabled));
pend.shift()({ status: 400, json: async () => ({ error: 'x' }) }); await named;
out('single-flight spans named and custom forms');

// custom outcomes
async function custom(status, body, text = '/run-issue 7') {
  globalThis.fetch = async () => ({ status, json: async () => body });
  const i = new Launcher({}); i.state = { ...base, text };
  i.setState = (p) => { i.state = { ...i.state, ...p }; };
  await i.onCustom({ preventDefault() {} }); await tick();
  return i.state;
}
let st = await custom(400, fix.bad_repo);
assert.equal(st.result.kind, 'repo'); assert.ok(alerts(render({ result: st.result })).some((n) => text(n).startsWith('not a git repository')));
st = await custom(409, fix.dup);
assert.equal(st.result.kind, 'duplicate');
assert.ok(find('a', alerts(render({ result: st.result }))[0]).some((a) => a.props.href === '#/run/o/r/7'));
st = await custom(502, null); assert.equal(st.result.kind, 'error');
globalThis.fetch = async () => { throw new Error('net'); };
const ni = new Launcher({}); ni.state = { ...base, text: '/x' }; ni.setState = (p) => { ni.state = { ...ni.state, ...p }; };
await ni.onCustom({ preventDefault() {} }); await tick();
assert.equal(ni.state.result.kind, 'error');
out('custom submit outcomes: repo, duplicate, generic, network');
"""


def launcher_all_checks():
    import json
    import subprocess

    repo, plain, fcall = _launcher_fixture()
    import ui_runner
    import ui_sessions

    def call(obj, method="POST", path="/api/sessions"):
        s, _r, d = fcall(method, path, obj)
        return s, d

    # SAFETY: never launch a real claude
    captured = []
    real_start = ui_runner.start

    def stub(command_text, cwd, link=None):
        captured.append((command_text, cwd))
        return ui_sessions.create(command_text, cwd, link=link)

    ui_runner.start = stub
    try:
        s, repos = call(None, "GET", "/api/repos")
        assert s == 200, s
        s, bad = call({"repo": plain, "text": "/pr-fix-comments 42"})
        assert s == 400 and bad["error"].startswith("not a git repository"), (s, bad)
        assert not captured
        s, b = call({"repo": "o/r", "text": "/pr-fix-comments 42"})
        assert s == 201 and captured[-1] == ("/pr-fix-comments 42", repo), (s, b, captured)
        s, b = call({"repo": "o/r", "command": "prd", "args": "x"})
        assert s == 201 and captured[-1][0] == "/prd x", (s, b, captured)
        ok("real server (runner stubbed): custom text verbatim, named prd -> '/prd x'")
        n = len(captured)
        s, b = call({"repo": "o/r", "text": "/no-such-command 1"})
        assert s == 201 and captured[-1][0] == "/no-such-command 1", (s, b)
        for t in ("  \n", "--help"):
            s, b = call({"repo": "o/r", "text": t})
            assert s == 400, (t, s, b)
        assert len(captured) == n + 1
        ok("unknown slash command accepted; blank and leading-dash rejected")

        rec = ui_sessions.create("/pr-fix-comments 42", repo)
        ui_sessions.update(rec["id"], status="waiting", pending_question={"text": "q?"})
        named = ui_sessions.create("/prd x", repo)
        ui_sessions.update(named["id"], status="waiting", pending_question={"text": "q?"})
        s, lst = call(None, "GET")
        assert s == 200, s
        items = {i["id"]: i for i in lst["sessions"]}
        assert items[rec["id"]]["waiting"] is True and items[rec["id"]]["command"] == "/pr-fix-comments 42", items[rec["id"]]
        assert items[rec["id"]]["waiting"] == items[named["id"]]["waiting"]
        ok("custom-text session surfaced waiting exactly like a named one")
        live = ui_sessions.create("/run-issue 7", repo, link={"owner": "o", "repo": "r", "issue": 7})
        ui_sessions.update(live["id"], status="running")
        s, dup = call({"repo": "o/r", "command": "run-issue", "args": "7"})
        assert s == 409 and dup["link"]["issue"] == 7, (s, dup)
        s, lst = call(None, "GET")
        sj = json.dumps(lst)
        assert rec["id"] in sj
    finally:
        ui_runner.start = real_start

    lp = os.path.join(STATIC, "launcher.js")
    assert os.path.exists(lp), "launcher.js missing"
    js = read(lp).decode()
    for name in ("run-issue", "pr-grind", "prd", "intake", "dump", "worklog", "gh-issue"):
        assert name in js, name
    specs = re.findall(r"""(?:^|\n)\s*import\b[^'"]*?from\s*['"]([^'"]+)['"]""", js)
    assert specs and set(specs) <= {"./vendor/preact.mjs", "./vendor/htm.mjs"}, specs
    assert not re.search(r"console\.log|debugger|https?://", js)
    s, r, _ = req(port, "/static/launcher.js")
    assert s == 200 and r.getheader("Content-Type", "").startswith("text/javascript"), s
    ok("launcher.js served, names all seven commands, hygiene")

    css = read(os.path.join(STATIC, "app.css")).decode()
    assert re.search(r"textarea[^{}]*\{[^}]*min-height\s*:\s*(?:4[4-9]|[5-9]\d)px", css), "textarea min-height >= 44px"
    assert re.search(r"textarea[^{}]*\{[^}]*font-family\s*:[^;}]*monospace", css), "textarea monospace"
    for m in re.finditer(r"(?<![\w-])(?:min-)?width\s*:\s*(\d+)px", css):
        assert int(m.group(1)) <= 390, m.group(0)
    ok("css: textarea >= 44px, monospace")

    if not shutil.which("node"):
        print("note: node not found, skipping launcher logic checks")
        return
    appjs = pathlib.Path(os.path.join(STATIC, "app.js")).as_uri()
    chk = (
        "const A=await import(process.env.APP_URL);"
        "const d=[{id:process.env.SID,status:'waiting'}];const w=A.waitingInfo(d);"
        "if(w.count<1)throw new Error('no waiting');"
        "const b=A.headerBadge(false,d);"
        "if(b.href!=='#/answer/'+encodeURIComponent(w.firstId))throw new Error(b.href);"
        "if(b.href!=='#/answer/'+process.env.SID)throw new Error('id '+b.href);"
        "console.log('ok custom waiting session routes to #/answer/<id>');"
    )
    p = subprocess.run(["node", "--input-type=module", "-e", chk],
                       env=dict(os.environ, APP_URL=appjs, SID=rec["id"]),
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr[-1500:]
    ok("custom waiting session routes to #/answer/<id>")

    env = dict(os.environ, LAUNCHER_URL=pathlib.Path(lp).as_uri(),
               LAUNCHER_FIX=json.dumps({"bad_repo": bad, "dup": dup}))
    p = subprocess.run(["node", "--input-type=module", "-e", LAUNCHER_ALL_JS], env=env,
                       capture_output=True, text=True, timeout=60)
    for line in p.stdout.splitlines():
        if line.startswith("ok "):
            ok(line[3:])
    assert p.returncode == 0, p.stderr[-1500:]


if LAUNCHER_ALL:
    try:
        launcher_all_checks()
    finally:
        srv.shutdown()
        for d in _fixture_dirs:
            shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{passed} checks passed")
    sys.exit(0)


if BOARD:
    try:
        board_checks()
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{passed} checks passed")
    sys.exit(0)


if SHELL:
    try:
        shell_checks()
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{passed} checks passed")
    sys.exit(0)

try:
    # real tree
    s, r, body = req(port, "/")
    assert s == 200, s
    assert r.getheader("Content-Type", "").startswith("text/html")
    assert body == read(os.path.join(STATIC, "index.html"))
    assert int(r.getheader("Content-Length")) == len(body)
    ok("GET / serves index.html")

    for name in ("preact", "htm"):
        s, r, body = req(port, f"/static/vendor/{name}.mjs")
        assert s == 200, s
        assert r.getheader("Content-Type", "").startswith("text/javascript")
        assert body == read(os.path.join(VENDOR, f"{name}.mjs"))
        assert int(r.getheader("Content-Length")) == len(body)
        ok(f"{name}.mjs served as text/javascript")
    assert req(port, "/static/vendor/htm.mjs?v=1")[0] == 200
    ok("query string ignored")

    # 404s on the real tree
    s, _, body = req(port, "/static/nope.js")
    assert s == 404 and b"not found" in body
    ok("missing 404")
    for p in ("/static/vendor", "/static/vendor/", "/static/", "/static"):
        s, _, body = req(port, p)
        assert s == 404 and b"preact.mjs" not in body, p
    ok("directories 404, no listing")
    for p in (
        "/static/../route.py", "/static/../../etc/passwd", "/static/%2e%2e/route.py",
        "/static/%2E%2E/route.py", "/static/..%2froute.py", "/static/%252e%252e/route.py",
        "/static//etc/passwd", "/static/vendor/../../ui_server.py",
    ):
        s, _, body = req(port, p)
        assert s == 404 and b"def " not in body and b"root:" not in body, (p, s)
    ok("traversal variants 404")
    assert req(port, "/static/a%00.js")[0] == 404
    ok("NUL byte 404")

    # guard
    for p, kw in (("/", {"host": "evil.example"}), ("/", {"host": ""}),
                  ("/static/vendor/preact.mjs", {"origin": "http://evil.example"})):
        s, r, _ = req(port, p, **kw)
        assert s == 403, (p, kw, s)
        assert not any(k.lower().startswith("access-control-") for k, _ in r.getheaders())
    s, r, _ = req(port, "/")
    assert not any(k.lower().startswith("access-control-") for k, _ in r.getheaders())
    ok("guard applies, no CORS")

    # temp root: types, symlink, sibling prefix
    root = os.path.join(tmp, "ui_static")
    os.makedirs(root)
    for n in ("a.js", "a.css", "a.html", "a.mjs"):
        with open(os.path.join(root, n), "w") as f:
            f.write("x")
    with open(os.path.join(tmp, "secret.txt"), "w") as f:
        f.write("SECRET")
    os.symlink(os.path.join(tmp, "secret.txt"), os.path.join(root, "link"))
    os.makedirs(os.path.join(tmp, "ui_static_evil"))
    with open(os.path.join(tmp, "ui_static_evil", "x.js"), "w") as f:
        f.write("EVIL")
    ui_server.STATIC_DIR = root
    try:
        for n, t in (("a.js", "text/javascript"), ("a.css", "text/css"), ("a.html", "text/html")):
            s, r, _ = req(port, f"/static/{n}")
            assert s == 200 and r.getheader("Content-Type", "").startswith(t), (n, s)
        ok("js/css/html content types")
        mimetypes.add_type("application/x-bogus", ".mjs")
        s, r, _ = req(port, "/static/a.mjs")
        assert s == 200 and r.getheader("Content-Type", "").startswith("text/javascript")
        ok(".mjs forced to text/javascript")
        s, _, body = req(port, "/static/link")
        assert s == 404 and b"SECRET" not in body
        ok("escaping symlink 404")
        s, _, body = req(port, "/static/../ui_static_evil/x.js")
        assert s == 404 and b"EVIL" not in body
        ok("sibling-prefix escape 404")
    finally:
        ui_server.STATIC_DIR = real_static

    # vendoring
    for name, lic in (("preact", "MIT"), ("htm", "Apache-2.0")):
        src = read(os.path.join(VENDOR, f"{name}.mjs")).decode()
        assert src.startswith(("/*", "//")), name
        head = src[:600]
        assert name in head and lic in head and re.search(r"\d+\.\d+\.\d+", head), name
        assert "sourceMappingURL" not in src, name
    pre = read(os.path.join(VENDOR, "preact.mjs")).decode()
    assert re.search(r"export\s*\{", pre) and all(re.search(rf"\bas\s+{n}\b", pre) or re.search(rf"export\s*\{{[^}}]*\b{n}\b", pre) for n in ("h", "render", "Component"))
    htm = read(os.path.join(VENDOR, "htm.mjs")).decode()
    assert "export default" in htm or re.search(r"export\s*\{", htm)
    ok("vendored headers and exports")

    # hygiene
    assert not os.path.exists(os.path.join(VENDOR, "package.json"))
    import subprocess
    g = subprocess.run(["git", "-C", REPO, "ls-files"], capture_output=True, text=True)
    if g.returncode:
        print("note: not a git checkout, skipping tracked-file hygiene check")
    else:
        for f in g.stdout.splitlines():
            parts = f.split("/")
            assert "node_modules" not in parts and parts[-1] != "package.json", f
    ok("no package.json / node_modules")
finally:
    srv.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)

print(f"{passed} checks passed")
