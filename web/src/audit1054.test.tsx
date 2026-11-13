import { options, type VNode } from "preact";
import { renderToString } from "preact-render-to-string";
import { beforeAll, describe, expect, it } from "vitest";
import { createClient } from "./api/client";
import { useMockClient } from "./api/http";
import type { Dispatch, Lane } from "./api/types";
import { mockFetch } from "../mock/server";
import { App } from "./app/App";
import { AskForm } from "./components/AskForm";
import { SessionView } from "./components/SessionView";
import { dispatches, loadMany, sessionList } from "./state/data";
import { argRequired, baseName, cleanTitle, friendlyRef, frozenAt, inTab, laneSeconds, needsLanes, parseCost, parseMax, recentDispatches, runSummary, targetError } from "./state/dispatchView";
import { nav } from "./state/route";
import { startReq } from "./state/ui";
import { registry } from "./state/data";

const lane = (over: Partial<Lane> = {}): Lane => ({ key: "a/b#1", repo: "a/b", n: 1, title: "t", deps: [], stage: "implementing", pr: null, needs_you: null, held: null, gate: null,
  skip_reason: null, paused: false, paused_by: null, hold_merge: false, limited_until: null, started_at: 1000, ended_at: null, session: null,
  usage: { cost: 0, tokens: null, seconds: 5 }, stalled: null, ...over });
const disp = (over: Partial<Dispatch> = {}): Dispatch => ({ id: "d", epic: "a/b#9", title: "Epic: Payouts", state: "running", settings: {} as never, lanes: [lane()],
  totals: { lanes: 1, closed: 0, cost: 0 }, created_at: 1000, ended_at: null, ...over });

describe("dispatch list", () => {
  it("a cancelled dispatch is not in Needs you, a running one is", () => {
    const l = lane({ needs_you: "waiting on you" });
    expect(inTab(disp({ lanes: [l] }), "needs")).toBe(true);
    expect(inTab(disp({ state: "cancelled", lanes: [l] }), "needs")).toBe(false);
    expect(needsLanes(disp({ state: "done", lanes: [l] }))).toEqual([]);
  });
  it("All shows live dispatches and the last 14 days, and hides a cancelled duplicate of a newer run", () => {
    const now = 100 * 86400;
    const live = disp({ id: "live", created_at: 1 });
    const old = disp({ id: "old", state: "done", epic: "a/b#1", created_at: 1, ended_at: 2 });
    const fresh = disp({ id: "fresh", state: "done", epic: "a/b#2", created_at: now - 86400, ended_at: now - 3600 });
    const dupOld = disp({ id: "dup", state: "cancelled", epic: "a/b#2", created_at: now - 2 * 86400, ended_at: now - 2 * 86400 + 60 });
    expect(recentDispatches([live, old, fresh, dupOld], now).map((d) => d.id)).toEqual(["live", "fresh"]);
  });
  it("cleans titles and counts paused dispatches", () => {
    expect(cleanTitle("Epic: Payouts")).toBe("Payouts");
    expect(cleanTitle("Small changes: a, b")).toBe("a, b");
    expect(runSummary([disp(), disp({ state: "paused" }), disp({ state: "paused" }), disp({ state: "done" })])).toBe("1 running · 2 paused");
    expect(runSummary([disp({ state: "done" })])).toBe("0 running");
  });
  it("freezes lane timers at the last event, not the wall clock", () => {
    const d = disp({ state: "cancelled", ended_at: null, events: [{ at: 1500, lane: null, kind: "x", text: "y" }, { at: 1200, lane: null, kind: "x", text: "z" }] });
    expect(frozenAt(d)).toBe(1500);
    expect(laneSeconds(d, lane({ started_at: 1000 }))).toBe(500);
    expect(laneSeconds(disp(), lane())).toBe(5);
  });
});

describe("form validation", () => {
  it("At most at once is 1–10 and empty means unset, never 0", () => {
    expect(parseMax("")).toEqual({ ok: true, value: null });
    expect(parseMax("3")).toEqual({ ok: true, value: 3 });
    for (const bad of ["0", "11", "2.5", "x"]) expect(parseMax(bad).ok).toBe(false);
    expect(parseCost("0").ok).toBe(false);
    expect(parseCost("12.5")).toEqual({ ok: true, value: 12.5 });
  });
  it("validates the epic field inline", () => {
    expect(targetError("acme/app#12", false)).toBe("");
    expect(targetError("12", false)).toBe("");
    expect(targetError("twelve", false)).not.toBe("");
    expect(targetError("a/b#1, a/b#2", true)).toBe("");
    expect(targetError("a/b#1, 2", true)).not.toBe("");
  });
  it("treats a bracketed or empty args hint as optional", () => {
    expect(argRequired("<issue | epic>")).toBe(true);
    expect(argRequired("[--dry-run]")).toBe(false);
    expect(argRequired("")).toBe(false);
    expect(argRequired(undefined)).toBe(false);
  });
  it("names repos by their last folder, and shortens GitHub links", () => {
    expect(baseName("/Users/siam/code/setu")).toBe("setu");
    expect(friendlyRef("https://github.com/acme/app/issues/12")).toBe("acme/app#12");
    expect(friendlyRef("https://github.com/orgs/acme/projects/3/views/1")).toBe("acme · project 3");
  });
});

describe("rendered", () => {
  beforeAll(async () => {
    useMockClient(createClient(mockFetch));
    await loadMany(["status", "repos", "products", "settings", "registry", "inbox", "dispatches", "grinds", "sessions"]);
  });

  it("AskForm is keyed by the question id, so a new question starts with an empty draft", () => {
    const s = sessionList.value!.sessions.find((x) => x.pending_question)!;
    const keys: unknown[] = [];
    const prev = options.vnode;
    options.vnode = (v: VNode) => { if (v.type === AskForm) keys.push(v.key); prev?.(v); };
    try { renderToString(<SessionView s={s} />); } finally { options.vnode = prev; }
    expect(keys).toEqual([s.pending_question!.id]);
  });

  const startHtml = (args?: string) => {
    startReq.value = { step: registry.value.find((x) => x.id === "implement-issue")!, repo: "acme/wasensi-backend", args };
    nav("#/inbox");
    const html = renderToString(<App />);
    startReq.value = null;
    return html;
  };
  it("Start is disabled while a required argument is empty, and enabled once it is filled", () => {
    expect(startHtml()).toMatch(/<button type="submit" class="btn pri"[^>]*disabled[^>]*>Start</);
    expect(startHtml("12")).not.toMatch(/<button type="submit" class="btn pri"[^>]*disabled[^>]*>Start</);
  });
  it("Start has a command search", () => {
    expect(startHtml()).toContain('aria-label="Search commands"');
  });
});
