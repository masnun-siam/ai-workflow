import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { QueryProvider } from '../QueryProvider';
import { BoardStatus } from './BoardStatus';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const show = (onRetry?: () => void) => render(
  <QueryProvider><MemoryRouter><BoardStatus failed onRetry={onRetry} /></MemoryRouter></QueryProvider>,
);

it('the could-not-refresh banner retries the board now', async () => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response('{}', { status: 200 }))));
  const onRetry = vi.fn();
  show(onRetry);
  await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
  expect(onRetry).toHaveBeenCalledTimes(1);
});

it('shows no Retry when the caller gives none', () => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response('{}', { status: 200 }))));
  show();
  expect(screen.getByText('Could not refresh.')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull();
});
