import { ApiFailure, createClient, Declined, type Client } from "./client";
import type { EventSourceLike } from "./sse";

let impl: Client = createClient();
let sseFactory: ((url: string) => EventSourceLike) | undefined;

/** What the user picked when a start needs a repo map (FR-12). "onboard" means the chooser already started
 *  agentic-onboard; for http both it and "cancel" decline the original start. */
export type MapChoice = "monorepo" | "onboard" | "cancel";
let mapChooser: ((repo: string) => Promise<MapChoice>) | undefined;
/** Registered once at start-up; without one, a 409 `needs a repo map` reaches the caller as any other error. */
export function setMapChooser(fn: ((repo: string) => Promise<MapChoice>) | undefined): void {
  mapChooser = fn;
}

const SLUG = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
/** The repo a start needs a map for, when `e` is the server's 409 for a session or dispatch start; else null. */
function unmappedRepo(e: unknown, method: string, path: string): string | null {
  if (!(e instanceof ApiFailure) || e.status !== 409 || e.body.error !== "needs a repo map") return null;
  if (method !== "POST" || !(path.startsWith("/api/sessions") || path === "/api/dispatches")) return null;
  const repo = e.body.repo;
  return typeof repo === "string" && SLUG.test(repo) ? repo : null;
}

async function send<T>(method: "POST" | "PUT" | "DELETE", path: string, body?: unknown): Promise<T> {
  try {
    return await impl.send<T>(method, path, body);
  } catch (e) {
    const repo = unmappedRepo(e, method, path);
    if (!repo || !mapChooser) throw e;
    if ((await mapChooser(repo)) !== "monorepo") throw new Declined();
    // a failed map write propagates, and the original start is not repeated
    await impl.send("POST", `/api/repos/${repo}/monorepo`, {});
    return impl.send<T>(method, path, body);
  }
}

/** The client every screen uses. It delegates, so the mock can be swapped in at start-up. A start the server
 *  answers with 409 `needs a repo map` asks the registered chooser, then retries it or declines. */
export const http: Client = {
  get: (p) => impl.get(p),
  send,
};

export const sseCreate = (): ((url: string) => EventSourceLike) | undefined => sseFactory;

/** Dev flag: `npm run dev:mock` (vite --mode mock) swaps in web/mock. The branch is dead code in production builds. */
export async function initApi(): Promise<void> {
  if (import.meta.env.MODE === "mock") {
    const m = await import("../../mock/server");
    impl = createClient(m.mockFetch);
    sseFactory = m.createMockEventSource;
  }
}

export function useMockClient(c: Client): void {
  impl = c;
}
