import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { ChangeDialog, type RoundEntry } from './ChangeDialog';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('None of these counts as a change and posts none to /api/afk/change', async () => {
  const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify({ results: [] }), { status: 200, headers: { 'Content-Type': 'application/json' } })));
  vi.stubGlobal('fetch', fetchMock);
  const round = { id: 'r1', sid: 's1', command: 'cmd', at: '2026-01-01T00:00:00Z', questions: [{ question: 'Extras?', multiSelect: true, allowFreeText: false, options: [{ label: 'A' }, { label: 'B' }], picked: ['A'] }] } as unknown as RoundEntry;
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><MemoryRouter><ChangeDialog rounds={[round]} onClose={() => {}} /></MemoryRouter></QueryClientProvider>);
  const submit = screen.getByRole('button', { name: 'Submit' }) as HTMLButtonElement;
  expect(submit.disabled).toBe(true);
  await userEvent.setup().click(screen.getByRole('checkbox', { name: 'None of these' }));
  expect(submit.disabled).toBe(false);
  await userEvent.setup().click(submit);
  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe('/api/afk/change');
  expect(JSON.parse(init.body as string)).toEqual({ changes: [{ id: 'r1', answers: { 0: { none: true } } }] });
});
