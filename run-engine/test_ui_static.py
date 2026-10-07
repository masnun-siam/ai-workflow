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
ANSWER = sys.argv[1:3] == ["--view", "answer"]
NOTIFY = sys.argv[1:3] == ["--view", "notify"]

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
    assert set(specs) <= {"./vendor/preact.mjs", "./vendor/htm.mjs", "./answer.js", "./notify.js"}, specs
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
    assert re.search(r"""<button[^>]*type="button"[^>]*>\s*Enable notifications""", app), "labelled Enable button"
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
