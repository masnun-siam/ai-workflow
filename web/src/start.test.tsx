import { renderToString } from "preact-render-to-string";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { createClient } from "./api/client";
import { useMockClient } from "./api/http";
import { mockFetch } from "../mock/server";
import { App } from "./app/App";
import { applyJev, argLength, askJev, createArgs, createBody, jevLine, likelyDuplicate } from "./components/Start";
import { loadMany, registry } from "./state/data";
import { nav } from "./state/route";
import { createDraft, createJevPick, createOpen, createRoute, createRouteTouched, openCreate, startReq } from "./state/ui";

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

describe("create box routes", () => {
  const common = { repo: "acme/wasensi-backend" };
  it("builds each route's argument", () => {
    expect(createArgs("feature", "  Monthly statement \n", "P1", "Staging")).toBe("Monthly statement");
    expect(createArgs("small", "Fix the typo", "P3", "Staging")).toBe("Fix the typo\n\nPriority: P3");
    expect(createArgs("bug", "Login 500s after upgrade", "P1", "Staging")).toBe("Login 500s after upgrade\n\nPriority: P1\nEnvironment: Staging");
  });
  it("builds each route's request body; only model and effort per request", () => {
    expect(createBody("bug", createArgs("bug", "Login 500s after upgrade", "P1", "Staging"), common, ["security"])).toEqual({
      step: "report-bug", args: "Login 500s after upgrade\n\nPriority: P1\nEnvironment: Staging", model: "opus", effort: "high", repo: "acme/wasensi-backend",
    });
    expect(createBody("small", "x\n\nPriority: P2", common, ["security"])).toEqual({ step: "small-change", args: "x\n\nPriority: P2", repo: "acme/wasensi-backend" });
    expect(createBody("feature", "x", common, ["security"])).toEqual({ step: "create-prd", args: "x", lenses: ["security"], model: "opus", effort: "medium", repo: "acme/wasensi-backend" });
    expect(createBody("feature", "x", common, []).lenses).toBeUndefined();
  });
  it("counts code points, not UTF-16 units", () => {
    expect(argLength("a🐛b")).toBe(3);
  });
});

describe("create box: bug route and the length cap", () => {
  beforeAll(async () => {
    useMockClient(createClient(mockFetch));
    await loadMany(["status", "repos", "products", "settings", "registry", "inbox"]);
    nav("#/inbox");
  });
  afterEach(() => {
    createRoute.value = "feature";
    createDraft.value = "";
    createOpen.value = false;
  });
  const render = () => {
    createOpen.value = true;
    const html = renderToString(<App />);
    createOpen.value = false;
    return html;
  };
  it("bug route: three routes in order, priority, environment and its submit label", () => {
    createDraft.value = "Login 500s after upgrade";
    createRoute.value = "bug";
    const html = render();
    const at = ["Feature", "Small change", "Bug"].map((l) => html.indexOf(`<b>${l}</b>`));
    expect(at.every((i) => i >= 0)).toBe(true);
    expect([...at].sort((a, b) => a - b)).toEqual(at);
    expect(html).toContain("reproduce it, then file and refine");
    for (const s of ["Priority", "P2", "Environment", "Unknown", "Reproduce the bug"]) expect(html).toContain(s);
    expect(html).not.toContain("Review the PRD with");
  });
  it("counter hidden at 18,000, shown past it, submit blocked past 20,000", () => {
    createDraft.value = "x".repeat(18000);
    expect(render()).not.toContain("/ 20,000");
    createDraft.value = "x".repeat(18001);
    let html = render();
    expect(html).toContain("18,001 / 20,000");
    expect(html).not.toMatch(/<button[^>]*disabled[^>]*>Start the PRD interview/);
    createDraft.value = "x".repeat(20001);
    html = render();
    expect(html).toContain("20,001 / 20,000");
    expect(html).toMatch(/<button[^>]*disabled[^>]*>Start the PRD interview/);
  });
  it("the count includes the lines a route adds", () => {
    createRoute.value = "bug";
    createDraft.value = "x".repeat(19990);
    const html = render();
    expect(html).toContain(`${(19990 + "\n\nPriority: P2\nEnvironment: Unknown".length).toLocaleString("en-US")} / 20,000`);
    expect(html).toMatch(/<button[^>]*disabled[^>]*>Reproduce the bug/);
  });
  it("whitespace-only text cannot be submitted", () => {
    createDraft.value = "   \n ";
    expect(render()).toMatch(/<button[^>]*disabled[^>]*>Start the PRD interview/);
  });
  it("opening with an empty draft starts on Feature; a kept draft keeps the route", () => {
    createRoute.value = "bug";
    createDraft.value = "Login 500s";
    openCreate();
    expect(createRoute.value).toBe("bug");
    createDraft.value = "";
    openCreate();
    expect(createRoute.value).toBe("feature");
    createRoute.value = "bug";
    openCreate("Add a CSV export");
    expect(createRoute.value).toBe("feature");
    expect(createDraft.value).toBe("Add a CSV export");
  });
  it("small change: the count includes the priority line", () => {
    createRoute.value = "small";
    createDraft.value = "x".repeat(19990);
    const html = render();
    expect(html).toContain("20,004 / 20,000");
    expect(html).toMatch(/<button[^>]*disabled[^>]*>File the issue/);
  });
});

describe("create box: jev preselects the route", () => {
  beforeAll(async () => {
    useMockClient(createClient(mockFetch));
    await loadMany(["status", "repos", "products", "settings", "registry", "inbox"]);
    nav("#/inbox");
  });
  afterEach(() => {
    createRoute.value = "feature";
    createDraft.value = "";
    createOpen.value = false;
    createRouteTouched.value = false;
    createJevPick.value = null;
    useMockClient(createClient(mockFetch));
  });
  const sent = "The export crashes with a 500 on save";
  const bug = { route: "bug" as const, p: 0.82, status: "ok" };
  const render = () => {
    createOpen.value = true;
    const html = renderToString(<App />);
    createOpen.value = false;
    return html;
  };
  it("an answer for the current text, route untouched, is a pick", () => {
    expect(applyJev(bug, sent, sent, false)).toEqual({ route: "bug", p: 0.82 });
  });
  it("a touched route, a changed text or no answer is ignored", () => {
    expect(applyJev(bug, sent, sent, true)).toBeNull();
    expect(applyJev(bug, sent, `${sent} and more`, false)).toBeNull();
    expect(applyJev({ route: null, p: null, status: "off" }, sent, sent, false)).toBeNull();
    expect(applyJev({ route: null, p: null, status: "unsure" }, sent, sent, false)).toBeNull();
  });
  it("names each route in the jev line", () => {
    expect(jevLine({ route: "bug", p: 0.82 })).toBe("jev: bug · 82%");
    expect(jevLine({ route: "feature", p: 0.4 })).toBe("jev: feature · 40%");
    expect(jevLine({ route: "small", p: 0.667 })).toBe("jev: small change · 67%");
  });
  it("shows the jev line for its own pick, hides it once the user picked", () => {
    createDraft.value = sent;
    createRoute.value = "bug";
    createJevPick.value = { route: "bug", p: 0.82 };
    expect(render()).toContain("jev: bug · 82%");
    createRouteTouched.value = true;
    expect(render()).not.toContain("jev: bug");
  });
  it("no pick, no line", () => {
    createDraft.value = sent;
    expect(render()).not.toContain("jev:");
  });
  it("a kept draft keeps the pick and the touched flag; an empty draft clears both", () => {
    createDraft.value = sent;
    createRoute.value = "bug";
    createJevPick.value = { route: "bug", p: 0.82 };
    createRouteTouched.value = true;
    openCreate();
    expect([createRoute.value, createRouteTouched.value, createJevPick.value]).toEqual(["bug", true, { route: "bug", p: 0.82 }]);
    createDraft.value = "";
    openCreate();
    expect([createRoute.value, createRouteTouched.value, createJevPick.value]).toEqual(["feature", false, null]);
  });
  it("asks jev and applies a bug answer for the current text", async () => {
    createDraft.value = sent;
    await askJev(sent);
    expect([createRoute.value, createJevPick.value]).toEqual(["bug", { route: "bug", p: 0.82 }]);
  });
  it("a jev answer after the user picked, or for older text, changes nothing", async () => {
    createDraft.value = sent;
    createRoute.value = "feature";
    createRouteTouched.value = true;
    await askJev(sent);
    expect([createRoute.value, createJevPick.value]).toEqual(["feature", null]);
    createRouteTouched.value = false;
    createDraft.value = `${sent} when the file is big`;
    await askJev(sent);
    expect([createRoute.value, createJevPick.value]).toEqual(["feature", null]);
  });
  it("jev unsure or a failed request keeps Feature, with no error", async () => {
    createDraft.value = "Let merchants download a monthly statement";
    await askJev(createDraft.value);
    expect([createRoute.value, createJevPick.value]).toEqual(["feature", null]);
    useMockClient(createClient(async () => new Response(JSON.stringify({ error: "boom" }), { status: 500 })));
    createDraft.value = sent;
    await expect(askJev(sent)).resolves.toBeUndefined();
    expect([createRoute.value, createJevPick.value]).toEqual(["feature", null]);
  });
  it("new text from the palette clears the pick and the touched flag", () => {
    createDraft.value = sent;
    createJevPick.value = { route: "bug", p: 0.82 };
    createRouteTouched.value = true;
    openCreate("Add a CSV export");
    expect([createRoute.value, createRouteTouched.value, createJevPick.value]).toEqual(["feature", false, null]);
  });
});
