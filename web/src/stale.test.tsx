import { renderToString } from "preact-render-to-string";
import { beforeEach, describe, expect, it } from "vitest";
import { createClient } from "./api/client";
import { useMockClient } from "./api/http";
import { mockFetch, resetMock } from "../mock/server";
import { App } from "./app/App";
import { COORD_STALE_HINT } from "./screens/Activity";
import { activityTab, coordinators, loadMany } from "./state/data";
import { TYPE_LABEL } from "./state/inboxView";
import { nav } from "./state/route";

beforeEach(async () => {
  resetMock();
  useMockClient(createClient(mockFetch));
  await loadMany(["status", "repos", "products", "settings", "registry", "sessions", "coordinators"]);
  activityTab.value = "coordinators";
  nav("#/activity");
});

const rows = (html: string) => html.match(/<tr[^>]*>.*?<\/tr>/g) ?? [];

describe("stale coordinator issues", () => {
  it("highlight the in-progress-stale row with blubird's hint and leave the others plain", () => {
    const html = renderToString(<App />);
    const stale = rows(html).filter((r) => r.includes("#<!-- -->463") || r.includes("#463"));
    expect(stale).toHaveLength(1);
    expect(stale[0]).toMatch(/^<tr class="need">/);
    expect(stale[0]).toContain(`<div class="dim">${COORD_STALE_HINT}</div>`);
    expect(stale[0]).toContain('<span class="tag c-w">in-progress-stale</span>');
    const plain = rows(html).filter((r) => r.includes("Rate cache") || r.includes("phpstan"));
    expect(plain).toHaveLength(2);
    for (const r of plain) {
      expect(r).toMatch(/^<tr>/);
      expect(r).not.toContain(COORD_STALE_HINT);
    }
  });

  it("show no hint when no queue line is stale", () => {
    coordinators.value = coordinators.value!.map((c) => ({ ...c, queue: c.queue.filter((q) => q.state !== "in-progress-stale") }));
    const html = renderToString(<App />);
    expect(html).toContain("Rate cache");
    expect(html).not.toContain(COORD_STALE_HINT);
    expect(html).not.toContain('class="need"');
  });

  it("have an Inbox label", () => {
    expect(TYPE_LABEL.coord_stale).toBe("Stale issue");
  });
});
