import { useEffect, useRef } from "preact/hooks";
import { Detail } from "../components/Detail";
import { Questions } from "../components/Questions";
import { ConfirmDialog, Help, Palette, StartDialog, Toast } from "../components/Overlays";
import { Btn, useFocusTrap } from "../components/ui";
import type { ComponentChildren } from "preact";
import { Inbox } from "../screens/Inbox";
import { Me } from "../screens/Me";
import { Ops } from "../screens/Ops";
import { Prd } from "../screens/Prd";
import { Releases } from "../screens/Releases";
import { River } from "../screens/River";
import { Runs } from "../screens/Runs";
import { SessionPage } from "../screens/SessionPage";
import { Settings } from "../screens/Settings";
import { currentView, loadMany, runsTab, status, load } from "../state/data";
import { HINTS, resolveKey } from "../state/keymap";
import { applyPrefs, prefs } from "../state/prefs";
import { visibleKeys } from "../state/refetch";
import { startRealtime } from "../state/realtime";
import { goScreen, route, SCREENS, startRouter } from "../state/route";
import { currentTarget, hasList, needCount, quickCount } from "../state/select";
import { confirmReq, connected, detailOpen, helpOpen, paletteOpen, startReq } from "../state/ui";
import { pct } from "../state/format";
import { targetActions } from "../components/Detail";
import { closeTopLayer, runCommand, screenActionList } from "./commands";

function Screen() {
  const r = route.value;
  if (r.screen === "runs" && r.id) return <SessionPage />;
  switch (r.screen) {
    case "river": return <River />;
    case "inbox": return <Inbox />;
    case "runs": return <Runs />;
    case "releases": return <Releases />;
    case "ops": return <Ops />;
    case "me": return <Me />;
    case "settings": return <Settings />;
    case "prd": return <Prd />;
  }
}

function Nav() {
  const cur = route.value.screen;
  return (
    <>
      {SCREENS.map(([id, name], i) => (
        <button key={id} type="button" class={`nv${cur === id ? " on" : ""}`} aria-current={cur === id ? "page" : undefined} onClick={() => { detailOpen.value = false; goScreen(id); }}>
          <kbd>{i + 1}</kbd>{name}{id === "inbox" && needCount.value > 0 && <span class="n" aria-label={`${needCount.value} need you`}>{needCount.value}</span>}
        </button>
      ))}
    </>
  );
}

function Brand() {
  return <div class="brand"><b>setu</b><span>সেতু</span></div>;
}

function StatusLine() {
  const st = status.value;
  const u = st?.usage[0];
  return (
    <>
      <span><i class={`status-dot${connected.value ? " on" : ""}`} />{connected.value ? "live" : "offline"}</span>
      <span>blubird {st?.blubird.installed ? st.blubird.version : "missing"}</span>
      {u && <span>{u.label} · {pct(u.five_hour)}</span>}
      <span>away {st?.away.active ? "on" : "off"}</span>
    </>
  );
}

function Banners() {
  const st = status.value;
  if (!st) return null;
  return (
    <>
      {!st.blubird.installed && <div class="banner" role="alert">blubird is not installed, so its skills are disabled. <Btn small onClick={() => goScreen("settings")}>Open settings</Btn></div>}
      {!st.gh.ok && <div class="banner bad" role="alert">GitHub CLI is not signed in{st.gh.error ? `: ${st.gh.error}` : ""}. Run <code>gh auth login</code> in a terminal, then reload.</div>}
    </>
  );
}

function Drawer({ children }: { children: ComponentChildren }) {
  const box = useRef<HTMLDivElement>(null);
  useFocusTrap(box, true);
  return (
    <>
      <div class="scrim" onClick={() => (detailOpen.value = false)} />
      <div class="drawer" ref={box} tabIndex={-1} role="dialog" aria-modal="true" aria-label="Detail">
        <div class="drawer-top"><Btn small onClick={() => (detailOpen.value = false)}>← Back</Btn><kbd class="wide-only">esc</kbd></div>
        {children}
      </div>
    </>
  );
}

const SPLIT_SCREENS = new Set(["river", "inbox", "runs", "ops"]);

export function App() {
  const r = route.value;
  const p = prefs.value;
  const split = p.layout === "split";
  const showSide = split && SPLIT_SCREENS.has(r.screen) && !r.id && (r.screen !== "runs" || runsTab.value === "sessions");
  const hints = [...(HINTS[r.screen] ?? []), ["1-7", "screens"], [":", "skill"], [".", "mode"], ["s", "look"], ["?", "keys"]] as [string, string][];

  useEffect(() => {
    applyPrefs(prefs.peek());
    const stopRoute = startRouter();
    const stopSse = startRealtime();
    void load("registry"); void load("settings");
    return () => { stopRoute(); stopSse(); };
  }, []);
  useEffect(() => { detailOpen.value = false; void loadMany(visibleKeys(currentView())); }, [r.screen, r.id, runsTab.value]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const typing = !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
      const cmd = resolveKey(
        { key: e.key, meta: e.metaKey, ctrl: e.ctrlKey, alt: e.altKey, typing },
        {
          screen: route.value.screen,
          overlay: !!confirmReq.value || !!startReq.value || paletteOpen.value || helpOpen.value,
          actions: [...targetActions(currentTarget.value), ...screenActionList()],
          quickOptions: quickCount.value,
          nav: hasList(route.value.screen),
        },
      );
      if (!cmd) return;
      if (cmd.t === "escape") {
        if (typing && !paletteOpen.value && !startReq.value) { el!.blur(); return; }
      }
      // Enter on a focused button must stay a click; list navigation never steals it
      if (cmd.t === "enter" && el && (el.tagName === "BUTTON" || el.tagName === "A")) return;
      if (cmd.t === "escape" && !closeTopLayer()) { runCommand(cmd); e.preventDefault(); return; }
      if (cmd.t === "escape") { e.preventDefault(); return; }
      e.preventDefault();
      runCommand(cmd);
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);

  const side = <Detail t={currentTarget.value} />;
  const main = <main class="main" id="main"><Banners />{!split && !(r.screen === "runs" && r.id) && <Questions />}<Screen /></main>;
  return (
    <div class="app">
      <a class="skip" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById("main")?.focus(); }}>Skip to content</a>
      {split ? (
        <>
          <header class="tabs"><Brand /><nav class="nav-wrap" aria-label="Main"><Nav /></nav><span class="st" style={{ display: "flex", gap: "12px" }}><StatusLine /></span></header>
          <div class="body">{main}{showSide && <aside class="side" aria-label="Detail">{side}</aside>}</div>
        </>
      ) : (
        <div class="body">
          <nav class="rail" aria-label="Main"><Brand /><Nav /><div class="railfoot"><StatusLine /></div></nav>
          {main}
        </div>
      )}
      <footer class="keys">{hints.map(([k, d]) => <span key={k + d}><kbd>{k}</kbd>{d}</span>)}</footer>
      {!split && detailOpen.value && currentTarget.value && (
        <Drawer>{side}</Drawer>
      )}
      {paletteOpen.value && <Palette />}
      {startReq.value && <StartDialog />}
      {helpOpen.value && <Help />}
      {confirmReq.value && <ConfirmDialog />}
      <Toast />
    </div>
  );
}
