#!/usr/bin/env python3
"""Planning board page (task 48).
`python3 run-engine/test_ui_planning_static.py` — exit 0 = green. Node-driven, no server or network.
"""

import os
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
const P = await import(U('planning.js'));
const B = await import(U('boardshell.js'));
const prd = (o) => ({ slug: 's', title: 'T', status: 'Approved', column: 'approved', path: 'docs/prds/s.md', abs_path: '/co/docs/prds/s.md', pr: null, epic: null, issues: 0, refined: 0, panel: null, ...o });
const data = { repo: 'o/r', stale: false, fetched_at: 'x', prds: [
  prd({ slug: 'a', title: 'Draft one', status: 'Draft', column: 'draft', path: 'docs/prds/a.md', abs_path: '/co/docs/prds/a.md' }),
  prd({ slug: 'b', title: 'In review one', status: 'In review', column: 'in_review', pr: { n: 12, url: 'u12' }, path: 'docs/prds/b.md' }),
  prd({ slug: 'c', title: 'Approved one', epic: 40, path: 'docs/prds/c.md' }),
  prd({ slug: 'd', title: 'Filed one', column: 'tasks_filed', epic: 41, issues: 8, refined: 3, path: 'docs/prds/d.md' }),
  prd({ slug: 'e', title: 'Refined one', column: 'refined', epic: 42, issues: 4, refined: 4, path: 'docs/prds/e.md' }),
] };
const OFFERS = { default: ['critical'], max_rounds: 5, kinds: { custom: ['critical', 'ceo', 'cto', 'qa'], 'create-prd': ['critical'] } };
const posts = []; let fail = null;
globalThis.fetch = async (u, o = {}) => { if (!o.body) return { ok: true, status: 200, json: async () => OFFERS }; posts.push([u, JSON.parse(o.body)]); return fail ? { ok: false, status: 409, json: async () => ({ error: fail }) } : { ok: true, status: 200, json: async () => ({ session: 'sess1', ok: true }) }; };
let reloads = 0;
const ctx = { repo: 'o/r', reload: () => { reloads++; } };
const board = new P.PlanningBoard({ data, ctx });
board.setState = (p, cb) => { board.state = { ...board.state, ...(typeof p === 'function' ? p(board.state) : p) }; cb && cb(); };
const view = () => board.render({ data, ctx }, board.state);
const cols = (t) => Object.fromEntries(find('section', t).map((s) => [s.props['aria-label'], text(s)]));
let t = view();
assert.deepEqual(find('section', t).map((s) => s.props['aria-label']), ['PRD draft', 'In review', 'Approved', 'Tasks filed', 'Refined']);
const c = cols(t);
assert.match(c['PRD draft'], /Draft one/); assert.match(c['In review'], /In review one[\s\S]*PR #12/);
assert.match(c['Approved'], /Approved one[\s\S]*Epic #40/); assert.match(c['Tasks filed'], /Filed one[\s\S]*8 issues[\s\S]*3\/8 refined/);
assert.match(c['Refined'], /Refined one[\s\S]*4\/4 refined/);
out('planning: PRDs land in their stage columns with stage detail; 3/8 refined is under Tasks filed');

const btn = (label) => find('button', view()).find((b) => text(b) === label);
assert.ok(btn('Create tasks') && btn('Refine') && btn('Autopilot'), 'one action per stage');
assert.equal(find('button', view()).length, 3, 'draft and in-review cards have no start button here');
assert.equal(byClass('bcard-slot', find('section', view())[0]).length, 1, 'draft card has the panel slot');
out('planning: Create tasks (approved, no issues), Refine (not all refined), Autopilot (all refined), draft panel slot');

await btn('Refine').props.onClick();
assert.deepEqual(posts.at(-1), ['/api/start', { repo: 'o/r', skill: 'refine-issues', arg: '41', via: 'headless' }]);
await btn('Create tasks').props.onClick();
assert.deepEqual(posts.at(-1), ['/api/start', { repo: 'o/r', skill: 'create-tasks', arg: 'docs/prds/c.md', via: 'headless' }]);
await btn('Autopilot').props.onClick();
assert.deepEqual(posts.at(-1), ['/api/autopilot', { repo: 'o/r', epic: 42, on: true }]);
assert.equal(reloads, 3);
assert.ok(find('a', view()).some((a) => a.props.href === '#/session/sess1'), 'session link after start');
out('planning: actions POST the PRD contract bodies and link the new session');

fail = 'issue already has a live session';
await btn('Refine').props.onClick();
assert.match(text(find('p', view()).filter((p) => p.props.role === 'alert')), /live session/); assert.equal(reloads, 3);
out('planning: a refused start shows its error');

const empty = new P.PlanningBoard({ data: { ...data, prds: [] }, ctx });
const et = empty.render({ data: { ...data, prds: [] }, ctx }, empty.state);
assert.match(text(et), /Run \/create-prd/); assert.equal(find('section', et).length, 0);
out('planning: no PRDs shows the Run /create-prd hint');

// task 51: panel on draft cards
const PC = await import(U('panel.js'));
const mount = (C, props) => { const i = new C(props); i.props = props; i.setState = (p, cb) => { i.state = { ...i.state, ...(typeof p === 'function' ? p(i.state) : p) }; cb && cb(); }; return i; };
const pview = (i) => i.render(i.props, i.state);
const draftCard = P.prdCard(data.prds[0], 'o/r', { offers: OFFERS, onChange: ctx.reload, onAct() {} });
const ctl = find(PC.PanelControl, draftCard)[0];
assert.ok(ctl && ctl.props.artifact === '/co/docs/prds/a.md' && ctl.props.repo === 'o/r', 'draft card mounts the panel control with the absolute artifact path');
assert.equal(find(PC.PanelControl, P.prdCard(data.prds[2], 'o/r', { onAct() {} })).length, 0);
out('panel: draft card mounts PanelControl with the absolute PRD path');

assert.deepEqual(PC.offerFor(OFFERS), ['critical', 'ceo', 'cto', 'qa'], 'the custom offer is what POST /api/review accepts');
const pc = mount(PC.PanelControl, { repo: 'o/r', artifact: '/co/docs/prds/a.md', panel: null, offers: OFFERS, onChange: ctx.reload });
assert.equal(find('button', pview(pc)).length, 0, 'no Start until review is ticked');
const cb = (l) => find('input', pview(pc)).find((x) => x.props.id.endsWith('-' + l));
find('input', pview(pc))[0].props.onChange({ target: { checked: true } });
cb('ceo').props.onChange({ target: { checked: true } }); cb('qa').props.onChange({ target: { checked: true } });
const nPosts = posts.length; fail = null;
await find('button', pview(pc)).find((b) => text(b) === 'Start review').props.onClick();
assert.deepEqual(posts.at(-1), ['/api/review', { repo: 'o/r', artifact: '/co/docs/prds/a.md', lenses: ['critical', 'ceo', 'qa'] }]);
assert.match(text(pview(pc)), /Review 0\/3, round 1/);
out('panel: Start POSTs /api/review with the picked lenses and shows 0/3, round 1');

const status = (o) => ({ id: 'p-1', root_session: 'root-1', approved: 1, total: 3, round: 2, state: 'running', reason: null, lenses: { critical: 'approve', ceo: 'failed', qa: 'waiting' }, ...o });
const live = mount(PC.PanelControl, { repo: 'o/r', artifact: '/a', panel: status(), offers: OFFERS, onChange: ctx.reload });
assert.match(text(pview(live)), /Review 1\/3, round 2/);
assert.deepEqual(find('button', pview(live)).map((b) => text(b)), ['Re-run', 'Drop']);
await find('button', pview(live))[0].props.onClick();
assert.deepEqual(posts.at(-1), ['/api/review/p-1/lens', { lens: 'ceo', action: 'rerun' }]);
await find('button', pview(live))[1].props.onClick();
assert.deepEqual(posts.at(-1), ['/api/review/p-1/lens', { lens: 'ceo', action: 'drop' }]);
out('panel: a failed lens shows Re-run and Drop, each POSTing its action');

const cap = mount(PC.PanelControl, { repo: 'o/r', artifact: '/a', panel: status({ state: 'cap reached', lenses: { critical: 'changes', ceo: 'approve', qa: 'approve' }, approved: 2, round: 5 }), offers: OFFERS });
assert.match(text(pview(cap)), /cap reached/i);
assert.ok(find('a', pview(cap)).some((a) => a.props.href === '#/session/root-1'), 'cap reached links the root session');
out('panel: cap reached links the root session');

const top = P.Planning(); assert.equal(top.type, B.BoardShell); assert.equal(top.props.path, '/api/planning');
out('planning: Planning mounts inside BoardShell polling /api/planning');
"""
)


js = read("panel.js")
assert "innerHTML" not in js and "console.log" not in js and "lensPicker" in js
ok("panel.js: no innerHTML, reuses lensPicker")
js = read("planning.js")
assert "innerHTML" not in js and "console.log" not in js and 'data-slot="panel"' in js
ok("planning.js: no innerHTML, panel slot on draft cards")

run_node(JS)
print(f"{passed} checks passed")
