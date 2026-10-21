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
const A0 = await import(U('delivery_actions.js'));
const t = D.board(data, ctx);
const lanes = find('details', t).filter((s) => String(s.props['aria-label']).match(/^(Epic|No epic)/));
assert.deepEqual(lanes.map((l) => l.props['aria-label']), ['Epic #40', 'No epic']);
const cols = find('section', lanes[0]).filter((s) => s.props['aria-label'] !== 'Epic #40');
assert.deepEqual(cols.map((c) => c.props['aria-label']), ['Needs refinement', 'Blocked', 'Ready', 'In progress', 'Draft PR', 'In review', 'Grinding', 'Merged']);
const inCol = (name) => text(cols.find((c) => c.props['aria-label'] === name));
assert.match(inCol('Blocked'), /Blocked one/); assert.ok(!/Blocked one/.test(inCol('Ready'))); assert.match(inCol('In progress'), /Running one/); assert.match(inCol('Draft PR'), /Draft/);
assert.match(inCol('In review'), /Review/); assert.match(inCol('Grinding'), /Grind/); assert.match(inCol('Merged'), /Done/);
out('delivery: epic lanes by eight stage columns');

assert.match(inCol('Blocked'), /Blocked by #3, #4/);
assert.ok(!/Blocked/.test(inCol('In progress')) && !/Blocked by/.test(inCol('Ready')));
const blocked = byClass('is-blocked', lanes[0]); assert.equal(blocked.length, 1);
assert.equal(find(A0.CardActions, byClass('is-blocked', lanes[0])[0]).length, 1);
{
  const gl = D.laneGroups([card({ n: 1, blocked_by: [3, 4] }), card({ n: 2, column: 'unrefined', blocked_by: [3] }), card({ n: 3 })]);
  assert.deepEqual([gl.blocked.map((c) => c.n), gl.unrefined.map((c) => c.n), gl.ready.map((c) => c.n)], [[1], [2], [3]]);
}
out('delivery: blocked card lands in Blocked with the lock line and blocker numbers');

{
  const L = D.lane(data.lanes[0], ctx);
  const sec = find('section', L).filter((s) => s.props['aria-label'] !== 'Epic #40');
  const empties = sec.filter((s) => s.props.class === 'bcol is-empty').map((s) => s.props['aria-label']);
  assert.deepEqual(empties, ['Needs refinement', 'Ready'], 'columns without cards collapse');
  assert.equal(byClass('empty', L).length, 0, 'no None box in a collapsed column');
  const sparse = D.lane({ ...data.lanes[0], cards: [card({ n: 1 }), card({ n: 8, column: 'in_review' })] }, ctx);
  const cl = find('section', sparse).filter((s) => s.props['aria-label'] !== 'Epic #40');
  assert.deepEqual(cl.filter((s) => s.props.class === 'bcol').map((s) => s.props['aria-label']), ['Ready', 'In review']);
  assert.equal(cl.filter((s) => s.props.class === 'bcol is-empty').length, 6);
}
out('delivery: columns without cards render is-empty with a heading only');

const heads = lanes.map((l) => text(byClass('lane-running', l)));
assert.deepEqual(heads, ['2/2 running', '2/2 running']); assert.equal(byClass('at-cap', lanes[0]).length, 1);
const low = D.lane({ ...data.lanes[0], running: 1 }); assert.equal(text(byClass('lane-running', low)), '1/2 running'); assert.equal(byClass('at-cap', low).length, 0);
{
  const head = find('summary', lanes[0]).find((s) => s.props.class === 'lane-head');
  assert.equal(find(A0.LaneAutopilot, head).length, 1); assert.equal(find(A0.CloseEpic, head).length, 1);
  const mce = new A0.CloseEpic({ lane: data.lanes[0], repo: 'o/r' }); mce.state = { busy: false };
  const mrender = mce.render({ lane: data.lanes[0], repo: 'o/r' }, mce.state);
  const ceb = find('button', mrender);
  assert.equal(ceb.length, 1, 'the mounted epic menu has exactly one button');
  assert.ok(find('button', byClass('menu-panel', mrender)[0]).includes(ceb[0]) && text(ceb[0]) === 'Close epic', 'and it is inside .menu-panel, not the header');
  const none = D.lane(data.lanes[1], ctx);
  assert.ok(find(A0.CloseEpic, none).length === 1 && A0.CloseEpic.prototype.render.call({ state: {} }, { lane: data.lanes[1] }, { busy: false }) === null, 'No epic lane has no menu');
}
out('delivery: lane header holds the Autopilot switch and the epic menu');

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
assert.equal(view(blockedA), null, 'blocked card renders no buttons');
const freeA = mount(A.CardActions, { card: card({ n: 6 }), repo: 'o/r', onChange: ctx.reload });
assert.deepEqual(labels(freeA), ['Start', 'Start in herdr']);
assert.ok(!btnOf(freeA, 'Start').props.disabled);
{
  const det = find('details', view(freeA))[0], sum = find('summary', det)[0];
  assert.equal(sum.props['aria-label'], 'More start options'); assert.equal(sum.props['aria-expanded'], false);
  det.props.onToggle({ currentTarget: { open: true } });
  assert.equal(find('summary', view(freeA))[0].props['aria-expanded'], true); assert.match(text(find('details', view(freeA))[0]), /Start in herdr/);
  freeA.setState({ busy: true });
  assert.ok(btnOf(freeA, 'Start').props.disabled && btnOf(freeA, 'Start in herdr').props.disabled && find('summary', view(freeA))[0].props['aria-disabled'] === true, 'busy disables Start, the toggle and the item');
  freeA.setState({ busy: false, menuOpen: false });
}
{
  let f = 0; freeA.menu = { open: true, querySelector: () => ({ focus: () => f++ }) };
  const mn = freeA.menu;
  await btnOf(freeA, 'Start').props.onClick();
  assert.equal(mn.open, false, 'headless Start closes the menu'); assert.equal(f, 0, 'and leaves focus alone');
  mn.open = true;
  await btnOf(freeA, 'Start in herdr').props.onClick();
  assert.equal(mn.open, false, 'Start in herdr closes the menu'); assert.equal(f, 1, 'and focuses its summary');
  posts.pop(); posts.pop(); reloads -= 2; freeA.menu = null;
}
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

{
  // the ⋯ menu: toggling opens by hand and never toggles the lane; Close epic confirms, then posts
  const ce = mount(A.CloseEpic, { lane: data.lanes[0], repo: 'o/r', onChange: ctx.reload });
  let sumFocus = 0; const menu = { open: false, querySelector: (q) => (q === 'summary' ? { focus: () => sumFocus++ } : null) }; ce.menu = menu;
  const sum = () => find('summary', view(ce))[0];
  assert.equal(sum().props['aria-label'], 'Epic actions'); assert.equal(text(sum()), '⋯');
  assert.equal(sum().props['aria-expanded'], false);
  byClass('lane-menu', view(ce))[0].props.onToggle({ currentTarget: { open: true } }); assert.equal(sum().props['aria-expanded'], true, 'aria-expanded follows the toggle');
  byClass('lane-menu', view(ce))[0].props.onToggle({ currentTarget: { open: false } });
  let prevented = 0; const ev = { preventDefault: () => { prevented++; } };
  sum().props.onClick(ev); assert.equal(menu.open, true); sum().props.onClick(ev); assert.equal(menu.open, false); assert.equal(prevented, 2);
  const panel = byClass('menu-panel', view(ce))[0]; panel.props.onClick(ev); assert.equal(prevented, 3, 'clicks inside the menu do not toggle the lane');
  globalThis.confirm = () => true; status = 200;
  globalThis.fetch = async (u, o = {}) => { posts.push([u, JSON.parse(o.body)]); return { ok: true, status: 200, json: async () => ({ closed: [1, 2] }) }; };
  menu.open = true;
  const p = find('button', view(ce)).find((b) => text(b) === 'Close epic').props.onClick();
  assert.equal(menu.open, false, 'the menu closes on choosing'); assert.equal(text(sum()), 'Closing…'); assert.equal(sum().props['aria-disabled'], true);
  assert.equal(sumFocus, 1, 'focus returns to its summary'); assert.equal(sum().props['aria-label'], 'Closing epic');
  sum().props.onClick(ev); assert.equal(menu.open, false, 'no toggling while closing');
  await p;
  assert.deepEqual(posts.at(-1), ['/api/epics/close', { repo: 'o/r', epic: 40 }]); assert.equal(text(sum()), '⋯');
}
out('delivery actions: epic menu opens by hand, Close epic confirms and shows Closing…');

out('delivery: Delivery mounts inside BoardShell polling /api/delivery');
"""
)


js = read("delivery.js")
assert "innerHTML" not in js and "console.log" not in js and 'data-slot="actions"' in js and "CardActions" in js
ok("delivery.js: no innerHTML, actions slot on cards")

run_node(JS)
print(f"{passed} checks passed")
