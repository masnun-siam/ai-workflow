import type { PublicPrd } from './types';

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
  return r.json() as Promise<T>;
}

export const getPrd = (signal?: AbortSignal) => shareFetch<PublicPrd>('/api/prd', { signal });
