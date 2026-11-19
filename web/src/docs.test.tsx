import { renderToString } from "preact-render-to-string";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { createClient } from "./api/client";
import { useMockClient } from "./api/http";
import type { BusinessGate } from "./api/types";
import { businessView } from "../mock/fixtures";
import { mockFetch } from "../mock/server";
import { App } from "./app/App";
import { BusinessTab, CollectDocs, DocView, docStepBody } from "./components/BusinessDoc";
import { moduleOrder } from "./screens/Docs";
import { business, load, loadErrors, loadMany, productSel, registry } from "./state/data";
import { nav } from "./state/route";

const PRODUCT = "acme/wasensi-docs";
const gate = (g: Partial<BusinessGate>) => { business.value = { product: PRODUCT, ...businessView, gate: { ...businessView.gate, ...g } }; };
const page = () => { nav("#/docs"); return renderToString(<App />); };

describe("docs page", () => {
  beforeAll(async () => {
    useMockClient(createClient(mockFetch));
    productSel.value = PRODUCT;
    await loadMany(["status", "repos", "products", "settings", "registry", "inbox", "features"]);
    await load("business");
  });
  afterEach(() => { business.value = { product: PRODUCT, ...businessView }; });

  it("groups docs by module with their counts, epics under their own module, Other last", () => {
    const html = page();
    for (const s of ["Module cache", "Module payouts", "Module kyc", "Rate cache", "Cache invalidation", "Payout batches", "Updated 2026-11-10",
      "6 rules", "2 not delivered", "1 partly delivered", "1 planned", "1 open question", "1 drifted", "1 built differently", "4 rules", "2 planned"]) expect(html).toContain(s);
    expect(html.indexOf("Module cache")).toBeLessThan(html.indexOf("Module kyc"));
    expect(html.indexOf("Module kyc")).toBeLessThan(html.indexOf("Module payouts"));
    expect(html).toContain(`href="#/docs/docs%2Fbusiness%2Fcache%2Frates.md?product=${PRODUCT}"`);
    expect(moduleOrder(["other", "billing", "auth", "billing"])).toEqual(["auth", "billing", "other"]);
  });
  it("a doc with an error shows it, no counts, and still links to the reader", () => {
    const html = page();
    const row = /<a class="drow" href="[^"]*statements[^"]*">(.*?)<\/a>/.exec(html)?.[1] ?? "";
    expect(row).toContain("too large");
    expect(row).not.toContain("rule");
  });
  it("validation epic: children with the issue row and the server's Run epic action; not a Feature", () => {
    const html = page();
    for (const s of ["Business validation: Kyc", "#961", "#962", "Ready", "Needs refining", "Start", "Refine", "Run epic"]) expect(html).toContain(s);
    nav("#/features");
    expect(renderToString(<App />)).not.toContain("Business validation");
  });
  it("gate states: pass, fail with every line, unavailable with reason, checking…", () => {
    const pass = page();
    expect(pass).toContain("Gate passes");
    expect(pass).toMatch(/checked \d+m ago/);
    gate({ state: "fail", failures: ["docs/business/cache/rates.md:12: undated Timeline bullet", "docs/business/payouts/batches.md:3: no Updated line"] });
    let html = page();
    for (const s of ["Gate fails", "2 failure lines", "<details", "undated Timeline bullet", "no Updated line"]) expect(html).toContain(s);
    gate({ state: "unavailable", reason: "not checked yet", checked_at: null, running: true });
    html = page();
    for (const s of ["Gate unavailable", "not checked yet", "checking…"]) expect(html).toContain(s);
    expect(html).not.toMatch(/checked \d+m ago/);
    gate({ state: "unavailable", reason: "python3 not found" });
    expect(page()).toContain("python3 not found");
  });
  it("no docs: the empty state names Collect docs", () => {
    business.value = { product: PRODUCT, docs: [], epics: [], gate: { state: "unavailable", failures: [], reason: "no docs/business", checked_at: null, running: false } };
    const html = page();
    expect(html).toContain("No business docs");
    expect(html).toMatch(/<button[^>]*>Collect docs<\/button>/);
    expect(html).not.toMatch(/<button[^>]*disabled[^>]*>Collect docs/);
  });
  it("Collect docs is disabled with a reason when the registry lacks it or marks it unavailable", () => {
    const keep = registry.value;
    try {
      registry.value = keep.filter((s) => s.id !== "collect-docs");
      expect(renderToString(<CollectDocs repo={PRODUCT} />)).toContain("collect-docs is not available yet");
      registry.value = keep.map((s) => (s.id === "collect-docs" ? { ...s, available: false, reason: "needs blubird 1.2.0" } : s));
      const html = renderToString(<CollectDocs repo={PRODUCT} />);
      expect(html).toMatch(/disabled/);
      expect(html).toContain("needs blubird 1.2.0");
    } finally { registry.value = keep; }
  });
  it("an endpoint error (404 before the server has it) shows the banner, no crash", async () => {
    productSel.value = "acme/bop-bd-docs";
    try {
      await load("business");
      expect(loadErrors.value.business).toBeTruthy();
      const html = page();
      expect(html).toContain('class="banner bad"');
      expect(html).toContain("unknown product");
    } finally {
      productSel.value = PRODUCT;
      await load("business");
    }
    expect(loadErrors.value.business).toBeUndefined();
  });
});

describe("doc reader", () => {
  const file = { repo: PRODUCT, path: "docs/business/cache/rates.md", text: "# Rate cache\n\n## Rules\n\nR-1\n\n## Timeline\n\n- planned", sha: "s", branch: "main" };
  it("renders the TOC, path and branch, read-only note and both actions", () => {
    const html = renderToString(<DocView file={file} err="" repo={PRODUCT} path={file.path} />);
    for (const s of ["Table of contents", "Timeline", "docs/business/cache/rates.md", " on main", "read-only", "Refine this doc", "Validate this doc"]) expect(html).toContain(s);
  });
  it("the actions post the step with the doc path", () => {
    expect(docStepBody("refine-docs", PRODUCT, file.path)).toEqual({ step: "refine-docs", repo: PRODUCT, product: PRODUCT, args: file.path, guard: true });
    expect(docStepBody("business-code-validator", PRODUCT, file.path)).toEqual({ step: "business-code-validator", repo: PRODUCT, product: PRODUCT, args: file.path, guard: true });
  });
  it("an unavailable step disables its button with the reason", () => {
    const keep = registry.value;
    try {
      registry.value = keep.map((s) => (s.id === "refine-docs" ? { ...s, available: false, reason: "blubird older than 1.2.0" } : s));
      const html = renderToString(<DocView file={file} err="" repo={PRODUCT} path={file.path} />);
      expect(html).toMatch(/<button[^>]*disabled[^>]*>Refine this doc/);
      expect(html).toContain("blubird older than 1.2.0");
      expect(html).not.toMatch(/<button[^>]*disabled[^>]*>Validate this doc/);
    } finally { registry.value = keep; }
  });
  it("a failed fetch shows the error banner and keeps the page", () => {
    const html = renderToString(<DocView file={null} err="too large" repo={PRODUCT} path={file.path} />);
    expect(html).toContain('class="banner bad"');
    expect(html).toContain("too large");
    expect(html).toContain("Refine this doc");
  });
  it("the full-page route shows the crumb, title and reader", () => {
    nav(`#/docs/${encodeURIComponent(file.path)}?product=${PRODUCT}`);
    const html = renderToString(<App />);
    for (const s of ['href="#/docs"', "Rate cache", "Refine this doc", "Validate this doc"]) expect(html).toContain(s);
  });
  it("the mock answers the reader and its failure paths", async () => {
    const ok = await mockFetch(`/api/business?repo=${PRODUCT}&path=${encodeURIComponent(file.path)}`);
    expect(ok.status).toBe(200);
    expect((await mockFetch(`/api/business?repo=${PRODUCT}&path=docs%2Fbusiness%2Fnope.md`)).status).toBe(404);
    expect((await mockFetch(`/api/business?repo=${PRODUCT}&path=${encodeURIComponent("docs/business/payouts/statements.md")}`)).status).toBe(400);
  });
});

describe("feature Business tab", () => {
  it("lists the feature's docs in order and reads the first inline", () => {
    nav(`#/features/rates?product=${PRODUCT}&tab=business`);
    const html = renderToString(<App />);
    expect(html).toContain('id="tab-business"');
    expect(html.indexOf("cache/rates.md")).toBeLessThan(html.indexOf("payouts/batches.md"));
    expect(html).toContain("Refine this doc");
    expect(html).toContain("Open full page");
  });
  it("no match, or the field absent: the empty state names Collect docs", () => {
    nav(`#/features/batches?product=${PRODUCT}&tab=business`);
    const html = renderToString(<App />);
    expect(html).toContain("No business doc covers this feature yet");
    expect(html).toContain("Collect docs");
    expect(renderToString(<BusinessTab f={{ product: PRODUCT, business: [] }} />)).toContain("No business doc covers this feature yet");
  });
});
