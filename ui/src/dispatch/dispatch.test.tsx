import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { App } from '../App';
import { QueryProvider } from '../QueryProvider';
import { NewDispatchDialog } from './NewDispatchDialog';
import type { Dispatch, Lane } from '../api/types';
import { counts, eventText, laneNote, levels, nowLine } from './vocab';

const json = (b: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } }));
const AFK = { active: false, until: null, started: null, decisions: 0, held: 0, summary: null };
const S = { max: 2, grind: 'full', ci: 'wait', auto_merge: false, feature_branch: null, base_branch: null, model: null, effort: null } as const;
const lane = (n: number, o: Partial<Lane> = {}): Lane => ({
  key: `o/r#${n}`, repo: 'o/r', n, title: `Issue ${n}`, deps: [], stage: 'queued', pr: null, needs_you: null, held: null, gate: null,
  skip_reason: null, paused: null, hold_merge: null, limited_until: null, started_at: null, ended_at: null, session: null, tab: null,
  usage: { cost: 0, tokens: 0, seconds: 0 }, ...o,
});
const disp = (o: Partial<Dispatch> = {}): Dispatch => ({
  id: 'abc123abc123', epic: 'o/r#1', issues: null, title: 'Payments', runner: 'headless', state: 'running', settings: { ...S }, created_at: 1_700_000_000,
  ended_at: null, final_prs: null, totals: { cost: 1.5, tokens: 1200, seconds: 600 }, events: [{ at: 1_700_000_100, lane: 'o/r#2', kind: 'needs_you', text: 'waiting on you' }],
  lanes: [
    lane(2, { stage: 'implementing', needs_you: 'waiting on you', started_at: 1_700_000_000 }),
    lane(3, { stage: 'awaiting_merge', pr: 30 }),
    lane(4, { deps: ['o/r#2', 'o/r#3'] }),
  ],
  ...o,
});

let routes: Record<string, unknown>;
let posts: [string, unknown][];
let planSmall: unknown;
let startError: { error: string } | null;
let branchesError: string | null;
beforeEach(() => {
  localStorage.clear();
  posts = [];
  startError = null;
  branchesError = null;
  planSmall = { epic: null, issues: ['o/r#412', 'o/r#415'], title: 'Small changes: #412, #415', settings: S, runner: 'headless', lanes: [{ repo: 'o/r', n: 412, title: 'First', refined: true, deps: [] }, { repo: 'o/r', n: 415, title: 'Second', refined: true, deps: ['o/r#412'] }], waves: [['o/r#412'], ['o/r#415']], warnings: ['o/r#415: waits for o/r#9'] };
  routes = {
    '/api/repos': { repos: [{ slug: 'o/r', name: 'R', path: '/x' }], can_browse: false, scan_roots: [] },
    '/api/sessions': { sessions: [], limits: {}, usage: {}, afk: AFK },
    '/api/inbox': { items: [], afk: AFK, gh: { ok: true } },
    '/api/settings': { commands: [], default: 'work' },
    '/api/planning': { prds: [], fetched_at: 1, stale: false },
    '/api/dispatches': { dispatches: [disp(), disp({ id: 'old000000000', state: 'done', title: 'Old epic', lanes: [lane(9, { stage: 'closed' })] })] },
    '/api/dispatches/abc123abc123': disp(),
    '/api/github/branches': { branches: ['master', 'stage-hotfix', 'staging', 'dev'], default: 'master' },
  };
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollIntoView = () => {};
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const path = String(url).split('?')[0];
    if (init?.method === 'POST') {
      const body = init.body ? JSON.parse(init.body as string) : null;
      posts.push([path, body]);
      if (path === '/api/dispatches/plan' && body.issues) return json(planSmall);
      if (path === '/api/dispatches' && startError) return json(startError, 409);
      if (path === '/api/dispatches/plan')
        return json({ epic: 'o/r#1', title: 'Payments', settings: S, runner: 'headless', lanes: [{ repo: 'o/r', n: 2, title: 'A', refined: true, deps: [] }, { repo: 'o/r', n: 5, title: 'B', refined: false, deps: [] }], waves: [['o/r#2']], warnings: ['o/r#5: needs refine'] });
      return json(disp());
    }
    if (path === '/api/github/branches' && branchesError) return json({ error: branchesError }, 502);
    return path in routes ? json(routes[path]) : json({ error: 'nf' }, 404);
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('dispatch vocab', () => {
  it('levels lanes by dependency depth and survives cycles', () => {
    expect(levels([{ key: 'a', deps: [] }, { key: 'b', deps: ['a'] }, { key: 'c', deps: ['a', 'b', 'x'] }])).toEqual({ a: 0, b: 1, c: 2 });
    const cyc = levels([{ key: 'a', deps: ['b'] }, { key: 'b', deps: ['a'] }]);
    expect(Object.keys(cyc).sort()).toEqual(['a', 'b']);
  });
  it('counts and notes', () => {
    const c = counts(disp());
    expect(c).toMatchObject({ total: 3, active: 2, queued: 1, you: 2 });
    expect(laneNote(lane(1, { held: 'CI is red' }))).toEqual({ text: 'CI is red', tone: 'bad' });
    expect(laneNote(lane(1, { stage: 'awaiting_merge', hold_merge: true }))?.text).toBe('Merge held');
    expect(laneNote(lane(1, { stage: 'implementing' }))).toBeNull();
  });
  it('says what a lane does now, and what it needs from you', () => {
    const lanes = [lane(2, { stage: 'implementing' }), lane(4, { deps: ['o/r#2'] })];
    expect(nowLine(lanes[1], lanes).text).toBe('Starts after #2');
    expect(nowLine(lane(5), lanes).text).toBe('Starts when a slot frees up');
    expect(nowLine(lane(3, { stage: 'awaiting_merge', pr: 30 }), lanes)).toMatchObject({ ask: 'merge', text: 'PR #30 is ready for your merge' });
    expect(nowLine(lane(3, { needs_you: 'waiting on you', session: 's' }), lanes)).toMatchObject({ ask: 'open', text: 'Asked you a question' });
    expect(nowLine(lane(3, { stage: 'merge_gate', gate: 'CI is not green', pr: 9 }), lanes).text).toBe('Waiting for CI to pass');
    expect(nowLine(lane(3, { stage: 'merge_gate', gate: 'waiting for green CI (defer)', pr: 9 }), lanes).text).toBe('Waiting for green CI (defer)');
    expect(laneNote(lane(3, { stage: 'merge_gate', gate: 'waiting for green CI (defer)' }))?.text).toBe('waiting for green CI (defer)');
    expect(eventText({ kind: 'stage', text: 'queued -> implementing' })).toBe('started building');
  });
});

describe('Dispatches page', () => {
  it('shows running dispatches as cards and finished ones as history', async () => {
    window.location.hash = '#/dispatches?repo=o/r';
    render(<App />);
    const running = within(await screen.findByRole('region', { name: 'Running' }));
    expect(await running.findByText('Payments')).toBeTruthy();
    expect(running.getByText('PR #30 is ready for your merge')).toBeTruthy();
    expect(within(screen.getByRole('region', { name: 'History' })).getByText('Old epic')).toBeTruthy();
    expect(screen.getAllByRole('link', { name: /^Dispatches/ }).length).toBeGreaterThan(0); // in the rail (and the mobile nav)
  });

  it('previews an epic, warns, then starts it', async () => {
    window.location.hash = '#/dispatches?repo=o/r';
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: 'Run an epic' }));
    expect(screen.getByText(/use the herdr-dispatch skill/)).toBeTruthy();
    await userEvent.type(screen.getByLabelText('Epic'), '1');
    await userEvent.click(screen.getByRole('radio', { name: 'Simple' }));
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }));
    expect(await screen.findByText('o/r#5: needs refine')).toBeTruthy();
    expect(posts.at(-1)).toEqual(['/api/dispatches/plan', { epic: 'o/r#1', settings: { ...S, grind: 'simple' } }]);
    await userEvent.click(screen.getByRole('button', { name: 'Start 1 issue' }));
    await waitFor(() => expect(posts.at(-1)?.[0]).toBe('/api/dispatches'));
    expect(await screen.findByRole('heading', { name: 'Payments' })).toBeTruthy();
  });
});

describe('Dispatch CI mode', () => {
  it('sends the picked CI mode to the plan, defaulting to wait', async () => {
    window.location.hash = '#/dispatches?repo=o/r';
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: 'Run an epic' }));
    expect(screen.getByRole('radio', { name: 'Wait' }).getAttribute('aria-checked')).toBe('true');
    await userEvent.click(screen.getByRole('radio', { name: 'Ignore' }));
    expect(screen.getByText('CI never blocks: red CI can merge.')).toBeTruthy();
    await userEvent.click(screen.getByRole('radio', { name: 'Defer' }));
    await userEvent.type(screen.getByLabelText('Epic'), '1');
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await screen.findByText('o/r#5: needs refine');
    expect(posts.find(([p]) => p === '/api/dispatches/plan')?.[1]).toEqual({ epic: 'o/r#1', settings: { ...S, ci: 'defer' } });
  });

  it('shows the mode on the dispatch, wait when absent, and saves a live pick', async () => {
    routes['/api/dispatches/abc123abc123'] = disp({ settings: { ...S, ci: 'defer' } });
    window.location.hash = '#/dispatches/abc123abc123?repo=o/r';
    const a = render(<App />);
    expect(await screen.findByText(/CI: defer/)).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /Settings/ }));
    await userEvent.click(screen.getByRole('radio', { name: 'Ignore' }));
    await waitFor(() => expect(posts.at(-1)).toEqual(['/api/dispatches/abc123abc123/settings', { ci: 'ignore' }]));
    a.unmount();
    const { ci: _ci, ...noCi } = S;
    routes['/api/dispatches/abc123abc123'] = disp({ settings: noCi });
    render(<App />);
    expect(await screen.findByText(/CI: wait/)).toBeTruthy();
  });
});

describe('Dispatch model and effort', () => {
  it('preselects the saved pair and sends a new pick to the plan', async () => {
    routes['/api/settings'] = { commands: [], default: 'work', run_model: 'sonnet', run_effort: 'low' };
    window.location.hash = '#/dispatches?repo=o/r';
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: 'Run an epic' }));
    const model = screen.getByLabelText('Model') as HTMLSelectElement;
    await waitFor(() => expect(model.value).toBe('sonnet'));
    expect((screen.getByLabelText('Effort') as HTMLSelectElement).value).toBe('low');
    await userEvent.selectOptions(model, 'opus');
    await userEvent.selectOptions(screen.getByLabelText('Effort'), 'high');
    await userEvent.type(screen.getByLabelText('Epic'), '1');
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await screen.findByText('o/r#5: needs refine');
    expect(posts.find(([p]) => p === '/api/dispatches/plan')?.[1]).toEqual({ epic: 'o/r#1', settings: { ...S, model: 'opus', effort: 'high' } });
  });

  it('saves a live pick and keeps a model outside the list', async () => {
    routes['/api/dispatches/abc123abc123'] = disp({ settings: { ...S, model: 'claude-opus-4-1' } });
    window.location.hash = '#/dispatches/abc123abc123?repo=o/r';
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: /Settings/ }));
    const model = screen.getByLabelText('Model') as HTMLSelectElement;
    expect(model.value).toBe('claude-opus-4-1');
    await userEvent.selectOptions(screen.getByLabelText('Effort'), 'max');
    await waitFor(() => expect(posts).toContainEqual(['/api/dispatches/abc123abc123/settings', { effort: 'max' }]));
  });
});

describe('Dispatch page', () => {
  it('shows lanes as a graph, switches to a list, opens a lane and acts on it', async () => {
    window.location.hash = '#/dispatches/abc123abc123?repo=o/r';
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Payments' })).toBeTruthy();
    const graph = screen.getByRole('group', { name: 'Issues by what they wait for' });
    expect(within(graph).getByText('Starts first')).toBeTruthy();
    expect(within(graph).getByText('Then')).toBeTruthy();
    expect(screen.getByText('0 of 3 issues done. 2 in progress and 1 waiting their turn.')).toBeTruthy();
    const asks = within(screen.getByRole('region', { name: 'Needs you' }));
    expect(asks.getByText('2 issues need you')).toBeTruthy();
    expect(asks.getByRole('button', { name: 'Merge' })).toBeTruthy();
    await userEvent.click(screen.getByRole('radio', { name: 'List' }));
    expect(screen.getByRole('table')).toBeTruthy();
    expect(localStorage.getItem('aiw.dispatch.view')).toBe('list');
    await userEvent.click(within(screen.getByRole('table')).getByRole('button', { name: /#3 Issue 3/ }));
    const panel = within(await screen.findByRole('complementary', { name: 'Lane #3' }));
    await userEvent.click(panel.getByRole('button', { name: 'Issue actions' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Hold the merge' }));
    await waitFor(() => expect(posts.at(-1)).toEqual(['/api/dispatches/abc123abc123/lane', { lane: 'o/r#3', action: 'hold' }]));
    await userEvent.click(panel.getByRole('button', { name: /Merge PR #30/ }));
    await userEvent.click(await screen.findByRole('button', { name: 'Merge' }));
    await waitFor(() => expect(posts.at(-1)).toEqual(['/api/dispatches/abc123abc123/lane', { lane: 'o/r#3', action: 'merge' }]));
  });

  it('moves through lanes by key, opens and follows the lane panel, and Esc closes it', async () => {
    window.location.hash = '#/dispatches/abc123abc123?repo=o/r';
    render(<App />);
    await screen.findByRole('heading', { name: 'Payments' });
    await userEvent.keyboard('j');
    await userEvent.keyboard('{Enter}');
    expect(await screen.findByRole('complementary', { name: 'Lane #2' })).toBeTruthy();
    expect(window.location.hash).toContain('lane=o%2Fr%232');
    await userEvent.keyboard('j');
    expect(await screen.findByRole('complementary', { name: 'Lane #3' })).toBeTruthy();
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('complementary', { name: /^Lane/ })).toBeNull());
    expect(document.activeElement?.getAttribute('data-lane')).toBe('o/r#3');
  });

  it('follows the table order in the list view', async () => {
    localStorage.setItem('aiw.dispatch.view', 'list');
    routes['/api/dispatches/abc123abc123'] = disp({ lanes: [lane(4, { deps: ['o/r#2'] }), lane(2, { stage: 'implementing' })] });
    window.location.hash = '#/dispatches/abc123abc123?repo=o/r';
    render(<App />);
    await screen.findByRole('table');
    await userEvent.keyboard('j');
    await userEvent.keyboard('{Enter}');
    expect(await screen.findByRole('complementary', { name: 'Lane #4' })).toBeTruthy();
  });

  it('merges the selected lane with M and cancels the dispatch with X', async () => {
    window.location.hash = '#/dispatches/abc123abc123?repo=o/r';
    render(<App />);
    await screen.findByRole('heading', { name: 'Payments' });
    await userEvent.keyboard('jj'); // lane #3 at awaiting_merge
    await userEvent.keyboard('m');
    expect((await screen.findByRole('alertdialog')).textContent).toContain('Merge PR #30?');
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    await userEvent.keyboard('x');
    expect((await screen.findByRole('alertdialog')).textContent).toContain('Cancel this dispatch?');
  });

  it('edits settings live and pauses the dispatch', async () => {
    window.location.hash = '#/dispatches/abc123abc123?repo=o/r';
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: /Settings/ }));
    await userEvent.click(screen.getByRole('switch', { name: 'Auto-merge' }));
    await waitFor(() => expect(posts.at(-1)).toEqual(['/api/dispatches/abc123abc123/settings', { auto_merge: true }]));
    await userEvent.click(screen.getByRole('button', { name: 'More at once' }));
    await waitFor(() => expect(posts.at(-1)).toEqual(['/api/dispatches/abc123abc123/settings', { max: 3 }]));
    await userEvent.click(screen.getByRole('button', { name: /Pause/ }));
    await waitFor(() => expect(posts.at(-1)).toEqual(['/api/dispatches/abc123abc123/state', { state: 'paused' }]));
  });

  it('offers the end actions once every lane is done', async () => {
    routes['/api/dispatches/abc123abc123'] = disp({ state: 'done', settings: { ...S, feature_branch: 'feature/pay' }, lanes: [lane(2, { stage: 'closed' })] });
    window.location.hash = '#/dispatches/abc123abc123?repo=o/r';
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: /Open PR from feature\/pay into the default branch/ }));
    await waitFor(() => expect(posts.some(([p, b]) => p === '/api/dispatches/abc123abc123/end' && (b as { action: string }).action === 'open-pr')).toBe(true));
    expect(posts.some(([p]) => p === '/api/dispatches/abc123abc123/seen')).toBe(true);
  });

  it('names the base branch on the Open PR button', async () => {
    routes['/api/dispatches/abc123abc123'] = disp({ state: 'done', settings: { ...S, feature_branch: 'feature/pay', base_branch: 'staging' }, lanes: [lane(2, { stage: 'closed' })] });
    window.location.hash = '#/dispatches/abc123abc123?repo=o/r';
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: /Open PR from feature\/pay into staging/ }));
    await waitFor(() => expect(posts.some(([p, b]) => p === '/api/dispatches/abc123abc123/end' && (b as { action: string }).action === 'open-pr')).toBe(true));
  });
});

const SMALL = { epic: null, issues: ['o/r#412', 'o/r#415'], title: 'Small changes: #412, #415' };

describe('Issue-list dispatches', () => {
  it('shows the title on its card and the repo under it in History', async () => {
    routes['/api/dispatches'] = { dispatches: [disp(), disp({ id: 'sm1', ...SMALL }), disp({ id: 'sm2', state: 'done', ...SMALL })] };
    window.location.hash = '#/dispatches?repo=o/r';
    render(<App />);
    expect((await screen.findAllByText('Small changes: #412, #415')).length).toBe(2);
    expect(within(screen.getByRole('table')).getByText('o/r')).toBeTruthy();
    expect(screen.getByText('Payments')).toBeTruthy();
  });

  it('titles its page, links the repo and offers no end actions once done', async () => {
    routes['/api/dispatches/abc123abc123'] = disp({ state: 'done', ...SMALL, settings: { ...S, feature_branch: 'feature/pay' }, lanes: [lane(412, { stage: 'closed' })] });
    window.location.hash = '#/dispatches/abc123abc123?repo=o/r';
    render(<App />);
    expect((await screen.findByRole('heading', { level: 1 })).textContent).toBe('Small changes: #412, #415');
    expect(screen.getByRole('link', { name: 'o/r' }).getAttribute('href')).toBe('https://github.com/o/r');
    expect(screen.getByText('Small changes', { selector: 'nav span' })).toBeTruthy();
    expect(screen.queryByText(/Epic #/)).toBeNull();
    expect(screen.getByText('Every issue is done.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Run QA|Open PR|Grind/ })).toBeNull();
    await waitFor(() => expect(posts.some(([p]) => p === '/api/dispatches/abc123abc123/seen')).toBe(true));
  });

  it('does not break the Features page while running', async () => {
    routes['/api/dispatches'] = { dispatches: [disp({ id: 'sm1', ...SMALL })] };
    window.location.hash = '#/features?repo=o/r';
    render(<App />);
    await waitFor(() => expect(document.body.textContent).not.toContain('Something went wrong'));
  });
});

describe('Inbox dispatch rows', () => {
  it('words a finished issue-list dispatch without QA, and an epic one as before', async () => {
    routes['/api/inbox'] = {
      afk: AFK, gh: { ok: true },
      items: [
        { key: 'x', group: 'decide', type: 'dispatch_done', repo: 'o/r', at: null, dispatch: 'sm1', epic: null, title: 'Small changes: #412, #415', feature_branch: null, final_prs: {} },
        { key: 'y', group: 'decide', type: 'dispatch_done', repo: 'o/r', at: null, dispatch: 'abc123abc123', epic: 'o/r#1', feature_branch: null, final_prs: {} },
      ],
    };
    window.location.hash = '#/inbox?repo=o/r';
    render(<App />);
    expect(await screen.findByText('Every lane of Small changes: #412, #415 is done')).toBeTruthy();
    expect(screen.getByText('Every issue is done.')).toBeTruthy();
    expect(screen.getByText('Every lane of o/r#1 is done')).toBeTruthy();
    expect(screen.getAllByText(/Run QA on the whole feature/).length).toBe(1);
  });

  it('renders a lane that needs you and a merge decision', async () => {
    routes['/api/inbox'] = {
      afk: AFK, gh: { ok: true },
      items: [
        { key: 'a', group: 'answer', type: 'dispatch_lane', repo: 'o/r', at: null, dispatch: 'abc123abc123', lane: 'o/r#2', issue: 2, title: 'Issue 2', stage: 'implementing', pr: null, reason: 'waiting on you' },
        { key: 'b', group: 'decide', type: 'dispatch_lane', repo: 'o/r', at: null, dispatch: 'abc123abc123', lane: 'o/r#3', issue: 3, title: 'Issue 3', stage: 'awaiting_merge', pr: 30, reason: 'PR #30 is ready to merge' },
      ],
    };
    window.location.hash = '#/inbox?repo=o/r';
    render(<App />);
    expect(await screen.findByText('#2 Issue 2')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Merge' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Merge', hidden: false }));
    await waitFor(() => expect(posts.at(-1)).toEqual(['/api/dispatches/abc123abc123/lane', { lane: 'o/r#3', action: 'merge' }]));
  });
});

describe('Run small changes dialog', () => {
  const PICKED = [{ n: 412, title: 'First' }, { n: 415, title: 'Second' }];
  const open = (onOpenChange = vi.fn()) => {
    render(
      <QueryProvider>
        <MemoryRouter initialEntries={['/x?repo=o/r']}>
          <Routes>
            <Route path="/dispatches/:id" element={<p>dispatch page</p>} />
            <Route path="*" element={<NewDispatchDialog open onOpenChange={onOpenChange} issues={PICKED} />} />
          </Routes>
        </MemoryRouter>
      </QueryProvider>,
    );
    return onOpenChange;
  };

  it('shows the picked issues as chips, with no epic or feature branch field', async () => {
    open();
    expect(await screen.findByText('Run small changes')).toBeTruthy();
    expect(screen.getByText('#412 First')).toBeTruthy();
    expect(screen.getByText('#415 Second')).toBeTruthy();
    expect(screen.queryByLabelText('Epic')).toBeNull();
    expect(screen.queryByText('Feature branch')).toBeNull();
    expect(screen.queryByText(/herdr/)).toBeNull();
  });

  it('previews waves and warnings, then starts and opens the dispatch page', async () => {
    const onOpenChange = open();
    await userEvent.click(await screen.findByRole('button', { name: 'Preview' }));
    expect(await screen.findByText('o/r#415: waits for o/r#9')).toBeTruthy();
    expect(screen.getByText('Starts first')).toBeTruthy();
    const body = { issues: ['o/r#412', 'o/r#415'], settings: { ...S } };
    expect(posts.at(-1)).toEqual(['/api/dispatches/plan', body]);
    await userEvent.click(screen.getByRole('button', { name: 'Start 2 issues' }));
    expect(await screen.findByText('dispatch page')).toBeTruthy();
    expect(posts.at(-1)).toEqual(['/api/dispatches', body]);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('says so when none of the picked issues is open, and cannot start', async () => {
    planSmall = { ...(planSmall as object), lanes: [], waves: [], warnings: [] };
    open();
    await userEvent.click(await screen.findByRole('button', { name: 'Preview' }));
    expect(await screen.findByText(/none of the picked issues is open/)).toBeTruthy();
    expect((screen.getByRole('button', { name: /^Start/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('keeps the dialog open when start answers 409', async () => {
    startError = { error: 'o/r#412 runs in dispatch abc' };
    const onOpenChange = open();
    await userEvent.click(await screen.findByRole('button', { name: 'Preview' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Start 2 issues' }));
    await waitFor(() => expect(posts.at(-1)?.[0]).toBe('/api/dispatches'));
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByText('Run small changes')).toBeTruthy();
  });

  it('hides Feature branch in the live settings of an issue-list dispatch only', async () => {
    routes['/api/dispatches/abc123abc123'] = disp({ ...SMALL });
    window.location.hash = '#/dispatches/abc123abc123?repo=o/r';
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: /Settings/ }));
    expect(screen.queryByText('Feature branch')).toBeNull();
    cleanup();
    routes['/api/dispatches/abc123abc123'] = disp();
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: /Settings/ }));
    expect(screen.getByText('Feature branch')).toBeTruthy();
  });
});

describe('Base branch picker', () => {
  const open = (props: { epic?: string; issues?: { n: number; title: string }[] } = {}) =>
    render(
      <QueryProvider>
        <MemoryRouter initialEntries={['/x?repo=o/r']}>
          <NewDispatchDialog open onOpenChange={vi.fn()} {...props} />
        </MemoryRouter>
      </QueryProvider>,
    );
  const field = () => screen.getByRole('button', { name: /^Base branch/ }) as HTMLButtonElement;
  const sentBase = async () => {
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(posts.some(([p]) => p === '/api/dispatches/plan')).toBe(true));
    return (posts.at(-1)![1] as { settings: { base_branch: string | null } }).settings.base_branch;
  };

  it('is disabled with a hint until an epic is entered', async () => {
    open();
    expect(field().disabled).toBe(true);
    expect(screen.getByText('Pick an epic first')).toBeTruthy();
    await userEvent.type(screen.getByLabelText('Epic'), '7');
    await waitFor(() => expect(field().disabled).toBe(false));
  });

  it('filters on typing, lists the default first, and sends the pick', async () => {
    open({ epic: 'o/r#1' });
    await userEvent.click(field());
    expect(await screen.findByText('staging')).toBeTruthy();
    expect(screen.getByText('default')).toBeTruthy();
    await userEvent.type(screen.getByPlaceholderText('Find a branch…'), 'STA');
    expect(screen.getByText('stage-hotfix')).toBeTruthy();
    expect(screen.queryByText('master')).toBeNull();
    expect(screen.queryByText('dev')).toBeNull();
    await userEvent.click(screen.getByText('staging'));
    expect(await sentBase()).toBe('staging');
  });

  it('sends null untouched, and after picking the repo base again', async () => {
    open({ epic: 'o/r#1' });
    expect(await sentBase()).toBeNull();
    cleanup();
    posts = [];
    open({ epic: 'o/r#1' });
    await userEvent.click(field());
    await userEvent.click(await screen.findByText('staging'));
    await userEvent.click(field());
    await userEvent.click(await screen.findByText('Repo’s base (default)'));
    expect(await sentBase()).toBeNull();
  });

  it('has no free-text value: a name outside the list picks nothing', async () => {
    open({ epic: 'o/r#1' });
    await userEvent.click(field());
    await userEvent.type(await screen.findByPlaceholderText('Find a branch…'), 'nope{Enter}');
    expect(screen.getByText('No branch matches.')).toBeTruthy();
    await userEvent.keyboard('{Escape}');
    expect(await sentBase()).toBeNull();
  });

  it('shows the load error and keeps the repo base', async () => {
    branchesError = 'boom';
    open({ epic: 'o/r#1' });
    expect(await screen.findByText('boom', {}, { timeout: 4000 })).toBeTruthy(); // the query retries once
    expect(await sentBase()).toBeNull();
  });

  it('shows a loading state while the list loads', async () => {
    const f = vi.mocked(fetch);
    const base = f.getMockImplementation()!;
    f.mockImplementation(((url: string, init?: RequestInit) => (String(url).startsWith('/api/github/branches') ? new Promise(() => {}) : base(url, init))) as typeof fetch);
    open({ epic: 'o/r#1' });
    expect(await screen.findByRole('button', { name: 'Base branch: Loading branches…' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Preview' })).toBeTruthy();
  });

  it('is shown for small changes and sends the pick', async () => {
    open({ issues: [{ n: 412, title: 'First' }] });
    await userEvent.click(field());
    await userEvent.click(await screen.findByText('staging'));
    expect(await sentBase()).toBe('staging');
  });

  it('shows the base read-only on the dispatch page, "Repo’s base" when absent', async () => {
    routes['/api/dispatches/abc123abc123'] = disp({ settings: { ...S, base_branch: 'staging' } });
    window.location.hash = '#/dispatches/abc123abc123?repo=o/r';
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: /Settings/ }));
    expect(screen.getByText('staging')).toBeTruthy();
    cleanup();
    const { base_branch: _b, ...old } = S as Record<string, unknown>;
    routes['/api/dispatches/abc123abc123'] = disp({ settings: old as never });
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: /Settings/ }));
    expect(screen.getByText('Repo’s base')).toBeTruthy();
  });
});
