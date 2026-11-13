import { renderToString } from "preact-render-to-string";
import { beforeEach, describe, expect, it } from "vitest";
import { createClient, type FetchLike } from "./api/client";
import { useMockClient } from "./api/http";
import { mockFetch, resetMock } from "../mock/server";
import { App } from "./app/App";
import { saveIdleGuard } from "./screens/settings/Accounts";
import { loadMany, settings } from "./state/data";
import { nav } from "./state/route";

const calls: { method: string; path: string; body: unknown }[] = [];
const recorder: FetchLike = async (input, init) => {
  calls.push({ method: init?.method ?? "GET", path: String(input), body: init?.body ? JSON.parse(String(init.body)) : undefined });
  return mockFetch(input, init);
};

/** The <label class="opt"> that wraps the given visible label text. */
const optLabel = (html: string, text: string) => html.match(new RegExp(`<label class="opt"><input[^>]*>\\s*<span><b>${text}</b>`))?.[0] ?? "";

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
    expect(await saveIdleGuard(false)).toBe(true);
    expect(calls.filter((c) => c.method === "PUT")).toEqual([{ method: "PUT", path: "/api/settings", body: { idle_guard: false } }]);
    expect(settings.value?.idle_guard).toBe(false);
    const label = optLabel(renderToString(<App />), "Idle guard");
    expect(label).toContain('type="checkbox"');
    expect(label).not.toContain("checked");
  });

  it("a failed save leaves the setting as it was", async () => {
    useMockClient(createClient(async () => new Response(JSON.stringify({ error: "disk full" }), { status: 500, headers: { "content-type": "application/json" } })));
    expect(await saveIdleGuard(false)).toBe(false);
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
