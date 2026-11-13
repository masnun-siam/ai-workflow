import { renderToString } from "preact-render-to-string";
import { beforeEach, describe, expect, it } from "vitest";
import { createClient, type FetchLike } from "./api/client";
import { useMockClient } from "./api/http";
import type { Dispatch, Lane, Session } from "./api/types";
import { mockFetch, resetMock } from "../mock/server";
import { App } from "./app/App";
import { continueSession, SessionView } from "./components/SessionView";
import { continueLane, inTab } from "./screens/Dispatches";
import { dispatches, inbox, loadMany } from "./state/data";
import { nav } from "./state/route";

const DID = "d1a2b3c4d5e6";
const STALLED = "acme/wasensi-backend%23946";

/** A fetch that records every call and can answer some paths itself. */
function recorder(override?: (method: string, path: string) => Response | undefined) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  const f: FetchLike = async (input, init) => {
    const method = init?.method ?? "GET";
    const path = String(input);
    calls.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    return override?.(method, path) ?? mockFetch(input, init);
  };
  return { calls, f };
}
const conflict = () => new Response(JSON.stringify({ error: "no longer stalled" }), { status: 409, headers: { "content-type": "application/json" } });

beforeEach(async () => {
  resetMock();
  useMockClient(createClient(mockFetch));
  await loadMany(["status", "repos", "products", "settings", "registry", "inbox", "dispatches", "grinds", "sessions"]);
});

describe("stalled lanes", () => {
  it("show the Stalled tag, the reason banner, and Continue next to Retry", () => {
    nav(`#/dispatches/${DID}?lane=${STALLED}`);
    const html = renderToString(<App />);
    expect(html).toContain('<span class="tag c-w">Stalled</span>');
    expect(html).toContain('<div class="banner">Stalled: stopped before a PR</div>');
    expect(html).toMatch(/<button type="button" class="btn pri sm">Continue<\/button>/);
    expect(html).toMatch(/<button type="button" class="btn sm">Retry<\/button>/);
  });

  it("count as Needs you: the list tab and count, and the page section rather than Building now", () => {
    const d = dispatches.value!.find((x) => x.id === DID)!;
    expect(inTab(d, "needs")).toBe(true);
    nav("#/dispatches");
    expect(renderToString(<App />)).toContain("1 need you");
    nav(`#/dispatches/${DID}`);
    const html = renderToString(<App />);
    const needs = html.slice(html.indexOf('aria-label="Needs you"'), html.indexOf('aria-label="Can\'t start"'));
    expect(needs).toContain("Needs you · 1");
    expect(needs).toContain("Rate cache metrics");
    const building = html.slice(html.indexOf('aria-label="Building now"'), html.indexOf('aria-label="Up next"'));
    expect(building).not.toContain("Rate cache metrics");
  });

  it("a lane that needs you still says Needs you and has no Continue", () => {
    const d = structuredClone(dispatches.value!.find((x) => x.id === DID)!) as Dispatch;
    const l = d.lanes.find((x) => x.n === 946)! as Lane;
    Object.assign(l, { stalled: null, needs_you: "waiting on you" });
    dispatches.value = [d];
    nav(`#/dispatches/${DID}?lane=${STALLED}`);
    const html = renderToString(<App />);
    expect(html).toContain('<span class="tag c-w">Needs you</span>');
    expect(html).not.toContain("Stalled: "); // the lane's session list may still say Stalled for the old run
    expect(html).not.toContain(">Continue<");
    expect(html).toContain(">Retry<");
    expect(inTab(d, "needs")).toBe(true);
  });

  it("Continue posts {lane, action: continue} and stays pending until the reload ends", async () => {
    const r = recorder();
    useMockClient(createClient(r.f));
    let done = false;
    const p = continueLane({ id: DID }, "acme/wasensi-backend#946").then(() => { done = true; });
    expect(done).toBe(false);
    await p;
    const post = r.calls.find((c) => c.method === "POST")!;
    expect(post.path).toBe(`/api/dispatches/${DID}/lane`);
    expect(post.body).toEqual({ lane: "acme/wasensi-backend#946", action: "continue" });
    expect(r.calls.some((c) => c.method === "GET" && c.path.startsWith("/api/dispatches"))).toBe(true);
    expect(dispatches.value!.find((x) => x.id === DID)!.lanes.find((x) => x.n === 946)!.stalled).toBeNull();
  });

  it("a 409 (no longer stalled) reloads the dispatches", async () => {
    const r = recorder((m, p) => (m === "POST" && p.endsWith("/lane") ? conflict() : undefined));
    useMockClient(createClient(r.f));
    await continueLane({ id: DID }, "acme/wasensi-backend#946");
    const i = r.calls.findIndex((c) => c.method === "POST");
    expect(r.calls.slice(i + 1).some((c) => c.method === "GET" && c.path.startsWith("/api/dispatches"))).toBe(true);
  });
});

describe("stalled sessions", () => {
  const base = {
    id: "s1", title: "Docs refresh", command: "/blubird:docs-updater", status: "done", session_id: "abc", skill: null, repo: "o/r",
    link: null, hooks: 0, hold: false, dismissed: false, account: "Work", tokens: null, cost: null, stalled: null,
  } as unknown as Session;

  it("the session view shows Stalled, the reason and Continue", () => {
    const html = renderToString(<SessionView s={{ ...base, stalled: "ended its turn without finishing" }} />);
    expect(html).toContain('<span class="tag c-w">Stalled</span>');
    expect(html).toContain("Stalled: ended its turn without finishing");
    expect(html).toMatch(/<button type="button" class="btn pri sm">Continue<\/button>/);
  });

  it("a session that did not stall shows its status and no Continue", () => {
    const html = renderToString(<SessionView s={base} />);
    expect(html).toContain('<span class="tag c-o">done</span>');
    expect(html).not.toContain("Stalled");
    expect(html).not.toContain(">Continue<");
  });

  it("the session list shows Stalled in place of the status", () => {
    nav("#/activity");
    const html = renderToString(<App />);
    expect(html).toMatch(/<span class="tag c-w">Stalled<\/span><span class="t mono">blubird:docs-updater<\/span>/);
  });

  it("Continue posts to /api/sessions/<id>/continue; a 409 reloads sessions, session and inbox", async () => {
    const ok = recorder();
    useMockClient(createClient(ok.f));
    await continueSession("20261112T0110000000000Z-000000011");
    expect(ok.calls.find((c) => c.method === "POST")!.path).toBe("/api/sessions/20261112T0110000000000Z-000000011/continue");

    const r = recorder((m, p) => (m === "POST" && p.endsWith("/continue") ? conflict() : undefined));
    useMockClient(createClient(r.f));
    await continueSession("s1");
    const after = r.calls.slice(r.calls.findIndex((c) => c.method === "POST") + 1).map((c) => c.path);
    expect(after.some((p) => p.startsWith("/api/sessions"))).toBe(true);
    expect(after.some((p) => p.startsWith("/api/inbox"))).toBe(true);
  });
});

describe("stalled inbox rows", () => {
  it("sit under Fix with the server's Continue as the primary action", () => {
    const items = inbox.value!.items.filter((i) => i.type === "session_stalled" || i.type === "dispatch_stalled");
    expect(items.map((i) => i.type).sort()).toEqual(["dispatch_stalled", "session_stalled"]);
    for (const i of items) {
      expect(i.group).toBe("fix");
      expect(i.actions.find((a) => a.primary)?.label).toBe("Continue");
    }
    nav("#/inbox");
    const html = renderToString(<App />);
    const fix = html.slice(html.indexOf(">Fix<"));
    expect(fix).toContain("Docs refresh");
    expect(fix).toContain("Rate cache metrics");
  });
});
