import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useDeliveryAll, usePlanningAll } from '../api/hooks';
import type { PlanningAllResponse } from '../api/types';
import { useRepoFilter } from './useRepoFilter';

const json = (b: unknown) => Promise.resolve(new Response(JSON.stringify(b), { status: 200, headers: { 'Content-Type': 'application/json' } }));
const REPOS = { repos: [{ slug: 'o/r', name: 'R', path: '/x' }, { slug: 'o/bop-bd', name: 'B', path: '/y' }], can_browse: false, scan_roots: [] };
const ALL: PlanningAllResponse = {
  repos: [{ repo: 'o/r', stale: false, fetched_at: 1, prds: [] } as any, { repo: 'o/bop-bd', stale: false, fetched_at: null, error: 'boom' }],
  stale: ['o/bop-bd'],
};
const calls: string[] = [];

function stub(repos: unknown = REPOS) {
  calls.length = 0;
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    calls.push(String(url));
    const p = String(url).split('?')[0];
    return json(p === '/api/repos' ? repos : p === '/api/planning' ? ALL : { repos: [], stale: [] });
  }));
}

let ctl: ReturnType<typeof useRepoFilter>;
let loc = '';
function Probe() {
  ctl = useRepoFilter();
  const l = useLocation();
  loc = l.pathname + l.search;
  return null;
}
const mount = (url: string, ui = <Probe />) =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[url]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('useRepoFilter', () => {
  it('keeps the raw ?only= while repos load, then resolves it case-insensitively', async () => {
    stub();
    mount('/features?only=O/BOP-BD');
    expect(ctl.only).toBe('O/BOP-BD');
    await waitFor(() => expect(ctl.only).toBe('o/bop-bd'));
  });
  it('setOnly sets only and keeps repo; clearing removes it', async () => {
    stub();
    mount('/features?repo=o/r');
    await waitFor(() => expect(ctl.only).toBe(''));
    ctl.setOnly('o/bop-bd');
    await waitFor(() => expect(loc).toBe('/features?repo=o/r&only=o/bop-bd'));
    ctl.setOnly('');
    await waitFor(() => expect(loc).toBe('/features?repo=o/r'));
  });
  it('drops an unregistered only once repos load', async () => {
    stub();
    mount('/features?repo=o/r&only=x/gone');
    await waitFor(() => expect(loc).toBe('/features?repo=o/r'));
    expect(ctl.only).toBe('');
  });
  it('?repo= alone leaves only empty and the URL alone', async () => {
    stub();
    mount('/features?repo=o/r');
    await waitFor(() => expect(ctl.only).toBe(''));
    expect(loc).toBe('/features?repo=o/r');
  });
});

describe('all-repos board hooks', () => {
  function Boards({ on }: { on: boolean }) {
    const p = usePlanningAll(on);
    useDeliveryAll(on);
    const e = p.data?.repos[1];
    return <span data-testid="x">{p.data ? `${'prds' in p.data.repos[0]!}:${e && 'prds' in e}:${e?.error}` : 'none'}</span>;
  }
  it('passes the {repos, stale} body through, with a meta-only entry; calls no repo param', async () => {
    stub();
    const { findByText } = mount('/', <Boards on />);
    await findByText('true:false:boom');
    expect(calls).toContain('/api/planning');
    expect(calls).toContain('/api/delivery');
  });
  it('is disabled when enabled is false', async () => {
    stub();
    const { findByText } = mount('/', <Boards on={false} />);
    await findByText('none');
    expect(calls.filter((c) => c.startsWith('/api/planning') || c.startsWith('/api/delivery'))).toEqual([]);
  });
});
