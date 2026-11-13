import { options, type VNode } from "preact";
import { renderToString } from "preact-render-to-string";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createClient, type FetchLike } from "./api/client";
import { useMockClient } from "./api/http";
import { mockFetch, resetMock } from "../mock/server";
import { App } from "./app/App";
import { loadMany, settings } from "./state/data";
import { nav } from "./state/route";

const calls: { method: string; path: string; body: unknown }[] = [];
const recorder: FetchLike = async (input, init) => {
  calls.push({ method: init?.method ?? "GET", path: String(input), body: init?.body ? JSON.parse(String(init.body)) : undefined });
  return mockFetch(input, init);
};

/** The <label class="opt"> that wraps the given visible label text. */
const optLabel = (html: string, text: string) => html.match(new RegExp(`<label class="opt"><input[^>]*>\\s*<span><b>${text}</b>`))?.[0] ?? "";

/** Render the app and return the onChange handler of the Idle guard checkbox, as Preact would attach it. */
function idleGuardOnChange(): (e: { target: { checked: boolean } }) => unknown {
  let handler: ((e: { target: { checked: boolean } }) => unknown) | undefined;
  const prev = options.vnode;
  options.vnode = (v: VNode) => {
    const p = v.props as { name?: string; onChange?: typeof handler };
    if (v.type === "input" && p.name === "idle_guard") handler = p.onChange;
    prev?.(v);
  };
  try { renderToString(<App />); } finally { options.vnode = prev; }
  if (!handler) throw new Error("Idle guard checkbox not rendered");
  return handler;
}

beforeEach(async () => {
  resetMock();
  calls.length = 0;
  useMockClient(createClient(recorder));
  await loadMany(["status", "settings", "notify"]);
  nav("#/settings");
});

describe("Settings: idle guard", () => {
  it("shows the Idle guard checkbox inside its visible label, checked by default", () => {
    const label = optLabel(renderToString(<App />), "Idle guard");
    expect(label).toContain('type="checkbox"');
    expect(label).toContain("checked");
  });

  it("unchecking sends PUT /api/settings {idle_guard:false} and the box stays unchecked", async () => {
    idleGuardOnChange()({ target: { checked: false } });
    await vi.waitFor(() => expect(settings.value?.idle_guard).toBe(false));
    expect(calls.filter((c) => c.method === "PUT")).toEqual([{ method: "PUT", path: "/api/settings", body: { idle_guard: false } }]);
    const label = optLabel(renderToString(<App />), "Idle guard");
    expect(label).toContain('type="checkbox"');
    expect(label).not.toContain("checked");
  });

  it("a failed save leaves the setting as it was", async () => {
    let put = false;
    useMockClient(createClient(async () => { put = true; return new Response(JSON.stringify({ error: "disk full" }), { status: 500, headers: { "content-type": "application/json" } }); }));
    idleGuardOnChange()({ target: { checked: false } });
    await vi.waitFor(() => expect(put).toBe(true));
    await new Promise((r) => setTimeout(r, 0));
    expect(settings.value?.idle_guard).toBe(true);
  });
});

describe("Settings: notification matrix", () => {
  it("has a stalled row with every channel off", () => {
    const html = renderToString(<App />);
    const row = html.match(/<tr><td>A session or lane stalled .*?<\/tr>/)?.[0] ?? "";
    expect(row).not.toBe("");
    const boxes = row.match(/<input [^>]*>/g) ?? [];
    expect(boxes).toHaveLength(4);
    for (const b of boxes) expect(b).not.toMatch(/\bchecked\b/);
  });
});
