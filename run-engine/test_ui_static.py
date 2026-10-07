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

RUN_JS = r"""
const M = await import(process.env.RUN_URL);
const { sessionForRun, sessionsForRun, actionsFor, mergeStream, totals, nearBottom, mdToHtml, copyCommand, postAction, RunDetail } = M;
const A = await import(process.env.APP_URL);
const assert = (await import('node:assert')).strict;
const out = (n) => console.log('ok ' + n);
const tick = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 8; i++) await tick(); };
out('run.js imports without a document');

const { formatWhen, shortRepo } = await import(new URL('./fmt.js', process.env.RUN_URL).href);
const noon = new Date(2026, 9, 7, 12, 0);
assert.match(formatWhen(new Date(2026, 9, 7, 9, 5).toISOString(), noon), /^Today 09:05$/);
assert.match(formatWhen(new Date(2026, 9, 6, 17, 40).toISOString(), noon), /^Yesterday 17:40$/);
assert.match(formatWhen(new Date(2026, 9, 1, 8, 0).toISOString(), noon), /^Oct 1 08:00$/);
assert.equal(formatWhen(null, noon), '—'); assert.equal(formatWhen('garbage', noon), '—');
assert.equal(shortRepo('/Users/x/Projects/ai-workflow/'), 'ai-workflow'); assert.equal(shortRepo('o/r'), 'r'); assert.equal(shortRepo(''), '—');
out('fmt: formatWhen and shortRepo');

// ---- sessionForRun
const S = (id, command, extra = {}) => ({ id, repo: 'own/repo', command, outcome: 'done', ...extra });
const forms = ['/run-issue 42', '/ai-workflow:run-issue 42', '/run-issue #42', '/run-issue https://github.com/own/repo/issues/42'];
for (const f of forms) assert.equal(sessionForRun([S('x', f)], 'own', 'repo', 42)?.id, 'x', f);
assert.equal(sessionForRun([S('x', 'whatever', { link: 'https://github.com/own/repo/issues/42' })], 'own', 'repo', 42)?.id, 'x');
assert.equal(sessionForRun([S('new', '/run-issue 42'), S('old', '/run-issue 42')], 'own', 'repo', 42).id, 'new');
assert.equal(sessionForRun([S('o', '/run-issue 7'), S('m', '/run-issue 42')], 'own', 'repo', 42).id, 'm');
out('sessionForRun matches command forms and link, newest first');
assert.deepEqual(sessionsForRun([S('a', '/run-issue 42'), S('b', '/run-issue 7'), S('c', '/run-issue 42')], 'own', 'repo', 42).map((x) => x.id), ['a', 'c']);
assert.deepEqual(sessionsForRun(null, 'own', 'repo', 42), []);
out('sessionsForRun returns every matching session');
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
  c = await mount([sess({ outcome: o, ...(o === 'waiting' ? { ended_at: '2026-01-01T00:00:00Z' } : {}) })]);
  assert.equal(streamCalls().length, 1, o); assert.match(streamCalls()[0].u, /offset=0$/);
  assert.ok(!timers.some((t) => t.ms === 1000), o + ' no stream timer');
  c.componentWillUnmount && c.componentWillUnmount();
}
reset(); when(STREAM(), jr(true, 200, { events: [], offset: 0 }));
c = await mount([sess({ outcome: 'starting' })]); assert.ok(timers.some((t) => t.ms === 1000), 'starting polls');
c.componentWillUnmount && c.componentWillUnmount();
reset(); when(STREAM(), jr(true, 200, { events: [], offset: 0 }));
c = await mount([sess({ outcome: 'waiting', ended_at: null })]);
assert.ok(timers.some((t) => t.ms === 1000), 'waiting + process alive (ended_at null) keeps 1s stream poll');
c.componentWillUnmount && c.componentWillUnmount();
reset(); when(STREAM(), jr(true, 200, { events: [], offset: 0 }));
c = await mount([sess({ outcome: 'waiting', ended_at: '2026-01-01T00:00:00Z' })]);
assert.equal(streamCalls().length, 1); assert.ok(!timers.some((t) => t.ms === 1000), 'waiting + ended_at set: one fetch, no timer');
c.componentWillUnmount && c.componentWillUnmount();
out('stream poll only while starting/running or live waiting; terminal fetched once; run endpoint 3s');

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

reset(); when(STREAM(), jr(true, 200, { events: [], offset: 7 }));
c = await mount([sess({ outcome: 'waiting', ended_at: null })]);
assert.ok(timers.some((t) => t.ms === 1000), 'live waiting polls');
when(STREAM(), jr(true, 200, { events: [{ kind: 'text', text: 'TAIL2' }], offset: 20 }));
const before2 = streamCalls().length;
await update(c, [sess({ outcome: 'done', ended_at: '2026-01-01T00:00:00Z' })]);
assert.equal(streamCalls().length, before2 + 1); assert.match(streamCalls().at(-1).u, /offset=7$/);
assert.match(txt(c), /TAIL2/); assert.ok(!timers.some((t) => t.ms === 1000));
out('waiting-live to done does the final fetch and stops the poll');

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
assert.equal(tt.length, 3);
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
await tab(c, /sessions/i).props.onClick({}); await settle();
assert.match(text(tab(c, /sessions/i)), /Sessions \(0\)/);
assert.match(txt(c), /No UI sessions for this run/);
await tab(c, /plan/i).props.onClick({}); await settle();
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


def run_checks():
    import subprocess

    for name, t in (("run.js", "text/javascript"), ("app.css", "text/css")):
        s, r, _ = req(port, f"/static/{name}")
        assert s == 200 and r.getheader("Content-Type", "").startswith(t), (name, s)
    ok("run.js/app.css served with correct types")

    js = read(os.path.join(STATIC, "run.js")).decode()
    css = read(os.path.join(STATIC, "app.css")).decode()
    specs = re.findall(r"""(?:^|\n)\s*import\b[^'"]*?from\s*['"]([^'"]+)['"]""", js)
    assert specs and set(specs) <= {"./vendor/preact.mjs", "./vendor/htm.mjs", "./app.js", "./fmt.js"}, specs
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
LAUNCHER = sys.argv[1:3] == ["--view", "launcher"]
LAUNCHER_ALL = sys.argv[1:3] == ["--view", "launcher-all"]
BOARD = sys.argv[1:3] == ["--view", "board"]
ANSWER = sys.argv[1:3] == ["--view", "answer"]
NOTIFY = sys.argv[1:3] == ["--view", "notify"]
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

// real _public() shape: outcome + waiting, never `status`
const mk = (id, status) => (status === undefined ? { id } : { id, outcome: status, waiting: status === 'waiting' });
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
let lastOpts = null;
globalThis.fetch = (u, o) => { calls.push(u); lastOpts = o; return new Promise((res, rej) => pend.push({ res, rej })); };
const resp = (ok, status, body) => ({ ok, status, json: async () => { if (body instanceof Error) throw body; return body; } });
const results = [];
const stop = poll('/api/sessions', 1000, (r) => results.push(r));
assert.equal(calls.length, 1); assert.equal(calls[0], '/api/sessions');
assert.ok(lastOpts.signal instanceof AbortSignal, 'fetch carries a timeout signal so a hung server cannot stall the poll');
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

ANSWER_NODE_JS = r"""
const A = await import(process.env.ANSWER_URL);
const assert = (await import('node:assert')).strict;
const out = (n) => console.log('ok ' + n);
const { viewMode, displayLabel, initialAnswers, toggle, buildBody, startSubmit, afterSubmit,
  submitAnswer, runHash, planRun, planText, resumeCommand } = A;
out('import without document does not throw');

const waiting = { waiting: true, outcome: 'waiting', pending_question: { id: 'q1', status: 'pending' } };
assert.equal(viewMode(waiting), 'form');
assert.equal(viewMode({ ...waiting, waiting: false }), 'state');
assert.equal(viewMode({ ...waiting, outcome: 'running' }), 'state');
assert.equal(viewMode({ ...waiting, pending_question: { id: 'q1', status: 'answered' } }), 'state');
assert.equal(viewMode({ ...waiting, pending_question: null }), 'state');
assert.equal(viewMode({ outcome: 'failed' }), 'failed');
assert.equal(viewMode({ outcome: 'done' }), 'state');
assert.equal(viewMode(null), 'state');
assert.equal(viewMode({}), 'state');
out('viewMode');

const REC = 'Approve (Recommended)';
const pending = { id: 'r9', status: 'pending', questions: [
  { question: 'Pick one', header: 'One', multiSelect: false, allowFreeText: true, recommended: REC,
    options: [{ label: REC, description: 'd' }, { label: 'Reject', description: 'e' }] },
  { question: 'Pick many', header: 'Many', multiSelect: true, allowFreeText: true, recommended: 'B (Recommended)',
    options: [{ label: 'A' }, { label: 'B (Recommended)' }, { label: 'C' }] },
  { question: 'Free', header: 'Free', multiSelect: false, allowFreeText: true,
    options: [{ label: 'X' }, { label: 'Y' }] },
] };
const init = initialAnswers(pending);
assert.equal(init.length, 3);
assert.deepEqual(init[0].labels, [REC]); assert.equal(init[0].other, '');
assert.deepEqual(init[1].labels, ['B (Recommended)']);
assert.deepEqual(init[2].labels, []); assert.equal(init[2].other, '');
out('initialAnswers preselects recommended');

const st = { answers: [{ labels: [REC], other: '' }, { labels: ['A', 'B (Recommended)'], other: '' }, { labels: [], other: 'text' }], sending: false, error: null };
assert.deepEqual(buildBody(pending, st), { round_id: 'r9', answers: { '0': { labels: [REC] }, '1': { labels: ['A', 'B (Recommended)'] }, '2': { other: 'text' } } });
out('buildBody mixed round, exact labels incl. (Recommended)');
assert.equal(displayLabel(REC), 'Approve');
assert.equal(displayLabel('Plain'), 'Plain');
out('displayLabel strips suffix');

const mkst = (o) => ({ answers: [{ labels: [], other: '' }, { labels: ['A'], other: '' }, { labels: ['X'], other: '' }], sending: false, error: null, ...o });
let b = buildBody(pending, mkst({}));
assert.ok(b.error && /Pick one|One/.test(b.error), 'names question');
const wsp = mkst({ answers: [{ labels: [], other: '   ' }, { labels: ['A'], other: '' }, { labels: ['X'], other: '' }] });
assert.ok(buildBody(pending, wsp).error);
const both = mkst({ answers: [{ labels: [REC], other: ' mine ' }, { labels: ['A'], other: '  ' }, { labels: ['X'], other: '' }] });
b = buildBody(pending, both);
assert.deepEqual(b.answers['0'], { other: 'mine' });
assert.deepEqual(b.answers['1'], { labels: ['A'] });
out('buildBody empty, whitespace, other wins');

const nf = { id: 'r', questions: [{ question: 'Q', multiSelect: false, allowFreeText: false, options: [{ label: 'a' }] }] };
b = buildBody(nf, { answers: [{ labels: ['a'], other: 'sneaky' }] });
assert.deepEqual(b.answers['0'], { labels: ['a'] });
assert.ok(buildBody(nf, { answers: [{ labels: [], other: 'sneaky' }] }).error);
out('allowFreeText false never emits other');

const big = (n) => ({ answers: [{ labels: [], other: 'x'.repeat(n) }] });
const one = { id: 'r', questions: [{ question: 'Q', allowFreeText: true, options: [{ label: 'a' }] }] };
assert.equal(buildBody(one, big(4000)).answers['0'].other.length, 4000);
assert.ok(buildBody(one, big(4001)).error);
out('4000 char boundary');

const t0 = { answers: [{ labels: ['A'], other: '' }] };
assert.deepEqual(toggle(t0, 0, 'B', false).answers[0].labels, ['B']);
assert.deepEqual(toggle(t0, 0, 'B', true).answers[0].labels, ['A', 'B']);
assert.deepEqual(toggle(toggle(t0, 0, 'B', true), 0, 'A', true).answers[0].labels, ['B']);
assert.deepEqual(t0.answers[0].labels, ['A'], 'pure');
const pre = { answers: initialAnswers(pending) };
assert.ok(!toggle(pre, 1, 'B (Recommended)', true).answers[1].labels.includes('B (Recommended)'));
out('toggle pure, single/multi, untick recommended');

// fetch mocking
let calls = [], pend = [];
globalThis.fetch = (u, o) => { calls.push([u, o]); return new Promise((res, rej) => pend.push({ res, rej })); };
const tick = () => new Promise((r) => setImmediate(r));
const body = { round_id: 'r9', answers: { '0': { labels: ['a'] } } };
const pr = submitAnswer('a/b c', body);
assert.equal(calls.length, 1);
assert.equal(calls[0][0], '/api/sessions/' + encodeURIComponent('a/b c') + '/answer');
assert.equal(calls[0][1].method, 'POST');
assert.equal(calls[0][1].headers['Content-Type'], 'application/json');
assert.deepEqual(JSON.parse(calls[0][1].body), body);
pend.shift().res({ ok: true, status: 200, json: async () => ({ ok: 1 }) });
assert.deepEqual({ ...(await pr) }, { ok: true, status: 200, data: { ok: 1 } });
out('submitAnswer request and result');

let s1 = startSubmit(mkst({}));
assert.equal(s1.sending, true);
assert.equal(startSubmit(s1), null);
calls = []; pend = [];
const s2 = startSubmit(mkst({}));
if (s2) submitAnswer('s', body);
const s3 = startSubmit({ ...s2, sending: true });
if (s3) submitAnswer('s', body);
assert.equal(calls.length, 1, 'exactly one fetch');
out('startSubmit blocks double submit');

const typed = mkst({ sending: true });
const okr = afterSubmit(typed, { ok: true, status: 200, data: {} });
assert.ok(okr && okr.navigate, 'navigate target on success');
for (const [status, msg] of [[409, 'round already answered'], [400, 'bad'], [409, 'not waiting'], [500, 'boom']]) {
  const r = afterSubmit(typed, { ok: false, status, data: { error: msg } });
  assert.equal(r.sending, false); assert.equal(r.error, msg);
  assert.deepEqual(r.answers, typed.answers);
}
for (const bad of [{ ok: false, status: 0, data: null }, { ok: false, status: 502, data: undefined }]) {
  const r = afterSubmit(typed, bad);
  assert.equal(r.sending, false); assert.ok(typeof r.error === 'string' && r.error);
  assert.deepEqual(r.answers, typed.answers);
}
out('afterSubmit success and failures keep answers');
calls = []; pend = [];
const pf = submitAnswer('s', body); pend.shift().rej(new Error('net'));
const rf = await pf;
assert.equal(rf.ok, false);
const pj = submitAnswer('s', body); pend.shift().res({ ok: false, status: 500, json: async () => { throw new SyntaxError('x'); } });
assert.equal((await pj).ok, false);
assert.match(afterSubmit(typed, rf).error, /Could not reach|error|failed/i);
out('submitAnswer network/non-JSON errors resolve ok:false');

const L = { owner: 'o w', repo: 'r', issue: 5 };
assert.equal(runHash({ link: L }), '#/run/' + encodeURIComponent('o w') + '/r/5');
for (const bad of [{}, null, { link: { owner: 'o', repo: 'r', issue: 0 } }, { link: { owner: 'o', repo: 'r', issue: 1.5 } },
  { link: { owner: 'o', repo: 'r', issue: '5' } }, { link: { owner: 'o' } }]) assert.equal(runHash(bad), '#/sessions');
out('runHash');

const gate = { questions: [{ options: [{ label: 'Approve plan (Recommended)' }, { label: 'Revise' }] }] };
const g2a = { questions: [{ options: [{ label: 'Confirmed, continue' }, { label: 'Revise' }] }] };
const sess = (c) => ({ command: c, link: { owner: 'o', repo: 'r', issue: 7 } });
assert.deepEqual({ ...planRun(sess('/run-issue 7'), gate) }, { owner: 'o', repo: 'r', n: 7 });
assert.deepEqual({ ...planRun(sess('/ai-workflow:run-issue 7'), gate) }, { owner: 'o', repo: 'r', n: 7 });
assert.equal(planRun(sess('/run-issue 7'), g2a), null);
assert.equal(planRun(sess('/other 7'), gate), null);
assert.equal(planRun({ command: '/run-issue 7' }, gate), null);
assert.equal(planRun({ command: '/run-issue 7', link: { owner: 'o' } }, gate), null);
out('planRun gate detection');
assert.equal(planText({ plan: 'hello' }), 'hello');
for (const d of [{ plan: null }, { plan: '' }, { plan: 5 }, {}, null, undefined]) assert.equal(planText(d), null);
out('planText');

assert.equal(resumeCommand({ repo: '/tmp/x', session_id: 'abc' }), "cd '/tmp/x' && claude --resume 'abc'");
assert.equal(resumeCommand({ repo: "/tmp/it's", session_id: 'abc' }), "cd '/tmp/it'\\''s' && claude --resume 'abc'");
assert.equal(resumeCommand({ repo: '/tmp/x', session_id: "a'b" }), "cd '/tmp/x' && claude --resume 'a'\\''b'");
assert.equal(resumeCommand({ repo: '/tmp/x' }), null);
out('resumeCommand quoting');
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
    assert set(specs) <= {"./vendor/preact.mjs", "./vendor/htm.mjs", "./board.js", "./run.js", "./history.js", "./answer.js", "./notify.js", "./launcher.js"}, specs
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
const { cardTitle, runHref, matchSession, cardChips, formatCost, filterColumns, repoOptions, boardChanged, stationLabel, visibleCards, boardSummary, DONE_LIMIT, flipDeltas } = B;
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
assert.deepEqual(cardChips({ ...card, escalated: true }, 'dev', null), ['escalated']);
assert.deepEqual(cardChips({ ...card, escalated: true }, 'dev', S('a', 'b', 1, 'waiting')), ['waiting']);
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

assert.equal(stationLabel('researcher'), 'Research'); assert.equal(stationLabel('sdet'), 'SDET'); assert.equal(stationLabel('nope'), 'nope');
out('stationLabel');

const many = { key: 'done', cards: Array.from({ length: 25 }, (_, i) => ({ issue: i })) };
assert.equal(visibleCards(many, false).length, DONE_LIMIT);
assert.equal(visibleCards(many, true).length, 25);
assert.equal(visibleCards({ ...many, key: 'dev' }, false).length, 25);
out('visibleCards collapses only the done column');

const day = new Date('2026-10-07T12:00:00');
const sum = boardSummary(
  [{ key: 'dev', cards: [{ owner: 'a', repo: 'b', issue: 1 }, { owner: 'a', repo: 'b', issue: 2, escalated: true }] },
   { key: 'done', cards: [{ owner: 'a', repo: 'b', issue: 3, escalated: true }] }],
  [S('a', 'b', 1, 'running', { cost: 1.5, started_at: '2026-10-07T09:00:00' }), S('x', 'y', 9, 'done', { cost: 2, started_at: '2026-10-06T09:00:00' })],
  day,
);
assert.deepEqual(sum, { live: 1, waiting: 1, today: 1.5 });
assert.deepEqual(boardSummary([], null, day), { live: 0, waiting: 0, today: 0 });
out('boardSummary');

const rect = (x, y) => ({ x, y });
assert.deepEqual(
  flipDeltas(new Map([['a', rect(0, 0)], ['b', rect(10, 10)], ['gone', rect(1, 1)]]), new Map([['a', rect(0, 0.5)], ['b', rect(110, 40)], ['new', rect(5, 5)]])),
  [['b', -100, -30]],
);
out('flipDeltas only reports cards that moved and still exist');

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
    assert specs and set(specs) <= {"./vendor/preact.mjs", "./vendor/htm.mjs", "./app.js", "./fmt.js"}, specs
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
        "const d=[{id:process.env.SID,waiting:true}];const w=A.waitingInfo(d);"
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


def answer_checks():
    import subprocess

    s, r, _ = req(port, "/static/answer.js")
    assert s == 200 and r.getheader("Content-Type", "").startswith("text/javascript"), ("answer.js", s)
    ok("answer.js served as text/javascript")

    js = read(os.path.join(STATIC, "answer.js")).decode()
    app = read(os.path.join(STATIC, "app.js")).decode()
    css = read(os.path.join(STATIC, "app.css")).decode()
    specs = re.findall(r"""(?:^|\n)\s*import\b[^'"]*?from\s*['"]([^'"]+)['"]""", js)
    assert specs and set(specs) <= {"./vendor/preact.mjs", "./vendor/htm.mjs"}, specs
    pre = read(os.path.join(VENDOR, "preact.mjs")).decode()
    exports = re.search(r"export\s*\{([^}]*)\}", pre).group(1)
    names = {x.split(" as ")[-1].strip() for x in exports.split(",")}
    for m in re.finditer(r"import\s*\{([^}]*)\}\s*from\s*['\"]\./vendor/preact\.mjs", js):
        for n in m.group(1).split(","):
            assert n.strip().split(" as ")[0].strip() in names, n
    ok("answer.js imports only vendored modules, real names")

    assert re.search(r"import\s*\{[^}]*\bAnswer\b[^}]*\}\s*from\s*['\"]\./answer\.js['\"]", app), "app.js imports Answer"
    assert re.search(r"<\$\{Answer\}\s+session=\$\{route\.params\.session\}", app), "answer route renders Answer"
    ok("app.js imports and renders Answer")

    for bad in ("innerHTML", "dangerouslySetInnerHTML", "outerHTML", "insertAdjacentHTML",
                "http://", "https://", "console.log", "debugger"):
        assert bad not in js, bad
    ok("answer.js security/hygiene")

    for tok in ("<fieldset", "<legend", 'role="alert"', 'role="status"', 'maxlength="4000"', "<pre",
                "Session not found", "#/sessions", "Continue in terminal", "Copy failed", "disabled"):
        assert tok in js, tok
    assert "/api/sessions/" in js and "/api/runs/" in js
    ok("answer.js markup: fieldset/legend/alert/status/maxlength/pre/not-found/copy/disabled")

    def block(sel):
        m = re.search(re.escape(sel) + r"[^{]*\{([^}]*)\}", css)
        assert m, sel
        return m.group(1)
    for sel in (".opt", "button"):
        mh = re.search(r"min-height\s*:\s*(\d+)px", block(sel))
        assert mh and int(mh.group(1)) >= 44, sel
    plan = block("pre.plan")
    assert "pre-wrap" in plan and re.search(r"overflow-wrap\s*:\s*anywhere", plan)
    assert re.search(r"width\s*:\s*100%", block("textarea"))
    for m in re.finditer(r"(?<![\w-])(?:min-)?width\s*:\s*(\d+)px", css):
        assert int(m.group(1)) <= 390, m.group(0)
    ok("answer css: tap targets, plan wrapping, textarea width, no wide fixed widths")

    if not shutil.which("node"):
        print("note: node not found, skipping answer logic checks")
        return
    env = dict(os.environ, ANSWER_URL=pathlib.Path(os.path.join(STATIC, "answer.js")).as_uri())
    p = subprocess.run(["node", "--input-type=module", "-e", ANSWER_NODE_JS], env=env,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr[-1500:]
    for line in p.stdout.splitlines():
        if line.startswith("ok "):
            ok(line[3:])



NOTIFY_NODE_JS = r"""
const assert = (await import('node:assert')).strict;
const out = (n) => console.log('ok ' + n);
const tick = () => new Promise((r) => setImmediate(r));
// import with no document/Notification/location globals
const N = await import(process.env.NOTIFY_URL);
const { isWaiting, waitingWatcher, notifyState, requestNotify, notifyWaiting, pageTitle } = N;
out('import without browser globals does not throw');
assert.equal(notifyState(), 'unavailable');
assert.equal(await requestNotify(), 'unavailable');
out('no Notification global is unavailable');

const A = await import(process.env.APP_URL);
const { waitingInfo, headerBadge, poll } = A;

assert.equal(pageTitle(3), '(3) aiw');
assert.equal(pageTitle(1), '(1) aiw');
assert.equal(pageTitle(0), 'aiw');
out('pageTitle');

const W = (id, round = 'r1') => ({ id, waiting: true, outcome: 'waiting', pending_question: { id: round } });
const R = (id) => ({ id, waiting: false, outcome: 'running' });
const pub = [R('a'), W('b'), R('c'), W('d')];
assert.deepEqual({ ...waitingInfo(pub) }, { count: 2, firstId: 'b' });
assert.deepEqual({ ...headerBadge(false, pub) }, { kind: 'waiting', count: 2, href: '#/answer/b' });
out('badge counts _public()-shaped waiting sessions');
for (const bad of [{ id: 'x', status: 'waiting' }, { id: 'x', waiting: 'true' }, { id: 'x', waiting: 1 }])
  assert.equal(waitingInfo([bad]).count, 0);
assert.equal(isWaiting(W('a')), true);
assert.equal(isWaiting(null), false);
out('badge regression: only waiting === true counts');

const ids = (l) => l.map((s) => s.id);
let w = waitingWatcher();
assert.deepEqual(w([W('a')]), []);
assert.deepEqual(ids(w([W('a'), W('b')])), ['b']);
assert.deepEqual(w([W('a'), W('b')]), []);
out('watcher primes silently, notifies new, not repeats');

w = waitingWatcher(); w([]);
assert.deepEqual(ids(w([W('a'), W('b')])), ['a', 'b']);
out('watcher returns two newly waiting in one poll');

w = waitingWatcher(); w([]);
assert.deepEqual(ids(w([W('a', 'r1')])), ['a']);
assert.deepEqual(w([R('a')]), []);
assert.deepEqual(ids(w([W('a', 'r2')])), ['a']);
out('re-arm: waits, stops, waits new round');
w = waitingWatcher(); w([]);
assert.deepEqual(ids(w([W('a', 'r1')])), ['a']);
assert.deepEqual(ids(w([W('a', 'r2')])), ['a']);
assert.deepEqual(w([W('a', 'r2')]), []);
out('re-arm: stays waiting, round id changes');
w = waitingWatcher(); w([]);
assert.deepEqual(ids(w([W('a', 'r1')])), ['a']);
assert.deepEqual(w([R('a')]), []);
assert.deepEqual(ids(w([W('a', 'r1')])), ['a']);
out('re-arm: stop then same round again');

w = waitingWatcher();
for (const bad of [[], null, undefined]) assert.deepEqual(w(bad), []);
w = waitingWatcher(); w([W('a')]);
assert.deepEqual(w([]), []);
assert.deepEqual(ids(w([W('a')])), ['a']);
out('watcher empty/null input, absent then reappearing');

// Notification mock
let made = [];
const install = (perm, { throwCtor = false, reqResult, reqThrows = false } = {}) => {
  made = [];
  class Mock {
    constructor(title, opts) { if (throwCtor) throw new Error('ctor'); this.title = title; this.opts = opts; this.closed = 0; made.push(this); }
    close() { this.closed++; }
  }
  Mock.permission = perm;
  Mock.reqCalls = 0;
  Mock.requestPermission = async () => { Mock.reqCalls++; if (reqThrows) throw new Error('rej'); if (reqResult) Mock.permission = reqResult; return reqResult ?? perm; };
  globalThis.Notification = Mock;
  return Mock;
};
const loc = { hash: '' };
let focused = 0;
globalThis.location = loc;
globalThis.focus = () => { focused++; };

const sess = { id: 'a b', session_id: 'SESSIONXYZ', command: '/run-issue 124', repo: '/tmp/myrepo',
  pending_question: { id: 'r1', questions: [{ question: 'SECRETQ?', options: [{ label: 'SECRETOPT' }] }] } };
install('granted');
const nn = notifyWaiting(sess);
assert.ok(nn, 'returns the notification');
assert.equal(made.length, 1);
const txt = String(made[0].title) + ' ' + String(made[0].opts && made[0].opts.body);
assert.equal(String(made[0].opts.body), '/run-issue \u00b7 myrepo');
for (const leak of ['SECRETQ', 'SECRETOPT', 'SESSIONXYZ']) assert.ok(!txt.includes(leak), leak);
out('granted: one notification with command and repo only');
assert.equal(made[0].opts.tag, 'aiw-a b-r1');
notifyWaiting({ ...sess, pending_question: { ...sess.pending_question, id: 'r2' } });
assert.equal(made.at(-1).opts.tag, 'aiw-a b-r2');
assert.notEqual(made.at(-1).opts.tag, made[0].opts.tag);
out('tag includes round id: new round gives a different tag');
notifyWaiting({ id: 'p', command: '/prd secret idea here', repo: '/Users/me/private/deep/proj',
  pending_question: { id: 'rp', questions: [{ question: 'Q?' }] } });
const pv = made.at(-1);
const ptxt = String(pv.title) + ' ' + String(pv.opts.body);
assert.equal(String(pv.opts.body), '/prd \u00b7 proj');
for (const leak of ['secret', 'idea', 'here', '/Users', 'private']) assert.ok(!ptxt.includes(leak), leak);
out('privacy: free-text args and absolute path never reach the body');
made[0].onclick();
assert.equal(loc.hash, '#/answer/' + encodeURIComponent('a b'));
assert.equal(focused, 1);
assert.equal(made[0].closed, 1);
out('click: sets hash, focuses, closes');

notifyWaiting({ id: 'z', pending_question: { id: 'r', questions: [{ question: 'SECRETQ?' }] } });
const fb = made.at(-1);
const ftxt = String(fb.title) + ' ' + String(fb.opts.body);
assert.ok(!/undefined|null|SECRETQ/.test(ftxt), ftxt);
assert.ok(String(fb.opts.body).length > 0);
out('missing command/repo uses fixed fallbacks');

for (const p of ['default', 'denied']) {
  install(p);
  assert.equal(notifyWaiting(sess), null);
  assert.equal(made.length, 0);
  assert.equal(notifyState(), p);
}
out('default/denied: notifyWaiting returns null, no constructor');

const M1 = install('default', { reqResult: 'granted' });
assert.equal(await requestNotify(), 'granted');
assert.equal(notifyState(), 'granted');
assert.equal(M1.reqCalls, 1);
out('requestNotify resolves granted, notifyState reports it');

install('granted'); globalThis.isSecureContext = false;
assert.equal(notifyState(), 'unavailable');
assert.equal(notifyWaiting(sess), null);
assert.equal(made.length, 0);
const M2 = install('default'); globalThis.isSecureContext = false;
assert.equal(await requestNotify(), 'unavailable');
assert.equal(M2.reqCalls, 0);
globalThis.isSecureContext = true;
assert.equal(notifyState(), 'default');
delete globalThis.isSecureContext;
delete globalThis.Notification;
assert.equal(notifyState(), 'unavailable');
assert.equal(notifyWaiting(sess), null);
out('unavailable on insecure context or missing API');

install('granted', { throwCtor: true });
assert.equal(notifyWaiting(sess), null);
out('constructor throwing returns null');
install('default', { reqThrows: true });
const rs = await requestNotify();
assert.equal(typeof rs, 'string');
out('requestPermission rejection resolves a state string');

// late grant: no notification for already-waiting at first poll
install('default');
w = waitingWatcher();
for (const s of w([W('a')])) notifyWaiting(s);
globalThis.Notification.permission = 'granted';
for (const s of w([W('a')])) notifyWaiting(s);
assert.equal(made.length, 0);
out('already waiting at first poll, granted later: no notification');

// poll keepAlive
const doc = { hidden: false, ls: {}, addEventListener(t, f) { (this.ls[t] ||= []).push(f); },
  removeEventListener(t, f) { this.ls[t] = (this.ls[t] || []).filter((x) => x !== f); } };
const fire = (t) => (doc.ls[t] || []).slice().forEach((f) => f());
globalThis.document = doc;
let timers = [], tid = 0, calls = [], pend = [];
globalThis.setTimeout = (fn, ms) => { const t = { id: ++tid, fn, ms }; timers.push(t); return t.id; };
globalThis.clearTimeout = (id) => { timers = timers.filter((t) => t.id !== id); };
globalThis.fetch = (u) => { calls.push(u); return new Promise((res, rej) => pend.push({ res, rej })); };
const resp = (body) => ({ ok: true, status: 200, json: async () => body });
const stop = poll('/api/sessions', 1000, () => {}, () => true);
pend.shift().res(resp([])); await tick();
assert.equal(timers.length, 1);
doc.hidden = true; fire('visibilitychange');
assert.equal(timers.length, 1, 'hide does not clear with keepAlive');
timers.shift().fn();
assert.equal(calls.length, 2);
pend.shift().res(resp([])); await tick();
assert.equal(timers.length, 1, 'keeps scheduling while hidden');
stop();
assert.equal(timers.length, 0);
out('poll keepAlive keeps polling while hidden');
"""


def notify_checks():
    import subprocess

    s, r, _ = req(port, "/static/notify.js")
    assert s == 200 and r.getheader("Content-Type", "").startswith("text/javascript"), ("notify.js", s)
    ok("notify.js served as text/javascript")

    js = read(os.path.join(STATIC, "notify.js")).decode()
    app = read(os.path.join(STATIC, "app.js")).decode()
    specs = re.findall(r"""(?:^|\n)\s*import\b[^'"]*?from\s*['"]([^'"]+)['"]""", js)
    assert all(x.startswith("./") for x in specs), specs
    assert re.search(r"""from\s*['"]\./notify\.js['"]""", app), "app.js imports notify.js"
    ok("app.js imports notify.js, notify.js imports only relative modules")

    for bad in ("innerHTML", "console.log", "debugger", "http://", "https://"):
        assert bad not in js, bad
    assert not re.search(r"\.(questions|question|options)\b", js), "must not read question text"
    assert not re.search(r"pending_question\??\.(?!id\b)", js), "only the round id may be read"
    ok("notify.js hygiene")

    assert re.search(r"document\.title\s*=", app), "app.js sets document.title"
    assert re.search(r'<button[^>]*type="button"[^>]*aria-label="Enable notifications"', app), "labelled Enable button"
    assert re.search(r"""notif\s*===\s*['"]default['"]""", app), "button gated on default state"
    ok("app.js sets title and gates a labelled Enable notifications button")

    if not shutil.which("node"):
        print("note: node not found, skipping notify logic checks")
        return
    env = dict(os.environ, NOTIFY_URL=pathlib.Path(os.path.join(STATIC, "notify.js")).as_uri(),
               APP_URL=pathlib.Path(os.path.join(STATIC, "app.js")).as_uri())
    p = subprocess.run(["node", "--input-type=module", "-e", NOTIFY_NODE_JS], env=env,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr[-1500:]
    for line in p.stdout.splitlines():
        if line.startswith("ok "):
            ok(line[3:])


if NOTIFY:
    try:
        notify_checks()
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{passed} checks passed")
    sys.exit(0)


if ANSWER:
    try:
        answer_checks()
    finally:
        srv.shutdown()
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

HISTORY_JS = r"""
const H = await import(process.env.HISTORY_URL);
const { h } = await import(process.env.PREACT_URL);
const assert = (await import('node:assert')).strict;
const out = (n) => console.log('ok ' + n);
const tick = () => new Promise((r) => setImmediate(r));
out('import without document does not throw');

const { rowOutcome, rowAction, transcriptHref, sessionHref, filterSessions, fmtCost, fmtTime, resumeSession, History } = H;
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
  assert.equal(transcriptHref(S({ id: 'x y', link: l })), '#/session/x%20y');
}
assert.equal(sessionHref(S({ id: 'a/b' })), '#/session/a%2Fb');
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
assert.match(fmtTime('2020-01-02T03:04:05Z'), /2020/);
assert.match(fmtTime(new Date().toISOString()), /^Today \d\d:\d\d$/);
assert.equal(fmtTime('not-a-date'), 'not-a-date'); assert.equal(fmtTime(null), '—');
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
assert.ok(t.includes('#/session/s1'), 'Transcript links to the in-app viewer');
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
    assert specs and set(specs) <= {"./vendor/preact.mjs", "./vendor/htm.mjs", "./fmt.js"}, specs
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
