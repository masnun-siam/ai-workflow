import { renderToString } from "preact-render-to-string";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createClient, type FetchLike } from "./api/client";
import { useMockClient } from "./api/http";
import { mockFetch, resetMock } from "../mock/server";
import { App } from "./app/App";
import { awayLabel } from "./state/away";
import { applyPrefs, DEFAULT_PREFS } from "./state/prefs";
import { sameKey, subscribePush } from "./state/push";
import { loadMany, status } from "./state/data";
import { nav } from "./state/route";
import { SLACK_ID } from "./screens/settings/ReleaseNote";
import { intError } from "./screens/settings/common";
import { lensProblem } from "./screens/settings/Review";

describe("number fields", () => {
  it("an empty field is invalid, never 0", () => {
    expect(intError("", 1024, 65535)).toBe("Required");
    expect(intError("  ", 1, 20)).toBe("Required");
  });
  it("checks whole numbers and the range", () => {
    expect(intError("0", 1, 86400)).toBe("Must be 1 to 86400");
    expect(intError("1.5", 1, 20)).toBe("Enter a whole number");
    expect(intError("8420", 1024, 65535)).toBeNull();
  });
});

describe("review lenses", () => {
  it("a line without a colon blocks saving", () => {
    expect(lensProblem("security: look for leaks\nperf")).toBe("Line 2 needs the form name: instructions");
    expect(lensProblem(": no name")).not.toBeNull();
  });
  it("blank lines and good lines pass", () => {
    expect(lensProblem("a: b\n\nc: d: e")).toBeNull();
  });
});

describe("release note", () => {
  it("validates the Slack member id", () => {
    expect(SLACK_ID.test("U01ABC23DEF")).toBe(true);
    expect(SLACK_ID.test("ashique")).toBe(false);
  });
});

describe("prefs", () => {
  it("applyPrefs swaps only the skin class", () => {
    const cls = new Set(["skin-river", "keep-me"]);
    const doc = {
      body: { classList: { add: (c: string) => cls.add(c), remove: (c: string) => cls.delete(c), [Symbol.iterator]: () => cls.values() } },
      documentElement: { removeAttribute: () => {}, setAttribute: () => {} },
    } as unknown as Document;
    applyPrefs({ ...DEFAULT_PREFS, look: "console" }, doc);
    expect([...cls].sort()).toEqual(["keep-me", "skin-console"]);
  });
});

describe("away", () => {
  it("an active away without an end time is open-ended", () => {
    expect(awayLabel({ active: true, until: null })).toBe("Away (open-ended)");
    expect(awayLabel({ active: false, until: null })).toBe("Away mode off");
  });
  it("the rail card renders it as active and read-only", async () => {
    resetMock();
    useMockClient(createClient(mockFetch as FetchLike));
    await loadMany(["status", "settings"]);
    status.value = { ...status.value!, away: { active: true, until: null, started: 1, decisions: 0, held: 2, summary: null } };
    nav("#/inbox");
    const html = renderToString(<App />);
    const card = html.match(/<div class="away-card"[^>]*>.*?<\/div>/)?.[0] ?? "";
    expect(card).toContain("Away (open-ended)");
    expect(card).not.toContain("<button");
    expect(html.match(/I'm back/g)).toHaveLength(1);
  });
});

describe("push", () => {
  const key = new Uint8Array([1, 2, 3]);
  it("compares VAPID keys", () => {
    expect(sameKey(key.buffer as ArrayBuffer, key)).toBe(true);
    expect(sameKey(new Uint8Array([9]).buffer as ArrayBuffer, key)).toBe(false);
    expect(sameKey(null, key)).toBe(true);
  });

  const stub = (existing: { unsubscribe: () => Promise<boolean>; options: { applicationServerKey: ArrayBuffer } } | null, posts: number[]) => {
    const created = { unsubscribe: vi.fn(async () => true), toJSON: () => ({ endpoint: "https://push/x", keys: { p256dh: "a", auth: "b" } }) };
    const reg = { pushManager: { getSubscription: async () => existing, subscribe: vi.fn(async () => created) } };
    vi.stubGlobal("navigator", { serviceWorker: { ready: Promise.resolve(reg), register: async () => reg, getRegistration: async () => reg } });
    vi.stubGlobal("Notification", { permission: "granted", requestPermission: async () => "granted" });
    vi.stubGlobal("PushManager", class {});
    useMockClient(createClient((async (input: string) => {
      if (String(input).includes("/api/push/key")) return new Response(JSON.stringify({ public_key: "AQID" }), { headers: { "content-type": "application/json" } });
      posts.push(1);
      return new Response(JSON.stringify({ error: "nope" }), { status: 500, headers: { "content-type": "application/json" } });
    }) as FetchLike));
    return { created, reg };
  };

  it("a failed server POST unsubscribes the browser and rethrows", async () => {
    const posts: number[] = [];
    const { created } = stub(null, posts);
    await expect(subscribePush()).rejects.toThrow();
    expect(posts).toHaveLength(1);
    expect(created.unsubscribe).toHaveBeenCalled();
  });

  it("a subscription made with another VAPID key is replaced", async () => {
    const old = { unsubscribe: vi.fn(async () => true), options: { applicationServerKey: new Uint8Array([7, 7]).buffer as ArrayBuffer } };
    const { reg } = stub(old, []);
    await expect(subscribePush()).rejects.toThrow();
    expect(old.unsubscribe).toHaveBeenCalled();
    expect(reg.pushManager.subscribe).toHaveBeenCalled();
  });
});

beforeEach(() => vi.unstubAllGlobals());
