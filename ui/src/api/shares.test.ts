import { QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { createElement, type ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { makeQueryClient } from '../QueryProvider';
import { ApiError } from './client';
import { api } from './endpoints';
import { useShares, useStopShare } from './hooks';
import type { Share, ShareSummary } from './types';

const summary: ShareSummary = { id: 's1', repo: 'o/r', path: 'docs/prds/a.md', title: 'A', state: 'live', url: 'https://x/s/t', comments: 0, unread: 0, reachable: true, end_reason: null, expires_at: null };
// type-level: compiles only if Share has the shape the PRD tab relies on
const share: Share = { ...summary, created_at: '', ended_at: null, last_seen_at: null, prd_updated_at: null, unsent: 0, threads: [], approvals: [] };

const stub = (status = 200, body: unknown = {}) => {
  const f = vi.fn(async () => new Response(status === 204 ? null : JSON.stringify(body), { status }));
  vi.stubGlobal('fetch', f);
  return f;
};
const last = (f: ReturnType<typeof stub>) => {
  const [url, init] = f.mock.calls.at(-1) as unknown as [string, RequestInit];
  return { url, method: init.method, body: init.body ? JSON.parse(init.body as string) : undefined };
};

afterEach(() => vi.unstubAllGlobals());

describe('share endpoints', () => {
  const cases: [string, () => Promise<unknown>, string, string, unknown][] = [
    ['shares', () => api.shares(), 'GET', '/api/shares', undefined],
    ['share', () => api.share('a/b'), 'GET', '/api/shares/a%2Fb', undefined],
    ['createShare with expiry', () => api.createShare('o/r', 'docs/prds/a.md', 7), 'POST', '/api/shares', { repo: 'o/r', path: 'docs/prds/a.md', confirm: true, expires_in_days: 7 }],
    ['createShare', () => api.createShare('o/r', 'docs/prds/a.md'), 'POST', '/api/shares', { repo: 'o/r', path: 'docs/prds/a.md', confirm: true }],
    ['stopShare', () => api.stopShare('s1'), 'DELETE', '/api/shares/s1', {}],
    ['deleteThread', () => api.deleteThread('s1', 't 1'), 'DELETE', '/api/shares/s1/threads/t%201', {}],
    ['deleteComment', () => api.deleteComment('s1', 't1', 'c1'), 'DELETE', '/api/shares/s1/threads/t1/comments/c1', {}],
    ['deleteApproval', () => api.deleteApproval('s1', 'a1'), 'DELETE', '/api/shares/s1/approvals/a1', {}],
    ['deleteShareRecord', () => api.deleteShareRecord('s1'), 'DELETE', '/api/shares/s1/record', {}],
    ['replyThread', () => api.replyThread('s1', 't1', 'hi'), 'POST', '/api/shares/s1/threads/t1/comments', { body: 'hi' }],
    ['resolveThread', () => api.resolveThread('s1', 't1', true), 'PATCH', '/api/shares/s1/threads/t1', { resolved: true }],
    ['sendPreview', () => api.sendPreview('s1', ['t2']), 'POST', '/api/shares/s1/send', { outdated: ['t2'] }],
    ['sendShare', () => api.sendShare('s1', ['t2']), 'POST', '/api/shares/s1/send', { confirm: true, outdated: ['t2'] }],
    ['markSeen', () => api.markSeen('s1'), 'POST', '/api/shares/s1/seen', {}],
  ];
  it.each(cases)('%s sends the PRD contract', async (_n, call, method, url, body) => {
    const f = stub(200, share);
    await call();
    expect(last(f)).toEqual({ url, method, body });
  });
});

describe('request', () => {
  it('resolves null for an empty 204', async () => {
    stub(204);
    expect(await api.deleteThread('s1', 't1')).toBeNull();
  });
  it.each([409, 503])('rejects %i with status and the server message', async (status) => {
    stub(status, { error: 'nope' });
    const e = await api.createShare('o/r', 'p').catch((x) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect(e).toMatchObject({ status, message: 'nope' });
  });
});

describe('hooks', () => {
  it('a mutation invalidates the share list', async () => {
    const f = stub(200, [summary]);
    const client = makeQueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
    const list = renderHook(() => useShares(), { wrapper });
    await waitFor(() => expect(list.result.current.data).toEqual([summary]));
    const stop = renderHook(() => useStopShare(), { wrapper });
    const lists = () => f.mock.calls.filter((c) => (c as unknown as [string])[0] === '/api/shares' && (c as unknown as [string, RequestInit])[1].method === 'GET').length;
    expect(lists()).toBe(1);
    await act(() => stop.result.current.mutateAsync('s1'));
    await waitFor(() => expect(lists()).toBe(2));
  });
});
