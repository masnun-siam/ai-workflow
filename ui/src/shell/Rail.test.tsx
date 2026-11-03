import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';

const json = (b: unknown) => Promise.resolve(new Response(JSON.stringify(b), { status: 200, headers: { 'Content-Type': 'application/json' } }));
const AFK = { active: false, until: null, started: null, decisions: 0, held: 0, summary: null };
const CLAUDE = { five_hour: { pct: 34, resets_at: null }, seven_day: { pct: 12, resets_at: null }, error: null };
const CODEX = { error: 'not available for Codex', at: null };
const stub = (usage: unknown, limits: unknown = {}) => vi.stubGlobal('fetch', vi.fn((url: string) => {
  const routes: Record<string, unknown> = {
    '/api/repos': { repos: [{ slug: 'o/r', name: 'R', path: '/x' }], can_browse: false, scan_roots: [] },
    '/api/sessions': { sessions: [], limits, usage, afk: AFK },
    '/api/inbox': { items: [], afk: AFK, gh: { ok: true } },
    '/api/settings': { commands: [{ label: 'claude', cmd: 'claude', builtin: true, harness: 'claude' }, { label: 'Codex', cmd: 'codex', harness: 'codex' }], default: 'claude' },
    '/api/shares': [],
  };
  const path = String(url).split('?')[0];
  return path in routes ? json(routes[path]) : Promise.resolve(new Response('{}', { status: 404 }));
}));
const open = () => { window.location.hash = '#/inbox?repo=o/r'; render(<App />); };

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('Usage in the Rail and StatusMenu', () => {
  it('shows numbers for Claude and "usage unavailable" with no meter for Codex', async () => {
    stub({ claude: CLAUDE, codex: CODEX });
    open();
    const na = await screen.findByText('usage unavailable');
    expect(na.title).toBe('not available for Codex');
    expect(screen.getAllByText('5h 34% · 7d 12%')).toHaveLength(1);
    expect(screen.getByRole('img', { name: 'claude 5-hour usage 34%' })).toBeTruthy();
    expect(screen.queryByRole('img', { name: /^Codex 5-hour usage/ })).toBeNull();
  });
  it('shows the same two lines in the StatusMenu popover', async () => {
    stub({ claude: CLAUDE, codex: CODEX });
    open();
    await screen.findByText('usage unavailable');
    const btn = screen.getByRole('button', { name: 'Away mode and usage' });
    fireEvent.pointerDown(btn, { button: 0, ctrlKey: false });
    fireEvent.click(btn);
    await waitFor(() => expect(screen.getAllByText('usage unavailable')).toHaveLength(2));
    expect(screen.getAllByText('5h 34% · 7d 12%')).toHaveLength(2);
    expect(screen.getAllByRole('img', { name: 'claude 5-hour usage 34%' })).toHaveLength(2);
    expect(screen.queryByRole('img', { name: /^Codex 5-hour usage/ })).toBeNull();
  });
  it('keeps the meter of a stale entry with numbers and an error', async () => {
    stub({ claude: { ...CLAUDE, error: 're-login needed' } });
    open();
    const na = await screen.findByText('usage unavailable');
    expect(na.title).toBe('re-login needed');
    expect(screen.getByRole('img', { name: 'claude 5-hour usage 34%' })).toBeTruthy();
  });
  it('shows "limited until" with a full meter for a limited account', async () => {
    stub({ codex: CODEX }, { codex: { limited_until: Math.floor(Date.now() / 1000) + 3600 } });
    open();
    expect(await screen.findByText(/limited until/)).toBeTruthy();
    expect(screen.getByRole('img', { name: 'Codex 5-hour usage 100%' })).toBeTruthy();
  });
});
