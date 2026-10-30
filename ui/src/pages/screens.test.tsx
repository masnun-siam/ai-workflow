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
let changeReply: { status: number; body: unknown };
beforeEach(() => {
  localStorage.clear();
  posts = [];
  changeReply = { status: 200, body: { results: [] } };
  routes = {
    '/api/repos': { repos: [{ slug: 'o/r', name: 'R', path: '/x' }], can_browse: false, scan_roots: [] },
    '/api/sessions': { sessions: [], limits: {}, usage: {}, afk: AFK },
    '/api/inbox': { items: [], afk: AFK, gh: { ok: true } },
    '/api/settings': { commands: [{ label: 'work', cmd: 'c1' }, { label: 'personal', cmd: 'c2' }], default: 'work' },
  };
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const path = String(url).split('?')[0];
    if (init?.method === 'POST') { posts.push([path, init.body ? JSON.parse(init.body as string) : null]); if (path === '/api/afk/change') return json(changeReply.body, changeReply.status); return json({ id: 'new1', removed: 1 }); }
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
        item('prd_comment', 'decide', { key: 'pc', share: 'sh1', prd_path: 'docs/prds/my-feat.md', prd_title: 'My feat', summary: '2 new comments on My feat', comments: 2, approvals: 0 }),
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
    expect((await group('Decide')).getByText('2 new comments on My feat')).toBeTruthy();
    expect((await group('Decide')).getByRole('link', { name: /Open PRD/ }).getAttribute('href')).toMatch(/\/features\/my-feat\/prd\?repo=o\/r$/);
    expect((await group('Decide')).getByText(/round limit on “my feat”/)).toBeTruthy();
    const fix = await group('Fix');
    expect(fix.getByText('Grind paused on PR #8')).toBeTruthy();
    expect(fix.getByText('Worktree for #9 has unsaved work')).toBeTruthy();
    expect((await group('Set up')).getByRole('button', { name: 'Publish to GitHub' })).toBeTruthy();
    expect((await group('Waiting (nothing to do)')).getByText('refine-issues 2 paused by usage limit')).toBeTruthy();
    // the first question is expanded by default
    expect(await screen.findByRole('button', { name: 'Send answer and resume' })).toBeTruthy();
    // 9 items need you (everything but the 2 waiting)
    await waitFor(() => expect(document.title).toBe('(9) aiw'));
  });

  it('run 2 more rounds posts to the panel', async () => {
    routes['/api/inbox'] = { afk: AFK, gh: { ok: true }, items: [item('review_cap', 'decide', { prd_path: 'docs/prds/f.md', panel: 'p1', round: 3, max_rounds: 3 })] };
    window.location.hash = '#/inbox';
    render(<App />);
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Run 2 more rounds' }));
    await waitFor(() => expect(posts).toContainEqual(['/api/review/p1/rounds', { add: 2 }]));
  });

  describe('bootstrap cards', () => {
    const phases = (states: string[]) => ['audit', 'decide', 'constitution', 'guides', 'gates', 'docs'].map((name, i) => ({ name, state: states[i], session_id: states[i] === 'pending' ? null : `ps${i}` }));
    const runRec = (id: string, state: string, states: string[]) => ({ id, repo: 'o/r', issue: 12, branch: 'b', phases: phases(states), state, error: null, created_at: '', updated_at: '' });
    const load = async (items: unknown[], runs: unknown[]) => {
      routes['/api/inbox'] = { afk: AFK, gh: { ok: true }, items };
      routes['/api/bootstraps'] = { runs };
      window.location.hash = '#/inbox?repo=o/r';
      render(<App />);
    };
    const waiting = item('bootstrap_waiting', 'decide', { key: 'bw', run_id: 'w1', issue: 12, next_phase: 'decide' });
    const stopped = item('bootstrap_stopped', 'fix', { key: 'bs', run_id: 'x1', issue: 12, phase: 'guides', session_id: 'ps3', error: 'guides blew up' });

    it('a waiting run is a Decide card with Continue and a confirmed Stop, and shows its strip', async () => {
      await load([waiting], [runRec('w1', 'waiting', ['done', 'pending', 'pending', 'pending', 'pending', 'pending'])]);
      const decide = within(await screen.findByRole('region', { name: 'Decide' }));
      expect(decide.getByText('Bootstrap of r is waiting: audit issue #12 is ready for the team')).toBeTruthy();
      await waitFor(() => expect(decide.getAllByRole('listitem')).toHaveLength(6));
      expect(decide.getByRole('listitem', { current: 'step' }).textContent).toBe('decidePending');
      const u = userEvent.setup();
      await u.click(decide.getByRole('button', { name: /Continue bootstrap/ }));
      await waitFor(() => expect(posts).toContainEqual(['/api/bootstraps/w1/continue', {}]));
      await u.click(decide.getByRole('button', { name: /^Stop/ }));
      expect(posts.some(([p]) => p === '/api/bootstraps/w1/stop')).toBe(false);
      await u.click(await screen.findByRole('button', { name: 'End bootstrap' }));
      await waitFor(() => expect(posts).toContainEqual(['/api/bootstraps/w1/stop', {}]));
    });

    it('a stopped run is a Fix card with the error, Retry phase and the failed session link', async () => {
      await load([stopped], [runRec('x1', 'stopped', ['done', 'done', 'done', 'failed', 'pending', 'pending'])]);
      const fix = within(await screen.findByRole('region', { name: 'Fix' }));
      expect(fix.getByText('Bootstrap of r stopped at guides')).toBeTruthy();
      expect(fix.getByText('guides blew up')).toBeTruthy();
      expect(fix.getByRole('link', { name: /Open session/ }).getAttribute('href')).toBe('#/sessions/ps3');
      await waitFor(() => expect(fix.getByRole('listitem', { current: 'step' }).textContent).toBe('guidesFailed'));
      await userEvent.setup().click(fix.getByRole('button', { name: /Retry phase/ }));
      await waitFor(() => expect(posts).toContainEqual(['/api/bootstraps/x1/retry', {}]));
    });

    it('hides Open session without a session id and shows no strip when the run is not listed', async () => {
      await load([{ ...stopped, session_id: null, error: null }], []);
      const fix = within(await screen.findByRole('region', { name: 'Fix' }));
      expect(fix.queryByRole('link', { name: /Open session/ })).toBeNull();
      expect(fix.queryByRole('list')).toBeNull();
    });
  });

  describe('keyboard', () => {
    const pr = (n: number) => ({ number: n, title: `PR ${n}`, url: `https://github.com/o/r/pull/${n}`, state: 'open', author: 'me', created_at: '2026-01-01T00:00:00Z', head: 'f', base: 'main', body_html: '', additions: 1, deletions: 0, file_count: 0, files: [], commit_count: 0, commits: [], conversation: [], checks: [] });
    const rd = (n: number) => item('pr_ready', 'decide', { key: `pr${n}`, pr: n, issue: null, title: `T${n}`, reviewer: 'bot', checks: 1 });
    const q = { question: 'Which DB?', multiSelect: false, allowFreeText: false, options: [{ label: 'A' }, { label: 'B' }] };
    const qItem = item('question', 'answer', { key: 'q', session_id: 's1', command: '/x:implement-issue 1', questions: [q], process_alive: false });
    const sessionRoute = () => { routes['/api/sessions/s1'] = base({ id: 's1', outcome: 'waiting', waiting: true, ended_at: 'x', pending_question: { id: 'r', questions: [q] } }); };
    const panelOf = (n: number) => screen.findByRole('heading', { name: new RegExp(`PR #${n}\\s*PR ${n}`) });
    const rows = () => [...document.querySelectorAll<HTMLElement>('.item')];
    const load = async (items: unknown[]) => {
      routes['/api/inbox'] = { afk: AFK, gh: { ok: true }, items };
      routes['/api/pulls/o/r/7'] = pr(7);
      routes['/api/pulls/o/r/8'] = pr(8);
      window.location.hash = '#/inbox';
      render(<App />);
      await screen.findByText('PR #7 is ready to merge');
    };

    it('J J J K outlines the second item across groups; nothing is outlined before a key', async () => {
      await load([rd(7), rd(8), item('grind_paused', 'fix', { key: 'g', pr: 9, issue: null, round: 1, reason: 'CI' })]);
      expect(document.querySelector('[data-selected]')).toBeNull();
      const u = userEvent.setup();
      await u.keyboard('jjjk'); // the first J selects the first row
      expect(rows()[1].hasAttribute('data-selected')).toBe(true);
      expect(document.activeElement).toBe(rows()[1]);
      expect(document.querySelectorAll('[data-selected]')).toHaveLength(1);
    });

    it('Enter expands a question and focuses its first answer; Esc collapses and refocuses the row', async () => {
      sessionRoute();
      await load([qItem, rd(7)]);
      const u = userEvent.setup();
      await screen.findByRole('button', { name: /Send answer and resume/ });
      expect(document.activeElement?.tagName).not.toBe('INPUT'); // the default open does not take focus
      await u.keyboard('j{Enter}'); // collapses the default-open round
      await waitFor(() => expect(screen.queryByRole('button', { name: /Send answer and resume/ })).toBeNull());
      await u.keyboard('{Enter}');
      await screen.findByRole('button', { name: /Send answer and resume/ });
      await waitFor(() => expect(document.activeElement?.getAttribute('type')).toBe('radio'));
      await u.keyboard('{Escape}');
      await waitFor(() => expect(screen.queryByRole('button', { name: /Send answer and resume/ })).toBeNull());
      expect(document.activeElement).toBe(rows()[0]);
    });

    it('S on a paused grind confirms and sends skip CI', async () => {
      await load([rd(7), item('grind_paused', 'fix', { key: 'g', pr: 9, issue: null, round: 1, reason: 'CI' })]);
      const u = userEvent.setup();
      await u.keyboard('jj');
      await u.keyboard('s');
      await u.click(await screen.findByRole('button', { name: 'Skip CI and continue' }));
      await waitFor(() => expect(posts).toContainEqual(['/api/grind/skip-ci', { repo: 'o/r', pr: 9 }]));
      expect(await screen.findByText('Grind continues')).toBeTruthy();
    });

    it('M opens the PR panel, J follows to the next PR and Esc closes it with the row still selected', async () => {
      await load([rd(7), rd(8)]);
      const u = userEvent.setup();
      expect(screen.getAllByRole('button', { name: /Review and merge/ })[0].getAttribute('aria-keyshortcuts')).toBe('M');
      await u.keyboard('jm');
      expect(await panelOf(7)).toBeTruthy();
      await u.keyboard('j');
      expect(await panelOf(8)).toBeTruthy();
      await u.keyboard('{Escape}');
      await waitFor(() => expect(screen.queryByRole('heading', { name: /PR 8/ })).toBeNull());
      expect(rows()[1].hasAttribute('data-selected')).toBe(true);
    });

    it('Enter presses the primary button of a non-question item', async () => {
      await load([rd(7)]);
      await userEvent.setup().keyboard('j{Enter}');
      expect(await panelOf(7)).toBeTruthy();
    });

    it('selects the former third item after the second is removed by a poll', async () => {
      await load([rd(7), rd(8), item('grind_paused', 'fix', { key: 'g', pr: 9, issue: null, round: 1, reason: 'CI' })]);
      await userEvent.setup().keyboard('jj');
      expect(rows()[1].hasAttribute('data-selected')).toBe(true);
      routes['/api/inbox'] = { afk: AFK, gh: { ok: true }, items: [rd(7), item('grind_paused', 'fix', { key: 'g', pr: 9, issue: null, round: 1, reason: 'CI' })] };
      await new Promise((r) => setTimeout(r, 2100)); // past the query staleTime, so a focus refetches
      window.dispatchEvent(new Event('visibilitychange'));
      await waitFor(() => expect(rows()).toHaveLength(2));
      expect(rows()[1].hasAttribute('data-selected')).toBe(true);
      expect(rows()[1].textContent).toContain('PR #9');
    });

    const poll = async (items: unknown[]) => {
      routes['/api/inbox'] = { afk: AFK, gh: { ok: true }, items };
      await new Promise((r) => setTimeout(r, 2100)); // past the query staleTime, so a focus refetches
      window.dispatchEvent(new Event('visibilitychange'));
    };
    const q2Item = () => item('question', 'answer', { key: 'q2', session_id: 's2', command: '/x:implement-issue 2', questions: [{ ...q, question: 'Which cache?' }], process_alive: false });

    it('holds the order while a question is open, and applies it on Hide', async () => {
      sessionRoute();
      await load([qItem, q2Item(), rd(7)]);
      const u = userEvent.setup();
      expect(rows()[0].textContent).toContain('Which DB?'); // default-open, before any click
      await poll([q2Item(), qItem, rd(7)]);
      await new Promise((r) => setTimeout(r, 100));
      expect(rows()[0].textContent).toContain('Which DB?');
      const radio = within(rows()[0]).getAllByRole('radio')[0];
      await u.click(radio);
      expect(rows()[0].hasAttribute('data-selected')).toBe(true);
      await poll([q2Item(), qItem, rd(7)]);
      expect(rows()[0].textContent).toContain('Which DB?');
      expect(document.activeElement).toBe(radio);
      await u.click(within(rows()[0]).getByRole('button', { name: /Hide/ }));
      await waitFor(() => expect(rows()[0].textContent).toContain('Which cache?'));
    }, 15000);

    it('puts a new item last in its group while held', async () => {
      sessionRoute();
      await load([qItem, rd(7)]);
      await poll([qItem, item('question', 'answer', { key: 'q3', session_id: 's3', command: '/x:implement-issue 3', questions: [{ ...q, question: 'Which queue?' }], process_alive: false }), rd(7)]);
      await waitFor(() => expect(rows()).toHaveLength(3));
      expect(rows().map((r) => r.textContent?.includes('Which queue?'))).toEqual([false, true, false]);
    });

    it('holds the order while the side panel is open, and applies it on Esc', async () => {
      await load([rd(7), rd(8)]);
      const u = userEvent.setup();
      await u.keyboard('jm');
      expect(await panelOf(7)).toBeTruthy();
      await poll([rd(8), rd(7)]);
      await new Promise((r) => setTimeout(r, 100));
      expect(rows()[0].textContent).toContain('PR #7');
      await u.keyboard('{Escape}');
      await waitFor(() => expect(rows()[0].textContent).toContain('PR #8'));
    });

    it('? lists J / K and the selected row\'s action keys', async () => {
      await load([rd(7)]);
      const u = userEvent.setup();
      await u.keyboard('j');
      await u.keyboard('?');
      const dlg = await screen.findByRole('dialog');
      expect(within(dlg).getByText('J / K')).toBeTruthy();
      expect(within(dlg).getByText('M')).toBeTruthy();
      await u.keyboard('{Escape}');
    });

    it('X with nothing selected does nothing', async () => {
      await load([item('dispatch_done', 'wait', { key: 'dd', dispatch: 'd1', epic: 'E', feature_branch: null, final_prs: {} }), rd(7)]);
      await userEvent.setup().keyboard('x');
      expect(posts).toEqual([]);
    });
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

  it('away summary rows show picker, reasons, cost and checkboxes', async () => {
    const q = (question: string, picked: string[], why: string | null) => ({ question, multiSelect: false, allowFreeText: false, options: [{ label: 'A (Recommended)' }, { label: 'B' }], picked, why });
    const log = [
      { at: 1700000100, kind: 'answer', sid: 's1', command: 'implement-issue #455', question: 'Which store?', picked: 'A', id: 's1:r1', by: 'opus', answerer: 'ans1', cost: 0.31, changed: false, questions: [q('Which store?', ['A (Recommended)'], 'matches the state file')] },
      { at: 1700000200, kind: 'answer', sid: 's2', command: 'create-prd', question: 'How many epics?', picked: 'B', id: 's2:r1', by: 'recommended', answerer: null, cost: null, changed: false, questions: [q('How many epics?', ['B'], null)] },
      { at: 1700000300, kind: 'held', sid: 's3', command: 'create-tasks #470', question: 'Delete branch?', picked: '', id: 's3:r1', answerer: 'ans3', cost: 0.12, reason: 'destroys unmerged work', questions: [q('Delete branch?', [], null)] },
      { at: 1700000400, kind: 'answer', sid: 's4', command: 'legacy-cmd', question: 'Old?', picked: 'Yes' },
      { at: 1700000500, kind: 'answer', sid: 's5', command: 'done-cmd', question: 'Changed?', picked: 'A', id: 's5:r1', by: 'recommended', changed: true, questions: [q('Changed?', ['A (Recommended)'], null)] },
      { at: 1700000600, kind: 'retry', sid: 's6', command: 'grind PR', question: '', picked: 'retry 1 of 4' },
    ];
    routes['/api/inbox'] = { items: [], gh: { ok: true }, afk: { ...AFK, summary: { started: 1700000000, ended: 1700003600, held: 1, log } } };
    window.location.hash = '#/inbox';
    render(<App />);
    expect(await screen.findByText(/: 5 handled, 1 held/)).toBeTruthy();
    expect(screen.getByText('Opus')).toBeTruthy();
    expect(document.querySelectorAll('.chip.t-ship')).toHaveLength(2); // the two Recommended rows
    expect(screen.getByText('$0.31')).toBeTruthy();
    expect(screen.getByText(/matches the state file/)).toBeTruthy();
    expect(screen.getByText('Held')).toBeTruthy();
    expect(screen.getByText(/destroys unmerged work/)).toBeTruthy();
    expect(screen.getByText('Changed')).toBeTruthy();
    const links = screen.getAllByRole('link', { name: 'answerer transcript' });
    expect(links.map((a) => a.getAttribute('href'))).toEqual(['#/sessions/ans1', '#/sessions/ans3']);
    expect(screen.getAllByRole('checkbox')).toHaveLength(2);
    expect(screen.queryByRole('checkbox', { name: /Delete branch/ })).toBeNull();
    expect(screen.queryByRole('checkbox', { name: /Changed\?/ })).toBeNull();
    const box = screen.getByRole('checkbox', { name: 'Change answer: Which store?' }) as HTMLInputElement;
    await userEvent.setup().click(box);
    expect(box.checked).toBe(true);
    expect(screen.getByText(/legacy-cmd/)).toBeTruthy();
    expect(screen.getByText(/retry 1 of 4/)).toBeTruthy();
  });

  it('away summary shows the risk line only on risk-routed rounds', async () => {
    const q = { question: 'Q?', multiSelect: false, allowFreeText: false, options: [{ label: 'A (Recommended)' }], picked: ['A (Recommended)'] };
    const e = (n: number, extra: object) => ({ at: 1700000000 + n, kind: 'answer', sid: `s${n}`, command: `cmd-${n}`, question: '', picked: 'A', id: `s${n}:r1`, changed: false, questions: [q], ...extra });
    const run = async (log: object[]) => {
      routes['/api/inbox'] = { items: [], gh: { ok: true }, afk: { ...AFK, summary: { started: 1700000000, ended: 1700003600, held: 0, log } } };
      window.location.hash = '#/inbox';
      render(<App />);
    };
    await run([e(1, { by: 'opus', risk: 0.9 }), e(2, { by: 'recommended' }), e(3, { kind: 'held', by: 'opus', risk: 0.5 }), e(4, { by: 'opus', risk: 0.873 })]);
    expect(await screen.findByText('Risk check: sent to Opus (p=0.9)')).toBeTruthy();
    expect(screen.getByText('Risk check: sent to Opus (p=0.5)')).toBeTruthy();
    expect(screen.getByText('Risk check: sent to Opus (p=0.87)')).toBeTruthy();
    expect(screen.getAllByText(/Risk check/)).toHaveLength(3);
  });

  describe('Change dialog', () => {
    const q = (question: string, picked: string[]) => ({ question, multiSelect: false, allowFreeText: false, options: [{ label: 'A (Recommended)' }, { label: 'B' }], picked });
    const row = (n: number, sid: string, command: string) => ({ at: 1700000000 + n, kind: 'answer', sid, command, question: '', picked: 'A', id: `${sid}:r1`, by: 'recommended', changed: false, questions: [q(`First ${command}?`, ['A (Recommended)']), q(`Second ${command}?`, ['A (Recommended)'])] });
    const open = async () => {
      routes['/api/inbox'] = { items: [], gh: { ok: true }, afk: { ...AFK, summary: { started: 1700000000, ended: 1700003600, held: 0, log: [row(1, 's1', 'cmd-one'), row(2, 's2', 'cmd-two')] } } };
      window.location.hash = '#/inbox';
      render(<App />);
      const user = userEvent.setup();
      expect(screen.queryByRole('button', { name: /Change \d+ selected/ })).toBeNull();
      await user.click(await screen.findByRole('checkbox', { name: 'Change answer: First cmd-one?' }));
      await user.click(screen.getByRole('button', { name: 'Change 1 selected' }));
      return { user, dlg: within(await screen.findByRole('dialog')) };
    };
    it('opens prefilled, enables Submit once a pick changes, and posts every question of the round', async () => {
      const { user, dlg } = await open();
      const submit = dlg.getByRole('button', { name: 'Submit' }) as HTMLButtonElement;
      expect((dlg.getAllByRole('radio', { name: /A/ })[0] as HTMLInputElement).checked).toBe(true);
      expect(submit.disabled).toBe(true);
      await user.click(dlg.getAllByRole('radio', { name: 'B' })[1]);
      expect(submit.disabled).toBe(false);
      changeReply.body = { results: [{ sid: 's1', ids: ['s1:r1'], state: 'queued' }] };
      await user.click(submit);
      await waitFor(() => expect(posts).toContainEqual(['/api/afk/change', { changes: [{ id: 's1:r1', answers: { '0': { labels: ['A (Recommended)'] }, '1': { labels: ['B'] } } }] }]));
      expect(await screen.findByText('cmd-one: queued')).toBeTruthy();
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    });
    it('a refused session shows its reason in the toast', async () => {
      const { user, dlg } = await open();
      await user.click(dlg.getAllByRole('radio', { name: 'B' })[0]);
      changeReply.body = { results: [{ sid: 's1', ids: ['s1:r1'], error: 'Answer its pending question first' }] };
      await user.click(dlg.getByRole('button', { name: 'Submit' }));
      expect(await screen.findByText('cmd-one: Answer its pending question first')).toBeTruthy();
      expect((screen.getByRole('checkbox', { name: 'Change answer: First cmd-one?' }) as HTMLInputElement).checked).toBe(true);
    });
    it('a 409 keeps the dialog open with the message', async () => {
      const { user, dlg } = await open();
      await user.click(dlg.getAllByRole('radio', { name: 'B' })[0]);
      changeReply = { status: 409, body: { error: 'No away summary to change' } };
      await user.click(dlg.getByRole('button', { name: 'Submit' }));
      expect((await dlg.findByRole('alert')).textContent).toContain('No away summary to change');
      expect(screen.getByRole('dialog')).toBeTruthy();
    });
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
  it('Facts shows model and effort, or the defaults', async () => {
    open(base({ model: 'claude-opus-5-5', effort: 'high' }));
    expect(await screen.findByText('claude-opus-5-5')).toBeTruthy();
    expect(screen.getByText('high')).toBeTruthy();
  });
  it('Facts falls back to — and Default without model or effort', async () => {
    open(base());
    expect(await screen.findByText('Default')).toBeTruthy();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
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

describe('Session page keys', () => {
  const open = async (s: Record<string, unknown>) => {
    routes['/api/sessions/s1'] = s;
    routes['/api/sessions/s1/stream'] = { events: [], offset: 0 };
    window.location.hash = '#/sessions/s1';
    render(<App />);
    await screen.findAllByRole('button', { name: /Continue in terminal/ });
    const user = userEvent.setup();
    await user.click(document.body);
    return user;
  };
  const posted = (path: string) => posts.some(([p]) => p === path);
  it('X stops a running session after the confirm', async () => {
    const u = await open(base({ outcome: 'running', ended_at: null }));
    await u.keyboard('x');
    await u.click(await screen.findByRole('button', { name: 'Stop session' }));
    await waitFor(() => expect(posted('/api/sessions/s1/stop')).toBe(true));
  });
  it('R reruns a done session', async () => {
    const u = await open(base());
    await u.keyboard('r');
    await waitFor(() => expect(posted('/api/sessions/s1/rerun')).toBe(true));
  });
  it('R resumes a stopped session, not a rerun', async () => {
    const u = await open(base({ outcome: 'stopped' }));
    await u.keyboard('r');
    await waitFor(() => expect(posted('/api/sessions/s1/resume')).toBe(true));
    expect(posted('/api/sessions/s1/rerun')).toBe(false);
  });
  it('R presses Retry on a failed session', async () => {
    const u = await open(base({ outcome: 'failed', error: 'it broke' }));
    await u.keyboard('r');
    await waitFor(() => expect(posted('/api/sessions/s1/resume')).toBe(true));
    expect(posted('/api/sessions/s1/rerun')).toBe(false);
  });
  it('C focuses the message box', async () => {
    const u = await open(base());
    await u.keyboard('c');
    expect(document.activeElement).toBe(screen.getByLabelText('Message to this session'));
  });
  it('C does nothing while a question is pending', async () => {
    const q = { question: 'Which DB?', multiSelect: false, allowFreeText: false, options: [{ label: 'A' }] };
    const u = await open(base({ outcome: 'waiting', waiting: true, ended_at: 'x', pending_question: { id: 'r', questions: [q] } }));
    await u.keyboard('c');
    expect(document.activeElement).toBe(document.body);
  });
  it.each([['stopped', ['R', 'T', 'C']], ['running', ['T', 'X', 'C']]])('? on a %s session lists its keys', async (outcome, keys) => {
    const u = await open(base({ outcome, ended_at: outcome === 'running' ? null : 'x' }));
    await u.keyboard('?');
    const dlg = within(await screen.findByRole('dialog'));
    for (const k of keys) expect(dlg.queryAllByText(k), k).not.toHaveLength(0);
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
  it('clamps a live card command and drops the dangling cost dash', async () => {
    const command = '/x:dump ' + 'long/path/'.repeat(30);
    routes['/api/sessions'] = { limits: {}, usage: {}, afk: AFK, sessions: [
      base({ id: 'a', outcome: 'running', ended_at: null, command, cost: null }),
      base({ id: 'b', outcome: 'running', ended_at: null, cost: 1.5 }),
    ] };
    window.location.hash = '#/activity';
    render(<App />);
    await waitFor(() => expect(document.querySelectorAll('.live-card').length).toBe(2));
    const cards = document.querySelectorAll('.live-card');
    const link = cards[0].querySelector('a.cmd');
    expect(link?.classList.contains('clamp2')).toBe(true);
    expect(link?.getAttribute('title')).toBe(link?.textContent);
    expect(cards[0].textContent).not.toContain('—');
    expect(cards[1].textContent).toContain('$1.50');
  });
});

describe('Activity keys', () => {
  const open = async () => {
    routes['/api/sessions'] = { limits: {}, usage: {}, afk: AFK, sessions: [
      base({ id: 'a', outcome: 'running', ended_at: null, started_at: '2026-01-03T00:00:00Z' }),
      base({ id: 'b', outcome: 'done', started_at: '2026-01-02T00:00:00Z' }),
      base({ id: 'c', outcome: 'failed', started_at: '2026-01-01T00:00:00Z' }),
    ] };
    window.location.hash = '#/activity';
    render(<App />);
    await screen.findByText('Live');
    const u = userEvent.setup();
    await u.click(document.body);
    return u;
  };
  it('J walks the live card then the history rows; Enter opens the selected session', async () => {
    const u = await open();
    expect(document.querySelector('[data-selected]')).toBeNull();
    await u.keyboard('j');
    expect(document.querySelector('.live-card')?.hasAttribute('data-selected')).toBe(true);
    await u.keyboard('j');
    expect(document.querySelector('tr[data-selected]')).toBeTruthy();
    await u.keyboard('{Enter}');
    await waitFor(() => expect(window.location.hash).toBe('#/sessions/b'));
  });
  it('J follows the grouped order when Group by issue is on', async () => {
    routes['/api/sessions'] = { limits: {}, usage: {}, afk: AFK, sessions: [
      base({ id: 'x1', link: { owner: 'o', repo: 'r', issue: 1 }, started_at: '2026-01-03T00:00:00Z' }),
      base({ id: 'y2', link: { owner: 'o', repo: 'r', issue: 2 }, started_at: '2026-01-02T00:00:00Z' }),
      base({ id: 'x3', link: { owner: 'o', repo: 'r', issue: 1 }, started_at: '2026-01-01T00:00:00Z' }),
    ] };
    window.location.hash = '#/activity';
    render(<App />);
    const u = userEvent.setup();
    await u.click(await screen.findByLabelText('Group by issue'));
    await u.click(document.body);
    await u.keyboard('jj{Enter}');
    await waitFor(() => expect(window.location.hash).toBe('#/sessions/x3'));
  });
  it('R retries the selected failed row', async () => {
    const u = await open();
    await u.keyboard('jjj');
    await u.keyboard('r');
    await waitFor(() => expect(posts.some(([p]) => p === '/api/sessions/c/resume')).toBe(true));
  });
  it('typing in the search box moves nothing', async () => {
    const u = await open();
    await u.type(screen.getByLabelText('Search history'), 'j');
    expect(document.querySelector('[data-selected]')).toBeNull();
  });
});

describe('Feature page keys (FR-4)', () => {
  const prd = (o: Record<string, unknown> = {}) => ({ slug: 'f', title: 'F', status: 'Draft', path: 'docs/prds/f.md', abs_path: '/x/f.md', column: 'draft', pr: null, epic: null, issues: 0, refined: 0, unrefined: [], children: [], panel: null, ...o });
  const card = (n: number, o: Record<string, unknown> = {}) => ({ n, title: `Issue ${n}`, column: 'unrefined', priority: null, blocked_by: [], pr: null, session: null, needs_cleanup: null, ...o });
  const open = async (p: Record<string, unknown>, cards: unknown[] = []) => {
    routes['/api/planning'] = { repo: 'o/r', stale: false, fetched_at: 1, prds: [p] };
    routes['/api/delivery'] = { repo: 'o/r', stale: false, fetched_at: 1, cap: 2, running: 0, auto_grind: false, lanes: p.epic ? [{ epic: p.epic, title: 'F', running: 0, cards }] : [] };
    window.location.hash = '#/features/f?repo=o/r';
    render(<App />);
    await screen.findByLabelText('Next step');
  };

  it('P on a draft opens the approve confirm, like the click on "Approve without review"', async () => {
    await open(prd());
    const u = userEvent.setup();
    expect(screen.getByRole('button', { name: /Approve without review/ }).getAttribute('aria-keyshortcuts')).toBe('P');
    await u.keyboard('p');
    expect(await screen.findByRole('button', { name: 'Approve PRD' })).toBeTruthy();
  });

  it('E on a tasks feature starts refine-issues with the unrefined issues', async () => {
    await open(prd({ status: 'Approved', column: 'approved', epic: 10, issues: 2, unrefined: [1, 2] }), [card(1), card(2)]);
    await userEvent.setup().keyboard('e');
    await waitFor(() => expect(posts.some(([p, b]) => p === '/api/start' && (b as { skill?: string; arg?: string }).skill === 'refine-issues' && (b as { arg?: string }).arg === '1 2')).toBe(true));
  });

  it('? lists P on a review-stage feature', async () => {
    await open(prd({ status: 'In review', column: 'review' }));
    await userEvent.setup().keyboard('?');
    const d = await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
    expect(within(d).getByText(/Approve PRD/)).toBeTruthy();
  });
});

describe('Features list keys', () => {
  const prd = (o: Record<string, unknown> = {}) => ({ slug: 'f', title: 'F', status: 'Approved', path: 'docs/prds/f.md', abs_path: '/x/f.md', column: 'approved', pr: null, epic: 10, issues: 2, refined: 2, unrefined: [], children: [], panel: null, ...o });
  const card = (n: number, o: Record<string, unknown> = {}) => ({ n, title: `Issue ${n}`, column: 'unrefined', priority: null, blocked_by: [], pr: null, session: null, needs_cleanup: null, ...o });
  const load = (hash: string, cards: unknown[] = [card(1), card(2)]) => {
    routes['/api/planning'] = { repo: 'o/r', stale: false, fetched_at: 1, prds: [prd()] };
    routes['/api/delivery'] = { repo: 'o/r', stale: false, fetched_at: 1, cap: 2, running: 0, auto_grind: false, lanes: [{ epic: 10, title: 'F', running: 0, cards }] };
    window.location.hash = hash;
    render(<App />);
  };

  it('J then Enter on a feature row lands on its page', async () => {
    load('#/features?only=o/r');
    await screen.findByText('epic #10');
    await userEvent.setup().keyboard('j{Enter}');
    await waitFor(() => expect(window.location.hash).toContain('#/features/f'));
  });

  it('on the Issues tab J, Enter opens the issue panel and J switches it', async () => {
    load('#/features/f/issues?repo=o/r');
    await screen.findAllByText('Issue 1');
    const u = userEvent.setup();
    await u.keyboard('j{Enter}');
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/issues/o/r/1'), expect.anything()));
    await u.keyboard('j');
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/issues/o/r/2'), expect.anything()));
  });
});
