import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';

const json = (b: unknown) => Promise.resolve(new Response(JSON.stringify(b), { status: 200, headers: { 'Content-Type': 'application/json' } }));
const AFK = { active: false, until: null, started: null, decisions: 0, held: 0, summary: null };
const share = (o: Record<string, unknown> = {}) => ({ id: 'a', repo: 'o/r', path: 'docs/prds/my-feat.md', title: 'My feat', state: 'live', url: 'https://x', comments: 0, unread: 0, reachable: true, end_reason: null, ...o });

let shares: unknown[];
let calls: string[];
beforeEach(() => {
  localStorage.clear();
  calls = [];
  shares = [];
  const routes: Record<string, unknown> = {
    '/api/repos': { repos: [{ slug: 'o/r', name: 'R', path: '/x' }], can_browse: false, scan_roots: [] },
    '/api/sessions': { sessions: [], limits: {}, usage: {}, afk: AFK },
    '/api/inbox': { items: [], afk: AFK, gh: { ok: true } },
    '/api/settings': { commands: [{ label: 'work', cmd: 'c1' }], default: 'work' },
  };
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    const path = String(url).split('?')[0];
    calls.push(path);
    return path === '/api/shares' ? json(shares) : path in routes ? json(routes[path]) : Promise.resolve(new Response('{}', { status: 404 }));
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const badge = () => screen.queryByRole('button', { name: /Public shares/ });

describe('PublicBadge', () => {
  it('shows the live count on every page, none for no or ended shares', async () => {
    shares = [share({ id: 'e', state: 'ended' })];
    window.location.hash = '#/inbox?repo=o/r';
    render(<App />);
    await waitFor(() => expect(calls).toContain('/api/shares'));
    expect(badge()).toBeNull();
    cleanup();
    shares = [share()];
    for (const h of ['#/inbox', '#/features', '#/settings']) {
      window.location.hash = h;
      render(<App />);
      expect((await screen.findByRole('button', { name: 'Public shares: 1' })).textContent).toContain('(1)');
      cleanup();
    }
  });

  it('counts a not-reachable share and lists title, repo and links; Esc returns focus', async () => {
    shares = [share(), share({ id: 'b', repo: 'o/other', path: 'docs/prds/second.md', title: 'Second', reachable: false })];
    window.location.hash = '#/inbox?repo=o/r';
    render(<App />);
    const btn = await screen.findByRole('button', { name: 'Public shares: 2' });
    await userEvent.click(btn);
    expect(screen.getByText('My feat')).toBeTruthy();
    expect(screen.getByText('other')).toBeTruthy();
    expect(screen.getAllByText('not reachable')).toHaveLength(1);
    expect(screen.getByRole('link', { name: /Second/ }).getAttribute('href')).toBe('#/features/second/prd?repo=o/other');
    expect(screen.getByRole('link', { name: /My feat/ }).getAttribute('href')).toBe('#/features/my-feat/prd?repo=o/r');
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByText('My feat')).toBeNull());
    expect(document.activeElement).toBe(btn);
  });

  it('drops the badge once the share has ended', async () => {
    shares = [share()];
    window.location.hash = '#/inbox?repo=o/r';
    render(<App />);
    await screen.findByRole('button', { name: 'Public shares: 1' });
    shares = [share({ state: 'ended' })];
    await waitFor(() => expect(badge()).toBeNull(), { timeout: 15000 });
  }, 20000);
});
