import { renderToString } from "preact-render-to-string";
import { beforeAll, describe, expect, it } from "vitest";
import { createClient } from "./api/client";
import { useMockClient } from "./api/http";
import { mockFetch } from "../mock/server";
import type { FeatureIssue, FeatureIssueState, InboxItem } from "./api/types";
import { App } from "./app/App";
import { Changes } from "./screens/Changes";
import { closeOnEscape } from "./components/Shell";
import { headings } from "./components/Markdown";
import { changes, inbox, loadMany } from "./state/data";
import { displayTitle, typeLabel } from "./state/inboxView";
import { inboxAll, inboxItems, inboxQuery } from "./state/select";
import { nav } from "./state/route";

const issue = (n: number, state: FeatureIssueState, priority: string | null = "P1"): FeatureIssue => ({
  key: `acme/api#${n}`, repo: "acme/api", n, title: `Issue ${n}`, url: `https://github.com/acme/api/issues/${n}`, state, refined: state !== "unrefined",
  bug: false, blockers: [], priority, pr: null, session: null, actions: [],
});
const row = (key: string, kind: string, type: InboxItem["type"], group: InboxItem["group"]): InboxItem =>
  ({ key, group, type, kind, title: `${kind} ${key}`, repo: "acme/api", at: null, urgency: null, links: {}, actions: [] });

describe("small changes at scale", () => {
  const states: FeatureIssueState[] = ["ready", "unrefined", "blocked", "in_progress"];
  it("renders at most 50 rows per section for 1,000 issues and never lists an issue twice", () => {
    changes.value = { stale: [], pending: [], issues: Array.from({ length: 1000 }, (_, i) => issue(i + 1, states[i % 4]!)) };
    const html = renderToString(<Changes />);
    for (const sec of html.split("<section").slice(1)) expect((sec.match(/class="irow"/g) ?? []).length).toBeLessThanOrEqual(50);
    const ids = [...html.matchAll(/>api#(\d+)</g)].map((m) => m[1]);
    expect(ids.length).toBeGreaterThan(0);
    expect(new Set(ids).size).toBe(ids.length);
    expect(html).toContain("Show all 250");
    expect(html).toContain("Pick first 30 of 250");
  });
  it("hides the matrix with one priority bucket and labels columns when shown", () => {
    changes.value = { stale: [], pending: [], issues: [issue(1, "ready"), issue(2, "blocked")] };
    expect(renderToString(<Changes />)).not.toContain("where they stand");
    changes.value = { stale: [], pending: [], issues: [issue(1, "ready", "P0"), issue(2, "blocked", "P2")] };
    expect(renderToString(<Changes />)).toContain('<th scope="col">Priority</th>');
  });
  it("reads cleanly with nothing picked", () => {
    changes.value = { stale: [], pending: [], issues: [issue(1, "ready")] };
    const html = renderToString(<Changes />);
    expect(html).toContain("Run as a dispatch");
    expect(html).toContain("Pick all 1");
  });
});

describe("inbox", () => {
  it("shows a derived title for a failed session and keeps the prompt for the drawer", () => {
    const it = { ...row("failed:1", "Failed", "session_failed", "fix"), title: "/blubird:implement-issue 73 — a very long raw prompt", detail: ["boom", "step implement-issue"], links: { issue: "https://github.com/acme/api/issues/73" } };
    expect(displayTitle(it)).toBe("implement-issue #73 failed");
    expect(typeLabel("review_approved")).toBe("Review approved");
  });
  it("groups by kind and collapses Conflict after 5 rows", () => {
    inbox.value = { stale: [], count: 9, items: [
      ...Array.from({ length: 8 }, (_, i) => row(`c${i}`, "Conflict", "pr_conflict", "fix")),
      row("a", "Approval", "prd_approval", "decide"), row("g", "Grind paused", "grind_paused", "fix")] };
    inboxQuery.value = "";
    expect(inboxAll.value).toHaveLength(10);
    expect(inboxItems.value.filter((i) => i.kind === "Conflict")).toHaveLength(5);
    inboxQuery.value = "conflict";
    expect(inboxItems.value).toHaveLength(8);
    inboxQuery.value = "";
  });
});

describe("feature page and PRD view", () => {
  beforeAll(async () => {
    useMockClient(createClient(mockFetch));
    await loadMany(["status", "repos", "products", "settings", "registry", "inbox", "panels"]);
    await loadMany(["features"]);
  });
  it("closes a popover on Escape without letting the key travel on", () => {
    let open = true, stopped = false;
    const e = { key: "Escape", stopPropagation: () => { stopped = true; }, preventDefault: () => undefined };
    expect(closeOnEscape(e, (v) => { open = v; })).toBe(true);
    expect(open).toBe(false);
    expect(stopped).toBe(true);
    expect(closeOnEscape({ ...e, key: "a" }, (v) => { open = v; })).toBe(false);
  });
  it("More menu and tabs carry their ARIA", () => {
    nav("#/features/rates?product=acme/wasensi-docs");
    const html = renderToString(<App />);
    expect(html).toMatch(/aria-haspopup="menu"[^>]*aria-expanded="false"|aria-expanded="false"[^>]*aria-haspopup="menu"/);
    expect(html).toContain('role="tabpanel"');
    expect(html).toContain('aria-controls="feature-panel"');
    expect(html).toContain('tabindex="-1"');
    expect(html).toContain('aria-current="step"');
  });
  it("the PRD view without a query says so", () => {
    nav("#/prd");
    const html = renderToString(<App />);
    expect(html).toContain("No PRD selected");
    expect(html).toContain('href="#/features"');
  });
  it("builds a table of contents from headings outside code fences", () => {
    expect(headings("# A\n```\n# not\n```\n## B\n## B")).toEqual([
      { level: 1, text: "A", id: "a" }, { level: 2, text: "B", id: "b" }, { level: 2, text: "B", id: "b-1" }]);
  });
});
