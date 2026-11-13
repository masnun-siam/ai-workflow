import { renderToString } from "preact-render-to-string";
import { beforeAll, describe, expect, it } from "vitest";
import { createClient } from "./api/client";
import { useMockClient } from "./api/http";
import { mockFetch } from "../mock/server";
import { App } from "./app/App";
import { Detail } from "./components/Detail";
import { loadMany, ops } from "./state/data";
import { nav } from "./state/route";

const page = (hash: string) => { nav(hash); return renderToString(<App />); };

describe("Me, Ops, River, Onboarding", () => {
  beforeAll(async () => {
    useMockClient(createClient(mockFetch));
    await loadMany(["status", "repos", "products", "settings", "registry", "inbox", "sessions", "river", "ops", "me", "releases"]);
  });
  it("Me renders the day-end button by its step, lists the missing dates and shows both usage meters", () => {
    const html = page("#/me");
    expect(html).toContain("Run day-end");
    expect(html).toContain("2026-11-02, 2026-11-09");
    expect(html).toContain("five hour usage");
    expect(html).toContain("seven day usage");
  });
  it("Ops explains a row that needs a product and links to Settings", () => {
    const rows = ops.value!.rows;
    ops.value = { ...ops.value!, rows: [{ ...rows[0]!, summary: "needs a product", targets: [], actions: [] }, ...rows.slice(1)] };
    const html = page("#/ops");
    expect(html).toContain('href="#/settings?pane=products"');
    expect(html).toContain("Needs a product");
  });
  it("the ops detail table has column headers", () => {
    const row = ops.value!.rows[1]!;
    const html = renderToString(<Detail t={{ kind: "ops", row: { ...row, targets: [{ repo: "acme/web", last: null, note: "n" }] } }} />);
    expect(html).toContain('scope="col"');
  });
  it("Releases: stepper marks the current step and a repo select replaces the chips", () => {
    const html = page("#/releases");
    expect(html).toContain('aria-current="step"');
    expect(html).toContain('aria-hidden="true">[');
    expect(html).toContain('aria-haspopup="listbox"');
  });
  it("Onboarding links the textarea to its helper text", () => {
    const html = page("#/onboarding");
    expect(html).toContain('aria-describedby="onb-roots-help"');
    expect(html).toContain('id="onb-roots-help"');
  });
});
