import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { StartDialog } from './StartDialog';

/** What to pre-fill: a command id from COMMANDS, its argument (text, issue/PR number, path), a repo slug. */
export interface StartPreset {
  cmd?: string;
  arg?: string;
  repo?: string;
}
interface StartApi {
  isOpen: boolean;
  preset: StartPreset;
  /** Open the Start dialog (FR-22), optionally preset. */
  open: (p?: StartPreset) => void;
  close: () => void;
}
const Ctx = createContext<StartApi>({ isOpen: false, preset: {}, open: () => {}, close: () => {} });

/** `const start = useStart(); start.open({cmd: 'implement-issue', arg: '801'})`. */
export const useStart = () => useContext(Ctx);

export function StartProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ open: boolean; preset: StartPreset }>({ open: false, preset: {} });
  const open = useCallback((p: StartPreset = {}) => setState({ open: true, preset: p }), []);
  const close = useCallback(() => setState((s) => ({ ...s, open: false })), []);
  const value = useMemo(() => ({ isOpen: state.open, preset: state.preset, open, close }), [state, open, close]);
  return (
    <Ctx.Provider value={value}>
      {children}
      <StartDialog open={state.open} preset={state.preset} onClose={close} />
    </Ctx.Provider>
  );
}
