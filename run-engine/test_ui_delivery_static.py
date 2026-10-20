#!/usr/bin/env python3
"""Delivery board page (task 50).
`python3 run-engine/test_ui_delivery_static.py` — exit 0 = green. Node-driven, no server or network.
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
const D = await import(U('delivery.js'));
const B = await import(U('boardshell.js'));
const card = (o) => ({ n: 1, title: 'T', column: 'ready', priority: null, blocked_by: [], pr: null, session: null, grind_round: null, needs_cleanup: null, ...o });
const data = { repo: 'o/r', stale: false, fetched_at: 'x', cap: 2, running: 2, auto_grind: false, lanes: [
  { epic: 40, title: 'Boards', autopilot: true, cap: 2, running: 2, cards: [
    card({ n: 5, title: 'Blocked one', blocked_by: [3, 4] }),
    card({ n: 6, title: 'Running one', column: 'in_progress', session: { id: 's-6', status: 'running' } }),
    card({ n: 7, title: 'Draft', column: 'draft_pr', pr: { n: 70, draft: true, ci: 'pending', url: 'u70' } }),
    card({ n: 8, title: 'Review', column: 'in_review', pr: { n: 80, draft: false, ci: 'red', url: 'u80' } }),
    card({ n: 9, title: 'Grind', column: 'grinding', session: { id: 's-9', status: 'running' }, grind_round: 3, pr: { n: 90, draft: false, ci: 'green', url: 'u90' } }),
    card({ n: 10, title: 'Done', column: 'merged', needs_cleanup: { uncommitted: ['a'], unpushed: [] } }),
  ] },
  { epic: null, title: 'No epic', autopilot: false, cap: 2, running: 2, cards: [card({ n: 11, title: 'Loose' })] },
] };
const posts = []; let status = 200;
globalThis.fetch = async (u, o = {}) => { posts.push([u, JSON.parse(o.body)]); return status === 200 ? { ok: true, status, json: async () => ({ session: 's' }) } : { ok: false, status, json: async () => ({ error: 'issue is blocked' }) }; };
let reloads = 0;
const ctx = { repo: 'o/r', reload: () => { reloads++; } };
const t = D.board(data, ctx);
const lanes = find('details', t).filter((s) => String(s.props['aria-label']).match(/^(Epic|No epic)/));
assert.deepEqual(lanes.map((l) => l.props['aria-label']), ['Epic #40', 'No epic']);
const cols = find('section', lanes[0]).filter((s) => s.props['aria-label'] !== 'Epic #40');
assert.deepEqual(cols.map((c) => c.props['aria-label']), ['Ready', 'In progress', 'Draft PR', 'In review', 'Grinding', 'Merged']);
const inCol = (name) => text(cols.find((c) => c.props['aria-label'] === name));
assert.match(inCol('Ready'), /Blocked one/); assert.match(inCol('In progress'), /Running one/); assert.match(inCol('Draft PR'), /Draft/);
assert.match(inCol('In review'), /Review/); assert.match(inCol('Grinding'), /Grind/); assert.match(inCol('Merged'), /Done/);
out('delivery: epic lanes by six stage columns');

assert.match(inCol('Ready'), /Blocked by #3, #4/);
assert.ok(!/Blocked/.test(inCol('In progress')));
const blocked = byClass('is-blocked', lanes[0]); assert.equal(blocked.length, 1);
out('delivery: blocked card shows the lock with blocker numbers');

const heads = lanes.map((l) => text(byClass('lane-running', l)));
assert.deepEqual(heads, ['2/2 running', '2/2 running']); assert.equal(byClass('at-cap', lanes[0]).length, 1);
const low = D.lane({ ...data.lanes[0], running: 1 }); assert.equal(text(byClass('lane-running', low)), '1/2 running'); assert.equal(byClass('at-cap', low).length, 0);
assert.match(text(byClass('chip', lanes[0])), /autopilot on/);
out('delivery: lane header shows running/cap, flagged at cap');

assert.match(inCol('Grinding'), /grind round 3/);
const links = find('a', lanes[0]).map((a) => a.props.href);
assert.ok(links.includes('#/session/s-6') && links.includes('#/session/s-9'), 'session chips link the session view');
assert.match(inCol('Draft PR'), /ci running/); assert.match(inCol('In review'), /ci failing/); assert.match(inCol('Grinding'), /ci passing/);
assert.ok(!/ci /.test(inCol('Ready')));
assert.match(inCol('Merged'), /needs cleanup/);
assert.equal(byClass('bcard-slot', lanes[0]).length, 6, 'every card has an actions slot');
out('delivery: grind round, session chip link, CI chips from ghstatus, cleanup flag');

const noEpic = D.board({ ...data, lanes: [data.lanes[1]] });
assert.deepEqual(find('details', noEpic).filter((s) => /^(Epic|No epic)/.test(s.props['aria-label'])).map((s) => s.props['aria-label']), ['No epic']);
assert.match(text(D.board({ ...data, lanes: [] })), /Nothing to deliver/);
out('delivery: a repo with no epics shows only the No epic lane');

const shipped = { epic: 50, title: 'Shipped', autopilot: false, cap: 2, running: 0, cards: [card({ n: 12, title: 'Merged one', column: 'merged' })] };
assert.equal(D.openCount(shipped), 0); assert.equal(D.openCount(data.lanes[0]), 5, 'merged cards are not open work');
const both = D.board({ ...data, lanes: [data.lanes[0], shipped] }, ctx);
assert.deepEqual(find('details', both).map((d) => [d.props['aria-label'], d.props.open]), [['Epic #40', true], ['Epic #50', false]]);
assert.match(text(find('details', both)[1]), /nothing open/);
const only = D.board({ ...data, lanes: [data.lanes[0], shipped] }, { ...ctx, epic: '50' });
assert.deepEqual(find('details', only).map((d) => [d.props['aria-label'], d.props.open]), [['Epic #50', true]], 'a filtered epic shows open');
assert.equal(byClass('col-tabs', lanes[0]).length, 1, 'each lane has column tabs for phones');
out('delivery: a lane with nothing open starts collapsed; the epic filter shows one lane; column tabs');

const top = D.Delivery(); assert.equal(top.type, B.BoardShell); assert.equal(top.props.path, '/api/delivery');
const A = await import(U('delivery_actions.js'));
const mount = (C, props) => { const i = new C(props); i.props = props; i.setState = (p, cb) => { i.state = { ...i.state, ...(typeof p === 'function' ? p(i.state) : p) }; cb && cb(); }; return i; };
const view = (i) => i.render(i.props, i.state);
const labels = (i) => find('button', view(i)).map((b) => text(b));
const btnOf = (i, l) => find('button', view(i)).find((b) => text(b) === l);

const blockedA = mount(A.CardActions, { card: card({ n: 5, blocked_by: [3] }), repo: 'o/r', onChange: ctx.reload });
assert.deepEqual(labels(blockedA), ['Start', 'Start in herdr']);
assert.ok(btnOf(blockedA, 'Start').props.disabled && btnOf(blockedA, 'Start in herdr').props.disabled, 'blocked card cannot start');
const freeA = mount(A.CardActions, { card: card({ n: 6 }), repo: 'o/r', onChange: ctx.reload });
assert.ok(!btnOf(freeA, 'Start').props.disabled);
await btnOf(freeA, 'Start').props.onClick();
assert.deepEqual(posts.at(-1), ['/api/start', { repo: 'o/r', skill: 'implement-issue', arg: '6', via: 'headless' }]);
await btnOf(freeA, 'Start in herdr').props.onClick();
assert.deepEqual(posts.at(-1), ['/api/start', { repo: 'o/r', skill: 'implement-issue', arg: '6', via: 'herdr' }]);
assert.equal(reloads, 2);
status = 409; await btnOf(freeA, 'Start').props.onClick();
assert.equal(reloads, 2, '409 starts nothing and reloads nothing');
out('delivery actions: Start / Start in herdr POST implement-issue, blocked disabled, 409 starts nothing');

const rev = card({ n: 8, column: 'in_review', pr: { n: 80, draft: false, ci: 'green', url: 'u80' } });
assert.deepEqual(labels(mount(A.CardActions, { card: rev, repo: 'o/r', autoGrind: true })), []);
assert.deepEqual(labels(mount(A.CardActions, { card: card({ n: 7, column: 'draft_pr', pr: rev.pr }), repo: 'o/r', autoGrind: false })), []);
status = 200;
const grindA = mount(A.CardActions, { card: rev, repo: 'o/r', autoGrind: false, onChange: ctx.reload });
assert.deepEqual(labels(grindA), ['Grind']);
await btnOf(grindA, 'Grind').props.onClick();
assert.deepEqual(posts.at(-1), ['/api/start', { repo: 'o/r', skill: 'pr-grind', arg: 'u80', via: 'headless' }]);
const mounted = find(A.CardActions, D.board(data, ctx)); assert.equal(mounted.length, 7); assert.ok(mounted.every((m) => m.props.autoGrind === false && m.props.repo === 'o/r'), 'board passes repo and auto_grind down');
assert.ok(find(A.CardActions, D.board({ ...data, auto_grind: true }, ctx)).every((m) => m.props.autoGrind === true));
out('delivery actions: Grind only on In review cards when auto_grind is off');

const ap = mount(A.LaneAutopilot, { lane: data.lanes[0], repo: 'o/r', onChange: ctx.reload });
const sw = find('input', view(ap))[0]; assert.equal(sw.props.checked, true);
await sw.props.onChange();
assert.deepEqual(posts.at(-1), ['/api/autopilot', { repo: 'o/r', epic: 40, on: false }]);
assert.equal(view(mount(A.LaneAutopilot, { lane: data.lanes[1], repo: 'o/r' })), null, 'no switch on the No epic lane');
out('delivery actions: lane autopilot switch POSTs the toggled state');

const done = card({ n: 10, column: 'merged', needs_cleanup: { uncommitted: ['src/a.py'], unpushed: ['abc1234'] } });
const cl = mount(A.CardActions, { card: done, repo: 'o/r', onChange: ctx.reload });
assert.deepEqual(labels(cl), ['Clean']);
const before = posts.length;
btnOf(cl, 'Clean').props.onClick();
const dlg = byClass('clean-dialog', view(cl))[0];
assert.match(text(dlg), /src\/a\.py/); assert.match(text(dlg), /abc1234/); assert.equal(posts.length, before, 'nothing posted before confirming');
await btnOf(cl, 'Clean up').props.onClick();
assert.deepEqual(posts.at(-1), ['/api/cleanup', { repo: 'o/r', issue: 10, confirm: true }]);
assert.equal(byClass('clean-dialog', view(cl)).length, 0, 'dialog closes after cleaning');
assert.deepEqual(labels(mount(A.CardActions, { card: card({ n: 12, column: 'merged' }), repo: 'o/r' })), [], 'unflagged merged card has no Clean');
out('delivery actions: Clean lists uncommitted paths and unpushed shas before POST /api/cleanup');

out('delivery: Delivery mounts inside BoardShell polling /api/delivery');
"""
)


js = read("delivery.js")
assert "innerHTML" not in js and "console.log" not in js and 'data-slot="actions"' in js and "CardActions" in js
ok("delivery.js: no innerHTML, actions slot on cards")

run_node(JS)
print(f"{passed} checks passed")
