import { renderToString } from "preact-render-to-string";
import { beforeAll, describe, expect, it } from "vitest";
import { createClient } from "./api/client";
import { useMockClient } from "./api/http";
import { mockFetch } from "../mock/server";
import { App } from "./app/App";
import { loadMany } from "./state/data";
import { parseHash, nav } from "./state/route";

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
  it("unknown feature says so", () => {
    nav("#/features/nope?product=acme/wasensi-docs");
    expect(renderToString(<App />)).toContain("No feature");
  });
});
