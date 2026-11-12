import { createClient, type Client } from "./client";
import type { EventSourceLike } from "./sse";

let impl: Client = createClient();
let sseFactory: ((url: string) => EventSourceLike) | undefined;

/** The client every screen uses. It delegates, so the mock can be swapped in at start-up. */
export const http: Client = {
  get: (p) => impl.get(p),
  send: (m, p, b) => impl.send(m, p, b),
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
