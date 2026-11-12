import { renderToString } from "preact-render-to-string";
import { beforeAll, describe, expect, it } from "vitest";
import { createClient } from "./api/client";
import { useMockClient } from "./api/http";
import { mockFetch } from "../mock/server";
import { App } from "./app/App";
import { createRepo, publishRepo } from "./components/Repos";
import { loadMany } from "./state/data";
import { nav } from "./state/route";
import { startReq } from "./state/ui";

describe("repo dialogs and the away summary", () => {
  beforeAll(async () => {
    useMockClient(createClient(mockFetch));
    await loadMany(["status", "repos", "products", "settings", "registry", "inbox", "sessions"]);
  });
  it("inbox shows what Away mode answered and held", () => {
    nav("#/inbox");
    const html = renderToString(<App />);
    for (const s of ["While you were away", "1 answered · 1 held", "Nullable + backfill job", "Recommended", "held", "destructive: held for you", "Change", "Held only"]) expect(html).toContain(s);
  });
  it("create repo dialog", () => {
    createRepo.value = { vault: "05-Work/wasensi/notes-app" };
    const html = renderToString(<App />);
    createRepo.value = null;
    for (const s of ["Create a new repo", "Parent folder", "PRD from the notes vault", "notes-app"]) expect(html).toContain(s);
  });
  it("publish dialog", () => {
    publishRepo.value = "local/notes-app";
    const html = renderToString(<App />);
    publishRepo.value = null;
    expect(html).toContain("Publish local/notes-app to GitHub");
    expect(html).toContain("Private");
  });
  it("start dialog offers creating a repo", () => {
    startReq.value = { step: null, args: "x" };
    const html = renderToString(<App />);
    startReq.value = null;
    expect(html).toContain("Where");
  });
});
