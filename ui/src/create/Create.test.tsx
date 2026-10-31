import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { QueryProvider } from '../QueryProvider';
import { CreatePrompt, CreateProvider } from './Create';

type Call = { method: string; url: string; body: Record<string, unknown> | null };
let calls: Call[];
let commands: { label: string; cmd: string }[];
const json = (b: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } }));

beforeEach(() => {
  calls = [];
  commands = [{ label: 'main', cmd: 'claude' }];
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET';
    calls.push({ method, url: String(url), body: init?.body ? JSON.parse(String(init.body)) : null });
    if (url === '/api/repos') return json({ repos: [{ slug: 'o/r', name: 'R', path: '/x' }, { slug: 'o/q', name: 'Q', path: '/y' }], can_browse: false, scan_roots: [] });
    if (url === '/api/route') return json({ route: null, confidence: 0, why: 'x' });
    if (url === '/api/settings') return json({ commands, default: 'main' });
    if (method === 'POST') return json({ id: 's1' }, 201);
    return json({});
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const open = async () => {
  render(<QueryProvider><MemoryRouter><CreateProvider><CreatePrompt repo="o/r" /></CreateProvider></MemoryRouter></QueryProvider>);
  await userEvent.click(screen.getByRole('button', { name: /Describe a feature or a fix/ }));
  return screen.findByLabelText('Describe a feature or a fix');
};
const post = (url: string) => calls.find((c) => c.method === 'POST' && c.url === url)?.body;

async function pickQ() {
  await userEvent.click(await screen.findByRole('button', { name: 'Repository: r' }));
  await userEvent.click(await screen.findByText('q'));
}
const route = (name: string) => userEvent.click(screen.getByRole('radio', { name }));

it('Feature files into the picked repo', async () => {
  const box = await open();
  await pickQ();
  await route('Feature');
  await userEvent.type(box, 'x');
  await userEvent.click(screen.getByRole('button', { name: 'Start the PRD interview' }));
  await waitFor(() => expect(post('/api/sessions')?.repo).toBe('o/q'));
});

it('Small change files into the picked repo', async () => {
  const box = await open();
  await pickQ();
  await route('Small change');
  await userEvent.type(box, 'x');
  await userEvent.click(screen.getByRole('button', { name: 'File the issue' }));
  await waitFor(() => expect(post('/api/start')?.repo).toBe('o/q'));
});

it('defaults to the repo it was opened with, and Cmd+Enter submits', async () => {
  const box = await open();
  await route('Feature');
  await userEvent.type(box, 'x{Meta>}{Enter}{/Meta}');
  await waitFor(() => expect(post('/api/sessions')?.repo).toBe('o/r'));
});

it('hides the account picker with one account and pins nothing', async () => {
  const box = await open();
  await route('Feature');
  await userEvent.type(box, 'x');
  await userEvent.click(screen.getByRole('button', { name: 'Start the PRD interview' }));
  await waitFor(() => expect(post('/api/sessions')).toBeTruthy());
  expect(screen.queryByRole('radiogroup', { name: 'Run on' })).toBeNull();
  expect(post('/api/sessions')).not.toHaveProperty('pin_account');
});

it('starts on the picked account and pins it for the steps after', async () => {
  commands = [{ label: 'main', cmd: 'claude' }, { label: 'work', cmd: 'claude-work' }];
  const box = await open();
  await userEvent.click(await screen.findByRole('radio', { name: 'work' }));
  await route('Small change');
  await userEvent.type(box, 'x');
  await userEvent.click(screen.getByRole('button', { name: 'File the issue' }));
  await waitFor(() => expect(post('/api/start')).toMatchObject({ claude_cmd: 'work', pin_account: true }));
});

it('pins the default account when nothing else is picked', async () => {
  commands = [{ label: 'main', cmd: 'claude' }, { label: 'work', cmd: 'claude-work' }];
  const box = await open();
  await screen.findByRole('radio', { name: 'main' });
  await route('Feature');
  await userEvent.type(box, 'x');
  await userEvent.click(screen.getByRole('button', { name: 'Start the PRD interview' }));
  await waitFor(() => expect(post('/api/sessions')).toMatchObject({ claude_cmd: 'main', pin_account: true }));
});
