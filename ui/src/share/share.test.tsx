import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import { SharePage } from './SharePage';

const renderDiagrams = vi.hoisted(() => vi.fn());
vi.mock('../lib/prdRender', async (orig) => ({ ...(await orig<object>()), renderDiagrams }));

const prd = (o = {}) => ({ title: 'My PRD', status: 'Draft', text: '# My PRD\n\n## Goal\n\nHello world', updated_at: '2026-01-02T03:04:05Z', ...o });
const ok = (b: unknown) => Promise.resolve(new Response(JSON.stringify(b), { status: 200 }));
const status = (n: number) => Promise.resolve(new Response('{}', { status: n }));
const flush = () => act(async () => { await vi.advanceTimersByTimeAsync(0); });
const poll = () => act(async () => { await vi.advanceTimersByTimeAsync(30_000); });

let fetchMock: ReturnType<typeof vi.fn>;
let apprMock: Mock<(u: string, i?: RequestInit) => Promise<Response>>;
beforeEach(() => {
  vi.useFakeTimers();
  window.history.pushState({}, '', '/s/tok/');
  const prdMock = vi.fn();
  fetchMock = prdMock;
  // The PRD mock sees only PRD calls; thread calls get an empty list.
  apprMock = vi.fn(() => ok([]));
  localStorage.clear();
  vi.stubGlobal('fetch', (u: string, init?: RequestInit) => (String(u).endsWith('/api/threads') ? ok([]) : String(u).endsWith('/api/approvals') ? apprMock(u, init) : prdMock(u, init)));
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

  describe('approvals', () => {
    const KEY = 'aiw-share-approval:tok';
    const mount = async (list: unknown[] = [], p = {}) => {
      fetchMock.mockImplementation(() => ok(prd(p)));
      apprMock.mockImplementation((_u: string, init?: RequestInit) => (init?.method ? status(500) : ok(list)));
      render(<SharePage />);
      await flush();
    };
    const type = (name: string) => fireEvent.change(screen.getByLabelText('Your name to approve'), { target: { value: name } });
    const click = async (label: string) => { fireEvent.click(screen.getByRole('button', { name: label })); await flush(); };

    it('asks for a name, posts it and stores the key', async () => {
      await mount();
      const btn = screen.getByRole('button', { name: 'Approve' }) as HTMLButtonElement;
      expect(btn.disabled).toBe(true);
      type('  Ann ');
      apprMock.mockImplementation((_u: string, init?: RequestInit) => (init?.method ? ok({ name: 'Ann', at: '2026-01-03T00:00:00Z', key: 'k1' }) : ok([])));
      await click('Approve');
      const post = apprMock.mock.calls.find(([, i]) => i?.method === 'POST')!;
      expect(JSON.parse(String(post[1]?.body))).toEqual({ name: 'Ann' });
      expect(JSON.parse(localStorage.getItem(KEY)!)).toEqual({ name: 'Ann', key: 'k1' });
      expect(localStorage.getItem('aiw-share-name')).toBe('Ann');
      expect(screen.getByRole('button', { name: 'You approved · Withdraw' })).toBeTruthy();
      expect(screen.getByText('1 approval')).toBeTruthy();
    });

    it('state table: key held, name only, neither, stale key', async () => {
      localStorage.setItem(KEY, JSON.stringify({ name: 'Ann', key: 'k' }));
      await mount([{ name: 'ann', at: '2026-02-01T00:00:00Z' }]);
      expect(screen.getByRole('button', { name: 'You approved · Withdraw' })).toBeTruthy();
      cleanup(); localStorage.clear(); localStorage.setItem('aiw-share-name', 'Ann');
      await mount([{ name: 'Ann', at: '2026-02-01T00:00:00Z' }]);
      expect(screen.getByText('Approved as Ann')).toBeTruthy();
      expect(screen.queryByRole('button', { name: /Withdraw/ })).toBeNull();
      cleanup(); localStorage.clear();
      await mount([{ name: 'Bob', at: '2026-02-01T00:00:00Z' }]);
      expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy();
      cleanup(); localStorage.setItem(KEY, JSON.stringify({ name: 'Ann', key: 'k' }));
      await mount([{ name: 'Bob', at: '2026-02-01T00:00:00Z' }]);
      expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy();
      expect(localStorage.getItem(KEY)).toBeNull();
    });

    it('withdraw sends name and key; 204 clears both', async () => {
      localStorage.setItem(KEY, JSON.stringify({ name: 'Ann', key: 'k' }));
      await mount([{ name: 'Ann', at: '2026-02-01T00:00:00Z' }]);
      apprMock.mockImplementation((_u: string, init?: RequestInit) => (init?.method ? Promise.resolve(new Response(null, { status: 204 })) : ok([])));
      await click('You approved · Withdraw');
      const del = apprMock.mock.calls.find(([, i]) => i?.method === 'DELETE')!;
      expect(JSON.parse(String(del[1]?.body))).toEqual({ name: 'Ann', key: 'k' });
      expect(localStorage.getItem(KEY)).toBeNull();
      expect(screen.queryByText(/approval/)).toBeNull();
      expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy();
    });

    it('withdraw 404 shows the message, drops the key and reloads', async () => {
      localStorage.setItem(KEY, JSON.stringify({ name: 'Ann', key: 'k' }));
      await mount([{ name: 'Ann', at: '2026-02-01T00:00:00Z' }]);
      apprMock.mockImplementation((_u: string, init?: RequestInit) => (init?.method ? status(404) : ok([])));
      await click('You approved · Withdraw');
      expect(screen.getByText('That approval is no longer there')).toBeTruthy();
      expect(localStorage.getItem(KEY)).toBeNull();
      expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy();
    });

    it('200 without a key stores nothing and reads Approved as', async () => {
      await mount();
      type('Ann');
      apprMock.mockImplementation((_u: string, init?: RequestInit) => (init?.method ? ok({ name: 'Ann', at: '2026-02-01T00:00:00Z' }) : ok([])));
      await click('Approve');
      expect(localStorage.getItem(KEY)).toBeNull();
      expect(screen.getByText('Approved as Ann')).toBeTruthy();
    });

    it('is disabled while pending', async () => {
      await mount();
      type('Ann');
      let done!: (r: Response) => void;
      apprMock.mockImplementation((_u: string, init?: RequestInit) => (init?.method ? new Promise((r) => { done = r; }) : ok([])));
      await click('Approve');
      expect((screen.getByRole('button', { name: 'Approve' }) as HTMLButtonElement).disabled).toBe(true);
      done(new Response(JSON.stringify({ name: 'Ann', at: '2026-02-01T00:00:00Z', key: 'k' }), { status: 201 }));
      await flush();
    });

    it('shows count, plural and "before last edit" only for older approvals', async () => {
      await mount([{ name: 'Old', at: '2026-01-01T00:00:00Z' }, { name: 'New', at: '2026-01-03T00:00:00Z' }]);
      expect(screen.getByText('2 approvals')).toBeTruthy();
      expect(screen.getAllByText(/before last edit/)).toHaveLength(1);
      expect(screen.getByText('Old').closest('li')?.textContent).toContain('before last edit');
    });

    it.each([[400, 'That name is not valid'], [409, 'This share has reached its limit of 100 approvals'], [413, 'That is too large to send'], [429, 'Too many requests, try again in a minute']])('shows an inline message for %i', async (code, msg) => {
      await mount();
      type('Ann');
      apprMock.mockImplementation((_u: string, init?: RequestInit) => (init?.method ? status(code) : ok([])));
      await click('Approve');
      expect(screen.getByRole('alert').textContent).toBe(msg);
    });

    it('shows an inline message on a network failure', async () => {
      await mount();
      type('Ann');
      apprMock.mockImplementation((_u: string, init?: RequestInit) => (init?.method ? Promise.reject(new TypeError('x')) : ok([])));
      await click('Approve');
      expect(screen.getByRole('alert').textContent).toBe('Could not reach the server, try again');
    });

    it('sends only approvals, prd and threads requests; none changes status', async () => {
      await mount();
      type('Ann');
      await click('Approve');
      const urls = [...fetchMock.mock.calls, ...apprMock.mock.calls].map(([u]) => String(u));
      expect(urls.every((u) => /^\/s\/tok\/api\/(prd|threads|approvals)$/.test(u))).toBe(true);
    });

    it('is not shown in the no-longer-active view', async () => {
      fetchMock.mockImplementation(() => status(404));
      render(<SharePage />);
      await flush();
      expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    });
  });
});
