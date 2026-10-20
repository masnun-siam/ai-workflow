#!/usr/bin/env python3
"""Navigation and the shared board shell (task 40).
`python3 run-engine/test_ui_boards_static.py` — exit 0 = green. Node-driven, no server or network.
"""

import os
import re
import pathlib
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "ui_static")
passed = 0


def ok(label):
    global passed
    passed += 1
    print(f"  ok  {label}")


def read(name):
    with open(os.path.join(STATIC, name)) as f:
        return f.read()


def run_node(js):
    if not shutil.which("node"):
        print("note: node not found, skipping")
        return
    env = dict(os.environ, STATIC_URL=pathlib.Path(STATIC).as_uri() + "/")
    p = subprocess.run(["node", "--input-type=module", "-e", js], env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr[-2500:]
    for line in p.stdout.splitlines():
        if line.startswith("ok "):
            ok(line[3:])


PRE = r"""
const assert = (await import('node:assert')).strict;
const out = (n) => console.log('ok ' + n);
const tick = () => new Promise((r) => setImmediate(r));
const nodes = [];
const walk = (n) => { if (n == null || typeof n === 'boolean') return; if (Array.isArray(n)) return n.forEach(walk);
  if (typeof n !== 'object') return; nodes.push(n); walk(n.props && n.props.children); };
const text = (n) => (n == null || typeof n === 'boolean') ? '' : Array.isArray(n) ? n.map(text).join('') : typeof n === 'object' ? text(n.props && n.props.children) : String(n);
const find = (t, root) => { nodes.length = 0; walk(root); return nodes.filter((n) => n.type === t); };
const byClass = (c, root) => { nodes.length = 0; walk(root); return nodes.filter((n) => typeof n.props?.class === 'string' && n.props.class.split(' ').includes(c)); };
const U = (f) => new URL(f, process.env.STATIC_URL).href;
"""
JS = (
    PRE
    + r"""
const A = await import(U('app.js'));
const B = await import(U('boardshell.js'));
const nm = (h) => A.parseRoute(h).name;
assert.equal(nm('#/'), 'planning'); assert.equal(nm(''), 'planning'); assert.equal(nm('#/planning'), 'planning');
assert.equal(nm('#/delivery'), 'delivery'); assert.equal(nm('#/sessions'), 'sessions');
for (const h of ['#/run/o/r/1', '#/board', '#/flow', '#/planning/x']) assert.equal(nm(h), 'notfound', h);
out('routes: # is planning, planning/delivery/sessions parse, removed pages are not found');
assert.deepEqual(A.NAV.map((n) => n[2]), ['Planning', 'Delivery', 'Sessions']);
const app = new A.App({});
const tree = app.render({}, { ...app.state, route: A.parseRoute('#/planning'), sessions: [] });
const links = find('a', tree).map((a) => [a.props.href, text(a)]);
for (const [href, label] of [['#/planning', 'Planning'], ['#/delivery', 'Delivery'], ['#/sessions', 'Sessions'], ['#/new', 'New run'], ['#/settings', '']])
  assert.ok(links.some(([h, t]) => h === href && (!label || t.includes(label.split(' ')[0]))), href);
assert.equal(find('a', tree).find((a) => a.props.href === '#/planning').props['aria-current'], 'page');
out('nav shows Planning, Delivery, Sessions, New and Settings; current page marked');

assert.equal(B.boardView({ repo: '', data: null, error: false }), 'pick');
assert.equal(B.boardView({ repo: 'o/r', data: null, error: false }), 'skeleton');
assert.equal(B.boardView({ repo: 'o/r', data: null, error: true }), 'unavailable');
assert.equal(B.boardView({ repo: 'o/r', data: {}, error: true }), 'data', 'keeps last data');
assert.equal(B.boardUrl('/api/planning', 'o/r'), '/api/planning?repo=o%2Fr');
out('boardView and url');

const mem = new Map();
globalThis.localStorage = { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v) };
const props = { title: 'Planning', path: '/api/planning', render: (d) => `DATA:${d.repo}` };
const R = (st, p = props) => { const s = new B.BoardShell(p); return s.render(p, { ...s.state, ...st }); };
let t = R({});
assert.match(text(t), /Pick a repo/); assert.equal(find(R.constructor && (await import(U('repopicker.js'))).RepoPicker, t).length, 1, 'repo picker');
assert.ok(!text(t).includes('DATA'));
t = R({ repo: 'o/r' });
assert.equal(byClass('board-skeleton', t).length, 1, 'skeleton on first fetch');
t = R({ repo: 'o/r', error: true }); assert.match(text(t), /unavailable/);
t = R({ repo: 'o/r', data: { repo: 'o/r', stale: false, fetched_at: 1792510132 } });
assert.match(text(t), /DATA:o\/r/); assert.equal(byClass('stale-banner', t).length, 0);
t = R({ repo: 'o/r', data: { repo: 'o/r', stale: true, fetched_at: '2026-10-20T09:05:00' } });
assert.equal(byClass('stale-banner', t).length, 1); assert.match(text(byClass('stale-banner', t)), /Showing the board from \d\d:\d\d/); assert.match(text(t), /DATA:o\/r/);
t = R({ repo: 'o/r', data: { repo: 'o/r', stale: true } }); assert.match(text(byClass('stale-banner', t)), /Loading from GitHub/);
assert.doesNotMatch(text(t), /DATA:/, 'no board before the first fetch: empty issues would offer wrong actions'); assert.equal(byClass('board-skeleton', t).length, 1);
assert.equal(find('button', byClass('stale-banner', t)).length, 0, 'no Refresh before the first fetch');
t = R({ repo: 'o/r', data: { repo: 'o/r', stale: true, fetched_at: 1792510132, error: 'HTTP 502' } });
assert.match(text(byClass('stale-banner', t)), /Could not refresh from GitHub: HTTP 502\. Showing the board from \d\d:\d\d/);
assert.equal(text(find('button', byClass('stale-banner', t))[0]), 'Refresh');
t = R({ repo: 'o/r', data: { repo: 'o/r', stale: true, fetched_at: 1792510132, error: 'rate limited', retry_at: 1792510732 } });
assert.match(text(byClass('stale-banner', t)), /rate limit reached, retrying at \d\d:\d\d/);
assert.equal(find('button', byClass('stale-banner', t)).length, 0, 'no Refresh while rate limited');
assert.equal(B.boardUrl('/api/planning', 'o/r', true), '/api/planning?repo=o%2Fr&refresh=1');
out('shell: pick-a-repo, skeleton, unavailable, stale banner with fetched_at, data');

// persisted repo + keep-last-data poll
mem.set('aiw.repo', 'o/r');
let timers = [], calls = [], mode = 'ok', docLs = {};
globalThis.document = { hidden: false, addEventListener() {}, removeEventListener() {} };
globalThis.setTimeout = (fn, ms) => { timers.push({ fn, ms }); return timers.length; };
globalThis.clearTimeout = () => {};
globalThis.fetch = async (u) => {
  calls.push(u);
  if (u.startsWith('/api/repos')) return { ok: true, json: async () => ({ repos: [{ slug: 'o/r', name: 'r', path: '/p/r' }] }) };
  if (mode === 'fail') throw new Error('net');
  return { ok: true, json: async () => ({ repo: 'o/r', stale: false, prds: [], n: calls.length }) };
};
const sh = new B.BoardShell(props);
assert.equal(sh.state.repo, 'o/r', 'repo persisted');
sh.setState = (p, cb) => { sh.state = { ...sh.state, ...(typeof p === 'function' ? p(sh.state) : p) }; cb && cb(); };
sh.componentDidMount(); await tick(); await tick(); await tick();
assert.ok(calls.includes('/api/planning?repo=o%2Fr')); assert.ok(sh.state.data && sh.state.data.repo === 'o/r');
assert.equal(sh.state.repos[0].value, 'o/r');
assert.equal(timers.at(-1).ms, B.BOARD_POLL_MS);
mode = 'fail'; timers.at(-1).fn(); await tick(); await tick(); await tick();
assert.ok(sh.state.data, 'last data kept after a failed poll'); assert.equal(sh.state.error, false);
sh.pick({ repo: 'o/other' }); assert.equal(mem.get('aiw.repo'), 'o/other'); assert.equal(sh.state.data, null, 'switching repos clears data');
sh.componentWillUnmount();
out('shell: persisted repo, 15s poll, keeps last data on failure, picking saves and resets');
{
  const F = await import(U('fmt.js'));
  const st = (o) => ({ getItem: (k) => o[k] ?? null, setItem: (k, v) => { o[k] = v; } });
  assert.equal(F.hashRepo('#/delivery?repo=o/r'), 'o/r'); assert.equal(F.hashRepo('#/delivery'), '');
  assert.equal(F.currentRepo(st({ 'aiw.repo': 'a/b' }), '#/planning?repo=o/r'), 'o/r', 'the URL wins');
  assert.equal(F.currentRepo(st({ 'aiw.repo': 'a/b' }), '#/planning'), 'a/b');
  assert.equal(F.currentRepo(st({ 'aiw.boardRepo': 'c/d' }), ''), 'c/d', 'old board key still read');
  assert.equal(F.currentRepo(st({ 'aiw.lastRepo': '/abs/path' }), ''), '', 'a path is not a repo');
  assert.equal(F.withRepo('#/sessions', 'o/r'), '#/sessions?repo=o/r');
  assert.equal(F.withRepo('#/sessions?repo=o/r&x=1', ''), '#/sessions?x=1');
  const A = await import(U('app.js'));
  assert.deepEqual(A.parseRoute('#/delivery?repo=o/r'), { name: 'delivery', params: {}, repo: 'o/r' });
  assert.deepEqual(A.parseRoute('#/delivery'), { name: 'delivery', params: {} });
  out('repo: ?repo= in the URL wins over the remembered pick, shared by every page');
}
"""
)


app = read("app.js")
css = read("app.css")
shell = read("boardshell.js")
assert re.search(r"from '\./planning\.js'", app) and re.search(r"from '\./delivery\.js'", app)
specs = re.findall(r"""(?:^|\n)\s*import\b[^'"]*?from\s*['"]([^'"]+)['"]""", shell)
assert set(specs) <= {"./vendor/preact.mjs", "./vendor/htm.mjs", "./app.js", "./fmt.js", "./repopicker.js"}, specs
assert not re.search(r"https?://", shell) and "innerHTML" not in shell and "console.log" not in shell
ok("boardshell.js imports only vendored/local modules")
blocks = re.findall(r"([^{}]+)\{([^}]*)\}", css)
assert any(".cols" in s and re.search(r"overflow-x\s*:\s*auto", b) for s, b in blocks), (
    "columns scroll inside the board"
)
assert any(".bcol" in s and re.search(r"min-width\s*:\s*\d+px", b) for s, b in blocks)
for m in re.finditer(r"(?<![\w(-])(?:min-)?width\s*:\s*(\d+)px", css):
    assert int(m.group(1)) <= 390, m.group(0)
ok("css: columns scroll horizontally inside the board, no wide fixed widths")

run_node(JS)
print(f"{passed} checks passed")
