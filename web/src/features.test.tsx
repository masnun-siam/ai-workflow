import { renderToString } from "preact-render-to-string";
import { beforeAll, describe, expect, it } from "vitest";
import { createClient } from "./api/client";
import { useMockClient } from "./api/http";
import { mockFetch } from "../mock/server";
import { App } from "./app/App";
import { loadMany } from "./state/data";
import { parseHash, nav } from "./state/route";
import { newPrdRun, prdUpdateArgs, smallTaskRun } from "./screens/FeaturePage";
import { features } from "./state/data";

describe("features", () => {
  beforeAll(async () => {
    useMockClient(createClient(mockFetch));
    await loadMany(["status", "repos", "products", "settings", "registry", "inbox", "panels"]);
    await loadMany(["features"]);
  });
  it("routes a feature page", () => {
    expect(parseHash("#/features/rates?product=acme/wasensi-docs")).toMatchObject({ screen: "features", id: "rates", query: { product: "acme/wasensi-docs" } });
  });
  it("lists features in bays with stage ticks and next steps", () => {
    nav("#/features");
    const html = renderToString(<App />);
    for (const s of ["Stopped on you", "Waiting for your go", "Running on their own", "Rate cache", "Merge #1050", "Run epic", "Start peer review", "1 shipped", "PRD review"]) expect(html).toContain(s);
    expect(html.indexOf("Stopped on you")).toBeLessThan(html.indexOf("Waiting for your go"));
  });
  it("feature page: build map, issue buckets, add a task", () => {
    nav("#/features/rates?product=acme/wasensi-docs");
    const html = renderToString(<App />);
    for (const s of ["Build map", "#942", "Ready to merge", "Needs refining", "Refine", "Add a task to this epic", "Issues", "Peer review", "Sessions"]) expect(html).toContain(s);
  });
  it("feature page: the review tab shows the running panel", () => {
    nav("#/features/batches?product=acme/wasensi-docs&tab=review");
    const html = renderToString(<App />);
    expect(html).toContain("Round 1 of 3");
    expect(html).toContain("security");
  });
  it("feature page: a draft offers the panel with lenses", () => {
    nav("#/features/recheck?product=acme/wasensi-docs&tab=review");
    expect(renderToString(<App />)).toContain("Run the peer review panel");
  });
  it("feature page: an approved or done PRD is locked", () => {
    for (const slug of ["rates", "login"]) {
      nav(`#/features/${slug}?product=acme/wasensi-docs&tab=prd`);
      const html = renderToString(<App />);
      for (const s of ["Locked", "New PRD for this change", "One small task"]) expect(html, slug).toContain(s);
      expect(html, slug).not.toContain(">Edit<");
      expect(html, slug).not.toContain("ask claude to change it");
    }
  });
  it("feature page: a draft PRD keeps Edit and the change box", () => {
    nav("#/features/recheck?product=acme/wasensi-docs&tab=prd");
    const html = renderToString(<App />);
    expect(html).toContain(">Edit<");
    expect(html).toContain("ask claude to change it");
    expect(html).not.toContain("One small task");
    expect(html).not.toContain("Locked");
  });
  it("builds the locked PRD's change requests", () => {
    const all = features.value!.flatMap((l) => l.features);
    const rates = all.find((f) => f.slug === "rates")!;
    const login = all.find((f) => f.slug === "login")!;
    const np = newPrdRun(rates, "  Add a TTL setting  ");
    expect(np).toMatchObject({ step: "create-prd", repo: "acme/wasensi-docs", product: "acme/wasensi-docs" });
    expect(np.args).not.toMatch(/[\r\n]/);
    for (const s of ["Add a TTL setting", "docs/prds/cache/rates.md", "Related"]) expect(np.args).toContain(s);
    const withEpic = smallTaskRun(rates, "Add a TTL setting");
    expect(withEpic).toMatchObject({ step: "small-change", repo: "acme/wasensi-backend" });
    for (const s of ["Add a TTL setting", "docs/prds/cache/rates.md", "#941", "acme/wasensi-backend#941"]) expect(withEpic.args).toContain(s);
    const noEpic = smallTaskRun(login, "Fix the copy");
    expect(noEpic).toMatchObject({ step: "small-change", repo: "acme/wasensi-docs" });
    for (const s of ["Fix the copy", "docs/prds/login.md"]) expect(noEpic.args).toContain(s);
    expect(noEpic.args).not.toContain("epic");
  });
  it("PRD update args: path first, then the request on one line", () => {
    expect(prdUpdateArgs("docs/prds/x.md", "  rename the title  ")).toBe("docs/prds/x.md — update this PRD: rename the title");
    const multi = prdUpdateArgs("docs/prds/x.md", "first line\nsecond  line\r\n\r\n  third\r\nfourth");
    expect(multi).toBe("docs/prds/x.md — update this PRD: first line second  line third fourth");
    expect(multi).not.toMatch(/[\r\n]/);
  });
  it("unknown feature says so", () => {
    nav("#/features/nope?product=acme/wasensi-docs");
    expect(renderToString(<App />)).toContain("No feature");
  });
});
