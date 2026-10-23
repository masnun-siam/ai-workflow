import { useEffect, useMemo, useState } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { Button, Icon, Toaster } from '../components';
import { Palette } from '../palette/Palette';
import { DetailPanel } from '../panels/DetailPanel';
import { usePanel } from '../panels/PanelContext';
import { routes } from '../lib/routes';
import { useBrowserNotifier } from '../api/hooks';
import { useStart } from '../start/StartContext';
import { AwayBanner, OfflineBanner } from './Banners';
import { NAV, Rail, useInboxCount } from './Rail';
import { ShellCtx } from './ShellContext';
import { ShortcutsDialog, useGlobalShortcuts } from './shortcuts';
import { RepoSwitcher } from './RepoSwitcher';
import { useRepo } from './useRepo';
import { useAwayDocument } from './useAwayDocument';

const TITLES: [string, string][] = [
  ['/inbox', 'Inbox'], ['/features', 'Features'], ['/dispatches', 'Dispatches'], ['/activity', 'Activity'], ['/sessions', 'Session'], ['/settings', 'Settings'], ['/onboarding', 'Welcome'],
];

function Topbar({ openPalette }: { openPalette: () => void }) {
  const start = useStart();
  const { pathname } = useLocation();
  const title = TITLES.find(([p]) => pathname.startsWith(p))?.[1] ?? 'aiw';
  return (
    <div className="topbar">
      <span className="mob-only"><RepoSwitcher compact /></span>
      <h2 className="mob-only" style={{ fontSize: 16 }}>{title}</h2>
      <button type="button" className="btn grow" style={{ justifyContent: 'flex-start', color: 'var(--muted)', fontWeight: 500, maxWidth: 520 }} onClick={openPalette} aria-label="Search or jump to" aria-keyshortcuts="Meta+K Control+K">
        <Icon n="search" />
        <span className="grow ellipsis" style={{ textAlign: 'left' }}>Search or jump to…</span>
        <span className="kbd hide-sm">⌘K</span>
      </button>
      <span className="grow hide-sm" />
      <Button variant="primary" onClick={() => start.open()} aria-keyshortcuts="N">
        <Icon n="plus" />
        <span className="hide-sm">New</span>
        <span className="sr mob-only">New</span>
        <span className="kbd hide-sm" style={{ background: 'transparent', color: 'inherit', borderColor: 'currentColor', opacity: 0.6 }}>N</span>
      </Button>
    </div>
  );
}

function MobileNav() {
  const inbox = useInboxCount();
  const { link } = useRepo();
  const { pathname } = useLocation();
  const items = [...NAV.map((n) => ({ to: n.to, label: n.label, icon: n.icon, count: n.badge === 'inbox' ? inbox : 0 })), { to: routes.settings(), label: 'Settings', icon: 'sliders' as const, count: 0 }];
  return (
    <nav className="mob-nav" aria-label="Main">
      {items.map((n) => {
        const on = pathname.startsWith(n.to) || (n.to === routes.activity && pathname.startsWith('/sessions'));
        return (
          <Link key={n.to} to={link(n.to)} className={on ? 'on' : ''} aria-current={on ? 'page' : undefined} style={{ textDecoration: 'none' }}>
            <Icon n={n.icon} s={20} />
            {n.label}
            {n.count ? <span className="count" aria-label={`${n.count} need you`}>{n.count}</span> : null}
          </Link>
        );
      })}
    </nav>
  );
}

/** The frame: rail | (banners, top bar, page) | detail panel, plus the palette, shortcut sheet and toasts. */
export function Shell() {
  const [palette, setPalette] = useState(false);
  const [keys, setKeys] = useState(false);
  const inbox = useInboxCount();
  const panel = usePanel();
  const ctx = useMemo(() => ({ openPalette: () => setPalette(true), openShortcuts: () => setKeys(true) }), []);
  useEffect(() => {
    document.title = inbox ? `(${inbox}) aiw` : 'aiw';
  }, [inbox]);
  useAwayDocument();
  useBrowserNotifier();
  // The page scrolls inside .content, which the router keeps mounted: start each new page at the top.
  const { pathname } = useLocation();
  useEffect(() => { const c = document.getElementById('main-content'); if (c) c.scrollTop = 0; }, [pathname]);
  return (
    <ShellCtx.Provider value={ctx}>
      <GlobalKeys />
      <a className="skip" href="#main-content" onClick={(e) => { e.preventDefault(); document.getElementById('main-content')?.focus(); }}>Skip to content</a>
      <div className={`app${panel.target ? ' has-panel' : ''}`}>
        <Rail />
        <main className="main" id="main">
          <OfflineBanner />
          <AwayBanner />
          <Topbar openPalette={ctx.openPalette} />
          <div className="content" id="main-content" tabIndex={-1} style={{ outline: 'none' }}>
            <Outlet />
          </div>
        </main>
        <DetailPanel />
      </div>
      <MobileNav />
      {palette ? <Palette onClose={() => setPalette(false)} /> : null}
      <ShortcutsDialog open={keys} onClose={() => setKeys(false)} />
      <Toaster />
    </ShellCtx.Provider>
  );
}

function GlobalKeys() {
  useGlobalShortcuts();
  return null;
}
