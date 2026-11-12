import { describe, expect, it, vi } from "vitest";
import type { Action, Round } from "../api/types";
import { ApiFailure } from "../api/client";
import { runAction, type ActionDeps } from "./actions";
import { buildAnswers, canSubmit, emptyDraft, quickOptions, toggleLabel } from "./answer";
import { resolveKey, type KeyCtx } from "./keymap";
import { DEFAULT_PREFS, loadPrefs, next, sanitize, savePrefs } from "./prefs";
import { refetchFor, visibleKeys } from "./refetch";
import { parseHash } from "./route";

const act = (p: Partial<Action> = {}): Action => ({ key: "e", label: "Go", method: "POST", path: "/api/x", toast: "Done", ...p });
const deps = (o: Partial<ActionDeps> = {}) => {
  const d = { send: vi.fn(async () => ({})), confirm: vi.fn(async () => true), navigate: vi.fn(), toast: vi.fn(), onClears: vi.fn(), after: vi.fn(), ...o };
  return d as typeof d & ActionDeps;
};

describe("action runner", () => {
  it("sends, toasts, clears and refetches", async () => {
    const d = deps();
    expect(await runAction(act({ body: { a: 1 }, clears: true }), d)).toBe(true);
    expect(d.send).toHaveBeenCalledWith("POST", "/api/x", { a: 1 });
    expect(d.toast).toHaveBeenCalledWith("Done");
    expect(d.onClears).toHaveBeenCalled();
    expect(d.after).toHaveBeenCalled();
  });
  it("asks first when confirm is set and stops on no", async () => {
    const d = deps({ confirm: vi.fn(async () => false) });
    expect(await runAction(act({ confirm: "Sure?" }), d)).toBe(false);
    expect(d.confirm).toHaveBeenCalledWith("Sure?");
    expect(d.send).not.toHaveBeenCalled();
  });
  it("navigates instead of fetching for open", async () => {
    const d = deps();
    await runAction(act({ open: "#/sessions/x" }), d);
    expect(d.navigate).toHaveBeenCalledWith("#/sessions/x");
    expect(d.send).not.toHaveBeenCalled();
  });
  it("shows the server error and does not clear", async () => {
    const d = deps({ send: vi.fn(async () => { throw new ApiFailure(409, { error: "blocked by #1" }); }) });
    expect(await runAction(act({ clears: true }), d)).toBe(false);
    expect(d.toast).toHaveBeenCalledWith("blocked by #1", "error");
    expect(d.onClears).not.toHaveBeenCalled();
  });
});

describe("SSE refetch map (API.md section 6)", () => {
  const river = { screen: "river" };
  it("hello refetches everything visible", () => {
    expect(refetchFor("hello", {}, river)).toEqual(expect.arrayContaining(["status", "inbox", "river"]));
    expect(refetchFor("hello", {}, { screen: "runs", runsTab: "dispatch" })).toContain("dispatches");
  });
  it("sessions: list always, river/me when shown, stream only for the open session", () => {
    expect(refetchFor("sessions", { id: "a", change: "record" }, river)).toEqual(expect.arrayContaining(["river"]));
    expect(refetchFor("sessions", { id: "a", change: "record" }, { screen: "me" })).toContain("me");
    const v = { screen: "runs", sessionId: "a", runsTab: "sessions" };
    expect(refetchFor("sessions", { id: "a", change: "stream" }, v)).toEqual(expect.arrayContaining(["sessions", "session", "stream"]));
    expect(refetchFor("sessions", { id: "b", change: "stream" }, v)).not.toContain("stream");
  });
  it("inbox, dispatch, usage, products kinds, toast", () => {
    expect(refetchFor("inbox", { count: 1 }, river)).toEqual(["inbox"]);
    expect(refetchFor("dispatch", { id: "x" }, { screen: "runs", runsTab: "dispatch" })).toEqual(["dispatches"]);
    expect(refetchFor("usage", { kind: "away" }, river)).toEqual(["status"]);
    expect(refetchFor("usage", { kind: "settings" }, { screen: "settings" })).toEqual(expect.arrayContaining(["status", "settings", "notify"]));
    expect(refetchFor("products", { kind: "release" }, { screen: "releases" })).toEqual(["releases"]);
    expect(refetchFor("products", { kind: "blubird" }, { screen: "settings" })).toEqual(expect.arrayContaining(["blubird", "status"]));
    expect(refetchFor("products", { kind: "coordinator" }, { screen: "runs", runsTab: "coordinators" })).toEqual(["coordinators"]);
    expect(refetchFor("products", { kind: "coordinator" }, river)).toEqual([]);
    expect(refetchFor("toast", { id: 1 }, river)).toEqual([]);
  });
  it("visible keys per screen", () => {
    expect(visibleKeys({ screen: "ops" })).toContain("ops");
    expect(visibleKeys({ screen: "runs", sessionId: "s" })).toEqual(expect.arrayContaining(["session", "stream"]));
  });
});

describe("keyboard map", () => {
  const ctx = (o: Partial<KeyCtx> = {}): KeyCtx => ({ screen: "river", overlay: false, actions: [act({ key: "e" })], quickOptions: 0, nav: "river", ...o });
  const k = (key: string, o = {}, c = ctx()) => resolveKey({ key, ...o }, c);
  it("screens 1-7", () => {
    expect(k("1")).toEqual({ t: "go", screen: "river" });
    expect(k("7")).toEqual({ t: "go", screen: "settings" });
    expect(k("3")).toEqual({ t: "go", screen: "runs" });
  });
  it("palette, help, escape, mode, look, layout", () => {
    expect(k(":")).toEqual({ t: "palette" });
    expect(k("k", { meta: true })).toEqual({ t: "palette" });
    expect(k("k", { ctrl: true })).toEqual({ t: "palette" });
    expect(k("?")).toEqual({ t: "help" });
    expect(k("Escape")).toEqual({ t: "escape" });
    expect(k(".")).toEqual({ t: "mode" });
    expect(k("s")).toEqual({ t: "look" });
    expect(k("L")).toEqual({ t: "layout" });
  });
  it("hjkl and arrows move; river has h/l, lists do not", () => {
    expect(k("h")).toEqual({ t: "move", dx: -1, dy: 0 });
    expect(k("j")).toEqual({ t: "move", dx: 0, dy: 1 });
    expect(k("ArrowUp")).toEqual({ t: "move", dx: 0, dy: -1 });
    expect(k("h", {}, ctx({ nav: "list" }))).toEqual({ t: "screen", key: "h" });
    expect(k("Enter")).toEqual({ t: "enter" });
  });
  it("a/b/c answer only when options exist; action keys run", () => {
    expect(k("b", {}, ctx({ quickOptions: 3 }))).toEqual({ t: "answer", index: 1 });
    expect(k("c", {}, ctx({ quickOptions: 2 }))).toEqual({ t: "screen", key: "c" });
    expect(k("e")).toEqual({ t: "action", key: "e" });
  });
  it("typing and overlays swallow keys except esc and cmd-k", () => {
    expect(k("j", { typing: true })).toBeNull();
    expect(k("Escape", { typing: true })).toEqual({ t: "escape" });
    expect(k("1", {}, ctx({ overlay: true }))).toBeNull();
    expect(k("k", { meta: true, typing: true })).toEqual({ t: "palette" });
    expect(k("x", { meta: true })).toBeNull();
  });
  it("screen keys pass through (releases)", () => {
    expect(k("p", {}, ctx({ screen: "releases", nav: null, actions: [] }))).toEqual({ t: "screen", key: "p" });
  });
});

const round = (multi: boolean, n = 1): Round => ({ id: "r", status: "pending", allowFreeText: true, questions: Array.from({ length: n }, () => ({
  header: "h", question: "q", multiSelect: multi, allowFreeText: true, recommended: null, options: [{ label: "A", description: "" }, { label: "B", description: "" }] })) });
describe("answers", () => {
  it("single select replaces, multi toggles", () => {
    let d = emptyDraft(round(false))[0]!;
    d = toggleLabel(d, "A", false); d = toggleLabel(d, "B", false);
    expect(d.labels).toEqual(["B"]);
    let m = emptyDraft(round(true))[0]!;
    m = toggleLabel(toggleLabel(m, "A", true), "B", true);
    expect(m.labels).toEqual(["A", "B"]);
    expect(toggleLabel(m, "A", true).labels).toEqual(["B"]);
  });
  it("builds the Answers shape; free text wins; unanswered blocks submit", () => {
    const ds = emptyDraft(round(false, 2));
    expect(canSubmit(ds)).toBe(false);
    expect(buildAnswers(ds)).toBeNull();
    ds[0] = { labels: ["A"], other: "" };
    ds[1] = { labels: ["B"], other: " custom " };
    expect(buildAnswers(ds)).toEqual({ "0": { labels: ["A"] }, "1": { other: "custom" } });
  });
  it("quick options only for one single-select question", () => {
    expect(quickOptions(round(false))).toEqual(["A", "B"]);
    expect(quickOptions(round(true))).toEqual([]);
    expect(quickOptions(round(false, 2))).toEqual([]);
    expect(quickOptions(null)).toEqual([]);
  });
});

describe("prefs and routes", () => {
  it("defaults are Console + drawer + System; bad values fall back", () => {
    expect(DEFAULT_PREFS).toEqual({ look: "console", mode: "system", layout: "drawer" });
    expect(sanitize({ look: "x", mode: "dark" })).toEqual({ look: "console", mode: "dark", layout: "drawer" });
  });
  it("storage that throws never breaks", () => {
    const bad = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
    expect(loadPrefs(bad)).toEqual(DEFAULT_PREFS);
    expect(() => savePrefs(DEFAULT_PREFS, bad)).not.toThrow();
  });
  it("round-trips and cycles", () => {
    const mem = new Map<string, string>();
    const s = { getItem: (k: string) => mem.get(k) ?? null, setItem: (k: string, v: string) => void mem.set(k, v) };
    savePrefs({ look: "river", mode: "light", layout: "split" }, s);
    expect(loadPrefs(s)).toEqual({ look: "river", mode: "light", layout: "split" });
    expect(next(["system", "dark", "light"], "light")).toBe("system");
  });
  it("parses hashes", () => {
    expect(parseHash("#/inbox").screen).toBe("inbox");
    expect(parseHash("#/sessions/abc")).toMatchObject({ screen: "runs", id: "abc" });
    expect(parseHash("#/prd?repo=a/b&path=docs/x.md")).toMatchObject({ screen: "prd", query: { repo: "a/b", path: "docs/x.md" } });
    expect(parseHash("")).toMatchObject({ screen: "river" });
  });
});
