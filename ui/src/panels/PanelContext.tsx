import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

export type PanelTarget = { kind: 'issue'; repo: string; n: number } | { kind: 'pr'; repo: string; n: number } | { kind: 'feature'; repo: string; slug: string };

interface PanelApi {
  target: PanelTarget | null;
  /** True when the last `open` came with `from` (a list following its selection): the panel keeps focus where it is. */
  follow: boolean;
  /** Open (or switch) the right-hand detail panel. Same panel from Board, Features, Inbox and the palette. `from` becomes the element `close()` focuses. */
  open: (t: PanelTarget, from?: Element) => void;
  close: () => void;
}
const Ctx = createContext<PanelApi>({ target: null, follow: false, open: () => {}, close: () => {} });

/** `const panel = usePanel(); panel.open({kind: 'issue', repo, n: 801}); panel.close()`. */
export const usePanel = () => useContext(Ctx);

export function PanelProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<PanelTarget | null>(null);
  const [follow, setFollow] = useState(false);
  const opener = useRef<Element | null>(null);
  const open = useCallback((t: PanelTarget, from?: Element) => {
    if (from) opener.current = from;
    else if (!opener.current) opener.current = document.activeElement;
    setFollow(!!from);
    setTarget(t);
  }, []);
  const close = useCallback(() => {
    setTarget(null);
    const el = opener.current as HTMLElement | null;
    opener.current = null;
    el?.focus?.();
  }, []);
  const value = useMemo(() => ({ target, follow, open, close }), [target, follow, open, close]);
  // Esc closes the panel, unless a dialog or menu is on top (Radix handles those itself).
  useEffect(() => {
    if (!target) return;
    const h = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      if (document.querySelector('[role=dialog],[role=alertdialog],[role=menu]')) return;
      close();
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [target, close]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
