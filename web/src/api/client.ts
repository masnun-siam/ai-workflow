import type { ApiError } from "./types";

/** Thrown for every non-2xx response. `body` is the parsed `{error, ...extra}` object. */
export class ApiFailure extends Error {
  constructor(
    public status: number,
    public body: ApiError,
  ) {
    super(body.error);
    this.name = "ApiFailure";
  }
}

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export type Client = {
  get<T>(path: string): Promise<T>;
  send<T>(method: "POST" | "PUT" | "DELETE", path: string, body?: unknown): Promise<T>;
};

/** A JSON client for the setu API. Paths are absolute ("/api/..."). */
export function createClient(fetchImpl: FetchLike = (i, init) => fetch(i, init)): Client {
  async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const init: RequestInit = { method, headers: { Accept: "application/json" } };
    if (body !== undefined) {
      const json = JSON.stringify(body);
      init.headers = { ...init.headers, "Content-Type": "application/json" };
      init.body = json;
    } else if (method !== "GET") {
      // the server requires a JSON object body on POSTs that read one; harmless on "no body" actions
      init.headers = { ...init.headers, "Content-Type": "application/json" };
      init.body = "{}";
    }
    let res: Response;
    try {
      res = await fetchImpl(path, init);
    } catch (e) {
      throw new ApiFailure(0, { error: e instanceof Error ? e.message : "network error" });
    }
    const text = await res.text();
    let parsed: unknown = null;
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = null;
      }
    }
    if (!res.ok) {
      const err =
        parsed && typeof parsed === "object" && "error" in parsed
          ? (parsed as ApiError)
          : { error: text.trim() || res.statusText || `HTTP ${res.status}` };
      throw new ApiFailure(res.status, err);
    }
    return parsed as T;
  }
  return {
    get: (path) => request("GET", path),
    send: (method, path, body) => request(method, path, body),
  };
}

export const api = createClient();
