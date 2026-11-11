import { describe, expect, it } from "vitest";
import { ApiFailure, createClient } from "./client";
import { backoffDelay, connectEvents, type EventSourceLike } from "./sse";
import type { Session } from "./types";

describe("api client", () => {
  it("parses JSON, sends bodies and raises ApiFailure with the server error", async () => {
    const calls: { path: string; init?: RequestInit }[] = [];
    const client = createClient(async (path, init) => {
      calls.push({ path, init });
      if (path === "/api/boom") return new Response(JSON.stringify({ error: "nope", id: "s1" }), { status: 409 });
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    });
    expect(await client.get<{ ok: boolean }>("/api/health")).toEqual({ ok: true });
    await client.send("POST", "/api/sessions", { step: "create-prd" });
    expect(calls[1]?.init?.body).toBe('{"step":"create-prd"}');
    expect((calls[1]?.init?.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    const err = (await client.send("POST", "/api/boom").catch((e) => e)) as ApiFailure;
    expect(err).toBeInstanceOf(ApiFailure);
    expect(err.status).toBe(409);
    expect(err.body.id).toBe("s1");
  });

  it("types match the contract", () => {
    const s: Pick<Session, "status" | "link"> = { status: "running", link: null };
    expect(s.status).toBe("running");
  });
});

describe("sse client", () => {
  it("reconnects with growing backoff and resets after hello", () => {
    const sources: FakeEs[] = [];
    class FakeEs implements EventSourceLike {
      listeners: Record<string, (ev: MessageEvent) => void> = {};
      onerror: ((ev: Event) => void) | null = null;
      onopen: ((ev: Event) => void) | null = null;
      readyState = 0;
      closed = false;
      addEventListener(t: string, fn: (ev: MessageEvent) => void) {
        this.listeners[t] = fn;
      }
      close() {
        this.closed = true;
        this.readyState = 2;
      }
      emit(t: string, data: unknown) {
        this.listeners[t]?.({ data: JSON.stringify(data) } as MessageEvent);
      }
    }
    const timers: { fn: () => void; ms: number }[] = [];
    const got: string[] = [];
    const stop = connectEvents({
      onEvent: (t) => got.push(t),
      onHello: (h) => got.push(`hello:${h.version}`),
      create: () => {
        const e = new FakeEs();
        sources.push(e);
        return e;
      },
      setTimer: (fn, ms) => timers.push({ fn, ms }),
      clearTimer: () => {},
      random: () => 0,
    });
    expect(sources).toHaveLength(1);
    sources[0]!.onerror?.(new Event("error"));
    sources[0]!.onerror?.(new Event("error")); // a duplicate error must not double-schedule
    expect(timers.map((t) => t.ms)).toEqual([1000]);
    timers[0]!.fn();
    sources[1]!.onerror?.(new Event("error"));
    expect(timers.map((t) => t.ms)).toEqual([1000, 2000]);
    timers[1]!.fn();
    sources[2]!.emit("hello", { version: "1.2", boot_id: "b", resync: false });
    sources[2]!.emit("sessions", { id: "x", status: "running", change: "record" });
    expect(got).toEqual(["hello:1.2", "hello", "sessions"]);
    sources[2]!.onerror?.(new Event("error"));
    expect(timers[2]!.ms).toBe(1000); // reset by hello
    stop();
    expect(backoffDelay(30, 1000, 30000, () => 0)).toBe(30000);
  });
});
