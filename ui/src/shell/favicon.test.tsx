import { cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';

const json = (b: unknown) => Promise.resolve(new Response(JSON.stringify(b), { status: 200, headers: { 'Content-Type': 'application/json' } }));
const AFK = { active: false, until: null, started: null, decisions: 0, held: 0, summary: null };
const stub = (items: unknown[]) => vi.stubGlobal('fetch', vi.fn((url: string) => {
  const routes: Record<string, unknown> = {
    '/api/repos': { repos: [{ slug: 'o/r', name: 'R', path: '/x' }], can_browse: false, scan_roots: [] },
    '/api/sessions': { sessions: [], limits: {}, usage: {}, afk: AFK },
    '/api/inbox': { items, afk: AFK, gh: { ok: true } },
    '/api/settings': { commands: [{ label: 'work', cmd: 'c1' }], default: 'work' },
    '/api/shares': [],
  };
  const path = String(url).split('?')[0];
  return path in routes ? json(routes[path]) : Promise.resolve(new Response('{}', { status: 404 }));
}));
const addIcon = () => {
  const l = document.createElement('link');
  l.rel = 'icon';
  l.href = '/icons/icon.svg';
  document.head.appendChild(l);
  return l;
};

afterEach(() => { cleanup(); vi.unstubAllGlobals(); document.head.querySelectorAll('link[rel=icon]').forEach((l) => l.remove()); });

describe('favicon', () => {
  it('shows the alert icon while the Inbox needs you', async () => {
    stub([{ id: 'a', group: 'now', kind: 'pr', title: 't', repo: 'o/r' }]);
    const link = addIcon();
    window.location.hash = '#/inbox?repo=o/r';
    render(<App />);
    await waitFor(() => expect(link.href).toMatch(/icons\/icon-alert\.svg$/));
    expect(document.title).toBe('(1) aiw');
  });
  it('shows the normal icon at zero', async () => {
    stub([]);
    const link = addIcon();
    window.location.hash = '#/inbox?repo=o/r';
    render(<App />);
    await waitFor(() => expect(document.title).toBe('aiw'));
    expect(link.href).toMatch(/icons\/icon\.svg$/);
  });
  it('does not throw without a link[rel=icon]', async () => {
    stub([]);
    window.location.hash = '#/inbox?repo=o/r';
    render(<App />);
    await waitFor(() => expect(document.title).toBe('aiw'));
  });
});
