import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';

const json = (b: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } }));
const URL_ = 'https://x.ts.net/s/tok';
const calls: { method: string; path: string; body: any }[] = [];
const summary = (o: Record<string, unknown> = {}) => ({ id: 's1', repo: 'o/r', path: 'docs/prds/f1.md', title: 'F', state: 'live', url: URL_, comments: 3, unread: 0, reachable: true, end_reason: null, ...o });
const detail = (approvals: { id: string; name: string; at: string }[], o: Record<string, unknown> = {}) => ({ ...summary(o), created_at: '', ended_at: null, last_seen_at: null, prd_updated_at: null, unsent: 0, threads: [], approvals });
const ap = (k: number) => ({ id: `a${k}`, name: `Rev${k}`, at: '' });

function mock(o: { status?: string; shares?: unknown[]; detail?: unknown; post?: () => Promise<Response> } = {}) {
  calls.length = 0;
  const routes: Record<string, unknown> = {
    '/api/repos': { repos: [{ slug: 'o/r', name: 'R', path: '/x' }], can_browse: false, scan_roots: [] },
    '/api/sessions': { sessions: [], limits: {}, usage: {}, afk: { active: false, until: null, started: null, decisions: 0, held: 0, summary: null }, gh: { ok: true } },
    '/api/inbox': { items: [], afk: {}, gh: { ok: true } },
    '/api/planning': { repo: 'o/r', stale: false, fetched_at: 1, prds: [{ slug: 'f1', title: 'Feature one', status: o.status ?? 'In review', path: 'docs/prds/f1.md', abs_path: '/x/docs/prds/f1.md', column: 'review', pr: null, epic: null, issues: 0, refined: 0, unrefined: [], children: [], panel: null }] },
    '/api/delivery': { repo: 'o/r', stale: false, fetched_at: 1, cap: 2, running: 0, auto_grind: false, lanes: [] },
    '/api/prd': { text: '# F\n\n## A\nbody', sha: 'x', branch: 'main' },
  };
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const [path] = String(url).split('?');
    const method = init?.method ?? 'GET';
    if (method !== 'GET') calls.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (path === '/api/shares' && method === 'POST') return o.post ? o.post() : json(summary(), 201);
    if (path === '/api/shares') return json(o.shares ?? []);
    if (path === '/api/shares/s1') return method === 'GET' ? json(o.detail ?? detail([])) : json(summary({ state: 'ended', url: null }));
    if (method !== 'GET') return json({});
    return path in routes ? json(routes[path]) : json({ items: [] });
  }));
}
const posts = () => calls.filter((c) => c.method === 'POST');
async function open(o: Parameters<typeof mock>[0] = {}) {
  mock(o);
  window.location.hash = '#/features/f1/prd?repo=o/r';
  render(<App />);
  return screen.findByRole('button', { name: /^Share|Sharing/ });
}
beforeEach(() => localStorage.clear());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('Share button', () => {
  for (const status of ['Approved', 'Done']) {
    it(`is disabled with the reason for ${status}`, async () => {
      const b = await open({ status });
      expect((b as HTMLButtonElement).disabled).toBe(true);
      expect(b.getAttribute('title')).toBe('Only Draft or In review PRDs can be shared');
      expect(posts()).toHaveLength(0);
    });
  }

  it('warns, sends nothing on Cancel, creates on Confirm, then shows the link', async () => {
    const u = userEvent.setup();
    const b = await open({ shares: [] });
    await u.click(b);
    const dlg = await screen.findByRole('alertdialog');
    expect(dlg.textContent).toContain('The PRD text is public as written, including its header and any paths');
    await u.click(within(dlg).getByRole('button', { name: 'Cancel' }));
    expect(posts()).toHaveLength(0);
    await u.click(b);
    await u.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Share' }));
    await waitFor(() => expect(posts()).toEqual([{ method: 'POST', path: '/api/shares', body: { repo: 'o/r', path: 'docs/prds/f1.md', confirm: true } }]));
  });

  it('shows the live share: link, comments, end rule, reachability, Copy', async () => {
    const u = userEvent.setup();
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    const b = await open({ shares: [summary({ reachable: false })], detail: detail([ap(1)], { reachable: false }) });
    await u.click(b);
    expect(((await screen.findByLabelText('Share link')) as HTMLInputElement).value).toBe(URL_);
    expect(screen.getByText('3 comments')).toBeTruthy();
    expect(await screen.findByText('1 approval')).toBeTruthy();
    expect(screen.getByText('Ends when the PRD leaves Draft or In review')).toBeTruthy();
    expect(screen.getByText(/Not reachable right now/)).toBeTruthy();
    await u.click(screen.getByRole('button', { name: 'Copy' }));
    expect(writeText).toHaveBeenCalledWith(URL_);
    expect(posts()).toHaveLength(0);
  });

  it('shows Sharing… and sends one POST for a double click', async () => {
    const u = userEvent.setup();
    let release: (r: Response) => void = () => {};
    const b = await open({ post: () => new Promise<Response>((r) => { release = r; }) });
    await u.click(b);
    await u.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Share' }));
    const pending = await screen.findByRole('button', { name: 'Sharing…' });
    expect((pending as HTMLButtonElement).disabled).toBe(true);
    await u.dblClick(pending);
    expect(posts()).toHaveLength(1);
    release(new Response(JSON.stringify(summary()), { status: 201, headers: { 'Content-Type': 'application/json' } }));
  });

  for (const [status, msg] of [[503, 'Tailscale is not running: stopped'], [409, 'PRD is not Draft or In review']] as const) {
    it(`shows a ${status} refusal inline, with no link`, async () => {
      const u = userEvent.setup();
      const b = await open({ post: () => json({ error: msg }, status) });
      await u.click(b);
      await u.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Share' }));
      expect((await screen.findByText(msg)).getAttribute('role')).toBe('alert');
      expect(screen.queryByLabelText('Share link')).toBeNull();
    });
  }
});

describe('Stop, Remove and re-share', () => {
  for (const [n, text] of [
    [0, 'Reviewers lose access. Sharing again makes a new link.'],
    [1, 'Reviewers lose access. Sharing again makes a new link and clears the 1 approval.'],
    [2, 'Reviewers lose access. Sharing again makes a new link and clears the 2 approvals.'],
  ] as const) {
    it(`Stop asks the exact text for ${n} approvals, then deletes`, async () => {
      const u = userEvent.setup();
      const b = await open({ shares: [summary()], detail: detail([1, 2].slice(0, n).map(ap)) });
      await u.click(b);
      if (n) await screen.findByText(n === 1 ? '1 approval' : '2 approvals');
      await u.click(await screen.findByRole('button', { name: 'Stop' }));
      const dlg = await screen.findByRole('alertdialog');
      expect(dlg.textContent).toContain(text);
      await u.click(within(dlg).getByRole('button', { name: 'Stop' }));
      await waitFor(() => expect(calls.filter((c) => c.method === 'DELETE').map((c) => c.path)).toEqual(['/api/shares/s1']));
    });
  }

  for (const [n, clause] of [[2, 'Sharing again clears the 2 approvals.'], [1, 'Sharing again clears the 1 approval.'], [0, '']] as const) {
    it(`Share on an ended record with ${n} approvals`, async () => {
      const u = userEvent.setup();
      const ended = { state: 'ended', url: null, end_reason: 'stopped' };
      const b = await open({ shares: [summary(ended)], detail: detail([1, 2].slice(0, n).map(ap), ended) });
      await waitFor(() => expect(vi.mocked(fetch).mock.calls.some((c) => String(c[0]).startsWith('/api/shares/s1'))).toBe(true));
      await new Promise((r) => setTimeout(r, 50));
      await u.click(b);
      const dlg = await screen.findByRole('alertdialog');
      expect(dlg.textContent).toContain('any paths.');
      if (clause) expect(dlg.textContent).toContain(clause);
      else expect(dlg.textContent).not.toContain('clears');
      expect(posts()).toHaveLength(0);
    });
  }

  it('Remove asks with the name, then deletes the approval', async () => {
    const u = userEvent.setup();
    const b = await open({ shares: [summary()], detail: detail([ap(1)]) });
    await u.click(b);
    await u.click(await screen.findByRole('button', { name: "Remove Rev1's approval" }));
    const dlg = await screen.findByRole('alertdialog');
    expect(dlg.textContent).toContain("Remove Rev1's approval? This cannot be undone.");
    await u.click(within(dlg).getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(calls.filter((c) => c.method === 'DELETE').map((c) => c.path)).toEqual(['/api/shares/s1/approvals/a1']));
  });
});
