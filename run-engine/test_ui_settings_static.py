#!/usr/bin/env python3
"""Settings page per-repo section (task 41).
`python3 run-engine/test_ui_settings_static.py` — exit 0 = green. Node-driven, no server or network.
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
const S = await import(U('settings.js'));
assert.deepEqual({ ...S.repoRow({}, 'o/r') }, { auto_grind: false, autopilot_cap: 2, slack_channel: '' });
assert.equal(S.repoRow({ 'o/r': { autopilot_cap: 4 } }, 'o/r').autopilot_cap, 4);

const puts = []; let reject = null; let getSettings;
globalThis.fetch = async (u, o = {}) => {
  const method = o.method || 'GET';
  if (u === '/api/settings' && method === 'GET') return { ok: true, status: 200, json: async () => getSettings };
  if (u === '/api/repos') return { ok: true, status: 200, json: async () => ({ repos: [{ slug: 'o/a', name: 'a', path: '/p/a' }, { slug: 'o/b', name: 'b', path: '/p/b' }], scan_roots: [] }) };
  if (u === '/api/settings' && method === 'PUT') {
    const body = JSON.parse(o.body); puts.push(body);
    if (reject) return { ok: false, status: 400, json: async () => ({ error: reject }) };
    return { ok: true, status: 200, json: async () => ({ commands: [], default: null, repos: body.repos }) };
  }
  throw new Error('unexpected ' + u);
};
getSettings = { commands: [{ label: 'Claude', cmd: 'claude', builtin: true }], default: 'Claude', vault_dir: '', repos: { 'o/a': { auto_grind: true, autopilot_cap: 3, slack_channel: '#rev' } } };
const s = new S.Settings({});
s.setState = (p, cb) => { s.state = { ...s.state, ...(typeof p === 'function' ? p(s.state) : p) }; cb && cb(); };
await s.componentDidMount(); await tick();
const view = () => s.render({}, s.state);
let t = view();
assert.equal(find('input', t).filter((i) => i.props.type === 'checkbox').length, 2, 'one switch per repo');
const field = (label) => find('input', view()).find((i) => i.props['aria-label'] === label);
assert.equal(field('Auto-grind o/a').props.checked, true); assert.equal(field('Auto-grind o/b').props.checked, false);
assert.equal(field('Autopilot cap o/a').props.value, 3); assert.equal(field('Autopilot cap o/b').props.value, 2, 'default cap 2');
assert.equal(field('Slack channel o/a').props.value, '#rev');
assert.equal(field('Autopilot cap o/a').props.min, '1'); assert.equal(field('Autopilot cap o/a').props.max, '5');
assert.ok(!/Start grinding when a run finishes/.test(text(t)), 'global toggle is gone');
out('settings: each repo shows switch, 1-5 cap and Slack channel with defaults');

await field('Autopilot cap o/b').props.onChange({ target: { value: '1' } });
assert.equal(puts.length, 1); assert.deepEqual(Object.keys(puts[0]), ['repos']); assert.deepEqual(Object.keys(puts[0].repos), ['o/b'], 'only that repo');
assert.equal(puts[0].repos['o/b'].autopilot_cap, 1);
assert.equal(field('Autopilot cap o/b').props.value, 1); assert.equal(field('Autopilot cap o/a').props.value, 3, 'other repo untouched');
await field('Auto-grind o/b').props.onChange({ target: { checked: true } });
assert.equal(puts[1].repos['o/b'].auto_grind, true); assert.equal(puts[1].repos['o/b'].autopilot_cap, 1);
await field('Slack channel o/a').props.onChange({ target: { value: ' #new ' } });
assert.deepEqual(Object.keys(puts[2].repos), ['o/a']); assert.equal(puts[2].repos['o/a'].slack_channel, '#new');
out('settings: a change PUTs only that repo entry');

reject = 'autopilot_cap must be 1-5';
await field('Autopilot cap o/b').props.onChange({ target: { value: '9' } });
assert.equal(field('Autopilot cap o/b').props.value, 1, 'rejected save reverts the field');
assert.match(text(find('p', view()).filter((p) => p.props.role === 'alert')), /1-5/);
reject = null; await field('Auto-grind o/b').props.onChange({ target: { checked: false } });
assert.equal(find('p', view()).filter((p) => p.props.role === 'alert' && /1-5/.test(text(p))).length, 0, 'error cleared by the next change');
out('settings: 400 reverts and shows the error');

// vault and accounts saves no longer carry auto_grind
puts.length = 0;
await s.saveVault({ preventDefault() {} }); await s.save({ preventDefault() {} });
assert.equal(puts.length, 2); for (const p of puts) assert.ok(!('auto_grind' in p), JSON.stringify(p));
out('settings: vault and accounts saves drop auto_grind');
const R = Array.from({ length: 12 }, (_, i) => ({ slug: `o/r${i}`, path: `/p/r${i}` }));
assert.equal(S.visibleRepos(R, '', false).length, S.REPO_PREVIEW); assert.equal(S.visibleRepos(R, '', true).length, 12);
assert.deepEqual(S.visibleRepos(R, 'R11', false).map((r) => r.slug), ['o/r11'], 'search is case-insensitive and ignores the preview cap');
assert.deepEqual(S.visibleRepos(R, '/p/r3', false).map((r) => r.slug), ['o/r3'], 'path matches too');
const f = { server: 'https://ntfy.sh', topic: 't', user: '', public_url: '', token: '', password: '' };
assert.deepEqual(S.notifyBody(f), { server: 'https://ntfy.sh', topic: 't', user: '', public_url: '' }, 'empty secret boxes keep the stored ones');
assert.equal(S.notifyBody({ ...f, token: 'new' }).token, 'new');
assert.equal(S.notifyBody({ ...f, token: 'new', clear_token: true }).token, '', 'clear wins');
out('settings: repo filter with a preview of 8; notify body never sends an empty secret unless clearing');
"""
)


js = read("settings.js")
assert "setAutoGrind" not in js and "auto_grind: this.state" not in js and "autoGrind" not in js
assert not re.search(r"auto_grind\s*:\s*autoGrind", js)
ok("no global auto-grind left in settings.js")

run_node(JS)
print(f"{passed} checks passed")
