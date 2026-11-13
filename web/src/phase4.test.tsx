import { renderToString } from "preact-render-to-string";
import { beforeAll, describe, expect, it } from "vitest";
import { createClient } from "./api/client";
import { useMockClient } from "./api/http";
import { mockFetch } from "../mock/server";
import { App } from "./app/App";
import { ghTarget, workTarget } from "./components/WorkPanel";
import { loadMany } from "./state/data";
import { nav, parseHash } from "./state/route";

describe("small changes, dispatch page, issue/PR panel", () => {
  beforeAll(async () => {
    useMockClient(createClient(mockFetch));
    await loadMany(["status", "repos", "products", "settings", "registry", "inbox", "dispatches", "grinds", "sessions"]);
    await loadMany(["changes"]);
  });
  it("small changes: matrix, ready to run, needs refining, all issues", () => {
    nav("#/changes");
    const html = renderToString(<App />);
    for (const s of ["Where they stand", "ready to run · 2", "as a dispatch", "needs refining first · 1", "other issues · 1", "Typo on the payouts page", "P1"]) expect(html.toLowerCase()).toContain(s.toLowerCase());
  });
  it("routes and renders a dispatch page with lanes and activity", () => {
    expect(parseHash("#/dispatches/d1a2b3c4d5e6?lane=x")).toMatchObject({ screen: "dispatches", id: "d1a2b3c4d5e6", query: { lane: "x" } });
    nav("#/dispatches/d1a2b3c4d5e6?lane=acme/wasensi-backend%23942");
    const html = renderToString(<App />);
    for (const s of ["Courier rate cache", "Building now", "Up next", "Pause", "Cancel", "Settings", "lane · wasensi-backend#942", "Message the lane", "activity"]) expect(html).toContain(s);
  });
  it("a lane stranded behind a skipped one is called out with retry and unblock", () => {
    nav("#/dispatches/d1a2b3c4d5e6?lane=acme/wasensi-backend%23945");
    const html = renderToString(<App />);
    for (const s of ["Can't start", "skipped #944", "0/5 · 1 skipped", "Run #944 again", "Unblock them", "Unblock: start without it", "Skipped · 1"]) expect(html).toContain(s);
    nav("#/dispatches/d1a2b3c4d5e6?lane=acme/wasensi-backend%23944");
    const sk = renderToString(<App />);
    expect(sk).toContain("Run it again");
    expect(sk).toContain("1 issue waits on it");
    expect(sk).not.toContain("Message the lane");
  });
  it("the dispatch list is a table that opens the page", () => {
    nav("#/dispatches");
    const html = renderToString(<App />);
    expect(html).toContain('href="#/dispatches/d1a2b3c4d5e6"');
    expect(html).toContain("Run an epic");
  });
  it("small-change picks prefill a run-small-changes form", () => {
    nav("#/dispatches?new=acme/wasensi-backend%231051,%20acme/wasensi-backend%231052");
    const html = renderToString(<App />);
    expect(html).toContain("run small changes");
    expect(html).toContain("Base branch");
  });
  it("maps GitHub links of registered repos to the panel", () => {
    expect(ghTarget("https://github.com/acme/wasensi-backend/issues/1044")).toEqual({ kind: "issue", repo: "acme/wasensi-backend", n: 1044 });
    expect(ghTarget("https://github.com/ACME/wasensi-backend/pull/1060#discussion")).toEqual({ kind: "pr", repo: "acme/wasensi-backend", n: 1060 });
    expect(ghTarget("https://github.com/someone/else/issues/1")).toBeNull();
    expect(ghTarget("https://github.com/acme/wasensi-backend/actions/runs/1")).toBeNull();
  });
  it("renders the panel shell for an issue", () => {
    nav("#/changes");
    workTarget.value = { kind: "issue", repo: "acme/wasensi-backend", n: 1044 };
    const html = renderToString(<App />);
    workTarget.value = null;
    expect(html).toContain("Open on GitHub");
    expect(html).toContain("Loading from GitHub");
  });
});
