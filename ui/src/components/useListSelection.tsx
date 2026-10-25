import { useCallback, useEffect, useRef, useState } from 'react';
import { ignoreKey, useAction, useRegisterShortcuts, type ShortcutRow } from '../shell/shortcuts';
import './selection.css';

interface Sel {
  key: string;
  index: number;
}

/** Where the selection lands after the list changed: the same row if it is still there, else the row now at the same position, else none. */
export function nextSelection(prev: Sel | null, keys: string[]): Sel | null {
  if (!prev || keys.length === 0) return null;
  const at = keys.indexOf(prev.key);
  if (at >= 0) return { key: prev.key, index: at };
  const index = Math.min(prev.index, keys.length - 1);
  return { key: keys[index], index };
}

const ROWS: ShortcutRow[] = [
  { keys: 'J / K', label: 'Select next / previous row' },
  { keys: 'Enter', label: 'Open the selected row' },
];

/**
 * Keyboard selection for one list per page (FR-1..3). `keys` are the rows' stable keys in screen order; spread `rowProps(key)` on each row.
 * Wrap a row's buttons in `<KeyScope level="row" active={selected === key}>` so their keys work for the selected row only.
 * Pass `reset` (the repo, a filter) to clear the selection when it changes.
 */
export function useListSelection({ keys, onOpen, reset }: { keys: string[]; onOpen: (key: string) => void; reset?: unknown }) {
  const [sel, setSel] = useState<Sel | null>(null);
  const els = useRef(new Map<string, HTMLElement>());
  const latest = useRef({ keys, sel, onOpen });
  latest.current = { keys, sel, onOpen };
  const joined = keys.join('\n');

  useEffect(() => setSel((p) => nextSelection(p, latest.current.keys)), [joined]);
  useEffect(() => setSel(null), [reset]);
  useRegisterShortcuts(ROWS);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const { keys: ks, sel: cur } = latest.current;
      const dir = e.key === 'j' || e.key === 'ArrowDown' ? 1 : e.key === 'k' || e.key === 'ArrowUp' ? -1 : 0;
      if (!dir || !ks.length || ignoreKey(e)) return;
      e.preventDefault();
      const index = cur ? Math.min(Math.max(cur.index + dir, 0), ks.length - 1) : 0;
      if (cur && index === cur.index) return;
      setSel({ key: ks[index], index });
      const el = els.current.get(ks[index]);
      el?.focus({ preventScroll: true });
      el?.scrollIntoView?.({ block: 'nearest' });
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, []);

  const select = useCallback((key: string) => {
    const index = latest.current.keys.indexOf(key);
    if (index >= 0) setSel({ key, index });
  }, []);

  useAction(sel ? { key: 'Enter', label: 'Open the selected row', run: () => latest.current.onOpen(sel.key) } : null);

  const selected = sel?.key ?? null;
  const rowProps = (key: string) => ({
    ref: (el: HTMLElement | null) => void (el ? els.current.set(key, el) : els.current.delete(key)),
    tabIndex: selected === key ? 0 : -1,
    'data-selected': selected === key || undefined,
    onClick: () => select(key),
    onFocus: () => select(key),
  });
  return { selected, select, rowProps };
}
