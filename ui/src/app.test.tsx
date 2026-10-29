import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';

const json = (b: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } }));

function mockApi(over: Record<string, unknown> = {}) {
  const routes: Record<string, unknown> = {
    '/api/repos': { repos: [{ slug: 'o/r', name: 'R', path: '/x' }], can_browse: false, scan_roots: [] },
    '/api/sessions': { sessions: [], limits: {}, usage: {}, afk: { active: false, until: null, started: null, decisions: 0, held: 0, summary: null } },
    '/api/inbox': { items: [{ key: 'a', group: 'fix', type: 'repo_unpublished', repo: null, at: null, slug: 'local/x', path: '/p' }, { key: 'w', group: 'wait', type: 'queued', repo: null, at: null, session_id: 's', reason: 'x' }], afk: {}, gh: { ok: true } },
    '/api/planning': { repo: 'o/r', stale: false, fetched_at: 1, prds: [] },
    '/api/delivery': { repo: 'o/r', stale: false, fetched_at: 1, cap: 2, running: 0, auto_grind: false, lanes: [] },
    '/api/settings': { commands: [], default: '' },
    ...over,
  };
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    const path = String(url).split('?')[0];
    return path in routes ? json(routes[path]) : json({ items: [] });
  }));
}

beforeEach(() => {
  localStorage.clear();
  mockApi();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('app shell', () => {
  it('opens the Inbox at the root, 404s an old route, and counts non-waiting inbox items in the title', async () => {
    window.location.hash = '#/planning?repo=o/r';
    render(<App />);
    expect(await screen.findByText(/not found/i)).toBeTruthy(); // old routes are gone
    window.location.hash = '#/?repo=o/r';
    expect(await screen.findByRole('heading', { level: 1, name: 'Inbox' })).toBeTruthy();
    await waitFor(() => expect(document.title).toBe('(1) aiw'));
  });

  it('palette: typing 801 and Enter opens the issue panel', async () => {
    window.location.hash = '#/inbox?repo=o/r';
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', { level: 1, name: 'Inbox' });
    await user.keyboard('{Control>}k{/Control}');
    await user.type(await screen.findByRole('combobox'), '801');
    await user.keyboard('{Enter}');
    expect(await screen.findByLabelText('Issue details')).toBeTruthy();
    expect(screen.getByText(/#801/)).toBeTruthy();
  });

  it('N opens Start', async () => {
    window.location.hash = '#/inbox?repo=o/r';
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', { level: 1, name: 'Inbox' });
    await user.keyboard('n');
    expect(await screen.findByRole('dialog', { name: 'What should we start?' })).toBeTruthy();
  });

  it('shows the offline banner when /api/sessions fails', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => (String(url).startsWith('/api/sessions') ? Promise.reject(new TypeError('x')) : json({ repos: [{ slug: 'o/r', name: 'R', path: '/' }], items: [] }))));
    window.location.hash = '#/inbox';
    render(<App />);
    expect(await screen.findByText(/Can't reach the aiw server/)).toBeTruthy();
  });
});
