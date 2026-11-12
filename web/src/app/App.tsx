import { useEffect, useRef } from "preact/hooks";
import { Detail } from "../components/Detail";
import { ConfirmDialog, Help, Palette, Toast } from "../components/Overlays";
import { CreateDialog, StartDialog } from "../components/Start";
import { interceptGitHubLinks, WorkPanel, workTarget } from "../components/WorkPanel";
import { CreateRepoDialog, createRepo, PublishDialog, publishRepo } from "../components/Repos";
import { Btn, useFocusTrap } from "../components/ui";
import type { ComponentChildren } from "preact";
import { Inbox } from "../screens/Inbox";
import { Me } from "../screens/Me";
import { Ops } from "../screens/Ops";
import { Prd } from "../screens/Prd";
import { Releases } from "../screens/Releases";
import { River } from "../screens/River";
import { Activity } from "../screens/Activity";
import { Changes } from "../screens/Changes";
import { Dispatches } from "../screens/Dispatches";
import { Features } from "../screens/Features";
import { Onboarding, Rail, Topbar } from "../components/Shell";
import { SessionPage } from "../screens/SessionPage";
import { Settings } from "../screens/Settings";
import { http } from "../api/http";
import { activityTab, mutate, chooseProduct, currentRepo, currentView, loadMany, repoList, repos, status, load } from "../state/data";
import { HINTS, resolveKey } from "../state/keymap";
import { applyPrefs, prefs } from "../state/prefs";
import { visibleKeys } from "../state/refetch";
import { startRealtime } from "../state/realtime";
import { goScreen, nav, route, startRouter } from "../state/route";
import { currentTarget, hasList, needCount, quickCount } from "../state/select";
import { confirmReq, connected, createOpen, detailOpen, helpOpen, paletteOpen, repoOpen, startReq } from "../state/ui";
import { targetActions } from "../components/Detail";
import { closeTopLayer, runCommand, screenActionList } from "./commands";

function Screen() {
  const r = route.value;
  if (r.screen === "activity" && r.id) return <SessionPage />;
  switch (r.screen) {
    case "river": return <River />;
    case "inbox": return <Inbox />;
    case "features": return <Features />;
    case "changes": return <Changes />;
    case "dispatches": return <Dispatches />;
    case "activity": return <Activity />;
    case "onboarding": return <Onboarding />;
    case "releases": return <Releases />;
    case "ops": return <Ops />;
    case "me": return <Me />;
    case "settings": return <Settings />;
    case "prd": return <Prd />;
  }
}

function Banners() {
  const st = status.value;
  if (!st) return null;
  return (
    <>
      {!connected.value && <div class="banner" role="status">Offline: reconnecting to setu… What you see may be out of date.</div>}
      {st.away.active && <div class="banner" role="status">Away mode is on: Claude answers what it can and holds the rest. <Btn small onClick={() => mutate(() => http.send("POST", "/api/away/stop", {}), "Welcome back", ["status", "inbox"])}>I'm back</Btn></div>}
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

const SPLIT_SCREENS = new Set(["river", "inbox", "activity", "ops"]);

/** Old aiw gate: every page but Settings goes to onboarding while no repo is registered. */
function useOnboardingGate() {
  const r = route.value;
  const none = !!repos.value && repoList.value.length === 0;
  useEffect(() => {
    if (none && r.screen !== "settings" && r.screen !== "onboarding") nav("#/onboarding", true);
  }, [none, r.screen]);
}

export function App() {
  const r = route.value;
  const p = prefs.value;
  const split = p.layout === "split";
  const showSide = split && SPLIT_SCREENS.has(r.screen) && !r.id && (r.screen !== "activity" || activityTab.value === "sessions");
  const hints = [...(HINTS[r.screen] ?? []), ["0-9", "pages"], ["g r", "repo"], ["n", "new"], ["⌘K", "search"], ["?", "keys"]] as [string, string][];
  useOnboardingGate();
  // The current repo picks the product River, Releases and Ops show.
  const repoProduct = repoList.value.find((x) => x.slug === currentRepo.value)?.product;
  useEffect(() => { if (repoProduct) chooseProduct(repoProduct); }, [repoProduct]);
  // River, Releases and Ops scope by the repo itself when it has no product, so a repo change (switcher or ?repo=) reloads them.
  const repoNow = currentRepo.value, reposReady = !!repos.value;
  useEffect(() => { if (repoNow && reposReady) { void load("river"); void load("releases"); void load("ops"); } }, [repoNow, reposReady]);
  useEffect(() => {
    const n = needCount.value;
    document.title = n ? `(${n}) setu` : "setu";
  }, [needCount.value]);

  useEffect(() => {
    applyPrefs(prefs.peek());
    const stopRoute = startRouter();
    const stopSse = startRealtime();
    const stopLinks = interceptGitHubLinks();
    void load("registry"); void load("settings");
    return () => { stopRoute(); stopSse(); stopLinks(); };
  }, []);
  useEffect(() => { detailOpen.value = false; repoOpen.value = false; workTarget.value = null; void loadMany(visibleKeys(currentView())); }, [r.screen, r.id, activityTab.value]);
  useEffect(() => { if (r.screen === "changes") void load("changes"); }, [r.query.only]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const typing = !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
      const cmd = resolveKey(
        { key: e.key, meta: e.metaKey, ctrl: e.ctrlKey, alt: e.altKey, typing },
        {
          screen: route.value.screen,
          overlay: !!confirmReq.value || !!startReq.value || paletteOpen.value || helpOpen.value || repoOpen.value || createOpen.value || !!workTarget.value || !!createRepo.value || !!publishRepo.value,
          actions: [...targetActions(currentTarget.value), ...screenActionList()],
          quickOptions: quickCount.value,
          nav: hasList(route.value.screen),
        },
      );
      if (!cmd) return;
      if (cmd.t === "escape") {
        if (typing && !paletteOpen.value && !startReq.value && !createOpen.value) { el!.blur(); return; }
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
  const main = <main class="main" id="main"><Topbar /><Banners /><Screen /></main>;
  return (
    <div class="app">
      <a class="skip" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById("main")?.focus(); }}>Skip to content</a>
      <div class="body">
        <Rail />
        {main}
        {split && showSide && <aside class="side" aria-label="Detail">{side}</aside>}
      </div>
      <footer class="keys">{hints.map(([k, d]) => <span key={k + d}><kbd>{k}</kbd>{d}</span>)}</footer>
      {!split && detailOpen.value && currentTarget.value && (
        <Drawer>{side}</Drawer>
      )}
      {paletteOpen.value && <Palette />}
      {startReq.value && <StartDialog />}
      {createOpen.value && <CreateDialog />}
      {workTarget.value && <WorkPanel />}
      {createRepo.value && <CreateRepoDialog />}
      {publishRepo.value && <PublishDialog />}
      {helpOpen.value && <Help />}
      {confirmReq.value && <ConfirmDialog />}
      <Toast />
    </div>
  );
}
