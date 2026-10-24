import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';

const json = (b: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } }));
const AFK = { active: false, until: null, started: null, decisions: 0, held: 0, summary: null };
const base = (o: Record<string, unknown> = {}) => ({ id: 's1', command: '/ai-workflow:implement-issue 801', repo: '/x', link: { owner: 'o', repo: 'r', issue: 801 }, session_id: 'cl1', outcome: 'done', cost: 0.5, tokens: { input: 100, output: 50 }, started_at: new Date().toISOString(), ended_at: new Date().toISOString(), waiting: false, pending_question: null, error: null, note: null, peer_review: null, no_repo: false, vault_folder: null, repo_path: '/x', resume_command: null, ...o });
const item = (type: string, group: string, o: Record<string, unknown> = {}) => ({ key: `${type}:1`, group, type, repo: 'o/r', at: null, ...o });

let routes: Record<string, unknown>;
let posts: [string, unknown][];
beforeEach(() => {
  localStorage.clear();
  posts = [];
  routes = {
    '/api/repos': { repos: [{ slug: 'o/r', name: 'R', path: '/x' }], can_browse: false, scan_roots: [] },
    '/api/sessions': { sessions: [], limits: {}, usage: {}, afk: AFK },
    '/api/inbox': { items: [], afk: AFK, gh: { ok: true } },
    '/api/settings': { commands: [{ label: 'work', cmd: 'c1' }, { label: 'personal', cmd: 'c2' }], default: 'work' },
  };
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const path = String(url).split('?')[0];
    if (init?.method === 'POST') { posts.push([path, init.body ? JSON.parse(init.body as string) : null]); return json({ id: 'new1', removed: 1 }); }
    return path in routes ? json(routes[path]) : json({ error: 'nf' }, 404);
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('Inbox', () => {
  it('groups items with counts and renders each type with its actions', async () => {
    routes['/api/inbox'] = {
      afk: AFK, gh: { ok: false },
      items: [
        item('gh_auth', 'block', { repo: null, error: 'not logged in' }),
        item('question', 'answer', { key: 'q', session_id: 's1', command: '/x:implement-issue 1', questions: [{ question: 'Which DB?', multiSelect: false, allowFreeText: false, options: [{ label: 'A' }] }], process_alive: false }),
        item('review_cap', 'decide', { key: 'rc', prd_path: 'docs/prds/my-feat.md', panel: 'p1', round: 3, max_rounds: 3, note: 'cap' }),
        item('pr_ready', 'decide', { key: 'pr', pr: 7, issue: 5, title: 'T', reviewer: 'bot', checks: 4 }),
        item('grind_paused', 'fix', { key: 'g', pr: 8, issue: 5, round: 2, reason: 'CI failing' }),
        item('session_failed', 'fix', { key: 'f', session_id: 's2', command: '/x:pr-grind 8', error: 'boom' }),
        item('needs_cleanup', 'fix', { key: 'c', issue: 9, uncommitted: ['a.ts'], unpushed: [] }),
        item('repo_unpublished', 'setup', { key: 'u', repo: 'local/foo', slug: 'local/foo', path: '/p' }),
        item('limited', 'wait', { key: 'l', session_id: 's3', command: '/x:refine-issues 2', account: 'work', resets_at: 4102444800, auto_resume: true }),
        item('queued', 'wait', { key: 'qd', session_id: 's4', command: '/x:dump', reason: 'account is rate limited' }),
      ],
    };
    routes['/api/sessions/s1'] = base({ id: 's1', outcome: 'waiting', waiting: true, ended_at: 'x', pending_question: { id: 'r', questions: [{ question: 'Which DB?', multiSelect: false, allowFreeText: false, options: [{ label: 'A' }] }] } });
    window.location.hash = '#/inbox?repo=o/r';
    render(<App />);
    const group = async (name: string) => within(await screen.findByRole('region', { name }));
    expect((await group('Blocking everything')).getByText('GitHub CLI is not signed in')).toBeTruthy();
    expect((await group('Decide')).getByText('PR #7 is ready to merge')).toBeTruthy();
    expect((await group('Decide')).getByText(/round limit on “my feat”/)).toBeTruthy();
    const fix = await group('Fix');
    expect(fix.getByText('Grind paused on PR #8')).toBeTruthy();
    expect(fix.getByText('Worktree for #9 has unsaved work')).toBeTruthy();
    expect((await group('Set up')).getByRole('button', { name: 'Publish to GitHub' })).toBeTruthy();
    expect((await group('Waiting (nothing to do)')).getByText('refine-issues 2 paused by usage limit')).toBeTruthy();
    // the first question is expanded by default
    expect(await screen.findByRole('button', { name: 'Send answer and resume' })).toBeTruthy();
    // 8 items need you (everything but the 2 waiting)
    await waitFor(() => expect(document.title).toBe('(8) aiw'));
  });

  it('run 2 more rounds posts to the panel', async () => {
    routes['/api/inbox'] = { afk: AFK, gh: { ok: true }, items: [item('review_cap', 'decide', { prd_path: 'docs/prds/f.md', panel: 'p1', round: 3, max_rounds: 3 })] };
    window.location.hash = '#/inbox';
    render(<App />);
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Run 2 more rounds' }));
    await waitFor(() => expect(posts).toContainEqual(['/api/review/p1/rounds', { add: 2 }]));
  });

  it('empty inbox says all clear', async () => {
    window.location.hash = '#/inbox';
    render(<App />);
    expect(await screen.findByText('All clear')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'See what is running' })).toBeTruthy();
  });

  it('away banner says Claude answers every question', async () => {
    const now = Math.floor(Date.now() / 1000);
    const afk = { ...AFK, active: true, until: now + 3600, started: now };
    routes['/api/sessions'] = { sessions: [], limits: {}, usage: {}, afk };
    routes['/api/inbox'] = { items: [], gh: { ok: true }, afk };
    window.location.hash = '#/inbox';
    render(<App />);
    expect(await screen.findByText(/Opus decides/)).toBeTruthy();
    expect(screen.queryByText(/rest waits in your Inbox/)).toBeNull();
  });

  it('shows and dismisses the away summary', async () => {
    routes['/api/inbox'] = { items: [], gh: { ok: true }, afk: { ...AFK, summary: { started: 1700000000, ended: 1700003600, held: 2, log: [{ at: 1700000100, kind: 'answer', sid: 's1', command: 'x', picked: 'A' }] } } };
    window.location.hash = '#/inbox';
    render(<App />);
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Dismiss' }));
    await waitFor(() => expect(posts).toContainEqual(['/api/afk/dismiss', {}]));
  });
});

describe('Session page', () => {
  const open = (s: Record<string, unknown>, events: unknown[] = []) => {
    routes['/api/sessions/s1'] = s;
    routes['/api/sessions/s1/stream'] = { events, offset: events.length ? 10 : 0 };
    window.location.hash = '#/sessions/s1';
    render(<App />);
  };
  it('404 shows Session not found', async () => {
    window.location.hash = '#/sessions/nope';
    render(<App />);
    expect(await screen.findByText('Session not found')).toBeTruthy();
  });
  it('renders the peer_review object without crashing, and the transcript', async () => {
    open(base({ peer_review: { state: 'running', approved: 2, total: 5, round: 1, lenses: {} } }), [{ kind: 'text', text: 'hello there' }, { kind: 'tool', name: 'Bash', input: { command: 'ls' } }, { kind: 'result', text: 'done', cost: 0.5 }]);
    expect(await screen.findByText(/Peer review: running · 2\/5 approve · round 1/)).toBeTruthy();
    expect(await screen.findByText('hello there')).toBeTruthy();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Bash/ }));
    expect(document.querySelector('.ev pre')?.textContent).toContain('"command": "ls"');
    await user.type(screen.getByLabelText('Search the transcript'), 'zzz');
    expect(await screen.findByText('No events match.')).toBeTruthy();
  });
  it('failed shows the error with Retry and Continue in terminal', async () => {
    open(base({ outcome: 'failed', error: 'it broke' }));
    expect(await screen.findByText(/it broke/)).toBeTruthy();
    await userEvent.setup().click(screen.getAllByRole('button', { name: 'Retry' })[0]);
    await waitFor(() => expect(posts.some(([p]) => p === '/api/sessions/s1/resume')).toBe(true));
    expect(screen.getAllByRole('button', { name: 'Continue in terminal' }).length).toBeGreaterThan(0);
  });
  it('limited shows reset time and resume-on-another-account', async () => {
    open(base({ outcome: 'limited', ended_at: null, claude_cmd: 'c1', limit_resets_at: 4102444800, auto_resume: true }));
    expect(await screen.findByText(/Resumes on its own at/)).toBeTruthy();
    expect(screen.getByRole('button', { name: "Don't auto-resume" })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Resume on another account' })).toBeTruthy();
  });
  it('waiting shows the question form and disables the composer', async () => {
    open(base({ outcome: 'waiting', waiting: true, pending_question: { id: 'r', questions: [{ question: 'Pick?', multiSelect: false, allowFreeText: false, options: [{ label: 'A' }] }] } }));
    expect(await screen.findByText('Claude is waiting on you')).toBeTruthy();
    expect((screen.getByLabelText('Message to this session') as HTMLTextAreaElement).disabled).toBe(true);
  });
  it('queued shows the reason and Start now; a finished create-prd session offers Create repo', async () => {
    open(base({ outcome: 'queued', note: 'queued: account is rate limited' }));
    expect(await screen.findByRole('button', { name: 'Start now' })).toBeTruthy();
    cleanup();
    routes['/api/vault/prd'] = { exists: true, status: 'Draft', title: 'My PRD' };
    open(base({ command: '/ai-workflow:create-prd idea', no_repo: true, vault_folder: '05-Work/P', link: null }));
    expect(await screen.findByRole('button', { name: 'Create repo' })).toBeTruthy();
    expect(await screen.findByText(/Status: Draft/)).toBeTruthy();
  });
});

describe('Activity', () => {
  it('lists live cards and filtered history', async () => {
    routes['/api/sessions'] = { limits: {}, usage: {}, afk: AFK, sessions: [base({ id: 'a', outcome: 'running', ended_at: null }), base({ id: 'b', outcome: 'done' }), base({ id: 'c', outcome: 'failed', command: '/x:dump' })] };
    window.location.hash = '#/activity';
    render(<App />);
    expect(await screen.findByText('Live')).toBeTruthy();
    const user = userEvent.setup();
    const hist = within(await screen.findByRole('region', { name: 'History' }));
    expect(hist.getAllByRole('row').length).toBe(3); // head + 2
    await user.selectOptions(hist.getByLabelText('Result'), 'failed');
    expect(hist.getAllByRole('row').length).toBe(2);
  });
});
