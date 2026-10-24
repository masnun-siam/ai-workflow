import { describe, expect, it } from 'vitest';
import type { DeliveryCard, DeliveryLane, PanelRef, PlanningPrd } from '../api/types';
import { sessionInRepo } from './format';
import { joinFeatures, stageOf } from './features';
import { mdToHtml } from './md';
import { nextStep } from './nextStep';
import { migrateRepoKey, pickRepo, withRepoParam } from './repo';
import { boardColumn, issueStatus, BOARD_COLUMNS, PLAN_RUN } from './vocab';

const card = (o: Partial<DeliveryCard>): DeliveryCard => ({
  n: 1, title: 't', column: 'ready', priority: null, blocked_by: [], pr: null, session: null, needs_cleanup: null, ...o,
});
const prd = (o: Partial<PlanningPrd> = {}): PlanningPrd => ({
  slug: 'f', title: 'F', status: 'Approved', path: 'docs/prds/f.md', abs_path: '/x/f.md', column: 'approved',
  pr: null, epic: 10, issues: 0, refined: 0, unrefined: [], children: [], panel: null, ...o,
});
const lane = (cards: DeliveryCard[]): DeliveryLane => ({ epic: 10, title: 'F', running: 0, cards });
const panel = (o: Partial<PanelRef>): PanelRef => ({
  id: 'p', approved: 1, total: 3, round: 2, max_rounds: 5, state: 'running', lenses: {}, ...o,
});
const feat = (p: PlanningPrd, cards: DeliveryCard[] = []) => joinFeatures([p], [lane(cards)])[0];

describe('nextStep (FR-12)', () => {
  it('draft', () => {
    const s = nextStep(feat(prd({ status: 'Draft' })));
    expect(s.primary.action).toEqual({ kind: 'startReview' });
    expect(s.secondary?.label).toBe('Approve without review');
  });
  it('review running / cap / approved', () => {
    const run = nextStep(feat(prd({ status: 'Draft', panel: panel({}) })));
    expect(run.primary.label).toBe('Watch review');
    expect(run.secondary?.label).toBe('Approve now');
    const cap = nextStep(feat(prd({ status: 'Draft', panel: panel({ state: 'cap reached', round: 5 }) })));
    expect(cap.primary.label).toBe('Decide');
    expect(cap.secondary?.label).toBe('Approve anyway');
    const ok = nextStep(feat(prd({ status: 'Draft', panel: panel({ state: 'approved' }) })));
    expect(ok.primary.label).toBe('Approve PRD');
  });
  it('approved -> create tasks', () => {
    expect(nextStep(feat(prd())).primary.action).toEqual({ kind: 'createTasks' });
  });
  it('no open epic: open children come from whichever lane holds them', () => {
    const p = prd({ epic: null, issues: 1, column: 'refined', children: [{ n: 7, title: 't', refined: true }] });
    const loose: DeliveryLane = { epic: null, title: '', running: 0, cards: [card({ n: 7 }), card({ n: 8 })] };
    const f = joinFeatures([p], [loose])[0];
    expect(f.issues.map((i) => i.n)).toEqual([7]);
    expect(nextStep(f).primary).toEqual({ label: 'See the issues', action: { kind: 'tab', tab: 'issues' } }); // no epic to run
  });
  it('done column is shipped even with no merged cards in the lane', () => {
    expect(feat(prd({ column: 'done' }), []).stage).toBe('shipped');
  });
  it('tasks: refine N, no batch start', () => {
    const f = feat(prd({ issues: 2, unrefined: [2], column: 'tasks_filed' }), [card({ n: 2, column: 'unrefined' }), card({ n: 3 })]);
    expect(f.stage).toBe('tasks');
    const s = nextStep(f);
    expect(s.primary).toEqual({ label: 'Refine 1', action: { kind: 'refine', issues: [2] } });
    expect(s.secondary).toBeUndefined();
  });
  it('building: merge, run the epic, follow its dispatch, or see the issues', () => {
    const p = prd({ issues: 2 });
    const pr = { n: 9, draft: false, ci: 'success', url: '', review: 'approved' as const };
    const m = nextStep(feat(p, [card({ n: 1, column: 'in_review', pr, mergeable: true }), card({ n: 2 })]));
    expect(m.primary).toEqual({ label: 'Review and merge', action: { kind: 'merge', pr: 9 } });
    const a = nextStep(feat(p, [card({ n: 1, column: 'in_progress' }), card({ n: 2 })]));
    expect(a.primary).toEqual({ label: 'Run epic', action: { kind: 'dispatch' } });
    expect(a.secondary).toBeUndefined();
    const running = nextStep(feat(p, [card({ n: 1, column: 'in_progress' })]), { id: 'd1', closed: 1, total: 3, you: 1 });
    expect(running).toMatchObject({ title: 'The dispatch needs you on 1 issue', primary: { action: { kind: 'openDispatch', id: 'd1' } }, quiet: false });
    const quiet = nextStep(feat(p, [card({ n: 1, column: 'in_progress' })]));
    expect(quiet.primary.action).toEqual({ kind: 'tab', tab: 'issues' });
    expect(quiet.quiet).toBe(true);
  });
  it('shipped -> close epic', () => {
    const f = feat(prd({ issues: 0 }), [card({ column: 'merged' })]);
    expect(f.stage).toBe('shipped');
    expect(nextStep(f).primary.action).toEqual({ kind: 'closeEpic' });
  });
  it('merge follows the server rule (card.mergeable), not the PR fields', () => {
    const pr = { n: 9, draft: false, ci: 'success', url: '', review: 'approved' as const };
    expect(nextStep(feat(prd({ issues: 1 }), [card({ column: 'in_review', pr, mergeable: false })])).primary.label).not.toBe('Review and merge');
    expect(nextStep(feat(prd({ issues: 1 }), [card({ column: 'in_review', pr: { ...pr, review: 'none' }, mergeable: true })])).primary.action).toEqual({ kind: 'merge', pr: 9 });
  });
});

describe('board columns (FR-18)', () => {
  it('maps every delivery column to exactly one of five', () => {
    const cols = ['unrefined', 'ready', 'in_progress', 'draft_pr', 'in_review', 'grinding', 'merged'] as const;
    expect(cols.map((c) => boardColumn({ column: c }))).toEqual(['refine', 'ready', 'building', 'building', 'review', 'review', 'merged']);
    expect(BOARD_COLUMNS).toHaveLength(5);
  });
  it('blocked stays in Ready; issue status shows Blocked', () => {
    const c = { column: 'ready' as const, blocked_by: [4] };
    expect(boardColumn(c)).toBe('ready');
    expect(issueStatus(c)).toBe('blocked');
    expect(issueStatus({ column: 'in_review', blocked_by: [4] })).toBe('in_review');
  });
  it('stageOf: Approved with open children and all ready is Building', () => {
    expect(stageOf(prd({ issues: 2 }), lane([card({}), card({ n: 2 })]))).toBe('building');
  });
});

describe('repo choice (FR-3)', () => {
  const mem = (init: Record<string, string>) => {
    const m = new Map(Object.entries(init));
    return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k), m };
  };
  it('reads a legacy key once into aiw.repo, then drops it', () => {
    const s = mem({ 'aiw.boardRepo': '/path/x', 'aiw.lastRepo': 'o/r' });
    expect(migrateRepoKey(s)).toBe('o/r');
    expect(s.m.get('aiw.repo')).toBe('o/r');
    expect(s.m.has('aiw.boardRepo') || s.m.has('aiw.lastRepo')).toBe(false);
  });
  it('never overwrites aiw.repo', () => {
    const s = mem({ 'aiw.repo': 'a/b', 'aiw.lastRepo': 'o/r' });
    expect(migrateRepoKey(s)).toBe('a/b');
  });
  it('URL beats storage; unknown remembered repo falls back to the first', () => {
    expect(pickRepo('?repo=x/y', ['a/b'], 'a/b')).toBe('x/y');
    expect(pickRepo('', ['a/b', 'c/d'], 'c/d')).toBe('c/d');
    expect(pickRepo('', ['a/b'], 'gone/x')).toBe('a/b');
  });
  it('withRepoParam keeps other params', () => {
    expect(withRepoParam('?a=1', 'o/r')).toBe('?a=1&repo=o/r');
    expect(withRepoParam('?repo=o/r', '')).toBe('');
  });
});

describe('md', () => {
  it('escapes html and only links http(s)', () => {
    expect(mdToHtml('<b>x</b> javascript:alert(1)')).toBe('<p>&lt;b&gt;x&lt;/b&gt; javascript:alert(1)</p>');
    expect(mdToHtml('see https://a.b/c.')).toContain('<a href="https://a.b/c" target="_blank" rel="noopener noreferrer">');
  });
  it('lists, headings, fences', () => {
    expect(mdToHtml('# T\n- a\n- b')).toBe('<h1>T</h1>\n<ul>\n<li>a</li>\n<li>b</li>\n</ul>');
    expect(mdToHtml('```\n<x>\n```')).toBe('<pre><code>&lt;x&gt;</code></pre>');
    expect(mdToHtml('```mermaid\na->>b\n```')).toBe('<pre class="mermaid">a-&gt;&gt;b</pre>');
  });
  it('markdown links: http(s) linked, relative paths left as text', () => {
    expect(mdToHtml('[Docs](https://a.b/c) and [Logs](../x.md)')).toBe('<p><a href="https://a.b/c" target="_blank" rel="noopener noreferrer">Docs</a> and Logs</p>');
    expect(mdToHtml('[x](javascript:alert(1))')).toBe('<p>x)</p>');
  });
});

describe('PLAN_RUN', () => {
  it('is the opus alias at medium effort', () => expect(PLAN_RUN).toEqual({ model: 'opus', effort: 'medium' }));
});

describe('mdToHtml tables', () => {
  it('renders a pipe table', () => {
    const h = mdToHtml('| a | b |\n|---|---|\n| **x** | `y` |\n\nafter');
    expect(h).toContain('<th>a</th><th>b</th>');
    expect(h).toContain('<td><strong>x</strong></td><td><code>y</code></td>');
    expect(h).toContain('<p>after</p>');
  });
});

describe('sessionInRepo', () => {
  const s = (o: Record<string, unknown>) => ({ link: null, repo: null, ...o }) as Parameters<typeof sessionInRepo>[0];
  it('matches by slug when there is one, else by checkout path', () => {
    expect(sessionInRepo(s({ slug: 'O/R' }), 'o/r', '/x')).toBe(true);
    expect(sessionInRepo(s({ slug: 'o/other', repo: '/x' }), 'o/r', '/x')).toBe(false);
    expect(sessionInRepo(s({ repo: '/x' }), 'o/r', '/x')).toBe(true);
    expect(sessionInRepo(s({ repo: '/other' }), 'o/r', '/x')).toBe(false);
    expect(sessionInRepo(s({ repo: '/x' }), 'o/r', undefined)).toBe(false);
    expect(sessionInRepo(s({ slug: 'o/r', repo: '/private/x' }), 'o/r', '/x')).toBe(true);
  });
});
