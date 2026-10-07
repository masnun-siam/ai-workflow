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
HISTORY = sys.argv[1:3] == ["--view", "history"]

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
    assert set(specs) <= {"./vendor/preact.mjs", "./vendor/htm.mjs", "./history.js"}, specs
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


if SHELL:
    try:
        shell_checks()
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{passed} checks passed")
    sys.exit(0)

HISTORY_JS = r"""
const H = await import(process.env.HISTORY_URL);
const { h } = await import(process.env.PREACT_URL);
const assert = (await import('node:assert')).strict;
const out = (n) => console.log('ok ' + n);
const tick = () => new Promise((r) => setImmediate(r));
out('import without document does not throw');

const { rowOutcome, rowAction, transcriptHref, filterSessions, fmtCost, fmtTime, resumeSession, History } = H;
const S = (o) => ({ id: 's1', command: 'cmd', repo: 'r', outcome: 'done', cost: 0.5,
  started_at: '2026-01-02T03:04:05Z', ended_at: '2026-01-02T04:04:05Z', link: null, ...o });

assert.equal(rowOutcome(S({ outcome: 'waiting' })), 'waiting');
assert.equal(rowOutcome(S({ outcome: 'running', waiting: true })), 'waiting');
for (const o of ['starting', 'running', 'done', 'failed', 'stopped']) assert.equal(rowOutcome(S({ outcome: o })), o);
out('rowOutcome');

const f = rowAction(S({ outcome: 'failed', resume_command: 'cd x && claude --resume y' }));
assert.equal(f.kind, 'terminal'); assert.equal(f.label, 'Continue in terminal');
assert.equal(f.command, 'cd x && claude --resume y');
const w = rowAction(S({ id: 'a b', outcome: 'waiting' }));
assert.equal(w.label, 'Answer'); assert.equal(w.href, '#/answer/a%20b');
const st = rowAction(S({ id: 'a/b', outcome: 'stopped' }));
assert.equal(st.label, 'Resume'); assert.equal(st.method, 'POST'); assert.equal(st.url ?? st.href, '/api/sessions/a%2Fb/resume');
const link = { owner: 'o', repo: 'r', issue: 7 };
for (const o of ['running', 'starting']) {
  const a = rowAction(S({ outcome: o, link }));
  assert.equal(a.label, 'Open'); assert.equal(a.href, '#/run/o/r/7');
}
assert.equal(rowAction(S({ outcome: 'done' })), null);
assert.equal(rowAction(S({ outcome: 'weird' })), null);
assert.equal(rowAction(S({ outcome: undefined })), null);
out('rowAction mapping');

assert.equal(transcriptHref(S({ link })), '#/run/o/r/7');
assert.equal(transcriptHref(S({ link: { owner: 'a b', repo: 'c/d', issue: 1 } })), '#/run/a%20b/c%2Fd/1');
for (const l of [null, undefined, { owner: 'o', repo: 'r', issue: 0 }, { owner: 'o', repo: 'r', issue: 1.5 },
  { owner: 'o', repo: 'r', issue: '3' }, { owner: 'o', repo: 'r' }]) {
  assert.equal(transcriptHref(S({ id: 'x y', link: l })), '/api/sessions/x%20y/stream');
}
out('transcriptHref');

const L = [S({ id: '1', outcome: 'failed' }), S({ id: '2', outcome: 'done' }), S({ id: '3', outcome: 'failed' }),
  S({ id: '4', outcome: 'running', waiting: true })];
assert.deepEqual(filterSessions(L, 'failed').map((s) => s.id), ['1', '3']);
assert.deepEqual(filterSessions(L, 'all').map((s) => s.id), ['1', '2', '3', '4']);
assert.deepEqual(filterSessions(L, 'waiting').map((s) => s.id), ['4']);
assert.deepEqual(filterSessions(L, 'stopped'), []);
out('filterSessions');

const resp = (ok, status, body) => ({ ok, status, json: async () => { if (body instanceof Error) throw body; return body; } });
let calls = [];
globalThis.fetch = async (u, o) => { calls.push([u, o]); return resp(true, 200, {}); };
assert.deepEqual({ ...(await resumeSession('a b')) }, { ok: true });
assert.equal(calls[0][0], '/api/sessions/a%20b/resume'); assert.equal(calls[0][1].method, 'POST');
globalThis.fetch = async () => resp(false, 409, { error: 'nope' });
let r = await resumeSession('x'); assert.equal(r.ok, false); assert.equal(r.error, 'nope');
globalThis.fetch = async () => resp(false, 405, new SyntaxError('bad'));
r = await resumeSession('x'); assert.equal(r.ok, false); assert.equal(r.error, 'HTTP 405');
globalThis.fetch = async () => { throw new Error('net'); };
r = await resumeSession('x'); assert.equal(r.ok, false); assert.ok(typeof r.error === 'string' && r.error.length > 0);
out('resumeSession ok, server error, HTTP status, network failure');

assert.equal(fmtCost(0.1234), '$0.12'); assert.equal(fmtCost(0), '$0.00');
assert.match(fmtTime('2026-01-02T03:04:05Z'), /2026|26/);
out('fmtCost/fmtTime');

// mini renderer: vnode -> html string, plus element lookup
const esc = (t) => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const kids = (c) => (c == null ? [] : Array.isArray(c) ? c.flat(Infinity) : [c]);
const insts = new Map();
const expand = (v, key = 'root') => {
  if (v == null || typeof v === 'boolean') return null;
  if (typeof v === 'string' || typeof v === 'number') return v;
  if (typeof v.type === 'function') {
    const props = { ...v.props };
    let out;
    if (v.type.prototype && v.type.prototype.render) {
      let inst = insts.get(key);
      if (!inst) { inst = new v.type(props); insts.set(key, inst); inst.state = inst.state || {};
        inst.setState = (p) => { inst.state = { ...inst.state, ...(typeof p === 'function' ? p(inst.state, inst.props) : p) }; }; }
      inst.props = props;
      out = inst.render(props, inst.state);
    } else out = v.type(props);
    return expand(out, key + '/c');
  }
  return { tag: v.type, props: v.props || {}, kids: kids(v.props && v.props.children).map((c, i) => expand(c, key + '/' + i)).filter((c) => c != null) };
};
const ser = (n) => {
  if (n == null) return '';
  if (typeof n !== 'object') return esc(n);
  const a = Object.entries(n.props).filter(([k, v]) => k !== 'children' && typeof v !== 'function' && v != null && v !== false)
    .map(([k, v]) => ` ${k}="${esc(v === true ? '' : v)}"`).join('');
  return `<${n.tag}${a}>${n.kids.map(ser).join('')}</${n.tag}>`;
};
const find = (n, pred, acc = []) => { if (n && typeof n === 'object') { if (pred(n)) acc.push(n); n.kids.forEach((k) => find(k, pred, acc)); } return acc; };
const render = (sessions) => expand(h(History, { sessions }));
const html = (sessions) => ser(render(sessions));
const BAD = /\bnull\b|undefined|NaN/;

let t = html([]);
assert.match(t, /No sessions yet/); assert.ok(!/<table/.test(t));
t = html(null);
assert.ok(!/No sessions yet/.test(t) && /[Ll]oading/.test(t) && !/<table/.test(t));
out('empty and loading states');

const longCmd = 'x'.repeat(2000);
t = html([S({ outcome: 'running', cost: null, ended_at: null, command: null, repo: null, link: null }),
  S({ id: 'q', command: longCmd }), S({ id: 'z', outcome: 'mystery' }), S({ id: 'bd', started_at: 'not-a-date' })]);
assert.ok(!BAD.test(t.replace(/[a-z]+="[^"]*"/g, '')), 'no null/undefined/NaN text');
assert.ok(t.includes('—'), 'em dash');
assert.match(t, /unknown/);
assert.ok(t.includes('not-a-date'));
assert.ok(t.includes(`title="${longCmd}"`), 'full command in title');
assert.ok(t.includes('/api/sessions/s1/stream'), 'missing link falls back to stream');
out('null fields, unknown outcome, invalid date, long command title');

t = html([S({ outcome: 'failed' })]);
assert.match(t, /Continue in terminal/); assert.ok(!/<code><\/code>/.test(t) && !/<code>\s*<\/code>/.test(t));
t = html([S({ outcome: 'failed', resume_command: 'run me' })]);
assert.match(t, /<code[^>]*>run me<\/code>/);
out('failed row with and without resume_command');

t = html([S({ outcome: 'done', command: '<img src=x onerror=alert(1)>' })]);
assert.ok(!t.includes('<img') && t.includes('&lt;img'));
out('html in command is escaped text');

// filter via select handler, no-match message
let tree = render(L);
const sel = find(tree, (n) => n.tag === 'select')[0];
const onch = sel.props.onChange || sel.props.onInput || sel.props.onchange;
assert.ok(onch, 'select has change handler');
onch({ target: { value: 'stopped' } });
tree = render(L); t = ser(tree);
assert.ok(!/<table/.test(t) && /[Nn]o .*match|[Nn]o sessions (match|with)/.test(t) && !/No sessions yet/.test(t));
onch({ target: { value: 'failed' } });
assert.equal(find(render(L), (n) => n.tag === 'tr').length, 3, 'header + 2 failed rows');
out('filter select narrows rows; no-match message');

// resume: double click, busy survives re-render, 405 alert
insts.clear();
const SL = [S({ id: 'r1', outcome: 'stopped' })];
calls = []; const pend = [];
globalThis.fetch = (u, o) => { calls.push(u); return new Promise((res) => pend.push(res)); };
const btn = () => find(render(SL), (n) => n.tag === 'button')[0];
const click = (b) => (b.props.onClick || b.props.onclick)({ preventDefault() {} });
click(btn()); await tick();
assert.equal(calls.length, 1);
assert.ok(btn().props.disabled, 'disabled while busy');
click(btn()); await tick();
assert.equal(calls.length, 1, 'second click sends no request');
assert.ok(btn().props.disabled, 'busy survives re-render with new props');
pend.shift()(resp(false, 405, new SyntaxError('x'))); await tick(); await tick();
t = ser(render(SL));
assert.match(t, /role="alert"[^>]*>[^<]*HTTP 405/);
assert.ok(!btn().props.disabled, 'enabled again after failure');
out('resume double-click guard, busy persists, 405 shown in alert');

insts.clear(); calls = [];
globalThis.fetch = async () => { throw new Error('net down'); };
click(btn()); await tick(); await tick(); await tick();
assert.match(ser(render(SL)), /role="alert"/);
out('network failure shown in alert');
"""


def history_checks():
    import subprocess

    s, r, body = req(port, "/static/history.js")
    assert s == 200 and r.getheader("Content-Type", "").startswith("text/javascript"), s
    ok("history.js served as text/javascript")

    js = read(os.path.join(STATIC, "history.js")).decode()
    specs = re.findall(r"""(?:^|\n)\s*import\b[^'"]*?from\s*['"]([^'"]+)['"]""", js)
    assert specs and set(specs) <= {"./vendor/preact.mjs", "./vendor/htm.mjs"}, specs
    pre = read(os.path.join(VENDOR, "preact.mjs")).decode()
    exports = re.search(r"export\s*\{([^}]*)\}", pre).group(1)
    names = {x.split(" as ")[-1].strip() for x in exports.split(",")}
    for m in re.finditer(r"import\s*\{([^}]*)\}\s*from\s*['\"]\./vendor/preact\.mjs", js):
        for n in m.group(1).split(","):
            assert n.strip().split(" as ")[0].strip() in names, n
    ok("history.js imports only vendored modules, real names, not app.js")

    app = read(os.path.join(STATIC, "app.js")).decode()
    assert re.search(r"import\s*\{[^}]*\bHistory\b[^}]*\}\s*from\s*['\"]\./history\.js['\"]", app)
    assert re.search(r"<\$\{History\}[^>]*sessions", app), "sessions route renders <History sessions>"
    ok("app.js imports and renders History")

    assert "<table" in js and "<thead" in js
    heads = re.findall(r'<th\s+scope="col"\s*>\s*([^<]*?)\s*</th>', js)
    assert heads == ["Command", "Repo", "Started", "Ended", "Outcome", "Cost", "Transcript", "Action"], heads
    assert "<select" in js and "<label" in js
    ok("table markup: 8 scoped headers, labelled outcome select")

    for bad in ("innerHTML", "dangerouslySetInnerHTML", "console.log", "debugger"):
        assert bad not in js, bad
    assert not re.search(r"https?://", js)
    assert "encodeURIComponent" in js
    assert re.search(r"title\s*=\s*\$\{[^}]*command", js), "full command in title="
    assert 'role="alert"' in js
    ok("no innerHTML/console.log/absolute URLs; encodes ids; title + alert")

    css = read(os.path.join(STATIC, "app.css")).decode()
    blocks = re.findall(r"([^{}]+)\{([^}]*)\}", css)
    cmd = [b for sel, b in blocks if re.search(r"\.cmd\b|\.history\s+td", sel)]
    assert any(all(re.search(p, b) for p in (r"white-space\s*:\s*nowrap", r"overflow\s*:\s*hidden", r"text-overflow\s*:\s*ellipsis")) for b in cmd), "cmd truncation css"
    assert any("table-wrap" in sel and re.search(r"overflow-x\s*:\s*auto", b) for sel, b in blocks), "table-wrap overflow-x"
    assert any("history" in sel and re.search(r"min-width\s*:\s*[\d.]+(rem|ch)", b) for sel, b in blocks), "table min-width in rem/ch"
    tap = [b for sel, b in blocks if "history" in sel and re.search(r"\b(a|button|summary)\b", sel)]
    assert any(re.search(r"min-height\s*:\s*44px", b) for b in tap), "44px tap targets"
    assert any("select" in sel and re.search(r"min-height\s*:\s*44px", b) for sel, b in blocks), "select 44px"
    for m in re.finditer(r"(?<![\w-])(?:min-)?width\s*:\s*(\d+)px", css):
        assert int(m.group(1)) <= 390, m.group(0)
    ok("css: truncation, scroll wrapper, rem min-width, 44px targets")

    if not shutil.which("node"):
        print("note: node not found, skipping history logic checks")
        return
    env = dict(os.environ, HISTORY_URL=pathlib.Path(os.path.join(STATIC, "history.js")).as_uri(),
               PREACT_URL=pathlib.Path(os.path.join(VENDOR, "preact.mjs")).as_uri())
    p = subprocess.run(["node", "--input-type=module", "-e", HISTORY_JS], env=env,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr[-1500:]
    for line in p.stdout.splitlines():
        if line.startswith("ok "):
            ok(line[3:])


if HISTORY:
    try:
        history_checks()
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
