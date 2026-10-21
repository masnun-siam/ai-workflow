import { useEffect, useRef, useSyncExternalStore } from 'react';
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
  { keys: 'G then I / F / B / A / S', label: 'Inbox, Features, Board, Activity, Settings' },
  { keys: '?', label: 'Show this list' },
  { keys: 'Esc', label: 'Close the panel or dialog' },
  { keys: '⌘ Enter', label: 'Submit a form' },
];

// Screens register extra rows while mounted (the Board adds j/k/h/l), so the sheet lists exactly what works.
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

const typing = (t: EventTarget | null) => {
  const el = t as HTMLElement | null;
  return !!el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);
};
const overlayOpen = () => !!document.querySelector('[role=dialog],[role=alertdialog],[role=menu]');

/** Global keys (FR-5). None fires while typing in a field or while a dialog is open; Esc is handled by the dialogs and the panel. */
export function useGlobalShortcuts() {
  const navigate = useNavigate();
  const { search } = useLocation();
  const { openPalette, openShortcuts } = useShell();
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
      if (typing(e.target) || e.metaKey || e.ctrlKey || e.altKey || e.repeat) return;
      if (overlayOpen()) return;
      if (Date.now() - g.current < 900) {
        const dest = ({ i: routes.inbox, f: routes.features, b: routes.board, a: routes.activity, s: routes.settings() } as Record<string, string>)[e.key.toLowerCase()];
        g.current = 0;
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
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [navigate, search, openPalette, openShortcuts, start]);
}

export function ShortcutsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const rows = useSyncExternalStore((cb) => (subs.add(cb), () => subs.delete(cb)), () => snapshot);
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
