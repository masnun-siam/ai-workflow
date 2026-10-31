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
const S = { max: 2, grind: 'full', ci: 'wait', auto_merge: false, feature_branch: null, base_branch: null, model: null, effort: null, account: null } as const;
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
  const done = (id: string, o: Partial<Dispatch> = {}) => disp({ id, state: 'done', title: id, lanes: [lane(9, { stage: 'closed' })], ...o });
  const running = (id: string, o: Partial<Dispatch> = {}) => disp({ id, title: id, lanes: [lane(5, { stage: 'implementing' })], ...o });
  const titles = () => screen.getAllByRole('row').slice(1).map((r) => within(r).getByRole('link').textContent);
  const tab = (name: RegExp) => screen.getByRole('button', { name });
  const DAY = 86_400;
  const NOW = 1_700_000_000;
  const TWO_REPOS = { repos: [{ slug: 'o/r', name: 'R', path: '/x' }, { slug: 'o/q', name: 'Q', path: '/y' }], can_browse: false, scan_roots: [] };

  it('shows live and finished dispatches in one table with no cards or sections', async () => {
    window.location.hash = '#/dispatches?repo=o/r';
    render(<App />);
    const table = await screen.findByRole('table');
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['State', 'Dispatch', 'Issues', 'Took', 'Spent']);
    expect(within(table).getByRole('link', { name: 'Payments' }).getAttribute('href')).toBe('#/dispatches/abc123abc123');
    expect(within(table).getByRole('link', { name: 'Old epic' })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Running' })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'History' })).toBeNull();
    expect(document.querySelector('.page-head .sub')).toBeNull();
    expect(screen.getByRole('button', { name: 'Run an epic' })).toBeTruthy();
    expect(screen.getAllByRole('link', { name: /^Dispatches/ }).length).toBeGreaterThan(0); // in the rail (and the mobile nav)
  });

  it('shows Needs you on a paused dispatch waiting for its merge, and Cancelled on a held one', async () => {
    routes['/api/dispatches'] = { dispatches: [
      disp({ id: 'p1', state: 'paused', title: 'Paused one', lanes: [lane(3, { stage: 'awaiting_merge', pr: 30 })] }),
      disp({ id: 'c1', state: 'cancelled', title: 'Cancelled one', lanes: [lane(4, { held: 'CI is red' })] }),
    ] };
    window.location.hash = '#/dispatches';
    render(<App />);
    const paused = (await screen.findByRole('link', { name: 'Paused one' })).closest('tr')!;
    const cancelled = screen.getByRole('link', { name: 'Cancelled one' }).closest('tr')!;
    expect(within(paused).getByText('Needs you')).toBeTruthy();
    expect(paused.textContent).toContain('#3 PR #30 is ready for your merge');
    expect(within(cancelled).getByText('Cancelled')).toBeTruthy();
    expect(within(cancelled).queryByText('Needs you')).toBeNull();
    expect(cancelled.textContent).not.toContain('CI is red');
  });

  it('shows the first issue that needs you and how many more', async () => {
    routes['/api/dispatches'] = { dispatches: [disp({ lanes: [lane(2, { stage: 'implementing', needs_you: 'waiting on you' }), lane(3, { stage: 'awaiting_merge', pr: 30 }), lane(4, { held: 'CI is red' })] })] };
    window.location.hash = '#/dispatches';
    render(<App />);
    expect((await screen.findByText(/Asked you a question/)).textContent).toBe('#2 Asked you a question and 2 more');
  });

  it('shows the issue bar in order, sized by count, with a text label', async () => {
    routes['/api/dispatches'] = { dispatches: [disp({ lanes: [
      ...[1, 2, 3].map((n) => lane(n, { stage: 'closed' })), lane(4, { stage: 'implementing' }), lane(5, { stage: 'grinding' }), lane(6), lane(7),
    ] })] };
    window.location.hash = '#/dispatches';
    render(<App />);
    const bar = await screen.findByRole('img', { name: '3 of 7 done' });
    expect(bar.closest('td')!.textContent).toContain('3/7');
    expect([...bar.children].map((i) => [i.className, (i as HTMLElement).style.flexGrow])).toEqual([['s-merged', '3'], ['s-build', '2'], ['s-ready', '2']]);
  });

  it('shows the totals, a dash under Spent for herdr, and the date and skipped count once finished', async () => {
    routes['/api/dispatches'] = { dispatches: [
      running('headless1', { totals: { cost: 1.5, tokens: 1, seconds: 600 } }),
      done('herdr1', { runner: 'herdr', lanes: [lane(9, { stage: 'closed' }), lane(8, { stage: 'skipped' })] }),
    ] };
    window.location.hash = '#/dispatches';
    render(<App />);
    const cells = (name: string) => [...screen.getByRole('link', { name }).closest('tr')!.querySelectorAll('td.num')].map((c) => c.textContent);
    await screen.findByRole('link', { name: 'herdr1' });
    expect(cells('headless1')).toEqual(['10m', '$1.50']);
    expect(cells('herdr1')[1]).toBe('—');
    const line = screen.getByRole('link', { name: 'herdr1' }).closest('td')!.querySelector('.strip-m')!;
    expect(line.textContent).toContain('r');
    expect(line.textContent).toContain(new Date(NOW * 1000).toLocaleDateString());
    expect(line.textContent).toContain('1 skipped');
    expect(screen.getByRole('link', { name: 'headless1' }).closest('td')!.querySelector('.strip-m')!.textContent).toBe('r');
  });

  it('leaves the repo line out of a record with neither epic nor issues', async () => {
    routes['/api/dispatches'] = { dispatches: [done('blank', { epic: null, issues: null })] };
    window.location.hash = '#/dispatches';
    render(<App />);
    expect((await screen.findByRole('link', { name: 'blank' })).closest('td')!.querySelector('.strip-m')).toBeNull();
  });

  it('orders Needs you, Running, Paused, then finished and cancelled together, newest first', async () => {
    routes['/api/dispatches'] = { dispatches: [
      done('finished-old', { created_at: NOW - 7 * DAY }),
      disp({ id: 'cancelled-new', title: 'cancelled-new', state: 'cancelled', created_at: NOW - DAY, lanes: [lane(9, { stage: 'closed' })] }),
      disp({ id: 'paused-new', title: 'paused-new', state: 'paused', created_at: NOW, lanes: [lane(5, { stage: 'implementing' })] }),
      running('running-old', { created_at: NOW - 2 * DAY }),
      running('running-new', { created_at: NOW }),
      disp({ id: 'needs-old', title: 'needs-old', created_at: NOW - 7 * DAY }),
    ] };
    window.location.hash = '#/dispatches';
    render(<App />);
    await screen.findByRole('table');
    expect(titles()).toEqual(['needs-old', 'running-new', 'running-old', 'paused-new', 'cancelled-new', 'finished-old']);
  });

  it('keeps the tab in the URL: click, Back, reload; a dispatch needing you counts under Live too', async () => {
    routes['/api/dispatches'] = { dispatches: [disp(), running('run'), done('fin')] };
    window.location.hash = '#/dispatches?repo=o/r';
    const view = render(<App />);
    await screen.findByRole('table');
    expect(tab(/^All \d/).textContent).toBe('All 3');
    expect(tab(/^Needs you/).textContent).toBe('Needs you 1');
    expect(tab(/^Live/).textContent).toBe('Live 2');
    expect(tab(/^Finished/).textContent).toBe('Finished 1');
    expect(tab(/^All \d/).getAttribute('aria-pressed')).toBe('true');
    await userEvent.click(tab(/^Needs you/));
    await waitFor(() => expect(window.location.hash).toContain('show=needs'));
    expect(window.location.hash).toContain('repo=o/r');
    expect(titles()).toEqual(['Payments']);
    await userEvent.click(tab(/^Live/));
    await waitFor(() => expect(titles()).toEqual(['Payments', 'run']));
    await userEvent.click(tab(/^Needs you/));
    await waitFor(() => expect(titles()).toEqual(['Payments']));
    view.unmount();
    render(<App />); // a reload keeps it
    await screen.findByRole('table');
    expect(tab(/^Needs you/).getAttribute('aria-pressed')).toBe('true');
    expect(titles()).toEqual(['Payments']);
    await userEvent.click(tab(/^All \d/));
    await waitFor(() => expect(window.location.hash).not.toContain('show='));
    expect(titles().length).toBe(3);
    window.history.back();
    await waitFor(() => expect(window.location.hash).toContain('show=needs'));
    await waitFor(() => expect(titles()).toEqual(['Payments']));
  });

  it('reads an unknown ?show= as All', async () => {
    window.location.hash = '#/dispatches?show=nonsense';
    render(<App />);
    await screen.findByRole('table');
    expect(tab(/^All \d/).getAttribute('aria-pressed')).toBe('true');
    expect(titles().length).toBe(2);
  });

  it('narrows rows and tab counts to ?only=, in any case, and All repos clears it', async () => {
    routes['/api/repos'] = TWO_REPOS;
    routes['/api/dispatches'] = { dispatches: [running('r-run'), running('q-run', { epic: 'O/Q#1' }), done('q-fin', { epic: null, issues: ['o/q#2'] }), done('blank', { epic: null, issues: null })] };
    window.location.hash = '#/dispatches?only=o/Q';
    render(<App />);
    await screen.findByRole('link', { name: 'q-run' });
    await waitFor(() => expect(titles()).toEqual(['q-run', 'q-fin']));
    expect(tab(/^All \d/).textContent).toBe('All 2');
    expect(tab(/^Live/).textContent).toBe('Live 1');
    expect(tab(/^Finished/).textContent).toBe('Finished 1');
    expect(screen.getByRole('group', { name: 'Show dispatches from' })).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'All repos' }));
    await waitFor(() => expect(window.location.hash).not.toContain('only='));
    await waitFor(() => expect(titles().length).toBe(4));
    expect(tab(/^All \d/).textContent).toBe('All 4');
  });

  it('J selects the first visible row on a filtered tab, after an earlier selection too; Enter opens it', async () => {
    routes['/api/dispatches'] = { dispatches: [running('run1', { created_at: NOW }), running('run2', { created_at: NOW - 1 }), done('fin1', { created_at: NOW - 2 }), done('fin2', { created_at: NOW - 3 })] };
    window.location.hash = '#/dispatches';
    render(<App />);
    await screen.findByRole('table');
    expect(document.querySelector('[data-selected]')).toBeNull();
    await userEvent.keyboard('jjj');
    expect(screen.getByRole('link', { name: 'fin1' }).closest('tr')!.hasAttribute('data-selected')).toBe(true);
    await userEvent.keyboard('k');
    expect(screen.getByRole('link', { name: 'run2' }).closest('tr')!.hasAttribute('data-selected')).toBe(true);
    await userEvent.click(tab(/^Finished/));
    await waitFor(() => expect(titles()).toEqual(['fin1', 'fin2']));
    await waitFor(() => expect(document.querySelector('[data-selected]')).toBeNull());
    await userEvent.keyboard('j');
    expect(screen.getByRole('link', { name: 'fin1' }).closest('tr')!.hasAttribute('data-selected')).toBe(true);
    await userEvent.keyboard('{Enter}');
    await waitFor(() => expect(window.location.hash).toBe('#/dispatches/fin1'));
  });

  it('opens the dispatch from its row and from its name', async () => {
    routes['/api/dispatches'] = { dispatches: [running('run1')] };
    routes['/api/dispatches/run1'] = running('run1');
    window.location.hash = '#/dispatches';
    render(<App />);
    await userEvent.click((await screen.findByRole('table')).querySelector('td')!);
    await waitFor(() => expect(window.location.hash).toBe('#/dispatches/run1'));
    window.location.hash = '#/dispatches';
    await userEvent.click(await screen.findByRole('link', { name: 'run1' }));
    await waitFor(() => expect(window.location.hash).toBe('#/dispatches/run1'));
  });

  it('shows one line for an empty filter and keeps the tabs clickable', async () => {
    routes['/api/repos'] = TWO_REPOS;
    routes['/api/dispatches'] = { dispatches: [running('run')] };
    window.location.hash = '#/dispatches?show=needs';
    render(<App />);
    expect(await screen.findByText('Nothing needs you.')).toBeTruthy();
    expect(screen.queryByRole('table')).toBeNull();
    await userEvent.click(tab(/^Finished/));
    expect(await screen.findByText('Nothing has finished yet.')).toBeTruthy();
    await userEvent.click(tab(/^Live/));
    expect(await screen.findByRole('table')).toBeTruthy();
    cleanup();
    window.location.hash = '#/dispatches?only=o/q&show=live';
    render(<App />);
    expect(await screen.findByText('Nothing is live.')).toBeTruthy();
    await userEvent.click(tab(/^All \d/));
    expect(await screen.findByText('No dispatches in this repo.')).toBeTruthy();
  });

  it('shows a skeleton while loading, and a failed first load shows the banner and no empty state', async () => {
    let fail = () => {};
    const gate = new Promise<void>((r) => { fail = r; });
    const real = fetch;
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => (String(url).split('?')[0] === '/api/dispatches' ? gate.then(() => json({ error: 'boom' }, 500)) : real(url, init))));
    window.location.hash = '#/dispatches';
    render(<App />);
    await waitFor(() => expect(document.querySelector('.content-inner .skel')).toBeTruthy());
    expect(screen.queryByRole('group', { name: 'Show dispatches' })).toBeNull();
    fail();
    expect(await screen.findByText(/Could not load dispatches/, undefined, { timeout: 4000 })).toBeTruthy();
    expect(screen.queryByText('Nothing is running')).toBeNull();
    expect(document.querySelector('.content-inner .skel')).toBeNull();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy();
  });

  it('with no dispatches shows Nothing is running and hides the tabs', async () => {
    routes['/api/dispatches'] = { dispatches: [] };
    window.location.hash = '#/dispatches?show=needs';
    render(<App />);
    expect(await screen.findByText('Nothing is running')).toBeTruthy();
    expect(screen.queryByRole('group', { name: 'Show dispatches' })).toBeNull();
    expect(screen.queryByText('Nothing needs you.')).toBeNull();
  });

  it('?new= opens the dialog on that epic, and closing it keeps ?show=', async () => {
    window.location.hash = '#/dispatches?new=o/r%231&show=live';
    render(<App />);
    expect((await screen.findByLabelText('Epic') as HTMLInputElement).value).toBe('o/r#1');
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(window.location.hash).not.toContain('new='));
    expect(window.location.hash).toContain('show=live');
  });

  it('J/K/Enter do nothing with no dispatches', async () => {
    routes['/api/dispatches'] = { dispatches: [] };
    window.location.hash = '#/dispatches';
    render(<App />);
    await screen.findByText('Nothing is running');
    await userEvent.keyboard('jk{Enter}');
    expect(document.querySelector('[data-selected]')).toBeNull();
    expect(window.location.hash).toBe('#/dispatches');
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
  it('shows lanes as building now, up next and done, opens a lane and acts on it', async () => {
    routes['/api/dispatches/abc123abc123'] = disp({ lanes: [...disp().lanes, lane(5, { stage: 'closed', pr: 50, started_at: 1_700_000_000, ended_at: 1_700_003_600, usage: { cost: 2.5, tokens: 1, seconds: 3600 } })] });
    window.location.hash = '#/dispatches/abc123abc123?repo=o/r';
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Payments' })).toBeTruthy();
    expect(screen.getByRole('img', { name: '1 of 4 done, 2 building, 1 waiting' })).toBeTruthy();
    const building = within(screen.getByRole('region', { name: 'Building now' }));
    expect(building.getAllByRole('button').map((b) => b.getAttribute('data-lane'))).toEqual(['o/r#2', 'o/r#3']);
    expect(within(screen.getByRole('region', { name: 'Up next' })).getByText('Starts after #2 and #3')).toBeTruthy();
    const done = within(screen.getByRole('region', { name: 'Done' }));
    expect(done.getByText('PR #50')).toBeTruthy();
    expect(done.getByText('1h 0m')).toBeTruthy();
    expect(done.getByText('$2.50')).toBeTruthy();
    const asks = within(screen.getByRole('region', { name: 'Needs you' }));
    expect(asks.getByText('2 issues need you')).toBeTruthy();
    expect(asks.getByRole('button', { name: 'Merge' })).toBeTruthy();
    expect(screen.queryByText('Nothing needs you')).toBeNull();
    await userEvent.click(building.getByRole('button', { name: /Issue 3/ }));
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

  it('trims the epic name off issue titles and orders up next ready first', async () => {
    routes['/api/dispatches/abc123abc123'] = disp({ lanes: [lane(4, { title: 'Payments: refunds', deps: ['o/r#2'] }), lane(2, { stage: 'implementing' }), lane(6, { title: 'Payments: receipts' })] });
    window.location.hash = '#/dispatches/abc123abc123?repo=o/r';
    render(<App />);
    const next = within(await screen.findByRole('region', { name: 'Up next' }));
    expect(next.getAllByRole('button').map((b) => b.textContent)).toEqual(['#6receiptsStarts when a slot frees up', '#4refundsStarts after #2']);
    expect(screen.getByText('Nothing needs you')).toBeTruthy();
    await userEvent.keyboard('jj');
    await userEvent.keyboard('{Enter}');
    expect(await screen.findByRole('complementary', { name: 'Lane #6' })).toBeTruthy();
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

  it('picks the account in the dialog and the live editor, and hides it with one account', async () => {
    const two = { commands: [{ label: 'work', cmd: 'claude' }, { label: 'home', cmd: 'cc-profile home' }], default: 'work' };
    routes['/api/settings'] = two;
    window.location.hash = '#/dispatches?repo=o/r';
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: 'Run an epic' }));
    expect((await screen.findByRole('radio', { name: 'work' })).getAttribute('aria-checked')).toBe('true');
    await userEvent.click(screen.getByRole('radio', { name: 'home' }));
    await userEvent.type(screen.getByLabelText('Epic'), '1');
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await screen.findByText('o/r#5: needs refine');
    expect(posts.find(([p]) => p === '/api/dispatches/plan')?.[1]).toEqual({ epic: 'o/r#1', settings: { ...S, account: 'home' } });
    cleanup();
    posts.length = 0;
    window.location.hash = '#/dispatches/abc123abc123?repo=o/r';
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: /Settings/ }));
    await userEvent.click(await screen.findByRole('radio', { name: 'home' }));
    await waitFor(() => expect(posts.at(-1)).toEqual(['/api/dispatches/abc123abc123/settings', { account: 'home' }]));
    cleanup();
    routes['/api/settings'] = { commands: [{ label: 'work', cmd: 'claude' }], default: 'work' };
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: /Settings/ }));
    await screen.findByRole('switch', { name: 'Auto-merge' });
    expect(screen.queryByRole('radio', { name: 'work' })).toBeNull();
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
  it('shows the title in its row and the repo under it', async () => {
    routes['/api/dispatches'] = { dispatches: [disp(), disp({ id: 'sm1', ...SMALL }), disp({ id: 'sm2', state: 'done', ...SMALL })] };
    window.location.hash = '#/dispatches?repo=o/r';
    render(<App />);
    const links = await screen.findAllByRole('link', { name: 'Small changes: #412, #415' });
    expect(links.length).toBe(2);
    expect(links[0].closest('td')!.querySelector('.strip-m')!.textContent).toBe('r');
    expect(screen.getByRole('link', { name: 'Payments' })).toBeTruthy();
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
