import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

export type PanelTarget = { kind: 'issue'; repo: string; n: number } | { kind: 'pr'; repo: string; n: number };

interface PanelApi {
  target: PanelTarget | null;
  /** Open (or switch) the right-hand detail panel. Same panel from Board, Features, Inbox and the palette. */
  open: (t: PanelTarget) => void;
  close: () => void;
}
const Ctx = createContext<PanelApi>({ target: null, open: () => {}, close: () => {} });

/** `const panel = usePanel(); panel.open({kind: 'issue', repo, n: 801}); panel.close()`. */
export const usePanel = () => useContext(Ctx);

export function PanelProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<PanelTarget | null>(null);
  const opener = useRef<Element | null>(null);
  const open = useCallback((t: PanelTarget) => {
    if (!opener.current) opener.current = document.activeElement;
    setTarget(t);
  }, []);
  const close = useCallback(() => {
    setTarget(null);
    const el = opener.current as HTMLElement | null;
    opener.current = null;
    el?.focus?.();
  }, []);
  const value = useMemo(() => ({ target, open, close }), [target, open, close]);
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
