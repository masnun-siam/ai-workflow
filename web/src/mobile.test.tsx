import { renderToString } from "preact-render-to-string";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { createClient } from "./api/client";
import { useMockClient } from "./api/http";
import { mockFetch } from "../mock/server";
import { Rail, Topbar } from "./components/Shell";
import { loadMany } from "./state/data";
import { nav } from "./state/route";
import { narrow, navOpen } from "./state/ui";

describe("phone-width shell", () => {
  beforeAll(async () => {
    useMockClient(createClient(mockFetch));
    await loadMany(["status", "repos", "products", "settings", "registry", "inbox", "sessions"]);
  });
  afterEach(() => { narrow.value = false; navOpen.value = false; });

  it("wide keeps the side rail with its footer", () => {
    const html = renderToString(<Rail />);
    expect(html).not.toContain("menu-btn");
    for (const s of ["Features", "Away mode", "keys"]) expect(html).toContain(s);
  });
  it("narrow is a top bar with the page title and a closed menu", () => {
    nav("#/features");
    narrow.value = true;
    const html = renderToString(<Rail />);
    expect(html).toContain("rail bar");
    expect(html).toContain('class="bar-title"');
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain("Away mode");
  });
  it("the open menu sheet holds the pages and the rail footer", () => {
    narrow.value = true;
    navOpen.value = true;
    const html = renderToString(<Rail />);
    expect(html).toContain("pop sheet");
    for (const s of ["Small changes", "Away mode", "keys", "system"]) expect(html).toContain(s);
  });
  it("the search button has a visible label and an aria-label", () => {
    const html = renderToString(<Topbar />);
    expect(html).toContain('aria-label="Search, jump or run a command"');
    expect(html).toContain("narrow-only");
  });
});
