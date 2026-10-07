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
RUN = sys.argv[1:3] == ["--view", "run"]

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


RUN_JS = r"""
const M = await import(process.env.RUN_URL);
const { sessionForRun, actionsFor, mergeStream, totals, nearBottom, mdToHtml, copyCommand, postAction, RunDetail } = M;
const A = await import(process.env.APP_URL);
const assert = (await import('node:assert')).strict;
const out = (n) => console.log('ok ' + n);
const tick = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 8; i++) await tick(); };
out('run.js imports without a document');

// ---- sessionForRun
const S = (id, command, extra = {}) => ({ id, repo: 'own/repo', command, outcome: 'done', ...extra });
const forms = ['/run-issue 42', '/ai-workflow:run-issue 42', '/run-issue #42', '/run-issue https://github.com/own/repo/issues/42'];
for (const f of forms) assert.equal(sessionForRun([S('x', f)], 'own', 'repo', 42)?.id, 'x', f);
assert.equal(sessionForRun([S('x', 'whatever', { link: 'https://github.com/own/repo/issues/42' })], 'own', 'repo', 42)?.id, 'x');
assert.equal(sessionForRun([S('new', '/run-issue 42'), S('old', '/run-issue 42')], 'own', 'repo', 42).id, 'new');
assert.equal(sessionForRun([S('o', '/run-issue 7'), S('m', '/run-issue 42')], 'own', 'repo', 42).id, 'm');
out('sessionForRun matches command forms and link, newest first');
for (const c of ['/run-issue 420', '/run-issue 4', '/pr-grind 42', '/run-issue 42x'])
  assert.equal(sessionForRun([S('x', c)], 'own', 'repo', 42), null, c);
assert.equal(sessionForRun([S('x', '/run-issue 42', { repo: 'other/repo' })], 'own', 'repo', 42), null);
for (const bad of [[], null, {}, 'x', undefined, 5]) assert.equal(sessionForRun(bad, 'own', 'repo', 42), null);
out('sessionForRun boundaries and bad input');

// ---- mergeStream
const st0 = { events: [], offset: 0 };
const e1 = { kind: 'text', text: 'a' }, e2 = { kind: 'text', text: 'b' };
let st = mergeStream(st0, { events: [e1], offset: 10 });
assert.equal(st.offset, 10); assert.deepEqual(st.events, [e1]);
st = mergeStream(st, { events: [e2], offset: 20 });
assert.deepEqual(st.events, [e1, e2]); assert.equal(st.offset, 20);
st = mergeStream(st, { events: [], offset: 25 });
assert.deepEqual(st.events, [e1, e2]); assert.equal(st.offset, 25);
out('mergeStream appends and advances offset');
const dup = mergeStream(st, { events: [e1, e2], offset: 25 });
assert.deepEqual(dup.events, [e1, e2]); assert.equal(dup.offset, 25);
const old = mergeStream(st, { events: [e1], offset: 5 });
assert.deepEqual(old.events, [e1, e2]); assert.equal(old.offset, 25);
out('mergeStream drops stale or duplicate responses');

// ---- totals
const res = (cost, extra = {}) => ({ kind: 'result', cost, is_error: false, text: 't', ...extra });
assert.equal(totals([res(0.1), res(0.7)], { cost: 9 }).cost, 0.7);
assert.equal(totals([res(null)], { cost: 3 }).cost, 3);
assert.equal(totals([], { cost: 2 }).cost, 2);
assert.equal(totals([], null).cost, null);
assert.equal(totals([res(1)], null).tokens, null);
assert.deepEqual({ ...totals([res(1, { usage: { input: 1200, output: 300 } })], null).tokens }, { input: 1200, output: 300 });
assert.equal(totals([res(1, { usage: { input: 'x', output: 3 } })], null).tokens, null);
out('totals cost fallback and tokens only with usage');

// ---- nearBottom
assert.equal(nearBottom({ scrollHeight: 1000, scrollTop: 600, clientHeight: 400 }), true);
assert.equal(nearBottom({ scrollHeight: 1000, scrollTop: 590, clientHeight: 400 }), true);
assert.equal(nearBottom({ scrollHeight: 1000, scrollTop: 100, clientHeight: 400 }), false);
out('nearBottom');

// ---- actionsFor
const O = (outcome, rc = null) => ({ id: 'x', outcome, resume_command: rc });
for (const o of ['starting', 'running', 'waiting']) assert.deepEqual([...actionsFor(O(o))], ['stop'], o);
assert.deepEqual([...actionsFor(O('stopped', 'claude -r x'))], ['resume', 'terminal']);
assert.deepEqual([...actionsFor(O('stopped'))], ['resume']);
for (const o of ['done', 'failed']) { assert.deepEqual([...actionsFor(O(o, 'claude -r x'))], ['terminal']); assert.deepEqual([...actionsFor(O(o))], []); }
assert.deepEqual([...actionsFor(O('running', 'claude -r x'))], ['stop', 'terminal']);
assert.deepEqual([...actionsFor(null)], []);
out('actionsFor');

// ---- mdToHtml
let h = mdToHtml('# Title\n\nsome **bold** and `code`\n\n- a\n- b\n\n1. one\n2. two\n\n```\n# not heading\n**raw**\n```');
assert.match(h, /<h1>Title<\/h1>/); assert.match(h, /<strong>bold<\/strong>/); assert.match(h, /<code>code<\/code>/);
assert.match(h, /<ul>\s*<li>a<\/li>\s*<li>b<\/li>\s*<\/ul>/); assert.match(h, /<ol>\s*<li>one<\/li>\s*<li>two<\/li>\s*<\/ol>/);
assert.match(h, /<p>some /); assert.match(h, /<pre>[\s\S]*# not heading[\s\S]*\*\*raw\*\*[\s\S]*<\/pre>/);
assert.doesNotMatch(h, /<h1>not heading/); assert.doesNotMatch(h, /<strong>raw/);
out('mdToHtml renders blocks and inline');
for (const bad of ['<img src=x onerror=alert(1)>', '<script>alert(1)</script>', '"><svg onload=alert(1)>', '[x](javascript:alert(1))', "a & b 'q'"]) {
  const r = mdToHtml(bad);
  assert.doesNotMatch(r, /<(img|script|svg)/i, bad); assert.doesNotMatch(r, /<a[\s>]/i); assert.doesNotMatch(r, /href/i);
  assert.doesNotMatch(r, /<[a-z]+[^>]*\s(on\w+|src)=/i, bad);
}
assert.match(mdToHtml('a & <b> "q" \'s\''), /a &amp; &lt;b&gt; &quot;q&quot; &#0?39;s&#0?39;|a &amp; &lt;b&gt; &quot;q&quot; &#x27;s&#x27;/);
assert.equal(mdToHtml(''), ''); assert.equal(mdToHtml(null), '');
out('mdToHtml escapes hostile input; empty is empty');

// ---- copyCommand / postAction
assert.deepEqual({ ...(await copyCommand('c', { clipboard: { writeText: async () => {} } })) }, { ok: true });
assert.equal((await copyCommand('c', {})).ok, false);
assert.equal((await copyCommand('c', undefined)).ok, false);
assert.equal((await copyCommand('c', { clipboard: { writeText: async () => { throw new Error('no'); } } })).ok, false);
out('copyCommand');

const jr = (ok, status, body) => ({ ok, status, json: async () => { if (body instanceof Error) throw body; return body; } });
let calls = [], timers = [], tid = 0, routes = [];
const doc = { hidden: false, ls: {}, addEventListener(t, f) { (this.ls[t] ||= []).push(f); },
  removeEventListener(t, f) { this.ls[t] = (this.ls[t] || []).filter((x) => x !== f); } };
globalThis.document = doc;
globalThis.setTimeout = (fn, ms) => { const t = { id: ++tid, fn, ms }; timers.push(t); return t.id; };
globalThis.clearTimeout = (id) => { timers = timers.filter((t) => t.id !== id); };
globalThis.fetch = (u, o) => {
  calls.push({ u, o });
  for (const r of routes) if (r.test(u, o)) return typeof r.reply === 'function' ? r.reply(u, o) : Promise.resolve(r.reply);
  return Promise.resolve(jr(false, 500, {}));
};
const reset = () => { calls = []; timers = []; routes = []; };
const when = (re, reply) => routes.unshift({ test: (u) => re.test(u), reply });

reset(); when(/./, jr(true, 200, { ok: 1 }));
assert.deepEqual({ ...(await postAction('a b', 'stop')) }, { ok: true });
assert.equal(calls[0].u, '/api/sessions/a%20b/stop'); assert.equal(calls[0].o.method, 'POST');
reset(); when(/./, jr(false, 409, { error: 'already stopped' }));
assert.deepEqual({ ...(await postAction('s', 'resume')) }, { ok: false, error: 'already stopped' });
reset(); when(/./, jr(false, 502, new SyntaxError('x')));
assert.deepEqual({ ...(await postAction('s', 'stop')) }, { ok: false, error: 'HTTP 502' });
reset(); when(/./, () => Promise.reject(new Error('net down')));
const nr = await postAction('s', 'stop'); assert.equal(nr.ok, false); assert.ok(nr.error);
out('postAction');

// ---- poll extensions in app.js
reset(); let offs = 0; let got = [];
when(/^\/x\?o=\d+$/, jr(false, 404, {}));
const stopP = A.poll(() => '/x?o=' + offs++, 1000, (r) => got.push(r));
await settle();
assert.equal(calls[0].u, '/x?o=0'); assert.equal(got[0].ok, false); assert.equal(got[0].status, 404);
timers.shift().fn(); await settle(); assert.equal(calls[1].u, '/x?o=1');
stopP();
out('poll accepts a url function and reports status on failure');

// ---- vnode walker
const norm = (v) => {
  if (v == null || typeof v === 'boolean') return null;
  if (typeof v === 'string' || typeof v === 'number') return String(v);
  if (Array.isArray(v)) return { type: null, props: {}, kids: v.map(norm).filter((x) => x !== null) };
  if (typeof v.type === 'function' && !v.type.prototype?.render) return norm(v.type({ ...v.props, children: v.props.children }));
  const c = v.props?.children;
  return { type: v.type, props: v.props || {}, key: v.key, kids: c == null ? [] : [].concat(c).flatMap((x) => (Array.isArray(x) ? x : [x])).map(norm).filter((x) => x !== null) };
};
const text = (n) => (typeof n === 'string' ? n : n.props?.dangerouslySetInnerHTML ? '' : n.kids.map(text).join(' ')).replace(/\s+/g, ' ');
const all = (n, acc = []) => { if (typeof n === 'string') return acc; acc.push(n); n.kids.forEach((k) => all(k, acc)); return acc; };
const find = (n, f) => all(n).filter(f);
const T = (c) => norm(c.render(c.props, c.state));
const txt = (c) => text(T(c)).trim();

const RUN = { owner: 'own', repo: 'repo', issue: 42, status: 'running', currentStation: 'dev',
  stations: [{ name: 'plan', status: 'done', bounces: 0 }, { name: 'dev', status: 'running', bounces: 2 }, { name: 'verify', status: 'pending', bounces: 0 }, { name: 'ship', status: 'bounced', bounces: 0 }],
  trace: [], plan: '# Plan title\n\n- step one', totals: { stations: 4, done: 1, bounces: 2 }, errors: {} };
const sess = (o = {}) => ({ id: 's1', repo: 'own/repo', command: '/run-issue 42', outcome: 'running', cost: null, resume_command: null, resumed_fresh: false, note: null, ...o });
const RUNURL = /^\/api\/runs\/own\/repo\/42$/;
const STREAM = (id = 's1', off = '\\d+') => new RegExp('^/api/sessions/' + id + '/stream\\?offset=' + off + '$');
const streamCalls = () => calls.filter((c) => /\/stream/.test(c.u));

async function mount(sessions, runReply = jr(true, 200, RUN), props = {}) {
  const c = new RunDetail({ owner: 'own', repo: 'repo', n: 42, sessions, ...props });
  c.state = c.state || {};
  c.setState = (p, cb) => { c.state = { ...c.state, ...(typeof p === 'function' ? p(c.state, c.props) : p) }; if (cb) cb(); };
  if (runReply) when(RUNURL, runReply);
  c.componentDidMount && c.componentDidMount();
  await settle();
  return c;
}
async function update(c, sessions) {
  const prev = c.props; c.props = { ...prev, sessions };
  c.componentDidUpdate && c.componentDidUpdate(prev, c.state);
  await settle();
}
const fireTimers = async (ms) => { for (const t of timers.filter((x) => x.ms === ms)) { timers = timers.filter((x) => x !== t); t.fn(); } await settle(); };
const btns = (c) => find(T(c), (n) => n.type === 'button' && n.props.role !== 'tab');
const btn = (c, re) => btns(c).find((b) => re.test(text(b)));
const status = (c) => find(T(c), (n) => n.props.role === 'status').map(text).join(' ');
const tab = (c, re) => find(T(c), (n) => n.props.role === 'tab' && re.test(text(n)))[0];

// ---- timeline
reset(); when(STREAM(), jr(true, 200, { events: [], offset: 0 }));
let c = await mount([sess()]);
let tl = find(T(c), (n) => n.type === 'ol')[0];
assert.ok(tl, 'ol timeline');
let rows = tl.kids.filter((k) => k.type === 'li');
assert.equal(rows.length, 4);
['plan', 'dev', 'verify', 'ship'].forEach((nm, i) => assert.match(text(rows[i]), new RegExp(nm)));
['done', 'running', 'pending', 'bounced'].forEach((st, i) => assert.match(text(rows[i]), new RegExp(st)));
const cur = find(tl, (n) => n.props['aria-current'] === 'step');
assert.equal(cur.length, 1); assert.match(text(cur[0]), /dev/); assert.match(text(cur[0]), /2/);
assert.doesNotMatch(text(tl), /\d\s*(ms|sec|seconds|min|minutes|hours?)\b|\bago\b|\d:\d\d/i);
const all0 = txt(c); assert.match(all0, /4/); assert.match(all0, /own\/repo#42/);
out('timeline order, status, aria-current, bounces, totals, no time text');
c.componentWillUnmount && c.componentWillUnmount();

reset(); when(/./, jr(true, 200, {}));
c = await mount([sess({ outcome: 'done' })], jr(true, 200, { ...RUN, status: 'done', currentStation: null, stations: [{ name: 'plan', status: 'done', bounces: 0 }, { name: 'weird', status: 'zzz-unknown', bounces: 0 }] }));
assert.equal(find(T(c), (n) => n.props['aria-current'] === 'step').length, 0);
assert.match(txt(c), /zzz-unknown/);
out('timeline done run has no current row; unknown status shown');

// ---- polling schedule
reset(); when(STREAM(), jr(true, 200, { events: [], offset: 0 }));
c = await mount([sess({ outcome: 'running' })]);
assert.ok(timers.some((t) => t.ms === 3000), 'run endpoint 3s'); assert.ok(calls.some((x) => RUNURL.test(x.u)));
assert.ok(timers.some((t) => t.ms === 1000), 'stream 1s while running');
assert.match(streamCalls()[0].u, /s1\/stream\?offset=0$/);
c.componentWillUnmount && c.componentWillUnmount();
assert.equal(timers.length, 0, 'unmount stops all polls');
for (const o of ['done', 'failed', 'stopped', 'waiting']) {
  reset(); when(STREAM(), jr(true, 200, { events: [], offset: 0 }));
  c = await mount([sess({ outcome: o })]);
  assert.equal(streamCalls().length, 1, o); assert.match(streamCalls()[0].u, /offset=0$/);
  assert.ok(!timers.some((t) => t.ms === 1000), o + ' no stream timer');
  c.componentWillUnmount && c.componentWillUnmount();
}
reset(); when(STREAM(), jr(true, 200, { events: [], offset: 0 }));
c = await mount([sess({ outcome: 'starting' })]); assert.ok(timers.some((t) => t.ms === 1000), 'starting polls');
c.componentWillUnmount && c.componentWillUnmount();
out('stream poll only while starting/running; terminal fetched once; run endpoint 3s');

// ---- output pane, offsets, terminal transition, id change
const EV = [{ kind: 'text', text: 'hello <b>x</b>' }, { kind: 'tool', name: 'Bash', input: { command: 'ls -la' } }, { kind: 'result', cost: 0.5, is_error: false, text: 'finished ok' }];
reset(); let step = 0;
when(STREAM(), () => { step++; return Promise.resolve(jr(true, 200, step === 1 ? { events: EV, offset: 100 } : { events: [], offset: 100 })); });
c = await mount([sess()]);
let t0 = txt(c);
assert.ok(t0.includes('hello <b>x</b>'), 'text event as literal text'); assert.match(t0, /Bash/); assert.match(t0, /ls -la/); assert.match(t0, /finished ok/);
assert.equal(find(T(c), (n) => n.type === 'b').length, 0);
assert.match(t0, /0\.5/);
assert.doesNotMatch(t0, /token/i);
await fireTimers(1000);
assert.match(streamCalls().at(-1).u, /offset=100$/);
assert.equal(txt(c).split('hello').length, 2, 'no duplicates');
out('output pane renders events as text, polls from saved offset, no duplicates');

when(STREAM(), jr(true, 200, { events: [{ kind: 'text', text: 'LASTLINE' }], offset: 130 }));
const before = streamCalls().length;
await update(c, [sess({ outcome: 'done' })]);
assert.equal(streamCalls().length, before + 1); assert.match(streamCalls().at(-1).u, /offset=100$/);
assert.match(txt(c), /LASTLINE/);
assert.ok(!timers.some((t) => t.ms === 1000));
await fireTimers(3000);
assert.equal(streamCalls().length, before + 1, 'no further stream fetches');
out('terminal transition stops poll and fetches the tail once');

reset(); when(STREAM('s1'), jr(true, 200, { events: [{ kind: 'text', text: 'OLDSTREAM' }], offset: 50 }));
when(STREAM('s2'), jr(true, 200, { events: [{ kind: 'text', text: 'NEWSTREAM' }], offset: 7 }));
c = await mount([sess()]);
assert.match(txt(c), /OLDSTREAM/);
await update(c, [sess({ id: 's2' }), sess()]);
assert.match(streamCalls().at(-1).u, /s2\/stream\?offset=0$/);
assert.doesNotMatch(txt(c), /OLDSTREAM/); assert.match(txt(c), /NEWSTREAM/);
out('session id change resets stream and restarts at offset 0');

// ---- no session / not found / retry
reset();
c = await mount([]);
assert.match(txt(c), /No UI session for this run/);
assert.equal(btns(c).length, 0); assert.equal(streamCalls().length, 0);
assert.equal(find(T(c), (n) => n.type === 'ol').length, 1);
await tab(c, /plan/i).props.onClick({}); await settle();
assert.ok(find(T(c), (n) => n.props.dangerouslySetInnerHTML).length === 1);
out('no matching session: timeline and plan render, no buttons, no stream fetch');

reset(); c = await mount([], jr(false, 404, {}));
assert.match(txt(c), /not found/i);
assert.ok(find(T(c), (n) => n.type === 'a' && n.props.href === '#/').length >= 1);
reset(); c = await mount([]);
when(RUNURL, jr(false, 500, {}));
await fireTimers(3000);
assert.match(txt(c), /retrying/i); assert.doesNotMatch(txt(c), /not found/i); assert.match(txt(c), /verify/);
out('404 shows not-found with Board link; other failures keep data and retry');

// ---- plan tab and tabs aria
reset(); c = await mount([]);
const tabs = find(T(c), (n) => n.props.role === 'tablist')[0];
assert.ok(tabs); const tt = find(tabs, (n) => n.props.role === 'tab');
assert.equal(tt.length, 2);
for (const t of tt) { assert.equal(t.type, 'button'); assert.ok(t.props['aria-controls']); assert.ok(t.props.id); }
assert.equal(tt.filter((t) => t.props['aria-selected'] === true || t.props['aria-selected'] === 'true').length, 1);
let panel = find(T(c), (n) => n.props.role === 'tabpanel');
assert.equal(panel.length, 1);
const selId = (cc) => find(T(cc), (n) => n.props.role === 'tab' && String(n.props['aria-selected']) === 'true')[0];
assert.equal(panel[0].props['aria-labelledby'], selId(c).props.id); assert.equal(panel[0].props.id, selId(c).props['aria-controls']);
const first = selId(c).props.id;
await tab(c, /plan/i).props.onClick({}); await settle();
assert.notEqual(selId(c).props.id, first); assert.match(text(selId(c)), /plan/i);
panel = find(T(c), (n) => n.props.role === 'tabpanel');
assert.equal(panel[0].props['aria-labelledby'], selId(c).props.id);
const dsh = find(panel[0], (n) => n.props.dangerouslySetInnerHTML)[0];
assert.match(dsh.props.dangerouslySetInnerHTML.__html, /<h1>Plan title<\/h1>/);
out('tabs aria and plan rendering via mdToHtml');

reset(); c = await mount([], jr(true, 200, { ...RUN, plan: null }));
await tab(c, /plan/i).props.onClick({}); await settle();
assert.match(txt(c), /No plan yet/); assert.doesNotMatch(txt(c), /could not be read/);
reset(); c = await mount([], jr(true, 200, { ...RUN, plan: null, errors: { plan: 'bad json' } }));
await tab(c, /plan/i).props.onClick({}); await settle();
assert.match(txt(c), /Plan could not be read/); assert.doesNotMatch(txt(c), /No plan yet/);
out('plan empty vs unreadable states');

// ---- action buttons
const label = (c) => btns(c).map((b) => text(b));
reset(); when(STREAM(), jr(true, 200, { events: [], offset: 0 }));
c = await mount([sess({ outcome: 'running' })]);
assert.equal(btns(c).length, 1); assert.match(label(c)[0], /stop/i);
assert.ok(btns(c).every((b) => b.props.type === 'button'));
reset(); c = await mount([sess({ outcome: 'stopped', resume_command: 'claude -r s1' })]);
assert.ok(btn(c, /^resume/i)); assert.ok(btn(c, /terminal/i)); assert.ok(!btn(c, /stop/i));
reset(); c = await mount([sess({ outcome: 'done', resume_command: 'claude -r s1' })]);
assert.deepEqual(label(c).length, 1); assert.match(label(c)[0], /terminal/i);
out('buttons per outcome are real type=button');

reset(); let release; when(STREAM(), jr(true, 200, { events: [], offset: 0 }));
c = await mount([sess({ outcome: 'running' })]);
when(/\/stop$/, () => new Promise((r) => { release = r; }));
const clicked = btn(c, /stop/i).props.onClick({ preventDefault() {} });
await settle();
assert.ok(btn(c, /stop/i).props.disabled, 'disabled while in flight');
assert.equal(calls.find((x) => /\/stop$/.test(x.u)).o.method, 'POST');
release(jr(true, 200, { ok: true })); await clicked; await settle();
assert.match(status(c), /Stopped/); assert.ok(!btn(c, /stop/i)?.props.disabled);
when(/\/stop$/, jr(false, 409, { error: 'not running' }));
await btn(c, /stop/i).props.onClick({ preventDefault() {} }); await settle();
assert.match(status(c), /Stop failed: not running/);
out('stop button disabled in flight, status region reports result');

reset(); c = await mount([sess({ outcome: 'stopped' })]);
when(/\/resume$/, jr(true, 200, { ok: true }));
await btn(c, /^resume/i).props.onClick({ preventDefault() {} }); await settle();
assert.match(status(c), /Resumed/);
out('resume button reports Resumed');

reset(); Object.defineProperty(globalThis, 'navigator', { value: { clipboard: { writeText: async () => {} } }, configurable: true });
c = await mount([sess({ outcome: 'done', resume_command: 'claude -r s1' })]);
await btn(c, /terminal/i).props.onClick({ preventDefault() {} }); await settle();
assert.match(status(c), /Copied/);
Object.defineProperty(globalThis, 'navigator', { value: {}, configurable: true });
reset(); c = await mount([sess({ outcome: 'done', resume_command: 'claude -r s1' })]);
await btn(c, /terminal/i).props.onClick({ preventDefault() {} }); await settle();
assert.match(status(c), /Copy failed: select the command below/);
const box = find(T(c), (n) => n.type === 'input' && (n.props.readOnly || n.props.readonly))[0];
assert.ok(box); assert.equal(box.props.value, 'claude -r s1'); assert.ok(box.props['aria-label']);
out('copy success and readonly fallback box');

reset(); c = await mount([sess({ outcome: 'stopped', resumed_fresh: true, note: 'context was lost' })]);
assert.match(txt(c), /resumed fresh/i); assert.match(txt(c), /context was lost/);
reset(); c = await mount([sess({ outcome: 'stopped' })]);
assert.doesNotMatch(txt(c), /resumed fresh/i);
out('resumed fresh note');

// ---- App routing
const app = new A.App();
app.state = { route: A.parseRoute('#/run/a/b/1'), sessions: [sess()], offline: false };
const tree = norm(app.render(app.props, app.state));
const rd = find(tree, (n) => n.type === RunDetail)[0];
assert.ok(rd, 'RunDetail routed');
assert.equal(rd.props.owner, 'a'); assert.equal(rd.props.repo, 'b'); assert.equal(rd.props.n, 1);
assert.equal(rd.props.sessions.length, 1); assert.equal(rd.key, 'a/b/1');
out('App routes #/run to RunDetail keyed by owner/repo/n');
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
    assert set(specs) <= {"./vendor/preact.mjs", "./vendor/htm.mjs", "./run.js"}, specs
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



def run_checks():
    import subprocess

    for name, t in (("run.js", "text/javascript"), ("app.css", "text/css")):
        s, r, _ = req(port, f"/static/{name}")
        assert s == 200 and r.getheader("Content-Type", "").startswith(t), (name, s)
    ok("run.js/app.css served with correct types")

    js = read(os.path.join(STATIC, "run.js")).decode()
    css = read(os.path.join(STATIC, "app.css")).decode()
    specs = re.findall(r"""(?:^|\n)\s*import\b[^'"]*?from\s*['"]([^'"]+)['"]""", js)
    assert specs and set(specs) <= {"./vendor/preact.mjs", "./vendor/htm.mjs", "./app.js"}, specs
    assert not re.search(r"https?://", js), "no absolute URLs"
    assert "console.log" not in js and "debugger" not in js and "innerHTML" not in js.replace("dangerouslySetInnerHTML", "")
    pre = read(os.path.join(VENDOR, "preact.mjs")).decode()
    exports = re.search(r"export\s*\{([^}]*)\}", pre).group(1)
    names = {x.split(" as ")[-1].strip() for x in exports.split(",")}
    for m in re.finditer(r"import\s*\{([^}]*)\}\s*from\s*['\"]\./vendor/preact\.mjs", js):
        for n in m.group(1).split(","):
            assert n.strip().split(" as ")[0].strip() in names, n
    for m in re.finditer(r"dangerouslySetInnerHTML\s*=\s*\$\{\s*\{\s*__html\s*:\s*([^}]*)\}", js):
        assert m.group(1).strip().startswith("mdToHtml("), m.group(1)
    assert len(re.findall(r"dangerouslySetInnerHTML", js)) == len(re.findall(r"__html\s*:\s*mdToHtml\(", js))
    ok("run.js imports, no innerHTML/absolute URLs, html only via mdToHtml")

    assert re.search(r"flex-wrap\s*:\s*wrap", css)
    assert re.search(r"min-height\s*:\s*44px", css)
    for m in re.finditer(r"(?<![\w-])(?:min-)?width\s*:\s*(\d+)px", css):
        assert int(m.group(1)) <= 390, m.group(0)
    out_rule = re.search(r"\.output\s*\{([^}]*)\}", css)
    assert out_rule and "overflow-y: auto" in out_rule.group(1).replace(":auto", ": auto") and "max-height" in out_rule.group(1)
    assert re.search(r"\[role=tab\][^{]*\{[^}]*min-height\s*:\s*44px|\.run button[^{]*\{[^}]*min-height\s*:\s*44px", css)
    ok("css run layout wraps, 44px targets, bounded scrolling output")

    if not shutil.which("node"):
        print("note: node not found, skipping run logic checks")
        return
    env = dict(os.environ, RUN_URL=pathlib.Path(os.path.join(STATIC, "run.js")).as_uri(),
               APP_URL=pathlib.Path(os.path.join(STATIC, "app.js")).as_uri())
    p = subprocess.run(["node", "--input-type=module", "-e", RUN_JS], env=env,
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-2500:]
    for line in p.stdout.splitlines():
        if line.startswith("ok "):
            ok(line[3:])


if RUN:
    try:
        run_checks()
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
