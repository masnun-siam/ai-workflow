import { createContext, useContext, useEffect, useMemo, useRef, useSyncExternalStore, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Button, Dialog } from '../components';
import { routes } from '../lib/routes';
import { useStart } from '../start/StartContext';
import { useShell } from './ShellContext';

export interface ShortcutRow {
  keys: string;
  label: string;
}
const BASE: ShortcutRow[] = [
  { keys: '⌘K', label: 'Search or jump anywhere' },
  { keys: 'N', label: 'Start something new' },
  { keys: 'G then I / F / D / A / S', label: 'Inbox, Features, Dispatches, Activity, Settings' },
  { keys: 'G then R', label: 'Switch repository' },
  { keys: '?', label: 'Show this list' },
  { keys: 'Esc', label: 'Close the panel or dialog' },
  { keys: '⌘ Enter', label: 'Submit a form' },
];

// Screens register extra rows while mounted, so the sheet lists exactly what works.
let extra: { id: number; rows: ShortcutRow[] }[] = [];
let seq = 0;
let snapshot: ShortcutRow[] = BASE;
const subs = new Set<() => void>();
const rebuild = () => {
  snapshot = [...BASE, ...extra.flatMap((e) => e.rows)];
  subs.forEach((f) => f());
};

/** `useRegisterShortcuts([{keys: 'J / K', label: 'Next / previous card'}])`: rows show in the sheet while the caller is mounted. Pass a module-level constant. */
export function useRegisterShortcuts(rows: ShortcutRow[]) {
  useEffect(() => {
    const id = ++seq;
    extra = [...extra, { id, rows }];
    rebuild();
    return () => {
      extra = extra.filter((e) => e.id !== id);
      rebuild();
    };
  }, [rows]);
}

/** The keys a button may take (FR-4), as `e.key.toLowerCase()` gives them. N, G, J, K, ?, [, ] and digits stay reserved. */
export type ActionKey = 'Enter' | 'a' | 'p' | 'm' | 'r' | 's' | 'e' | 't' | 'c' | 'o' | 'x';
const ACTION_KEYS: readonly string[] = ['Enter', 'a', 'p', 'm', 'r', 's', 'e', 't', 'c', 'o', 'x'];

export interface KeyAction {
  /** A function lets the palette read a button's current text when it opens. */
  label: string | (() => string);
  key?: ActionKey;
  run: () => void;
  disabled?: boolean;
  primary?: boolean;
}
type Level = 'page' | 'row' | 'panel';
export const LEVEL_RANK: Record<Level, number> = { page: 1, row: 2, panel: 3 };
interface Scope {
  level: Level;
  active: boolean;
  name?: string;
}
const ScopeCtx = createContext<Scope>({ level: 'page', active: true });

/** Wrap a page, panel or row: the actions inside register at its level, only while `active`. `name` is the row's name for the palette. */
export function KeyScope({ level, active, name, children }: { level: Level; active: boolean; name?: string; children: ReactNode }) {
  const value = useMemo(() => ({ level, active, name }), [level, active, name]);
  return <ScopeCtx.Provider value={value}>{children}</ScopeCtx.Provider>;
}

export interface RegisteredAction {
  label: string;
  key?: ActionKey;
  level: Level;
  name?: string;
  seq: number;
  primary: boolean;
  disabled: boolean;
  run: () => void;
}
interface Entry {
  seq: number;
  key?: ActionKey;
  level: Level;
  name?: string;
  primary: boolean;
  ref: { current: KeyAction | null };
}
let entries: Entry[] = [];
let actionsSnapshot: RegisteredAction[] = [];
let flushQueued = false;
// Many buttons register in one render: tell subscribers once per burst.
const flush = () => {
  flushQueued = false;
  actionsSnapshot = entries.flatMap((e) => {
    const a = e.ref.current;
    if (!a) return [];
    return [{
    label: typeof a.label === 'function' ? a.label() : a.label,
    key: e.key,
    level: e.level,
    name: e.name,
    seq: e.seq,
    primary: e.primary,
    disabled: !!a.disabled,
    run: () => e.ref.current?.run(),
    }];
  });
  subs.forEach((f) => f());
};
const scheduleFlush = () => {
  if (!flushQueued) {
    flushQueued = true;
    queueMicrotask(flush);
  }
};

/** `useAction({label: 'Merge', key: 'm', run})`: registers the action with the nearest KeyScope while mounted and active. `null` registers nothing. */
export function useAction(a: KeyAction | null) {
  const { level, active, name } = useContext(ScopeCtx);
  const ref = useRef(a);
  ref.current = a;
  const on = !!a && active;
  const key = a?.key;
  const primary = !!a?.primary;
  useEffect(() => {
    if (!on) return;
    const entry: Entry = { seq: ++seq, key, level, name, primary, ref };
    entries = [...entries, entry];
    scheduleFlush();
    return () => {
      entries = entries.filter((e) => e !== entry);
      scheduleFlush();
    };
  }, [on, key, primary, level, name]);
}

const subscribe = (cb: () => void) => (subs.add(cb), () => subs.delete(cb));
/** The registered actions with their `level`, `name` and `seq`, for the palette. */
export const useActions = () => useSyncExternalStore(subscribe, () => actionsSnapshot);

const typing = (t: EventTarget | null) => {
  const el = t as HTMLElement | null;
  return !!el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);
};
const overlayOpen = () => !!document.querySelector('[role=dialog],[role=alertdialog],[role=menu]');
/** FR-10: true when a single-key shortcut must not fire (typing, a dialog or menu open, a modifier held, key repeat). */
export const ignoreKey = (e: KeyboardEvent) => typing(e.target) || e.metaKey || e.ctrlKey || e.altKey || e.repeat || overlayOpen();

/** Panel beats row beats page, primary beats secondary, then the first registered. */
function winner(key: string) {
  return entries
    .filter((e) => e.key === key)
    .sort((a, b) => LEVEL_RANK[b.level] - LEVEL_RANK[a.level] || +b.primary - +a.primary || a.seq - b.seq)[0];
}

/** Global keys (FR-5). None fires while typing in a field or while a dialog is open; Esc is handled by the dialogs and the panel. */
export function useGlobalShortcuts() {
  const navigate = useNavigate();
  const { search } = useLocation();
  const { openPalette, openShortcuts, openRepoSwitcher } = useShell();
  const start = useStart();
  const g = useRef(0);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        openPalette();
        return;
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        const form = (e.target as HTMLElement | null)?.closest?.('form');
        if (form) {
          e.preventDefault();
          form.requestSubmit();
        }
        return;
      }
      if (ignoreKey(e)) return;
      if (Date.now() - g.current < 900) {
        const dest = ({ i: routes.inbox, f: routes.features, d: routes.dispatches, a: routes.activity, s: routes.settings() } as Record<string, string>)[e.key.toLowerCase()];
        g.current = 0;
        if (e.key.toLowerCase() === 'r') {
          e.preventDefault();
          openRepoSwitcher();
          return;
        }
        if (dest) {
          e.preventDefault();
          navigate({ pathname: dest, search });
          return;
        }
      }
      if (e.key === 'g') g.current = Date.now();
      else if (e.key === 'n') {
        e.preventDefault();
        start.open();
      } else if (e.key === '?') openShortcuts();
      else {
        const k = e.key === 'Enter' ? 'Enter' : e.key.toLowerCase();
        if (!ACTION_KEYS.includes(k)) return;
        if (k === 'Enter' && (e.target as HTMLElement | null)?.closest?.('button,a,summary,[role=button]')) return;
        const w = winner(k);
        if (!w) return;
        e.preventDefault();
        if (!w.ref.current?.disabled) w.ref.current?.run();
      }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [navigate, search, openPalette, openShortcuts, openRepoSwitcher, start]);
}

export function ShortcutsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const base = useSyncExternalStore(subscribe, () => snapshot);
  const actions = useActions();
  const keyed = actions.filter((a) => a.key).map((a) => ({ keys: a.key === 'Enter' ? 'Enter' : a.key!.toUpperCase(), label: a.label }));
  const rows = [...base, ...keyed].filter((r, i, all) => all.findIndex((o) => o.keys === r.keys && o.label === r.label) === i);
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()} title="Keyboard shortcuts" description="Shortcuts that work on this page." footer={<Button variant="primary" onClick={onClose}>Done</Button>}>
      <dl className="keys-grid" style={{ margin: 0 }}>
        {rows.map((r) => (
          <div key={r.keys + r.label} style={{ display: 'contents' }}>
            <dt><span className="kbd">{r.keys}</span></dt>
            <dd style={{ margin: 0 }}>{r.label}</dd>
          </div>
        ))}
      </dl>
    </Dialog>
  );
}
