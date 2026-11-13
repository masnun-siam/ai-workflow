import { submitAnswers } from "../components/AskForm";
import { targetActions, targetId, targetRound } from "../components/Detail";
import { emptyDraft } from "../state/answer";
import { me } from "../state/data";
import { exec } from "../state/exec";
import type { Cmd } from "../state/keymap";
import { LAYOUTS, LOOKS, MODES, next, prefs, setPref } from "../state/prefs";
import { goBack, goScreen, nav, route, setParam, type ScreenId } from "../state/route";
import { closeTopLayer } from "../state/layers";
import { currentTarget, hasList, listLength, inboxItems, stages } from "../state/select";
import { clamp, detailOpen, helpOpen, openCreate, paletteOpen, repoOpen, sel, setSel, toast } from "../state/ui";
import { releaseKey } from "../screens/Releases";
import { blubirdAction } from "../screens/settings/Blubird";
import type { Action } from "../api/types";

/** Actions bound to keys that belong to the screen, not the selected item. */
export const screenActionList = (): readonly Action[] => (route.value.screen === "me" ? (me.value?.actions ?? []) : []);

/** The screen Escape goes back to from a detail page: a feature page to Features, a dispatch to Dispatches, a session to Activity, the PRD view to Features. */
export function parentScreen(): ScreenId | null {
  const r = route.value;
  if (r.screen === "prd") return "features";
  return r.id && (r.screen === "features" || r.screen === "dispatches" || r.screen === "activity") ? r.screen : null;
}

export function runCommand(c: Cmd): void {
  const screen = route.value.screen;
  switch (c.t) {
    case "go": detailOpen.value = false; goScreen(c.screen); return;
    case "palette": paletteOpen.value = true; return;
    case "help": helpOpen.value = !helpOpen.value; return;
    case "escape": if (!closeTopLayer()) { const parent = parentScreen(); if (parent) goBack(parent); } return;
    case "new": openCreate(); return;
    case "repo": repoOpen.value = true; return;
    case "mode": setPref("mode", next(MODES, prefs.value.mode)); toast(`Mode: ${prefs.value.mode}`); return;
    case "look": setPref("look", next(LOOKS, prefs.value.look)); toast(`Look: ${prefs.value.look}`); return;
    case "layout": detailOpen.value = false; setPref("layout", next(LAYOUTS, prefs.value.layout)); toast(`Layout: ${prefs.value.layout}`); return;
    case "answer": {
      const r = targetRound(currentTarget.value);
      const label = r?.round.questions[0]?.options[c.index]?.label;
      if (r && label) { const d = emptyDraft(r.round); d[0] = { labels: [label], other: "" }; void submitAnswers(r.sessionId, r.round, d); }
      return;
    }
    case "action": {
      const a = [...targetActions(currentTarget.value), ...screenActionList()].find((x) => x.key === c.key);
      if (a) void exec(a, targetId(currentTarget.value));
      return;
    }
    case "move": {
      const s = sel.peek();
      if (screen === "river") {
        const st = stages.value;
        const stage = clamp(s.stage + c.dx, 0, st.length - 1);
        const card = clamp(c.dx ? s.card : s.card + c.dy, 0, Math.max(0, (st[stage]?.cards.length ?? 1) - 1));
        setSel({ stage, card });
      } else {
        const key = screen === "inbox" ? "inbox" : screen === "ops" ? "ops" : "runs"; // "runs" = the Activity session list
        const len = screen === "inbox" ? inboxItems.value.length : listLength(screen);
        setSel({ [key]: clamp(s[key] + c.dy, 0, Math.max(0, len - 1)) });
      }
      return;
    }
    case "enter": {
      const t = currentTarget.value;
      if (!t) return;
      const visible = detailOpen.value || prefs.value.layout === "split";
      if (screen === "activity" && t.kind === "session" && visible) { nav(`#/sessions/${t.session.id}`); return; }
      detailOpen.value = true;
      return;
    }
    case "screen": {
      if (screen === "releases") { releaseKey(c.key); return; }
      if (screen === "me") { const a = me.value?.actions.find((x) => x.key === c.key); if (a) void exec(a); return; }
      if (screen === "features" && route.value.id && (c.key === "[" || c.key === "]")) {
        const tabs = ["issues", "prd", "review", "sessions"];
        const cur = Math.max(0, tabs.indexOf(route.value.query.tab ?? ""));
        setParam("tab", tabs[(cur + (c.key === "]" ? 1 : tabs.length - 1)) % tabs.length]!, true);
        return;
      }
      if (screen === "settings") { if (c.key === "u") void blubirdAction("update"); else if (c.key === "i") void blubirdAction("install"); }
      return;
    }
  }
}
export { closeTopLayer, hasList };
