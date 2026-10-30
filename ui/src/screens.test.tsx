import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { ExtButton } from './components';
import { mergeWarnings } from './panels/prWarnings';
import { SMALL_CHANGE_LOCK, SMALL_CHANGE_MARKER, SMALL_CHANGE_NOTE, smallChangeArg, smallChangeText } from './features/smallChange';

const json = (b: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } }));
const posts: { url: string; body: any }[] = [];

const card = (n: number, column: string, over: Record<string, unknown> = {}) => ({
  n, title: `Task ${n}`, column, priority: null, blocked_by: [], pr: null, session: null, grind: null, needs_cleanup: null, ...over,
});
const prd = (over: Record<string, unknown> = {}) => ({
  slug: 'f1', title: 'Feature one', status: 'Approved', path: 'docs/prds/f1.md', abs_path: '/x/docs/prds/f1.md', column: 'approved',
  pr: null, epic: 7, issues: 0, refined: 0, unrefined: [], children: [], panel: null, ...over,
});
const lane = (cards: any[], over: Record<string, unknown> = {}) => ({ epic: 7, title: 'F1', running: 0, cards, ...over });

function mock(o: { fetchedAt?: number | null; delFetchedAt?: number | null; stale?: boolean; prds?: any[]; lanes?: any[]; extra?: Record<string, (init?: RequestInit) => Promise<Response>>; repos?: { slug: string; name: string; path: string }[]; all?: { plan: any[]; del: any[] } } = {}) {
  posts.length = 0;
  const routes: Record<string, unknown> = {
    '/api/repos': { repos: o.repos ?? [{ slug: 'o/r', name: 'R', path: '/x' }], can_browse: false, scan_roots: [] },
    '/api/sessions': { sessions: [], limits: {}, usage: {}, afk: { active: false, until: null, started: null, decisions: 0, held: 0, summary: null }, gh: { ok: true } },
    '/api/inbox': { items: [], afk: {}, gh: { ok: true } },
    '/api/shares': [],
    '/api/planning': { repo: 'o/r', stale: o.stale ?? false, fetched_at: o.fetchedAt === undefined ? 1 : o.fetchedAt, prds: o.prds ?? [] },
    '/api/delivery': { repo: 'o/r', stale: o.stale ?? false, fetched_at: o.delFetchedAt === undefined ? 1 : o.delFetchedAt, cap: 2, running: 0, auto_grind: false, lanes: o.lanes ?? [] },
    '/api/settings': { commands: [{ label: 'main', cmd: 'claude' }, { label: 'work', cmd: 'claude2' }], default: 'main' },
    '/api/peer-review': { default: ['critical', 'qa'], max_rounds: 5, kinds: { custom: ['critical', 'qa', 'ux'] } },
  };
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const path = String(url).split('?')[0];
    if (init?.method === 'POST' || init?.method === 'PUT') posts.push({ url: path, body: JSON.parse(String(init.body ?? '{}')) });
    if (o.extra?.[path]) return o.extra[path](init);
    const only = new URLSearchParams(String(url).split('?')[1]).get('repo');
    if (o.all && only && (path === '/api/planning' || path === '/api/delivery')) return json((path === '/api/planning' ? o.all.plan : o.all.del).find((e) => e.repo === only));
    if ((path === '/api/planning' || path === '/api/delivery') && !only) {
      const rows = o.all ? (path === '/api/planning' ? o.all.plan : o.all.del) : [routes[path]];
      return json({ repos: rows, stale: [] });
    }
    if (init?.method === 'POST') return json(path === '/api/start' ? { session: 'sess1' } : { id: 'sess1' }, 201);
    return path in routes ? json(routes[path]) : json({ items: [] });
  }));
}
beforeEach(() => { localStorage.clear(); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const step = () => screen.findByRole('region', { name: 'Next step' });

describe('before the board snapshot is fetched', () => {
  it('Feature page and list show no next step, only a skeleton', async () => {
    mock({ fetchedAt: null, prds: [prd({ issues: 2, refined: 2, children: [] })], lanes: [lane([card(1, 'ready')])] });
    window.location.hash = '#/features/f1?repo=o/r';
    render(<App />);
    expect(await screen.findByText('Loading…')).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Next step' })).toBeNull();
    window.location.hash = '#/features?only=o/r';
    expect(await screen.findByText('Loading features…')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Create tasks' })).toBeNull();
  });
});

describe('real not-fetched server state (both snapshots null, stale)', () => {
  const noEpic = [{ epic: null, title: 'No epic', running: 0, cards: [] }];
  for (const [name, o] of [['both null', { fetchedAt: null, delFetchedAt: null }], ['delivery null only', { delFetchedAt: null }]] as const) {
    it(`${name}: no stage, no banner action, no Create tasks`, async () => {
      mock({ ...o, stale: true, prds: [prd({ epic: null })], lanes: noEpic });
      window.location.hash = '#/features/f1?repo=o/r';
      render(<App />);
      expect(await screen.findByText('Loading…')).toBeTruthy();
      expect(screen.queryByRole('button', { name: 'Create tasks' })).toBeNull();
      expect(screen.queryByText('Approved')).toBeNull();
      window.location.hash = '#/features?only=o/r';
      expect(await screen.findByText('Loading features…')).toBeTruthy();
      expect(screen.queryByRole('button', { name: 'Create tasks' })).toBeNull();
    });
  }
});

describe('Issues tab order', () => {
  it('lists In review before Ready, Blocked and Merged', async () => {
    mock({ prds: [prd({ issues: 4 })], lanes: [lane([card(1, 'merged'), card(2, 'ready', { blocked_by: [9] }), card(3, 'ready'), card(4, 'in_review')])] });
    window.location.hash = '#/features/f1/issues?repo=o/r';
    render(<App />);
    await screen.findByRole('region', { name: 'Next step' });
    const text = (await screen.findByRole('tabpanel')).textContent ?? '';
    const at = (t: string) => text.indexOf(t);
    expect(at('Task 4')).toBeLessThan(at('Task 3'));
    expect(at('Task 3')).toBeLessThan(at('Task 2'));
    expect(at('Task 2')).toBeLessThan(at('Task 1'));
  });
});

describe('Next step box wired to actions', () => {
  it('draft PRD: Start peer review opens the review tab', async () => {
    mock({ prds: [prd({ status: 'Draft', column: 'draft' })] });
    window.location.hash = '#/features/f1?repo=o/r';
    const user = userEvent.setup();
    render(<App />);
    const box = within(await step());
    await user.click(box.getByRole('button', { name: 'Start peer review' }));
    await waitFor(() => expect(window.location.hash).toContain('/features/f1/review'));
    expect(await screen.findByText('Run the peer review panel')).toBeTruthy();
  });

  it('Approve PRD asks first, then starts create-prd approve', async () => {
    mock({ prds: [prd({ status: 'In review', column: 'in_review', panel: { id: 'p1', state: 'approved', round: 1, max_rounds: 5, approved: 2, total: 2, lenses: {} } })] });
    window.location.hash = '#/features/f1?repo=o/r';
    const user = userEvent.setup();
    render(<App />);
    await user.click(within(await step()).getByRole('button', { name: 'Approve PRD' }));
    expect(posts).toHaveLength(0);
    expect((await screen.findByRole('alertdialog')).textContent).toContain('opens a PR (merged right away on repos you own)');
    await user.click(await screen.findByRole('button', { name: 'Approve PRD', hidden: false }).then(() => within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Approve PRD' })));
    await waitFor(() => expect(posts.some((p) => p.url === '/api/sessions' && p.body.command === 'create-prd' && p.body.args.startsWith('docs/prds/f1.md approve:') && ['prd/f1', 'open PR already', '--merge', 'signed-in `gh` user', 'only the PRD file'].every((t) => p.body.args.includes(t)) && p.body.model === 'opus' && p.body.effort === 'medium')).toBe(true));
  });

  it('Approved: Create tasks posts /api/start create-tasks with the PRD path', async () => {
    mock({ prds: [prd()] });
    window.location.hash = '#/features/f1?repo=o/r';
    const user = userEvent.setup();
    render(<App />);
    await user.click(within(await step()).getByRole('button', { name: 'Create tasks' }));
    await waitFor(() => expect(posts.find((p) => p.url === '/api/start')?.body).toMatchObject({ repo: 'o/r', skill: 'create-tasks', arg: 'docs/prds/f1.md', model: 'opus', effort: 'medium' }));
  });

  it('Tasks: Refine N sends the issue numbers; Building with a green approved PR says Review and merge', async () => {
    mock({ prds: [prd({ issues: 2, unrefined: [11, 12], column: 'tasks_filed' })], lanes: [lane([card(11, 'unrefined'), card(12, 'unrefined')])] });
    window.location.hash = '#/features/f1?repo=o/r';
    const user = userEvent.setup();
    render(<App />);
    await user.click(within(await step()).getByRole('button', { name: 'Refine 2' }));
    await waitFor(() => expect(posts.find((p) => p.url === '/api/start')?.body).toMatchObject({ skill: 'refine-issues', arg: '11 12', model: 'opus', effort: 'medium' }));
    cleanup();
    mock({ prds: [prd({ issues: 1, column: 'refined' })], lanes: [lane([card(11, 'in_review', { pr: { n: 40, draft: false, ci: 'success', url: 'u', review: 'approved' }, mergeable: true })])] });
    window.location.hash = '#/features/f1?repo=o/r';
    render(<App />);
    expect(await within(await step()).findByRole('button', { name: 'Review and merge' })).toBeTruthy();
  });

  it('Building with ready issues: Run epic opens the New dispatch dialog on the epic', async () => {
    mock({ prds: [prd({ issues: 1, column: 'refined' })], lanes: [lane([card(11, 'ready')])] });
    window.location.hash = '#/features/f1?repo=o/r';
    const user = userEvent.setup();
    render(<App />);
    await user.click(within(await step()).getByRole('button', { name: 'Run epic' }));
    expect(await screen.findByRole('dialog', { name: 'Run an epic' })).toBeTruthy();
    expect((screen.getByLabelText('Epic') as HTMLInputElement).value).toBe('o/r#7');
  });

  it('Shipped: Close epic confirms, then posts /api/epics/close', async () => {
    mock({ prds: [prd({ issues: 0 })], lanes: [lane([card(11, 'merged')])] });
    window.location.hash = '#/features/f1?repo=o/r';
    const user = userEvent.setup();
    render(<App />);
    await user.click(within(await step()).getByRole('button', { name: 'Close epic' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Close epic' }));
    await waitFor(() => expect(posts.find((p) => p.url === '/api/epics/close')?.body).toEqual({ repo: 'o/r', epic: 7 }));
  });

  it('unknown slug shows the not-found state', async () => {
    mock({ prds: [prd()] });
    window.location.hash = '#/features/nope?repo=o/r';
    render(<App />);
    expect(await screen.findByText('Feature not found')).toBeTruthy();
  });
});

describe('Features list', () => {
  it('the capture box with Feature picked starts create-prd', async () => {
    mock();
    window.location.hash = '#/features?only=o/r';
    const user = userEvent.setup();
    render(<App />);
    await user.type(await screen.findByLabelText('Describe a feature or a fix'), 'CSV import');
    await user.click(screen.getByRole('radio', { name: 'Feature' }));
    await user.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(posts.find((p) => p.url === '/api/sessions')?.body).toMatchObject({ repo: 'o/r', command: 'create-prd', args: 'CSV import', model: 'opus', effort: 'medium' }));
  });

  it('Auto opens the New page, where the jev route is preselected and Start files a small change', async () => {
    mock({ extra: { '/api/route': () => json({ route: 'small_change', confidence: 0.9, why: 'it reads as a fix or one contained change' }) } });
    window.location.hash = '#/features?only=o/r';
    const user = userEvent.setup();
    render(<App />);
    await user.type(await screen.findByLabelText('Describe a feature or a fix'), 'login 404s');
    await user.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(window.location.hash).toContain('#/new'));
    expect(await screen.findByText(/Auto picked/)).toBeTruthy();
    expect(screen.getByRole('radio', { name: /Small change/ }).getAttribute('aria-checked')).toBe('true');
    expect(posts.find((p) => p.url === '/api/route')?.body).toEqual({ text: 'login 404s' });
    await user.click(screen.getByRole('button', { name: 'File the issue' }));
    await waitFor(() => expect(posts.find((p) => p.url === '/api/start')?.body).toMatchObject({ skill: 'create-tasks', arg: smallChangeArg('login 404s') }));
    await waitFor(() => expect(window.location.hash).toContain('#/changes'));
  });

  it('when jev cannot tell, the New page asks for a route and Start stays disabled', async () => {
    mock({ extra: { '/api/route': () => json({ route: null, confidence: 0, why: 'jev is not installed' }) } });
    window.location.hash = '#/new?text=stuff&repo=o/r';
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByText(/Auto could not tell \(jev is not installed\)/)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Start the PRD interview' }) as HTMLButtonElement).disabled).toBe(true);
    await user.click(screen.getByRole('radio', { name: /Feature/ }));
    await user.click(screen.getByRole('button', { name: 'Start the PRD interview' }));
    await waitFor(() => expect(posts.find((p) => p.url === '/api/sessions')?.body).toMatchObject({ command: 'create-prd', args: 'stuff' }));
  });

  describe('duplicate warning', () => {
    const issue = { kind: 'issue', n: 12, title: 'Dark mode support', url: 'https://github.com/o/r/issues/12' };
    const dupMock = (h: (init?: RequestInit) => Promise<Response>) => mock({ extra: { '/api/route': () => json({ route: null, confidence: 0, why: 'x' }), '/api/duplicate': h } });
    const text20 = 'Add dark mode to the settings page';
    const dups = () => posts.filter((p) => p.url === '/api/duplicate');

    it('shows a linked issue match and both buttons still start', async () => {
      dupMock(() => json({ match: issue, confidence: 0.7, why: 'same' }));
      window.location.hash = `#/new?text=${encodeURIComponent(text20)}&repo=o/r`;
      const user = userEvent.setup();
      render(<App />);
      await screen.findByText(/Looks like/, undefined, { timeout: 2000 });
      const a = screen.getByRole('link', { name: '#12 Dark mode support' });
      expect(a.getAttribute('href')).toBe(issue.url);
      expect(a.getAttribute('target')).toBe('_blank');
      expect(a.getAttribute('rel')).toBe('noopener noreferrer');
      expect(dups()[0].body).toEqual({ repo: 'o/r', text: text20 });
      await user.click(screen.getByRole('radio', { name: /Feature/ }));
      await user.click(screen.getByRole('button', { name: 'Start the PRD interview' }));
      await waitFor(() => expect(posts.find((p) => p.url === '/api/sessions')?.body).toMatchObject({ command: 'create-prd' }));
    });

    it('shows a PRD match by its title', async () => {
      dupMock(() => json({ match: { kind: 'prd', path: 'f1', title: 'Feature one', url: '#/features/f1?repo=o/r' }, confidence: 0.7, why: 'same' }));
      window.location.hash = `#/new?text=${encodeURIComponent(text20)}&repo=o/r`;
      render(<App />);
      expect((await screen.findByRole('link', { name: 'Feature one' }, { timeout: 2000 })).getAttribute('href')).toBe('#/features/f1?repo=o/r');
    });

    it('checks at 20 characters, not 19', async () => {
      dupMock(() => json({ match: null, confidence: 0, why: 'x' }));
      window.location.hash = '#/new?text=0123456789012345678&repo=o/r';
      const user = userEvent.setup();
      render(<App />);
      await screen.findByLabelText('Describe a feature or a fix');
      await new Promise((r) => setTimeout(r, 1000));
      expect(dups()).toHaveLength(0);
      await user.type(screen.getByLabelText('Describe a feature or a fix'), '9');
      await waitFor(() => expect(dups()).toHaveLength(1), { timeout: 2000 });
    });

    it('hides on edit', async () => {
      dupMock(() => json({ match: issue, confidence: 0.7, why: 'same' }));
      window.location.hash = `#/new?text=${encodeURIComponent(text20)}&repo=o/r`;
      const user = userEvent.setup();
      render(<App />);
      await screen.findByText(/Looks like/, undefined, { timeout: 2000 });
      await user.type(screen.getByLabelText('Describe a feature or a fix'), '!');
      expect(screen.queryByText(/Looks like/)).toBeNull();
    });

    it('ignores a stale response', async () => {
      let release: (r: Response) => void = () => {};
      let n = 0;
      dupMock(() => (++n === 1 ? new Promise<Response>((r) => { release = r; }) : json({ match: null, confidence: 0, why: 'x' })));
      window.location.hash = `#/new?text=${encodeURIComponent(text20)}&repo=o/r`;
      const user = userEvent.setup();
      render(<App />);
      await waitFor(() => expect(dups()).toHaveLength(1), { timeout: 2000 });
      await user.type(screen.getByLabelText('Describe a feature or a fix'), '!');
      await waitFor(() => expect(dups()).toHaveLength(2), { timeout: 2000 });
      release(await json({ match: issue, confidence: 0.7, why: 'same' }));
      await new Promise((r) => setTimeout(r, 100));
      expect(screen.queryByText(/Looks like/)).toBeNull();
    });

    it('shows nothing for a failed check', async () => {
      dupMock(() => json({ error: 'boom' }, 500));
      window.location.hash = `#/new?text=${encodeURIComponent(text20)}&repo=o/r`;
      render(<App />);
      await waitFor(() => expect(dups()).toHaveLength(1), { timeout: 2000 });
      await new Promise((r) => setTimeout(r, 100));
      expect(screen.queryByText(/Looks like|boom|error/i)).toBeNull();
    });
  });
});

describe('PRD tab', () => {
  it('a save refused with 409 says the file changed on disk', async () => {
    mock({
      prds: [prd({ status: 'Draft', column: 'draft' })],
      extra: {
        '/api/prd': (init) => (init?.method === 'POST' ? json({ error: 'changed on disk' }, 409) : json({ text: '# Hi', sha: 'abc', branch: 'main' })),
      },
    });
    window.location.hash = '#/features/f1/prd?repo=o/r';
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Edit' }));
    const ta = await screen.findByLabelText('PRD markdown');
    await user.type(ta, ' more');
    await user.click(screen.getByRole('button', { name: 'Save and commit' }));
    expect(await screen.findByText(/changed on disk since you opened it/)).toBeTruthy();
    expect(posts.find((p) => p.url === '/api/prd')?.body.base_sha).toBe('abc');
  });
});

describe('GitHub links open the side panel', () => {
  const open = async () => {
    mock({
      prds: [prd({ status: 'Draft', column: 'draft' })],
      extra: { '/api/prd': () => json({ text: 'See [one](https://github.com/o/r/issues/5) and [two](https://github.com/o/r/pull/3/files).', sha: 'abc', branch: 'main' }) },
    });
    window.location.hash = '#/features/f1/prd?repo=o/r';
    render(<App />);
    return userEvent.setup();
  };

  it('a plain click on an issue link opens the panel; a meta-click and a non-issue link do not', async () => {
    const user = await open();
    const issue = await screen.findByRole('link', { name: 'one' });
    await user.keyboard('{Meta>}');
    await user.click(issue);
    await user.keyboard('{/Meta}');
    expect(screen.queryByRole('complementary', { name: 'Issue details' })).toBeNull();
    await user.click(screen.getByRole('link', { name: 'two' }));
    expect(screen.queryByLabelText('Pull request details')).toBeNull();
    await user.click(issue);
    expect(await screen.findByLabelText('Issue details')).toBeTruthy();
  });

  it('an ExtButton is not intercepted', () => {
    render(<ExtButton href="https://github.com/o/r/issues/5">Issue on GitHub</ExtButton>);
    expect(screen.getByRole('link').hasAttribute('data-ext')).toBe(true);
  });
});

describe('Small changes page', () => {
  const open = async (hash: string) => { window.location.hash = hash; const user = userEvent.setup(); render(<App />); return user; };

  it('lists open issues outside every feature; a card starts headless only and a 409 toasts the running session', async () => {
    mock({
      prds: [prd({ issues: 1 })],
      lanes: [lane([card(11, 'ready')]), lane([card(30, 'ready'), card(31, 'unrefined')], { epic: null, title: 'No epic' })],
      extra: { '/api/start': () => json({ error: 'already running', id: 'abc', href: '#/session/abc' }, 409) },
    });
    const user = await open('#/changes?only=o/r');
    expect((await screen.findAllByText('Task 30')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Task 31').length).toBeGreaterThan(0);
    expect(screen.queryByText('Task 11')).toBeNull(); // part of the feature
    expect(screen.getByText('2 open issues outside any feature. 1 is ready to run now.')).toBeTruthy();
    await user.click(await screen.findByRole('button', { name: 'More ways to start' }));
    expect(screen.queryByRole('menuitem', { name: /herdr tab/ })).toBeNull();
    await user.keyboard('{Escape}');
    await user.click(screen.getAllByRole('button', { name: 'Start' })[0]);
    expect(await screen.findByRole('button', { name: 'Open session' })).toBeTruthy();
    const body = posts.find((p) => p.url === '/api/start')?.body;
    expect(body).toMatchObject({ skill: 'implement-issue' });
    expect(body).not.toHaveProperty('model'); // only the planning starts carry PLAN_RUN
  });

  it('File issue is disabled while blank, starts one headless create-tasks with the collapsed text, and clears', async () => {
    mock({ lanes: [lane([card(30, 'ready')], { epic: null })] });
    const user = await open('#/changes?only=o/r');
    const btn = await screen.findByRole('button', { name: 'File issue' });
    const box = screen.getByLabelText('Describe a feature or a fix') as HTMLInputElement;
    expect((btn as HTMLButtonElement).disabled).toBe(true);
    await user.type(box, '   ');
    expect((btn as HTMLButtonElement).disabled).toBe(true);
    await user.clear(box);
    await user.type(box, 'a   b  c');
    expect((btn as HTMLButtonElement).disabled).toBe(false);
    await user.click(btn);
    await waitFor(() => expect(box.value).toBe(''));
    const posted = posts.filter((p) => p.url === '/api/start');
    expect(posted).toHaveLength(1);
    expect(posted[0].body).toMatchObject({ repo: 'o/r', skill: 'create-tasks', via: 'headless', model: 'opus', effort: 'medium' });
    expect((posted[0].body as { arg: string }).arg).toBe(smallChangeArg('a b c'));
    expect(window.location.hash).toContain('#/changes');
  });

  it('a failing start keeps the text and toasts the error', async () => {
    mock({ lanes: [lane([card(30, 'ready')], { epic: null })], extra: { '/api/start': () => json({ error: 'boom' }, 502) } });
    const user = await open('#/changes?only=o/r');
    const box = (await screen.findByLabelText('Describe a feature or a fix')) as HTMLInputElement;
    await user.type(box, 'broken thing');
    await user.click(screen.getByRole('button', { name: 'File issue' }));
    expect(await screen.findByText('boom')).toBeTruthy();
    expect(box.value).toBe('broken thing');
  });

  it('smallChangeArg puts the marker first, collapses whitespace and ends with the note', () => {
    const arg = smallChangeArg('  a \n b  ');
    expect(arg.startsWith(`${SMALL_CHANGE_MARKER} a b`)).toBe(true);
    expect(arg.endsWith(SMALL_CHANGE_NOTE)).toBe(true);
    expect(arg).not.toMatch(/[\n\0]/);
  });

  const sess = (id: string, command: string, outcome: string, over: Record<string, unknown> = {}) => ({ id, command, outcome, repo: '/x', link: null, started_at: `2026-01-01T00:00:0${id.length}Z`, ...over });
  const withSessions = (sessions: unknown[]) => ({ '/api/sessions': () => json({ sessions, limits: {}, usage: {}, afk: { active: false, until: null, started: null, decisions: 0, held: 0, summary: null }, gh: { ok: true } }) });
  const marked = (text: string) => `/create-tasks ${smallChangeArg(text)}`;

  it('smallChangeText returns the typed text for both command forms and null otherwise', () => {
    expect(smallChangeText(marked('fix it'))).toBe('fix it');
    expect(smallChangeText(marked('fix it').replace('/ai-workflow:refine-issues', '/refine-issues'))).toBe('fix it');
    expect(smallChangeText(marked('Instructions: keep this'))).toBe('Instructions: keep this');
    expect(smallChangeText(`/ai-workflow:create-tasks ${SMALL_CHANGE_MARKER} fix it`)).toBe('fix it');
    expect(smallChangeText('/create-tasks A finding for epic #7 here')).toBeNull();
    expect(smallChangeText('/implement-issue 3')).toBeNull();
  });

  it('a live marked session shows a row with its state and button; ended, other repo, other skill do not', async () => {
    mock({
      lanes: [lane([card(30, 'ready'), card(31, 'unrefined')], { epic: null })],
      extra: withSessions([
        sess('a', marked('typed text'), 'running'),
        sess('bb', marked('queued one'), 'queued'),
        sess('ccc', marked('needs one'), 'waiting'),
        sess('dddd', marked('done one'), 'done'),
        sess('eeeee', marked('failed one'), 'failed'),
        sess('ffffff', marked('other repo'), 'running', { repo: '/other' }),
        sess('g', '/implement-issue 5', 'running'),
        sess('h', '/create-tasks A finding for epic #7 here', 'running'),
      ]),
    });
    const user = await open('#/changes?only=o/r');
    expect(await screen.findByText('typed text')).toBeTruthy();
    expect(screen.getByText('queued one')).toBeTruthy();
    expect(screen.getByText('needs one')).toBeTruthy();
    for (const t of ['done one', 'failed one', 'other repo']) expect(screen.queryByText(t)).toBeNull();
    expect(screen.getByText('typed text').closest('.frow')?.textContent).not.toContain('Instructions');
    expect(screen.getByText('Creating…')).toBeTruthy();
    expect(screen.getByText('Queued')).toBeTruthy();
    expect(screen.getByText('Needs you')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: 'Watch' })).toHaveLength(2);
    await user.click(screen.getByRole('button', { name: 'Answer' }));
    expect(window.location.hash).toContain('/sessions/ccc');
  });

  it('a pending row locks Refine on unrefined rows only; with the session done Refine is enabled', async () => {
    const lanes = [lane([card(30, 'ready'), card(31, 'unrefined')], { epic: null })];
    mock({ lanes, extra: withSessions([sess('a', marked('x'), 'running')]) });
    await open('#/changes?only=o/r');
    const refine = (await screen.findByRole('button', { name: 'Refine' })) as HTMLButtonElement;
    expect(refine.disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Refine #31' }) as HTMLButtonElement).disabled).toBe(true);
    expect(refine.title).toBe(SMALL_CHANGE_LOCK);
    expect((screen.getByRole('button', { name: 'Start' }) as HTMLButtonElement).disabled).toBe(false);
    cleanup();
    mock({ lanes, extra: withSessions([sess('a', marked('x'), 'done')]) });
    await open('#/changes?only=o/r');
    expect(((await screen.findByRole('button', { name: 'Refine' })) as HTMLButtonElement).disabled).toBe(false);
  });

  it.each(['/refine-issues 30 31', '/ai-workflow:refine-issues 30 31'])('a live %s session shows Refining… on both issues', async (command) => {
    mock({ lanes: [lane([card(30, 'unrefined'), card(31, 'unrefined')], { epic: null })], extra: withSessions([sess('a', command, 'running', { slug: 'o/r' })]) });
    await open('#/changes?only=o/r');
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Refining…' })).toHaveLength(2));
    expect(screen.queryByRole('button', { name: 'Refine' })).toBeNull();
  });

  describe('pick bar', () => {
    const lanes = [lane([card(30, 'ready'), card(31, 'unrefined'), card(32, 'ready', { blocked_by: [30] }), card(33, 'in_progress'), card(34, 'merged')], { epic: null, title: 'No epic' })];
    const box = (n: number) => screen.queryByRole('checkbox', { name: `Pick #${n}` }) as HTMLInputElement | null;
    const btn = (name: string) => screen.queryByRole('button', { name }) as HTMLButtonElement | null;
    const lane30 = { key: 'o/r#30', repo: 'o/r', n: 30, title: 'Task 30', deps: [], stage: 'implementing', pr: null, needs_you: null, held: null, gate: null, skip_reason: null, paused: null, hold_merge: null, limited_until: null, started_at: 1, ended_at: null, session: 's', tab: null, usage: { cost: 0, tokens: 0, seconds: 0 } };
    const owning = { '/api/dispatches': () => json({ dispatches: [{ id: 'd1', epic: null, issues: ['o/r#30'], title: 'Small', runner: 'headless', state: 'running', settings: {}, created_at: 1, ended_at: null, final_prs: null, totals: { cost: 0, tokens: 0, seconds: 0 }, lanes: [lane30] }] }) };

    it('unrefined, ready and blocked rows get a checkbox; the bar counts Refine and Run and Clear empties it', async () => {
      mock({ lanes });
      const user = await open('#/changes?only=o/r');
      await screen.findAllByText('Task 30');
      for (const n of [30, 31, 32]) expect(box(n)).toBeTruthy();
      for (const n of [33, 34]) expect(box(n)).toBeNull();
      expect(btn('Clear')).toBeNull();
      await user.click(box(31)!);
      expect(btn('Refine 1')).toBeTruthy();
      expect(screen.queryByRole('button', { name: /^Run \d/ })).toBeNull();
      await user.click(box(30)!);
      await user.click(box(32)!);
      expect(btn('Refine 1')).toBeTruthy();
      expect(btn('Run 2')).toBeTruthy();
      await user.click(box(31)!);
      expect(btn('Refine 1')).toBeNull();
      expect(btn('Run 2')).toBeTruthy();
      await user.click(box(30)!);
      await user.click(box(32)!);
      expect(btn('Clear')).toBeNull();
      await user.click(box(30)!);
      await user.click(box(31)!);
      await user.click(btn('Clear')!);
      expect(btn('Clear')).toBeNull();
      expect(box(30)!.checked || box(31)!.checked).toBe(false);
    });

    it('Refine 1 starts one headless refine-issues on the picked unrefined issue', async () => {
      mock({ lanes });
      const user = await open('#/changes?only=o/r');
      await screen.findAllByText('Task 31');
      await user.click(box(31)!);
      await user.click(box(30)!);
      await user.click(btn('Refine 1')!);
      await waitFor(() => expect(posts.find((p) => p.url === '/api/start')?.body).toEqual({ repo: 'o/r', skill: 'refine-issues', arg: '31', via: 'headless', model: 'opus', effort: 'medium' }));
      await waitFor(() => expect(window.location.hash).toBe('#/sessions/sess1?repo=o/r'));
    });

    it('Run 2 opens the small-changes dialog on the picked refined issues and Preview posts them', async () => {
      const plan = { epic: null, issues: ['o/r#30', 'o/r#32'], title: 'Small changes', settings: {}, runner: 'headless', lanes: [], waves: [], warnings: [] };
      mock({ lanes, extra: { '/api/dispatches/plan': () => json(plan) } });
      const user = await open('#/changes?only=o/r');
      await screen.findAllByText('Task 30');
      await user.click(box(30)!);
      await user.click(box(31)!);
      await user.click(box(32)!);
      await user.click(btn('Run 2')!);
      const dialog = await screen.findByRole('dialog');
      expect(within(dialog).getByText('Run small changes')).toBeTruthy();
      expect(within(dialog).getByText('#30 Task 30')).toBeTruthy();
      expect(within(dialog).getByText('#32 Task 32')).toBeTruthy();
      expect(within(dialog).queryByText('#31 Task 31')).toBeNull();
      expect(within(dialog).queryByLabelText('Epic')).toBeNull();
      await user.click(within(dialog).getByRole('button', { name: 'Preview' }));
      await waitFor(() => expect(posts.find((p) => p.url === '/api/dispatches/plan')?.body).toMatchObject({ issues: ['o/r#30', 'o/r#32'], settings: expect.any(Object) }));
    });

    it('a row a dispatch owns shows In dispatch, has no checkbox and leaves the Run count', async () => {
      mock({ lanes, extra: owning });
      const user = await open('#/changes?only=o/r');
      expect(await screen.findByRole('link', { name: 'In dispatch' })).toBeTruthy();
      expect(box(30)).toBeNull();
      await user.click(box(32)!);
      expect(btn('Run 1')).toBeTruthy();
    });

    it('a live small-change session disables Refine N with the hint; Run N stays enabled', async () => {
      mock({ lanes, extra: withSessions([sess('a', marked('x'), 'running')]) });
      const user = await open('#/changes?only=o/r');
      await screen.findAllByText('Task 31');
      await user.click(box(31)!);
      await user.click(box(30)!);
      expect(btn('Refine 1')!.disabled).toBe(true);
      expect(btn('Refine 1')!.title).toBe(`${SMALL_CHANGE_LOCK} (E)`);
      expect(btn('Run 1')!.disabled).toBe(false);
    });

    it('switching repo clears the picks', async () => {
      mock({ lanes, extra: { '/api/repos': () => json({ repos: [{ slug: 'o/r', name: 'R', path: '/x' }, { slug: 'o/s', name: 'S', path: '/y' }], can_browse: false, scan_roots: [] }) } });
      const user = await open('#/changes?only=o/r');
      await screen.findAllByText('Task 30');
      await user.click(box(30)!);
      expect(btn('Run 1')).toBeTruthy();
      window.location.hash = '#/changes?only=o/s';
      await waitFor(() => expect(btn('Run 1')).toBeNull());
      await screen.findAllByText('Task 30');
      expect(box(30)!.checked).toBe(false);
      expect(btn('Clear')).toBeNull();
    });
  });

  it('the empty message hides while a pending row exists and shows when both are empty', async () => {
    mock({ extra: withSessions([sess('a', marked('x'), 'running')]) });
    await open('#/changes?only=o/r');
    expect(await screen.findByText('x')).toBeTruthy();
    expect(screen.queryByText(/Nothing here\. Describe a bug/)).toBeNull();
    cleanup();
    mock();
    await open('#/changes?only=o/r');
    expect(await screen.findByText(/Nothing here\. Describe a bug/)).toBeTruthy();
  });

  it('wraps the sections in one .stack and renders no empty .list when nothing is pending', async () => {
    mock();
    await open('#/changes?only=o/r');
    const text = await screen.findByText(/Nothing here\. Describe a bug/);
    const stack = text.closest('.stack');
    expect(stack).toBeTruthy();
    expect(stack!.querySelector('.list')).toBeNull();
  });

  it('ready issues fill the Ready panel; picking two runs them as a dispatch', async () => {
    mock({ lanes: [lane([card(1, 'ready'), card(2, 'ready'), card(3, 'ready')], { epic: null })] });
    const user = await open('#/changes?only=o/r');
    expect(await screen.findByText('3 open issues outside any feature. 3 are ready to run now.')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Pick issues to run' }) as HTMLButtonElement).disabled).toBe(true);
    await user.click(screen.getByRole('checkbox', { name: 'Run #1' }));
    await user.click(screen.getByRole('checkbox', { name: 'Run #2' }));
    await user.click(screen.getByRole('button', { name: 'Run 2 as a dispatch' }));
    expect(within(await screen.findByRole('dialog')).getByText('#1 Task 1')).toBeTruthy();
  });

  it('a priority cell filters the list, and Show all clears it', async () => {
    mock({ lanes: [lane([card(1, 'unrefined', { priority: 'high' }), card(2, 'ready', { priority: 'low' })], { epic: null })] });
    const user = await open('#/changes?only=o/r');
    await user.click(await screen.findByRole('button', { name: 'High, needs refining: 1' }));
    expect(screen.getByRole('heading', { name: /Filtered issues/ }).textContent).toContain('1');
    await user.click(screen.getByRole('button', { name: 'Show all' }));
    expect(screen.getByRole('heading', { name: /All issues/ }).textContent).toContain('2');
  });

  it('old links to the Features tab land here with the repo kept', async () => {
    mock({ lanes: [lane([card(30, 'ready')], { epic: null })] });
    await open('#/features?tab=changes&repo=o/r');
    await waitFor(() => expect(window.location.hash).toBe('#/changes?repo=o%2Fr'));
  });

  it('an issue under an epic with no PRD is listed', async () => {
    mock({ prds: [prd({ issues: 1 })], lanes: [lane([card(11, 'ready')]), lane([card(40, 'ready')], { epic: 99 })] });
    await open('#/changes?only=o/r');
    expect((await screen.findAllByText('Task 40')).length).toBeGreaterThan(0);
    expect(screen.queryByText('Task 11')).toBeNull();
  });

  it('#/issues redirects here and there is no Other issues link', async () => {
    mock({ lanes: [lane([card(30, 'ready')], { epic: null })] });
    await open('#/issues?repo=o/r');
    expect((await screen.findAllByText('Task 30')).length).toBeGreaterThan(0);
    expect(window.location.hash).toBe('#/changes?repo=o%2Fr');
    expect(screen.queryByRole('link', { name: /Other issues/ })).toBeNull();
  });

  describe('All repos', () => {
    const REPOS = { '/api/repos': () => json({ repos: [{ slug: 'o/r', name: 'R', path: '/x' }, { slug: 'o/q', name: 'Q', path: '/y' }], can_browse: false, scan_roots: [] }) };
    const board = (repo: string, cards: any[], over: Record<string, unknown> = {}) => ({
      planning: { repo, stale: false, fetched_at: 1, prds: [], ...over },
      delivery: { repo, stale: false, fetched_at: 1, cap: 2, running: 0, auto_grind: false, lanes: [lane(cards, { epic: null })], ...over },
    });
    const all = (...bs: ReturnType<typeof board>[]) => ({ plan: bs.map((b) => b.planning), del: bs.map((b) => b.delivery) });
    const high = (n: number, column = 'ready') => card(n, column, { priority: 'high' });
    const two = all(board('o/r', [high(1), high(2), card(3, 'unrefined')]), board('o/q', [high(4), card(5, 'unrefined')]));

    it('totals the grid across repos and a cell filters the list under both repo headers', async () => {
      mock({ all: two, extra: REPOS });
      const user = await open('#/changes?repo=o/r');
      const cell = await screen.findByRole('button', { name: 'High, ready: 3' });
      expect(screen.getByText('5 open issues outside any feature. 3 are ready to run now.')).toBeTruthy();
      await user.click(cell);
      expect(screen.getByRole('heading', { name: /Filtered issues/ }).textContent).toContain('3');
      const list = within(screen.getByRole('heading', { name: /Filtered issues/ }).closest('section')!);
      expect(list.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual(['R o/r', 'Q o/q']);
      expect(list.queryByText('Task 3')).toBeNull();
    });

    it('Ready rows have checkboxes and Run; the capture bar picks a repo', async () => {
      mock({ all: two, extra: REPOS });
      await open('#/changes?repo=o/r');
      await screen.findByRole('button', { name: 'High, ready: 3' });
      expect(screen.getByRole('checkbox', { name: 'Run #1' })).toBeTruthy();
      expect(screen.getByRole('button', { name: 'Pick issues to run' })).toBeTruthy();
      expect(screen.getByRole('button', { name: /^Capture repo/ })).toBeTruthy();
    });

    it('a pick in o/r disables o/q checkboxes with the note; unchecking frees them', async () => {
      mock({ all: two, extra: REPOS });
      const user = await open('#/changes?repo=o/r');
      await user.click(await screen.findByRole('checkbox', { name: 'Run #1' }));
      expect((screen.getByRole('checkbox', { name: 'Run #4' }) as HTMLInputElement).disabled).toBe(true);
      expect((screen.getByRole('checkbox', { name: 'Run #2' }) as HTMLInputElement).disabled).toBe(false);
      expect(screen.getByText('Picks are from R. Clear them to pick from another repo.')).toBeTruthy();
      await user.click(screen.getByRole('checkbox', { name: 'Run #1' }));
      expect((screen.getByRole('checkbox', { name: 'Run #4' }) as HTMLInputElement).disabled).toBe(false);
      expect(screen.queryByText(/Picks are from/)).toBeNull();
    });

    it('a picked issue that stops being ready is dropped and frees the other repos', async () => {
      let gone = false;
      const cur = () => (gone ? all(board('o/r', [high(2), card(3, 'unrefined')]), board('o/q', [high(4), card(5, 'unrefined')])) : two);
      mock({ all: two, extra: { ...REPOS, '/api/planning': () => json({ repos: cur().plan, stale: [] }), '/api/delivery': () => json({ repos: cur().del, stale: [] }) } });
      const user = await open('#/changes?repo=o/r');
      await user.click(await screen.findByRole('checkbox', { name: 'Run #1' }));
      expect((screen.getByRole('checkbox', { name: 'Run #4' }) as HTMLInputElement).disabled).toBe(true);
      gone = true;
      await waitFor(() => expect((screen.getByRole('checkbox', { name: 'Run #4' }) as HTMLInputElement).disabled).toBe(false), { timeout: 20000 }); // the next 15s board poll
    }, 30000);

    it('Run plans the picked repo even when the switcher is on another', async () => {
      const plan = { epic: null, issues: ['o/r#1'], title: 'Small changes', settings: {}, runner: 'headless', lanes: [], waves: [], warnings: [] };
      mock({ all: two, extra: { ...REPOS, '/api/dispatches/plan': () => json(plan) } });
      const user = await open('#/changes?repo=o/q');
      await user.click(await screen.findByRole('checkbox', { name: 'Run #1' }));
      await user.click(screen.getByRole('button', { name: 'Run 1 as a dispatch' }));
      await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Preview' }));
      await waitFor(() => expect(posts.find((p) => p.url === '/api/dispatches/plan')?.body).toMatchObject({ issues: ['o/r#1'] }));
    });

    it('a small-change session in o/r locks Refine on o/r cards only; o/q Refine starts on o/q', async () => {
      mock({ all: two, extra: { ...REPOS, ...withSessions([sess('a', marked('x'), 'running')]) } });
      const user = await open('#/changes?repo=o/r');
      expect(((await screen.findByRole('button', { name: 'Refine #3' })) as HTMLButtonElement).disabled).toBe(true);
      const q = screen.getByRole('button', { name: 'Refine #5' }) as HTMLButtonElement;
      expect(q.disabled).toBe(false);
      await user.click(q);
      await waitFor(() => expect(posts.find((p) => p.url === '/api/start')?.body).toMatchObject({ repo: 'o/q', skill: 'refine-issues', arg: '5' }));
    });

    it('PickBar Run in the o/q group plans that repo\'s issues', async () => {
      const plan = { epic: null, issues: ['o/q#4'], title: 'Small changes', settings: {}, runner: 'headless', lanes: [], waves: [], warnings: [] };
      mock({ all: two, extra: { ...REPOS, '/api/dispatches/plan': () => json(plan) } });
      const user = await open('#/changes?repo=o/r');
      const row = (await screen.findAllByText('Task 4')).map((e) => e.closest('.frow, tr, li, div')).find(Boolean);
      expect(row).toBeTruthy();
      await user.click(screen.getAllByRole('checkbox', { name: 'Pick #4' })[0]);
      await user.click(screen.getByRole('button', { name: 'Run 1' }));
      await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Preview' }));
      await waitFor(() => expect(posts.find((p) => p.url === '/api/dispatches/plan')?.body).toMatchObject({ issues: ['o/q#4'] }));
    });

    it('?only= narrows to one repo', async () => {
      mock({ all: two, extra: REPOS });
      await open('#/changes?only=o/q');
      await screen.findAllByText('Task 4');
      expect(screen.queryByText('Task 1')).toBeNull();
      expect(screen.getAllByRole('checkbox', { name: 'Run #4' })).toHaveLength(1);
    });

    it('loading and stale repos show a note, never as empty', async () => {
      mock({
        all: all(board('o/r', [high(1)]), board('o/q', [], { fetched_at: null }), { planning: { repo: 'o/z', stale: true, fetched_at: 1, error: 'rate limited' }, delivery: { repo: 'o/z', stale: true, fetched_at: 1, error: 'rate limited' } } as any),
        extra: REPOS,
      });
      await open('#/changes?repo=o/r');
      expect(await screen.findByText('Still loading…')).toBeTruthy();
      expect(screen.getByText('GitHub data is stale. rate limited')).toBeTruthy();
      expect(screen.queryByText(/Nothing here/)).toBeNull();
    });

    it('no watched repo shows the pick-one text', async () => {
      mock({ all: { plan: [], del: [] }, extra: REPOS });
      await open('#/changes?repo=o/r');
      expect(await screen.findByText('No repo opened recently. Pick one in the filter.')).toBeTruthy();
    });

    it('a failed read with no data shows Issues unavailable with Retry', async () => {
      mock({ all: two, extra: { ...REPOS, '/api/planning': () => json({ error: 'boom' }, 500) } });
      await open('#/changes?repo=o/r');
      expect(await screen.findByRole('button', { name: 'Retry' }, { timeout: 5000 })).toBeTruthy(); // the query client retries once first
      expect(screen.getByText('Issues unavailable')).toBeTruthy();
    }, 15000);
  });

  it('an empty tab shows the message', async () => {
    mock();
    await open('#/changes?only=o/r');
    expect(await screen.findByText('Nothing here. Describe a bug or small change above to start one.')).toBeTruthy();
  });

  it('a failed delivery read shows Retry', async () => {
    let calls = 0;
    mock({ extra: { '/api/delivery': () => { calls++; return json({ error: 'boom' }, 500); } } });
    const user = await open('#/changes?only=o/r');
    const retry = await screen.findByRole('button', { name: 'Retry' }, { timeout: 5000 }); // the query client retries once first
    expect(screen.getByText('Issues unavailable')).toBeTruthy();
    const before = calls;
    await user.click(retry);
    await waitFor(() => expect(calls).toBeGreaterThan(before));
  }, 15000);
});

describe('dispatch-owned issues', () => {
  it('an issue a dispatch owns links there instead of Start, and the feature header shows the dispatch', async () => {
    const lane11 = { key: 'o/r#11', repo: 'o/r', n: 11, title: 'Task 11', deps: [], stage: 'implementing', pr: null, needs_you: null, held: null, gate: null, skip_reason: null, paused: null, hold_merge: null, limited_until: null, started_at: 1, ended_at: null, session: 's', tab: null, usage: { cost: 0, tokens: 0, seconds: 0 } };
    mock({
      prds: [prd({ issues: 2 })],
      lanes: [lane([card(11, 'in_progress'), card(12, 'ready')])],
      extra: { '/api/dispatches': () => json({ dispatches: [{ id: 'd1', epic: 'o/r#7', title: 'F', runner: 'headless', state: 'running', settings: {}, created_at: 1, ended_at: null, final_prs: null, totals: { cost: 0, tokens: 0, seconds: 0 }, lanes: [lane11] }] }) },
    });
    window.location.hash = '#/features/f1/issues?repo=o/r';
    render(<App />);
    expect(await screen.findByRole('link', { name: /Dispatch: 0 of 1 done/ })).toBeTruthy();
    expect(await screen.findByRole('link', { name: 'In dispatch' })).toBeTruthy();
    expect(screen.getByText('Implementing the issue')).toBeTruthy();
    expect(within(await step()).getByRole('button', { name: 'Open dispatch' })).toBeTruthy();
  });
});

describe('work panel: issue + PR tabs, grinding switch', () => {
  const issue = { number: 12, title: 'Task 12', state: 'open', url: 'https://github.com/o/r/issues/12', author: 'me', created_at: '2026-01-01T00:00:00Z', labels: [], assignees: [], body_html: '', comments: [], comment_count: 0, is_pr: false };
  const pull = { number: 40, title: 'PR T', url: 'https://github.com/o/r/pull/40', state: 'open', author: 'me', created_at: '2026-01-01T00:00:00Z', head: 'f', base: 'main', body_html: '', additions: 1, deletions: 0, file_count: 0, files: [], commit_count: 0, commits: [], conversation: [], checks: [] };
  const grinding = card(12, 'grinding', { pr: { n: 40, draft: false, ci: 'success', url: 'u' }, grind_on: true, grind: { state: 'running', round: 2, thread: 'https://x.slack.com/archives/C1/p1' } });
  it('an issue with a PR has Issue and PR tabs; turning grinding off confirms and posts /api/grind/issue', async () => {
    mock({ prds: [prd({ issues: 1, column: 'refined' })], lanes: [lane([grinding])], extra: { '/api/issues/o/r/12': () => json(issue), '/api/pulls/o/r/40': () => json(pull) } });
    window.location.hash = '#/features/f1/issues?repo=o/r';
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Task 12' }));
    const panel = await screen.findByRole('complementary', { name: 'Issue details' });
    expect(within(panel).getByRole('tab', { name: 'Issue' }).getAttribute('aria-selected')).toBe('true');
    expect(within(panel).getByRole('tab', { name: 'PR overview' })).toBeTruthy();
    expect(within(panel).getByRole('link', { name: /Open Slack thread/ }).getAttribute('href')).toBe('https://x.slack.com/archives/C1/p1');
    await user.click(within(panel).getByRole('switch', { name: 'Grinding for #12' }));
    await user.click(await screen.findByRole('button', { name: 'Stop grind' }));
    await waitFor(() => expect(posts.find((p) => p.url === '/api/grind/issue')?.body).toEqual({ repo: 'o/r', issue: 12, on: false }));
  });
  it('the Features list shows Merge #n for each mergeable PR, opening the panel on the PR', async () => {
    const ready = (n: number, pr: number) => card(n, 'in_review', { pr: { n: pr, draft: false, ci: 'success', url: 'u' }, mergeable: true });
    mock({ prds: [prd({ issues: 2, column: 'refined' })], lanes: [lane([ready(12, 40), ready(13, 41)])], extra: { '/api/issues/o/r/12': () => json(issue), '/api/pulls/o/r/40': () => json(pull) } });
    window.location.hash = '#/features?only=o/r';
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByRole('button', { name: 'Merge #41' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Review and merge' })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Merge #40' }));
    const panel = await screen.findByRole('complementary', { name: 'Pull request details' });
    expect(within(panel).getByRole('tab', { name: 'PR overview' }).getAttribute('aria-selected')).toBe('true');
    expect(within(panel).getByRole('tab', { name: 'Issue' })).toBeTruthy();
    expect(await within(panel).findByRole('button', { name: 'Merge…' })).toBeTruthy();
  });
});

describe('merge conflicts', () => {
  const pull = { number: 40, title: 'PR T', url: 'https://github.com/o/r/pull/40', state: 'open', author: 'me', created_at: '2026-01-01T00:00:00Z', head: 'f', base: 'main', body_html: '', additions: 1, deletions: 0, file_count: 0, files: [], commit_count: 0, commits: [], conversation: [], checks: [], conflict: true };
  it('the PR panel disables Merge and Resolve conflicts starts a session', async () => {
    mock({ extra: { '/api/pulls/o/r/40': () => json(pull) } });
    const { WorkPanel } = await import('./panels/WorkPanel');
    const { QueryProvider } = await import('./QueryProvider');
    const { ConfirmProvider } = await import('./components');
    const { HashRouter } = await import('react-router-dom');
    const { PanelProvider } = await import('./panels/PanelContext');
    const user = userEvent.setup();
    render(<QueryProvider><ConfirmProvider><HashRouter><PanelProvider><WorkPanel kind="pr" repo="o/r" n={40} /></PanelProvider></HashRouter></ConfirmProvider></QueryProvider>);
    expect((await screen.findByRole('button', { name: 'Merge…' })).hasAttribute('disabled')).toBe(true);
    await user.click(screen.getByRole('button', { name: 'Resolve conflicts' }));
    await waitFor(() => expect(String(posts.find((p) => p.url === '/api/sessions')?.body.text)).toMatch(/^Resolve the merge conflicts on https:\/\/github.com\/o\/r\/pull\/40 /));
  });
  it('a running resolve session turns the button into a Resolving… link', async () => {
    const { resolveText } = await import('./board/ResolveConflicts');
    mock({ extra: { '/api/pulls/o/r/40': () => json(pull), '/api/sessions': () => json({ sessions: [{ id: 's9', command: resolveText(pull.url), outcome: 'running', link: null, repo: '/x' }], limits: {}, usage: {}, afk: {}, gh: { ok: true } }) } });
    const { WorkPanel } = await import('./panels/WorkPanel');
    const { QueryProvider } = await import('./QueryProvider');
    const { ConfirmProvider } = await import('./components');
    const { HashRouter } = await import('react-router-dom');
    const { PanelProvider } = await import('./panels/PanelContext');
    render(<QueryProvider><ConfirmProvider><HashRouter><PanelProvider><WorkPanel kind="pr" repo="o/r" n={40} /></PanelProvider></HashRouter></ConfirmProvider></QueryProvider>);
    expect(await screen.findByRole('link', { name: 'Resolving…' })).toBeTruthy();
  });
});

describe('settings: grinding mode', () => {
  it('Simple saves grind_mode for every grind', async () => {
    mock();
    const { ReposSection } = await import('./settings/ReposSection');
    const { QueryProvider } = await import('./QueryProvider');
    const { ConfirmProvider } = await import('./components');
    const user = userEvent.setup();
    render(<QueryProvider><ConfirmProvider><ReposSection /></ConfirmProvider></QueryProvider>);
    const deep = await screen.findByRole('radio', { name: 'Deep' });
    expect((deep as HTMLInputElement).checked).toBe(true);
    await user.click(screen.getByRole('radio', { name: 'Simple' }));
    await waitFor(() => expect(posts.find((p) => p.url === '/api/settings')?.body).toEqual({ grind_mode: 'simple' }));
  });
});

describe('PR panel merge', () => {
  const pull = (over: Record<string, unknown>) => ({
    number: 40, title: 'T', url: 'https://github.com/o/r/pull/40', state: 'open', author: 'me', created_at: '2026-01-01T00:00:00Z', head: 'f', base: 'main',
    labels: [], assignees: [], milestone: null, body_html: '', additions: 1, deletions: 0, file_count: 0, files: [], commit_count: 0, commits: [], conversation: [], checks: [], ...over,
  });
  async function open(p: Record<string, unknown>) {
    mock({ extra: { '/api/pulls/o/r/40': () => json(pull(p)) } });
    window.location.hash = '#/inbox?repo=o/r';
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', { level: 1, name: 'Inbox' });
    await user.keyboard('{Control>}k{/Control}');
    return user;
  }
  it('warnings change the confirm button to Merge anyway', async () => {
    mock({ extra: { '/api/pulls/o/r/40': () => json(pull({ checks: [{ name: 'ci', link: null, bucket: 'red' }] })) } });
    window.location.hash = '#/inbox?repo=o/r';
    const { WorkPanel } = await import('./panels/WorkPanel');
    const { QueryProvider } = await import('./QueryProvider');
    const { ConfirmProvider } = await import('./components');
    const { HashRouter } = await import('react-router-dom');
    const { PanelProvider } = await import('./panels/PanelContext');
    const user = userEvent.setup();
    render(<QueryProvider><ConfirmProvider><HashRouter><PanelProvider><WorkPanel kind="pr" repo="o/r" n={40} /></PanelProvider></HashRouter></ConfirmProvider></QueryProvider>);
    await user.click(await screen.findByRole('button', { name: 'Merge…' }));
    expect(screen.getByText(/1 check failing/)).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Merge anyway' }));
    await waitFor(() => expect(posts.some((p) => p.url === '/api/pulls/o/r/40/merge')).toBe(true));
    void open;
  });
  it('mergeWarnings: failing, running, review state', () => {
    expect(mergeWarnings([], [])).toEqual(['no approving review']);
    expect(mergeWarnings([{ name: 'a', link: null, bucket: 'pending' }], [{ kind: 'review', verdict: 'APPROVED', author: 'x', at: null, body_html: '' }])).toEqual(['1 check still running']);
    expect(mergeWarnings([{ name: 'a', link: null, bucket: 'green' }], [{ kind: 'review', verdict: 'APPROVED', author: 'x', at: null, body_html: '' }])).toEqual([]);
    expect(mergeWarnings([], [{ kind: 'review', verdict: 'CHANGES_REQUESTED', author: 'x', at: null, body_html: '' }])).toEqual(['changes requested']);
  });
});

describe('PR panel close and reopen', () => {
  const pull = (over: Record<string, unknown>) => ({
    number: 40, title: 'T', url: 'https://github.com/o/r/pull/40', state: 'open', author: 'me', created_at: '2026-01-01T00:00:00Z', head: 'f', base: 'main',
    labels: [], assignees: [], milestone: null, body_html: '', additions: 1, deletions: 0, file_count: 0, files: [], commit_count: 0, commits: [], conversation: [], checks: [], ...over,
  });
  async function open(state: string, stateRoute?: () => Promise<Response>) {
    mock({ extra: { '/api/pulls/o/r/40': () => json(pull({ state })), ...(stateRoute ? { '/api/pulls/o/r/40/state': stateRoute } : {}) } });
    window.location.hash = '#/inbox?repo=o/r';
    const { WorkPanel } = await import('./panels/WorkPanel');
    const { QueryProvider } = await import('./QueryProvider');
    const { ConfirmProvider } = await import('./components');
    const { HashRouter } = await import('react-router-dom');
    const { PanelProvider } = await import('./panels/PanelContext');
    const user = userEvent.setup();
    render(<QueryProvider><ConfirmProvider><HashRouter><PanelProvider><WorkPanel kind="pr" repo="o/r" n={40} /></PanelProvider></HashRouter></ConfirmProvider></QueryProvider>);
    await screen.findByText('PR on GitHub');
    return user;
  }
  const btn = (n: string) => screen.queryByRole('button', { name: n });
  it('open and draft show Close PR… only; merged shows neither; closed shows Reopen PR only', async () => {
    await open('open');
    expect(btn('Close PR…')).toBeTruthy();
    expect(btn('Reopen PR')).toBeNull();
    cleanup();
    await open('draft');
    expect(btn('Close PR…')).toBeTruthy();
    expect(screen.getByText(/Draft PRs cannot be merged/)).toBeTruthy();
    cleanup();
    await open('merged');
    expect(btn('Close PR…') ?? btn('Reopen PR')).toBeNull();
    cleanup();
    await open('closed');
    expect(btn('Close PR…')).toBeNull();
    expect(btn('Reopen PR')).toBeTruthy();
  });
  it('Close PR… asks, Cancel and Esc return focus, Confirm posts closed', async () => {
    const user = await open('open');
    await user.click(btn('Close PR…')!);
    expect(screen.getByText('Close PR #40 without merging? The branch is kept.')).toBeTruthy();
    await user.click(btn('Cancel')!);
    expect(screen.queryByRole('alertdialog')).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(btn('Close PR…')));
    await user.click(btn('Close PR…')!);
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(posts.some((p) => p.url.endsWith('/state'))).toBe(false);
    await user.click(btn('Close PR…')!);
    await user.click(btn('Close PR')!);
    await waitFor(() => expect(posts).toContainEqual({ url: '/api/pulls/o/r/40/state', body: { state: 'closed' } }));
  });
  it('Reopen PR posts open with no confirm', async () => {
    const user = await open('closed');
    await user.click(btn('Reopen PR')!);
    expect(screen.queryByRole('alertdialog')).toBeNull();
    await waitFor(() => expect(posts).toContainEqual({ url: '/api/pulls/o/r/40/state', body: { state: 'open' } }));
  });
  it('a refusal shows GitHub\'s message, keeps the state and the confirm usable', async () => {
    const user = await open('open', () => json({ error: 'head branch was deleted' }, 422));
    await user.click(btn('Close PR…')!);
    await user.click(btn('Close PR')!);
    expect(await screen.findByText('head branch was deleted')).toBeTruthy();
    expect(screen.getByText('PR open')).toBeTruthy();
    expect((btn('Close PR') as HTMLButtonElement).disabled).toBe(false);
  });
  it('a Reopen refusal shows in the normal footer', async () => {
    const user = await open('closed', () => json({ error: 'cannot reopen' }, 422));
    await user.click(btn('Reopen PR')!);
    expect(await screen.findByText('cannot reopen')).toBeTruthy();
    expect(screen.getByText('PR closed')).toBeTruthy();
  });
  it('buttons are disabled while the request is pending', async () => {
    let release: (r: Response) => void = () => {};
    const user = await open('open', () => new Promise<Response>((r) => { release = r; }));
    await user.click(btn('Close PR…')!);
    await user.click(btn('Close PR')!);
    await waitFor(() => expect((btn('Close PR') as HTMLButtonElement).disabled).toBe(true));
    release(new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
  });
});

describe('work panel action keys', () => {
  const pull = (over: Record<string, unknown> = {}) => ({ number: 40, title: 'PR T', url: 'https://github.com/o/r/pull/40', state: 'open', author: 'me', created_at: '2026-01-01T00:00:00Z', head: 'f', base: 'main', body_html: '', additions: 1, deletions: 0, file_count: 0, files: [], commit_count: 0, commits: [], conversation: [], checks: [], ...over });
  const ready = (over: Record<string, unknown> = {}) => card(12, 'in_review', { pr: { n: 40, draft: false, ci: 'success', url: 'u' }, mergeable: true, ...over });
  async function openPanel(p: Record<string, unknown> = {}, c = ready()) {
    mock({ prds: [prd({ issues: 1, column: 'refined' })], lanes: [lane([c])], extra: { '/api/pulls/o/r/40': () => json(pull(p)), '/api/issues/o/r/12': () => json({ number: 12, title: 'Task 12', state: 'open', url: 'u', author: 'me', created_at: '2026-01-01T00:00:00Z', labels: [], assignees: [], body_html: '', comments: [], comment_count: 0, is_pr: false }) } });
    window.location.hash = '#/features/f1/issues?repo=o/r';
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Task 12' }));
    const panel = await screen.findByRole('complementary', { name: 'Issue details' });
    await user.click(await within(panel).findByRole('tab', { name: 'PR overview' }));
    await within(panel).findByText('PR open');
    (document.activeElement as HTMLElement | null)?.blur();
    return { user, panel };
  }
  it('M asks, Esc cancels back to Merge…, M then Enter merges', async () => {
    const { user, panel } = await openPanel();
    await user.keyboard('m');
    expect(await screen.findByText(/Merge PR #40 into main/)).toBeTruthy();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(posts.some((p) => p.url.endsWith('/merge'))).toBe(false);
    expect(screen.getByRole('complementary', { name: 'Issue details' })).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(within(panel).getByRole('button', { name: /^Merge…/ })));
    await user.keyboard('m');
    await screen.findByRole('alertdialog');
    await user.keyboard('{Enter}');
    await waitFor(() => expect(posts.some((p) => p.url === '/api/pulls/o/r/40/merge')).toBe(true));
  });
  it('M does nothing on a conflicting PR', async () => {
    await openPanel({ conflict: true });
    await userEvent.keyboard('m');
    expect(screen.queryByRole('alertdialog')).toBeNull();
  });
  it('S presses Skip CI on a paused grind', async () => {
    const { user } = await openPanel({}, ready({ mergeable: false, grind: { state: 'paused', round: 1 } }));
    await user.keyboard('s');
    await waitFor(() => expect(posts.some((p) => p.url === '/api/grind/skip-ci')).toBe(true));
  });
  it('C focuses the Conversation comment box and typing m merges nothing', async () => {
    const { user, panel } = await openPanel();
    await user.click(within(panel).getByRole('tab', { name: 'Conversation' }));
    await user.keyboard('c');
    const box = await within(panel).findByLabelText('Comment on the PR');
    await waitFor(() => expect(document.activeElement).toBe(box));
    await user.keyboard('m');
    expect((box as HTMLTextAreaElement).value).toBe('m');
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(posts.length).toBe(0);
  });
});

describe('Features across repos', () => {
  const repos = ['o/a', 'o/b', 'o/c'].map((slug) => ({ slug, name: slug.slice(2).toUpperCase(), path: `/x/${slug}` }));
  const pl = (repo: string, prds: any[], over: Record<string, unknown> = {}) => ({ repo, stale: false, fetched_at: 1, prds, ...over });
  const dl = (repo: string, lanes: any[], over: Record<string, unknown> = {}) => ({ repo, stale: false, fetched_at: 1, cap: 2, running: 0, auto_grind: false, lanes, ...over });
  const feat = (slug: string, epic: number) => prd({ slug, title: `Feat ${slug}`, epic, column: 'building', issues: 1, refined: 1 });
  const run = (repo: string, epic: number) => ({ id: 'd1', state: 'running', epic: `${repo}#${epic}`, totals: { seconds: 1, cost: 0 }, lanes: [{ n: 1, key: 'l1', stage: 'building', needs_you: 'waiting on you' }] });
  const three = () => mock({
    repos,
    all: {
      plan: [pl('o/a', [feat('a1', 1), feat('a2', 2)]), pl('o/b', [feat('b1', 3), feat('b2', 4), feat('b3', 5)]), pl('o/c', [prd({ slug: 'c1', title: 'Done', epic: 6, column: 'shipped' })])],
      del: [dl('o/a', [lane([card(1, 'in_review')], { epic: 1 }), lane([card(2, 'ready')], { epic: 2 })]), dl('o/b', [lane([card(3, 'ready')], { epic: 3 }), lane([card(4, 'ready')], { epic: 4 }), lane([card(5, 'ready')], { epic: 5 })]), dl('o/c', [lane([card(6, 'merged')], { epic: 6 })])],
    },
    extra: { '/api/dispatches': () => json({ dispatches: [run('o/a', 2)] }) },
  });
  const headings = () => [...document.querySelectorAll('.fgroup-h')].map((h) => h.textContent ?? '');

  it('groups by repo, the repo with a feature stopped on you first, the empty repo as one line', async () => {
    three();
    window.location.hash = '#/features?repo=o/b';
    render(<App />);
    await screen.findByText('Feat a1');
    const h = headings();
    expect(h[0]).toContain('A');
    expect(h[0]).toContain('2 in progress · 0 shipped');
    expect(h[1]).toContain('3 in progress');
    expect(screen.getByText(/nothing in progress/).textContent).toContain('1 shipped');
    expect(screen.queryByText('Shipped')).toBeNull();
    expect(screen.getByText(/5 in progress across 2 repos; 1 is stopped on you/)).toBeTruthy();
  });

  it('a card in another repo opens and acts on its own repo, not the switcher\'s', async () => {
    three();
    window.location.hash = '#/features?repo=o/a';
    render(<App />);
    const link = await screen.findByRole('link', { name: 'Feat b1' });
    expect(link.getAttribute('href')).toBe('#/features/b1?repo=o/b');
    const user = userEvent.setup();
    await user.click(within(screen.getByRole('article', { name: 'Feat b1' })).getByRole('button', { name: 'Run epic' }));
    expect((await screen.findByLabelText('Epic') as HTMLInputElement).value).toBe('o/b#3');
  });

  it('the filter sets only, leaves repo, and All repos clears it', async () => {
    three();
    window.location.hash = '#/features?repo=o/a';
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText('Feat b1');
    await user.click(screen.getByRole('button', { name: /Repo filter/ }));
    await user.click(await screen.findByText('b'));
    await waitFor(() => expect(window.location.hash).toContain('only=o%2Fb'.replace('%2F', '/')));
    expect(window.location.hash).toContain('repo=o/a');
    await user.click(screen.getByRole('button', { name: /Repo filter/ }));
    await user.click(await screen.findByText('All repos'));
    await waitFor(() => expect(window.location.hash).not.toContain('only='));
  });

  it('a loading or stale repo is never shown as empty, and a meta-only entry shows its error', async () => {
    mock({
      repos,
      all: {
        plan: [pl('o/a', [], { fetched_at: null, stale: true }), pl('o/b', [], { stale: true, error: 'boom' }), { repo: 'o/c', stale: true, fetched_at: null, error: 'gh failed' }],
        del: [dl('o/a', [], { fetched_at: null, stale: true }), dl('o/b', []), { repo: 'o/c', stale: true, fetched_at: null }],
      },
    });
    window.location.hash = '#/features?repo=o/a';
    render(<App />);
    expect((await screen.findAllByText('Still loading…')).length).toBeGreaterThan(0);
    expect(screen.getByText(/GitHub data is stale: boom/)).toBeTruthy();
    expect(screen.queryByText(/nothing in progress/)).toBeNull();
  });

  it('no watched repo shows the empty text', async () => {
    mock({ all: { plan: [], del: [] } });
    window.location.hash = '#/features';
    render(<App />);
    expect(await screen.findByText('No repo opened recently. Pick one in the filter.')).toBeTruthy();
  });
});
