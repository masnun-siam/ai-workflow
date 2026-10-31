import * as PO from '@radix-ui/react-popover';
import { useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { needsYouCount, useAfkStart, useAfkStop, useDispatches, useInbox, useSessions, useSettings } from '../api/hooks';
import { Button, Icon, type IconName } from '../components';
import { clockText } from '../lib/format';
import { applyTheme, getTheme, type Theme } from '../lib/theme';
import { RUNNING_NOW } from '../lib/vocab';
import { routes } from '../lib/routes';
import { useShell } from './ShellContext';
import { useRepo } from './useRepo';

export const NAV: { to: string; label: string; icon: IconName; badge?: 'inbox' | 'running' | 'dispatch' }[] = [
  { to: routes.inbox, label: 'Inbox', icon: 'inbox', badge: 'inbox' },
  { to: routes.features, label: 'Features', icon: 'layers' },
  { to: routes.changes, label: 'Small changes', icon: 'tool' },
  { to: routes.dispatches, label: 'Dispatches', icon: 'bolt', badge: 'dispatch' },
  { to: routes.activity, label: 'Activity', icon: 'activity', badge: 'running' },
];

/** The number on the Inbox nav item: everything except Waiting (FR-7). */
export function useInboxCount() {
  return needsYouCount(useInbox().data?.items);
}

const PRESETS: [number, string][] = [[30, '30 min'], [60, '1 h'], [120, '2 h'], [240, '4 h']];

function AwayCard() {
  const afk = useSessions().data?.afk;
  const start = useAfkStart();
  const stop = useAfkStop();
  const [open, setOpen] = useState(false);
  const [end, setEnd] = useState('');
  const until = (mins: number) => Math.floor(Date.now() / 1000) + mins * 60;
  if (afk?.active && afk.until) {
    return (
      <div className="away-card">
        <div className="row"><Icon n="moon" /><b className="grow">Away until {clockText(afk.until)}</b></div>
        <p className="muted" style={{ fontSize: 12.5 }}>Answering every question (Opus when there is no recommendation), retrying failures. {afk.held} held for you.</p>
        <div className="row">
          <Button sm onClick={() => start.mutate(Math.min(afk.until! + 1800, Math.floor(Date.now() / 1000) + 86000))}>+30 min</Button>
          <Button sm variant="primary" onClick={() => stop.mutate()}>I'm back</Button>
        </div>
      </div>
    );
  }
  const go = (epoch: number) => {
    setOpen(false);
    start.mutate(epoch);
  };
  const endEpoch = () => {
    const [h, m] = end.split(':').map(Number);
    if (Number.isNaN(h)) return 0;
    const d = new Date();
    d.setHours(h, m || 0, 0, 0);
    if (d.getTime() <= Date.now()) d.setDate(d.getDate() + 1);
    return Math.floor(d.getTime() / 1000);
  };
  return (
    <div className="away-card" style={{ gap: 6 }}>
      <div className="row">
        <Icon n="moon" />
        <b className="grow">Away mode</b>
        <Button sm aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Cancel' : 'Go away'}</Button>
      </div>
      {open ? (
        <>
          <div className="row wrap" style={{ gap: 4 }}>
            {PRESETS.map(([m, l]) => <Button key={m} sm onClick={() => go(until(m))}>{l}</Button>)}
          </div>
          <form className="row" onSubmit={(e) => { e.preventDefault(); const t = endEpoch(); if (t) go(t); }}>
            <input className="f" type="time" aria-label="Away until" value={end} onChange={(e) => setEnd(e.target.value)} style={{ minHeight: 28, padding: '3px 8px' }} />
            <Button sm type="submit" disabled={!end}>Set</Button>
          </form>
        </>
      ) : (
        <p className="faint" style={{ fontSize: 12.5 }}>Claude keeps going without you and saves the rest.</p>
      )}
    </div>
  );
}

function Usage() {
  const data = useSessions().data;
  const cmds = useSettings().data?.commands ?? [];
  const usage = data?.usage ?? {};
  const limits = data?.limits ?? {};
  const names = [...new Set([...Object.keys(usage), ...Object.keys(limits)])];
  if (!names.length) return null;
  return (
    <div className="stack" style={{ gap: 8, padding: '0 10px' }}>
      {names.map((cmd) => {
        const label = cmds.find((c) => c.cmd === cmd || c.label === cmd)?.label ?? cmd;
        const u = usage[cmd];
        const until = limits[cmd]?.limited_until;
        const limited = !!until && until * 1000 > Date.now();
        const five = limited ? 100 : Math.round(u?.five_hour?.pct ?? 0);
        const seven = Math.round(u?.seven_day?.pct ?? 0);
        return (
          <div key={cmd} className="stack" style={{ gap: 4 }}>
            <div className="row" style={{ fontSize: 12 }}>
              <b className="grow ellipsis">{label}</b>
              {limited ? (
                <span style={{ color: 'var(--bad)', fontWeight: 600 }}>limited until {clockText(until!)}</span>
              ) : u?.error ? (
                <span className="faint" title={u.error}>usage unavailable</span>
              ) : (
                <span className="faint">5h {five}% · 7d {seven}%</span>
              )}
            </div>
            <div className={`meter ${five >= 100 ? 'full' : five >= 80 ? 'hot' : ''}`} role="img" aria-label={`${label} 5-hour usage ${five}%`}>
              <span style={{ width: `${Math.min(100, five)}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

const NEXT: Record<Theme, Theme> = { system: 'light', light: 'dark', dark: 'system' };
export function ThemeButton() {
  const [t, setT] = useState<Theme>(getTheme);
  const icon: IconName = t === 'light' ? 'sun' : t === 'dark' ? 'moon' : 'monitor';
  return (
    <Button variant="ghost" icon aria-label={`Theme: ${t}. Switch to ${NEXT[t]}`} title={`Theme: ${t}`} onClick={() => { applyTheme(NEXT[t]); setT(NEXT[t]); }}>
      <Icon n={icon} />
    </Button>
  );
}

/** The left rail: page links with their counts (needs-you in amber, running and dispatching quiet), then
    Away mode, plan usage, theme and keys at the foot. Hidden on phones, where MobileNav and StatusMenu take over. */
export function SideRail() {
  const inbox = useInboxCount();
  const running = (useSessions().data?.sessions ?? []).filter((s) => RUNNING_NOW.includes(s.outcome)).length;
  const dispatching = (useDispatches().data?.dispatches ?? []).filter((d) => d.state === 'running').length;
  const { openShortcuts } = useShell();
  const { link } = useRepo();
  const { pathname } = useLocation();
  return (
    <aside className="rail">
      <NavLink to={link(routes.inbox)} className="brand" aria-label="aiw home">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" aria-hidden="true"><path d="M3 12h4l3-8 4 16 3-8h4" /></svg>
        aiw
      </NavLink>
      <nav className="nav" aria-label="Main">
        {[...NAV, { to: routes.settings(), label: 'Settings', icon: 'sliders' as IconName, badge: undefined }].map((n) => {
          const count = n.badge === 'inbox' ? inbox : n.badge === 'running' ? running : n.badge === 'dispatch' ? dispatching : 0;
          const on = pathname === n.to || (n.to === routes.features && pathname.startsWith('/features')) || (n.to === routes.activity && pathname.startsWith('/sessions')) || (n.to === routes.dispatches && pathname.startsWith('/dispatches')) || (n.label === 'Settings' && pathname.startsWith('/settings'));
          return (
            <NavLink key={n.to} to={link(n.to)} className={`nav-a${on ? ' on' : ''}`} aria-current={on ? 'page' : undefined}>
              <Icon n={n.icon} />
              {n.label}
              {count ? <span className={`count${n.badge !== 'inbox' ? ' quiet' : ''}`} aria-label={`${count} ${n.badge === 'inbox' ? 'need you' : 'running'}`}>{count}</span> : null}
            </NavLink>
          );
        })}
      </nav>
      <div className="rail-foot">
        <AwayCard />
        <Usage />
        <div className="row" style={{ gap: 2 }}>
          <span className="grow faint" style={{ fontSize: 12.5, paddingLeft: 10 }}>Theme and keys</span>
          <ThemeButton />
          <Button variant="ghost" icon aria-label="Keyboard shortcuts" onClick={openShortcuts}><Icon n="help" /></Button>
        </div>
      </div>
    </aside>
  );
}

/** Away mode, usage, theme and the shortcut sheet, behind one top-bar button. */
export function StatusMenu() {
  const afk = useSessions().data?.afk;
  const { openShortcuts } = useShell();
  const away = !!(afk?.active && afk.until);
  return (
    <PO.Root>
      <PO.Trigger asChild>
        <button type="button" className={`btn${away ? ' you' : ' ghost'}`} aria-label={away ? `Away until ${clockText(afk!.until!)}. Away mode and usage` : 'Away mode and usage'}>
          <Icon n="moon" /><span className="hide-sm">{away ? `Away until ${clockText(afk!.until!)}` : 'Away'}</span>
        </button>
      </PO.Trigger>
      <PO.Portal>
        <PO.Content className="pop-c status-pop" align="end" sideOffset={8} collisionPadding={8}>
          <AwayCard />
          <Usage />
          <div className="row" style={{ gap: 2, borderTop: '1px solid var(--line)', paddingTop: 8 }}>
            <span className="grow muted" style={{ fontSize: 12.5, paddingLeft: 6 }}>Theme and keys</span>
            <ThemeButton />
            <Button variant="ghost" icon aria-label="Keyboard shortcuts" onClick={openShortcuts}><Icon n="help" /></Button>
          </div>
        </PO.Content>
      </PO.Portal>
    </PO.Root>
  );
}
