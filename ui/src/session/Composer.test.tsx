import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Session } from '../api/types';
import { Composer } from './Composer';

const s = { id: 's1', outcome: 'done' } as Session;
const mount = () => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify({ state: 'sent' }), { status: 200, headers: { 'Content-Type': 'application/json' } }))));
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><Composer s={s} /></MemoryRouter></QueryClientProvider>);
};
const send = async (text: string) => {
  fireEvent.change(screen.getByLabelText('Message to this session'), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  await screen.findByText('Sent. The session is resuming.');
};
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

describe('Composer note', () => {
  it('clears when the user types again', async () => {
    mount();
    await send('hi');
    fireEvent.change(screen.getByLabelText('Message to this session'), { target: { value: 'n' } });
    await waitFor(() => expect(screen.queryByText('Sent. The session is resuming.')).toBeNull());
  });

  it('clears after a few seconds', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mount();
    await send('hi');
    act(() => { vi.advanceTimersByTime(5100); });
    expect(screen.queryByText('Sent. The session is resuming.')).toBeNull();
  });
});
