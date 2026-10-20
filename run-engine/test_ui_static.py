#!/usr/bin/env python3
"""Self-check for static serving in run-engine/ui_server.py (issue #109).
`python3 test_ui_static.py` — exit 0 = green. Assert-based, like test_ui_server.py.
"""

from __future__ import annotations

import http.client
import json
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

import ui_server  # noqa: E402

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
assert.equal(nm('#/'), 'planning');
const ans = parseRoute('#/answer/abc123');
assert.equal(ans.name, 'answer');
assert.equal(ans.params.session, 'abc123');
assert.equal(nm('#/new'), 'new');
assert.equal(nm('#/settings'), 'settings');
assert.equal(nm('#/sessions'), 'sessions');
out('parseRoute normal routes');

assert.equal(nm(''), 'planning');
assert.equal(nm('#'), 'planning');
out('parseRoute empty hash is planning');

for (const h of ['#/run/acme/web/42', '#/flow', '#/flow/x', '#/dispatch', '#/dispatch/p-20261007120000-aaaaaa', '#/board',
  '#/answer/', '#/bogus']) assert.equal(nm(h), 'notfound', h);
out('parseRoute removed pages and boundary routes are notfound');

{
  const C = await import(process.env.APP_URL.replace('app.js', 'cleanup.js'));
  const ci = [{ key: 'a', label: '/x', repo: 'o/r', flags: [] }, { key: 'b', label: '/x', repo: 'o/r', flags: ['dirty'] },
    { key: 'c', label: '/x', repo: 'o/s', flags: [] }, { key: 'd', label: 'x', flags: [] }];
  assert.deepEqual(C.groupByRepo(ci).map(([r, g]) => [r, g.length]), [['o/r', 2], ['o/s', 1], ['Other', 1]]);
  assert.deepEqual([...C.quickPick(ci, 'safe')], ['a', 'c', 'd']); assert.equal(C.quickPick(ci, 'none').size, 0);
  for (const k of ['safe', 'none']) assert.ok(!C.quickPick(ci, k).has('b'), `${k} never ticks unsaved work`);
  out('cleanup: grouped by repo; safe/none quick picks never tick unsaved work');
}

assert.equal(nm('#/sessions/'), 'sessions');
assert.equal(parseRoute('#/answer/a%20b').params.session, 'a b');
assert.deepEqual({ ...parseRoute('#/session/x%20y') }, { name: 'session', params: { id: 'x y' } });
assert.equal(nm('#/session/'), 'notfound'); assert.equal(nm('#/session/a/b'), 'notfound');
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
const { mergeStream, mdToHtml } = await import(process.env.MD_URL);
const assert = (await import('node:assert')).strict;
const out = (n) => console.log('ok ' + n);
const { viewMode, displayLabel, initialAnswers, toggle, buildBody, startSubmit, afterSubmit,
  submitAnswer, doneHash, resumeCommand, processLive } = A;
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

assert.equal(processLive(waiting), true);
assert.equal(processLive({ ...waiting, ended_at: '2026-10-14T00:00:00Z' }), false);
assert.equal(processLive({ outcome: 'running' }), false);
assert.equal(processLive(null), false);
out('processLive: waiting with no ended_at blocks submit');

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

assert.equal(doneHash({ id: 's 2' }), '#/session/s%202');
assert.equal(doneHash(undefined), '#/sessions');
out('doneHash: the session itself, else the list');

assert.equal(resumeCommand({ repo: '/tmp/x', session_id: 'abc' }), "cd '/tmp/x' && claude --resume 'abc'");
assert.equal(resumeCommand({ repo: "/tmp/it's", session_id: 'abc' }), "cd '/tmp/it'\\''s' && claude --resume 'abc'");
assert.equal(resumeCommand({ repo: '/tmp/x', session_id: "a'b" }), "cd '/tmp/x' && claude --resume 'a'\\''b'");
assert.equal(resumeCommand({ repo: '/tmp/x' }), null);
out('resumeCommand quoting');

// ---- mergeStream
const mst0 = { events: [], offset: 0 };
const me1 = { kind: 'text', text: 'a' }, me2 = { kind: 'text', text: 'b' };
let mst = mergeStream(mst0, { events: [me1], offset: 10 });
assert.equal(mst.offset, 10); assert.deepEqual(mst.events, [me1]);
mst = mergeStream(mst, { events: [me2], offset: 20 });
assert.deepEqual(mst.events, [me1, me2]); assert.equal(mst.offset, 20);
mst = mergeStream(mst, { events: [], offset: 25 });
assert.deepEqual(mst.events, [me1, me2]); assert.equal(mst.offset, 25);
out('mergeStream appends and advances offset');
const mdup = mergeStream(mst, { events: [me1, me2], offset: 25 });
assert.deepEqual(mdup.events, [me1, me2]); assert.equal(mdup.offset, 25);
const mold = mergeStream(mst, { events: [me1], offset: 5 });
assert.deepEqual(mold.events, [me1, me2]); assert.equal(mold.offset, 25);
out('mergeStream drops stale or duplicate responses');
// ---- mdToHtml
let mh = mdToHtml('# Title\n\nsome **bold** and `code`\n\n- a\n- b\n\n1. one\n2. two\n\n```\n# not heading\n**raw**\n```');
assert.match(mh, /<h1>Title<\/h1>/); assert.match(mh, /<strong>bold<\/strong>/); assert.match(mh, /<code>code<\/code>/);
assert.match(mh, /<ul>\s*<li>a<\/li>\s*<li>b<\/li>\s*<\/ul>/); assert.match(mh, /<ol>\s*<li>one<\/li>\s*<li>two<\/li>\s*<\/ol>/);
assert.match(mh, /<p>some /); assert.match(mh, /<pre>[\s\S]*# not heading[\s\S]*\*\*raw\*\*[\s\S]*<\/pre>/);
assert.doesNotMatch(mh, /<h1>not heading/); assert.doesNotMatch(mh, /<strong>raw/);
out('mdToHtml renders blocks and inline');
for (const bad of ['<img src=x onerror=alert(1)>', '<script>alert(1)</script>', '"><svg onload=alert(1)>', '[x](javascript:alert(1))', "a & b 'q'"]) {
  const r = mdToHtml(bad);
  assert.doesNotMatch(r, /<(img|script|svg)/i, bad); assert.doesNotMatch(r, /<a[\s>]/i); assert.doesNotMatch(r, /href/i);
  assert.doesNotMatch(r, /<[a-z]+[^>]*\s(on\w+|src)=/i, bad);
}
assert.match(mdToHtml('a & <b> "q" \'s\''), /a &amp; &lt;b&gt; &quot;q&quot; &#0?39;s&#0?39;|a &amp; &lt;b&gt; &quot;q&quot; &#x27;s&#x27;/);
assert.equal(mdToHtml(''), ''); assert.equal(mdToHtml(null), '');
out('mdToHtml escapes hostile input; empty is empty');
assert.equal(mdToHtml('**Next:**\n- a\n- b'), '<p><strong>Next:</strong></p>\n<ul>\n<li>a</li>\n<li>b</li>\n</ul>');
out('mdToHtml: a list straight under a paragraph line renders after it');
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

    s, r, body = req(port, "/sw.js")
    assert (
        s == 200 and r.getheader("Content-Type").startswith("text/javascript") and b"addEventListener('fetch'" in body
    )
    s, r, body = req(port, "/static/manifest.webmanifest")
    assert s == 200 and r.getheader("Content-Type").startswith("application/manifest+json")
    man = json.loads(body)
    assert man["display"] == "standalone" and man["start_url"] == "/" and man["scope"] == "/"
    sizes = {i["sizes"] for i in man["icons"]}
    assert {"192x192", "512x512"} <= sizes and any(i["purpose"] == "maskable" for i in man["icons"])
    for i in man["icons"]:
        assert req(port, i["src"])[0] == 200, i["src"]
    assert 'rel="manifest"' in index and "serviceWorker.register('/sw.js')" in index
    ok("PWA: root service worker, manifest MIME, installable icons served")

    for name, t in (("app.js", "text/javascript"), ("app.css", "text/css")):
        s, r, _ = req(port, f"/static/{name}")
        assert s == 200 and r.getheader("Content-Type", "").startswith(t), (name, s)
    ok("app.js/app.css served with correct types")

    js = read(os.path.join(STATIC, "app.js")).decode()
    css = read(os.path.join(STATIC, "app.css")).decode()
    specs = re.findall(r"""(?:^|\n)\s*import\b[^'"]*?from\s*['"]([^'"]+)['"]""", js)
    assert specs, "no imports found"
    assert set(specs) <= {
        "./vendor/preact.mjs",
        "./vendor/htm.mjs",
        "./history.js",
        "./answer.js",
        "./notify.js",
        "./launcher.js",
        "./session.js",
        "./keys.js",
        "./toast.js",
        "./settings.js",
        "./planning.js",
        "./delivery.js",
        "./fmt.js",
        "./cleanup.js",
        "./issue.js",
        "./pr.js",
        "./afk.js",
        "./usage.js",
    }, specs
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
    for m in re.finditer(r"(?<![\w(-])(?:min-)?width\s*:\s*(\d+)px", css):
        assert int(m.group(1)) <= 390, m.group(0)
    ok("css palette, wrapping header, tap targets, no wide fixed widths")

    assert "/api/sessions" in js
    ok("app.js fetches /api/sessions")

    if not shutil.which("node"):
        print("note: node not found, skipping shell logic checks")
        return
    env = dict(os.environ, APP_URL=pathlib.Path(os.path.join(STATIC, "app.js")).as_uri())
    p = subprocess.run(
        ["node", "--input-type=module", "-e", NODE_JS], env=env, capture_output=True, text=True, timeout=60
    )
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
const { repoOptions, argIssue, repoFromText, validate, buildBody, outcome, sessionHref, loadLastRepo, saveLastRepo, makeSubmitter, Launcher } = L;
out('import without document/localStorage does not throw');
const plain = (x) => JSON.parse(JSON.stringify(x));

// repoOptions
const opts = repoOptions(fix.repos);
assert.equal(opts.length, 1); assert.equal(opts[0].value, 'o/r');
out('repoOptions from real /api/repos body');
const RP = await import(process.env.LAUNCHER_URL.replace('launcher.js', 'repopicker.js'));
{
  const repos = [{ value: 'a/web', name: 'Web App', path: '/p/web' }, { value: 'a/api', name: 'api', path: '/p/api' }, { value: 'b/webhooks', name: 'b/webhooks', path: '/q/hooks' }];
  const vals = (rows) => rows.map((r) => (r.kind === 'repo' ? r.repo.value : r.kind));
  assert.equal(RP.pathOption('  /a/b '), '/a/b'); assert.equal(RP.pathOption('rel/x'), null); assert.equal(RP.pathOption(''), null);
  assert.deepEqual(RP.matchRepos(repos, 'web').map((r) => r.value), ['a/web', 'b/webhooks'], 'name prefix first');
  assert.deepEqual(RP.matchRepos(repos, 'a api').map((r) => r.value), ['a/api'], 'every word');
  assert.deepEqual(RP.matchRepos(repos, 'hooks').map((r) => r.value), ['b/webhooks'], 'path matches');
  assert.deepEqual(vals(RP.pickerRows({ repos, query: '' })), ['a/web', 'a/api', 'b/webhooks']);
  assert.deepEqual(vals(RP.pickerRows({ repos, query: '', recent: ['a/api', 'gone/x'] })), ['a/api', 'a/web', 'b/webhooks'], 'recent first, once, unknown dropped');
  assert.deepEqual(RP.pickerRows({ repos, query: '', recent: ['a/api'] }).map((r) => r.group), ['Recent', 'All repos', 'All repos']);
  assert.deepEqual(vals(RP.pickerRows({ repos, query: 'zzz', recent: ['a/api'] })), [], 'searching hides recents and the all row');
  assert.deepEqual(vals(RP.pickerRows({ repos, query: '', allLabel: 'All repos' })).slice(0, 1), ['all']);
  assert.deepEqual(vals(RP.pickerRows({ repos, query: '/tmp/x', allowPath: true, canBrowse: true })), ['path', 'browse']);
  assert.deepEqual(vals(RP.pickerRows({ repos, query: '/tmp/x' })), [], 'no path or browse rows where the host takes only repos');
  assert.deepEqual(vals(RP.pickerRows({ repos, query: '/p/web', allowPath: true })), ['a/web'], 'a registered path is that repo, not a raw path');
  const mem = new Map(); const st = { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v) };
  for (const s of ['a', 'b', 'c', 'd', 'b', 'e']) RP.pushRecent(st, s);
  assert.deepEqual(RP.loadRecent(st), ['e', 'b', 'd', 'c'], 'most recent first, deduped, capped at 4');
  assert.deepEqual(RP.loadRecent({ getItem: () => 'not json' }), []); assert.deepEqual(RP.loadRecent({ getItem: () => { throw new Error('x'); } }), []);
  assert.deepEqual(vals(RP.pickerRows({ repos, query: '', allowVault: true, allowCreate: true, canBrowse: true })), ['vault', 'a/web', 'a/api', 'b/webhooks', 'create'], 'no repo first, create last');
  assert.deepEqual(vals(RP.pickerRows({ repos, query: 'new', allowVault: true })), ['vault'], 'typing "new" finds the no-repo row');
  assert.deepEqual(vals(RP.pickerRows({ repos, query: '', allowCreate: true })), ['a/web', 'a/api', 'b/webhooks', 'create'], 'create works without the folder dialog: the folder is typed');
  out('repo picker: search ranking, recent first, all/path/browse rows, recent list persistence');
}
for (const bad of [null, undefined, {}, { repos: 5 }, [], { repos: [{ name: 'x' }, { slug: 'a/b' }, null] }])
  assert.deepEqual(plain(repoOptions(bad)), [], JSON.stringify(bad));
out('repoOptions empty/malformed -> []');

// buildBody
assert.deepEqual(plain(buildBody({ repo: 'o/r', command: 'implement-issue', args: ' 7 ' })), { repo: 'o/r', command: 'implement-issue', args: '7' });
for (const a of ['#12', 'https://github.com/o/r/pull/12'])
  assert.deepEqual(plain(buildBody({ repo: 'o/r', command: 'pr-grind', args: a })), { repo: 'o/r', command: 'pr-grind', args: a, issue: 12 });
out('buildBody trims; pr-grind adds issue');

// repoFromText
{
  const rs = [{ value: 'Blu/bop-bd' }, { value: 'o/r' }];
  assert.equal(repoFromText(rs, 'https://github.com/blu/bop-bd/issues/5978'), 'Blu/bop-bd');
  assert.equal(repoFromText(rs, 'o/r#12'), 'o/r');
  assert.equal(repoFromText(rs, 'https://github.com/x/y/pull/3'), null);
  assert.equal(repoFromText(rs, '42'), null);
}
// argIssue
for (const a of ['7', '#7', 'https://github.com/o/r/issues/7']) assert.equal(argIssue('implement-issue', a), 7, a);
for (const a of ['12', '#12', 'https://github.com/o/r/pull/12']) assert.equal(argIssue('pr-grind', a), 12, a);
out('argIssue accepted forms');
for (const a of ['0', '-1', '7.5', '7x', '', 'abc']) { assert.equal(argIssue('implement-issue', a), null, a); assert.equal(argIssue('pr-grind', a), null, a); }
assert.equal(argIssue('pr-grind', 'https://github.com/o/r/issues/7'), null);
assert.equal(argIssue('implement-issue', 'https://github.com/o/r/pull/7'), null);
out('argIssue boundary -> null');

// outcome / sessionHref
assert.deepEqual(plain(outcome(201, { id: 'x', link: { owner: 'o', repo: 'r', issue: 7 } })), { kind: 'open', href: '#/sessions' });
assert.deepEqual(plain(outcome(201, { id: 'x', link: null })), { kind: 'open', href: '#/sessions' });
out('outcome 201');
assert.equal(sessionHref({ link: { owner: 'a b', repo: 'c/d', issue: 3 } }), '#/sessions');
out('sessionHref always lands on the sessions list');
const o400 = outcome(400, fix.bad_repo);
assert.equal(o400.kind, 'repo'); assert.ok(o400.message.startsWith('not a git repository'), o400.message);
out('outcome 400 not a git repository (real body)');
const o409 = outcome(409, fix.dup);
assert.equal(o409.kind, 'duplicate'); assert.equal(o409.message, fix.dup.error); assert.equal(o409.href, '#/sessions');
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
for (const c of ['implement-issue', 'pr-grind']) for (const a of ['', '   ', '\n']) {
  const e = validate({ repo: 'o/r', command: c, args: a }); assert.ok(e && e.args, `${c} ${JSON.stringify(a)}`);
}
assert.ok(validate({ repo: '', path: '', command: 'implement-issue', args: '7' }).repo);
assert.ok(validate({ repo: '', path: '  ', manual: true, command: 'implement-issue', args: '7' }).repo);
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
const b = { repo: 'o/r', command: 'implement-issue', args: '7' };
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
const base = { repos: opts, repo: 'o/r', manual: false, path: '', command: 'implement-issue', args: '', pending: false, errors: {}, result: null };
const render = (st) => new Launcher({}).render({}, { ...base, ...st });
const nodes = [];
const walk = (n) => { if (n == null || typeof n === 'boolean') return; if (Array.isArray(n)) return n.forEach(walk);
  if (typeof n !== 'object') return; nodes.push(n); walk(n.props && n.props.children); };
const text = (n) => (n == null || typeof n === 'boolean') ? '' : Array.isArray(n) ? n.map(text).join('') : typeof n === 'object' ? text(n.props && n.props.children) : String(n);
const find = (t, root) => { nodes.length = 0; walk(root); return nodes.filter((n) => n.type === t); };
let tree = render({});
assert.equal(find(RP.RepoPicker, tree).length, 1, 'the shared repo picker'); assert.equal(find(RP.RepoPicker, tree)[0].props.allowPath, true);
const radios = find('input', tree).filter((i) => i.props.type === 'radio');
assert.deepEqual(radios.map((r) => r.props.value).sort(), ['create-prd', 'create-tasks', 'day', 'docs-updater', 'dump', 'flow', 'herdr-dispatch', 'implement-issue', 'peer-review', 'pr-grind', 'pr-review', 'refine-issues', 'release-pr', 'sync-from-wasensi', 'verifier-locally', 'worklog']);
const lab = (t) => find('label', render({ command: t })).map((l) => text(l)).join('|');
assert.match(lab('implement-issue'), /issue/i); assert.match(lab('pr-grind'), /PR|pull/i);
assert.notEqual(lab('implement-issue'), lab('pr-grind'));
out('render: repo combobox, seven command radios, command-specific args label');
const fs = find('fieldset', tree); assert.ok(fs.length >= 1); assert.ok(find('legend', fs[0]).length === 1);
tree = render({});
const labelFor = new Set(find('label', tree).map((l) => l.props.htmlFor ?? l.props['for']));
for (const c of [...find('input', tree).filter((i) => i.props.type !== 'radio' && i.props.type !== 'submit'), ...find('select', tree)])
  assert.ok(c.props.id && labelFor.has(c.props.id), 'control without label: ' + c.props.id);
out('render: a11y labels and fieldset/legend');
const noRepos = render({ repos: [], repo: '' });
assert.ok(find(RP.RepoPicker, noRepos).some((p) => p.props.id === 'repo-path' && p.props.allowPath), 'an empty repo list still takes a typed path');
out('render: empty repo list still takes a path in the repo picker');
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
const pathIn = find(RP.RepoPicker, t3)[0];
assert.ok(pathIn && pathIn.props.error, 'the picker gets the error id (it sets aria-invalid and aria-describedby)');
assert.ok(al3.some((n) => n.props.id && n.props.id === pathIn.props.error));
assert.deepEqual(pathIn.props.value, { repo: '', path: '/tmp/x', vault: false });
const trig = new RP.RepoPicker({}).render({ id: 'x', repos: [], value: { repo: '', path: '/tmp/x' }, error: 'repo-error' }, { open: false });
const tb = find('button', trig)[0];
assert.equal(tb.props['aria-invalid'], 'true'); assert.equal(tb.props['aria-describedby'], 'repo-error'); assert.equal(tb.props.id, 'x');
out('render: repo error alert tied to the repo picker');
const t4 = render({ result: { kind: 'duplicate', message: fix.dup.error, href: '#/sessions' } });
const al4 = find('div', t4).concat(find('p', t4)).filter((n) => n.props.role === 'alert');
assert.ok(al4.length);
assert.ok(find('a', al4[0]).some((a) => a.props.href === '#/sessions'));
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
    s, r, bad = call("POST", "/api/sessions", {"repo": plain, "command": "implement-issue", "args": "7"})
    assert s == 400 and bad["error"].startswith("not a git repository"), (s, bad)
    rec = ui_sessions.create("/implement-issue 7", repo, link={"owner": "o", "repo": "r", "issue": 7})
    ui_sessions.update(rec["id"], status="running")
    s, r, dup = call("POST", "/api/sessions", {"repo": "o/r", "command": "implement-issue", "args": "7"})
    assert s == 409 and dup["link"]["issue"] == 7 and dup["id"] == rec["id"], (s, dup)
    ok("real server: /api/repos, 400 non-git, 409 duplicate bodies captured")

    lp = os.path.join(STATIC, "launcher.js")
    assert os.path.exists(lp), "launcher.js missing"
    js = read(lp).decode()
    specs = re.findall(r"""(?:^|\n)\s*import\b[^'"]*?from\s*['"]([^'"]+)['"]""", js)
    assert specs and set(specs) <= {
        "./vendor/preact.mjs",
        "./vendor/htm.mjs",
        "./toast.js",
        "./fmt.js",
        "./repopicker.js",
        "./vault.js",
    }, specs
    assert not re.search(r"console\.log|debugger|https?://", js)
    ok("launcher.js imports only vendored modules, no debug/absolute URLs")
    s, r, _ = req(port, "/static/launcher.js")
    assert s == 200 and r.getheader("Content-Type", "").startswith("text/javascript"), s
    ok("launcher.js served as text/javascript")

    css = read(os.path.join(STATIC, "app.css")).decode()
    for m in re.finditer(r"(?<![\w(-])(?:min-)?width\s*:\s*(\d+)px", css):
        assert int(m.group(1)) <= 390, m.group(0)
    assert re.search(r"(?:input|select|button|textarea)[^{}]*\{[^}]*min-height\s*:\s*(?:4[4-9]|[5-9]\d)px", css), (
        "form controls need min-height >= 44px"
    )
    ok("css: no wide fixed widths, form controls >= 44px")

    if not shutil.which("node"):
        print("note: node not found, skipping launcher logic checks")
        return
    env = dict(
        os.environ,
        LAUNCHER_URL=pathlib.Path(lp).as_uri(),
        LAUNCHER_FIX=json.dumps({"repos": repos, "bad_repo": bad, "dup": dup}),
    )
    p = subprocess.run(
        ["node", "--input-type=module", "-e", LAUNCHER_JS], env=env, capture_output=True, text=True, timeout=60
    )
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
const ALL = ['create-prd', 'create-tasks', 'day', 'docs-updater', 'dump', 'flow', 'herdr-dispatch', 'implement-issue', 'peer-review', 'pr-grind', 'pr-review', 'refine-issues', 'release-pr', 'sync-from-wasensi', 'verifier-locally', 'worklog'];
assert.equal(typeof L.validateCustom, 'function', 'validateCustom export');
assert.equal(typeof L.buildCustomBody, 'function', 'buildCustomBody export');

const base = { repos: [{ value: 'o/r', label: 'o/r' }], repo: 'o/r', manual: false, path: '', command: 'implement-issue', args: '', text: '', pending: false, errors: {}, result: null };
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
for (const c of ALL) assert.ok(!find('legend', render({ command: c })).some((l) => /Options/.test(text(l))), c);
out('one radio per command, no Options fieldset for any command');
const hint = (c) => find('label', render({ command: c })).map((l) => text(l)).join('|');
const hints = ALL.map(hint);
assert.ok(hints.every((h) => h.length > 0)); assert.equal(new Set(hints).size, ALL.length, 'hints pairwise distinct');
assert.match(hint('implement-issue'), /issue/i); assert.match(hint('pr-grind'), /PR|pull/i);
out('per-command hints distinct');

for (const c of ['create-prd', 'dump', 'worklog', 'refine-issues']) {
  const b = plain(buildBody({ repo: 'o/r', command: c, args: '  some text ' }));
  assert.deepEqual(b, { repo: 'o/r', command: c, args: 'some text' }, c);
}
assert.deepEqual(plain(buildBody({ repo: 'o/r', command: 'pr-grind', args: '#12' })), { repo: 'o/r', command: 'pr-grind', args: '#12', issue: 12 });
out('buildBody for new commands has no issue key');
const OPT = ['worklog', 'day', 'verifier-locally', 'docs-updater', 'sync-from-wasensi', 'peer-review', 'release-pr'];
for (const c of OPT) assert.equal(validate({ repo: 'o/r', command: c, args: '' }), null, c);
for (const c of ALL.filter((c) => !OPT.includes(c))) for (const a of ['', '  ', '\n']) {
  const e = validate({ repo: 'o/r', command: c, args: a }); assert.ok(e && e.args, c + JSON.stringify(a));
}
out('worklog, day and the skill-sweep commands take optional args, others required');

tree = render({});
const ta = find('textarea', tree);
assert.equal(ta.length, 1); assert.equal(ta[0].props.id, 'custom');
assert.ok(find('label', tree).some((l) => (l.props.htmlFor ?? l.props['for']) === 'custom'));
assert.ok(find('button', tree).some((b) => text(b).trim() === 'Run in selected repo'));
assert.match(text(tree), /skip-permissions/i);
out('custom box: textarea, label, button, skip-permissions note');
for (const c of ['create-prd', 'dump', 'day']) assert.equal(find('textarea', render({ command: c })).filter((t) => t.props.id === 'args').length, 1, c);
for (const c of ['implement-issue', 'pr-grind', 'worklog']) assert.equal(find('textarea', render({ command: c })).filter((t) => t.props.id === 'args').length, 0, c);
out('free-text commands get a textarea, number/link commands a single line');
{
  const cmds = [{ label: 'Work', cmd: 'claude', builtin: true }, { label: 'Masum', cmd: 'cc masum' }];
  assert.equal(L.limitedUntil(cmds, 'Masum', { 'cc masum': { limited_until: 99 } }), 99);
  assert.equal(L.limitedUntil(cmds, '', { 'cc masum': { limited_until: 99 } }), null);
  const radios = find('button', render({ cmds, claudeLabel: 'Masum' })).filter((b) => b.props.role === 'radio');
  assert.deepEqual(radios.map((b) => [text(b).trim(), b.props['aria-checked']]), [['Work', false], ['Masum', true]]);
  assert.equal(find('button', render({ cmds: cmds.slice(0, 1) })).filter((b) => b.props.role === 'radio').length, 0, 'no switch with one account');
  assert.equal(find('select', render({ cmds })).length, 0);
}
out('Run as: one radio per account, chosen one checked, limited reset lookup');

assert.deepEqual(plain(L.buildCustomBody({ repo: 'o/r', text: '/pr-review 42' })), { repo: 'o/r', text: '/pr-review 42' });
assert.equal(L.buildCustomBody({ repo: 'o/r', text: '  /pr-review 42\n' }).text, '/pr-review 42');
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
const sf = new Launcher({}); sf.state = { ...base, args: '7', text: '/pr-review 42' };
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
async function custom(status, body, text = '/implement-issue 7') {
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
assert.ok(find('a', alerts(render({ result: st.result }))[0]).some((a) => a.props.href === '#/sessions'));
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

    def stub(command_text, cwd, link=None, **_):
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
        s, b = call({"repo": "o/r", "command": "create-prd", "args": "x"})
        assert s == 201 and captured[-1][0] == "/create-prd x", (s, b, captured)
        ok("real server (runner stubbed): custom text verbatim, named create-prd -> '/create-prd x'")
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
        named = ui_sessions.create("/create-prd x", repo)
        ui_sessions.update(named["id"], status="waiting", pending_question={"text": "q?"})
        s, lst = call(None, "GET")
        assert s == 200, s
        items = {i["id"]: i for i in lst["sessions"]}
        assert items[rec["id"]]["waiting"] is True and items[rec["id"]]["command"] == "/pr-fix-comments 42", items[
            rec["id"]
        ]
        assert items[rec["id"]]["waiting"] == items[named["id"]]["waiting"]
        ok("custom-text session surfaced waiting exactly like a named one")
        live = ui_sessions.create("/implement-issue 7", repo, link={"owner": "o", "repo": "r", "issue": 7})
        ui_sessions.update(live["id"], status="running")
        s, dup = call({"repo": "o/r", "command": "implement-issue", "args": "7"})
        assert s == 409 and dup["link"]["issue"] == 7, (s, dup)
        s, lst = call(None, "GET")
        sj = json.dumps(lst)
        assert rec["id"] in sj
    finally:
        ui_runner.start = real_start

    lp = os.path.join(STATIC, "launcher.js")
    assert os.path.exists(lp), "launcher.js missing"
    js = read(lp).decode()
    for name in (
        "implement-issue",
        "verifier-locally",
        "pr-review",
        "docs-updater",
        "sync-from-wasensi",
        "pr-grind",
        "create-prd",
        "refine-issues",
        "dump",
        "worklog",
        "day",
    ):
        assert name in js, name
    for gone in (
        "run-" + "issue",
        "gh-issue",
        "intake",
        "jira-to-gh",
        "pr-fix-comments",
        "issue-to-pr",
        "fix-blockers",
        "autoGrind",
        "<legend>Options",
    ):
        assert gone not in js, gone
    specs = re.findall(r"""(?:^|\n)\s*import\b[^'"]*?from\s*['"]([^'"]+)['"]""", js)
    assert specs and set(specs) <= {
        "./vendor/preact.mjs",
        "./vendor/htm.mjs",
        "./toast.js",
        "./fmt.js",
        "./repopicker.js",
        "./vault.js",
    }, specs
    assert not re.search(r"console\.log|debugger|https?://", js)
    s, r, _ = req(port, "/static/launcher.js")
    assert s == 200 and r.getheader("Content-Type", "").startswith("text/javascript"), s
    ok("launcher.js served, names the kept and imported commands, no removed-command Options, hygiene")

    css = read(os.path.join(STATIC, "app.css")).decode()
    assert re.search(r"textarea[^{}]*\{[^}]*min-height\s*:\s*(?:4[4-9]|[5-9]\d)px", css), "textarea min-height >= 44px"
    assert re.search(r"textarea[^{}]*\{[^}]*font-family\s*:[^;}]*monospace", css), "textarea monospace"
    for m in re.finditer(r"(?<![\w(-])(?:min-)?width\s*:\s*(\d+)px", css):
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
    p = subprocess.run(
        ["node", "--input-type=module", "-e", chk],
        env=dict(os.environ, APP_URL=appjs, SID=rec["id"]),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert p.returncode == 0, p.stderr[-1500:]
    ok("custom waiting session routes to #/answer/<id>")

    env = dict(
        os.environ, LAUNCHER_URL=pathlib.Path(lp).as_uri(), LAUNCHER_FIX=json.dumps({"bad_repo": bad, "dup": dup})
    )
    p = subprocess.run(
        ["node", "--input-type=module", "-e", LAUNCHER_ALL_JS], env=env, capture_output=True, text=True, timeout=60
    )
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
    assert specs and set(specs) <= {"./vendor/preact.mjs", "./vendor/htm.mjs", "./toast.js"}, specs
    pre = read(os.path.join(VENDOR, "preact.mjs")).decode()
    exports = re.search(r"export\s*\{([^}]*)\}", pre).group(1)
    names = {x.split(" as ")[-1].strip() for x in exports.split(",")}
    for m in re.finditer(r"import\s*\{([^}]*)\}\s*from\s*['\"]\./vendor/preact\.mjs", js):
        for n in m.group(1).split(","):
            assert n.strip().split(" as ")[0].strip() in names, n
    ok("answer.js imports only vendored modules, real names")

    assert re.search(r"import\s*\{[^}]*\bAnswer\b[^}]*\}\s*from\s*['\"]\./answer\.js['\"]", app), (
        "app.js imports Answer"
    )
    assert re.search(r"<\$\{Answer\}\s+session=\$\{route\.params\.session\}", app), "answer route renders Answer"
    ok("app.js imports and renders Answer")

    assert "dangerouslySetInnerHTML" not in js
    for bad in ("outerHTML", "insertAdjacentHTML", "http://", "https://", "console.log", "debugger"):
        assert bad not in js, bad
    ok("answer.js security/hygiene")

    for tok in (
        "<fieldset",
        "<legend",
        'role="alert"',
        'role="status"',
        'maxlength="4000"',
        "Session not found",
        "#/sessions",
        "Continue in terminal",
        "Copy failed",
        "disabled",
    ):
        assert tok in js, tok
    assert "/api/sessions/" in js and "/api/runs/" not in js
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
    for m in re.finditer(r"(?<![\w(-])(?:min-)?width\s*:\s*(\d+)px", css):
        assert int(m.group(1)) <= 390, m.group(0)
    ok("answer css: tap targets, plan wrapping, textarea width, no wide fixed widths")

    if not shutil.which("node"):
        print("note: node not found, skipping answer logic checks")
        return
    env = dict(
        os.environ,
        ANSWER_URL=pathlib.Path(os.path.join(STATIC, "answer.js")).as_uri(),
        MD_URL=pathlib.Path(os.path.join(STATIC, "md.js")).as_uri(),
    )
    p = subprocess.run(
        ["node", "--input-type=module", "-e", ANSWER_NODE_JS], env=env, capture_output=True, text=True, timeout=60
    )
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

const sess = { id: 'a b', session_id: 'SESSIONXYZ', command: '/implement-issue 124', repo: '/tmp/myrepo',
  pending_question: { id: 'r1', questions: [{ question: 'SECRETQ?', options: [{ label: 'SECRETOPT' }] }] } };
install('granted');
const nn = notifyWaiting(sess);
assert.ok(nn, 'returns the notification');
assert.equal(made.length, 1);
const txt = String(made[0].title) + ' ' + String(made[0].opts && made[0].opts.body);
assert.equal(String(made[0].opts.body), '/implement-issue \u00b7 myrepo');
for (const leak of ['SECRETQ', 'SECRETOPT', 'SESSIONXYZ']) assert.ok(!txt.includes(leak), leak);
out('granted: one notification with command and repo only');
assert.equal(made[0].opts.tag, 'aiw-a b-r1');
notifyWaiting({ ...sess, pending_question: { ...sess.pending_question, id: 'r2' } });
assert.equal(made.at(-1).opts.tag, 'aiw-a b-r2');
assert.notEqual(made.at(-1).opts.tag, made[0].opts.tag);
out('tag includes round id: new round gives a different tag');
notifyWaiting({ id: 'p', command: '/create-prd secret idea here', repo: '/Users/me/private/deep/proj',
  pending_question: { id: 'rp', questions: [{ question: 'Q?' }] } });
const pv = made.at(-1);
const ptxt = String(pv.title) + ' ' + String(pv.opts.body);
assert.equal(String(pv.opts.body), '/create-prd \u00b7 proj');
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
    env = dict(
        os.environ,
        NOTIFY_URL=pathlib.Path(os.path.join(STATIC, "notify.js")).as_uri(),
        APP_URL=pathlib.Path(os.path.join(STATIC, "app.js")).as_uri(),
    )
    p = subprocess.run(
        ["node", "--input-type=module", "-e", NOTIFY_NODE_JS], env=env, capture_output=True, text=True, timeout=60
    )
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
  assert.equal(a.label, 'Open'); assert.equal(a.href, '#/session/s1');
}
assert.deepEqual(rowAction(S({ outcome: 'done' })), { kind: 'link', label: 'Open', href: '#/session/s1' });
assert.equal(rowAction(S({ outcome: 'weird' })), null);
assert.equal(rowAction(S({ outcome: undefined })), null);
out('rowAction mapping');

assert.equal(transcriptHref(S({ link })), '#/session/s1');
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
assert.equal(H.cmdLabel({ command: '/pr-grind https://x.slack.com/a', link: { issue: 7 } }), 'pr-grind round #7');
assert.equal(H.cmdLabel({ command: '/implement-issue 7', link: { issue: 7 } }), '/implement-issue 7');
out('cmdLabel shortens grind commands and names the issue');

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
const btn = () => find(render(SL), (n) => n.tag === 'button' && n.props.class !== 'btn')[0];
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
    assert specs and set(specs) <= {
        "./vendor/preact.mjs",
        "./vendor/htm.mjs",
        "./fmt.js",
        "./toast.js",
        "./cleanup.js",
    }, specs
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
    assert heads == ["Command", "Repo", "Started", "Ended", "Outcome", "Cost", "Tokens", "Action"], heads
    assert "<select" in js and "<label" in js
    ok("table markup: 7 scoped headers, labelled outcome select")

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
    assert any(
        all(
            re.search(p, b)
            for p in (r"white-space\s*:\s*nowrap", r"overflow\s*:\s*hidden", r"text-overflow\s*:\s*ellipsis")
        )
        for b in cmd
    ), "cmd truncation css"
    assert any("table-wrap" in sel and re.search(r"overflow-x\s*:\s*auto", b) for sel, b in blocks), (
        "table-wrap overflow-x"
    )
    assert any("history" in sel and re.search(r"min-width\s*:\s*[\d.]+(rem|ch)", b) for sel, b in blocks), (
        "table min-width in rem/ch"
    )
    tap = [b for sel, b in blocks if "history" in sel and re.search(r"\b(a|button|summary)\b", sel)]
    assert any(re.search(r"min-height\s*:\s*44px", b) for b in tap), "44px tap targets"
    assert any("select" in sel and re.search(r"min-height\s*:\s*44px", b) for sel, b in blocks), "select 44px"
    for m in re.finditer(r"(?<![\w(-])(?:min-)?width\s*:\s*(\d+)px", css):
        assert int(m.group(1)) <= 390, m.group(0)
    ok("css: truncation, scroll wrapper, rem min-width, 44px targets")

    if not shutil.which("node"):
        print("note: node not found, skipping history logic checks")
        return
    env = dict(
        os.environ,
        HISTORY_URL=pathlib.Path(os.path.join(STATIC, "history.js")).as_uri(),
        PREACT_URL=pathlib.Path(os.path.join(VENDOR, "preact.mjs")).as_uri(),
    )
    p = subprocess.run(
        ["node", "--input-type=module", "-e", HISTORY_JS], env=env, capture_output=True, text=True, timeout=60
    )
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


AFK = sys.argv[1:3] == ["--view", "afk"]

AFK_NODE_JS = r"""
const assert = (await import('node:assert')).strict;
const out = (n) => console.log('ok ' + n);
const { countdownText, untilClock, entryHref, plural, PRESETS } = await import(process.env.AFK_URL);
const { paletteItems } = await import(process.env.KEYS_URL);
assert.equal(countdownText(5025), '1:23:45');
assert.equal(countdownText(725), '12:05');
assert.equal(countdownText(-3), '0:00');
out('countdownText');
const now = new Date(2026, 9, 9, 14, 30);
assert.equal(untilClock('15:00', now), Math.floor(new Date(2026, 9, 9, 15, 0).getTime() / 1000));
assert.equal(untilClock('14:30', now), Math.floor(new Date(2026, 9, 10, 14, 30).getTime() / 1000));
for (const bad of ['', '25:00', '9', 'ab:cd', '12:60']) assert.equal(untilClock(bad, now), null);
out('untilClock rolls to tomorrow and rejects bad input');
assert.equal(entryHref({ link: { owner: 'o', repo: 'r', issue: 7 }, sid: 'x' }), '#/session/x');
assert.equal(entryHref({ link: null, sid: 'a b' }), '#/session/a%20b');
assert.equal(entryHref({}), null);
assert.equal(plural(1, 'decision'), '1 decision');
assert.equal(plural(3, 'decision'), '3 decisions');
assert.deepEqual(PRESETS.map((p) => p[0]), [30, 60, 120, 240]);
out('entryHref, plural, presets');
const off = paletteItems({ board: null, sessions: [], afk: { active: false } }).find((i) => i.id === 'afk');
const on = paletteItems({ board: null, sessions: [], afk: { active: true } }).find((i) => i.id === 'afk');
assert.equal(off.event, 'aiw:afk');
assert.equal(on.event, 'aiw:afk-back');
assert.equal(on.label, "I'm back");
out('palette offers Go AFK or I\'m back');
"""


def afk_checks():
    import subprocess

    css = read(os.path.join(STATIC, "app.css")).decode()
    app = read(os.path.join(STATIC, "app.js")).decode()
    assert "#7ff0dd" not in css.split(":root", 1)[1].split("}", 1)[1], "accent hover goes through --accent-hover"
    afk = css[css.index("html[data-afk] {") :]
    for tok in ("--accent:", "--accent-bg:", "--on-accent:", "--accent-hover:"):
        assert tok in afk.split("}", 1)[0], tok
    ok("AFK theme swaps accent tokens")
    assert "toggleAttribute('data-afk'" in app and "headerBadge(offline, afk?.active ? [] : sessions)" in app
    assert "if (!away) notifyWaiting(s)" in app
    ok("app.js themes on data-afk and mutes the badge and pings while away")
    if not shutil.which("node"):
        print("note: node not found, skipping afk logic checks")
        return
    env = dict(
        os.environ,
        AFK_URL=pathlib.Path(os.path.join(STATIC, "afk.js")).as_uri(),
        KEYS_URL=pathlib.Path(os.path.join(STATIC, "keys.js")).as_uri(),
    )
    p = subprocess.run(
        ["node", "--input-type=module", "-e", AFK_NODE_JS], env=env, capture_output=True, text=True, timeout=60
    )
    assert p.returncode == 0, p.stderr[-1500:]
    for line in p.stdout.splitlines():
        if line.startswith("ok "):
            ok(line[3:])


if AFK:
    afk_checks()
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
        "/static/../route.py",
        "/static/../../etc/passwd",
        "/static/%2e%2e/route.py",
        "/static/%2E%2E/route.py",
        "/static/..%2froute.py",
        "/static/%252e%252e/route.py",
        "/static//etc/passwd",
        "/static/vendor/../../ui_server.py",
    ):
        s, _, body = req(port, p)
        assert s == 404 and b"def " not in body and b"root:" not in body, (p, s)
    ok("traversal variants 404")
    assert req(port, "/static/a%00.js")[0] == 404
    ok("NUL byte 404")

    # guard
    for p, kw in (
        ("/", {"host": "evil.example"}),
        ("/", {"host": ""}),
        ("/static/vendor/preact.mjs", {"origin": "http://evil.example"}),
    ):
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

    # scroll boxes are sized from the room left in the viewport, not from a 100vh guess (#221)
    def css_rules(src):
        """[(media or None, selector, body)] with comments dropped; one @media level deep."""
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
        out = []

        def walk(text, media):
            i = 0
            while i < len(text):
                j = text.find("{", i)
                if j < 0:
                    break
                head, depth, k = text[i:j].strip(), 1, j + 1
                while depth and k < len(text):
                    depth += {"{": 1, "}": -1}.get(text[k], 0)
                    k += 1
                inner = text[j + 1 : k - 1]
                if head.startswith("@media"):
                    walk(inner, re.sub(r"\s+", " ", head[6:].strip()))
                elif not head.startswith("@"):
                    out.append((media, re.sub(r"\s+", " ", head), inner))
                i = k

        walk(src, None)
        return out

    def decl(rules, media, selector):
        got = [b for m, sel, b in rules if m == media and selector in [x.strip() for x in sel.split(",")]]
        assert got, (media, selector)
        return " ".join(got)

    rules = css_rules(read(os.path.join(STATIC, "app.css")).decode())
    # every remaining vh-sized scroll box is an overlay that starts near the top (audited in #221)
    vh_boxes = sorted({sel for m, sel, b in rules if re.search(r"max-height\s*:[^;]*\dvh\b", b)})
    assert vh_boxes == [".dialog", ".dialog.issue"], vh_boxes
    ok("css only audited overlays keep a vh max-height")

    # vendoring
    for name, lic in (("preact", "MIT"), ("htm", "Apache-2.0")):
        src = read(os.path.join(VENDOR, f"{name}.mjs")).decode()
        assert src.startswith(("/*", "//")), name
        head = src[:600]
        assert name in head and lic in head and re.search(r"\d+\.\d+\.\d+", head), name
        assert "sourceMappingURL" not in src, name
    pre = read(os.path.join(VENDOR, "preact.mjs")).decode()
    assert re.search(r"export\s*\{", pre) and all(
        re.search(rf"\bas\s+{n}\b", pre) or re.search(rf"export\s*\{{[^}}]*\b{n}\b", pre)
        for n in ("h", "render", "Component")
    )
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

_la = read(os.path.join(STATIC, "launcher.js")).decode()
assert "id: 'peer-review'" in _la and "id: 'custom-review'" in _la and "/api/peer-review" in _la, "both New run forms"
assert "reviewOffer(command)" in _la and "reviewOffer('custom')" in _la, "offers come from config, keyed by command"
assert "up to ${rounds || 5} rounds, on Opus" in _la and "isn't forced" in _la, "cost and the not-a-gate note, said"
assert "'critical'" not in _la, "no lens is hardcoded in the frontend"
_se = read(os.path.join(STATIC, "session.js")).decode()
assert "meta.peer_review" in _se and "peer review: ${meta.peer_review}" in _se, "a session shows its peer review status"
ok("both New run forms offer the lens picker from /api/peer-review; session shows the post-check")

# The launcher picker and routing checks run in the default mode (so in run_tests.sh and CI); every --view
# block runs too, from the loop at the end of this file.
FLOW_JS = r"""
const assert = (await import('node:assert')).strict;
const out = (n) => console.log('ok ' + n);
const { parseRoute, NAV } = await import(process.env.APP_URL);
assert.deepEqual(NAV.map(([, , label]) => label), ['Planning', 'Delivery', 'Sessions']);
out('NAV: Planning, Delivery, Sessions');
for (const h of ['', '#', '#/']) assert.equal(parseRoute(h).name, 'planning', h);
assert.equal(parseRoute('#/sessions').name, 'sessions');
assert.equal(parseRoute('#/new').name, 'new'); assert.equal(parseRoute('#/settings').name, 'settings');
for (const h of ['#/run/o/r/1', '#/flow/x', '#/flow', '#/dispatch', '#/dispatch/p-20261007120000-aaaaaa', '#/board']) assert.equal(parseRoute(h).name, 'notfound', h);
out('routes: / lands on Planning, /sessions on Sessions; removed pages are not found');
const L = await import(process.env.APP_URL.replace('app.js', 'launcher.js'));
assert.deepEqual(L.buildBody({ repo: 'o/r', command: 'create-prd', args: ' 05-Work/P/F ', lenses: ['critical', 'qa'] }), { repo: 'o/r', command: 'create-prd', args: '05-Work/P/F', peer_review: ['critical', 'qa'] });
assert.deepEqual(L.buildBody({ repo: 'o/r', command: 'create-prd', args: 'x', lenses: null }), { repo: 'o/r', command: 'create-prd', args: 'x' });
assert.deepEqual(L.buildCustomBody({ repo: 'o/r', text: ' fix it ', lenses: ['ux'] }), { repo: 'o/r', text: 'fix it', peer_review: ['ux'] });
assert.deepEqual(L.buildCustomBody({ repo: 'o/r', text: 'fix it' }), { repo: 'o/r', text: 'fix it' });
const OFF = { default: ['critical'], max_rounds: 3, kinds: { dump: ['critical', 'ceo', 'qa'] } };
assert.equal(L.pickedLenses(false, ['qa'], OFF), null, 'review off sends nothing');
assert.deepEqual(L.pickedLenses(true, undefined, OFF), ['critical'], 'ticking review starts with the default');
assert.deepEqual(L.pickedLenses(true, [], OFF), [], 'all unticked: a validation error, never a silent default');
assert.deepEqual(L.toggleLens(['qa'], 'critical', true, OFF.kinds.dump), ['critical', 'qa'], 'config order kept');
assert.deepEqual(L.toggleLens(['critical', 'qa'], 'critical', false, OFF.kinds.dump), ['qa']);
assert.equal(L.lensName('ceo'), 'CEO'); assert.equal(L.lensName('critical'), 'Critical');
assert.deepEqual(L.validateCustom({ repo: 'o/r', text: 'x' }, []), { customLenses: 'Tick at least one reviewer' });
assert.equal(L.validateCustom({ repo: 'o/r', text: 'x' }, ['ux']), null);
assert.equal(L.lensPicker({ id: 'p', offer: null }), null, 'a command with no offer shows no picker');
out('launcher: lens lists in the body (named and custom), default critical, empty is an error, config order');
{
  const it = { number: 12, title: 'Fix login redirect', labels: ['bug'], url: 'https://x/o/r/issues/12' };
  const items = [it, { number: 120, title: 'Export CSV', labels: ['feature'] }, { number: 7, title: 'Docs', labels: [] }];
  assert.equal(L.pickValue('implement-issue', 'o/r', it), '12'); assert.equal(L.pickValue('pr-review', 'o/r', it), '12');
  assert.equal(L.typedNumber('#12'), 12); assert.equal(L.typedNumber('o/r#12'), 12); assert.equal(L.typedNumber(it.url), 12); assert.equal(L.typedNumber('fix'), null);
  const nums = (q) => L.matchItems(items, q).map((x) => x.number);
  assert.deepEqual(nums(''), [12, 120, 7]); assert.deepEqual(nums('12'), [12, 120], 'number prefix');
  assert.deepEqual(nums('login fix'), [12], 'every word in the title'); assert.deepEqual(nums('feature'), [120], 'labels match');
  assert.deepEqual(nums('o/r#12'), [12, 120, 7], 'a filled-in reference keeps the whole list visible');
  assert.deepEqual(L.GROUPS.flatMap(([, c]) => c.map(([n]) => n)).sort(), Object.keys(L.PICK).concat(['pr-grind', 'create-prd', 'refine-issues', 'dump', 'day', 'worklog', 'verifier-locally', 'docs-updater', 'sync-from-wasensi', 'create-tasks', 'herdr-dispatch', 'flow', 'peer-review', 'release-pr']).sort(), 'every command is grouped once');
  assert.equal(L.switchArgs('dump', 'create-prd', 'long idea', 'o/r'), 'long idea', 'free text carries over');
  assert.equal(L.switchArgs('implement-issue', 'pr-review', '12', 'o/r'), '', 'issue to PR clears');
  assert.equal(L.switchArgs('dump', 'implement-issue', 'idea', 'o/r'), '');
  assert.equal(L.switchArgs('implement-issue', 'implement-issue', 'login', 'o/r'), 'login', 'search words stay');
  assert.equal(L.switchArgs('worklog', 'pr-grind', '2026-10-08', 'o/r'), '');
  {
    const W = (o) => L.worklogDates(o, '2026-10-15');
    assert.deepEqual(W({}), { dates: ['today'] }); assert.deepEqual(W({ mode: 'yesterday' }), { dates: ['yesterday'] });
    assert.deepEqual(W({ mode: 'day', day: '2026-10-01' }), { dates: ['2026-10-01'] });
    assert.ok(W({ mode: 'day' }).error && W({ mode: 'day', day: '2026-10-16' }).error, 'missing or future day');
    assert.deepEqual(W({ mode: 'range', from: '2026-09-29', to: '2026-10-02' }).dates, ['2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02'], 'crosses a month end');
    assert.deepEqual(W({ mode: 'range', from: '2026-10-15', to: '2026-10-15' }).dates, ['2026-10-15']);
    assert.ok(W({ mode: 'range', from: '2026-10-05', to: '2026-10-01' }).error, 'reversed');
    assert.ok(W({ mode: 'range', from: '2026-10-01', to: '2026-10-20' }).error, 'future end');
    assert.ok(W({ mode: 'range', from: '2026-08-01', to: '2026-10-15' }).error, 'over the cap');
    assert.equal(W({ mode: 'range', from: '2026-09-15', to: '2026-10-15' }).dates.length, 31, 'exactly the cap is fine');
    assert.ok(W({ mode: 'range', from: '2026-10-01' }).error, 'needs both ends');
    assert.equal(L.isoDay(new Date(2026, 0, 5)), '2026-01-05');
  }
  {
    const V = await import(process.env.APP_URL.replace('app.js', 'vault.js'));
    const fs = [{ project: 'Shop', feature: null }, { project: 'Shop', feature: 'Checkout' }, { project: 'Gym', feature: null }, { project: 'Gym', feature: 'Member Check-ins' }];
    assert.deepEqual(V.keywordSuggest(fs, 'speed up the shop checkout page').map((x) => [x.project, x.feature]), [['Shop', 'Checkout'], ['Shop', null]], 'feature beats its project');
    assert.equal(V.keywordSuggest(fs, 'gym members want check-in reminders')[0].feature, 'Member Check-ins', 'near word forms match');
    assert.deepEqual(V.keywordSuggest(fs, 'the and with'), [], 'stop words alone suggest nothing');
    assert.equal(V.keywordSuggest([...fs, { project: 'Wasensi', feature: null }], 'improve the wasensi checkout with saved addresses')[0].project, 'Wasensi', 'a named project beats a shared feature word');
    assert.equal(V.folderOf({ project: 'Gym', feature: 'Check/ins' }), '05-Work/Gym/Check ins'); assert.equal(V.folderOf({ project: 'Gym' }), '05-Work/Gym');
    assert.equal(V.folderOf({ project: '' }), null); assert.equal(V.folderOf({ project: '..' }), null);
    assert.equal(V.repoName('Gym App: Check-ins!'), 'gym-app-check-ins');
    assert.deepEqual(V.parentFolders([{ path: '/u/P/a' }, { path: '/u/P/b/' }, { path: '/u/Q/c' }, { path: 'rel/x' }, {}]), ['/u/P', '/u/Q'], 'most used first; relative paths skipped');
    assert.ok(L.validate({ vault: true, command: 'dump', args: 'x' }) === null, 'dump runs with no repo');
    assert.match(L.validate({ vault: true, command: 'implement-issue', args: '7' }).repo, /needs a repo/);
    assert.equal(L.validateCustom({ vault: true, text: 'x' }), null);
    assert.deepEqual(L.vaultBody({ vault: true, vf: { project: 'Gym', feature: 'Check-ins' } }), { repo: '', no_repo: true, vault_folder: '05-Work/Gym/Check-ins' });
    assert.deepEqual(L.vaultBody({ vault: true }), { repo: '', no_repo: true }); assert.deepEqual(L.vaultBody({}), {});
    out('no repo yet: keyword folder suggestions, folder names, validation and request body');
  }
  out('launcher picker: fill forms per command, typed number parsing, search by number/words/labels; switching command keeps a compatible argument');
}
"""
if shutil.which("node"):
    import subprocess

    _env = dict(os.environ, APP_URL=pathlib.Path(os.path.join(STATIC, "app.js")).as_uri())
    _p = subprocess.run(
        ["node", "--input-type=module", "-e", FLOW_JS], env=_env, capture_output=True, text=True, timeout=60
    )
    assert _p.returncode == 0, _p.stderr[-2500:]
    for _line in _p.stdout.splitlines():
        if _line.startswith("ok "):
            ok(_line[3:])
else:
    print("note: node not found, skipping flow.js checks")

# Each --view runs in its own process (they each start a server); the plain run, which is what
# run_tests.sh and CI call, must cover them all or they rot unseen.
import subprocess  # noqa: E402

for _view in ("shell", "launcher", "launcher-all", "answer", "notify", "history", "afk"):
    _v = subprocess.run([sys.executable, __file__, "--view", _view], capture_output=True, text=True, timeout=300)
    assert _v.returncode == 0, f"--view {_view} failed:\n{(_v.stdout + _v.stderr)[-2500:]}"
    ok(f"--view {_view}")

print(f"{passed} checks passed")
