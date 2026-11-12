import { renderToString } from "preact-render-to-string";
import { beforeAll, describe, expect, it } from "vitest";
import { createClient } from "./api/client";
import { useMockClient } from "./api/http";
import { mockFetch } from "../mock/server";
import { App } from "./app/App";
import { likelyDuplicate } from "./components/Start";
import { loadMany, registry } from "./state/data";
import { nav } from "./state/route";
import { createDraft, createOpen, startReq } from "./state/ui";

const it_ = (number: number, title: string) => ({ number, title, labels: [], updated_at: "", draft: false });

describe("duplicate hint", () => {
  const open = [it_(1044, "CSV export drops the VAT column"), it_(1013, "Batch scheduler")];
  it("matches an issue that shares most words", () => {
    expect(likelyDuplicate("The CSV export drops VAT for some merchants", open)?.number).toBe(1044);
  });
  it("needs at least two shared words", () => {
    expect(likelyDuplicate("Rework the batch payouts screen layout", open)).toBeNull();
    expect(likelyDuplicate("hi", open)).toBeNull();
  });
});

describe("create box and start dialog render", () => {
  beforeAll(async () => {
    useMockClient(createClient(mockFetch));
    await loadMany(["status", "repos", "products", "settings", "registry", "inbox"]);
    nav("#/inbox");
  });
  it("create box: feature and small change routes, repo field, accounts", () => {
    createDraft.value = "Let merchants download a monthly statement";
    createOpen.value = true;
    const html = renderToString(<App />);
    createOpen.value = false;
    expect(html).toContain("What should change?");
    expect(html).toContain("Start the PRD interview");
    expect(html).toContain("Small change");
    expect(html).toContain("Run on");
    expect(html).toContain("Run a command instead");
  });
  it("start dialog: grouped commands, where, model and effort", () => {
    startReq.value = { step: registry.value.find((s) => s.id === "implement-issue")!, repo: "acme/wasensi-backend" };
    const html = renderToString(<App />);
    startReq.value = null;
    for (const s of ["Plan", "Build", "Review", "Ship", "Custom prompt", "Where", "Model", "Effort", "Make these the default", "Implement issue"]) expect(html).toContain(s);
  });
  it("start dialog: a custom prompt offers the notes vault and another folder", () => {
    startReq.value = { step: null, args: "summarise the logs" };
    const html = renderToString(<App />);
    startReq.value = null;
    expect(html).toContain("A custom prompt runs headless");
    expect(html).toContain("Prompt");
  });
});
