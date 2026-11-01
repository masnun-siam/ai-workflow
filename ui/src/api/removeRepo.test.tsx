import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { useRemoveRepo } from './hooks';

afterEach(() => vi.unstubAllGlobals());

it('removing a repo invalidates planning and delivery', async () => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }))));
  const qc = new QueryClient();
  qc.setQueryData(['planning', 'x'], 1);
  qc.setQueryData(['delivery', 'x'], 1);
  const { result } = renderHook(() => useRemoveRepo(), { wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider> });
  await act(() => result.current.mutateAsync('o/r'));
  await waitFor(() => {
    expect(qc.getQueryState(['planning', 'x'])?.isInvalidated).toBe(true);
    expect(qc.getQueryState(['delivery', 'x'])?.isInvalidated).toBe(true);
  });
});
