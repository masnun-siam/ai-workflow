import { submitAnswers } from "../components/AskForm";
import { targetActions, targetId, targetRound } from "../components/Detail";
import { emptyDraft } from "../state/answer";
import { me } from "../state/data";
import { exec } from "../state/exec";
import type { Cmd } from "../state/keymap";
import { LAYOUTS, LOOKS, MODES, next, prefs, setPref } from "../state/prefs";
import { goScreen, nav, route } from "../state/route";
import { currentTarget, hasList, listLength, inboxItems, stages } from "../state/select";
import { clamp, confirmReq, detailOpen, helpOpen, paletteOpen, repoOpen, sel, setSel, startReq, toast } from "../state/ui";
import { releaseKey } from "../screens/Releases";
import { runBlubird } from "../screens/settings/Blubird";
import type { Action } from "../api/types";

/** Actions bound to keys that belong to the screen, not the selected item. */
export const screenActionList = (): readonly Action[] => (route.value.screen === "me" ? (me.value?.actions ?? []) : []);

export function closeTopLayer(): boolean {
  if (confirmReq.value) { confirmReq.value.resolve(false); return true; }
  if (repoOpen.value) { repoOpen.value = false; return true; }
  if (startReq.value) { startReq.value = null; return true; }
  if (paletteOpen.value) { paletteOpen.value = false; return true; }
  if (helpOpen.value) { helpOpen.value = false; return true; }
  if (detailOpen.value) { detailOpen.value = false; return true; }
  return false;
}

export function runCommand(c: Cmd): void {
  const screen = route.value.screen;
  switch (c.t) {
    case "go": detailOpen.value = false; goScreen(c.screen); return;
    case "palette": paletteOpen.value = true; return;
    case "help": helpOpen.value = !helpOpen.value; return;
    case "escape": if (!closeTopLayer() && route.value.id) nav("#/activity"); return;
    case "new": paletteOpen.value = true; return;
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
      if (screen === "ops" && t.kind === "ops" && t.row.actions.length === 1) { void exec(t.row.actions[0]!); return; }
      const visible = detailOpen.value || prefs.value.layout === "split";
      if (screen === "activity" && t.kind === "session" && visible) { nav(`#/sessions/${t.session.id}`); return; }
      detailOpen.value = true;
      return;
    }
    case "screen": {
      if (screen === "releases") { releaseKey(c.key); return; }
      if (screen === "me") { const a = me.value?.actions.find((x) => x.key === c.key); if (a) void exec(a); return; }
      if (screen === "settings") { if (c.key === "u") void runBlubird("update"); else if (c.key === "i") void runBlubird("install"); }
      return;
    }
  }
}
export { hasList };
