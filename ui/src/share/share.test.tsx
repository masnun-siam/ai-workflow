import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SharePage } from './SharePage';

const renderDiagrams = vi.hoisted(() => vi.fn());
vi.mock('../lib/prdRender', async (orig) => ({ ...(await orig<object>()), renderDiagrams }));

const prd = (o = {}) => ({ title: 'My PRD', status: 'Draft', text: '# My PRD\n\n## Goal\n\nHello world', updated_at: '2026-01-02T03:04:05Z', ...o });
const ok = (b: unknown) => Promise.resolve(new Response(JSON.stringify(b), { status: 200 }));
const status = (n: number) => Promise.resolve(new Response('{}', { status: n }));
const flush = () => act(async () => { await vi.advanceTimersByTimeAsync(0); });
const poll = () => act(async () => { await vi.advanceTimersByTimeAsync(30_000); });

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  vi.useFakeTimers();
  window.history.pushState({}, '', '/s/tok/');
  const prdMock = vi.fn();
  fetchMock = prdMock;
  // The PRD mock sees only PRD calls; thread calls get an empty list.
  vi.stubGlobal('fetch', (u: string, init?: RequestInit) => (String(u).endsWith('/api/threads') ? ok([]) : prdMock(u, init)));
  renderDiagrams.mockClear();
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('SharePage', () => {
  it('shows loading, then title, status, updated line and rendered text', async () => {
    fetchMock.mockImplementation(() => ok(prd()));
    render(<SharePage />);
    expect(screen.getByText('Loading the PRD…')).toBeTruthy();
    await flush();
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('My PRD');
    expect(screen.getByText('Draft')).toBeTruthy();
    expect(document.body.textContent).toContain('Last updated');
    expect(document.querySelector('.prose h2')?.textContent).toBe('Goal');
    expect(fetchMock.mock.calls.every(([u]) => String(u).startsWith('/s/tok/api/'))).toBe(true);
  });

  it('a poll with changed text shows it; unchanged text keeps the same DOM node', async () => {
    fetchMock.mockReturnValueOnce(ok(prd())).mockReturnValueOnce(ok(prd())).mockReturnValueOnce(ok(prd({ text: 'New body' })));
    render(<SharePage />);
    await flush();
    const node = document.querySelector('.prose');
    const calls = renderDiagrams.mock.calls.length;
    await poll();
    expect(document.querySelector('.prose')).toBe(node);
    expect(renderDiagrams.mock.calls.length).toBe(calls);
    await poll();
    expect(document.querySelector('.prose')?.textContent).toContain('New body');
  });

  it('404 on first load shows the inactive message', async () => {
    fetchMock.mockImplementation(() => status(404));
    render(<SharePage />);
    await flush();
    expect(screen.getByText('This link is no longer active')).toBeTruthy();
  });

  it('404 on a later poll switches to the inactive message and stops polling', async () => {
    fetchMock.mockReturnValueOnce(ok(prd())).mockImplementation(() => status(404));
    render(<SharePage />);
    await flush();
    await poll();
    expect(screen.getByText('This link is no longer active')).toBeTruthy();
    await poll();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('a network failure or 5xx keeps the text, shows the retry line, and clears on success', async () => {
    fetchMock.mockReturnValueOnce(ok(prd())).mockImplementationOnce(() => Promise.reject(new TypeError('x'))).mockReturnValueOnce(status(500)).mockImplementation(() => ok(prd()));
    render(<SharePage />);
    await flush();
    await poll();
    expect(screen.getByText("Can't reach the PRD right now, retrying")).toBeTruthy();
    expect(document.querySelector('.prose')?.textContent).toContain('Hello world');
    await poll();
    expect(screen.getByText("Can't reach the PRD right now, retrying")).toBeTruthy();
    await poll();
    expect(screen.queryByText("Can't reach the PRD right now, retrying")).toBeNull();
  });

  it('a failed first load shows the retry line and no text', async () => {
    fetchMock.mockImplementation(() => status(502));
    render(<SharePage />);
    await flush();
    expect(screen.getByText("Can't reach the PRD right now, retrying")).toBeTruthy();
    expect(document.querySelector('.prose')).toBeNull();
  });

  it('shows no repo, path or branch fields from extra payload keys', async () => {
    fetchMock.mockReturnValue(ok({ ...prd(), repo: 'secret/repo', path: '/Users/x/prd.md', branch: 'feat-secret' }));
    render(<SharePage />);
    await flush();
    for (const s of ['secret/repo', '/Users/x/prd.md', 'feat-secret']) expect(document.body.textContent).not.toContain(s);
  });

  it('shows nothing for an invalid updated_at', async () => {
    fetchMock.mockReturnValue(ok(prd({ updated_at: 'nope' })));
    render(<SharePage />);
    await flush();
    expect(document.body.textContent).not.toContain('Invalid Date');
    expect(document.body.textContent).not.toContain('Last updated');
  });
});
