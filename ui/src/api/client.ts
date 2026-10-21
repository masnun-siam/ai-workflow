// One fetch wrapper for the whole app: JSON in, JSON out, errors carry the status and the server's {error}.

export class ApiError extends Error {
  status: number; // 0 = the server could not be reached
  body: Record<string, unknown> | null;
  constructor(status: number, message: string, body: Record<string, unknown> | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
  get offline() {
    return this.status === 0;
  }
  /** 409 duplicate start: {id, href} of the session already running. */
  get duplicate(): { id?: string; href?: string } | null {
    return this.status === 409 && this.body && ('id' in this.body || 'href' in this.body)
      ? { id: this.body.id as string | undefined, href: this.body.href as string | undefined }
      : null;
  }
}

type Method = 'GET' | 'POST' | 'PUT';

export async function request<T>(method: Method, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const init: RequestInit = { method, signal, headers: { Accept: 'application/json' } };
  if (method !== 'GET') {
    (init.headers as Record<string, string>)['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body ?? {});
  }
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e;
    throw new ApiError(0, 'Could not reach the aiw server');
  }
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    const obj = data && typeof data === 'object' ? (data as Record<string, unknown>) : null;
    const msg = obj && typeof obj.error === 'string' ? obj.error : `Request failed (${res.status})`;
    throw new ApiError(res.status, msg, obj);
  }
  return data as T;
}

export const get = <T>(path: string, signal?: AbortSignal) => request<T>('GET', path, undefined, signal);
export const post = <T = Record<string, never>>(path: string, body?: unknown) => request<T>('POST', path, body);
export const put = <T = Record<string, never>>(path: string, body?: unknown) => request<T>('PUT', path, body);

/** Query string from defined values only. */
export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') sp.set(k, String(v));
  const s = sp.toString().replace(/%2F/gi, '/');
  return s ? `?${s}` : '';
}

export const enc = encodeURIComponent;
/** Split owner/name for the /api/issues|pulls|repos/<o>/<r>/... routes. */
export function splitRepo(repo: string): [string, string] {
  const [o, ...r] = repo.split('/');
  return [enc(o), enc(r.join('/'))];
}
