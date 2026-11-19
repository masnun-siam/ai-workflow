import { renderToString } from "preact-render-to-string";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiFailure, createClient, isDeclined, type FetchLike } from "./api/client";
import { http, setMapChooser, useMockClient, type MapChoice } from "./api/http";
import type { Action, Product, Session } from "./api/types";
import { mockFetch, resetMock } from "../mock/server";
import { Header } from "./components/Header";
import { RepoMapChoice, stagingMissing } from "./components/Overlays";
import { ProductsPane } from "./screens/settings/Products";
import { runAction } from "./state/actions";
import { loadMany, mutate, products } from "./state/data";
import { chooseRepoMap } from "./state/repoMap";
import { route } from "./state/route";
import { askRepoMap, repoMapReq, toastMsg } from "./state/ui";

type Call = { method: string; path: string; body: unknown };
const res = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const needsMap = (repo = "acme/app") => res(409, { error: "needs a repo map", repo });

/** A fetch that records every call; `answer` gets the call index and may answer it itself. */
function recorder(answer?: (method: string, path: string, n: number) => Response | undefined) {
  const calls: Call[] = [];
  const f: FetchLike = async (input, init) => {
    const method = init?.method ?? "GET";
    const path = String(input);
    calls.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    return answer?.(method, path, calls.length - 1) ?? mockFetch(input, init);
  };
  useMockClient(createClient(f));
  return calls;
}

/** A chooser that always picks `c` and counts how often it was asked. */
function chooser(c: MapChoice) {
  const asked: string[] = [];
  setMapChooser(async (repo) => { asked.push(repo); return c; });
  return asked;
}

const START = { step: "create-prd", repo: "acme/app", guard: true };
const session = (id: string) => res(201, { id, status: "running" });

beforeEach(() => {
  resetMock();
  useMockClient(createClient(mockFetch));
  toastMsg.value = null;
});
afterEach(() => setMapChooser(undefined));

describe("a start that needs a repo map", () => {
  it("monorepo writes the map, then repeats the original start and returns its result", async () => {
    const asked = chooser("monorepo");
    const calls = recorder((m, p, n) => (n === 0 ? needsMap() : p.endsWith("/monorepo") ? res(201, { product: {} }) : n === 2 ? session("s-new") : undefined));
    const s = await http.send<Session>("POST", "/api/sessions", START);
    expect(s.id).toBe("s-new");
    expect(asked).toEqual(["acme/app"]);
    expect(calls).toEqual([
      { method: "POST", path: "/api/sessions", body: START },
      { method: "POST", path: "/api/repos/acme/app/monorepo", body: {} },
      { method: "POST", path: "/api/sessions", body: START },
    ]);
  });

  it("does the same for a dispatch and a rerun", async () => {
    chooser("monorepo");
    const body = { product: "acme/app", issues: [1] };
    let calls = recorder((m, p, n) => (n === 0 ? needsMap() : n === 1 ? res(200, { product: {} }) : res(201, { id: "d1" })));
    expect(await http.send("POST", "/api/dispatches", body)).toEqual({ id: "d1" });
    expect(calls.map((c) => c.path)).toEqual(["/api/dispatches", "/api/repos/acme/app/monorepo", "/api/dispatches"]);
    expect(calls[2]!.body).toEqual(body);
    calls = recorder((m, p, n) => (n === 0 ? needsMap() : n === 1 ? res(200, { product: {} }) : session("s2")));
    await http.send("POST", "/api/sessions/s1/rerun", {});
    expect(calls.map((c) => c.path)).toEqual(["/api/sessions/s1/rerun", "/api/repos/acme/app/monorepo", "/api/sessions/s1/rerun"]);
  });

  it("onboard starts agentic-onboard in the repo and declines the original start", async () => {
    setMapChooser(chooseRepoMap);
    const calls = recorder((m, p, n) => (n === 0 ? needsMap() : n === 1 ? session("s-onb") : undefined));
    const p = http.send("POST", "/api/sessions", START).catch((x: unknown) => x);
    await vi.waitFor(() => expect(repoMapReq.value?.repo).toBe("acme/app"));
    repoMapReq.value!.resolve("onboard");
    const e = await p;
    expect(isDeclined(e)).toBe(true);
    expect(repoMapReq.value).toBeNull();
    expect(calls[1]).toEqual({ method: "POST", path: "/api/sessions", body: { step: "agentic-onboard", repo: "acme/app", guard: true } });
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(2);
    expect(toastMsg.value?.msg).toBe("Started agentic-onboard");
    expect(route.value).toMatchObject({ screen: "activity", id: "s-onb" });
  });

  it("cancel starts nothing more, and mutate and runAction stay quiet", async () => {
    chooser("cancel");
    const calls = recorder((m, p, n) => (n === 0 ? needsMap() : undefined));
    expect(await mutate(() => http.send("POST", "/api/sessions", START), "Started")).toBeUndefined();
    expect(calls).toHaveLength(1);
    expect(toastMsg.value).toBeNull();

    recorder(() => needsMap());
    const toasts: string[] = [];
    const a = { key: "r", label: "Refine", method: "POST", path: "/api/sessions", body: START, toast: "Started refine" } as unknown as Action;
    const ran = await runAction(a, { send: (m, p, b) => http.send(m, p, b), confirm: async () => true, navigate: () => undefined, toast: (m) => toasts.push(m) });
    expect(ran).toBe(false);
    expect(toasts).toEqual([]);
  });

  it("a failed map write is toasted and the start is not repeated", async () => {
    chooser("monorepo");
    const calls = recorder((m, p, n) => (n === 0 ? needsMap() : res(409, { error: "already has a repo map with another entry" })));
    expect(await mutate(() => http.send("POST", "/api/sessions", START), "Started")).toBeUndefined();
    expect(calls.map((c) => c.path)).toEqual(["/api/sessions", "/api/repos/acme/app/monorepo"]);
    expect(toastMsg.value).toMatchObject({ msg: "already has a repo map with another entry", level: "error" });
  });

  it("other errors, other paths, a bad slug and no chooser pass through untouched", async () => {
    const asked = chooser("monorepo");
    const pass = async (r: Response, method: "POST" | "DELETE" = "POST", path = "/api/sessions") => {
      recorder(() => r.clone());
      return http.send(method, path, START).catch((e: unknown) => e as ApiFailure);
    };
    expect(await pass(res(409, { error: "just started", id: "s1", href: "#/sessions/s1" }))).toMatchObject({ status: 409, body: { error: "just started" } });
    expect(await pass(res(400, { error: "bad step" }))).toMatchObject({ status: 400 });
    expect(await pass(needsMap(), "POST", "/api/dispatches/plan")).toMatchObject({ status: 409 });
    expect(await pass(needsMap(), "DELETE", "/api/sessions/s1")).toMatchObject({ status: 409 });
    expect(await pass(needsMap("../../x"))).toMatchObject({ status: 409 });
    expect(asked).toEqual([]);
    setMapChooser(undefined);
    const e = await pass(needsMap());
    expect(isDeclined(e)).toBe(false);
    expect(e).toMatchObject({ status: 409, body: { error: "needs a repo map", repo: "acme/app" } });
  });

  it("against the mock server: an unmapped repo becomes a product, then the PRD session starts", async () => {
    chooser("monorepo");
    await http.send("POST", "/api/repos", { slug: "acme/app", path: "/code/app" });
    const s = await http.send<Session>("POST", "/api/sessions", START);
    expect(s.step).toBe("create-prd");
    await loadMany(["products"]);
    expect(products.value!.find((p) => p.docs_repo === "acme/app")).toMatchObject({ map_committed: false });
    // a second monorepo write on a mapped repo is refused
    await expect(http.send("POST", "/api/repos/acme/app/monorepo", {})).rejects.toMatchObject({ status: 409 });
  });

  it("a second refused start while the choice is open cancels the first", async () => {
    const first = askRepoMap("acme/a");
    const second = askRepoMap("acme/b");
    expect(await first).toBe("cancel");
    expect(repoMapReq.value?.repo).toBe("acme/b");
    repoMapReq.value!.resolve("monorepo");
    expect(await second).toBe("monorepo");
    expect(repoMapReq.value).toBeNull();
  });
});

describe("the monorepo choice dialog", () => {
  const html = (repo: string, noStaging = false) => renderToString(<RepoMapChoice repo={repo} noStaging={noStaging} choose={() => undefined} />);

  it("offers monorepo, onboard and Cancel", () => {
    const h = html("acme/app");
    expect(h).toContain("Use acme/app as a monorepo");
    expect(h).toContain("Run agentic-onboard");
    expect(h).toContain("Cancel");
    expect(h).not.toContain("staging");
  });

  it("a local repo only says to add a remote, with Cancel", () => {
    const h = html("local/x");
    expect(h).toContain("Add a GitHub remote first");
    expect(h).toContain("Cancel");
    expect(h).not.toContain("monorepo<");
    expect(h).not.toContain("Run agentic-onboard");
  });

  it("adds the staging line when the repo has no staging branch", () => {
    expect(html("acme/app", true)).toContain("blubird skills target <code>staging</code> unless the repo's own instructions name another base.");
  });

  it("checks the branches: no staging, staging, and a failed call", async () => {
    recorder(() => res(200, { branches: ["main"], default: "main" }));
    expect(await stagingMissing("acme/app")).toBe(true);
    const calls = recorder(() => res(200, { branches: ["main", "staging"], default: "main" }));
    expect(await stagingMissing("acme/app")).toBe(false);
    expect(calls[0]!.path).toBe("/api/repos/acme/app/branches");
    recorder(() => res(502, { error: "gh failed" }));
    expect(await stagingMissing("acme/app")).toBe(false);
  });
});

describe("Map not committed", () => {
  const withProducts = async (flag: boolean | undefined) => {
    await loadMany(["products", "repos", "settings"]);
    const list = structuredClone(products.value!) as Product[];
    (list[0] as { map_committed?: boolean }).map_committed = flag;
    products.value = list;
  };
  const NOTE = 'title="The first session\'s commit should carry .blubird/repos.json.">Map not committed</span>';

  it("shows in the header and the Settings row while the map is not committed", async () => {
    await withProducts(false);
    expect(renderToString(<Header title="River" products />)).toContain(NOTE);
    expect(renderToString(<ProductsPane />)).toContain(NOTE);
  });

  it("shows for a single product too", async () => {
    await withProducts(false);
    products.value = products.value!.slice(0, 1);
    expect(renderToString(<Header title="River" products />)).toContain(NOTE);
  });

  it("is absent when committed, and when an older server sends no flag", async () => {
    for (const flag of [true, undefined]) {
      await withProducts(flag);
      expect(renderToString(<Header title="River" products />)).not.toContain("Map not committed");
      expect(renderToString(<ProductsPane />)).not.toContain("Map not committed");
    }
  });
});
