import type { Anchor } from '../lib/anchor';
import type { ApproveResult, PublicApproval, PublicComment, PublicPrd, PublicThread } from './types';

export class ShareError extends Error {
  constructor(public status: number) { super(status ? `HTTP ${status}` : 'network'); }
}

export const shareToken = (): string => /^\/s\/([^/]+)/.exec(location.pathname)?.[1] ?? '';

export async function shareFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const post = (init.method ?? 'GET') !== 'GET';
  const headers = { Accept: 'application/json', ...(post ? { 'Content-Type': 'application/json' } : {}) };
  let r: Response;
  try { r = await fetch(`/s/${shareToken()}${path}`, { ...init, headers }); } catch { throw new ShareError(0); }
  if (!r.ok) throw new ShareError(r.status);
  if (r.status === 204) return undefined as T;
  return r.json() as Promise<T>;
}

export const getPrd = (signal?: AbortSignal) => shareFetch<PublicPrd>('/api/prd', { signal });

export const getThreads = (signal?: AbortSignal) => shareFetch<PublicThread[]>('/api/threads', { signal });
export const postThread = (b: { name: string; body: string; anchor: Anchor }) => shareFetch<PublicThread>('/api/threads', { method: 'POST', body: JSON.stringify(b) });
export const postComment = (tid: string, b: { name: string; body: string }) => shareFetch<PublicComment>(`/api/threads/${encodeURIComponent(tid)}/comments`, { method: 'POST', body: JSON.stringify(b) });

export const getApprovals = (signal?: AbortSignal) => shareFetch<PublicApproval[]>('/api/approvals', { signal });
export const approve = (name: string) => shareFetch<ApproveResult>('/api/approvals', { method: 'POST', body: JSON.stringify({ name }) });
export const withdraw = (name: string, key: string) => shareFetch<void>('/api/approvals', { method: 'DELETE', body: JSON.stringify({ name, key }) });

const POST_ERRORS: Record<number, string> = {
  400: 'That name or comment is not valid, your draft is kept',
  409: 'Share is full, your draft is kept',
  413: 'That is too large to post, your draft is kept',
  429: 'Too many comments, try again in a minute. Your draft is kept',
};
const APPROVE_ERRORS: Record<number, string> = {
  400: 'That name is not valid',
  409: 'This share has reached its limit of 100 approvals',
  413: 'That is too large to send',
  429: 'Too many requests, try again in a minute',
};
export const postError = (e: unknown, approvals = false): string =>
  (e instanceof ShareError && (approvals ? APPROVE_ERRORS : POST_ERRORS)[e.status]) || (approvals ? 'Could not reach the server, try again' : 'Could not post, your draft is kept');
