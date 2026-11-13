import { renderToString } from "preact-render-to-string";
import { beforeAll, beforeEach, describe, expect, it } from "vitest";
import { createClient } from "./api/client";
import { useMockClient } from "./api/http";
import { mockFetch } from "../mock/server";
import { App } from "./app/App";
import { parentScreen, runCommand } from "./app/commands";
import { Palette, matchPages } from "./components/Overlays";
import { loadMany } from "./state/data";
import type { LoadKey } from "./state/refetch";
import { hintsFor, resolveKey, type KeyCtx } from "./state/keymap";
import { closeTopLayer, layerCount, overlayOpen, pushLayer } from "./state/layers";
import { nav, parseHash, route } from "./state/route";
import { askConfirm, confirmReq, paletteOpen, toastMs } from "./state/ui";

const ALL: LoadKey[] = ["status", "river", "inbox", "sessions", "releases", "ops", "me", "settings", "notify", "review", "blubird", "products", "repos", "dispatches", "coordinators", "grinds", "panels", "registry"];

beforeAll(async () => {
  useMockClient(createClient(mockFetch));
  await loadMany(ALL);
});
/** A layer that unmounts itself when closed, as a dialog does. */
function layer(onClose: () => void = () => {}, modal = true): () => void {
  const off = pushLayer(() => { onClose(); off(); }, modal);
  return off;
}
beforeEach(() => { while (closeTopLayer()) { /* drop layers left by a test */ } });

const ctx = (o: Partial<KeyCtx> = {}): KeyCtx => ({ screen: "inbox", overlay: overlayOpen(), actions: [], quickOptions: 0, nav: "list", ...o });

describe("Escape", () => {
  it.each([
    ["#/features/payouts?product=o/r", "features"],
    ["#/dispatches/d1", "dispatches"],
    ["#/sessions/s1", "activity"],
    ["#/prd?repo=a/b&path=x.md", "features"],
  ])("goes from %s to the parent screen %s", (hash, parent) => {
    nav(hash);
    expect(parentScreen()).toBe(parent);
    runCommand({ t: "escape" });
    expect(route.value.screen).toBe(parent);
    expect(route.value.id).toBeUndefined();
  });

  it("does nothing on a top-level screen", () => {
    nav("#/settings");
    expect(parentScreen()).toBeNull();
    runCommand({ t: "escape" });
    expect(route.value.screen).toBe("settings");
  });

  it("closes the top layer first and only then goes back", () => {
    nav("#/features/payouts");
    const closed: string[] = [];
    layer(() => closed.push("drawer"), false);
    layer(() => closed.push("popover"));
    expect(closeTopLayer()).toBe(true);
    expect(closed).toEqual(["popover"]);
    expect(closeTopLayer()).toBe(true);
    expect(closed).toEqual(["popover", "drawer"]);
    expect(closeTopLayer()).toBe(false);
  });
});

describe("global keys under dialogs", () => {
  it("ignores n, digits and cmd-k while a dialog or popover is open, but not Escape", () => {
    expect(resolveKey({ key: "n" }, ctx())).toEqual({ t: "new" });
    const off = layer();
    expect(overlayOpen()).toBe(true);
    expect(resolveKey({ key: "n" }, ctx())).toBeNull();
    expect(resolveKey({ key: "2" }, ctx())).toBeNull();
    expect(resolveKey({ key: "k", meta: true }, ctx())).toBeNull();
    expect(resolveKey({ key: "Escape" }, ctx())).toEqual({ t: "escape" });
    off();
    expect(layerCount()).toBe(0);
    expect(resolveKey({ key: "n" }, ctx())).toEqual({ t: "new" });
  });

  it("keeps global keys on for a non-modal layer such as the detail drawer", () => {
    const off = layer(() => {}, false);
    expect(overlayOpen()).toBe(false);
    off();
  });
});

describe("routing", () => {
  it("sends a malformed or unknown hash to the inbox without throwing", () => {
    expect(parseHash("#/sessions/%E0%A4%A").screen).toBe("inbox");
    expect(parseHash("#/features/%E0%A4%A").screen).toBe("inbox");
    expect(parseHash("#/foo").screen).toBe("inbox");
    expect(parseHash("#/sessions").screen).toBe("inbox");
    expect(parseHash("#/sessions/a%20b").id).toBe("a b");
  });
});

describe("confirm, hints, palette", () => {
  it("marks a destructive confirm", async () => {
    const p = askConfirm("Stop it?", true);
    expect(confirmReq.value?.danger).toBe(true);
    confirmReq.value!.resolve(false);
    expect(await p).toBe(false);
    void askConfirm("Fine?");
    expect(confirmReq.value?.danger).toBe(false);
    confirmReq.value!.resolve(true);
  });

  it("keeps toasts with an action up for at least 6 s", () => {
    expect(toastMs("info")).toBe(2600);
    expect(toastMs("info", "#/activity")).toBeGreaterThanOrEqual(6000);
    expect(toastMs("error")).toBe(6000);
  });

  it("shows the [ ] tab hint on a feature page only", () => {
    expect(hintsFor("features", false)).toEqual([]);
    expect(hintsFor("features", true)).toEqual([["[ ]", "tab"]]);
  });

  it("lists page jumps and renders the describe row as an option", () => {
    expect(matchPages("sett").map((p) => p.id)).toEqual(["settings"]);
    expect(matchPages("")).toHaveLength(10);
    paletteOpen.value = true;
    const html = renderToString(<Palette />);
    paletteOpen.value = false;
    expect(html).toContain("Go to Settings");
    expect(html).toMatch(/role="option"[^>]*>(?:(?!<\/button>).)*Describe a feature or a fix/);
    expect(html).toContain('aria-expanded="true"');
  });
});

describe("aria-current", () => {
  it("is never the string false", () => {
    for (const hash of ["#/inbox", "#/river", "#/activity", "#/ops"]) {
      nav(hash);
      expect(renderToString(<App />)).not.toContain('aria-current="false"');
    }
  });
});
