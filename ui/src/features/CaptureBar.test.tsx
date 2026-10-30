import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { QueryProvider } from '../QueryProvider';
import { CaptureBar } from './CaptureBar';

type Call = { method: string; url: string; body: Record<string, unknown> | null };
let calls: Call[];
const json = (b: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } }));

beforeEach(() => {
  calls = [];
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET';
    calls.push({ method, url: String(url), body: init?.body ? JSON.parse(String(init.body)) : null });
    if (url === '/api/repos') return json({ repos: [{ slug: 'o/r', name: 'R', path: '/x' }, { slug: 'o/q', name: 'Q', path: '/y' }], can_browse: false, scan_roots: [] });
    if (method === 'POST') return json({ id: 's1' }, 201);
    return json({});
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const Where = () => { const l = useLocation(); return <div data-testid="loc">{l.pathname + l.search}</div>; };
const open = (pickRepo: boolean) => render(
  <QueryProvider><MemoryRouter><CaptureBar repo="o/r" pickRepo={pickRepo} /><Where /></MemoryRouter></QueryProvider>,
);
const post = (url: string) => calls.find((c) => c.method === 'POST' && c.url === url)?.body;

async function pickQ() {
  await userEvent.click(await screen.findByRole('button', { name: 'Capture repo: r' }));
  await userEvent.click(await screen.findByText('q'));
}
const type = (t: string) => fireEvent.change(screen.getByLabelText('Describe a feature or a fix'), { target: { value: t } });
const route = (name: string) => userEvent.click(screen.getByRole('radio', { name }));

it('Feature files into the picked repo', async () => {
  open(true);
  await pickQ();
  await route('Feature'); type('x');
  await userEvent.click(screen.getByRole('button', { name: 'Create' }));
  await waitFor(() => expect(post('/api/sessions')?.repo).toBe('o/q'));
});

it('Small change files into the picked repo', async () => {
  open(true);
  await pickQ();
  await route('Small change'); type('x');
  await userEvent.click(screen.getByRole('button', { name: 'File issue' }));
  await waitFor(() => expect(post('/api/start')?.repo).toBe('o/q'));
});

it('Auto opens the New page on the picked repo', async () => {
  open(true);
  await pickQ();
  type('x');
  await userEvent.click(screen.getByRole('button', { name: 'Create' }));
  await waitFor(() => expect(screen.getByTestId('loc').textContent).toMatch(/^\/new\?.*&repo=o\/q$/));
});

it('defaults to the repo prop and has no picker without pickRepo', async () => {
  open(false);
  await waitFor(() => expect(calls.some((c) => c.url === '/api/repos')).toBe(true));
  expect(screen.queryByRole('button', { name: /^Capture repo/ })).toBeNull();
  await route('Feature'); type('x');
  await userEvent.click(screen.getByRole('button', { name: 'Create' }));
  await waitFor(() => expect(post('/api/sessions')?.repo).toBe('o/r'));
});
