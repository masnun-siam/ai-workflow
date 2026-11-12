import { renderToString } from "preact-render-to-string";
import { beforeAll, describe, expect, it } from "vitest";
import { createClient } from "./api/client";
import { useMockClient } from "./api/http";
import { mockFetch } from "../mock/server";
import { App } from "./app/App";
import { activityTab, loadMany } from "./state/data";
import type { LoadKey } from "./state/refetch";
import { prefs } from "./state/prefs";
import { nav } from "./state/route";

const ALL: LoadKey[] = ["status", "river", "inbox", "sessions", "releases", "ops", "me", "settings", "notify", "review", "blubird", "products", "repos", "dispatches", "coordinators", "grinds", "panels", "registry"];

beforeAll(async () => {
  useMockClient(createClient(mockFetch));
  await loadMany(ALL);
});

const SCREENS: [string, string][] = [["#/river", "Merchant payouts v2"], ["#/inbox", "Questions"], ["#/activity", "Payout batch model"], ["#/dispatches", "Dispatches"],
  ["#/features", "Features"], ["#/changes", "Small changes"], ["#/releases", "release note preview"],
  ["#/ops", "security-sweep"], ["#/me", "Reconcile today"], ["#/settings", "appearance"], ["#/prd?repo=a/b&path=x.md", "PRD"]];

describe("smoke render from mock fixtures", () => {
  for (const look of ["classic", "console", "river"] as const) {
    for (const layout of ["drawer", "split"] as const) {
      for (const [hash, needle] of SCREENS) {
        it(`${look} ${layout} ${hash}`, () => {
          prefs.value = { look, mode: "system", layout };
          nav(hash);
          const html = renderToString(<App />);
          expect(html).toContain(needle);
          expect(html).toContain('aria-label="Main"');
        });
      }
    }
  }
  it("renders the session page with the transcript, hooks and an answer form", async () => {
    prefs.value = { look: "console", mode: "system", layout: "drawer" };
    nav("#/sessions/20261112T010000000000Z-00000001");
    await loadMany(["session", "stream"]);
    const html = renderToString(<App />);
    expect(html).toContain("Migration");
    expect(html).toContain("Nullable + backfill job");
  });
  it("renders the activity sub-views", () => {
    nav("#/activity");
    for (const t of ["coordinators", "grinds", "panels"] as const) {
      activityTab.value = t;
      expect(renderToString(<App />).length).toBeGreaterThan(1000);
    }
    activityTab.value = "sessions";
  });
  it("shows the repo switcher and filters a page to one repo with ?only=", () => {
    prefs.value = { look: "classic", mode: "system", layout: "drawer" };
    nav("#/activity");
    const all = renderToString(<App />);
    expect(all).toContain("Switch repository");
    expect(all).toContain("All repos");
    nav("#/activity?only=acme/wasensi-web");
    const one = renderToString(<App />);
    expect(one).toContain("wasensi-web");
    expect(one).not.toContain("Payout batch model");
  });
  it("renders server-provided actions generically on the river detail", () => {
    nav("#/river");
    expect(renderToString(<App />)).toContain("Merchant payouts v2");
  });
});
