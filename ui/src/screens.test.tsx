import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { mergeWarnings } from './panels/prWarnings';

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

function mock(o: { fetchedAt?: number | null; delFetchedAt?: number | null; stale?: boolean; prds?: any[]; lanes?: any[]; extra?: Record<string, (init?: RequestInit) => Promise<Response>> } = {}) {
  posts.length = 0;
  const routes: Record<string, unknown> = {
    '/api/repos': { repos: [{ slug: 'o/r', name: 'R', path: '/x' }], can_browse: false, scan_roots: [] },
    '/api/sessions': { sessions: [], limits: {}, usage: {}, afk: { active: false, until: null, started: null, decisions: 0, held: 0, summary: null }, gh: { ok: true } },
    '/api/inbox': { items: [], afk: {}, gh: { ok: true } },
    '/api/planning': { repo: 'o/r', stale: o.stale ?? false, fetched_at: o.fetchedAt === undefined ? 1 : o.fetchedAt, prds: o.prds ?? [] },
    '/api/delivery': { repo: 'o/r', stale: o.stale ?? false, fetched_at: o.delFetchedAt === undefined ? 1 : o.delFetchedAt, cap: 2, running: 0, auto_grind: false, lanes: o.lanes ?? [] },
    '/api/settings': { commands: [{ label: 'main', cmd: 'claude' }, { label: 'work', cmd: 'claude2' }], default: 'main' },
    '/api/peer-review': { default: ['critical', 'qa'], max_rounds: 5, kinds: { custom: ['critical', 'qa', 'ux'] } },
  };
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const path = String(url).split('?')[0];
    if (init?.method === 'POST' || init?.method === 'PUT') posts.push({ url: path, body: JSON.parse(String(init.body ?? '{}')) });
    if (o.extra?.[path]) return o.extra[path](init);
    if (init?.method === 'POST') return json({ id: 'sess1' }, 201);
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
    window.location.hash = '#/features?repo=o/r';
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
      window.location.hash = '#/features?repo=o/r';
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
    const text = document.body.textContent ?? '';
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
  it('empty repo shows the idea box and starts create-prd', async () => {
    mock();
    window.location.hash = '#/features?repo=o/r';
    const user = userEvent.setup();
    render(<App />);
    await user.type(await screen.findByLabelText('Describe the feature'), 'CSV import');
    await user.click(screen.getByRole('button', { name: 'Write the PRD' }));
    await waitFor(() => expect(posts.find((p) => p.url === '/api/sessions')?.body).toMatchObject({ repo: 'o/r', command: 'create-prd', args: 'CSV import', model: 'opus', effort: 'medium' }));
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

describe('Other issues and dispatch-owned issues', () => {
  it('lists open issues outside every feature; a card starts headless only and a 409 toasts the running session', async () => {
    mock({
      prds: [prd({ issues: 1 })],
      lanes: [lane([card(11, 'ready')]), lane([card(30, 'ready'), card(31, 'unrefined')], { epic: null, title: 'No epic' })],
      extra: { '/api/start': () => json({ error: 'already running', id: 'abc', href: '#/session/abc' }, 409) },
    });
    window.location.hash = '#/features?repo=o/r';
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('link', { name: /Other issues/ }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Other issues' })).toBeTruthy();
    expect(screen.getByText('Task 30')).toBeTruthy();
    expect(screen.queryByText('Task 11')).toBeNull(); // part of the feature
    await user.click(await screen.findByRole('button', { name: 'More ways to start' }));
    expect(screen.queryByRole('menuitem', { name: /herdr tab/ })).toBeNull();
    await user.keyboard('{Escape}');
    await user.click(screen.getByRole('button', { name: 'Start' }));
    expect(await screen.findByRole('button', { name: 'Open session' })).toBeTruthy();
    const body = posts.find((p) => p.url === '/api/start')?.body;
    expect(body).toMatchObject({ skill: 'implement-issue' });
    expect(body).not.toHaveProperty('model'); // only the planning starts carry PLAN_RUN
  });

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
    window.location.hash = '#/features?repo=o/r';
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
