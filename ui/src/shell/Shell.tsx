import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { Button, Icon, Toaster } from '../components';
import { Palette } from '../palette/Palette';
import { DetailPanel } from '../panels/DetailPanel';
import { usePanel } from '../panels/PanelContext';
import { ghTarget } from '../lib/ghLink';
import { routes } from '../lib/routes';
import { useBrowserNotifier } from '../api/hooks';
import { useStart } from '../start/StartContext';
import { AwayBanner, OfflineBanner } from './Banners';
import { NAV, NavPills, StatusMenu, useInboxCount } from './Rail';
import { ShellCtx } from './ShellContext';
import { ShortcutsDialog, useGlobalShortcuts } from './shortcuts';
import { PublicBadge } from './PublicBadge';
import { ScrollJump } from './ScrollJump';
import { RepoSwitcher } from './RepoSwitcher';
import { useRepo } from './useRepo';
import { useAwayDocument } from './useAwayDocument';

const TITLES: [string, string][] = [
  ['/inbox', 'Inbox'], ['/features', 'Features'], ['/changes', 'Small changes'], ['/new', 'New'], ['/dispatches', 'Dispatches'], ['/activity', 'Activity'], ['/sessions', 'Session'], ['/settings', 'Settings'], ['/onboarding', 'Welcome'],
];

/** The one bar across the top: repo, page links, search, what needs you, Away and New. */
function Topbar({ openPalette }: { openPalette: () => void }) {
  const start = useStart();
  const inbox = useInboxCount();
  const { link } = useRepo();
  const { pathname } = useLocation();
  const title = TITLES.find(([p]) => pathname.startsWith(p))?.[1] ?? 'aiw';
  return (
    <div className="topbar">
      <Link to={link(routes.features)} className="brand hide-sm" aria-label="aiw home">aiw</Link>
      <span className="hide-sm"><RepoSwitcher /></span>
      <span className="mob-only"><RepoSwitcher compact /></span>
      <h2 className="mob-only" style={{ fontSize: 16 }}>{title}</h2>
      <NavPills />
      <span className="grow" />
      <button type="button" className="btn search-btn" onClick={openPalette} aria-label="Search or jump to" aria-keyshortcuts="Meta+K Control+K">
        <Icon n="search" />
        <span className="hide-sm">Search</span>
        <span className="kbd hide-sm">⌘K</span>
      </button>
      <PublicBadge />
      {inbox ? <Link to={link(routes.inbox)} className="you-pill hide-sm"><i />{inbox} need you</Link> : null}
      <StatusMenu />
      <Button variant="primary" noAction onClick={() => start.open()} aria-keyshortcuts="N">
        <Icon n="plus" />
        <span className="hide-sm">New</span>
        <span className="sr mob-only">New</span>
        <span className="kbd hide-sm on-primary">N</span>
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

/** The frame: (banners, top bar, page) | detail panel, plus the palette, shortcut sheet and toasts. */
export function Shell() {
  const [palette, setPalette] = useState(false);
  const [keys, setKeys] = useState(false);
  const inbox = useInboxCount();
  const panel = usePanel();
  const switchers = useRef(new Set<{ trigger: () => HTMLElement | null; open: () => void }>());
  const ctx = useMemo(() => ({
    openPalette: () => setPalette(true),
    openShortcuts: () => setKeys(true),
    openRepoSwitcher: () => [...switchers.current].find((s) => (s.trigger()?.getClientRects().length ?? 0) > 0)?.open(),
    registerRepoSwitcher: (s: { trigger: () => HTMLElement | null; open: () => void }) => {
      switchers.current.add(s);
      return () => void switchers.current.delete(s);
    },
  }), []);
  useEffect(() => {
    document.title = inbox ? `(${inbox}) aiw` : 'aiw';
  }, [inbox]);
  useAwayDocument();
  useBrowserNotifier();
  // Issue and PR links anywhere open the side panel; modified clicks and `data-ext` buttons still go to GitHub.
  const { open } = panel;
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as Element).closest<HTMLAnchorElement>('a[href]:not([data-ext])');
      const target = a && ghTarget(a.href);
      if (!target) return;
      e.preventDefault();
      open(target);
    };
    document.addEventListener('click', onClick);
    return () => document.removeEventListener('click', onClick);
  }, [open]);
  // The page scrolls inside .content, which the router keeps mounted: start each new page at the top.
  const { pathname } = useLocation();
  useEffect(() => { const c = document.getElementById('main-content'); if (c) c.scrollTop = 0; }, [pathname]);
  return (
    <ShellCtx.Provider value={ctx}>
      <GlobalKeys />
      <a className="skip" href="#main-content" onClick={(e) => { e.preventDefault(); document.getElementById('main-content')?.focus(); }}>Skip to content</a>
      <div className={`app${panel.target ? ' has-panel' : ''}`}>
        <main className="main" id="main">
          <OfflineBanner />
          <AwayBanner />
          <Topbar openPalette={ctx.openPalette} />
          <div className="content" id="main-content" tabIndex={-1} style={{ outline: 'none' }}>
            <Outlet />
          </div>
          <ScrollJump />
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
